#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import csv
import math
import datetime as dt

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def parse_iso(ts: str) -> float:
    """Return POSIX seconds from ISO8601 timestamp (supports tz offset)."""
    t = dt.datetime.fromisoformat(ts)
    return t.timestamp()


def read_csv_rows(path: Path):
    """Read CSV into a list of dict rows."""
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows = list(r)
    return rows


def build_series(rows, want_temp: bool, temp_col: str | None = None):
    """
    Build time, pressure, unit, events and optional temperature series.

    Returns
    -------
    t : list[float]
        Time in seconds relative to first valid timestamp.
    p : list[float]
        Pressure values.
    unit : str | None
        Pressure unit from CSV (column 'unit').
    events : list[tuple[float, str]]
        List of (t, label) for step events.
    temps : list[float] | None
        Temperature series if available and requested.
    temp_label : str | None
        Label for temperature axis (column name).
    """
    if not rows:
        return [], [], None, [], None, None

    # --- Time axis: prefer ts_iso, else t_perf, else index ---
    t_abs = []
    for i, row in enumerate(rows):
        ts = row.get("ts_iso") or ""
        if ts:
            try:
                t_abs.append(parse_iso(ts))
                continue
            except Exception:
                pass

        # fallback t_perf
        tperf = row.get("t_perf", "")
        if tperf:
            try:
                t_abs.append(float(tperf))
                continue
            except Exception:
                pass

        # last fallback: simple index
        t_abs.append(float(i))

    t0 = next((x for x in t_abs if math.isfinite(x)), None)
    if t0 is None:
        raise ValueError("No valid timestamps in CSV.")
    t = [(x - t0) if math.isfinite(x) else math.nan for x in t_abs]

    # --- Pressure + unit ---
    unit = None
    p = []
    for row in rows:
        u = row.get("unit") or unit or "bar"
        unit = u
        try:
            p.append(float(row.get("pressure", "nan")))
        except Exception:
            p.append(math.nan)

    # --- Events (step commands), if any ---
    events = []
    for i, row in enumerate(rows):
        ev = (row.get("event") or "").strip()
        if not ev:
            continue
        if ev.upper().startswith("STEP"):
            p2 = row.get("target_p2_bar") or ""
            tau = row.get("tau_s") or ""
            if p2 or tau:
                label = f"STEP p2={p2} tau={tau}"
            else:
                label = ev
            events.append((t[i], label))

    # --- Temperature series (optional) ---
    temps = None
    temp_label = None

    if want_temp:
        header = rows[0].keys()

        # pick column if not explicitly given
        if temp_col is None:
            candidates = [
                "cpu_temp_c",
                "cpu_temp",
                "temperature",
                "temp_c",
                "temp",
                "T",
            ]
            for c in candidates:
                if c in header:
                    temp_col = c
                    break

        if temp_col is not None and temp_col in header:
            series = []
            for row in rows:
                val = row.get(temp_col, "")
                try:
                    series.append(float(val))
                except Exception:
                    series.append(math.nan)
            temps = series
            temp_label = temp_col

    return t, p, unit, events, temps, temp_label


def decimate(x, y, max_pts=5000):
    """Simple downsampling for long series (keep every k-th point)."""
    n = len(x)
    if n <= max_pts:
        return x, y
    step = max(1, n // max_pts)
    return x[::step], y[::step]


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Plot pressure vs time from logger CSV (optionally with temperature)."
    )
    ap.add_argument("csv", type=Path, help="Input CSV file.")
    ap.add_argument("--out", type=Path, default=None, help="Output PNG path.")
    ap.add_argument("--title", default="Pressure vs. Time (dynamic steps)")
    ap.add_argument("--dpi", type=int, default=180)
    ap.add_argument("--grid", action="store_true", help="Show major grid.")
    ap.add_argument(
        "--maxpts",
        type=int,
        default=6000,
        help="Max points to plot (decimate if more).",
    )
    ap.add_argument(
        "--temp",
        action="store_true",
        help="Also plot temperature on secondary y-axis (if column exists).",
    )
    ap.add_argument(
        "--temp-col",
        type=str,
        default=None,
        help="Temperature column name (overrides auto-detection).",
    )
    args = ap.parse_args()

    rows = read_csv_rows(args.csv)
    t, p, unit, events, temps, temp_label = build_series(
        rows, want_temp=args.temp, temp_col=args.temp_col
    )

    # Decimate pressure
    t_plot, p_plot = decimate(t, p, max_pts=args.maxpts)

    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.plot(t_plot, p_plot, linewidth=1.2)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel(f"Pressure ({unit or 'bar'})")
    ax.set_title(args.title)

    if args.grid:
        ax.grid(True, which="major", linestyle="--", alpha=0.4)

    # Mark step events if present
    if events:
        ymin = math.nanmin(p_plot) if p_plot else 0.0
        ymax = math.nanmax(p_plot) if p_plot else 1.0
        if (not math.isfinite(ymin)) or (not math.isfinite(ymax)) or ymax == ymin:
            ymin, ymax = 0.0, 1.0
        height = ymax - ymin
        for (tx, label) in events:
            ax.axvline(tx, linestyle=":", linewidth=1)
            ax.text(
                tx,
                ymax - 0.05 * height,
                label,
                rotation=90,
                va="top",
                ha="right",
                fontsize=8,
                alpha=0.7,
            )

    # Optional temperature on secondary y-axis
    if temps is not None:
        # Match decimation with time axis
        if len(temps) == len(t):
            t_temp, temps_plot = decimate(t, temps, max_pts=args.maxpts)
        else:
            # Fallback: naive alignment
            t_temp, temps_plot = t_plot[: len(temps)], temps[: len(t_plot)]

        ax2 = ax.twinx()
        ax2.plot(t_temp[: len(temps_plot)], temps_plot, linestyle="--", linewidth=1.0)

        # Label y2 with column name and °C if appropriate
        if temp_label:
            lbl = temp_label
            if "c" in temp_label.lower():
                ax2.set_ylabel(f"{lbl} (°C)")
            else:
                ax2.set_ylabel(lbl)

    ax.margins(x=0.02, y=0.1)
    fig.tight_layout()

    out = args.out or args.csv.with_suffix(".png")
    fig.savefig(out, dpi=args.dpi)
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
