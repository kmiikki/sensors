#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import ScalarFormatter
from scipy import stats

DEFAULT_BINS_MAX = 20
DEFAULT_SLOPE_TH = 1e-3
DEFAULT_DPI = 300

DT_STEM_RE = re.compile(r"^(dps_addr\d{2})_(\d{8}-\d{6})$")
NO_DT_STEM_RE = re.compile(r"^(dps_addr\d{2})$")


def classify_stem(stem: str) -> tuple[str, str | None]:
    m = DT_STEM_RE.match(stem)
    if m:
        return ("dt", m.group(2))

    if NO_DT_STEM_RE.match(stem):
        return ("no_dt", None)

    return ("invalid", None)


def valid_csvs_in_dir(directory: Path) -> list[Path]:
    files = []
    for p in directory.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() != ".csv":
            continue
        kind, _ = classify_stem(p.stem)
        if kind in {"dt", "no_dt"}:
            files.append(p)
    return sorted(files)


def select_group(anchor: Path, directory: Path) -> list[Path]:
    files = valid_csvs_in_dir(directory)
    kind, dt = classify_stem(anchor.stem)

    if kind == "dt" and dt is not None:
        return [p for p in files if classify_stem(p.stem) == ("dt", dt)]

    if kind == "no_dt":
        return [p for p in files if classify_stem(p.stem)[0] == "no_dt"]

    raise ValueError(f"Invalid DPS CSV filename format: {anchor.name}")


def resolve_targets(directory: Path, filename: str | None) -> list[Path]:
    directory = directory.expanduser().resolve()

    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    files = valid_csvs_in_dir(directory)
    if not files:
        raise FileNotFoundError(f"No valid DPS CSV files found in directory: {directory}")

    if filename:
        candidate = Path(filename).expanduser()
        if candidate.is_absolute():
            anchor = candidate.resolve()
        else:
            anchor = (directory / candidate).resolve()

        if not anchor.exists():
            raise FileNotFoundError(f"CSV file not found: {anchor}")
        if not anchor.is_file():
            raise FileNotFoundError(f"Not a file: {anchor}")

        kind, _ = classify_stem(anchor.stem)
        if kind == "invalid":
            raise ValueError(f"Invalid DPS CSV filename format: {anchor.name}")
    else:
        anchor = files[-1]

    return select_group(anchor, anchor.parent)


