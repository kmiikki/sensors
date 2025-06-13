#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jun  4 10:41:43 2025

@author: Kim Miikki
"""
# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import argparse                      # ADDED: command‑line argument parsing
import datetime
import glob
import os
import re
import sys
from datetime import datetime
from pathlib import Path
# ---------------------------------------------------------------------------
# Third‑party imports
# ---------------------------------------------------------------------------
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split


def find_latest_merged_csv():
    """
    Look for merged-YYYYMMDD-hhmmss.csv in cal/, cal/analysis/, then the parent directory.
    Return the path to the most recent file or None if none found.
    """
    parent_dir = os.path.abspath('.')  # One level up from current directory

    # Directories to check in order:
    dirs_to_check = [
        'cal',
        os.path.join('cal', 'analysis'),
        parent_dir
    ]

    pattern = re.compile(r'merged-(\d{8}-\d{6})\.csv$')
    candidates = []

    for d in dirs_to_check:
        if not os.path.isdir(d):
            continue
        files = glob.glob(os.path.join(d, 'merged-*.csv'))
        for f in files:
            fname = os.path.basename(f)
            match = pattern.match(fname)
            if match:
                dt_str = match.group(1)  # e.g. 20250407-114016
                # convert "YYYYMMDD-HHMMSS" -> integer "YYYYMMDDHHMMSS"
                dt_int = int(dt_str.replace('-', ''))
                candidates.append((dt_int, os.path.abspath(f)))
    if not candidates:
        return None

    # sort descending by dt_int => pick the newest
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def read_and_filter_data(file_path):
    """
    Read the CSV file into a DataFrame and filter out rows where
    'Sum of abs(slope)' exceeds threshold.
    """
    df = pd.read_csv(file_path)
    df_filtered = df[['Time (s)','Measurement', 'RH1% (%)', 'RH2% (%)', 'RHref (%RH)']]
    return df_filtered


# ---------------------------------------------------------------------------
# Helper: pretty print & optionally save regression results
# ---------------------------------------------------------------------------

def report_regression(stats: dict,
                      sensor_label: str,
                      input_file: str,
                      save_to_file: bool = True) -> None:
    """Print a neat summary **and** (optionally) write it to a *.txt* file.

    New in this patch:
        * Adds formula *y = ax + b* and R² to the output
        * Embeds timestamp & input filename for provenance
        * Re‑usable for both RH1 and RH2 sensors
    """

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    a = stats['slope']
    b = stats['intercept']
    formula = f"y = {a:.4f}x + {b:.4f}"
    mse = stats['mse']
    r2 = stats['r2']
    n_train = stats['n_train']
    n_test = stats['n_test']
    number = re.findall('\d+', sensor_label)[0]

    lines = [
        f"Analysis time : {ts}",
        f"Input file    : {input_file}",
        f"Sensor        : {number}",
        f"Formula       : {formula}",
        f"Intercept     : {b:.4f}",
        f"Coefficient   : {a:.4f}",
        f"N (training)  : {n_train}",
        f"N (test)      : {n_test}",
        f"Test MSE      : {mse:.4f}",
        f"Test R²       : {r2:.4f}",
    ]

    # --- console output ---------------------------------------------------
    for ln in lines:
        print(ln)

    # --- optional file output --------------------------------------------
    if save_to_file:
        out_name = sensor_label.lower().replace('%', '').replace(' ', '') + "_rhref_regression.txt"
        with open(out_name, 'w', encoding='utf-8') as fh:
            for ln in lines:
                fh.write(ln + "\n")
        print(f'→ saved stats to {out_name}')


# ---------------------------------------------------------------------------
# NEW: Regression engine
# ---------------------------------------------------------------------------
def run_regression(xs: np.ndarray, ys: np.ndarray):
    X = xs.reshape(-1, 1)
    y = ys

    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.30, random_state=42, shuffle=True)

    mdl = LinearRegression().fit(Xtr, ytr)
    yhat = mdl.predict(Xte)

    stats = {
        'intercept': mdl.intercept_,
        'slope':     float(mdl.coef_[0]),
        'mse':       mean_squared_error(yte, yhat),
        'r2':        r2_score(yte, yhat),
        'n_train':   len(Xtr),
        'n_test':    len(Xte)
    }
    return mdl, Xte, yte, yhat, stats


# ---------------------------------------------------------------------------
# NEW: Plot function
# ---------------------------------------------------------------------------
def plot_calib(x_test: np.ndarray,
               y_pred: np.ndarray,
               stats: dict,
               label: str,
               make_graph: bool):
    if not make_graph:
        return

    x_max = x_test.max()
    x_end = 100 if x_max >= 50 else int(np.ceil(x_max / 10.0)) * 10
    x_end = max(x_end, 10)

    y_min = y_pred.min()
    y_start = 0 if y_min >= 0 else int(np.floor(y_min / 10.0)) * 10


    fig, ax = plt.subplots()
    ax.scatter(x_test, y_pred, marker='.', alpha=0.2, color='blue', label='data')

    xs = np.array([0, x_end])
    ys = stats['slope'] * xs + stats['intercept']
    y_max = np.max(ys)
    y_end = 100 if x_end == 100 and y_max <= 100 else int(np.ceil(y_max / 10.0)) * 10

    ax.plot(xs, ys, color='black',
            label=f'y = {stats["slope"]:.4f}x + {stats["intercept"]:.4f}\n'
                  f'R² = {stats["r2"]:.4f}')

    ax.set_xlim(0, x_end)
    ax.set_ylim(y_start, y_end)
    ax.set_xlabel(f'{label.upper()} (%)')
    ax.set_ylabel('RHref (%)')
    ax.set_title('Relative humidity regression')
    ax.grid(True, linestyle=':', linewidth=0.5)
    ax.legend()

    out_png = label.lower().replace('%', '').replace(' ', '') + "_rhref_regression.png"
    fig.savefig(out_png, dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(f'→ saved plot to {out_png}')


def main():
    
    """Main entry point.

    Modifications in this patch:
        * argparse for -i -s -e -n -N
        * user‑controlled clipping that *cannot* widen original bounds
        * delegates summary printing & plotting to helper functions
    """
    print('rh-linreg analysis - Kim Miikki 2025')
    # ------------------------------------------------------------------
    # 0.  Parse command‑line arguments
    # ------------------------------------------------------------------
    parser = argparse.ArgumentParser(description="Linear calibration of BME280 against Vaisala reference.")
    parser.add_argument('-i', '--input', metavar='FILE', help='Input CSV (merged-*.csv). If omitted, auto‑detect.')
    parser.add_argument('-s', '--start', type=float, metavar='SEC', help='Clip *start* time in seconds (further restrict).')
    parser.add_argument('-e', '--end',   type=float, metavar='SEC', help='Clip *end* time in seconds (further restrict).')
    parser.add_argument('-n', action='store_true', help='Do NOT create graphs.')
    parser.add_argument('-N', action='store_true', help='Do NOT create graphs or analysis files.')
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1.  Determine input file & initial clip values
    # ------------------------------------------------------------------
    # Program default
    x_start = 0

    # 1a) current directory (kept for compatibility)
    curdir = os.getcwd()
    dir_path = Path(curdir)

    # 1b) Locate merged CSV
    merged_csv_path = args.input if args.input else find_latest_merged_csv()
    if merged_csv_path is None or not Path(merged_csv_path).is_file():
        print('Merge file not found.')
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2.  Read & optionally restrict by -s / -e
    # ------------------------------------------------------------------
    df = read_and_filter_data(merged_csv_path)

    # Translate -s / -e (seconds) into *indices* using the Time (s) column
    # They may only *reduce* the default span, never extend it.
    time_col = df['Time (s)'].to_numpy()

    # Start clip
    if args.start is not None:
        idx_candidates = np.where(time_col >= args.start)[0]
        if idx_candidates.size:
            new_start_idx = int(idx_candidates[0])
            # Only shrink (move forward in time)
            if new_start_idx > x_start:
                x_start = new_start_idx

    # End clip (initially full length)
    global_end_idx = len(df) - 1
    if args.end is not None:
        idx_candidates = np.where(time_col <= args.end)[0]
        if idx_candidates.size:
            new_end_idx = int(idx_candidates[-1])
            # Only shrink (move backward in time)
            if new_end_idx < global_end_idx:
                global_end_idx = new_end_idx
    
    
    # 1) Get current directory
    curdir = os.getcwd()
    dir_path = Path(curdir)

    # 2) Find the latest merged CSV (including parent directory)
    merged_csv_path = find_latest_merged_csv()
    if merged_csv_path is None:
        print('Merge file not found.')
        sys.exit()

    # 3) Read/Filter rh_analysis.csv
    df = read_and_filter_data(merged_csv_path)
    length = len(df)
    x_end = len(df)
    
    # 4) Determine sensor count
    ref_col = ''
    if 'RHref (%RH)' in df.columns:
        ref_col = df.columns.get_loc('RHref (%RH)')
        refs = np.array(df.iloc[:, ref_col])
    has_sensor1 = False
    has_sensor2 = False
    if 'RH1% (%)' in df.columns:
        sensor_col1 = df.columns.get_loc('RH1% (%)')
        has_sensor1 = True
    if 'RH2% (%)' in df.columns:
        sensor_col2 = df.columns.get_loc('RH2% (%)')
        has_sensor2 = True

    # Decribe sensors
    sensors = [
        {   # reference sensor (only slopes & mean/min/max used for checks)
            "role":  "ref",                        # used for special tests
            "name":  "RHref%",                    # pretty‑print label
            "col":   "RHref (%RH)",               # column name in df
            "start": -1,
            "end": -1,
            "col_idx": ref_col,                   # numeric column index
            "active": True                        # always present
        },
        {
            "role":  "measure",
            "name":  "RH1%",
            "col":   "RH1% (%)",
            "data": [],
            "median": -1,
            "start": -1,
            "end": -1,
            "col_idx": sensor_col1,
            "active": has_sensor1
        },
        {
            "role":  "measure",
            "name":  "RH2%",
            "col":   "RH2% (%)",
            "data": [],
            "median": -1,
            "start": -1,
            "end": -1,
            "col_idx": sensor_col2,
            "active": has_sensor2
        },
    ]

    if has_sensor1:
        sensors[1]["data"]= np.array(df.iloc[:, sensor_col1])
    if has_sensor2:
        sensors[2]["data"]= np.array(df.iloc[:, sensor_col2])


    # Minium and maximum allowed sensor values
    min_val = 0.01
    max_val = 99.99

    is_drying = (refs[-1] - refs[0] < 0)
    
    # Check reference valid range ---------------------------------------------
    if is_drying:
        mins = np.where(refs < min_val)[0]
        if len(mins) > 0:
            sensors[0]['end'] = mins[0] -1
        else:
            sensors[0]['end'] = len(refs)
    else:
        maxs = np.where(refs > max_val)[0]
        if len(maxs) > 0:
            sensors[0]['end'] = maxs[0] - 1
        else:
            sensors[0]['end'] = len(refs)
    sensors[0]['start'] = x_start

    # Loop trough sensors
    i = 1
    while i <= 2:
        # Check if sensor data is found
        if not sensors[i]['active']:
            i += 1
            continue

        print("")    
        # Determine valid ranges
        sensors[i]['start'] = 0
        if is_drying:
            mins = np.where(sensors[i]["data"] < min_val)[0]
            if len(mins) > 0:
                sensors[i]['end'] = mins[0] - 1
            else:
                sensors[i]['end'] = len(sensors[1]["data"])
        else:
            maxs = np.where(sensors[i]["data"] > max_val)[0]
            if len(maxs) > 0:
                sensors[i]['end'] = maxs[0] - 1
            else:
                sensors[i]['end'] = len(sensors[1]["data"])

        # Clip from the beginning
        sensors[i]['start'] = x_start
        
        # Set x0
        a = sensors[0]['start']
        b = sensors[i]['start']
        if a >= b:
            x0 = a
        else:
            x0 = b
        
        # Set x1
        a = sensors[0]['end']
        b = sensors[i]['end']
        if a <= b:
            x1 = a
        else:
            x1 = b 
        
        # Respect global end limit (‑e) for *each* sensor
        if 'global_end_idx' in locals():
            x1 = min(x1, global_end_idx)

        # Crop xs and ys ---------------------------------------------------
        xs = sensors[i]['data'][x0:x1]
        ys = refs[x0:x1]
        
        mdl, Xte, yte, yhat, stats = run_regression(xs, ys)
               
        # -----------------------------------------------------------------
        # 5.  Reporting & optional file output
        # -----------------------------------------------------------------
        sensor_label = sensors[i]['name']
        report_regression(stats, sensor_label, merged_csv_path,
                              save_to_file= not (args.N))

        # -----------------------------------------------------------------
        # 6.  Optional graph generation
        # -----------------------------------------------------------------
        plot_calib(Xte.flatten(), yhat, stats,
                   label=sensor_label,
                   make_graph=not (args.n or args.N))        

        i += 1
   

if __name__ == '__main__':
    main()