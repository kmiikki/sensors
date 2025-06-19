#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thp-t-flats.py – quick‑and‑dirty plateau selector + calibration export
──────────────────────────────────────────────────────────────────────────────
*SHIFT + FLATS* – aligns **Tref** in time, detects temperature plateaus for the
BME280 sensors (*t1* / *t2*), runs a linear regression, and writes artefacts
& calibration data.

*2025‑06‑18 – patch 2*
  • **FIX**: re‑added ``save_slopes_csv`` and ``save_final_ranks_csv_txt`` helpers
    that went missing, eliminating *NameError* during run.
  • Keeps all new features from patch 1 (R² six‑decimal precision, `-cal`/`-z`
    flags, thpcal.json updates).
"""
from __future__ import annotations

###############################################################################
# Imports
###############################################################################
import os, sys, argparse, math, re, json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from sklearn.linear_model import LinearRegression
from scipy.stats import linregress

# Calibration‑dictionary helper ---------------------------------------------
from thpcaldb import parse_zone_numbers

###############################################################################
# --- JSON helpers (borrowed from t‑analysis.py) -----------------------------
###############################################################################

def find_thpcal_json() -> Tuple[str, bool]:
    """Search cwd → parent → /opt/tools for *thpcal.json*."""
    filename = "thpcal.json"
    for d in (os.getcwd(), os.path.abspath(os.path.join(os.getcwd(), os.pardir)), "/opt/tools"):
        p = os.path.join(d, filename)
        if os.path.isfile(p):
            return p, True
    return os.path.join(os.getcwd(), filename), False


def read_thpcal_json(path: str) -> Dict[int, Dict[str, Dict[str, Any]]]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return {int(k): v for k, v in raw.items()}


def merge_thpcal(existing: dict, new_entries: dict) -> dict:
    for num, sensors in new_entries.items():
        existing.setdefault(num, {})
        for sens, types in sensors.items():
            existing[num].setdefault(sens, {}).update(types)
    return existing


def write_thpcal_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({str(k): v for k, v in data.items()}, fh, indent=2, ensure_ascii=False)

###############################################################################
# PART A) SHIFT LOGIC (unchanged)
###############################################################################

def compute_std_for_shift(sens_time, sens_temp, ref_time, ref_temp, shift):
    """Compute std of diff after time‑shifting *Tref* by *shift* seconds."""
    shifted_ref_time = ref_time + shift
    t_min = max(shifted_ref_time.min(), sens_time.min())
    t_max = min(shifted_ref_time.max(), sens_time.max())
    if t_min >= t_max:
        return np.inf, None
    mask = (sens_time >= t_min) & (sens_time <= t_max)
    if not np.any(mask):
        return np.inf, None
    sens_time_ov = sens_time[mask]
    sens_temp_ov = sens_temp[mask]
    ref_temp_shifted = np.interp(sens_time_ov, shifted_ref_time, ref_temp)
    return float(np.std(ref_temp_shifted - sens_temp_ov)), mask


def find_best_shift(sens_time, sens_temp, ref_time, ref_temp, shift_min=-300, shift_max=300):
    shift_vals = np.arange(shift_min, shift_max + 1, 1)
    sdev_vals, best_shift, best_sdev, best_mask = [], 0, np.inf, None
    for s in shift_vals:
        sd, mask = compute_std_for_shift(sens_time, sens_temp, ref_time, ref_temp, s)
        sdev_vals.append(sd)
        if sd < best_sdev:
            best_shift, best_sdev, best_mask = s, sd, mask
    return best_shift, best_sdev, best_mask, shift_vals, np.array(sdev_vals)


def align_data_for_shift(sens_time, sens_temp, ref_time, ref_temp, best_shift, mask):
    sens_time_al = sens_time[mask]
    sens_temp_al = sens_temp[mask]
    ref_temp_al = np.interp(sens_time_al, ref_time + best_shift, ref_temp)
    return sens_time_al, sens_temp_al, ref_temp_al

###############################################################################
# PART B) SLOPE / PLATEAU LOGIC
###############################################################################

def compute_slope(df: pd.DataFrame, xcol: str, ycol: str):
    reg = LinearRegression().fit(df[[xcol]].values, df[ycol].values)
    return float(reg.coef_[0]), float(reg.intercept_)


def calc_window_slopes(df, time_col, ref_col, sensor_col, interval, window):
    results = []
    t_min, t_max = df[time_col].min(), df[time_col].max()
    s = t_min
    while (s + window - 1) <= t_max:
        sub = df[(df[time_col] >= s) & (df[time_col] <= s + window - 1)]
        if len(sub) < 2:
            s += interval; continue
        m_ref, _ = compute_slope(sub, time_col, ref_col)
        m_sen, _ = compute_slope(sub, time_col, sensor_col)
        sum_abs = abs(m_ref) + abs(m_sen)
        results.append({
            "Interval start (s)": s,
            "Interval end (s)": s + window,  # half‑open
            "Sum of abs(slope)": sum_abs,
            f"Slope: {ref_col}": m_ref,
            f"Slope: {sensor_col}": m_sen,
            f"Mean: {ref_col}": sub[ref_col].mean(),
            f"Mean: {sensor_col}": sub[sensor_col].mean(),
            f"Min: {ref_col}": sub[ref_col].min(),
            f"Max: {ref_col}": sub[ref_col].max(),
            f"Min: {sensor_col}": sub[sensor_col].min(),
            f"Max: {sensor_col}": sub[sensor_col].max(),
        })
        s += interval
    return results


def partition_calibration_points(df_sorted, ref_col, sensor_col, threshold, segments):
    valid = df_sorted[df_sorted["Sum of abs(slope)"] <= threshold]
    if valid.empty:
        return []
    sensor_mean = f"Mean: {sensor_col}"
    lo, hi_tot = valid[sensor_mean].min(), valid[sensor_mean].max()
    if math.isclose(lo, hi_tot):
        return [valid.iloc[0].to_dict()]
    seg_size = (hi_tot - lo) / segments
    chosen = []
    for _ in range(segments):
        hi = lo + seg_size
        sub = valid[(valid[sensor_mean] >= lo) & (valid[sensor_mean] < hi)]
        if not sub.empty:
            chosen.append(sub.iloc[0].to_dict())
        lo = hi
    return chosen

###############################################################################
# PART C) CSV / RENAME HELPERS
###############################################################################

def rename_temp_columns_in(df):
    df.rename(columns={"t1 (°C)": "t1", "t2 (°C)": "t2", "Tref (°C)": "Tref"}, inplace=True)


def rename_temp_columns_out(df):
    df.rename(columns={"t1": "t1 (°C)", "t2": "t2 (°C)", "Tref": "Tref (°C)"}, inplace=True)


def create_analysis_t_directory() -> str:
    out_dir = Path(os.getcwd()) / "analysis-t"
    out_dir.mkdir(exist_ok=True)
    return str(out_dir)


def make_slopes_rename_map(ref_col: str, sensor_col: str) -> Dict[str, str]:
    """Helper for pretty column names in slopes CSV."""
    return {
        f"Slope: {ref_col}": f"Slope: {ref_col} (°C)",
        f"Mean: {ref_col}":  f"Mean: {ref_col} (°C)",
        f"Min: {ref_col}":   f"Min: {ref_col} (°C)",
        f"Max: {ref_col}":   f"Max: {ref_col} (°C)",
        f"Slope: {sensor_col}": f"Slope: {sensor_col} (°C)",
        f"Mean: {sensor_col}":  f"Mean: {sensor_col} (°C)",
        f"Min: {sensor_col}":   f"Min: {sensor_col} (°C)",
        f"Max: {sensor_col}":   f"Max: {sensor_col} (°C)",
    }


def save_slopes_csv(slopes_df: pd.DataFrame, sensor_id: str, out_dir: str) -> None:
    """Write *slopes-<sensor>.csv* with friendly column names."""
    ref_col = "Tref"  # internal name
    out_df = slopes_df.copy()
    out_df.rename(columns=make_slopes_rename_map(ref_col, sensor_id), inplace=True)
    cols = [
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
    out_df = out_df[[c for c in cols if c in out_df.columns]]
    out_path = Path(out_dir) / f"slopes-{sensor_id}.csv"
    out_df.to_csv(out_path, index=False, float_format="%.6f")


def save_final_ranks_csv_txt(chosen_rows: List[dict],
                             sensor_id: str,
                             out_dir: str) -> None:
    """
    Save final plateau means for one sensor to
    <sensor>-ranks.csv  (with Rank)  and  <sensor>-ranks.txt (without Rank).
    """
    if not chosen_rows:
        return

    df = pd.DataFrame({
        "Rank":            [r["Rank"]           for r in chosen_rows],
        "Tref (°C)":       [r["Mean: Tref"]     for r in chosen_rows],
        f"{sensor_id} (°C)": [r[f"Mean: {sensor_id}"] for r in chosen_rows],
    })

    # CSV + TXT
    df.to_csv(Path(out_dir) / f"{sensor_id}-ranks.csv",
              index=False, float_format="%.6f")
    df.drop(columns=["Rank"]).to_csv(Path(out_dir) / f"{sensor_id}-ranks.txt",
                                     index=False, float_format="%.6f")


###############################################################################
# PART D) MAIN
###############################################################################

def main() -> None:
    i_def, w_def, th_def, seg_def = 10, 60, 5e-4, 5

    p = argparse.ArgumentParser(
        "Align Tref, detect plateaus, create calibration.")
    p.add_argument("-shmin", type=int, default=-300)
    p.add_argument("-shmax", type=int, default=300)
    p.add_argument("-i",  "--interval",  type=int, default=i_def)
    p.add_argument("-w",  "--window",    type=int, default=w_def)
    p.add_argument("-th", "--threshold", type=float, default=th_def)
    p.add_argument("-seg","--segments",  type=int, default=seg_def)
    # NEW
    p.add_argument("-cal", metavar="SPEC",
                   help="Calibration spec zone,num1[,num2] e.g. C3,4")
    p.add_argument("-z", action="store_true",
                   help="Zero time component of datetime in JSON entry")
    args = p.parse_args()

    # ---------------------------------------------------------------- merged CSV
    patt = re.compile(r"^merged-.*\.csv$")
    merged_files = sorted([f for f in os.listdir(".") if patt.match(f)])
    if not merged_files:
        print("No merged-*.csv found!"); sys.exit(1)
    merged_filename = merged_files[-1]
    df = pd.read_csv(merged_filename)

    # Datetime for JSON
    cal_dt = None
    if "Datetime" in df.columns and not df["Datetime"].empty:
        cal_dt = str(df["Datetime"].iloc[0])
        if args.z and cal_dt:
            cal_dt = cal_dt[:10] + " 00:00:00"

    # Column names → internal
    rename_temp_columns_in(df)
    for col in ("Time (s)", "Tref", "t1"):
        if col not in df.columns:
            print("Missing column", col); sys.exit(1)
    has_t2 = "t2" in df.columns

    ref_time = df["Time (s)"].to_numpy()
    ref_temp = df["Tref"].to_numpy()

    # ------------------------------------------------ alignment shifts
    def handle(sensor_name):
        sens_time = df["Time (s)"].to_numpy()
        sens_temp = df[sensor_name].to_numpy()
        return find_best_shift(sens_time, sens_temp,
                               ref_time, ref_temp,
                               args.shmin, args.shmax)

    best_shift_1, best_sdev_1, mask_1, shifts_1, sdevs_1 = handle("t1")
    print(f"[t1] best shift = {best_shift_1} s, std = {best_sdev_1:.6f}")
    if has_t2:
        best_shift_2, best_sdev_2, mask_2, shifts_2, sdevs_2 = handle("t2")
        print(f"[t2] best shift = {best_shift_2} s, std = {best_sdev_2:.6f}")

    # ------------------------------------------------ shift-vs-std plot
    out_dir = create_analysis_t_directory()
    plt.figure(figsize=(6,4), dpi=300)
    plt.plot(shifts_1, sdevs_1, marker="o", label="t1")
    pd.DataFrame({"Shift (s)": shifts_1,
                  "std_dev":  sdevs_1}
                ).to_csv(Path(out_dir)/"tshift-temp-t1.csv", index=False)
    if has_t2:
        plt.plot(shifts_2, sdevs_2, marker="x", label="t2")
        pd.DataFrame({"Shift (s)": shifts_2,
                      "std_dev":  sdevs_2}
                    ).to_csv(Path(out_dir)/"tshift-temp-t2.csv", index=False)
    plt.xlabel("Shift time (s)")
    plt.ylabel("Std of (Tref_interp − Tsensor)")
    plt.title("Shift vs. Std dev"); plt.legend()
    plt.savefig(Path(out_dir)/"tshift-temp.png", dpi=300); plt.close()

    # ------------------------------------------------ aligned DF
    final_mask = mask_1 if not has_t2 else (mask_1 & mask_2)
    al_time1, al_temp1, al_ref = align_data_for_shift(
        df["Time (s)"].to_numpy(), df["t1"].to_numpy(),
        ref_time, ref_temp, best_shift_1, final_mask)

    data_al = {"Time (s)": al_time1, "t1": al_temp1, "Tref": al_ref}
    if has_t2:
        _, al_temp2, _ = align_data_for_shift(
            df["Time (s)"].to_numpy(), df["t2"].to_numpy(),
            ref_time, ref_temp, best_shift_2, final_mask)
        data_al["t2"] = al_temp2

    df_aligned = pd.DataFrame(data_al)

    # keep Datetime / Timestamp / Measurement if present
    extras = [c for c in ("Datetime","Timestamp","Measurement") if c in df.columns]
    if extras:
        df_aligned = pd.merge(
            df[["Time (s)"]+extras].drop_duplicates("Time (s)"),
            df_aligned, on="Time (s)")

    rename_temp_columns_out(df_aligned)
    order = [c for c in ("Datetime","Timestamp","Time (s)","Measurement",
                         "t1 (°C)","t2 (°C)","Tref (°C)") if c in df_aligned.columns]
    df_aligned = df_aligned[order]
    df_aligned.to_csv(Path(out_dir)/"talign-thp.csv",
                      index=False, float_format="%.6f")

    # ------------------------------------------------ plateau detection
    df_slopes = df_aligned.copy(); rename_temp_columns_in(df_slopes)
    sensor_cols = [c for c in ("t1","t2") if c in df_slopes.columns]

    plt.figure(figsize=(8,6), dpi=300)
    plt.plot(df_slopes["Time (s)"], df_slopes["Tref"],
             label="Tref", lw=2)

    calibration_points: Dict[str, List[dict]] = {}
    for sens in sensor_cols:
        slope_data = calc_window_slopes(df_slopes, "Time (s)", "Tref",
                                        sens, args.interval, args.window)
        slope_df = pd.DataFrame(slope_data)
        if slope_df.empty:
            print(f"No slope results for {sens}"); continue
        slope_df.sort_values("Sum of abs(slope)", inplace=True)
        slope_df.reset_index(drop=True, inplace=True)
        slope_df["Rank"] = slope_df.index + 1

        # CSV of slopes
        save_slopes_csv(slope_df.copy(), sens, out_dir)

        chosen = partition_calibration_points(
            slope_df, "Tref", sens, args.threshold, args.segments)
        calibration_points[sens] = chosen

        save_final_ranks_csv_txt(chosen, sens, out_dir)
        plt.plot(df_slopes["Time (s)"], df_slopes[sens], label=sens)

    # draw plateau bars
    ax = plt.gca()
    for sens, rows in calibration_points.items():
        for row in rows:
            x_mid = 0.5 * (row["Interval start (s)"] + row["Interval end (s)"])
            ax.add_patch(
                mpatches.FancyArrowPatch(
                    (x_mid, row["Mean: Tref"]),
                    (x_mid, row[f"Mean: {sens}"]),
                    arrowstyle="|-|", color="gray", lw=1))

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("Aligned data + plateaus")
    ax.legend(); plt.tight_layout()
    plt.savefig(Path(out_dir)/"temp_plateaus.png", dpi=300); plt.close()

    # ------------------------------------------------ regression + JSON
    print("Regression on chosen plateaus …")
    json_results: Dict[int, Dict[str, Dict[str, Any]]] = {}

    # sensor-code map from -cal
    sensor_code_map: Dict[str, str] = {}
    if args.cal:
        try:
            zone, num1, num2 = parse_zone_numbers(args.cal)
            if num1 is not None:
                sensor_code_map["t1"] = sensor_code_map["t1 (°C)"] = f"{zone}{num1}"
            if has_t2 and num2 is not None:
                sensor_code_map["t2"] = sensor_code_map["t2 (°C)"] = f"{zone}{num2}"
        except Exception as e:
            print("Invalid -cal spec:", e); args.cal = None

    def regress_sensor(sens: str, rows: List[dict]) -> None:
        if not rows:
            return
        x = np.array([r[f"Mean: {sens}"] for r in rows])
        y = np.array([r["Mean: Tref"] for r in rows])
        lr = linregress(x, y)
        r2 = lr.rvalue ** 2
        print(f"  {sens} → slope={lr.slope:.5f}  intercept={lr.intercept:.3f}  "
              f"R²={r2:.6f}  N={len(x)}")

        # scatter + fit plot
        fig, ax = plt.subplots(figsize=(6,6), dpi=300)
        ax.scatter(x, y, label="data", s=18)
        xr = np.array([x.min()-1, x.max()+1])
        fit_label = f"y = {lr.slope:.4f}x + {lr.intercept:.4f}\nR² = {r2:.6f}"
        ax.plot(xr, lr.slope*xr + lr.intercept, label=fit_label)
        ax.set_xlabel(f"{sens} (°C)")
        ax.set_ylabel("Tref (°C)")
        ax.set_title("Temperature regression")
        ax.grid(True, ls=":"); ax.legend(); ax.set_aspect("equal")
        plt.tight_layout()
        plt.savefig(Path(out_dir)/f"{sens}_tref_regression.png", dpi=300)
        plt.close(fig)

        # TXT summary
        with open(Path(out_dir)/f"{sens}_tref_regression.txt", "w",
                  encoding="utf-8") as fh:
            fh.write(
                "Linear Regression Results\n"
                f"  y = {lr.slope:.6f}x + {lr.intercept:.6f}\n"
                f"  R-squared: {r2:.6f}\n"
                f"  N: {len(x)}\n"
            )

        # JSON entry
        num = 1 if sens == "t1" else 2
        sensor_code = sensor_code_map.get(sens, f"S{num}")
        json_results.setdefault(num, {}).setdefault(sensor_code, {})["T"] = {
            "datetime": cal_dt or datetime.now().
                        strftime("%Y-%m-%d %H:%M:%S"),
            "label":    "Temperature",
            "name":     sens,
            "col":      sens + " (°C)" if not sens.endswith("°C)") else sens,
            "slope":    lr.slope,
            "constant": lr.intercept,
            "r2":       r2,
        }

    for sens in sensor_cols:
        regress_sensor(sens, calibration_points.get(sens, []))

    if args.cal and json_results:
        json_path, exists = find_thpcal_json()
        cal_dict = read_thpcal_json(json_path) if exists else {}
        cal_dict = merge_thpcal(cal_dict, json_results)
        write_thpcal_json(json_path, cal_dict)
        print(f"Calibration dictionary updated → {json_path}")

    print("Done – results saved in", out_dir)


###############################################################################
if __name__ == "__main__":
    main()
