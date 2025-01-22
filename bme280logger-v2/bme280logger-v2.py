#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bme280logger.py
---------------
Data logger for BME280 sensors on a Raspberry Pi, with:
 - Automatic sensor detection & reading (including reboots via relay).
 - 5 consecutive failures => 1 hour cooldown logic.
 - Optional calibration for relative humidity (via thpcaldb).
 - Graph generation (Temperature, RH, Pressure) using raw or calibrated RH.
 - Data retention in memory, logging to CSV, and optional live console output.

Created on Wed Aug 21 12:17:22 2024

@author: Kim Miikki
"""

import argparse
import board
import math
import matplotlib.pyplot as plt
import numpy as np
import os
import random
import re
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from sys import exit
from time import sleep, perf_counter

# ------------------------------
# IMPORTS FROM LOCAL MODULES
# ------------------------------
from relays import Relay         # relay.py
from logfile import DataLog, ErrorLog
from bme280 import readBME280All
from thpcaldb import Calibration, parse_zone_numbers

# Global print formatting for NumPy
np.set_printoptions(suppress=True, formatter={'float_kind': '{:f}'.format})

# ------------------------------
# GLOBAL CONSTANTS & DEFAULTS
# ------------------------------
rows_limit = 3600 * 24 * 60
"""
The rows_limit variable is the upper limit for data rows stored in memory. It
is calculated as follows:
    memory of one row of data * 3600 * 24 * 60 = 373248000 (356 MB),
    where the memory consumption for one data row is 72 bytes for two sensors,
    In this calculation, the smallest interval is selected, which is 1 s.
    The memory consumption of one data row is obtained from the non-transposed
    memdata Numpy array with the np.nbytes function, e.g. memdata[0].nbytes
