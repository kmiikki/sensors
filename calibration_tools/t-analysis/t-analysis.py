#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t‑analysis.py – Temperature plateau analysis & calibration
──────────────────────────────────────────────────────────────
Detect flat temperature plateaus in *merged-*.csv logs, pick one window per
10 °C step (−50…+100 °C), regress Tref vs. sensor temperature, and write all
artefacts needed for calibration.

Outputs
=======
<MERGE_DIR>/
 ├─ t1_analysis.csv   full window list (Rank, slopes, means …)
 └─ t2_analysis.csv   (if t2 present)
analysis-t/
 ├─ t1-ranks.csv / .txt   chosen plateaus (sorted by Tref) + Rank
 ├─ t2-ranks.*            idem for t2 if available
 ├─ t1_tref_regression.png/.txt      regression plot & coeffs
 ├─ t2_tref_regression.png/.txt      (optional)
 ├─ t1_cal_plateaus.png              overview of trace + plateaus
 ├─ t2_cal_plateaus.png              (optional)
 └─ thp-args.log                     CLI history
"""
from __future__ import annotations

import argparse, glob, os, re, shlex, sys, datetime
from pathlib import Path
from typing import List, Dict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import linregress
from sklearn.linear_model import LinearRegression

###############################################################################
# CONSTANTS & TEMPLATES
###############################################################################

REF_COL, SENS1_COL, SENS2_COL = "Tref (°C)", "t1 (°C)", "t2 (°C)"
TIME_COL = "Time (s)"
OUTDIR = Path("analysis-t")
TARGET_LEVELS: List[int] = list(range(-50, 101, 10))

PLATEAU_PNG_FMT = "{tag}_cal_plateaus.png"
REG_PNG_FMT = "{tag}_tref_regression.png"
REG_TXT_FMT = "{tag}_tref_regression.txt"
ANALYSIS_CSV = "{tag}_analysis.csv"
RANK_CSV = "{tag}-ranks.csv"
RANK_TXT = "{tag}-ranks.txt"

###############################################################################
# HELPERS
###############################################################################

def newest_merged() -> Path | None:
    """Return newest *merged-YYYYMMDD-hhmmss.csv* in cwd or *None*."""
    patt = re.compile(r"merged-\d{8}-\d{6}\.csv$")
    files = [Path(f) for f in glob.glob("merged-*.csv") if patt.search(f)]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None

def lslope(df: pd.DataFrame, x: str, y: str) -> float:
    """Slope of linear regression *y = m·x + b* for columns *x*, *y*."""
    return float(LinearRegression().fit(df[[x]], df[y]).coef_[0])

def rank_by_score(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by *Score*, add 1‑based Rank column, return copy."""
    ranked = df.sort_values("Score").reset_index(drop=True)
    ranked.insert(0, "Rank", ranked.index + 1)
    return ranked

def bands(levels: List[int]):
    """Generate (low,target,high) tuples for plateau centre values."""
    out=[]
    for i,lvl in enumerate(levels):
        lo = levels[i-1] if i else lvl
        hi = levels[i+1] if i < len(levels)-1 else lvl
        out.append(((lvl+lo)/2, lvl, (lvl+hi)/2))
    return out

def plot_plateaus(df_full: pd.DataFrame, subset: pd.DataFrame, sensor_col: str, out_png: Path) -> None:
    """Plot whole trace with horizontal/vertical markers for each plateau."""
    if subset.empty:
        return
    fig, ax = plt.subplots()
    ax.plot(df_full[TIME_COL], df_full[REF_COL], label="Tref", color="tab:red", lw=1.2)
    ax.plot(df_full[TIME_COL], df_full[sensor_col], label=sensor_col, color="tab:blue", lw=1.0)
    for _, r in subset.iterrows():
        s, e = r.Tstart, r.Tend
        ax.hlines([r.Mean_ref, r.Mean_sens], xmin=s, xmax=e, colors="k")
        ax.vlines((s+e)/2, min(r.Mean_ref, r.Mean_sens), max(r.Mean_ref, r.Mean_sens), colors="k")
    ax.set_xlabel("Time (s)"); ax.set_ylabel("Temperature (°C)")
    ax.set_title(f"Calibration plateaus – {sensor_col}")
    ax.grid(True, ls=":", lw=0.5); ax.legend(); fig.tight_layout()
    fig.savefig(out_png, dpi=300); plt.close(fig)

###############################################################################
# CORE
###############################################################################

