#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extended rh-analysis.py to also create new calibration graphs with reference curves,
but only for the best calibration ranks, and optionally auto-choosing x-axis units.
Also checks the parent directory for merged CSV.
Original author: Kim
Modified for new graph requirements and auto x-axis.
"""

import pandas as pd
import argparse
import matplotlib.pyplot as plt
import os
import sys
from pathlib import Path
import re
import glob

def get_input_file_path(base_dir, file):
    """
    Search for the given file in a small directory list: current dir, cal/, cal/analysis/.
    Returns full path if found, else None.
    """
    dirs = ['', 'cal', 'cal/analysis']
    for d in dirs:
        target = os.path.join(base_dir, d, file)
        if os.path.isfile(target):
            return os.path.abspath(target)
    return None

def find_latest_merged_csv():
    """
    Look for merged-YYYYMMDD-hhmmss.csv in cal/, cal/analysis/, then the parent directory.
    Return the path to the most recent file or None if none found.
    """
    parent_dir = os.path.abspath('..')  # One level up from current directory

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
      If both rh_analysis.csv and merged CSV are in current dir => 'analysis-rh'
      Else if rh_analysis.csv is in cal/analysis => 'analysis-rh' (within cal/analysis)
      Otherwise default to 'analysis-rh'.
    """
    current_dir = os.path.abspath('.')
    rh_dir = os.path.dirname(os.path.abspath(rh_path)) if rh_path else ''
    merged_dir = os.path.dirname(os.path.abspath(merged_path)) if merged_path else ''

    if rh_dir == current_dir and merged_dir == current_dir:
        # both in current dir
        return os.path.join(current_dir, 'analysis-rh')
    # if rh_analysis in cal/analysis (or we see "analysis" in path)
    if 'cal/analysis' in rh_dir.replace('\\','/'):
        return os.path.join(rh_dir, 'analysis-rh')

    return os.path.join(current_dir, 'analysis-rh')

def read_and_filter_data(file_path, threshold):
    """
    Read the CSV file into a DataFrame and filter out rows where
    'Sum of abs(slope)' exceeds threshold.
    """
    df = pd.read_csv(file_path)
    df_filtered = df[df['Sum of abs(slope)'] <= threshold]
    return df_filtered

def analyze_column(data, col_mean_rhref, col_mean, targets):
    """
    For each target in 'targets', find the row whose col_mean is closest.
    Keep each rank only once. Return a list of (Rank, RHref, RHx).
    """
    results = []
    seen_ranks = []

    for target in targets:
        # find row with col_mean closest to target
        print(target)
        closest_row = data.iloc[(data[col_mean] - target).abs().argsort()[:1]].iloc[0]
        value = closest_row[col_mean]
        dist = abs(value - target)
        # skip if too far from target
        if target < 80 and dist > 5:
            continue
        elif dist > 2.5:
            continue
        if closest_row['Rank'] not in seen_ranks:
            results.append((int(closest_row['Rank']),
                            closest_row[col_mean_rhref],
                            closest_row[col_mean]))
            seen_ranks.append(closest_row['Rank'])

    # sort by sensor RH
    results_sorted = sorted(results, key=lambda x: x[2])
    return results_sorted

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

    ax.set_xlabel(x_label)  # auto-chosen or "Time (s)"
    ax.set_ylabel('%RH')
    ax.set_title('Calibration Levels')
    ax.grid(True, which='major')
    ax.legend(loc='upper left')
    plt.savefig(out_png, dpi=300)
    plt.close()

