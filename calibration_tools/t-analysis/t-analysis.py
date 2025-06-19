#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t‑analysis.py – Temperature plateau analysis & calibration
──────────────────────────────────────────────────────────────
Detect flat temperature plateaus in *merged-*.csv logs, pick one window per
10 °C step (−50…+100 °C), regress Tref vs. sensor temperature, and write all
artefacts needed for calibration.

*2025‑06‑18 – patch*
  • **NEW**: JSON calibration‑dictionary output (shared *thpcal.json*).
  • Supports **‑cal zone,num1[,num2]** and **‑z** flags as in RH tools.
  • Writes temperature entries under key ``"T"``; R² auto‑computed when
    missing.
  • **Legend & TXT precision** – R² now printed with **six** decimals (%.6f)
"""
from __future__ import annotations

###############################################################################
# Imports
###############################################################################
import argparse, glob, os, re, shlex, sys
import posixpath
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import linregress
from sklearn.linear_model import LinearRegression

# NEW – JSON calibration helpers
import json
from thpcaldb import parse_zone_numbers

###############################################################################
# CONSTANTS & FILE PATTERNS
###############################################################################
REF_COL, SENS1_COL, SENS2_COL = "Tref (°C)", "t1 (°C)", "t2 (°C)"
TIME_COL = "Time (s)"
OUTDIR   = Path("analysis-t")
TARGET_LEVELS: List[int] = list(range(-50, 101, 10))

PLATEAU_PNG_FMT = "{tag}_cal_plateaus.png"
REG_PNG_FMT     = "{tag}_tref_regression.png"
REG_TXT_FMT     = "{tag}_tref_regression.txt"
ANALYSIS_CSV    = "{tag}_analysis.csv"
RANK_CSV        = "{tag}-ranks.csv"
RANK_TXT        = "{tag}-ranks.txt"

###############################################################################
# JSON‑dict helper functions (borrowed from *rh‑analysis.py*)
###############################################################################

def _convert_value(val: str) -> Any:
    """Try float, else raw string."""
    try:
        return float(val)
    except ValueError:
        return val


def find_thpcal_json() -> Tuple[str, bool]:
    """Locate *thpcal.json* (cwd → parent → /opt/tools). Returns (path, exists)."""
    filename = "thpcal.json"
    search_dirs = [
        os.getcwd(),
        os.path.abspath(os.path.join(os.getcwd(), os.pardir)),
        "/opt/tools",
    ]
    for d in search_dirs:
        p = os.path.join(d, filename)
        if os.path.isfile(p):
            print(f"Calibration file thpcal.json found in: {d}")
            return p, True
    new_p = os.path.join(os.getcwd(), filename)
    print(f"Path to the new calibration file thpcal.json: {os.getcwd()}")
    return new_p, False


def read_thpcal_json(filename: str) -> Dict[int, Dict[str, Dict[str, Any]]]:
    with open(filename, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return {int(k): v for k, v in raw.items()}


def read_and_merge_thpcal_json(filename: str, new_entries: Dict[int, Dict[str, Dict[str, Any]]]) -> Dict[int, Dict[str, Dict[str, Any]]]:
    try:
        cal = read_thpcal_json(filename)
    except Exception:
        print("Creating a new thpcal.json file.")
        return new_entries
    for num, sensors in new_entries.items():
        cal.setdefault(num, {})
        for sensor, types in sensors.items():
            cal[num].setdefault(sensor, {})
            for t, info in types.items():
                cal[num][sensor][t] = info
    print("Merged new data with existing calibration file.")
    return cal


def write_thpcal_json(filename: str, cal_dict: Dict[int, Dict[str, Dict[str, Any]]]) -> None:
    raw = {str(k): v for k, v in cal_dict.items()}
    with open(filename, "w", encoding="utf-8") as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=2)
    print("→ saved thpcal.json")

###############################################################################
# Plateau‑finding helpers (unchanged)
###############################################################################

def newest_merged() -> Path | None:
    patt = re.compile(r"merged-\d{8}-\d{6}\.csv$")
    files = [Path(f) for f in glob.glob("merged-*.csv") if patt.search(f)]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def lslope(df: pd.DataFrame, x: str, y: str) -> float:
    return float(LinearRegression().fit(df[[x]], df[y]).coef_[0])


def rank_by_score(df: pd.DataFrame) -> pd.DataFrame:
    ranked = df.sort_values("Score").reset_index(drop=True)
    ranked.insert(0, "Rank", ranked.index + 1)
    return ranked


def bands(levels: List[int]):
    out = []
    for i, lvl in enumerate(levels):
        lo = levels[i - 1] if i else lvl
        hi = levels[i + 1] if i < len(levels) - 1 else lvl
        out.append(((lvl + lo) / 2, lvl, (lvl + hi) / 2))
    return out

# --- auto‑scale helper (import from RH script) ------------------------------

def get_time_scale_and_label(max_time_s: float) -> tuple[float, str]:
    if max_time_s <= 300:
        return 1.0, "Time (s)"
    if max_time_s <= 18_000:
        return 1 / 60.0, "Time (min)"
    if max_time_s <= 432_000:
        return 1 / 3600.0, "Time (h)"
    return 1 / 86_400.0, "Time (d)"


def plot_plateaus(df_full: pd.DataFrame, subset: pd.DataFrame, sensor_col: str, out_png: Path, *, auto_scale: bool = False) -> None:
    if subset.empty:
        return
    scale, xlabel = (get_time_scale_and_label(df_full[TIME_COL].max()) if auto_scale else (1.0, "Time (s)"))
    t_scaled = df_full[TIME_COL] * scale
    fig, ax = plt.subplots()
    ax.plot(t_scaled, df_full[REF_COL], label="Tref", color="tab:red", lw=1.2)
    ax.plot(t_scaled, df_full[sensor_col], label=sensor_col, color="tab:blue", lw=1.0)
    for _, r in subset.iterrows():
        s_sc, e_sc = r.Tstart * scale, r.Tend * scale
        ax.hlines([r.Mean_ref, r.Mean_sens], xmin=s_sc, xmax=e_sc, colors="k")
        ax.vlines((s_sc + e_sc) / 2, min(r.Mean_ref, r.Mean_sens), max(r.Mean_ref, r.Mean_sens), colors="k")
    ax.set_xlabel(xlabel); ax.set_ylabel("Temperature (°C)")
    ax.set_title(f"Calibration plateaus – {sensor_col}")
    ax.grid(True, ls=":", lw=0.5); ax.legend()
    fig.tight_layout(); fig.savefig(out_png, dpi=300); plt.close(fig)

###############################################################################
# MAIN WORKFLOW
###############################################################################

def main() -> None:
    p = argparse.ArgumentParser("Temperature plateau analysis")
    p.add_argument("-th", type=float, default=5e-4, help="slope tolerance |m_ref|+|m_sensor|")
    p.add_argument("-s", "--start", type=int, default=0, help="start row index")
    p.add_argument("-w", "--window", type=int, default=300, help="window length (rows)")
    p.add_argument("-i", "--interval", type=int, default=30, help="slide step (rows)")
    p.add_argument("-maxdt", type=float, default=5.0, help="max |Tref−Tsensor| inside window (°C)")
    p.add_argument("-a", "--auto", action="store_true", help="auto‑scale time axis units in plateau plots")
    # NEW flags
    p.add_argument("-cal", metavar="SPEC", type=str, help="Calibration spec zone,num1[,num2] (e.g. -cal C3,4)")
    p.add_argument("-z", action="store_true", help="Zero the time component of stored datetime (→ 00:00:00)")
    args = p.parse_args()

    # Ensure output dir exists
    OUTDIR.mkdir(exist_ok=True)

    merged = newest_merged()
    if merged is None:
        print("No merged-*.csv found"); sys.exit(1)

    df = pd.read_csv(merged)
    for req in (TIME_COL, REF_COL, SENS1_COL):
        if req not in df.columns:
            print("Missing", req); sys.exit(1)
    has_t2 = SENS2_COL in df.columns

    # Extract first Datetime string if present (for JSON)
    cal_dt = None
    if "Datetime" in df.columns and not df["Datetime"].empty:
        cal_dt = str(df["Datetime"].iloc[0])
        if args.z and cal_dt:
            cal_dt = cal_dt[:10] + " 00:00:00"

    # Derive sensor‑code mapping from -cal
    sensor_code_map: Dict[str, str] = {}
    if args.cal:
        try:
            zone, num1, num2 = parse_zone_numbers(args.cal)
            if num1 is not None:
                sensor_code_map[SENS1_COL] = f"{zone}{num1}"
            if num2 is not None and has_t2:
                sensor_code_map[SENS2_COL] = f"{zone}{num2}"
        except Exception as exc:
            print(f"Invalid -cal spec '{args.cal}': {exc}. Skipping calibration JSON generation.")
            args.cal = None  # disable JSON path

    # ------------------------------------------------------------------
    # 1.  Sliding‑window search for plateaus (unchanged, freshly copied)
    # ------------------------------------------------------------------
    results_windows: Dict[str, List[dict]] = {"t1": [], "t2": []}
    pos = args.start
    while pos < len(df) - 1:
        win = df.iloc[pos : pos + args.window]
        if win.empty:
            break
        mean_ref = win[REF_COL].mean(); slope_ref = lslope(win, TIME_COL, REF_COL)

        def consider(col: str, store: List[dict]):
            mean_s = win[col].mean()
            if abs(mean_s - mean_ref) > args.maxdt:
                return
            slope_s = lslope(win, TIME_COL, col)
            score = abs(slope_s) + abs(slope_ref)
            if score > args.th:
                return
            store.append(dict(Start=pos, End=pos+len(win)-1, Tstart=win[TIME_COL].iat[0], Tend=win[TIME_COL].iat[-1],
                              Slope_ref=slope_ref, Slope_sens=slope_s, Mean_ref=mean_ref, Mean_sens=mean_s, Score=score))

        consider(SENS1_COL, results_windows["t1"])
        if has_t2:
            consider(SENS2_COL, results_windows["t2"])
        pos += args.interval

    frames = {k: rank_by_score(pd.DataFrame(v)) for k, v in results_windows.items() if v}

    # Save full analysis CSV next to merged file
    for tag, df_tag in frames.items():
        if not df_tag.empty:
            df_tag.to_csv(Path(merged).parent / ANALYSIS_CSV.format(tag=tag), index=False)

    # ------------------------------------------------------------------
    # 2.  Pick one plateau per TARGET_LEVELS band
    # ------------------------------------------------------------------
    band_defs = bands(TARGET_LEVELS)
    chosen: Dict[str, List[int]] = {}
    for tag, df_tag in frames.items():
        picks, seen = [], set()
        for lo, mid, hi in band_defs:
            idx = (df_tag["Mean_ref"] - mid).abs().idxmin()
            row = df_tag.loc[idx]
            if lo <= row.Mean_ref <= hi and row.Rank not in seen:
                picks.append(int(row.Rank)); seen.add(int(row.Rank))
        chosen[tag] = picks

    def save_ranks(tag: str) -> pd.DataFrame:
        if not chosen.get(tag):
            return pd.DataFrame()
        sub = frames[tag][frames[tag]["Rank"].isin(chosen[tag])].sort_values("Mean_ref")
        tidy = sub[["Rank", "Mean_ref", "Mean_sens"]].rename(columns={"Mean_ref": "Tref (°C)", "Mean_sens": f"{tag.upper()} (°C)"})
        tidy.to_csv(OUTDIR / RANK_CSV.format(tag=tag), index=False)
        tidy.drop(columns=["Rank"]).to_csv(OUTDIR / RANK_TXT.format(tag=tag), index=False, header=True)
        return sub

    picked = {tag: save_ranks(tag) for tag in chosen if chosen[tag]}

    # ------------------------------------------------------------------
    # 3.  Regression + artefacts + JSON
    # ------------------------------------------------------------------
    print("Linear regression on chosen plateaus …")
    json_results: Dict[int, Dict[str, Dict[str, Any]]] = {}

    def regress(tag: str, sensor_col: str):
        sub = picked.get(tag)
        if sub is None or sub.empty:
            return
        x, y = sub.Mean_sens.to_numpy(), sub.Mean_ref.to_numpy()
        lr = linregress(x, y)
        r2 = lr.rvalue ** 2
        print(f"  {tag.upper()} → slope={lr.slope:.5f}  intercept={lr.intercept:.3f}  R²={r2:.6f}  N={len(x)}")

        # Scatter + fit plot
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.scatter(x, y, label="data")
        xr = np.array([x.min() - 1, x.max() + 1])
        fit_label = f"y = {lr.slope:.4f}x + {lr.intercept:.4f}\nR² = {r2:.6f}"
        ax.plot(xr, lr.slope * xr + lr.intercept, label=fit_label)
        ax.set_xlabel(f"{tag.upper()} (°C)"); ax.set_ylabel("Tref (°C)")
        ax.set_title("Temperature regression"); ax.grid(True); ax.legend(); ax.set_aspect("equal")
        fig.tight_layout(); fig.savefig(OUTDIR / REG_PNG_FMT.format(tag=tag), dpi=300); plt.close(fig)

        # TXT summary
        with open(OUTDIR / REG_TXT_FMT.format(tag=tag), "w", encoding="utf-8") as fh:
            fh.write(
                "Linear Regression Results:\n"
                f"  Formula: y = {lr.slope:.4f}x + {lr.intercept:.4f}\n"
                f"  Slope:          {lr.slope:.4f}\n"
                f"  Intercept:      {lr.intercept:.4f}\n"
                f"  R-value:        {lr.rvalue:.6f}\n"
                f"  R-squared:      {r2:.6f}\n"
                f"  Standard Error: {lr.stderr:.4f}\n"
                f"  P-value:        {lr.pvalue:.3g}\n"
                f"  N:              {len(x)}\n"
            )

        # Plateau overview plot
        plot_plateaus(df_full=df, subset=sub, sensor_col=sensor_col, out_png=OUTDIR / PLATEAU_PNG_FMT.format(tag=tag), auto_scale=args.auto)

        # ---- JSON dictionary entry -----------------------------------
        num = 1 if tag == "t1" else 2
        sensor_code = sensor_code_map.get(sensor_col, f"S{num}")
        json_results.setdefault(num, {}).setdefault(sensor_code, {})["T"] = {
            "datetime": cal_dt if cal_dt else datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label": "Temperature",
            "name": tag,
            "col": sensor_col,
            "slope": lr.slope,
            "constant": lr.intercept,
            "r2": r2,
        }

    regress("t1", SENS1_COL)
    if has_t2:
        regress("t2", SENS2_COL)

    # ------------------------------------------------------------------
    # 4.  Persist JSON calibration dictionary
    # ------------------------------------------------------------------
    if args.cal and json_results:
        print("Creating/updating calibration file …")
        json_path, exists = find_thpcal_json()
        merged = read_and_merge_thpcal_json(json_path, json_results) if exists else json_results
        write_thpcal_json(json_path, merged)

    print("Done – results in", OUTDIR)

###############################################################################
# CLI guard
###############################################################################

if __name__ == "__main__":
    main()