def main() -> None:
    """CLI entry point for plateau detection and regression workflow."""
    p = argparse.ArgumentParser("Temperature plateau analysis")
    p.add_argument("-th", type=float, default=5e-4, help="slope tolerance |m_ref|+|m_sensor|")
    p.add_argument("-w", "--window", type=int, default=300, help="window length (rows)")
    p.add_argument("-i", "--interval", type=int, default=30, help="slide step (rows)")
    p.add_argument("-s", "--start", type=int, default=0, help="start row index")
    p.add_argument("-maxdt", type=float, default=5.0, help="max |Tref−Tsensor| inside window (°C)")
    args = p.parse_args()

    # log call
    OUTDIR.mkdir(exist_ok=True)
    with open(OUTDIR/"thp-args.log", "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} t-analysis.py {shlex.join(sys.argv[1:])}\n")

    merged = newest_merged()
    if merged is None:
        print("No merged-*.csv found"); sys.exit(1)
    df = pd.read_csv(merged)
    for req in (TIME_COL, REF_COL, SENS1_COL):
        if req not in df.columns:
            print("Missing", req); sys.exit(1)
    has_t2 = SENS2_COL in df.columns

    print("Scanning windows for flat plateaus …")
    results: Dict[str, List[dict]] = {"t1": [], "t2": []}
    pos=args.start
    while pos < len(df)-1:
        win = df.iloc[pos:pos+args.window]
        if win.empty: break
        mean_ref = win[REF_COL].mean(); slope_ref = lslope(win, TIME_COL, REF_COL)

        def consider(col:str, store:List[dict]):
            mean_s=win[col].mean();
            if abs(mean_s-mean_ref)>args.maxdt: return
            slope_s=lslope(win, TIME_COL, col)
            score=abs(slope_s)+abs(slope_ref)
            if score>args.th: return
            store.append(dict(Start=pos,End=pos+len(win)-1,Tstart=win[TIME_COL].iat[0],Tend=win[TIME_COL].iat[-1],
                              Slope_ref=slope_ref,Slope_sens=slope_s,Mean_ref=mean_ref,Mean_sens=mean_s,Score=score))
        consider(SENS1_COL, results["t1"])
        if has_t2: consider(SENS2_COL, results["t2"])
        pos += args.interval

    frames: Dict[str,pd.DataFrame] = {k: rank_by_score(pd.DataFrame(v)) for k,v in results.items() if v}
    # save full analysis CSV next to merged file
    for tag,df_tag in frames.items():
        if not df_tag.empty:
            df_tag.to_csv(merged.parent/ANALYSIS_CSV.format(tag=tag), index=False)

    band_defs=bands(TARGET_LEVELS)
    chosen: Dict[str,List[int]]={}
    for tag,df_tag in frames.items():
        picks,seen=[],set()
        for lo,mid,hi in band_defs:
            idx=(df_tag["Mean_ref"]-mid).abs().idxmin(); row=df_tag.loc[idx]
            if lo<=row.Mean_ref<=hi and row.Rank not in seen:
                picks.append(int(row.Rank)); seen.add(int(row.Rank))
        chosen[tag]=picks

    def save_ranks(tag:str)->pd.DataFrame:
        if not chosen.get(tag): return pd.DataFrame()
        sub=frames[tag][frames[tag]["Rank"].isin(chosen[tag])].sort_values("Mean_ref")
        tidy=sub[["Rank","Mean_ref","Mean_sens"]].rename(columns={"Mean_ref":"Tref (°C)","Mean_sens":f"{tag.upper()} (°C)"})
        tidy.to_csv(OUTDIR/RANK_CSV.format(tag=tag), index=False)
        tidy.to_csv(OUTDIR/RANK_TXT.format(tag=tag), index=False, header=False)
        return sub

    picked={tag:save_ranks(tag) for tag in chosen if chosen[tag]}

    print("Linear regression on chosen plateaus …")
    def regress(tag:str, sensor_col:str):
        sub=picked.get(tag)
        if sub is None or sub.empty: return
        x,y=sub.Mean_sens.to_numpy(), sub.Mean_ref.to_numpy()
        lr=linregress(x,y)
        print(f"  {tag.upper()} → slope={lr.slope:.5f}  intercept={lr.intercept:.3f}  N={len(x)}")
        # scatter fit plot
        fig,ax=plt.subplots(figsize=(6,6))
        ax.scatter(x,y,label="data")
        xr=np.array([x.min()-1,x.max()+1])
        ax.plot(xr, lr.slope*xr+lr.intercept, label=f"y = {lr.slope:.4f}x + {lr.intercept:.4f}")
        ax.set_xlabel(f"{tag.upper()} (°C)")
        ax.set_ylabel("Tref (°C)")
        ax.set_title("Temperature regression")
        ax.grid(True)
        ax.legend()
        ax.set_aspect('equal')
        fig.tight_layout()
        fig.savefig(OUTDIR/REG_PNG_FMT.format(tag=tag), dpi=300); plt.close(fig)
        with open(OUTDIR / REG_TXT_FMT.format(tag=tag), "w", encoding="utf-8") as fh:
            fh.write(
                "Linear Regression Results:\n"
                f"  Formula: y = {lr.slope:.4f}x + {lr.intercept:.4f}\n"
                f"  Slope:          {lr.slope:.4f}\n"
                f"  Intercept:      {lr.intercept:.4f}\n"
                f"  R-value:        {lr.rvalue:.4f}\n"
                f"  R-squared:      {lr.rvalue**2:.4f}\n"
                f"  Standard Error: {lr.stderr:.4f}\n"
                f"  P-value:        {lr.pvalue:.3g}\n"
                f"  N:              {len(x)}\n"
            )
        # trace overview with plateaus
        plot_plateaus(df_full=df, subset=sub, sensor_col=sensor_col, out_png=OUTDIR/PLATEAU_PNG_FMT.format(tag=tag))

    regress("t1", SENS1_COL)
    if has_t2:
        regress("t2", SENS2_COL)

    print("Done – results in", OUTDIR)

###############################################################################
# CLI
###############################################################################

if __name__ == "__main__":
    main()