def main():
    analysis_dir = './analysis-rh'  # original default; we will override below if needed

    parser = argparse.ArgumentParser(description='Process RH Analysis Data.')
    parser.add_argument('file_path', type=str, help='Path to the CSV file (rh_analysis.csv).')
    parser.add_argument('-th', type=float, default=0.003, help='Threshold for "Sum of abs(slope)"')
    # NEW ARGUMENT: "-a" or "--auto" (store_true => becomes True if given, else False)
    parser.add_argument('-a', '--auto', action='store_true',
                        help='Automatically choose time-axis units for plateau plots.')
    args = parser.parse_args()

    # 1) Confirm rh_analysis.csv location
    dir_path = str(Path(args.file_path).parent.absolute())
    file_name = Path(args.file_path).name
    analysis_csv_path = get_input_file_path(dir_path, file_name)
    if analysis_csv_path is None:
        print(f'File {file_name} not found.')
        sys.exit()

    # 2) Find the latest merged CSV (including parent directory)
    merged_csv_path = find_latest_merged_csv()

    # 3) Decide output directory based on rules
    if merged_csv_path:
        analysis_dir = determine_target_directory(analysis_csv_path, merged_csv_path)

    # 4) Read/Filter rh_analysis.csv
    df = read_and_filter_data(analysis_csv_path, args.th)

    # Create analysis directory
    analysis_dir = Path(analysis_dir).absolute()
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # 5) Original steps: analyze ranks
    targets = list(range(0, 90, 10))
    targets.append(85)
    targets.append(90)
    targets.append(95)
    targets.append(100)

    # We'll keep these for plateau plotting:
    best_rh1_ranks = []
    best_rh2_ranks = []

    # Analyze RH1 if present
    if 'Mean: RH1% (%)' in df.columns:
        results_rh1 = analyze_column(df, 'Mean: RHref (%RH)', 'Mean: RH1% (%)', targets)
        csv_file = os.path.join(analysis_dir, 'rh1-ranks.csv')
        save_results_to_csv(results_rh1, csv_file, 'RH1%')
        png_file = os.path.join(analysis_dir, 'rh1-cal-levels.png')
        plot_results(df, results_rh1, 'Interval start (s)', 'Interval end (s)', 'Mean: RH1% (%)', png_file)

        # Save the best ranks for new plateau plotting
        best_rh1_ranks = [row[0] for row in results_rh1]  # row[0] is the Rank

    # Analyze RH2 if present
    if 'Mean: RH2% (%)' in df.columns:
        results_rh2 = analyze_column(df, 'Mean: RHref (%RH)', 'Mean: RH2% (%)', targets)
        csv_file = os.path.join(analysis_dir, 'rh2-ranks.csv')
        save_results_to_csv(results_rh2, csv_file, 'RH2%')
        png_file = os.path.join(analysis_dir, 'rh2-cal-levels.png')
        plot_results(df, results_rh2, 'Interval start (s)', 'Interval end (s)', 'Mean: RH2% (%)', png_file)

        # Save the best ranks
        best_rh2_ranks = [row[0] for row in results_rh2]

    # 6) Generate the new calibration plateau graphs if we have a merged CSV
    if merged_csv_path is not None and os.path.isfile(merged_csv_path):
        merged_df = pd.read_csv(merged_csv_path)

        # If sensor1 present -> rh1_cal_plateaus.png
        has_rh1 = ('RH1% (%)' in merged_df.columns) and ('Mean: RH1% (%)' in df.columns)
        if has_rh1 and best_rh1_ranks:
            # Subset df to only those rows whose "Rank" is in best_rh1_ranks
            df_rh1_subset = df[df['Rank'].isin(best_rh1_ranks)]
            out_png_1 = os.path.join(analysis_dir, 'rh1_cal_plateaus.png')
            plot_calibration_plateaus(
                merged_df=merged_df,
                analysis_subset=df_rh1_subset,
                sensor_mean_col='Mean: RH1% (%)',
                sensor_label='RH1% (%)',
                out_png=out_png_1,
                auto_scale=args.auto  # <--- new
            )

        # If sensor2 present -> rh2_cal_plateaus.png
        has_rh2 = ('RH2% (%)' in merged_df.columns) and ('Mean: RH2% (%)' in df.columns)
        if has_rh2 and best_rh2_ranks:
            df_rh2_subset = df[df['Rank'].isin(best_rh2_ranks)]
            out_png_2 = os.path.join(analysis_dir, 'rh2_cal_plateaus.png')
            plot_calibration_plateaus(
                merged_df=merged_df,
                analysis_subset=df_rh2_subset,
                sensor_mean_col='Mean: RH2% (%)',
                sensor_label='RH2% (%)',
                out_png=out_png_2,
                auto_scale=args.auto  # <--- new
            )
    else:
        print("No merged CSV found; skipping creation of new plateau graphs.")

if __name__ == '__main__':
    main()
