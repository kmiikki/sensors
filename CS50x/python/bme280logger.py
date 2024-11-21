#!/usr/bin/env python3                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 #!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Aug 21 12:17:22 2024

@author: Kim Miikki
"""

from sys import exit
from time import sleep, perf_counter
from relays import Relay
from pathlib import Path
from datetime import datetime
from logfile import DataLog, ErrorLog
from bme280 import *
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

np.set_printoptions(suppress=True, formatter={'float_kind':'{:f}'.format})

relay_pin_list = [21, 20]
relay_failures = [26]
nc_high_mode = True
# relay_pin_list = []


interval = 1   # Unit is 's'
is_nan_logging = False  # If False, data containing nan values will not be logged

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
   
max_rows = -1  # Will be calculated later
retention_time = 7  # Data retention time in memory in days.
                    # This value does not affect the size of log files, as
                    # they are allowed to grow indefinitely until storage is full
                    # or user termination of the logging.
sensors = []       # List of BME280 sensor address(es)

disable_halt = False  # Enable or disable CTRL+C termination of the program
trials = 3  # Sensor reboot attempts
delay = 0.1  # Delay in seconds between attempts
is_simulation = False  # Simulate random sensor failures

base_dir = ""
is_subdir = False
is_prefix = False

# Failure probability in simulation
relay_fail = None
thr = None
pfail = 0.01
stop_threads = True

# Measurement data info
time_dict = {"timestamp": 0, "time": 0, "N": 0}
data_cols = 3  # Temperature, Humidity and Pressure
log = None
memdata = None # Measurement data in memory
sensor_count = 0

# Figures flags
is_basic_figures = False
is_combo_figures = False


def parse_arguments():
    global retention_time
    global interval
    global base_dir
    global is_subdir
    global is_prefix
    global is_simulation
    global is_nan_logging
    global is_basic_figures
    global is_combo_figures

    parser = argparse.ArgumentParser()
    parser.add_argument("-d", type=str, help="specify file base directory (default = current working directory)", required=False)
    parser.add_argument("-s", action="store_true", help="enable datetime subdirectories", required=False)
    parser.add_argument("-ts", action="store_true", help="add timestamp as prefix for files", required=False)
    parser.add_argument("-i", type=float, help="interval in seconds", required=False)
    parser.add_argument("-nan", action="store_true", help="log failed readings as NaN", required=False)
    parser.add_argument("-r", type=int, help="data retention period in memory (default: " + str(retention_time)+" d)", required=False)
    parser.add_argument("-b", action="store_true", help="create basic graphs", required=False)
    parser.add_argument("-c", action='store_true', help="create graphs of two sensors", required=False)
    parser.add_argument("-a", action='store_true', help="create all graphs", required=False)
    parser.add_argument("-simfail", action="store_true", help="simulate random sensor failures", required=False)
    args = parser.parse_args()

    # Base directory argument
    if args.d != None:
        base_dir = args.d.strip()

    # Subdir argument
    if args.s:
        is_subdir = True

    # Prefix argument
    if args.ts:
        is_prefix = True

    # Interval argument
    if args.i != None:
        interval = args.i
        if args.i < 1:
            print('\nInterval set to 1')
            interval = 1
        else:
            interval = args.i

    # Prefix argument
    if args.nan:
        is_nan_logging = True

    # Data retention time argument
    if args.r != None:
        if args.r < 1:
            print('Illegal value. Data retention period must be > 0.')
            exit(1)
        else:
            retention_time = args.r

    # Simfail argument: Simulate failures
    if args.simfail:
        if len(relay_failures) > 0:
            is_simulation = True
        else:
            print("No relay pin for failures simulation assigned")
            sys.exdt(1)
    
    # Basic figures argument
    if args.b:
        is_basic_figures = True

    # Combined figures argument
    if args.c:
        is_combo_figures = True

    # Basic figures argument
    if args.a:
        is_basic_figures = True
        is_combo_figures = True


def get_sensors() -> list():
    # Initalize sensor(s) and get address / addresses
    i2c = board.I2C()  # uses board.SCL and board.SDA
    while not i2c.try_lock():
        pass

    try:
        addrs = [hex(device_address) for device_address in i2c.scan()]
        print("I2C addresses found:", addrs)
    finally:  # unlock the i2c bus when ctrl-c'ing out of the loop
        i2c.unlock()

    devices = []
    if "0x76" in addrs:
        devices.append(0x76)
    if "0x77" in addrs:
        devices.append(0x77)
    devices_count = len(devices)
    # if devices_count == 0:
    #    print("No BME280 sensors found. The program is terminated.")
    #    sys.exit()
    return devices


def display_info():
    print('Interval: '+str(interval)+' s')

    # Get current directory
    curdir = os.getcwd()
    path = Path(curdir)
    dirname = os.path.basename(curdir)
    print('')
    print("Current directory:")
    print(curdir)
    print('')
    print('Press Ctrl+C to end logging.')
    print('')


def auto_scale(times: np.array, diff_time=False):
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


# Graph functions
# ---------------

def create_graph_1(xs: np.array, ys: np.array,
                   xlabel: str, ylabel: str, full_path: str):

    fig=plt.figure()
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.plot(xs, ys, color='k')
    plt.ticklabel_format(useOffset=False)
    plt.ticklabel_format(style='plain')
    xmin = math.floor(xs[0])
    xmax = xs[-1]
    ymin = ys[np.isfinite(ys)].min()
    ymax = ys[np.isfinite(ys)].max()
    plt.xlim(xmin, xmax)
    plt.ylim(ymin, ymax)
    plt.grid()        
    fig.tight_layout()
    plt.savefig(full_path, dpi=300,bbox_inches='tight')
    plt.close(fig)

    
def create_graph_2(xs: np.array, ys1: np.array, ys2: np.array,
                   legend1: str,
                   legend2: str,
                   xlabel: str,
                   ylabel: str,
                   full_path: str):

    fig=plt.figure()
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.plot(xs, ys1, color='k', label=legend1)
    plt.plot(xs, ys2, color='0.33', label=legend2)
    plt.ticklabel_format(useOffset=False)
    plt.ticklabel_format(style='plain')
    xmin = math.floor(xs[0])
    xmax = xs[-1]
    ymin = min([ys1[np.isfinite(ys1)].min(), ys2[np.isfinite(ys2)].min()])
    ymax = max([ys1[np.isfinite(ys1)].max(), ys2[np.isfinite(ys2)].max()])
    plt.xlim(xmin, xmax)
    plt.ylim(ymin, ymax)
    plt.grid()
    plt.legend(loc=0)        
    fig.tight_layout()
    plt.savefig(full_path, dpi=300,bbox_inches='tight')
    plt.close(fig)


def create_graph_combo(xs: np.array, ys1: np.array, ys2: np.array,
                       legend1: str,
                       legend2: str,
                       xlabel: str,
                       ylabel1: str,
                       ylabel2: str,
                       color1: str,
                       color2: str,
                       full_path: str):

    fig, ax1 = plt.subplots()
    plt.xlabel(xlabel)
    ax1.set_ylabel(ylabel1)
    ax1.plot(xs, ys1, color=color1, label=ylabel1)
    xmin = math.floor(xs[0])
    xmax = xs[-1]
    ymin = ys1[np.isfinite(ys1)].min()
    ymax = ys1[np.isfinite(ys1)].max()
    ax1.set_xlim(xmin, xmax)
    ax1.set_ylim(ymin, ymax)
    ax1.grid(color="tab:gray", linestyle="--")
    ax2 = ax1.twinx()
    ax2.set_ylabel(ylabel2)
    ax2.plot(xs, ys2, color=color2, label=ylabel2)
    ymin = ys2[np.isfinite(ys2)].min()
    ymax = ys2[np.isfinite(ys2)].max()    
    ax2.set_ylim(ymin, ymax)
    plt.ticklabel_format(useOffset=False)
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax2.legend(lines + lines2, labels + labels2, loc=0)
    fig.tight_layout()
    plt.savefig(full_path ,dpi=300, bbox_inches='tight')
    plt.close(fig)
    
# ---------------


# Create a signal handler for Signals.SIGINT:  CTRL + C
def SignalHandler_SIGINT(SignalNumber, Frame):
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
    
    # Save graphs
    # At least two data points are required for a graph
    if memdata is None:
        exit(0)
    elif memdata.ndim == 1:
        exit(0)
        
    # Transpose the data
    memdata = memdata.T
    xs = memdata[1] # Time row
    xs, unit = auto_scale(xs,)
    x_label = f"Time ({unit})"
    pos = 3 # Measurement data start row
    base_dir = log.dir_path
    if log.ts_prefix:
        prefix = log.dt_part + "-"
    else:
        prefix = ""
    
    if True in [is_basic_figures, is_combo_figures]:
        print("")
        print("Generating figures:")
    
    if is_basic_figures:
        # Create single graphs
        print("- basic graphs")
        for i in range(sensor_count):
            create_graph_1(xs, memdata[pos + i * 3], x_label,
                           f"Temperature{i+1} (°C)",
                           f"{base_dir}{prefix}fig{i+1}-single-t.png")
            create_graph_1(xs, memdata[pos + i * 3 + 1], x_label,
                           f"RH{i+1}% (%)",
                           f"{base_dir}{prefix}fig{i+1}-single-h.png")
            create_graph_1(xs, memdata[pos + i * 3 + 2], x_label,
                           f"Pressure{i+1} (hPa)",
                           f"{base_dir}{prefix}fig{i+1}-single-p.png")

    if sensor_count == 2 and is_combo_figures:
        # Create diff graphs
        print("- difference graphs")
        create_graph_1(xs, memdata[pos + 3] - memdata[pos],
                       x_label, "T2 - T1 (°C)", f"{base_dir}{prefix}fig-diff-t21.png")
        create_graph_1(xs, memdata[pos + 3 + 1] - memdata[pos + 1],
                       x_label, "RH2% - RH1% (%)",
                       f"{base_dir}{prefix}fig-diff-rh21.png")
        create_graph_1(xs, memdata[pos + 3 + 2] - memdata[pos + 2],
                       x_label, "p2 - p1 (hPa)", f"{base_dir}{prefix}fig-diff-p21.png")
    
        # Create pair graphs
        print("- pair graphs")
        create_graph_2(xs, memdata[pos], memdata[pos + 3],
                       "t1", "t2",
                       x_label,
                       "Temperature (°C)", f"{base_dir}{prefix}fig-pair-t12.png")
        create_graph_2(xs, memdata[pos + 1], memdata[pos + 4],
                       "RH1%", "RH2%",
                       x_label,
                       "RH% (%)", f"{base_dir}{prefix}fig-pair-rh12.png")
        create_graph_2(xs, memdata[pos + 2], memdata[pos + 5],
                       "p1", "p2",
                       x_label,
                       "Pressure (hPa)", f"{base_dir}{prefix}fig-pair-p12.png")

        
        # Create combined graphs
        print("- combined graphs")
        create_graph_combo(xs, memdata[pos], memdata[pos + 1],
                       "t1", "t2",
                       x_label,
                       "Temperature (°C)",
                       "RH% (%)",
                       "r",
                       "b",
                       f"{base_dir}{prefix}fig1-combo-trh.png")        
        create_graph_combo(xs, memdata[pos+3], memdata[pos + 4],
                       "t1", "t2",
                       x_label,
                       "Temperature (°C)",
                       "RH% (%)",
                       "r",
                       "b",
                       f"{base_dir}{prefix}fig2-combo-trh.png")        

    exit(0)


def get_sec_fractions(resolution=5) -> float:  # Final resolution = 5
    t = datetime.now()
    return round(t.timestamp() % 1, resolution)


def simulate_failure():
    global pfail
    global stop_threads
    global relay_fail
    global thr
    while True:
        if stop_threads:
            break
        rnd = random.random()
        if rnd < pfail:
            relay_fail.ch_open(1)
        sleep(0.1)


def format_data(tdata: time_dict, data: np.array) -> str:
    decimals = 2
    s = ""
    dt = tdata["timestamp"]
    ts = str(dt.timestamp())
    t = tdata["time"]
    n = tdata["N"]
    out = [dt.strftime("%Y-%m-%d %H:%M:%S.%f")]
    out.append(ts)
    out.append(str(f"{t:.1f}"))
    out.append(str(n))
    for value in data:
        value = round(value, decimals)
        out.append(f"{value:.{decimals}f}")
    s = ", ".join(out)
    return s

def main():
    global is_nan_logging
    global is_simulation
    global stop_threads
    global relay_fail
    global thr
    global retention_time
    global memdata
    global sensor_count
    global log
    global is_combo_figures

    print("BME280 data logger - Kim Miikki 2024\n")

    parse_arguments()

    # Determine relay mode
    if len(relay_pin_list) > 0:
        is_relays = True
        r = Relay(relay_pin_list, nc_high=nc_high_mode)
    else:
        is_relays = False

    if is_simulation:
        relay_fail = Relay(relay_failures, nc_high=nc_high_mode)
        # relay_fail.all_close()
        sleep(0.1)

    if is_simulation:
        random.seed(1)  # Use fixed seed to ensure repeatability of simulation
        thr = threading.Thread(target=simulate_failure)
        stop_threads = False

    # Reboot sensors before trying to detect them
    print("Intializing sensor(s).\n")
    for i in range(2):
        r.all_toggle()
        sleep(0.1)

    # Try to find sensor(s)
    i = 1
    while True:
        sensors = get_sensors()
        if len(sensors) > 0:
            # Try to read sensors
            is_ok = False
            try:
                for address in sensors:
                    readBME280All(address)
                    print(f"Sensor {hex(address)}: PASS")
                is_ok = True
            except:
                print(f"Unable to read {hex(address)}!")
            if is_ok:
                break
        if i < 2:
            # Turn off sensor(s)
            r.all_toggle()
            sleep(0.5)
            # Turn on sensor(s)
            r.all_toggle()
            i += 1
        else:
            print("")
            print("No functional BME280 sensors found. The program is terminated.")
            sys.exit()
    sensor_count = len(sensors)
    if sensor_count == 1 and is_combo_figures:
        is_combo_figures = False
        print("")
        print("Combined graphs are disabled when using only one sensor!\n")
        

    display_info()
    signal.signal(signal.SIGINT, SignalHandler_SIGINT)

    # Calculate maximum rows limit for data which can be stored in memory
    max_rows = int(retention_time * 24 * 3600 / interval)
    if max_rows > rows_limit:
        max_rows = rows_limit
        # Calculate a new retention time
        retention_time = max_rows * interval / (24 * 3600)
        print("The combination of retention time and interval exceeded the upper limit "
              "of the data storage in memory, therefore the retention time has been "
              f"adjusted to a new value: {retention_time:.2f} d\n")

    # Wait until a new second starts
    while get_sec_fractions() != 0:
        pass

    # Get perf_copunter start time
    tp0 = perf_counter()
    tstart = datetime.now().timestamp()

    # Create log objects
    log = DataLog(tstart, base_dir, "thp", "csv", is_subdir, is_prefix)

    # Start simulation of sensor failure
    if is_simulation:
        thr.start()

    count = 1
    errors = 0
    disable_halt = True
    while True:
        t = datetime.now()
        tp_cur = perf_counter()

        # TODO: Simulate sensor failure with relays
        # Failure when GND is disconnected
        data = np.full(sensor_count * data_cols, np.nan)
        sensor_num = 0
        for address in sensors:
            i = 0
            while True:
                try:
                    ts, p, h = readBME280All(address)
                    # Add measurement data to a numpy array
                    data[sensor_num * data_cols] = ts
                    data[sensor_num * data_cols + 1] = h
                    data[sensor_num * data_cols + 2] = p
                    break

                except:
                    if i < trials and is_relays:
                        terr = datetime.now().timestamp()
                        if errors == 0:
                            # Create an error log object
                            error_log = ErrorLog(
                                log.dir_path, "sensor_failures", "log", log.dt_part, log.ts_prefix)
                        out = f"Unable to read sensor on address {hex(address)}. Rebooting sensor: {i+1}/{trials}"
                        # Write the error event to error log
                        error_log.write(terr, count, out)
                        print(out)

                        # Turn off sensor(s)
                        r.all_open()
                        sleep(delay)
                        # Turn on sensor(s)
                        if is_simulation:
                            relay_fail.all_close()
                        r.all_close()
                        errors += 1
                        i += 1
                        # Wait before trying to read the sensor again
                        sleep(delay)
                        t = datetime.now()
                        tp_cur = perf_counter()
                    else:
                        break
            sensor_num += 1

        # Do not log the data if it contains nan and 'nan logging' is disabled
        if not (np.isnan(data).any() == True and (is_nan_logging == False)):
            disable_halt = True
            
            if count == 1:
                # Generate data header
                header = ["Datetime", "Timestamp", "Time (s)", "Measurement"]
                for i in range(sensor_count):
                    n = i + 1
                    header.append(f"t{n} (°C)")
                    header.append(f"RH{n}% (%)")
                    header.append(f"p{n} (hPa)")
                out = ", ".join(header)
                # Replace the timestamp with ','
                out_print = re.sub(r",[^,]*,", ",", out, count=1)
                print(out_print)
                # Write headers to log file
                log.write(header)
            
            # Create a data row for memdata
            # Template: datetime, time, n, t1, h1, p1 (,t2 , h2, p2)
            row = [t.timestamp(), tp_cur - tp0, count]
            for value in data:
                row.append(value)
            if count == 1:
                memdata = np.array(row)
            else:
                memdata = np.vstack([memdata,row])
            
            # Perform data retention
            if len(memdata) > max_rows:
                memdata = memdata[1:,:]            
            
            time_dict["timestamp"] = t
            time_dict["time"] = tp_cur - tp0
            time_dict["N"] = count
            out = format_data(time_dict, data)
            # Remove the substring from the string starting at
            # the decimal point of the second and ending at
            # the comma after the timestamp
            out_print = re.sub(r"\..*?,.*?,", ",", out, count=1)
            print(out_print)
            
            # Append data to the log file
            log.write(out)
            
            disable_halt = False

        # Calculate remaining time for next interval
        tp1 = perf_counter()
        wait_time = count * interval - (tp1 - tp0)
        if wait_time > 0:
            sleep(wait_time)
        count += 1
    print("")


if __name__ == "__main__":
    main()
