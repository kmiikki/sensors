#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Example script that:
 1) Finds merged-*.csv
 2) (Optionally) renames columns "t1 (°C)" -> "t1" internally for convenience
 3) For each BME sensor (t1, t2), tries shifting Tref in a user-specified range
    to minimize std of (Tref - Tsensor). Saves shift vs. std dev results in:
       tshift-temp.png, tshift-temp-t1.csv, [tshift-temp-t2.csv]
 4) Builds a time-aligned DataFrame => talign-thp.csv
 5) Performs the temperature plateau detection with linear regression in
    sliding windows => slopes-t1.csv / slopes-t2.csv, etc.
 6) Creates final “calibration” points => t1-ranks.csv / t2-ranks.csv
 7) Everything is saved under analysis-t/ except for the final 'talign-thp.csv'
    and 'tshift-temp*.csv' which are in the working dir for demonstration.

Author: <Kim Miikki>
Created: 2025-01-30
"""

import os
import sys
import argparse
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from sklearn.linear_model import LinearRegression

###############################################################################
# PART A) SHIFT LOGIC
###############################################################################

def compute_std_for_shift(sens_time, sens_temp, ref_time, ref_temp, shift):
    """
    Shift Tref by 'shift' => (ref_time + shift).
    Interpolate Tref onto sens_time, compute std of (Tref_interpolated - Tsensor).
    Returns (std_diff, overlap_mask).
      - overlap_mask is True/False for each sens_time point that lies within
        the overlapping region after the shift.
      - If there's no overlap, returns (np.inf, None).
    """
    shifted_ref_time = ref_time + shift
    
    # Determine overlapping time window
    t_min = max(shifted_ref_time.min(), sens_time.min())
    t_max = min(shifted_ref_time.max(), sens_time.max())
    if t_min >= t_max:
        return np.inf, None
    
    overlap_mask = (sens_time >= t_min) & (sens_time <= t_max)
    if not np.any(overlap_mask):
        return np.inf, None
    
    sens_time_overlap = sens_time[overlap_mask]
    sens_temp_overlap = sens_temp[overlap_mask]
    ref_temp_shifted_interp = np.interp(sens_time_overlap, shifted_ref_time, ref_temp)
    
    diff = ref_temp_shifted_interp - sens_temp_overlap
    std_diff = np.std(diff)
    return std_diff, overlap_mask

def find_best_shift(sens_time, sens_temp, ref_time, ref_temp, shift_min=-300, shift_max=300):
    """
    Tests all integer shifts from shift_min..shift_max. Picks the shift that yields
    min std of (Tref_interpolated - Tsensor).
    Returns: (best_shift, best_sdev, best_mask, shift_values, sdev_values)
    """
    shift_values = np.arange(shift_min, shift_max + 1, 1)
    sdev_values = []
    
    best_shift = 0
    best_sdev = np.inf
    best_mask = None
    
    for s in shift_values:
        std_diff, overlap_mask = compute_std_for_shift(sens_time, sens_temp, ref_time, ref_temp, s)
        sdev_values.append(std_diff)
        if std_diff < best_sdev:
            best_sdev = std_diff
            best_shift = s
            best_mask = overlap_mask
    
    return best_shift, best_sdev, best_mask, shift_values, sdev_values

def align_data_for_shift(sens_time, sens_temp, ref_time, ref_temp, best_shift, overlap_mask):
    """
    With best_shift, produce aligned arrays for sensor-time vs. shifted Tref.
    We keep only the overlapping portion indicated by overlap_mask.
    Returns arrays: aligned_sens_time, aligned_sens_temp, aligned_ref_temp
    """
    # Subset sensor
    sens_time_al = sens_time[overlap_mask]
    sens_temp_al = sens_temp[overlap_mask]
    
    # Shift ref time, then interpolate
    shifted_ref_time = ref_time + best_shift
    ref_temp_al = np.interp(sens_time_al, shifted_ref_time, ref_temp)
    
    return sens_time_al, sens_temp_al, ref_temp_al


###############################################################################
# PART B) SLOPE DETECTION LOGIC
###############################################################################

def compute_slope(df, xcol, ycol):
    """Linear regression slope (m) & intercept (c) of ycol vs xcol."""
    X = df[[xcol]].values
    Y = df[ycol].values
    reg = LinearRegression().fit(X, Y)
    return float(reg.coef_[0]), float(reg.intercept_)

def calc_window_slopes(df, time_col, ref_col, sensor_col, interval, window):
    """
    Slide in steps of 'interval' seconds.
    For each step s, consider data in [s, s+window], i.e. inclusive logic here.
    Return list of dict with slopes & summary stats.
    """
    results = []
    
    time_min = df[time_col].min()
    time_max = df[time_col].max()
    
    # We'll use inclusive logic: subDF in [s, s+window-1].
    # Then store interval_end = s + window so that user sees an inclusive range.
    s = time_min
    while (s + window - 1) <= time_max:
        interval_start = s
        interval_end = s + window - 1
        
        subdf = df[(df[time_col] >= interval_start) & (df[time_col] <= interval_end)]
        if len(subdf) < 2:
            s += interval
            continue
        
        m_ref, _ = compute_slope(subdf, time_col, ref_col)
        m_sen, _ = compute_slope(subdf, time_col, sensor_col)
        sum_abs_slopes = abs(m_ref) + abs(m_sen)
        
        # summary stats
        mean_ref = subdf[ref_col].mean()
        mean_sen = subdf[sensor_col].mean()
        min_ref  = subdf[ref_col].min()
        max_ref  = subdf[ref_col].max()
        min_sen  = subdf[sensor_col].min()
        max_sen  = subdf[sensor_col].max()
        
        results.append({
            "Interval start (s)": interval_start,
            "Interval end (s)": interval_end + 1,  # store as half-open or just +1 for clarity
            "Sum of abs(slope)": sum_abs_slopes,
            f"Slope: {ref_col}": m_ref,
            f"Slope: {sensor_col}": m_sen,
            f"Mean: {ref_col}": mean_ref,
            f"Mean: {sensor_col}": mean_sen,
            f"Min: {ref_col}": min_ref,
            f"Max: {ref_col}": max_ref,
            f"Min: {sensor_col}": min_sen,
            f"Max: {sensor_col}": max_sen,
        })
        
        s += interval
    
    return results

def partition_calibration_points(sorted_df, ref_col, sensor_col, threshold, segments):
    """
    Filter to rows with sum of abs slopes <= threshold, then partition by 'Mean: sensor_col'.
    Return top-ranked row from each partition (lowest sum_abs_slope).
    """
    valid_df = sorted_df[sorted_df["Sum of abs(slope)"] <= threshold]
    if valid_df.empty:
        return []
    
    sensor_mean = f"Mean: {sensor_col}"
    min_val = valid_df[sensor_mean].min()
    max_val = valid_df[sensor_mean].max()
    
    if math.isclose(min_val, max_val):
        # Not enough range, pick best row
        return [valid_df.iloc[0].to_dict()]
    
    seg_size = (max_val - min_val) / segments
    chosen = []
    current_low = min_val
    
    for i in range(segments):
        current_high = current_low + seg_size
        subset = valid_df[(valid_df[sensor_mean] >= current_low) & (valid_df[sensor_mean] < current_high)]
        if not subset.empty:
            # top-ranked = first row after sort by Sum of abs(slope)
            chosen.append(subset.iloc[0].to_dict())
        current_low = current_high
    
    return chosen

###############################################################################
# PART C) RENAME HELPERS & FILE EXPORT
###############################################################################

def rename_temp_columns_in(df):
    """
    Rename the original columns for easier internal usage:
      't1 (°C)' -> 't1',
      't2 (°C)' -> 't2',
      'Tref (°C)' -> 'Tref'
    """
    rename_map = {
        "t1 (°C)": "t1",
        "t2 (°C)": "t2",
        "Tref (°C)": "Tref"
    }
    df.rename(columns={k:v for k,v in rename_map.items() if k in df.columns}, inplace=True)

def rename_temp_columns_out(df):
    """
    Opposite rename so final CSV matches original style.
      't1' -> 't1 (°C)',
      't2' -> 't2 (°C)',
      'Tref' -> 'Tref (°C)'
    """
    rename_map = {
        "t1": "t1 (°C)",
        "t2": "t2 (°C)",
        "Tref": "Tref (°C)"
    }
    df.rename(columns={k:v for k,v in rename_map.items() if k in df.columns}, inplace=True)

def create_analysis_t_directory():
    out_dir = os.path.join(os.getcwd(), "analysis-t")
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    return out_dir

def make_slopes_rename_map(ref_col, sensor_col):
    """
    Build a dict to rename e.g. "Slope: Tref" -> "Slope: Tref (°C)", etc.
    So final CSV has your original style headers.
    """
    rename_map = {
        f"Slope: {ref_col}": f"Slope: {ref_col} (°C)",
        f"Mean: {ref_col}":  f"Mean: {ref_col} (°C)",
        f"Min: {ref_col}":   f"Min: {ref_col} (°C)",
        f"Max: {ref_col}":   f"Max: {ref_col} (°C)",
        
        f"Slope: {sensor_col}": f"Slope: {sensor_col} (°C)",
        f"Mean: {sensor_col}":  f"Mean: {sensor_col} (°C)",
        f"Min: {sensor_col}":   f"Min: {sensor_col} (°C)",
        f"Max: {sensor_col}":   f"Max: {sensor_col} (°C)",
    }
    return rename_map

def save_slopes_csv(slopes_df, sensor_id, out_dir):
    """
    Write slopes-*.csv with final columns named in the "original" style:
      Slope: Tref (°C), Slope: t1 (°C), etc.
    """
    ref_col = "Tref"  # after internal rename
    out_df = slopes_df.copy()
    
    # rename slope columns to "Slope: Tref (°C)", etc.
    rename_map = make_slopes_rename_map(ref_col, sensor_id)
    out_df.rename(columns=rename_map, inplace=True)
    
    # reorder
    wanted_cols = [
        "Rank",
        "Interval start (s)",
        "Interval end (s)",
        "Sum of abs(slope)",
        f"Slope: {ref_col} (°C)",
        f"Slope: {sensor_id} (°C)",
        f"Mean: {ref_col} (°C)",
        f"Mean: {sensor_id} (°C)",
        f"Min: {ref_col} (°C)",
        f"Max: {ref_col} (°C)",
        f"Min: {sensor_id} (°C)",
        f"Max: {sensor_id} (°C)",
    ]
    out_df = out_df[wanted_cols]
    
    fname = f"slopes-{sensor_id}.csv"
    outpath = os.path.join(out_dir, fname)
    out_df.to_csv(outpath, index=False, float_format="%.6f")

def save_final_ranks_csv_txt(chosen_rows, sensor_id, out_dir):
    """
    Save final chosen calibration points into t1-ranks.csv/.txt or t2-ranks.csv/.txt.
    CSV:  Rank,Tref (°C),t1 (°C)
    TXT:  Tref (°C),t1 (°C)
    """
    if not chosen_rows:
        return
    # Build DataFrame
    data_list = []
    for row in chosen_rows:
        data_list.append({
            "Rank": row["Rank"],
            "Tref": row["Mean: Tref"],
            sensor_id: row[f"Mean: {sensor_id}"]
        })
    df = pd.DataFrame(data_list)
    # rename for final columns
    rename_map = {
        "Tref": "Tref (°C)",
        sensor_id: f"{sensor_id} (°C)"
    }
    df.rename(columns=rename_map, inplace=True)
    
    # CSV
    csv_cols = ["Rank", "Tref (°C)", f"{sensor_id} (°C)"]
    csv_fname = f"{sensor_id}-ranks.csv"
    df[csv_cols].to_csv(os.path.join(out_dir, csv_fname), index=False, float_format="%.6f")
    
    # TXT (drop rank)
    txt_cols = ["Tref (°C)", f"{sensor_id} (°C)"]
    txt_fname = f"{sensor_id}-ranks.txt"
    with open(os.path.join(out_dir, txt_fname), "w", encoding="utf-8") as f:
        f.write(",".join(txt_cols) + "\n")
        for _, row in df.iterrows():
            f.write(f"{row['Tref (°C)']:.6f},{row[f'{sensor_id} (°C)']:.6f}\n")

###############################################################################
# PART D) MAIN
###############################################################################

def main():
    i_def = 10
    w_def = 60
    th_def = 0.0005
    seg_def = 5
    
    parser = argparse.ArgumentParser(description="Align Tref in time, then do temperature plateau detection.")

    parser.add_argument("-shmin", type=int, default=-300, help="Minimum shift in seconds (default=-300).")
    parser.add_argument("-shmax", type=int, default=300, help="Maximum shift in seconds (default=300).")
    
    parser.add_argument("-i", "--interval", type=int, default=i_def, help=f"Sliding step in seconds (default={i_def}).")
    parser.add_argument("-w", "--window", type=int, default=w_def, help=f"Window size in seconds (default={w_def}).")
    parser.add_argument("-th", "--threshold", type=float, default=th_def, help=f"Max sum of abs slopes accepted (default={th_def}).")
    parser.add_argument("-seg", "--segments", type=int, default=seg_def, help=f"Number of segments for calibration partition (default={seg_def}).")
    
    args = parser.parse_args()

    shift_min = args.shmin
    shift_max = args.shmax
    interval  = args.interval
    window    = args.window
    threshold = args.threshold
    segments  = args.segments
    
    # -------------------------------------------------------------------------
    # 1) Find merged-*.csv
    # -------------------------------------------------------------------------
    def find_files_by_pattern_with_re(directory, start_str, extension):
        matching = []
        if not extension.startswith('.'):
            extension = f'.{extension}'
        import re
        pattern = re.compile(rf"^{re.escape(start_str)}.*{re.escape(extension)}$")
        for fn in os.listdir(directory):
            if pattern.match(fn):
                matching.append(os.path.join(directory, fn))
        return matching

    merged_files = find_files_by_pattern_with_re(".", "merged-", ".csv")
    if not merged_files:
        print("No merged-*.csv found!")
        sys.exit(1)
    merged_filename = merged_files[-1]
    
    df = pd.read_csv(merged_filename, encoding="utf-8")
    
    # optional: reduce scientific notation in prints
    pd.set_option("display.float_format", lambda x: f"{x:.6f}")
    
    # -------------------------------------------------------------------------
    # 2) Rename columns internally if needed
    # -------------------------------------------------------------------------
    rename_temp_columns_in(df)
    
    # Must have "Time (s)", "Tref", "t1" at least
    needed_cols = ["Time (s)", "Tref", "t1"]
    for c in needed_cols:
        if c not in df.columns:
            print(f"ERROR: Missing required column '{c}'.")
            sys.exit(1)
    
    has_t2 = ("t2" in df.columns)
    
    # We'll treat the BME sensor times as "sens_time" for alignment
    # Because often Tref is the same time as well, but let's keep the logic consistent.
    # For each sensor (t1, t2), we find the best shift that aligns Tref to that sensor.
    
    ref_time = df["Time (s)"].to_numpy()
    ref_temp = df["Tref"].to_numpy()
    
    # -- t1 --
    sens_time_1 = df["Time (s)"].to_numpy()  # same times if we expect identical sampling
    sens_temp_1 = df["t1"].to_numpy()
    best_shift_1, best_sdev_1, mask_1, shifts_1, sdevs_1 = find_best_shift(
        sens_time_1, sens_temp_1, ref_time, ref_temp, shift_min, shift_max
    )
    
    print(f"[t1] best shift = {best_shift_1} s, std = {best_sdev_1:.6f}")
    
    # possibly t2
    if has_t2:
        sens_time_2 = df["Time (s)"].to_numpy()
        sens_temp_2 = df["t2"].to_numpy()
        best_shift_2, best_sdev_2, mask_2, shifts_2, sdevs_2 = find_best_shift(
            sens_time_2, sens_temp_2, ref_time, ref_temp, shift_min, shift_max
        )
        print(f"[t2] best shift = {best_shift_2} s, std = {best_sdev_2:.6f}")
    
    # -------------------------------------------------------------------------
    # 3) Plot shift vs std dev => tshift-temp.png, tshift-temp-t1.csv/t2.csv
    # -------------------------------------------------------------------------
    # analysis-t folder
    out_dir = create_analysis_t_directory()
    
    plt.figure(figsize=(6,4), dpi=300)
    plt.plot(shifts_1, sdevs_1, marker='o', label="t1")
    save_path = os.path.join(out_dir, "tshift-temp-t1.csv")
    pd.DataFrame({"Shift (s)": shifts_1, "std_dev": sdevs_1}).to_csv(save_path, index=False)
    
    if has_t2:
        plt.plot(shifts_2, sdevs_2, marker='x', label="t2")
        save_path = os.path.join(out_dir, "tshift-temp-t2.csv")
        pd.DataFrame({"Shift (s)": shifts_2, "std_dev": sdevs_2}).to_csv(save_path, index=False)
    
    plt.xlabel("Shift time (s)")
    plt.ylabel("Std of (Tref_interp - Tsensor)")
    plt.title("Shift vs. Standard Deviation")
    plt.legend()
    plot_path = os.path.join(out_dir, "tshift-temp.png")
    plt.savefig(plot_path, dpi=300)
    plt.close()
    
    # -------------------------------------------------------------------------
    # 4) Build final aligned data => talign-thp.csv
    # -------------------------------------------------------------------------
    # We'll keep only the overlapping region for both t1 & t2 if we have 2 sensors
    # so that Tref is consistent. That means we combine masks if we want overlap across all.
    # If you prefer to handle them separately, you can. Here's a single overlap approach:
    
    if not has_t2:
        final_mask = mask_1
    else:
        # Intersection of mask_1 & mask_2 so we only keep times that exist for both
        final_mask = mask_1 & mask_2
    
    aligned_time_1, aligned_temp_1, aligned_ref_1 = align_data_for_shift(
        sens_time_1, sens_temp_1, ref_time, ref_temp, best_shift_1, final_mask
    )
    # For reference, we just store aligned_ref_1 as Tref
    if has_t2:
        aligned_time_2, aligned_temp_2, aligned_ref_2 = align_data_for_shift(
            sens_time_2, sens_temp_2, ref_time, ref_temp, best_shift_2, final_mask
        )
        # This should produce the same "aligned_ref_1" and "aligned_ref_2" if the same Tref sensor,
        # but we typically just keep one. We'll rely on aligned_time_1 as the main time axis.
        
        # We'll assume aligned_time_1 == aligned_time_2 if the final_mask was the same,
        # so let's call that "aligned_time."
        aligned_time = aligned_time_1
        aligned_ref  = aligned_ref_1
    else:
        aligned_time = aligned_time_1
        aligned_ref  = aligned_ref_1
    
    # Build an intermediate DataFrame for the aligned portion
    data_al = {
        "Time (s)": aligned_time,
        "t1": aligned_temp_1,   # internal name
        "Tref": aligned_ref     # internal name
    }
    if has_t2:
        data_al["t2"] = aligned_temp_2
    df_aligned = pd.DataFrame(data_al)
    
    # Merge back with original to get Datetime,Timestamp,Measurement if needed
    # We'll do an inner join on "Time (s)" or we might do approximate merges if times differ.
    # For now we assume it matches exactly.
    
    needed_cols_extra = ["Datetime","Timestamp","Measurement"]
    available_cols = [c for c in needed_cols_extra if c in df.columns]
    if available_cols:
        df_main_subset = df[["Time (s)"] + available_cols].drop_duplicates("Time (s)")
        df_final = pd.merge(df_main_subset, df_aligned, on="Time (s)", how="inner")
    else:
        df_final = df_aligned
    
    # rename back "t1" -> "t1 (°C)", etc. for final CSV
    rename_temp_columns_out(df_final)
    
    # reorder typical columns
    out_cols = ["Datetime","Timestamp","Time (s)","Measurement","t1 (°C)","t2 (°C)","Tref (°C)"]
    out_cols_exist = [c for c in out_cols if c in df_final.columns]
    df_final = df_final[out_cols_exist]
    save_path = os.path.join(out_dir, "talign-thp.csv")
    df_final.to_csv(save_path, index=False, float_format="%.6f")
    print("Wrote talign-thp.csv with aligned data.")
    
    # -------------------------------------------------------------------------
    # 5) Perform slope detection (plateau) on the *aligned* data
    # -------------------------------------------------------------------------
    # We'll read it back or continue with df_final:
    # But now we want the short internal columns again, so let's rename internally once more:
    # You could skip re-reading from disk if you like:
    df_slopes = df_final.copy()
    rename_temp_columns_in(df_slopes)  # "t1 (°C)" -> "t1", etc.
    
    # If we do plateau detection, we need "Time (s)", "Tref", "t1" at least
    sensor_cols = []
    if "t1" in df_slopes.columns:
        sensor_cols.append("t1")
    if "t2" in df_slopes.columns:
        sensor_cols.append("t2")
    
    # Plot for final
    fig, ax = plt.subplots(figsize=(8,6), dpi=300)
    ax.plot(df_slopes["Time (s)"], df_slopes["Tref"], label="Tref", linewidth=2)
    
    calibration_points = {}
    
    for sensor_col in sensor_cols:
        slope_data = calc_window_slopes(df_slopes, "Time (s)", "Tref", sensor_col, interval, window)
        slope_df = pd.DataFrame(slope_data)
        if slope_df.empty:
            print(f"No slope results for {sensor_col}. Skipping.")
            continue
        
        # sort ascending by sum of abs slope
        slope_df.sort_values("Sum of abs(slope)", inplace=True)
        slope_df.reset_index(drop=True, inplace=True)
        slope_df["Rank"] = slope_df.index + 1
        
        # Save slopes-*.csv
        slope_df["Interval end (s)"] = slope_df["Interval end (s)"] - 1
        save_slopes_csv(slope_df, sensor_col, out_dir)
        slope_df["Interval end (s)"] = slope_df["Interval end (s)"] + 1
        
        
        
        # pick calibration points
        chosen = partition_calibration_points(slope_df, "Tref", sensor_col, threshold, segments)
        save_final_ranks_csv_txt(chosen, sensor_col, out_dir)
        calibration_points[sensor_col] = chosen
        
        # plot sensor
        ax.plot(df_slopes["Time (s)"], df_slopes[sensor_col], label=sensor_col)
    
    # Add T-bars from Tref to sensor
    for sensor_col, rows in calibration_points.items():
        for row in rows:
            x = 0.5*(row["Interval start (s)"] + row["Interval end (s)"])
            tref_val = row["Mean: Tref"]
            tsen_val = row[f"Mean: {sensor_col}"]
            arr = mpatches.FancyArrowPatch(
                (x, tref_val), (x, tsen_val),
                arrowstyle='|-|',
                color='gray',
                mutation_scale=15,
                lw=1.2
            )
            ax.add_patch(arr)
    
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("Aligned Temperature Data + Plateau Detection")
    ax.legend()
    
    plot_path = os.path.join(out_dir, "temp_plateaus.png")
    plt.savefig(plot_path, dpi=300)
    plt.close()
    
    print("Done! All plateau results and plots are in the 'analysis-t' folder.")

if __name__ == "__main__":
    main()
