#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bme280logger-v2.py
---------------
Data logger for BME280 sensors on a Raspberry Pi, with:
 - Automatic sensor detection & reading (including reboots via relay).
 - 5 consecutive failures => 1 hour cooldown logic.
 - Optional calibration for multiple sensor measurements (Temperature, Relative Humidity, Pressure) via thpcaldb.
 - Graph generation (Temperature, RH, Pressure) using raw or calibrated values.
 - Data retention in memory, logging to CSV, and optional live console output.

Updated to support multiple calibration types per sensor.
Calibration columns (in CSV and on-screen) are dynamically added based on which calibrations are available.
For example, if only RH calibration exists for sensor 1, and Temperature plus RH for sensor 2, 
the header might be: RHcal1% (%), Tcal2 (°C), RHcal2% (%)

Created on Wed Aug 21 12:17:22 2024 (updated 2025)
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
from smbus2 import SMBus   # <-- already available in OS images
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

# --- BME280 register addresses ---
CTRL_MEAS = 0xF4           # measurement control
STATUS    = 0xF3           # bit 3 (0x08) = measuring
RESET_REG = 0xE0
RESET_CMD = 0xB6           # soft-reset command

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

COOLDOWN_DURATION = 3600.0  # 1 hour in seconds

# Program version
version = 2.2

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

# Up to 2 sensors can be calibrated.
# Each element is either None or a Calibration object that holds a dict of calibrations.
sensor_cals = [None, None]
# This global will later hold, per sensor, a list of available calibration types.
sensor_cal_types = []
# Disable sensor plots as default
is_plot_calibration = False

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

# Data logging start time
tstart = 0

# Initialize sensor variables
zone = ""
num1 = -1
num2 = -1

# ------------------------------
# ARGUMENT PARSING
# ------------------------------

