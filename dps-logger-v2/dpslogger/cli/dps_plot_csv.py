#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import ScalarFormatter
from scipy import stats

DEFAULT_DPI = 300
DEFAULT_SLOPE_TH = 1e-3
DEFAULT_BINS_MAX = 200


def resolve_targets(directory: Path, csv_name: str | None) -> list[Path]:
    if csv_name:
        target = Path(csv_name)
        if not target.is_absolute():
            target = directory / target
        if not target.exists():
            raise FileNotFoundError(f"CSV file not found: {target}")
        return [target]

    files = sorted(directory.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in {directory}")
    return files


def auto_bins(values: np.ndarray) -> int:
    """
    Select histogram bin count using the Freedman–Diaconis rule.

    This is the fallback method for general continuous-valued data.

    Formula:
        bin_width = 2 * IQR / n^(1/3)
        bins = ceil((max - min) / bin_width)

    Why this method:
    - More robust than sqrt(n) because it uses both sample size and IQR
    - Less sensitive to outliers than variance-based rules

    Fallbacks:
    - If n <= 1, return 1
    - If IQR <= 0 or range <= 0, fall back to sqrt(n)-style estimate
    - Clamp to [1, DEFAULT_BINS_MAX], with a practical minimum of 10
      when there is data variation
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n <= 1:
        return 1

    data_min = float(np.min(values))
    data_max = float(np.max(values))
    data_range = data_max - data_min
    if data_range <= 0:
        return 1

    q1, q3 = np.percentile(values, [25, 75])
    iqr = float(q3 - q1)

    if iqr <= 0:
        return max(10, min(DEFAULT_BINS_MAX, int(round(math.sqrt(n)))))

    bin_width = 2.0 * iqr / (n ** (1.0 / 3.0))
    if bin_width <= 0:
        return max(10, min(DEFAULT_BINS_MAX, int(round(math.sqrt(n)))))

    bins = int(math.ceil(data_range / bin_width))
    return max(10, min(DEFAULT_BINS_MAX, bins))


def quantized_bin_edges(values: np.ndarray) -> np.ndarray | None:
    """
    Build histogram bin edges for quantized measurement data.

    Strategy:
    - Infer the quantization step from the smallest positive difference
      between observed unique values.
    - Build one bin for every possible quantized level between observed
      minimum and maximum.
    - This preserves real empty bins if some quantized levels are missing.

    Example:
        If observed values are on a 1e-5 grid from 1.01415 to 1.01422,
        bins are created for every level in that full range.
        Missing levels remain visible as true empty bins.

    Returns:
    - bin edges array if a stable quantized grid can be inferred
    - None if the data does not look quantized on a single consistent step
    """
    unique_vals = np.unique(np.asarray(values, dtype=float))
    if len(unique_vals) < 2:
        return None

    diffs = np.diff(unique_vals)
    positive_diffs = diffs[diffs > 0]
    if len(positive_diffs) == 0:
        return None

    step = float(np.min(positive_diffs))
    if step <= 0:
        return None

    data_min = float(unique_vals[0])
    data_max = float(unique_vals[-1])

    # Verify that all observed values lie on the inferred quantized grid.
    indices = np.round((unique_vals - data_min) / step)
    reconstructed = data_min + indices * step
    if not np.allclose(unique_vals, reconstructed, rtol=0.0, atol=1e-12):
        return None

    n_levels = int(round((data_max - data_min) / step)) + 1
    if n_levels < 2:
        return None

    levels = data_min + step * np.arange(n_levels, dtype=float)

    edges = np.empty(n_levels + 1, dtype=float)
    edges[1:-1] = (levels[:-1] + levels[1:]) / 2.0
    edges[0] = levels[0] - step / 2.0
    edges[-1] = levels[-1] + step / 2.0
    return edges


def load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    if "t_rel" not in df.columns or "pressure" not in df.columns:
        raise ValueError(f"{csv_path.name}: CSV must contain columns 't_rel' and 'pressure'")

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


def get_pressure_unit(df: pd.DataFrame) -> str:
    if "unit" in df.columns:
        units = df["unit"].dropna().astype(str).str.strip().unique()
        if len(units) == 1 and units[0]:
            return units[0]
    return "pressure_unit"


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
    """
    Linear regression with centered x for better numerical robustness.

    Internally:
        x_centered = x - mean(x)

    The returned model is converted back to the original form:
        y = slope * time_s + intercept

    so the visible regression equation remains in the same form as before.
    """
    x_mean = float(np.mean(x))
    x_centered = x - x_mean

    result = stats.linregress(x_centered, y)

    slope = float(result.slope)
    intercept_centered = float(result.intercept)
    intercept = intercept_centered - slope * x_mean

    return {
        "slope": slope,
        "intercept": intercept,
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


def choose_time_unit(duration_s: float, override: str | None = None) -> tuple[str, float]:
    factors = {
        "s": 1.0,
        "min": 60.0,
        "h": 3600.0,
        "d": 86400.0,
    }

    if override is not None:
        return override, factors[override]

    if duration_s <= 5 * 60:
        return "s", 1.0
    if duration_s <= 5 * 60 * 60:
        return "min", 60.0
    if duration_s <= 5 * 24 * 3600:
        return "h", 3600.0
    return "d", 86400.0


def convert_time_axis(values: np.ndarray, factor: float) -> np.ndarray:
    return values / factor


def plot_pressure(
    df: pd.DataFrame,
    out: Path,
    grid: bool,
    dpi: int,
    time_unit: str,
    time_factor: float,
) -> None:
    fig, ax = plt.subplots()

    x = df["t_rel"].to_numpy(dtype=float)
    x_plot = convert_time_axis(x, time_factor)
    y = df["pressure"].to_numpy(dtype=float)

    ax.plot(
        x_plot,
        y,
        marker="o",
        linestyle="-",
        linewidth=1,
        markersize=3,
    )
    ax.set_xlabel(f"Time ({time_unit})")
    ax.set_ylabel(get_pressure_label(df))
    configure_plain_axis(ax, axis="x")
    configure_plain_axis(ax, axis="y")

    if grid:
        ax.grid(True)

    fig.tight_layout()
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


def plot_hist(df: pd.DataFrame, out: Path, bins: int, grid: bool, dpi: int) -> None:
    fig, ax = plt.subplots()

    y = df["pressure"].to_numpy(dtype=float)

    # Prefer quantized-level bins when the data looks like quantized measurement
    # data on a consistent step. This preserves true empty bins if some levels
    # are missing. Otherwise fall back to Freedman–Diaconis bin count.
    edges = quantized_bin_edges(y)

    if edges is not None:
        ax.hist(
            y,
            bins=edges,
            rwidth=1.0,
            edgecolor="black",
            linewidth=0.5,
        )
    else:
        ax.hist(
            y,
            bins=bins,
            rwidth=1.0,
            edgecolor="black",
            linewidth=0.5,
        )

    ax.set_xlabel(get_pressure_label(df))
    ax.set_ylabel("Count")
    configure_plain_axis(ax, axis="x")

    if grid:
        ax.grid(True)

    fig.tight_layout()
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


def plot_regression(
    df: pd.DataFrame,
    reg: dict[str, float],
    out: Path,
    grid: bool,
    dpi: int,
    time_unit: str,
    time_factor: float,
) -> None:
    fig, ax = plt.subplots()

    x = df["t_rel"].to_numpy(dtype=float)
    x_plot = convert_time_axis(x, time_factor)
    y = df["pressure"].to_numpy(dtype=float)

    ax.plot(
        x_plot,
        y,
        marker="o",
        linestyle="-",
        linewidth=1,
        markersize=3,
        label="Measured pressure",
    )

    # Regression is computed in seconds, but drawn in the selected display
    # time scale so that the fitted line matches the plotted x-axis.
    xr = np.array([x.min(), x.max()], dtype=float)
    xr_plot = convert_time_axis(xr, time_factor)
    yr = reg["slope"] * xr + reg["intercept"]
    ax.plot(xr_plot, yr, linewidth=1.5, label="Linear regression")

    ax.set_xlabel(f"Time ({time_unit})")
    ax.set_ylabel(get_pressure_label(df))
    configure_plain_axis(ax, axis="x")
    configure_plain_axis(ax, axis="y")

    if grid:
        ax.grid(True)

    pressure_unit = get_pressure_unit(df)
    eq_text = (
        f"Pressure = {reg['slope']:.3e} * time_s + {reg['intercept']:.6f}\n"
        f"slope = {reg['slope']:.3e} {pressure_unit}/s\n"
        f"r² = {reg['r2']:.4f}"
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
    median_val = float(np.median(p))
    std_val = float(np.std(p, ddof=1)) if n > 1 else 0.0
    min_val = float(np.min(p))
    max_val = float(np.max(p))

    with out.open("w", encoding="utf-8") as f:
        f.write("[data]\n\n")
        f.write(f"file = {csv_path.name}\n")
        f.write(f"sensor_address = {sensor_address}\n")
        f.write(f"samples = {n}\n")
        f.write(f"interval = {interval:.6f}\n")
        f.write(f"duration = {duration:.6f}\n")
        f.write(f"pressure_unit = {pressure_unit}\n")
        f.write("time_unit = s\n")

        f.write("\n\n[statistics]\n\n")
        f.write(f"mean = {mean_val:.6f}\n")
        f.write(f"median = {median_val:.6f}\n")
        f.write(f"std = {std_val:.6f}\n")
        f.write(f"min = {min_val:.6f}\n")
        f.write(f"max = {max_val:.6f}\n")

        if reg is not None:
            f.write("\n\n[linear_regression]\n\n")
            f.write(
                f"Pressure(time_s) = {reg['slope']:.3e} * time_s + {reg['intercept']:.6f}\n"
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
                f.write(f"n = {ci['n']}\n")
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
    time_mode: str,
) -> None:
    df = load_csv(csv_path)

    if len(df) == 0:
        print(f"{csv_path.name}: no valid t_rel/pressure rows")
        return

    y = df["pressure"].to_numpy(dtype=float)
    bins = bins_override if bins_override is not None else auto_bins(y)
    bins = max(1, min(DEFAULT_BINS_MAX, bins))

    x = df["t_rel"].to_numpy(dtype=float)
    reg = regression(x, y) if len(df) >= 2 else None

    duration_s = float(df["t_rel"].iloc[-1]) if len(df) > 0 else 0.0
    time_override = None if time_mode == "auto" else time_mode
    time_unit, time_factor = choose_time_unit(duration_s, time_override)

    stem = csv_path.with_suffix("")
    pressure_png = Path(f"{stem}_pressure.png")
    hist_png = Path(f"{stem}_hist.png")
    stats_txt = Path(f"{stem}_stats.txt")
    regression_png = Path(f"{stem}_regression.png")

    plot_pressure(df, pressure_png, grid, dpi, time_unit, time_factor)
    plot_hist(df, hist_png, bins, grid, dpi)
    write_stats(csv_path, df, reg, slope_th, stats_txt)

    if reg is not None and abs(reg["slope"]) <= slope_th:
        plot_regression(df, reg, regression_png, grid, dpi, time_unit, time_factor)

    print(f"Analysed: {csv_path.name}")
    print(f"  wrote: {pressure_png.name}")
    print(f"  wrote: {hist_png.name}")
    print(f"  wrote: {stats_txt.name}")
    if reg is not None and abs(reg["slope"]) <= slope_th:
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
    parser.add_argument(
        "--time",
        choices=["auto", "s", "min", "h", "d"],
        default="auto",
        help="Time unit for plots: auto, s, min, h, or d (default: auto)",
    )

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
                time_mode=args.time,
            )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())