#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RH analysis & calibration tool (extended)
────────────────────────────────────────
* Added **linear‑regression** output for each RH sensor present (RH1% / RH2%).
  – Uses ``scipy.stats.linregress`` on the *selected calibration plateaus*.
  – Generates 300 dpi regression scatter + fit plots:
        • ``rh1%_(%)_regression.png``
        • ``rh2%_(%)_regression.png`` (only if RH2 present)
  – Writes plain‑text summaries (same base‑name ``.txt``) containing:
        slope, intercept, r‑value, r², stderr, p‑value, **N** (#points).
  – The summary is also echoed to the terminal.

All other behaviour of the original **rh‑analysis.py** is unchanged.

Author: Kim (orig.) – updated 2025‑05‑03
"""

import argparse
import glob
import os
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import json
from typing import Dict, Any, Tuple
from datetime import datetime           # NEW – for the log time‑stamp
from scipy.stats import linregress
from sklearn.linear_model import LinearRegression

# External helper – parses the “zone,num1[,num2]” string
from thpcaldb import parse_zone_numbers

def _regression_plot(x, y, slope, intercept, png_path, sensor_label):
    """Create scatter + fitted‑line plot (300 dpi)."""
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(x, y, s=40, alpha=0.75, label="data")

    xr = np.array([x.min() - 1, x.max() + 1])
    ax.plot(xr, slope * xr + intercept, lw=2, label=f"y = {slope:.4f}x + {intercept:.4f}")

    ax.set_xlim(0,100)
    ax.set_ylim(0,100)
    ax.xaxis.set_major_locator(plt.MultipleLocator(10))
    ax.yaxis.set_major_locator(plt.MultipleLocator(10))
    ax.set_xlabel(f"{sensor_label}")
    ax.set_ylabel("Reference (RH%)")
    ax.grid(True, ls="--", lw=0.5)
    ax.legend()
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    plt.savefig(png_path, dpi=300)
    plt.close(fig)


def _regression_summary(lr, n):
    """Return nicely formatted summary string (incl. N)."""
    return (
        "Linear Regression Results:\n"
        f"  Formula: y = {lr.slope:.4f}x + {lr.intercept:.4f}\n\n"
        f"  Slope:          {lr.slope:.4f}\n"
        f"  Intercept:      {lr.intercept:.4f}\n"
        f"  R-value:        {lr.rvalue:.4f}\n"
        f"  R-squared:      {lr.rvalue**2:.4f}\n"
        f"  Standard Error: {lr.stderr:.4f}\n"
        f"  P-value:        {lr.pvalue:.4g}\n"
        f"  N:              {n}\n"
    )


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


def determine_target_directory(rh_path, merged_path):
    """
    Decide output directory based on locations:
      If merged CSV is in current dir => 'analysis-rh'
      Else if rh_analysis.csv is in cal/analysis => 'analysis-rh' (within cal/analysis)
      Otherwise default to 'analysis-rh'.
    """
    current_dir = os.path.abspath('.')
    rh_dir = os.path.dirname(os.path.abspath(rh_path)) if rh_path else ''
    merged_dir = os.path.dirname(os.path.abspath(merged_path)) if merged_path else ''

    if merged_dir == current_dir:
        # both in current dir
        return os.path.join(current_dir, 'analysis-rh')
    # if rh_analysis in cal/analysis (or we see "analysis" in path)
    if 'cal/analysis' in rh_dir.replace('\\','/'):
        return os.path.join(rh_dir, 'analysis-rh')

    return os.path.join(current_dir, 'analysis-rh')


def read_and_filter_data(file_path):
    """
    Read the CSV file into a DataFrame and filter out rows where
    'Sum of abs(slope)' exceeds threshold.
    """
    df = pd.read_csv(file_path)
    df_filtered = df[['Time (s)','Measurement', 'RH1% (%)', 'RH2% (%)', 'RHref (%RH)']]
    
    # Caldict addition
    date_time = None
    try:
        date_time = df['Datetime'][0]
    except:
        print('Invalid log format. Datetime value not found in the first data row.')
        
    
    # return df_filtered
    return date_time, df_filtered


def analyze_column(data: pd.DataFrame, col_mean_rhref: str, col_mean: str, targets):
    """
    For each target in 'targets', find the row whose col_mean is closest.
    Keep each rank only once. Return a list of (Rank, RHref, RHx).
    """
    # quick sanity‑checks
    required = {"Rank", col_mean_rhref, col_mean}
    missing  = required.difference(data.columns)
    if missing:
        print("analyze_column → missing columns:", ", ".join(missing))
        return []

    if data.empty:
        return []

    results, seen_ranks = [], []

    for low, target, high in targets:
        # locate the single closest row
        closest = data.loc[(data[col_mean] - target).abs().idxmin()]
        value   = closest[col_mean]

        # skip if the closest point is outside the tolerance band
        if not (low <= value <= high):
            continue

        rank = int(closest["Rank"])
        if rank not in seen_ranks:
            results.append((rank, closest[col_mean_rhref], value))
            seen_ranks.append(rank)

    # sort by sensor RH ascending
    return sorted(results, key=lambda x: x[2])



def save_results_to_csv(results, file_path, value_col):
    """
    Save (Rank, RHref%, value_col) to CSV and a corresponding .txt.
    """
    headers = ['Rank', 'RHref%', value_col]
    df = pd.DataFrame(results, columns=headers)
    df.to_csv(file_path, index=False)

    txt_file_path = file_path.replace('.csv', '.txt')
    df_txt = df[['RHref%', value_col]]
    df_txt.to_csv(txt_file_path, index=False, header=True)


def plot_results(data, results, interval_col_start, interval_col_end, y_col, filename):
    """
    Original plot: horizontal lines (interval start->end) at sensor mean.
    """
    fig, ax = plt.subplots()

    # Create the plot
    for row in results:
        rank, rhref, rh = row
        interval_start = data[data['Rank'] == rank][interval_col_start].values[0]
        interval_end   = data[data['Rank'] == rank][interval_col_end].values[0]
        ax.hlines(y=rh, xmin=interval_start, xmax=interval_end, colors='r', linewidth=2)

    # Adding grid, labels, and title
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_locator(plt.MultipleLocator(10))
    ax.grid(True, which='both', linestyle='--', linewidth=0.5)
    ax.set_xlabel('Measurement Number')
    ax.set_ylabel(f'{y_col}')
    ax.set_title('Calibration Levels')
    plt.yticks([i for i in range(0, 101, 10)])
    ax.set_ylim(0, 100)

    # Save the plot
    plt.savefig(filename, dpi=300)
    plt.close()


# ---------------------------------------------------------------
# NEW CODE: Automatic scaling of the x-axis for the plateau plots
# ---------------------------------------------------------------
def get_time_scale_and_label(max_time_s):
    """
    Decide the scale factor and label based on the largest time in seconds.
    0-300 s:   use seconds (s)
    301-18000 s (5min-300min):  use minutes (min)
    18001-432000 s (5h-120h):   use hours (h)
    >432000 s (>120h):          use days (d)
    Returns (scale_factor, x_label).
    """
    if max_time_s <= 300:
        return 1.0, "Time (s)"
    elif max_time_s <= 18000:
        return 1.0 / 60.0, "Time (min)"
    elif max_time_s <= 432000:
        return 1.0 / 3600.0, "Time (h)"
    else:
        return 1.0 / 86400.0, "Time (d)"


def plot_calibration_plateaus(
    merged_df, analysis_subset,
    sensor_mean_col, sensor_label, out_png,
    auto_scale=False
):
    """
    - If auto_scale=True, determine the best time scale from merged_df['Time (s)'].max().
    - Plot merged_df time vs reference and sensor.
    - Only the intervals in analysis_subset are drawn as plateau lines and vertical offsets.
    """
    if 'Time (s)' not in merged_df.columns or 'RHref (%RH)' not in merged_df.columns:
        print("Merged CSV missing required columns for the new plateau plot.")
        return
    if sensor_label not in merged_df.columns or sensor_mean_col not in analysis_subset.columns:
        print(f"Missing required columns for sensor {sensor_label}. Skipping that plot.")
        return

    # Decide scaling
    if auto_scale:
        max_time_s = merged_df['Time (s)'].max()
        x_scale, x_label = get_time_scale_and_label(max_time_s)
    else:
        x_scale, x_label = (1.0, "Time (s)")

    # Create scaled X data for the entire merged file
    merged_x = merged_df['Time (s)'] * x_scale

    # Build the figure
    fig, ax = plt.subplots()

    # Plot reference (scaled X)
    ax.plot(merged_x, merged_df['RHref (%RH)'], label='Ref RH', color='tab:red')
    # Plot sensor
    ax.plot(merged_x, merged_df[sensor_label], label=sensor_label, color='tab:blue')

    # Overlay calibration intervals from analysis_subset, also scaled
    for _, row in analysis_subset.iterrows():
        start_s = row.get('Interval start (s)', None)
        end_s   = row.get('Interval end (s)', None)
        ref_val = row.get('Mean: RHref (%RH)', None)
        sensor_val = row.get(sensor_mean_col, None)

        if pd.isna(start_s) or pd.isna(end_s) or pd.isna(ref_val) or pd.isna(sensor_val):
            continue

        # Scale intervals
        start_x = start_s * x_scale
        end_x   = end_s * x_scale
        mid_x   = 0.5*(start_x + end_x)

        # Horizontal line at sensor mean
        ax.hlines(y=sensor_val, xmin=start_x, xmax=end_x, linestyles='-', color='k')
        # Also a horizontal line at ref mean (if desired)
        ax.hlines(y=ref_val, xmin=start_x, xmax=end_x, linestyles='-', color='k')
        # Vertical line
        ymin, ymax = sorted([ref_val, sensor_val])
        ax.vlines(x=mid_x, ymin=ymin, ymax=ymax, linestyles='-', color='k')

    ax.set_ylim(0, 100)
    ax.yaxis.set_major_locator(plt.MultipleLocator(10))
    ax.set_xlabel(x_label)  # auto-chosen or "Time (s)"
    ax.set_ylabel('%RH')
    ax.set_title('Calibration Levels')
    ax.grid(True, which='major')
    ax.legend(loc='upper left')
    plt.savefig(out_png, dpi=300)
    plt.close()


def compute_slope(df, xcol, ycol):
    """
    Compute linear regression slope (m) and intercept (c) for ycol vs xcol in df.
    Returns: (slope, intercept).
    """
    X = df.iloc[:, xcol].values.reshape(-1,1)
    Y = df.iloc[:, ycol].values.reshape(-1,1)
    reg = LinearRegression().fit(X, Y)
    coef = reg.coef_[0][0]
    i = reg.intercept_[0]
    return float(coef), float(i)


def add_rank(df, by='Sum of abs(slope)', ascending=True):
    """Return a copy of *df* with a 1‑based Rank column."""
    ranked = (
        df.sort_values(by, ascending=ascending)
          .reset_index(drop=True)
          .assign(Rank=lambda d: d.index + 1)
    )
    return ranked


def compute_targets(target_list):
    result = []
    levels = len(target_list)
    index = 0
    for level in target_list:
        is_low = False
        is_high = False
        
        # Get the target level:
        target = level
        
        # Handle first and lowest value
        if index == 0:
            low = 0
            is_low = True
        
        # Handle last and highest value
        if index == levels - 1:
            high = 100
            is_high = True
            
        # Compute lower limit
        if not is_low:
            low = target - (target - target_list[index-1]) / 2
        
        # Compute lower limit
        if not is_high:
           high  = target + (target_list[index+1] - target) / 2
        result.append([low, target, high])
        index += 1
    return result

# ───────────────────────────────────────────────────────────────────────────────
#  JSON‑based calibration‑file helpers (used if –cal is given)
# ───────────────────────────────────────────────────────────────────────────────


def _convert_value(val: str) -> Any:
    """Return float if possible, else raw string."""
    try:
        return float(val)
    except ValueError:
        return val


def find_thpcal_json() -> Tuple[str, bool]:
    """
    Search for 'thpcal.json' in:
      1. current dir
      2. parent dir
      3. /opt/tools
    """
    filename = 'thpcal.json'
    search_dirs = [
        os.getcwd(),
        os.path.abspath(os.path.join(os.getcwd(), os.pardir)),
        '/opt/tools'
    ]
    for directory in search_dirs:
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            print("Calibration file thpcal.json found in: " + directory)
            return path, True
    new_path = os.path.join(os.getcwd(), filename)
    print("Path to the new calibration file thpcal.json: " + os.getcwd())
    return new_path, False


def read_thpcal_json(
    filename: str
) -> Dict[int, Dict[str, Dict[str, Any]]]:
    """Load nested dict from JSON, converting top‐level keys back to int."""
    with open(filename, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    return { int(k): v for k, v in raw.items() }


def read_and_merge_thpcal_json(
    filename: str,
    new_entries: Dict[int, Dict[str, Dict[str, Any]]]
) -> Dict[int, Dict[str, Dict[str, Any]]]:
    """
    1) Load existing JSON (if any)
    2) Merge in `new_entries` at keys (number → sensor → type)
    3) Return merged dict
    """
    try:
        cal = read_thpcal_json(filename)
    except Exception:
        print('Creating a new thpcal.json file.')
        return new_entries
    for num, sensors in new_entries.items():
        cal.setdefault(num, {})
        for sensor, types in sensors.items():
            cal[num].setdefault(sensor, {})
            for t, info in types.items():
                cal[num][sensor][t] = info
    print('Merged new data with existing calibration file.')
    return cal


def write_thpcal_json(
    filename: str,
    cal_dict: Dict[int, Dict[str, Dict[str, Any]]]
) -> None:
    """Dump nested calibration dict to JSON (int keys → str)."""
    raw = { str(num): sensors for num, sensors in cal_dict.items() }
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    print('→ saved thpcal.json')


def main():
    analysis_dir = './analysis-rh'  # original default; we will override below if needed

    parser = argparse.ArgumentParser(description="Process RH Analysis Data with regression.")    
    parser.add_argument("-th", type=float,  default=0.001, help="Slope threshold for plateau detection")
    parser.add_argument("-s",  "--start",   type=int,   default=0,
                        help="First sample index to analyse")
    parser.add_argument("-w",  "--window",  type=int,   default=180,
                        help="Sliding‑window length (samples)")
    parser.add_argument("-i",  "--interval",type=int,   default=30,
                        help="Step between windows (samples)")
    parser.add_argument("-maxdiff", "--maxdiff", type=float, default=10,
                        help="Max allowed |RHsensor – RHref| (%%RH)")
    parser.add_argument("-a",  "--auto",    action="store_true",
                        help="Auto‑scale X‑axis time units")
    
    # Optional calibration and datetime‑zero flags
    parser.add_argument(
        "-cal",
        metavar="SPEC",
        type=str,
        help="Calibration spec zone,num1[,num2] (e.g. -cal C11,12). If omitted, no cal JSON is produced.",
    )
    parser.add_argument(
        "-z",
        action="store_true",
        help="Zero the time component of the stored datetime (→ 00:00:00)",
    )
    
    args = parser.parse_args()

    th           = args.th
    start        = args.start
    window       = args.window
    interval     = args.interval
    max_rh_diff  = args.maxdiff
    auto_scale   = args.auto             # use when calling plot_calibration_plateaus
    
    # ----------------------------------------------------------------------
    # If -cal is provided, derive sensor codes
    # ----------------------------------------------------------------------
    sensor_code_map: Dict[str, str] = {}
    if args.cal:
        try:
            zone, num1, num2 = parse_zone_numbers(args.cal)
            if num1 is not None:
                sensor_code_map["RH1% (%)"] = f"{zone}{num1}"
            if num2 is not None:
                sensor_code_map["RH2% (%)"] = f"{zone}{num2}"
        except Exception as exc:
            print(f"Invalid -cal spec '{args.cal}': {exc}. Skipping calibration JSON generation.")
            args.cal = None  # disable cal path    
       
    target_levels = [0,
               10,
               20,
               30,
               40,
               50,
               60,
               70,
               80,
               85,
               90,
               95,
               100]
    
    targets = compute_targets(target_levels)

    # 1) Get current directory
    curdir = os.getcwd()
    dir_path = Path(curdir)

    # 2) Find the latest merged CSV (including parent directory)
    merged_csv_path = find_latest_merged_csv()
    if merged_csv_path is None:
        print('Merge file not found.')
        sys.exit()

    # 3) Read/Filter rh_analysis.csv and build calibration timestamp
    cal_dt, df = read_and_filter_data(merged_csv_path)
    # Remove nan rows
    df.dropna(inplace=True)
    length = len(df)
    if args.z and cal_dt:
        cal_dt = cal_dt[:10] + " 00:00:00"

    # 4) Determine sensor count
    ref_col = ''
    if 'RHref (%RH)' in df.columns:
        ref_col = df.columns.get_loc('RHref (%RH)')
    has_sensor1 = False
    has_sensor2 = False
    if 'RH1% (%)' in df.columns:
        sensor_col1 = df.columns.get_loc('RH1% (%)')
        has_sensor1 = True
    if 'RH2% (%)' in df.columns:
        sensor_col2 = df.columns.get_loc('RH2% (%)')
        has_sensor2 = True

    # 5) Create analysis directory
    print('1. Creating analysis directory and a log file.')
    analysis_dir = Path(analysis_dir).absolute()
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # ── argument log ───────────────────────────────────────────────────────
    log_path = analysis_dir / "thp-args.log"
    defaults = dict(th=0.001, start=0, window=180, interval=30,
                    maxdiff=10, auto=False)
    
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(f"{datetime.now().isoformat(timespec='seconds')}\n")
        fh.write(f"{merged_csv_path}\n")
    
        # Produce “‑opt=value” list, mark overrides with “*”
        for key, dflt in defaults.items():
            val = getattr(args, key if key != "maxdiff" else "maxdiff")
            mark = " *" if val != dflt else ""
            if key == "auto":
                # boolean flag prints only when set, per spec
                line = "-a" + mark if val else "-a=False"
            else:
                line = f"-{key}={val}{mark}"
            fh.write(line + "\n")
    # ───────────────────────────────────────────────────────────────────────
        
    # ------------------------------------------------------------------
    # 0.  Describe each sensor *once*
    # ------------------------------------------------------------------
    sensors = [
        {   # reference sensor (only slopes & mean/min/max used for checks)
            "role":  "ref",                        # used for special tests
            "name":  "RHref%",                    # pretty‑print label
            "col":   "RHref (%RH)",               # column name in df
            "slope": None,                        # slope cached per window
            "col_idx": ref_col,                   # numeric column index
            "active": True                        # always present
        },
        {
            "role":  "measure",
            "name":  "RH1%",
            "col":   "RH1% (%)",
            "col_idx": sensor_col1,
            "active": has_sensor1
        },
        {
            "role":  "measure",
            "name":  "RH2%",
            "col":   "RH2% (%)",
            "col_idx": sensor_col2,
            "active": has_sensor2
        },
    ]



    # --- BEFORE the sliding‑window loop -----------------------------
    ref_name   = 'RHref (%RH)'      #  ← include "(%RH)"
    sensor1    = 'RH1% (%)'
    sensor2    = 'RH2% (%)'

    # ------------------------------------------------------------------
    # 1.  Container for result rows, keyed by sensor label
    # ------------------------------------------------------------------
    core_cols = [
        "Start index", "End index", "N",
        "Interval start (s)", "Interval end (s)",
        "Sum of abs(slope)"
    ]
    result_frames = {
        s["name"]: pd.DataFrame(columns=core_cols + [
            f"Slope: {ref_name}",   f"Slope: {s['col']}",
            f"Mean: {ref_name}",    f"Mean: {s['col']}",
            f"Min: {ref_name}",     f"Max: {ref_name}",
            f"Min: {s['col']}",     f"Max: {s['col']}"
        ])
        for s in sensors if s["role"] == "measure"
    }    
        
    # Define loop variables
    pos = start
    time_col = 0
    
    # Minium and maximum allowed sensor values
    min_val = 0.01
    max_val = 99.99
    
    
    # ------------------------------------------------------------------
    # 2.  Sliding‑window loop
    # ------------------------------------------------------------------
    print("2. Performing linear regression analyses.")
    pos = start
    while pos < length - 1:             # need ≥ 2 data points
        win = df.iloc[pos : pos + window]
    
        # --------------------------------------------------------------
        # 2a. compute reference‑sensor stats once per window
        # --------------------------------------------------------------
        ref     = next(s for s in sensors if s["role"] == "ref")
        ref_vec = win[ref["col"]].values
    
        # skip whole window if reference contains clamped values
        if ref_vec.min() < min_val or ref_vec.min() > max_val:
            pos += interval
            continue
    
        pos_end         = pos + len(win) - 1
        mean_ref        = ref_vec.mean()
        ref["slope"], _ = compute_slope(win, time_col, ref["col_idx"])
    
        # --------------------------------------------------------------
        # 2b. loop over each measurement sensor
        # --------------------------------------------------------------
        for s in sensors:
            if s["role"] != "measure" or not s["active"]:
                continue
    
            vec = win[s["col"]].values
    
            # --- validity checks --------------------------------------
            proceed = (min_val <= vec.min() <= max_val)
            if proceed and abs(vec.mean() - mean_ref) > max_rh_diff:
                proceed = False
            if not proceed:
                continue
    
            # --- slope + combined slope threshold ---------------------
            s["slope"], _   = compute_slope(win, time_col, s["col_idx"])
            sum_abs_slopes  = abs(ref["slope"]) + abs(s["slope"])
            if sum_abs_slopes > th:
                continue     # skip storing this window
    
            # --- store summary row ------------------------------------
            result_frames[s["name"]].loc[len(result_frames[s["name"]])] = {
                "Start index":          pos,
                "End index":            pos_end,
                "N":                    len(win),
                "Interval start (s)":   win["Time (s)"].iat[0],
                "Interval end (s)":     win["Time (s)"].iat[-1],
                "Sum of abs(slope)":    sum_abs_slopes,
                
                f"Slope: {ref_name}":      ref["slope"],
                f"Slope: {s['col']}":      s["slope"],
                f"Mean: {ref_name}":       mean_ref,
                f"Mean: {s['col']}":       vec.mean(),
                f"Min: {ref_name}":        ref_vec.min(),
                f"Max: {ref_name}":        ref_vec.max(),
                f"Min: {s['col']}":        vec.min(),
                f"Max: {s['col']}":        vec.min(),
            }
    
        # --------------------------------------------------------------
        pos += interval
    
    # ------------------------------------------------------------------
    # 3.  Tidy result DataFrames
    # ------------------------------------------------------------------
    print('3. Ranking best slopes.')
    if has_sensor1:
        res1 = result_frames["RH1%"]   # RH1% results
    if has_sensor2:
        res2 = result_frames["RH2%"]   # RH2% results
       

    # We'll keep these for plateau plotting:
    best_rh1_ranks = []
    best_rh2_ranks = []

    # Analyze RH1 if present
    if has_sensor1:
        res1        = add_rank(res1)                    # gives the Rank column
        results_rh1 = analyze_column(res1,
                                     f"Mean: {ref_name}",
                                     f"Mean: {sensor1}",
                                     targets)
    
        csv_file = os.path.join(analysis_dir, 'rh1-ranks.csv')
        save_results_to_csv(results_rh1, csv_file, 'RH1%')
    
        png_file = os.path.join(analysis_dir, 'rh1-cal-levels.png')
        plot_results(res1,                # ← was df
                     results_rh1,
                     'Interval start (s)', 'Interval end (s)',
                     f"Mean: {sensor1}",  # keeps the label consistent
                     png_file)

        # Save the best ranks for new plateau plotting
        best_rh1_ranks = [row[0] for row in results_rh1]  # row[0] is the Rank

    # Analyze RH2 if present
    if has_sensor2:
        res2        = add_rank(res2)
        results_rh2 = analyze_column(res2,
                                     f"Mean: {ref_name}",
                                     f"Mean: {sensor2}",
                                     targets)
    
        csv_file = os.path.join(analysis_dir, 'rh2-ranks.csv')
        save_results_to_csv(results_rh2, csv_file, 'RH2%')
    
        png_file = os.path.join(analysis_dir, 'rh2-cal-levels.png')
        plot_results(res2,                # ← was df
                     results_rh2,
                     'Interval start (s)', 'Interval end (s)',
                     f"Mean: {sensor2}",
                     png_file)
    
        # Save the best ranks
        best_rh2_ranks = [row[0] for row in results_rh2]


    print('4. Saving analysis files.')
    if has_sensor1 and not res1.empty:
        res1.to_csv(os.path.join(Path(merged_csv_path).parent, 'rh1_analysis.csv'), index=False)
    if has_sensor2 and not res2.empty:
        res1.to_csv(os.path.join(Path(merged_csv_path).parent, 'rh2_analysis.csv'), index=False)


    # ------------------------------------------------------------------
    #  After plateau selection → perform linear regression(s)
    # ------------------------------------------------------------------
    print('5. Perform linear regression(s)')    
    sensors_info = [
        ("RH1% (%)", best_rh1_ranks if "best_rh1_ranks" in locals() else [], res1 if "res1" in locals() else None),
        ("RH2% (%)", best_rh2_ranks if "best_rh2_ranks" in locals() else [], res2 if "res2" in locals() else None),
    ]

    results = {}
    for sensor_col, ranks, res_df in sensors_info:
        # Skip missing dataframes or empty rank lists
        if res_df is None or not ranks:
            continue

        # Subset rows belonging to the chosen plateaus **inside the dedicated dataframe**
        subset = res_df[res_df["Rank"].isin(ranks)]
        if subset.empty:
            continue

        x = subset[f"Mean: {sensor_col}"].values
        y = subset["Mean: RHref (%RH)"].values

        lr = linregress(x, y)
        
        # --- add calibration results to JSON-ready dict -----------------
        num         = 1 if sensor_col.startswith("RH1") else 2
        sensor_code = sensor_code_map.get(sensor_col, f"S{num}")
    
        results.setdefault(num, {}).setdefault(sensor_code, {})['H'] = {
        "datetime": cal_dt
                   if cal_dt
                   else datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "label":    "Relative humidity",
        "name":     sensor_col.replace(" (%)", ""),
        "col":      sensor_col,
        "slope":    lr.slope,
        "constant": lr.intercept,
        "r2":       lr.rvalue ** 2,
    }
    # ---------------------------------------------------------------

        # Filenames (match requested pattern: rh1%_(%)_regression.png, etc.)
        base = sensor_col.lower().replace(" ", "_")  # "rh1%_(%)"
        png_path = analysis_dir / f"{base}_regression.png"
        txt_path = analysis_dir / f"{base}_regression.txt"

        _regression_plot(x, y, lr.slope, lr.intercept, png_path, sensor_col)
        summary_txt = _regression_summary(lr, len(x))

        # Write .txt summary and echo to terminal
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(summary_txt)
        print(f"\nRegression summary for {sensor_col}:")
        print(summary_txt)

    # -----------------------------------------------------------
    #  Create new calibration plateau graphs (reuse in‑memory data)
    # -----------------------------------------------------------
    # `df` already holds the merged CSV (filtered) so we don’t read it again.
    print('6. Create calibration plateau graphs')
    merged_df = df  # alias for clarity

    if not merged_df.empty:
        # ── RH1 ───────────────────────────────────────────────
        if has_sensor1 and best_rh1_ranks:
            rh1_subset = res1[res1["Rank"].isin(best_rh1_ranks)]
            if not rh1_subset.empty:
                out_png_1 = os.path.join(analysis_dir, "rh1_cal_plateaus.png")
                plot_calibration_plateaus(
                    merged_df=merged_df,
                    analysis_subset=rh1_subset,
                    sensor_mean_col="Mean: RH1% (%)",
                    sensor_label="RH1% (%)",
                    out_png=out_png_1,
                    auto_scale=args.auto,
                )

        # ── RH2 ───────────────────────────────────────────────
        if has_sensor2 and best_rh2_ranks:
            rh2_subset = res2[res2["Rank"].isin(best_rh2_ranks)]
            if not rh2_subset.empty:
                out_png_2 = os.path.join(analysis_dir, "rh2_cal_plateaus.png")
                plot_calibration_plateaus(
                    merged_df=merged_df,
                    analysis_subset=rh2_subset,
                    sensor_mean_col="Mean: RH2% (%)",
                    sensor_label="RH2% (%)",
                    out_png=out_png_2,
                    auto_scale=args.auto,
                )
    else:
        print("No data in merged DataFrame; skipping creation of new plateau graphs.")

    # -----------------------------------------------------------------
    # 6.  Optionally create / update thpcal.json
    # -----------------------------------------------------------------
    if args.cal and results:
        print("7. Creating/updating calibration file.")

        json_path, exists = find_thpcal_json()
        merged = read_and_merge_thpcal_json(json_path, results) if exists else results
        write_thpcal_json(json_path, merged)


if __name__ == '__main__':
    main()