def parse_arguments():
    """
    Reads command-line arguments with argparse and sets relevant globals.
    """
    global retention_time, interval, base_dir, is_subdir, is_prefix
    global is_simulation, is_nan_logging, is_basic_figures, is_combo_figures
    global is_plot_calibration, sensor_cals
    global zone, num1, num2

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
    parser.add_argument("-p", action="store_true", 
        help="Plot calibration graphs",
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
        
    if args.p:
        is_plot_calibration = True

    # Simulation of failures
    if args.simfail:
        # global is_simulation
        if len(relay_failures) > 0:
            is_simulation = True
        else:
            print("No relay pin for failures simulation assigned. Exiting.")
            sys.exit(1)

    # Calibration argument processing:
    if args.cal:
        zone, num1, num2 = parse_zone_numbers(args.cal)
        if zone:
            # Build path to the calibration DB in the same dir as this script.
            script_dir = os.path.dirname(__file__)
            db_file = os.path.join(script_dir, "calibration.db")

            if num1:
                sensor_cals[0] = Calibration(db_file, zone, num1)
                if sensor_cals[0] is not None:
                    print(f"Sensor {zone}{num1} calibrations in use for sensor #1. Available types: {list(sensor_cals[0]._cal_data.keys())}")
                else:
                    print(f"No calibration found for {zone}{num1} (sensor #1).")
            if num2:
                sensor_cals[1] = Calibration(db_file, zone, num2)
                if sensor_cals[1] is not None:
                    print(f"Sensor {zone}{num2} calibrations in use for sensor #2. Available types: {list(sensor_cals[1]._cal_data.keys())}")
                else:
                    print(f"No calibration found for {zone}{num2} (sensor #2).")
            if num1 or num2:
                print("")


# ------------------------------
# HELPER FUNCTIONS
# ------------------------------

def trigger_forced_measure(addr):
    """
    Put BME280 at *addr* into FORCED mode, wait until the conversion
    finishes (<10 ms with default oversampling), then return True.
    Returns False if sensor doesn’t respond.
    """
    try:
        with SMBus(1) as bus:
            reg = bus.read_byte_data(addr, CTRL_MEAS)
            reg = (reg & 0xFC) | 0x01          # set mode bits to 01 = FORCED
            bus.write_byte_data(addr, CTRL_MEAS, reg)
            t0 = time.time()
            while bus.read_byte_data(addr, STATUS) & 0x08:   # measuring?
                if time.time() - t0 > 0.05:                  # >50 ms → timeout
                    return False
                time.sleep(0.003)
        return True
    except OSError:
        return False


def soft_reset(addr):
    """Send Bosch soft-reset (0xB6) and wait 3 ms.  Returns True if ACKed."""
    try:
        with SMBus(1) as bus:
            bus.write_byte_data(addr, RESET_REG, RESET_CMD)
        time.sleep(0.003)
        return True
    except OSError:
        return False


def get_sensors() -> list:
    """
    Scans the I2C bus (via board.I2C) for 0x76 or 0x77 addresses and returns a list of found device addresses.
    """
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
    global pfail, stop_threads, relay_fail
    while True:
        if stop_threads:
            break
        if random.random() < pfail:
            relay_fail.ch_open(1)
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
    out_list = [t_str, ts, f"{runtime:.1f}", str(measnum)]
    for value in data:
        val_rounded = round(value, decimals)
        out_list.append(f"{val_rounded:.{decimals}f}")
    return ", ".join(out_list)


# Write a log file of the THP logging
def write_calibration_log(start_time, end_time, interval, sensor_cals, sensor_count, log_dir, zone, num1, num2):
    """
    Writes a calibration log file before generating graphs.
    """
    start_time_dt = datetime.fromtimestamp(start_time) if isinstance(start_time, float) else start_time
    end_time_dt = datetime.fromtimestamp(end_time) if isinstance(end_time, float) else end_time
    
    log_filename = f"thp-{start_time_dt.strftime('%Y%m%d_%H%M%S')}.log"
    log_path = os.path.join(log_dir, log_filename)
    duration = end_time_dt - start_time_dt
    
    with open(log_path, "w") as log_file:
        log_file.write("=== BME280 Data Logging Report ===\n\n")
        log_file.write(f"Start Time: {start_time_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.write(f"End Time:   {end_time_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.write(f"Duration:   {str(duration)}\n")
        log_file.write(f"Measurement Interval: {interval} seconds\n\n")
        log_file.write(f"Number of Sensors: {sensor_count}\n\n")
        
        has_calibration = any(sensor_cals)
        if has_calibration:
            log_file.write("--- Calibration Data ---\n")
            for i in range(sensor_count):
                if sensor_cals[i]:
                    sensor_num = num1 if i == 0 else num2
                    log_file.write(f"Sensor {i+1} (Zone {zone}, Number {sensor_num}):\n")
                    for cal_type, params in sensor_cals[i]._cal_data.items():
                        log_file.write(f"  - {cal_type} Calibration:\n")
                        slope = round(params['slope'], 4)
                        constant = round(params['const'], 4)
 
                        # Default length of 1.0012 is on left 1
                        l1 = len(str(slope).split(".")[0]) - 1
                        l2 = len(str(constant).split(".")[0]) - 1
                       
                        log_file.write(f"      - Slope:    {' ' * (l2 - l1)}{slope}\n")
                        log_file.write(f"      - Constant: {' ' * (l1 - l2)}{constant}\n")
                        log_file.write(f"      - cal_id: {params['cal_id']}\n")
                    log_file.write("\n")
        
        log_file.write("--- Summary ---\n")
        log_file.write(f"Log Directory: {log_dir}\n")
        log_file.write(f"Calibration Directory: {os.path.join(log_dir, 'cal')}\n\n")
        log_file.write("--- Notes ---\n")
        if has_calibration:
            log_file.write("- Calibration values applied to logged data.\n")
            log_file.write("- Relative Humidity values clamped between 0% and 100%.\n")
            log_file.write("- If calibration was unavailable for a sensor, raw values were used.\n")
        else:
            log_file.write("- No calibration data was applied; raw sensor values were logged.\n")
        log_file.write("- Data stored in CSV format with timestamps.\n\n")
        log_file.write("=== End of Log ===\n")


# ------------------------------
# GRAPHING FUNCTIONS (unchanged)
# ------------------------------
def create_graph_1(xs: np.array, ys: np.array, xlabel: str, ylabel: str, full_path: str):
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


def create_graph_2(xs: np.array, ys1: np.array, ys2: np.array, legend1: str, legend2: str,
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
                       legend1: str, legend2: str, xlabel: str,
                       ylabel1: str, ylabel2: str, color1: str, color2: str,
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


def plot_calibration_graphs():
    """
    Generates calibration plots if calibration data is available.
    """
    print("Generating calibration plots...")
    cal_dir = os.path.join(base_dir if base_dir else os.getcwd(),"cal")
    if not os.path.exists(cal_dir):
        os.makedirs(cal_dir)
    
    base_path = os.path.join(os.getcwd(), cal_dir)
    prefix = f"{log.dt_part}-" if log.ts_prefix else ""
    
    memdata_t = memdata.T
    xs = memdata_t[1]  # time row
    xs, unit = auto_scale(xs)
    x_label = f"Time ({unit})"
    
    cal_indices = {}
    raw_indices = {}
    col_idx = 3 + sensor_count * 3  # Start after raw sensor data
    
    for i in range(sensor_count):
        if sensor_cals[i]:
            for meas in ["Temperature", "Relative Humidity", "Pressure"]:
                if meas in sensor_cal_types[i]:
                    cal_indices[(i, meas)] = col_idx
                    col_idx += 1
        raw_indices[(i, "Temperature")] = 3 + i * 3
        raw_indices[(i, "Relative Humidity")] = 4 + i * 3
        raw_indices[(i, "Pressure")] = 5 + i * 3
    
    for (i, meas), cal_idx in cal_indices.items():
        filename = f"fig-cal-{meas.lower().replace(' ', '-')}{i+1}.png"
        create_graph_1(
            xs, memdata_t[cal_idx],
            x_label, f"{meas} (°C)",
            os.path.join(base_path, prefix + filename)
        )
    
    for (i, meas), cal_idx in cal_indices.items():
        raw_idx = raw_indices.get((i, meas))
        if raw_idx is not None:
            filename = f"fig-cal-compare-{meas.lower().replace(' ', '-')}{i+1}.png"
            create_graph_2(
                xs, memdata_t[cal_idx], memdata_t[raw_idx],
                f"{meas} Calibrated", f"{meas} Raw",
                x_label, f"{meas} (°C)",
                os.path.join(base_path, prefix + filename)
            )
    
    if sensor_count == 2 and all(sensor_cals):
        for meas in ["Temperature", "Relative Humidity", "Pressure"]:
            if (0, meas) in cal_indices and (1, meas) in cal_indices:
                filename = f"fig-cal-pair-{meas.lower().replace(' ', '-')}.png"
                create_graph_2(
                    xs, memdata_t[cal_indices[(0, meas)]], memdata_t[cal_indices[(1, meas)]],
                    f"{meas} Sensor 1", f"{meas} Sensor 2",
                    x_label, f"{meas} (°C)",
                    os.path.join(base_path, prefix + filename)
                )


# ------------------------------
# SIGNAL HANDLER
# ------------------------------
def SignalHandler_SIGINT(SignalNumber, Frame):
    global disable_halt, relay_fail, memdata, log, sensor_count, is_plot_calibration
    global sensor_cals
    global start
    global zone, num1, num2
    
    if disable_halt:
        return
    
    disable_halt=True
    print('\nTermination requested.')
    if is_simulation:
        global thr, stop_threads
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

    end_time = datetime.now()
    write_calibration_log(tstart, end_time, interval, sensor_cals, sensor_count, log.dir_path, zone, num1, num2)

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

    t_indexes = [(3 + i * 3) for i in range(sensor_count)]
    rh_indexes = [(3 + i * 3 + 1) for i in range(sensor_count)]
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
                x_label, f"Relative Humidity {i+1} (RH%)",
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
            x_label, "RH2% - RH1%",
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
            "RH1%", "RH2%",
            x_label, "Relative Humidity (%)",
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
            "T1", "RH1%",
            x_label,
            "Temperature (°C)", "RH% (%)",
            "r", "b",
            f"{base_path}{prefix}fig1-combo-trh.png"
        )
        create_graph_combo(
            xs,
            memdata_t[t_indexes[1]], memdata_t[rh_indexes[1]],
            "T2", "RH2%",
            x_label,
            "Temperature (°C)", "RH% (%)",
            "r", "b",
            f"{base_path}{prefix}fig2-combo-trh.png"
        )

    if is_plot_calibration and any(sensor_cals):
        plot_calibration_graphs()

    exit(0)


# ------------------------------
# CALIBRATION-ENABLED HEADER & DATA FUNCTIONS
# ------------------------------
def print_screen_header(sensor_count, sensor_cal_types):
    """
    Prints a one-line header for screen output.
    For each sensor, prints three columns: Temperature, Relative Humidity, and Pressure.
    For each measurement, if calibration exists for that type, use the calibrated header label,
    otherwise use the raw value header label.
    """
    header = ["Datetime", "Timestamp", "Time (s)", "Measurement"]
    for i in range(sensor_count):
        n = i + 1
        # Temperature
        if "Temperature" in sensor_cal_types[i]:
            header.append(f"Tcal{n} (°C)")
        else:
            header.append(f"t{n} (°C)")
        # Relative Humidity
        if "Relative Humidity" in sensor_cal_types[i]:
            header.append(f"RHcal{n}% (%)")
        else:
            header.append(f"RH{n}% (%)")
        # Pressure
        if "Pressure" in sensor_cal_types[i]:
            header.append(f"Pcal{n} (hPa)")
        else:
            header.append(f"p{n} (hPa)")
    print(", ".join(header))


def print_header_with_calibrations(sensor_count, sensor_cals, sensor_cal_types, log):
    """
    Builds and writes the CSV header row for the log file.
    The file header consists of raw sensor columns first and then, for sensors that have calibration,
    additional columns are appended.
    """
    file_header = ["Datetime", "Timestamp", "Time (s)", "Measurement"]
    
    # Raw sensor columns for each sensor:
    for i in range(sensor_count):
        n = i + 1
        file_header.extend([f"t{n} (°C)", f"RH{n}% (%)", f"p{n} (hPa)"])
    
    # Then add calibration columns for sensors that have calibration data:
    for i in range(sensor_count):
        n = i + 1
        if sensor_cal_types[i]:
            for meas in ["Temperature", "Relative Humidity", "Pressure"]:
                if meas in sensor_cal_types[i]:
                    if meas == "Temperature":
                        file_header.append(f"Tcal{n} (°C)")
                    elif meas == "Relative Humidity":
                        file_header.append(f"RHcal{n}% (%)")
                    elif meas == "Pressure":
                        file_header.append(f"Pcal{n} (hPa)")
    
    log.write(file_header)


def build_and_store_row(memdata, count, t, secs, sensor_values, cal_readings, sensor_cal_types, log, is_nan_logging, max_rows):
    """
    Builds a row: time info, raw sensor values, and then calibration values (if available)
    appended in the order determined by sensor_cal_types.
    """
    if (np.isnan(sensor_values).all()) and (not is_nan_logging):
        return memdata
    row = [t.timestamp(), secs, count]
    row.extend(sensor_values)
    for i in range(len(cal_readings)):
        for meas in ["Temperature", "Relative Humidity", "Pressure"]:
            if meas in sensor_cal_types[i]:
                val = cal_readings[i].get(meas, np.nan)
                row.append(val)

    if count == 1:
        memdata = np.array(row)
    else:
        memdata = np.vstack([memdata, row])
    if len(memdata) > max_rows:
        memdata = memdata[1:, :]
    combined = np.array(sensor_values, dtype=float)
    for i in range(len(cal_readings)):
        for meas in ["Temperature", "Relative Humidity", "Pressure"]:
            if meas in sensor_cal_types[i]:
                combined = np.append(combined, cal_readings[i].get(meas, np.nan))
    time_dict["timestamp"] = t
    time_dict["time"] = secs
    time_dict["N"] = count
    out_line = format_data(time_dict, combined)
    log.write(out_line)
    return memdata


def print_data_line_to_screen(t, secs, count, sensor_values, cal_readings, sensor_cal_types):
    """
    For each sensor, always print three values: Temperature, Relative Humidity, and Pressure.
    If calibration exists for a type, use the calibrated value; otherwise, use the raw value.
    """
    out_vals = []
    sensors = len(sensor_values) // 3
    for sensor_index in range(sensors):
        # Get raw values:
        t_raw = sensor_values[sensor_index*3]
        h_raw = sensor_values[sensor_index*3 + 1]
        p_raw = sensor_values[sensor_index*3 + 2]
        
        # Temperature:
        if sensor_cal_types[sensor_index] and "Temperature" in sensor_cal_types[sensor_index]:
            t_val = cal_readings[sensor_index].get("Temperature", t_raw)
        else:
            t_val = t_raw
        # Relative Humidity:
        if sensor_cal_types[sensor_index] and "Relative Humidity" in sensor_cal_types[sensor_index]:
            h_val = cal_readings[sensor_index].get("Relative Humidity", h_raw)
        else:
            h_val = h_raw
        # Pressure:
        if sensor_cal_types[sensor_index] and "Pressure" in sensor_cal_types[sensor_index]:
            p_val = cal_readings[sensor_index].get("Pressure", p_raw)
        else:
            p_val = p_raw
        
        out_vals.extend([t_val, h_val, p_val])
    
    arr = np.array(out_vals, dtype=float)
    time_dict["timestamp"] = t
    time_dict["time"] = secs
    time_dict["N"] = count
    line = format_data(time_dict, arr)
    # For screen brevity, replace the decimal portion of the second column:
    line_short = re.sub(r"\..*?,.*?,", ",", line, count=1)
    print(line_short)


# ------------------------------
# DATA LOGGING / SENSOR READING
# ------------------------------
def read_and_calibrate_sensor_data(address, relay_obj, sensor_index, sensor_cals, trials, delay, is_relays, is_simulation, errors, count):
    """
    Attempts to read from one BME280 sensor. If reading fails, tries rebooting
    up to 'trials' times.
    Returns: (success, t, h, p, cal_dict, errors)
    cal_dict is a dictionary with keys "Temperature", "Relative Humidity", "Pressure"
    for calibrated values. Calibration is applied only if a given type is available.
    """
    
    global error_log
    
    i = 0
    while True:
        try:
            # --- NEW: trigger a single FORCED-mode conversion ---
            if not trigger_forced_measure(address):
                raise OSError       # fall through to retry logic
            
            # now read the data (unchanged)
            t_, p_, h_ = readBME280All(address)  # (temp °C, pressure hPa, humidity %)
            cal_dict = {}
            if sensor_cals[sensor_index]:
                # Only attempt calibration if the calibration type is available
                if "Temperature" in sensor_cals[sensor_index]._cal_data:
                    t_cal = sensor_cals[sensor_index].get_calibrated_value(t_, "Temperature")
                    cal_dict["Temperature"] = t_cal
                if "Relative Humidity" in sensor_cals[sensor_index]._cal_data:
                    h_cal = sensor_cals[sensor_index].get_calibrated_value(h_, "Relative Humidity")
                    cal_dict["Relative Humidity"] = h_cal
                if "Pressure" in sensor_cals[sensor_index]._cal_data:
                    p_cal = sensor_cals[sensor_index].get_calibrated_value(p_, "Pressure")
                    cal_dict["Pressure"] = p_cal
            return True, t_, h_, p_, cal_dict, errors
        except Exception:
            # --- NEW: try ONE soft-reset before touching the relays ---
            if i == 0 and soft_reset(address):
                i += 1
                continue            # go back to try reading again
            
            # original relay-reboot logic follows
            if i < trials and is_relays:
                terr = datetime.now().timestamp()
                if error_log is None:                 # prevent duplicate object
                    error_log = ErrorLog(log.dir_path, "sensor_failures","log", log.dt_part, log.ts_prefix)
                msg = f"Unable to read sensor {hex(address)}. Reboot {i+1}/{trials}"
                if error_log:
                    error_log.write(terr, count, msg)
                print(msg)
                ch = sensor_index + 1          # 1 for first sensor (0x76), 2 for second (0x77)
                relay_obj.ch_open(ch)          # cut power only to that sensor 
                sleep(delay)
                if is_simulation:
                    relay_fail.all_close(1)
                relay_obj.ch_close(ch)         # restore power to that sensor
                errors += 1
                i += 1
                sleep(delay)
            else:
                return False, np.nan, np.nan, np.nan, {}, errors


# ------------------------------
# MAIN
# ------------------------------
def main():
    global memdata, sensor_count, log, relay_fail, stop_threads, thr, disable_halt, is_combo_figures, sensor_cal_types
    global tstart
    global zone, num1, num2

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

    # 6) Setup Ctrl+C handling
    signal.signal(signal.SIGINT, SignalHandler_SIGINT)

    # 7) Compute max_rows for data retention
    max_rows_calc = int(retention_time * 24 * 3600 / interval)
    if max_rows_calc > rows_limit:
        max_rows_calc = rows_limit
        new_retention = max_rows_calc * interval / (24 * 3600)
        print("Retention time was too large => adjusted to " f"{new_retention:.2f} days\n")
    max_rows = max_rows_calc

    if is_simulation:
        thr.start()

    count = 1
    errors = 0
    disable_halt = True

    # 8) For the "1 hour after 5 fails" logic
    # Initialize cooldown arrays
    consecutive_failures = [0] * sensor_count
    cooldown_until = [0] * sensor_count

    # Compute per-sensor available calibration types
    sensor_cal_types = []
    for i in range(sensor_count):
        if sensor_cals[i] is not None:
            available = []
            for meas in ["Temperature", "Relative Humidity", "Pressure"]:
                if meas in sensor_cals[i]._cal_data:
                    available.append(meas)
            sensor_cal_types.append(available)
        else:
            sensor_cal_types.append([])

    # 9) Wait until next full second
    print("Synchronizing time.")
    while get_sec_fractions(4) != 0:
        pass

    # 10) Start logging
    tp0 = perf_counter()
    tstart = datetime.now().timestamp()

    # create DataLog object
    log = DataLog(tstart, base_dir, "thp", "csv", is_subdir, is_prefix)

    # Print CSV header (with calibration columns if available)
    print_screen_header(sensor_count, sensor_cal_types)
    print_header_with_calibrations(sensor_count, sensor_cals, sensor_cal_types, log)
    
    # MAIN LOOP
    while True:
        disable_halt = True
        tp_now = perf_counter()
        t_now = datetime.now()
        sensor_values = []   # Raw sensor values: for each sensor, [temp, hum, pres]
        cal_readings = []    # For each sensor, a dict with calibrated values
        sensor_ok = [False] * sensor_count
        for s_idx, address in enumerate(sensors_list):
            now_time = time.time()
            if now_time < cooldown_until[s_idx]:
                # skip reading => store NaNs
                sensor_values.extend([np.nan, np.nan, np.nan])
                cal_readings.append({})
                continue
            else:
                # <--- WE JUST LEFT COOL-DOWN (if it was set before).
                # If consecutive_failures[s_idx] was >=5, reset to 0 now.
                if consecutive_failures[s_idx] >= 5:
                    consecutive_failures[s_idx] = 0
                # close (power on) this sensor
                r.ch_close(s_idx + 1)
            # read sensor
            success, t_, h_, p_, cal_dict, errors = read_and_calibrate_sensor_data(
                address=address,
                relay_obj=r,
                sensor_index=s_idx,
                sensor_cals=sensor_cals,
                trials=trials,
                delay=delay,
                is_relays=is_relays,
                is_simulation=is_simulation,
                errors=errors,
                count=count
            )
            sensor_values.extend([t_, h_, p_])
            cal_readings.append(cal_dict)
            if success:
                sensor_ok[s_idx] = True
                consecutive_failures[s_idx] = 0
                cooldown_until[s_idx] = 0
            else:
                consecutive_failures[s_idx] += 1
                if consecutive_failures[s_idx] >= 5:
                    # 1 hour cooldown
                    cooldown_until[s_idx] = now_time + COOLDOWN_DURATION
                    # r.ch_open(s_idx + 1)
                    print(f"Sensor {hex(address)} => 5 consecutive fails. Cooldown until {datetime.fromtimestamp(cooldown_until[s_idx])}.")
        if all(sensor_ok):
            for si in range(sensor_count):
                consecutive_failures[si] = 0
                cooldown_until[si] = 0
        secs = tp_now - tp0
        memdata = build_and_store_row(memdata, count, t_now, secs, sensor_values, cal_readings, sensor_cal_types, log, is_nan_logging, max_rows)

        # Print to screen if we haven't suppressed
        if not (np.isnan(sensor_values).all() and not is_nan_logging):
            
            print_data_line_to_screen(t_now, secs, count, sensor_values, cal_readings, sensor_cal_types)
        disable_halt = False

        # Wait for next interval
        tp_end = perf_counter()
        wait_time = count * interval - (tp_end - tp0)
        if wait_time > 0:
            sleep(wait_time)
        count += 1


# ------------------------------
# ENTRY POINT
# ------------------------------

if __name__ == "__main__":
    main()