def auto_bins(n: int) -> int:
    b = round(math.sqrt(n))
    return max(1, min(DEFAULT_BINS_MAX, b))


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    required = {"t_rel", "pressure"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {path.name}: {sorted(missing)}")

    df = df.copy()
    df["t_rel"] = pd.to_numeric(df["t_rel"], errors="coerce")
    df["pressure"] = pd.to_numeric(df["pressure"], errors="coerce")
    df = df.dropna(subset=["t_rel", "pressure"])

    return df


def get_pressure_label(df: pd.DataFrame) -> str:
    if "unit" in df.columns:
        units = df["unit"].dropna().astype(str).str.strip().unique()
        if len(units) == 1 and units[0]:
            return f"Pressure ({units[0]})"
    return "Pressure"


def configure_plain_axis(ax: plt.Axes, axis: str = "y") -> None:
    formatter = ScalarFormatter(useOffset=False)
    formatter.set_scientific(False)

    if axis == "x":
        ax.xaxis.set_major_formatter(formatter)
        ax.ticklabel_format(axis="x", style="plain", useOffset=False)
    elif axis == "y":
        ax.yaxis.set_major_formatter(formatter)
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    else:
        raise ValueError("axis must be 'x' or 'y'")


def regression(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    result = stats.linregress(x, y)
    return {
        "slope": float(result.slope),
        "intercept": float(result.intercept),
        "r": float(result.rvalue),
        "r2": float(result.rvalue ** 2),
        "pvalue": float(result.pvalue),
        "stderr": float(result.stderr),
    }


def ci95(values: np.ndarray) -> dict[str, float | str | int]:
    n = len(values)
    mean = float(np.mean(values))

    if n <= 1:
        return {
            "n": n,
            "mean": mean,
            "std": 0.0,
            "sem": float("nan"),
            "ci95_low": float("nan"),
            "ci95_high": float("nan"),
            "distribution": "n/a",
        }

    std = float(np.std(values, ddof=1))
    sem = std / math.sqrt(n)

    if n <= 30:
        crit = float(stats.t.ppf(0.975, n - 1))
        dist_name = "t"
    else:
        crit = float(stats.norm.ppf(0.975))
        dist_name = "normal"

    half_width = crit * sem

    return {
        "n": n,
        "mean": mean,
        "std": std,
        "sem": sem,
        "ci95_low": mean - half_width,
        "ci95_high": mean + half_width,
        "distribution": dist_name,
    }


def format_regression_equation(
    slope: float,
    intercept: float,
    x_name: str = "time",
    y_name: str = "Pressure",
) -> str:
    return f"{y_name} = {slope:.3e} * {x_name} + {intercept:.6f}"


def plot_pressure(df: pd.DataFrame, out: Path, grid: bool, dpi: int) -> None:
    fig, ax = plt.subplots()

    x = df["t_rel"].to_numpy(dtype=float)
    y = df["pressure"].to_numpy(dtype=float)

    ax.plot(
        x,
        y,
        marker="o",
        linestyle="-",
        linewidth=1,
        markersize=3,
    )
    ax.set_xlabel("Time (s)")
    ax.set_ylabel(get_pressure_label(df))
    configure_plain_axis(ax, axis="y")

    if grid:
        ax.grid(True)

    fig.tight_layout()
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


def plot_hist(df: pd.DataFrame, out: Path, bins: int, grid: bool, dpi: int) -> None:
    fig, ax = plt.subplots()

    y = df["pressure"].to_numpy(dtype=float)

    ax.hist(y, bins=bins)
    ax.set_xlabel(get_pressure_label(df))
    ax.set_ylabel("Count")
    configure_plain_axis(ax, axis="x")

    if grid:
        ax.grid(True)

    fig.tight_layout()
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


def plot_regression(df: pd.DataFrame, reg: dict[str, float], out: Path, grid: bool, dpi: int) -> None:
    fig, ax = plt.subplots()

    x = df["t_rel"].to_numpy(dtype=float)
    y = df["pressure"].to_numpy(dtype=float)

    ax.plot(
        x,
        y,
        marker="o",
        linestyle="-",
        linewidth=1,
        markersize=3,
        label="Measured pressure",
    )

    xr = np.array([x.min(), x.max()], dtype=float)
    yr = reg["slope"] * xr + reg["intercept"]
    ax.plot(xr, yr, linewidth=1.5, label="Linear regression")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel(get_pressure_label(df))
    configure_plain_axis(ax, axis="y")

    if grid:
        ax.grid(True)

    eq_text = format_regression_equation(
        slope=reg["slope"],
        intercept=reg["intercept"],
        x_name="time",
        y_name="Pressure",
    )
    ax.text(
        0.02,
        0.98,
        eq_text,
        transform=ax.transAxes,
        va="top",
        ha="left",
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.85},
    )
    ax.legend()

    fig.tight_layout()
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


def write_stats(
    csv_path: Path,
    df: pd.DataFrame,
    reg: dict[str, float] | None,
    slope_th: float,
    out: Path,
) -> None:
    p = df["pressure"].to_numpy(dtype=float)
    n = len(p)

    if n == 0:
        with out.open("w", encoding="utf-8") as f:
            f.write("[data]\n\n")
            f.write(f"file = {csv_path.name}\n")
            f.write("sensor_address = unknown\n")
            f.write("samples = 0\n")
            f.write("interval = 0.0\n")
            f.write("duration = 0\n\n")
            f.write("pressure_unit = unknown\n")
            f.write("time_unit = s\n")
        return

    pressure_unit = "unknown"
    if "unit" in df.columns:
        units = df["unit"].dropna().astype(str).str.strip().unique()
        if len(units) == 1 and units[0]:
            pressure_unit = units[0]

    sensor_address = "unknown"
    m = re.match(r"^dps_addr(\d{2})", csv_path.stem)
    if m:
        sensor_address = str(int(m.group(1)))

    interval = 0.0
    if len(df) >= 2:
        diffs = np.diff(df["t_rel"].to_numpy(dtype=float))
        if len(diffs) > 0:
            interval = float(np.median(diffs))

    duration = float(df["t_rel"].iloc[-1]) if len(df) > 0 else 0.0

    mean_val = float(np.mean(p))
    std_val = float(np.std(p, ddof=1)) if n > 1 else 0.0
    min_val = float(np.min(p))
    max_val = float(np.max(p))

    with out.open("w", encoding="utf-8") as f:
        f.write("[data]\n\n")
        f.write(f"file = {csv_path.name}\n")
        f.write(f"sensor_address = {sensor_address}\n")
        f.write(f"samples = {n}\n")
        f.write(f"interval = {interval:.1f}\n")
        f.write(f"duration = {duration:.0f}\n\n")
        f.write(f"pressure_unit = {pressure_unit}\n")
        f.write("time_unit = s\n")

        f.write("\n\n[statistics]\n\n")
        f.write(f"mean = {mean_val:.6f}\n")
        f.write(f"std = {std_val:.6f}\n")
        f.write(f"min = {min_val:.6f}\n")
        f.write(f"max = {max_val:.6f}\n")

        if reg is not None:
            f.write("\n\n[linear_regression]\n\n")
            f.write(
                f"Pressure(time) = {reg['slope']:.3e} * time + {reg['intercept']:.6f}\n"
            )
            f.write(f"slope = {reg['slope']:.3e}\n")
            f.write(f"intercept = {reg['intercept']:.6f}\n")
            f.write(f"r2 = {reg['r2']:.4f}\n")

            if abs(reg["slope"]) <= slope_th:
                ci = ci95(p)
                half_width = float(ci["ci95_high"] - ci["mean"]) if n > 1 else float("nan")

                f.write("\n\n[stable_pressure_ci95]\n\n")
                f.write(f"method = {ci['distribution']}\n")
                f.write("confidence = 0.95\n")
                f.write(f"mean = {ci['mean']:.6f}\n")

                if isinstance(ci["ci95_low"], float) and math.isnan(ci["ci95_low"]):
                    f.write("lower = nan\n")
                    f.write("upper = nan\n")
                    f.write("half_width = nan\n")
                else:
                    f.write(f"lower = {ci['ci95_low']:.6f}\n")
                    f.write(f"upper = {ci['ci95_high']:.6f}\n")
                    f.write(f"half_width = {half_width:.6f}\n")


def analyse_file(
    csv_path: Path,
    bins_override: int | None,
    slope_th: float,
    grid: bool,
    dpi: int,
) -> None:
    df = load_csv(csv_path)

    if len(df) == 0:
        print(f"{csv_path.name}: no valid t_rel/pressure rows")
        return

    bins = bins_override if bins_override is not None else auto_bins(len(df))
    bins = max(1, min(DEFAULT_BINS_MAX, bins))

    x = df["t_rel"].to_numpy(dtype=float)
    y = df["pressure"].to_numpy(dtype=float)

    reg = regression(x, y) if len(df) >= 2 else None

    stem = csv_path.with_suffix("")
    pressure_png = Path(f"{stem}_pressure.png")
    hist_png = Path(f"{stem}_hist.png")
    stats_txt = Path(f"{stem}_stats.txt")
    regression_png = Path(f"{stem}_regression.png")

    plot_pressure(df, pressure_png, grid, dpi)
    plot_hist(df, hist_png, bins, grid, dpi)
    write_stats(csv_path, df, reg, slope_th, stats_txt)

    if reg is not None and abs(reg["slope"]) <= slope_th:
        plot_regression(df, reg, regression_png, grid, dpi)

    print(f"Analysed: {csv_path.name}")
    print(f"  wrote: {pressure_png.name}")
    print(f"  wrote: {hist_png.name}")
    print(f"  wrote: {stats_txt.name}")
    if reg is not None and abs(reg['slope']) <= slope_th:
        print(f"  wrote: {regression_png.name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DPS CSV analysis tool")

    parser.add_argument("csv", nargs="?", help="CSV file to analyse")

    parser.add_argument(
        "--dir",
        type=Path,
        default=Path.cwd(),
        help="Directory where CSV files are searched",
    )

    parser.add_argument("--bins", type=int, default=None)
    parser.add_argument("--slope-th", type=float, default=DEFAULT_SLOPE_TH)
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--no-grid", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    grid = not args.no_grid

    try:
        targets = resolve_targets(args.dir, args.csv)
        for csv_path in targets:
            analyse_file(
                csv_path=csv_path,
                bins_override=args.bins,
                slope_th=args.slope_th,
                grid=grid,
                dpi=args.dpi,
            )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
