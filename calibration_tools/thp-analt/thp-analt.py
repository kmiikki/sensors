#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon May 20 13:45:00 2025

@author: Kim

Example, how to monitor new data:
$ watch -n 2 ./thp-analt.py -n -t 5

"""

import argparse
import csv
import math
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import scipy.stats as st 
import sys

from datetime import datetime
from pathlib import Path


def line(x, slope, constant):
    return slope * x + constant

def first_decimal(number: float) -> int | float:
    """
    Returns the position (starting from 1) of the first non‑zero digit
    after the decimal separator. 0 → no non‑zero decimals, np.nan → input nan
    """
    if math.isnan(number):
        return np.nan

    s = np.format_float_positional(np.float32(number))

    # NEW: handle integers (no decimal point)
    if '.' not in s:
        return 0

    decimals = s.split('.', 1)[1]
    for i, ch in enumerate(decimals, start=1):
        if ch != '0':
            return i
    return 0


def fnumber(number: float, precision: int) -> str:
    """
    Returns the number as a string with exactly *precision* decimals,
    padding with zeros if necessary.
    """
    s = np.format_float_positional(np.float32(number))

    # NEW: cope gracefully with integers
    if '.' in s:
        integer, decimals = s.split('.', 1)
    else:
        integer, decimals = s, ''

    decimals = (decimals + '0' * precision)[:precision]
    return f'{integer}.{decimals}'


def generate_stats(names, data, precisions):    
    slope_unit = '°C/s'
    c_unit = '°C'
    width = 11
    out = []
    out.append('Statistics')
    out.append('----------')
    i = 0
    while i < len(names):
        if precisions[i] == -1:
            if names[i] == 'Method':
                value = data[i]
            else:
                pr = first_decimal(data[i])
                value = str(round(data[i], pr))
        else:
            if precisions[i] == 0:
                value = str(int(round(data[i],0)))
            else:
                value = str(round(data[i], precisions[i]))
        if names[i] == 'Slope':
            value += ' ' + slope_unit
        elif names[i] == 'Constant':
            value += ' ' + c_unit
        if names[i] != 'Time':
            out.append(names[i].ljust(width)+': '+value)
        else:
            out.append('Time (min)'.ljust(width)+': '+value)
        i += 1
    
    # Get the CI half precision
    ci_half = data[14]
    ci_low = data[12]
    ci_high = data[13]
    pr = first_decimal(ci_half)
    if pr < 3:
        pr += 1
    rh_str = fnumber(round(data[8], pr), pr)
    ci_str = fnumber(round(ci_half, pr), pr)
    ci_low_str = fnumber(round(ci_low, pr), pr)
    ci_high_str = fnumber(round(ci_high, pr), pr)
    a = alpha * 100
    if a.is_integer() :
        a_str = str(int(a))
    else:
        a_str =str(a)
    out.append('')
    out.append('t (°C): '+rh_str + '±' + ci_str)
    out.append('t (°C): ['+a_str+'% CI: '+ci_low_str+'-'+ci_high_str+']')    
    return out

def dataline(text, value, decimals = 0, width = 12):
    s = text.ljust(width) + ': '
    s += str(round(value,decimals))
    return s

def get_unit(xs):
    unit='s'
    factor = 5
    xmin = xs[0]
    xmax = xs[-1]
    range = xmax - xmin
    
    if range <= factor * 60:
        unit = 's'
        divisor = 1
    elif range <= factor * 3600:
        unit = 'min'
        divisor = 60
    elif range <= factor * 3600 * 24:
        unit = 'h'
        divisor = 3600
    else:
        unit = 'd'
        divisor = 3600 * 24

    return unit, divisor


def get_xlabel(text, unit):
    return text + ' (' + unit + ')'


sensors = 0
interval = 0
linefit_time = 10 # Default: 10 min
target_time = linefit_time
max_rows = 5 * 7 * 24 * 3600 # = 3024000
alpha = 0.95
n = 0
filename = ''
adir = ''
create_files = True
create_lines_full = False
create_lines_range = False
create_combo_range = False
create_diff_graph = False
show_line_in_full = False
is_full_range = False
is_info = True

print('THP temperature data analyzer - (C) Kim Miikki 2025')

# Get current directory
curdir = os.getcwd()
path = Path(curdir)
dirname = os.path.basename(curdir)
print('')
print("Current directory:")
print(curdir)
print('')

parser = argparse.ArgumentParser()
parser.add_argument('-f', type = str, help='thp.csv filename (last file is selected without this argument)', required=False)
parser.add_argument('-t', type = int, help='line fit time (default: '+str(linefit_time)+' min)', required=False)
parser.add_argument('-o', type = int, help='override maximum data rows (default: '+str(max_rows)+')', required=False)
parser.add_argument('-d', type = str, help='specify the name of the analysis subdirectory', required=False)
parser.add_argument('-n', action = 'store_true', help='do not create analysis files', required=False)
parser.add_argument('-a', action = 'store_true', help='generate all files (overrides other options)', required=False)
parser.add_argument('-l', action = 'store_true', help='create linear regression line graphs with all data points', required=False)
parser.add_argument('-r', action = 'store_true', help='create linear regression line graphs with data points in the time range', required=False)
parser.add_argument('-c', action = 'store_true', help='create combined temperature graph for 2 sensors', required=False)
parser.add_argument('-diff', action = 'store_true', help='create difference graph of two data sets (time range)', required=False)
parser.add_argument('-ni', action = 'store_true', help='do not display summary info on screen', required=False)
parser.add_argument('-sl', action = 'store_true', help='show fitted regression line in full data graph', required=False)

args = parser.parse_args()

if args.a:
    args.n = False    # Create analysis files
    args.l = True     # Create full range graphs
    args.r = True     # Create zoomed graphs
    args.c = True     # Create combined range graph
    args.diff = True  # Create difference graph for two data sets
    
if args.l:
    create_lines_full = True

if args.r:
    create_lines_range = True

if args.c:
    create_combo_range = True

if args.diff:
    create_diff_graph = True

if args.ni:
    is_info = False

if args.sl:
    show_line_in_full = True

if args.f != None:
    filename = args.f
    filename = Path(os.path.join(curdir, filename))
else:
    # Try to find the last *thp.csv file
    is_file = False
    for path in sorted(Path(curdir).glob('*thp.csv')):
        is_file = True
    if not is_file:
        sys.exit('A required *thp.csv file not found.')
    else:
        filename = path
    
if filename != '':
    try:
        with open(filename) as f:
            print('Log file found: '+filename.name)
    except FileNotFoundError:
        sys.exit('The file does not exist.')

if args.t != None:
    if args.t > 0:
        linefit_time = int(args.t)
        target_time = linefit_time

if args.o != None:
    if args.o < 2:
        sys.exit('At least 2 rows of data are needed')
    else:
        max_rows = args.o

if args.n:
    create_files = False

if create_files:
    file_stem=filename
        
    if args.d != None:
        adir = str(args.d).strip()
    
    # Generate analysis dir name from date and time if the name is not specified
    if adir == '':
        current_time = datetime.now()
        a_date = current_time.strftime('%Y%m%d')
        a_time = current_time.strftime('%H%M%S')
        adir = filename.stem + '-a'+a_date+'-'+a_time
    
    # Create analysis directory
    adir = Path(os.path.join(curdir, adir))
    try:  
        if not os.path.exists(adir):
            os.mkdir(adir)  
    except OSError:  
        sys.exit('Unable to create a subdirectory')

# Check if the log file has a header
with open(filename, 'r') as csvfile:
    sample = csvfile.read(2048)
    has_header = csv.Sniffer().has_header(sample)

# Count how many lines of data are in the log files
n_count = 0
n_count = sum(1 for row in open(filename,'r'))
if has_header:
    row_count = n_count - 1
else:
    row_count = n_count
    
if row_count <= max_rows:
    if has_header:
        df = pd.read_csv(filename, header = 0, encoding = 'utf-8')
    else:
        df = pd.read_csv(filename, header = None)
    
    if len(df) < 2:
        sys.exit('At least 2 rows of data is required')
else:
    skip_end = n_count - max_rows
    if has_header:
        skip_start = 1
        df = pd.read_csv(filename, header = 0, skiprows=range(skip_start, skip_end), encoding = 'utf-8')
    else:
        skip_start = 0
        df = pd.read_csv(filename, header = None, skiprows=range(skip_start, skip_end), encoding = 'utf-8')

# Determine interval length
xs = np.array(df.iloc[:,2])
intervals = np.unique(np.diff(xs))

# Display a warning if more than one interval exists
if len(intervals) > 1:
    print('')
    print('Warning, multiple intervals found: ', end='')
    elements = len(intervals)
    i = 0
    for val in intervals:
        i += 1
        print(str(val), end = '')
        if i < elements:
            print(', ', end = '')
        else:
            print(' ', end = '')
    print('s')
    i += 1
    interval = round(np.mean(np.diff(xs)))
elif len(intervals) == 1:
    interval = intervals[0]
else:
    sys.exit('No intervals found.')

# Determine sensors count
if len(df.columns) == 7:
    sensors = 1
    ys = np.array(df.iloc[:,4])
elif len(df.columns) == 10:
    sensors = 2
    ys = np.array(df.iloc[:,4])
    ys = np.vstack((ys, np.array(df.iloc[:,7])))
else:
    sys.exit('Sensor data not found.')

# Disable generation of difference plot, if only one sensor data is present
if sensors == 1 and create_diff_graph == True:
    print('')
    print('Warning: Cannot create diffrence graph when only one sensor data is present.')
    create_diff_graph = False

if sensors == 1 and create_combo_range == True:
    print('')
    print('Warning: Cannot create combined graph when only one sensor data is present.')
    create_combo_range = False

# Calculate maximum dtime for the data range
max_time = len(xs) * interval / 60
if linefit_time > max_time:
    linefit_time = round(max_time,2)
    print('')
    print('Warning: Requested time exceeds the measurement range.')
    print('Auto adjustment: All data points are selected for the analysis.')
    print('New data range:  '+str(round(max_time,2))+' min')
else:
    is_full_range = True

# Calculate maximum data points
max_slope_vals = round(linefit_time * 60 / interval)

# Get x and y values for linefit
xs_fit = xs[-max_slope_vals:]
ys_fit = ys.T
ys_fit = ys_fit[-max_slope_vals:]
ys_fit = ys_fit.T

# Add zeros rows to ys and ys_fit array if only one sensor data is present
if sensors == 1:
    ys = np.vstack((ys, np.zeros(len(ys))))
    ys_fit = np.vstack((ys_fit, np.zeros(len(ys_fit))))

# Collect series info
summary = []
width = 12
summary.append('Data info')
summary.append('---------')
summary.append('File'.ljust(width)+': ' + filename.name)
summary.append('Directory'.ljust(width)+': ' + curdir)
summary.append(dataline('Sensors', sensors))
summary.append(dataline('Data rows', len(xs)))
summary.append(dataline('Time (s)', xs[-1]))
summary.append(dataline('Time (min)', xs[-1] / 60 , 2))
summary.append(dataline('Target (min)', target_time, 2))
if is_full_range:
    summary.append(dataline('Range (min)', linefit_time, 2))
else:
    summary.append('Range'.ljust(width)+': all')
summary.append(dataline('Interval (s)', interval, 0))
    
# Calculate slope and statistics for temperature series
i = 0
results = []
while i < sensors:
    # Get slope and coefficient for the fitted line
    k, c = np.polyfit(xs_fit, ys_fit[i], 1)
    delta_y = line(xs_fit[-1], k, c) - line(xs_fit[0], k, c)
    n = len(ys_fit[i])
    if n < 2:
        sys.exit('At least two measurements is needed for the analysis.')
    mean = np.mean(ys_fit[i])
    median = np.median(ys_fit[i])
    sem = st.sem(ys_fit[i])
    ymin = np.min(ys_fit[i])
    ymax = np.max(ys_fit[i])
    
    if np.isclose(sem, 0):
        # NEW: constant series → no variation
        method = 'Constant value'
        ci_low = ci_high = mean
        ci_half = 0
    else:
        if n <= 30:
            method = "Student's t distribution"
            dof = n - 1
            ci_low, ci_high = st.t.interval(alpha, dof, loc=mean, scale=sem)
        else:
            method = 'Normal distribution'
            ci_low, ci_high = st.norm.interval(alpha, loc=mean, scale=sem)
        ci_half = (ci_high - ci_low) / 2    
       
    results.append([i+1, k, c, linefit_time, delta_y,
                    n, ymin, ymax, mean, median,
                    method, alpha, ci_low, ci_high, ci_half, sem])
    i += 1
    
names = ['Sensor', 'Slope', 'Constant', 'Time', 'Delta °C',
         'Trials', 'Min', 'Max', 'Mean', 'Median',
         'Method', 'Alpha', 'CI lower', 'CI upper', 'CI half', 'SEM']

precisions = [0, -1, 2, 0, 4,
              0, 3, 3, 3, 3,
              -1, 3, 4, 4, 4, -1]

if linefit_time < 10:
    precisions[3] = 1

is_open = False
if create_files:
    try:
        file_path = Path(os.path.join(adir, 'analysis.txt'))
        f = open(file_path,'w', encoding = 'utf_8')
        is_open = True
    except:
        print('Unable to save analysis file.')
print('')

# Display and save statistics
if is_info:
    for r in summary:
        print(r)
    print('')

# Write summary to the file
if is_open:
    for r in summary:
        try:
            f.write(r+'\n')
        except:
            print('Unable to save data into the analysis file.')

i = 0
for r in results:
    rows = generate_stats(names, r, precisions)
    if i == 0 and is_open:
        f.write('\n')
    elif i > 0:
        print('')
        if is_open:
            f.write('\n')
    for row in rows:
        print(row)
        if is_open:
            try:
                f.write(row+'\n')
            except:
                print('Unable to save data into the analysis file.')
    i += 1

if is_open:
    f.close()

if (True not in [create_lines_full, create_lines_range, create_diff_graph, create_combo_range]) or not create_files:
    sys.exit(0) # Exit if all is done


# Graphs section START
for data in results:
    sensor = data[0]
    index = sensor - 1
    k = data[1]
    c = data[2]
    # x_label = names[3]
    y_label = 'Temperature (°C)'

    if create_lines_full and is_full_range:
        reg_xs = np.array([xs[0], xs[-1]])
        reg_ys = np.array([k * reg_xs[0] + c, k * reg_xs[-1] + c])
        fig = plt.figure()
        unit, divisor = get_unit(xs)
        xs_plot = xs / divisor
        xs_plot_reg = reg_xs / divisor
        x_label = get_xlabel(names[3], unit) 
        plt.xlabel(x_label)
        plt.ylabel(y_label)
        plt.plot(xs_plot, ys[index], '.', color='k', markersize = 2)
        if show_line_in_full:
            plt.plot(xs_plot_reg, reg_ys, color = 'k')
            y_min = min([min(ys[index]), min(reg_ys)])
            y_max = max([max(ys[index]), max(reg_ys)])
        else:
            y_min = min(ys[index])
            y_max = max(ys[index])
        plt.xlim(xs_plot[0], xs_plot[-1])

        plt.ylim(y_min, y_max)
        plt.grid()      
        fig.tight_layout()
        fname = 'temperature-full-s'
        fname += str(sensor)
        fname += '.png'
        file_path = Path(os.path.join(adir, fname))
        plt.savefig(file_path,dpi=300,bbox_inches='tight')
        plt.ticklabel_format(style='plain')
        plt.close(fig)
        
    if create_lines_range:
        reg_xs = np.array([xs_fit[0], xs_fit[-1]])
        reg_ys = np.array([k * reg_xs[0] + c, k * reg_xs[-1] + c])
        fig = plt.figure()
        unit, divisor = get_unit(reg_xs)
        x_label = get_xlabel(names[3], unit)
        plt.xlabel(x_label)
        plt.ylabel(y_label)
        xs_plot = xs_fit / divisor
        xs_plot_reg = reg_xs / divisor
        plt.plot(xs_plot, ys_fit[index], '.', color='k', markersize = 2)
        plt.plot(xs_plot_reg, reg_ys, color = 'k')
        plt.xlim(xs_plot[0], xs_plot[-1])
        y_min = min([min(ys_fit[index]), min(reg_ys)])
        y_max = max([max(ys_fit[index]), max(reg_ys)])
        plt.ylim(y_min, y_max)
        plt.grid()      
        fig.tight_layout()
        fname = 'temperature-range-s'
        fname += str(sensor)
        fname += '.png'
        file_path = Path(os.path.join(adir, fname))
        plt.savefig(file_path,dpi=300,bbox_inches='tight')
        plt.ticklabel_format(style='plain')
        plt.close(fig)

if create_combo_range:
    k1 = results[0][1]
    c1 = results[0][2]
    k2 = results[1][1]
    c2 = results[1][2]

    reg_xs = np.array([xs_fit[0], xs_fit[-1]])
    reg_ys1 = np.array([k1 * reg_xs[0] + c1, k1 * reg_xs[-1] + c1])
    reg_ys2 = np.array([k2 * reg_xs[0] + c2, k2 * reg_xs[-1] + c2])
    fig = plt.figure()
    unit, divisor = get_unit(xs_fit)
    x_label = get_xlabel(names[3], unit)
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    xs_plot = xs_fit / divisor
    xs_plot_reg = reg_xs / divisor
    plt.plot(xs_plot, ys_fit[0], '.', color='r', markersize = 2)
    plt.plot(xs_plot_reg, reg_ys1, color = 'r')
    plt.plot(xs_plot, ys_fit[1], '.', color='b', markersize = 2)
    plt.plot(xs_plot_reg, reg_ys2, color = 'b')
    plt.xlim(xs_plot[0], xs_plot[-1])
    y_min = min([min(ys_fit[0]), min(reg_ys1), min(ys_fit[1]), min(reg_ys2)])
    y_max = max([max(ys_fit[0]), max(reg_ys1), max(ys_fit[1]), max(reg_ys2)])
    plt.ylim(y_min, y_max)
    plt.grid()      
    fig.tight_layout()
    fname = 'temperature-range-(s1,s2)'
    fname += '.png'
    file_path = Path(os.path.join(adir, fname))
    plt.savefig(file_path,dpi=300,bbox_inches='tight')
    plt.ticklabel_format(style='plain')
    plt.close(fig)
        
if create_diff_graph:
    fig=plt.figure()
    ys_diff = ys_fit[1] - ys_fit[0]
    unit, divisor = get_unit(xs_fit)
    x_label = get_xlabel(names[3], unit)
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    xs_plot = xs_fit / divisor
    plt.plot(xs_plot, ys_diff, color = 'k')
    plt.xlim(xs_plot[0], xs_plot[-1])
    y_min = min(ys_diff)
    y_max = max(ys_diff)
    plt.ylim(y_min, y_max)
    plt.grid()      
    fig.tight_layout()
    fname = 'temperature-range-diff-(s2-s1)'
    fname += '.png'
    file_path = Path(os.path.join(adir, fname))
    plt.savefig(file_path,dpi=300,bbox_inches='tight')
    plt.ticklabel_format(style='plain')
    plt.close(fig)

# Graphs section END