This row limitation guarantees sufficient memory for each measurement for
60 days, when the data acquisition interval is 1 s.
"""

COOLDOWN_DURATION = 30.0  # 1 hour in seconds

# Program version
version = 2.0

# Relay pins
relay_pin_list = [21, 20]
relay_failures = [26]
nc_high_mode = True

# BME280 & logging defaults
interval = 1.0         # Measurement interval (seconds)
retention_time = 7     # Data retention time in memory (days)
is_nan_logging = False # If False, skip logging lines that contain NaNs
is_simulation = False  # Simulate random sensor failures

# Directory handling
base_dir = ""
is_subdir = False
is_prefix = False

# Graph flags
is_basic_figures = False
is_combo_figures = False

# We can calibrate up to 2 sensors (or 1 if you only have 1 physically)
rh_cal = [None, None]  # each element is either None or a Calibration object

decimals = 2  # how many decimals to round sensor data

# Probability of simulated sensor failure
pfail = 0.01
stop_threads = True
thr = None
relay_fail = None

# Measurement data in memory
memdata = None
data_cols = 3
sensor_count = 0

# Data log object
log = None

# Error log object
error_log = None

# Time-tracking dictionary
time_dict = {"timestamp": 0, "time": 0, "N": 0}

# Hard-coded sensor reboot logic
trials = 3
delay = 0.1

# For handling Ctrl+C
disable_halt = False

# ------------------------------
# ARGUMENT PARSING
# ------------------------------

def parse_arguments():
    """
    Reads command-line arguments with argparse and sets relevant globals.
    """
    global retention_time
    global interval
    global base_dir
    global is_subdir
    global is_prefix
    global is_simulation
    global is_nan_logging
    global is_basic_figures
    global is_combo_figures
    global rh_cal

    parser = argparse.ArgumentParser()
    parser.add_argument("-d", type=str, 
        help="File base directory (default = current working directory)",
        required=False)
    parser.add_argument("-s", action="store_true", 
        help="Enable datetime subdirectories",
        required=False)
    parser.add_argument("-ts", action="store_true", 
        help="Add timestamp as prefix for files",
        required=False)
    parser.add_argument("-i", type=float, 
        help="Measurement interval in seconds (default=1.0)",
        required=False)
    parser.add_argument("-nan", action="store_true", 
        help="Log failed readings as NaN (default=False)",
        required=False)
    parser.add_argument("-r", type=int, 
        help=f"Data retention period in memory in days (default={retention_time})",
        required=False)
    parser.add_argument("-b", action="store_true", 
        help="Create basic graphs for single sensor data",
        required=False)
    parser.add_argument("-c", action='store_true', 
        help="Create graphs for two sensors (pair, difference, etc.)",
        required=False)
    parser.add_argument("-a", action='store_true', 
        help="Create all graphs (both basic & combo) for up to 2 sensors",
        required=False)
    parser.add_argument("-simfail", action="store_true", 
        help="Simulate random sensor failures with relays",
        required=False)
    parser.add_argument("-cal", type=str, 
        help="Specify calibrated sensors as -cal zone,num1,num2. Example: -cal A,1,2",
        required=False)

    args = parser.parse_args()

    # Base directory
    if args.d is not None:
        # global base_dir
        base_dir = args.d.strip()

    if args.s:
        # global is_subdir
        is_subdir = True

    if args.ts:
        # global is_prefix
        is_prefix = True

    # Interval
    if args.i is not None:
        if args.i < 1:
            print('\nInterval set to 1 second (minimum).')
            # global interval
            interval = 1.0
        else:
            interval = args.i

    # NaN logging
    if args.nan:
        # global is_nan_logging
        is_nan_logging = True

    # Retention time
    if args.r is not None:
        if args.r < 1:
            print('Illegal value. Data retention period must be > 0.')
            sys.exit(1)
        else:
            #global retention_time
            retention_time = args.r

    # Basic, combo, or all graphs
    if args.b:
        # global is_basic_figures
        is_basic_figures = True

    if args.c:
        # global is_combo_figures
        is_combo_figures = True

    if args.a:
        is_basic_figures = True
        is_combo_figures = True

    # Simulation of failures
    if args.simfail:
        # global is_simulation
        if len(relay_failures) > 0:
            is_simulation = True
        else:
            print("No relay pin for failures simulation assigned. Exiting.")
            sys.exit(1)

    # Calibration
    if args.cal:
        zone, num1, num2 = parse_zone_numbers(args.cal)
        if zone:
            # Build path to the calibration DB in the same dir as this script (optional usage)
            script_dir = os.path.dirname(__file__)
            db_file = os.path.join(script_dir, "calibration.db")

            if num1:
                rh_cal[0] = Calibration(db_file, zone, num1)
                if rh_cal[0] is not None:
                    print(f"Sensor {zone}{num1} calibration in use for sensor #1.")
                else:
                    print(f"No calibration found for {zone}{num1} (sensor #1).")
            if num2:
                rh_cal[1] = Calibration(db_file, zone, num2)
                if rh_cal[1] is not None:
                    print(f"Sensor {zone}{num2} calibration in use for sensor #2.")
                else:
                    print(f"No calibration found for {zone}{num2} (sensor #2).")
            if num1 or num2:
                print("")


# ------------------------------
# HELPER FUNCTIONS
# ------------------------------

def get_sensors() -> list:
    """
    Scans the I2C bus (via board.I2C) for 0x76 or 0x77 addresses
    and returns a list of found device addresses (ints).
    """
    #import board
    i2c = board.I2C()
    while not i2c.try_lock():
        pass
    try:
        addrs = [hex(device_address) for device_address in i2c.scan()]
        print("I2C addresses found:", addrs)
    finally:
        i2c.unlock()

    devices = []
    if "0x76" in addrs:
        devices.append(0x76)
    if "0x77" in addrs:
        devices.append(0x77)
    return devices


def display_info():
    print(f'Interval: {interval} s')
    curdir = os.getcwd()
    print('\nCurrent directory:')
    print(curdir)
    print('\nPress Ctrl+C to end logging.\n')


def auto_scale(times: np.array, diff_time=False):
    """
    Auto-scales time axis for plotting (seconds, minutes, hours, or days)
    based on the range of data.
    Returns scaled times array and the unit label.
    """
    if diff_time:
        start = times[0]
        end = times[-1]
        secs = abs(end - start)
    else:
        secs = times[-1]

    factor = 5
    if secs <= factor * 60:
        unit = 's'
        divisor = 1
    elif secs <= factor * 3600:
        unit = 'min'
        divisor = 60
    elif secs <= factor * 3600 * 24:
        unit = 'h'
        divisor = 3600
    else:
        unit = 'd'
        divisor = 3600 * 24

    if divisor > 1:
        times = times / divisor
    return times, unit


def simulate_failure():
    """
    Thread routine for artificially opening a relay channel
    with probability = pfail, to simulate sensor failure.
    """
    global pfail
    global stop_threads
    global relay_fail
    while True:
        if stop_threads:
            break
        rnd = random.random()
        if rnd < pfail:
            relay_fail.ch_open(1)  # For example, open channel #1
        sleep(0.1)


def get_sec_fractions(resolution=5) -> float:
    """
    Returns the fractional part of the current second, 
    rounded to 'resolution' decimal places.
    Useful for waiting until the next full second to start logging.
    """
    now = datetime.now()
    return round(now.timestamp() % 1, resolution)


def format_data(tdata: dict, data: np.array) -> str:
    """
    Formats a single row of numeric data for CSV/logging.
    tdata is like {"timestamp": datetime_obj, "time": float, "N": int}
    data is the numeric sensor array to be appended.

    The returned string is comma-separated, for example:
       "YYYY-mm-dd HH:MM:SS.ffffff, 1691187262.123456, 42.3, 100, <data0>, <data1>, ..."
    """
    global decimals
    dt = tdata["timestamp"]
    t_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    ts = str(dt.timestamp())
    runtime = tdata["time"]
    measnum = tdata["N"]

    out_list = [
        t_str,
        ts,
        f"{runtime:.1f}",
        str(measnum)
    ]
    for value in data:
        val_rounded = round(value, decimals)
        out_list.append(f"{val_rounded:.{decimals}f}")

    return ", ".join(out_list)


# ------------------------------
# GRAPHING FUNCTIONS
# ------------------------------

def create_graph_1(xs: np.array, ys: np.array,
                   xlabel: str, ylabel: str, full_path: str):

    fig = plt.figure()
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.plot(xs, ys, color='k')
    plt.ticklabel_format(useOffset=False, style='plain')
    xmin = math.floor(xs[0])
    xmax = xs[-1]
    # Filter out NaNs to get min & max
    ys_nz = ys[np.isfinite(ys)]
    if len(ys_nz) > 0:
        ymin = ys_nz.min()
        ymax = ys_nz.max()
        plt.xlim(xmin, xmax)
        plt.ylim(ymin, ymax)
    plt.grid()
    fig.tight_layout()
    plt.savefig(full_path, dpi=300, bbox_inches='tight')
    plt.close(fig)


def create_graph_2(xs: np.array, ys1: np.array, ys2: np.array,
                   legend1: str, legend2: str,
                   xlabel: str, ylabel: str, full_path: str):

    fig = plt.figure()
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.plot(xs, ys1, color='k', label=legend1)
    plt.plot(xs, ys2, color='0.33', label=legend2)
    plt.ticklabel_format(useOffset=False, style='plain')
    xmin = math.floor(xs[0])
    xmax = xs[-1]
    ys1_nz = ys1[np.isfinite(ys1)]
    ys2_nz = ys2[np.isfinite(ys2)]
    if len(ys1_nz) > 0 and len(ys2_nz) > 0:
        ymin = min(ys1_nz.min(), ys2_nz.min())
        ymax = max(ys1_nz.max(), ys2_nz.max())
        plt.xlim(xmin, xmax)
        plt.ylim(ymin, ymax)
    plt.grid()
    plt.legend(loc=0)
    fig.tight_layout()
    plt.savefig(full_path, dpi=300, bbox_inches='tight')
    plt.close(fig)


def create_graph_combo(xs: np.array, ys1: np.array, ys2: np.array,
                       legend1: str, legend2: str,
                       xlabel: str,
                       ylabel1: str, ylabel2: str,
                       color1: str, color2: str,
                       full_path: str):

    fig, ax1 = plt.subplots()
    plt.xlabel(xlabel)
    ax1.set_ylabel(ylabel1)
    ax1.plot(xs, ys1, color=color1, label=legend1)
    xmin = math.floor(xs[0])
    xmax = xs[-1]
    ys1_nz = ys1[np.isfinite(ys1)]
    if len(ys1_nz) > 0:
        ymin = ys1_nz.min()
        ymax = ys1_nz.max()
        ax1.set_xlim(xmin, xmax)
        ax1.set_ylim(ymin, ymax)
    ax1.grid(color="tab:gray", linestyle="--")
    ax2 = ax1.twinx()
    ax2.set_ylabel(ylabel2)
    ax2.plot(xs, ys2, color=color2, label=legend2)
    ys2_nz = ys2[np.isfinite(ys2)]
    if len(ys2_nz) > 0:
        ymin2 = ys2_nz.min()
        ymax2 = ys2_nz.max()
        ax2.set_ylim(ymin2, ymax2)
    plt.ticklabel_format(useOffset=False)
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax2.legend(lines + lines2, labels + labels2, loc=0)
    fig.tight_layout()
    plt.savefig(full_path, dpi=300, bbox_inches='tight')
    plt.close(fig)


# ------------------------------
# SIGNAL HANDLER
# ------------------------------

def SignalHandler_SIGINT(SignalNumber, Frame):
    """
    Handle Ctrl+C to exit gracefully, generate final figures, etc.
    """
    global disable_halt
    global relay_fail
    global memdata
    global log
    global sensor_count

    if disable_halt:
        return

    print('\nTermination requested.')
    if is_simulation:
        global thr
        global stop_threads
        stop_threads = True
        thr.join()
        sleep(0.1)

    # If we have no data or only 1 row, skip
    if memdata is None or memdata.ndim == 1:
        exit(0)

    # Transpose
    memdata_t = memdata.T
    xs = memdata_t[1]  # time row
    xs, unit = auto_scale(xs)
    x_label = f"Time ({unit})"

    base_path = log.dir_path
    prefix = f"{log.dt_part}-" if log.ts_prefix else ""

    if True in [is_basic_figures, is_combo_figures]:
        print("\nGenerating figures:")

    # Identify T/H/P rows in the transposed array
    #  - row 0 => wallclock time
    #  - row 1 => run time
    #  - row 2 => measurement count
    #  - row 3 => t1, row 4 => h1, row 5 => p1, row 6 => t2, row 7 => h2, row 8 => p2, etc.
    #
    # After raw T/H/P for sensor_count sensors, we may have calibration columns:
    #   - If sensor 0 is calibrated => next column
    #   - If sensor 1 is also calibrated => next column after that
    #

    # figure out which row we want for humidity:
    #  either raw or calibration, depending on rh_cal[i]

    rh_indexes = get_rh_indexes(memdata_t, sensor_count, rh_cal)
    rh_labels  = get_rh_labels(sensor_count, rh_cal)

    t_indexes = [(3 + i * 3) for i in range(sensor_count)]
    p_indexes = [(3 + i * 3 + 2) for i in range(sensor_count)]

    # ------------------------------
    # BASIC GRAPHS
    # ------------------------------
    if is_basic_figures:
        print("- basic graphs")
        for i in range(sensor_count):
            # Temperature
            create_graph_1(
                xs, memdata_t[t_indexes[i]],
                x_label, f"Temperature{i+1} (°C)",
                f"{base_path}{prefix}fig{i+1}-single-t.png"
            )
            # Humidity (raw or cal)
            create_graph_1(
                xs, memdata_t[rh_indexes[i]],
                x_label, rh_labels[i],
                f"{base_path}{prefix}fig{i+1}-single-h.png"
            )
            # Pressure
            create_graph_1(
                xs, memdata_t[p_indexes[i]],
                x_label, f"Pressure{i+1} (hPa)",
                f"{base_path}{prefix}fig{i+1}-single-p.png"
            )

    # ------------------------------
    # COMBO GRAPHS (if 2 sensors)
    # ------------------------------
    if sensor_count == 2 and is_combo_figures:
        print("- difference graphs")

        # T2 - T1
        t_diff21 = memdata_t[t_indexes[1]] - memdata_t[t_indexes[0]]
        create_graph_1(
            xs, t_diff21,
            x_label, "T2 - T1 (°C)",
            f"{base_path}{prefix}fig-diff-t21.png"
        )

        # RH2 - RH1
        rh_diff21 = memdata_t[rh_indexes[1]] - memdata_t[rh_indexes[0]]
        create_graph_1(
            xs, rh_diff21,
            x_label, f"{rh_labels[1]} - {rh_labels[0]}",
            f"{base_path}{prefix}fig-diff-rh21.png"
        )

        # p2 - p1
        p_diff21 = memdata_t[p_indexes[1]] - memdata_t[p_indexes[0]]
        create_graph_1(
            xs, p_diff21,
            x_label, "p2 - p1 (hPa)",
            f"{base_path}{prefix}fig-diff-p21.png"
        )

        print("- pair graphs")
        # Pair T
        create_graph_2(
            xs,
            memdata_t[t_indexes[0]], memdata_t[t_indexes[1]],
            "t1", "t2",
            x_label, "Temperature (°C)",
            f"{base_path}{prefix}fig-pair-t12.png"
        )
        # Pair RH
        create_graph_2(
            xs,
            memdata_t[rh_indexes[0]], memdata_t[rh_indexes[1]],
            rh_labels[0], rh_labels[1],
            x_label, "RH% (%)",
            f"{base_path}{prefix}fig-pair-rh12.png"
        )
        # Pair p
        create_graph_2(
            xs,
            memdata_t[p_indexes[0]], memdata_t[p_indexes[1]],
            "p1", "p2",
            x_label, "Pressure (hPa)",
            f"{base_path}{prefix}fig-pair-p12.png"
        )

        print("- combined graphs")
        create_graph_combo(
            xs,
            memdata_t[t_indexes[0]], memdata_t[rh_indexes[0]],
            "t1", rh_labels[0],
            x_label,
            "Temperature (°C)", "RH% (%)",
            "r", "b",
            f"{base_path}{prefix}fig1-combo-trh.png"
        )
        create_graph_combo(
            xs,
            memdata_t[t_indexes[1]], memdata_t[rh_indexes[1]],
            "t2", rh_labels[1],
            x_label,
            "Temperature (°C)", "RH% (%)",
            "r", "b",
            f"{base_path}{prefix}fig2-combo-trh.png"
        )

    exit(0)


# ------------------------------
# GRAPHING SUPPORT FOR (CAL vs RAW) HUMIDITY
# ------------------------------

def get_rh_indexes(memdata_t: np.ndarray, sensor_count: int, rh_cal_list: list):
    """
    Returns a list of row indices in 'memdata_t' (transposed) for 
    the humidity data of each sensor. If sensor i is calibrated (rh_cal_list[i] != None),
    we pick the calibration column; otherwise, we pick the raw humidity column.
    
    Layout in transposed array (rows):
      row 0 => DateTime
      row 1 => run time
      row 2 => measurement count
      row 3 => sensor 1 temp
      row 4 => sensor 1 hum
      row 5 => sensor 1 pres
      row 6 => sensor 2 temp
      row 7 => sensor 2 hum
      row 8 => sensor 2 pres
      ...
      row (3 + i*3 + 1) => sensor i's raw humidity
    Then after all raw columns, calibration columns for each sensor that has calibration
    in the order that they appear.
    """

    # base index for raw data (T/H/P) => first sensor T is row 3
    raw_start = 3
    # total raw columns => sensor_count * 3
    cal_base = raw_start + sensor_count * 3

    # We'll figure out how many calibration columns we've used so far
    # to find the correct offset.
    rh_rows = [None] * sensor_count
    cal_count_used = 0

    for i in range(sensor_count):
        if rh_cal_list[i] is not None:
            # has calibration => offset from cal_base
            rh_rows[i] = cal_base + cal_count_used
            cal_count_used += 1
        else:
            # raw humidity => raw_start + i*3 + 1
            rh_rows[i] = raw_start + i * 3 + 1

    return rh_rows


def get_rh_labels(sensor_count: int, rh_cal_list: list):
    """
    Returns a list of label strings for each sensor's humidity:
      either "RHcal{i}%" if calibrated, or "RH{i}%".
    """
    labels = []
    for i in range(sensor_count):
        if rh_cal_list[i] is not None:
            labels.append(f"RHcal{i+1}% (%)")
        else:
            labels.append(f"RH{i+1}% (%)")
    return labels


# ------------------------------
# DATA LOGGING / STORAGE HELPERS
# ------------------------------

def read_and_calibrate_sensor_data(
    address,
    relay_obj,
    sensor_index,
    rh_cal_list,
    trials,
    delay,
    is_relays,
    is_simulation,
    errors,
    count
):
    """
    Attempts to read from one BME280 sensor. If reading fails, tries rebooting
    up to 'trials' times. If calibration is present for sensor_index, applies it
    to the RH value.

    Returns:
      (success_flag, temperature, humidity, pressure, calibrated_hum, updated_errors)
    """
    
    global error_log
    
    i = 0
    while True:
        try:
            t_, p_, h_ = readBME280All(address)  # (temp °C, pressure hPa, humidity %)
            # If calibration is available
            if rh_cal_list[sensor_index]:
                h_cal = rh_cal_list[sensor_index].get_calibrated_value(h_)
                # Round inside here if you like, but we do final rounding in format_data
            else:
                h_cal = None
            return True, t_, h_, p_, h_cal, errors

        except:
            if i < trials and is_relays:
                # Attempt sensor reboot
                terr = datetime.now().timestamp()
                if errors == 0:
                    # first error => create error log object
                    error_log = ErrorLog(
                        log.dir_path, "sensor_failures", "log", log.dt_part, log.ts_prefix
                    )
                msg = f"Unable to read sensor {hex(address)}. Reboot {i+1}/{trials}"
                if error_log:
                    error_log.write(terr, count, msg)
                print(msg)
                # Turn off sensor
                relay_obj.all_open()
                sleep(delay)
                # Turn on sensor
                if is_simulation:
                    relay_fail.all_close()
                relay_obj.all_close()
                errors += 1
                i += 1
                sleep(delay)
            else:
                # fail
                return False, np.nan, np.nan, np.nan, None, errors


def build_and_store_row(
    memdata,
    count,
    t,
    tp0,
    sensor_values,
    sensor_cals,
    log,
    is_nan_logging,
    max_rows
):
    """
    Builds a row of data (time, sensor readings, calibrations),
    appends it to 'memdata', and writes to log if not all NaN (unless is_nan_logging=True).

    sensor_values: [temp1, hum1, pres1, temp2, hum2, pres2, ...]
    sensor_cals:   [humCal1, humCal2, ...] (None if no calibration)
    """
    # If all sensor_values are NaN and we do NOT want to log them => skip
    if (np.isnan(sensor_values).all()) and (not is_nan_logging):
        return memdata

    # Time
    tp_cur = perf_counter()
    row = [
        t.timestamp(),         # absolute wallclock in float
        (tp_cur - tp0),       # run time in seconds
        count
    ]

    # Add sensor raw data
    row.extend(sensor_values)
    # Add calibrations
    for h_cal in sensor_cals:
        if h_cal is None:
            row.append(np.nan)
        else:
            row.append(h_cal)

    # Append to memdata
    if count == 1:
        memdata = np.array(row)
    else:
        memdata = np.vstack([memdata, row])

    # Data retention
    if len(memdata) > max_rows:
        memdata = memdata[1:, :]

    # Write row to log file
    # We place raw data + calibration into a single array for logging
    combined = np.array(sensor_values, dtype=float)
    for h_cal in sensor_cals:
        combined = np.append(combined, h_cal if h_cal is not None else np.nan)

    time_dict["timestamp"] = t
    time_dict["time"] = tp_cur - tp0
    time_dict["N"] = count

    out_line = format_data(time_dict, combined)
    log.write(out_line)

    return memdata


def print_data_line_to_screen(t, tp0, count, sensor_values, sensor_cals):
    """
    Prints a shortened line of data to screen. If a sensor is calibrated, 
    that humidity is displayed instead of raw. 
    """
    # We'll build a partial array: [temp1, humOrCal1, p1, temp2, humOrCal2, p2, ...]
    out_vals = []
    for i in range(0, len(sensor_values), 3):
        t_ = sensor_values[i]
        h_ = sensor_values[i+1]
        p_ = sensor_values[i+2]
        s_idx = i // 3
        if sensor_cals[s_idx] is not None:
            # override the raw humidity
            h_ = sensor_cals[s_idx]
        out_vals.extend([t_, h_, p_])

    # Format
    arr = np.array(out_vals, dtype=float)
    time_dict["timestamp"] = t
    time_dict["time"] = perf_counter() - tp0
    time_dict["N"] = count
    line = format_data(time_dict, arr)
    # For screen brevity, replace the decimal portion of the second column:
    line_short = re.sub(r"\..*?,.*?,", ",", line, count=1)
    print(line_short)


# ------------------------------
# MAIN
# ------------------------------

def main():
    global memdata
    global sensor_count
    global log
    global decimals
    global relay_fail
    global stop_threads
    global thr
    global disable_halt
    global is_combo_figures

    print(f"BME280 data logger v. {version} - Kim Miikki 2024\n")

    # 1) Parse arguments
    parse_arguments()

    # 2) Relay setup
    if len(relay_pin_list) > 0:
        is_relays = True
        r = Relay(relay_pin_list, nc_high=nc_high_mode)
    else:
        is_relays = False
        r = None

    # 3) Simfail
    if is_simulation:
        relay_fail = Relay(relay_failures, nc_high=nc_high_mode)
        sleep(0.1)
        random.seed(1)
        thr = threading.Thread(target=simulate_failure)
        stop_threads = False

    # 4) Reboot sensors once
    print("Initializing sensor(s).\n")
    for _ in range(2):
        r.all_toggle()
        sleep(0.1)

    # 5) Attempt to locate sensors
    i = 1
    sensors_list = []
    while True:
        sensors_list = get_sensors()
        if len(sensors_list) > 0:
            # Check if we can read them
            is_ok = True
            for address in sensors_list:
                try:
                    readBME280All(address)
                    print(f"Sensor {hex(address)}: PASS")
                except:
                    print(f"Unable to read {hex(address)}!")
                    is_ok = False
                    break
            if is_ok:
                break
        if i < 2:
            # Try toggling again
            r.all_toggle()
            sleep(0.5)
            r.all_toggle()
            i += 1
        else:
            print("\nNo functional BME280 sensors found. Program terminated.")
            sys.exit()

    sensor_count = len(sensors_list)
    if sensor_count == 1 and is_combo_figures:
        print("\nOnly one sensor found => disabling combo figures.\n")
        # global is_combo_figures
        is_combo_figures = False

    display_info()

    # 6) Ctrl+C => signal handler
    signal.signal(signal.SIGINT, SignalHandler_SIGINT)

    # 7) Compute max_rows for data retention
    max_rows_calc = int(retention_time * 24 * 3600 / interval)
    if max_rows_calc > rows_limit:
        max_rows_calc = rows_limit
        new_retention = max_rows_calc * interval / (24 * 3600)
        print("Retention time was too large => adjusted to "
              f"{new_retention:.2f} days\n")

    max_rows = max_rows_calc

    # 8) Wait until next full second
    while get_sec_fractions() != 0:
        pass

    # 9) Start logging
    tp0 = perf_counter()
    tstart = datetime.now().timestamp()
    # create DataLog object
    log = DataLog(tstart, base_dir, "thp", "csv", is_subdir, is_prefix)

    if is_simulation:
        thr.start()

    count = 1
    errors = 0
    disable_halt = True

    # 10) For the "1 hour after 5 fails" logic
    consecutive_failures = [0] * sensor_count
    cooldown_until = [0] * sensor_count

    # --- Print CSV header (once) ---
    print_header_with_calibration(sensor_count, rh_cal, log)

    # MAIN LOOP
    while True:
        t_now = datetime.now()
        # tp_cur = perf_counter()

        sensor_values = []
        sensor_cals   = []
        sensor_ok = [False] * sensor_count

        # Loop sensors
        for s_idx, address in enumerate(sensors_list):
            now_time = time.time()

            # Check if sensor is in cooldown
            if now_time < cooldown_until[s_idx]:
                # skip reading => store NaNs
                sensor_values.extend([np.nan, np.nan, np.nan])
                sensor_cals.append(None)
                # Also ensure the relay is open => powered off
                r.ch_open(s_idx + 1)
                continue
            else:
                # <--- WE JUST LEFT COOL-DOWN (if it was set before).
                # If consecutive_failures[s_idx] was >=5, reset to 0 now.
                if consecutive_failures[s_idx] >= 5:
                    consecutive_failures[s_idx] = 0
                # close (power on) this sensor
                r.ch_close(s_idx + 1)           

            # read sensor
            success, t_, h_, p_, h_cal, errors = read_and_calibrate_sensor_data(
                address=address,
                relay_obj=r,
                sensor_index=s_idx,
                rh_cal_list=rh_cal,
                trials=trials,
                delay=delay,
                is_relays=is_relays,
                is_simulation=is_simulation,
                errors=errors,
                count=count
            )
            sensor_values.extend([t_, h_, p_])
            sensor_cals.append(h_cal)

            if success:
                sensor_ok[s_idx] = True
                consecutive_failures[s_idx] = 0
                cooldown_until[s_idx] = 0
            else:
                consecutive_failures[s_idx] += 1
                if consecutive_failures[s_idx] >= 5:
                    # 1 hour cooldown
                    cooldown_until[s_idx] = now_time + COOLDOWN_DURATION
                    r.ch_open(s_idx + 1)
                    print(
                        f"Sensor {hex(address)} => 5 consecutive fails. "
                        f"Cooldown until {datetime.fromtimestamp(cooldown_until[s_idx])}."
                    )

        # If all sensors work, reset everything
        if all(sensor_ok):
            for si in range(sensor_count):
                consecutive_failures[si] = 0
                cooldown_until[si] = 0

        # Store row + log
        memdata = build_and_store_row(
            memdata=memdata,
            count=count,
            t=t_now,
            tp0=tp0,
            sensor_values=sensor_values,
            sensor_cals=sensor_cals,
            log=log,
            is_nan_logging=is_nan_logging,
            max_rows=max_rows
        )

        # Print to screen if we haven't suppressed
        disable_halt = True
        if not (np.isnan(sensor_values).all() and not is_nan_logging):
            print_data_line_to_screen(t_now, tp0, count, sensor_values, sensor_cals)
        disable_halt = False

        # Wait for next interval
        tp_end = perf_counter()
        wait_time = count * interval - (tp_end - tp0)
        if wait_time > 0:
            sleep(wait_time)
        count += 1


def print_header_with_calibration(sensor_count, rh_cal, log):
    """
    Prints and logs the CSV header row, taking into account that if 
    sensor i is calibrated, we will have an extra column at the end for it.
    """
    # Screen header
    screen_header = ["Datetime", "Timestamp", "Time (s)", "Measurement"]
    for i in range(sensor_count):
        n = i + 1
        # We'll show e.g. t1, RHcal1, p1 if calibration is present
        if rh_cal[i] is not None:
            screen_header.append(f"t{n} (°C)")
            screen_header.append(f"RHcal{n}% (%)")
            screen_header.append(f"p{n} (hPa)")
        else:
            screen_header.append(f"t{n} (°C)")
            screen_header.append(f"RH{n}% (%)")
            screen_header.append(f"p{n} (hPa)")

    out_screen = ", ".join(screen_header)
    # Shorten second column for screen
    out_screen = re.sub(r",[^,]*,", ",", out_screen, count=1)
    print(out_screen)

    # File header -> raw T/H/P for each sensor, then appended calibration columns
    file_header = ["Datetime", "Timestamp", "Time (s)", "Measurement"]
    for i in range(sensor_count):
        n = i + 1
        file_header.append(f"t{n} (°C)")
        file_header.append(f"RH{n}% (%)")
        file_header.append(f"p{n} (hPa)")

    # Then columns for calibrations
    for i in range(sensor_count):
        if rh_cal[i] is not None:
            file_header.append(f"RHcal{i+1}% (%)")

    log.write(file_header)


# ------------------------------
# ENTRY POINT
# ------------------------------

if __name__ == "__main__":
    main()
