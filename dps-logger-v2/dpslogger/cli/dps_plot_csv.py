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
HIGH_RES_DPI = 600
DEFAULT_SLOPE_TH = 1e-3
DEFAULT_BINS_MAX = 200


def resolve_targets(
    directory: Path,
    csv_name: str | None,
    last_only: bool = False,
) -> list[Path]:
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

    if last_only:
        return [files[-1]]
    return files


def auto_bins(values: np.ndarray, coarse: bool = False) -> int:
    """
    Select histogram bin count using the Freedman–Diaconis rule.

    In coarse mode the returned count is reduced to produce a visually simpler
    histogram while still scaling with the data size.
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
        bins = int(round(math.sqrt(n)))
    else:
        bin_width = 2.0 * iqr / (n ** (1.0 / 3.0))
        if bin_width <= 0:
            bins = int(round(math.sqrt(n)))
        else:
            bins = int(math.ceil(data_range / bin_width))

    bins = max(10, min(DEFAULT_BINS_MAX, bins))

    if coarse:
        bins = max(10, bins // 3)

    return max(1, min(DEFAULT_BINS_MAX, bins))


def quantized_bin_edges(values: np.ndarray, grouping: int = 1) -> np.ndarray | None:
    """
    Build histogram bin edges for quantized measurement data.

    Strategy:
    - Infer the quantization step from the smallest positive difference
      between observed unique values.
    - Build one bin for every possible quantized level between observed
      minimum and maximum.
    - Optionally merge adjacent quantized levels using ``grouping``.

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

    indices = np.round((unique_vals - data_min) / step)
    reconstructed = data_min + indices * step
    if not np.allclose(unique_vals, reconstructed, rtol=0.0, atol=1e-12):
        return None

    n_levels = int(round((data_max - data_min) / step)) + 1
    if n_levels < 2:
        return None

    grouping = max(1, int(grouping))
    grouped_step = step * grouping
    levels = data_min + grouped_step * np.arange(int(math.ceil(n_levels / grouping)), dtype=float)

    edges = np.empty(len(levels) + 1, dtype=float)
    edges[:-1] = levels - grouped_step / 2.0
    edges[-1] = levels[-1] + grouped_step / 2.0
    return edges


def choose_histogram_bins(values: np.ndarray, bins_override: int | None, coarse_hist: bool) -> int:
    if bins_override is not None:
        bins = bins_override
        if coarse_hist:
            bins = max(10, bins // 3)
        return max(1, min(DEFAULT_BINS_MAX, bins))

    return auto_bins(values, coarse=coarse_hist)


def coarse_grouping_for_quantized(values: np.ndarray, target_bins: int) -> int:
    edges = quantized_bin_edges(values)
    if edges is None:
        return 1

    n_bins = len(edges) - 1
    if n_bins <= 0:
        return 1

    target_bins = max(1, target_bins)
    return max(1, int(math.ceil(n_bins / target_bins)))


def choose_histogram_spec(
    values: np.ndarray,
    bins_override: int | None,
    coarse_hist: bool,
) -> int | np.ndarray:
    target_bins = choose_histogram_bins(values, bins_override, coarse_hist)

    if coarse_hist:
        grouping = coarse_grouping_for_quantized(values, target_bins)
        edges = quantized_bin_edges(values, grouping=grouping)
        if edges is not None:
            return edges
        return target_bins

    edges = quantized_bin_edges(values)
    if edges is not None:
        return edges

    return target_bins


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


def choose_series_style(n_points: int) -> dict[str, float | str | None]:
    if n_points <= 300:
        return {"linewidth": 1.0, "markersize": 3.0, "marker": "o", "alpha": 1.0}
    if n_points <= 1000:
        return {"linewidth": 0.8, "markersize": 2.0, "marker": "o", "alpha": 0.9}
    if n_points <= 3000:
        return {"linewidth": 0.5, "markersize": 1.2, "marker": "o", "alpha": 0.85}
    if n_points <= 10000:
        return {"linewidth": 0.35, "markersize": 0.8, "marker": "o", "alpha": 0.8}
    return {"linewidth": 0.25, "markersize": 0.0, "marker": None, "alpha": 0.9}


def choose_plot_theme(bw: bool) -> dict[str, str]:
    if bw:
        return {
            "series": "black",
            "regression": "black",
            "hist_face": "0.65",
            "hist_edge": "black",
            "textbox_face": "white",
        }

    return {
        "series": "C0",
        "regression": "C1",
        "hist_face": "C0",
        "hist_edge": "black",
        "textbox_face": "white",
    }


def regression_linewidth(bw: bool, data_linewidth: float) -> float:
    if bw:
        return max(1.6, data_linewidth * 3.0)
    return max(1.2, data_linewidth * 1.5)


def plot_pressure(
    df: pd.DataFrame,
    out: Path,
    grid: bool,
    dpi: int,
    time_unit: str,
    time_factor: float,
    bw: bool,
) -> None:
    fig, ax = plt.subplots()

    x = df["t_rel"].to_numpy(dtype=float)
    x_plot = convert_time_axis(x, time_factor)
    y = df["pressure"].to_numpy(dtype=float)
    style = choose_series_style(len(df))
    theme = choose_plot_theme(bw)

    ax.plot(
        x_plot,
        y,
        color=theme["series"],
        marker=style["marker"],
        linestyle="-",
        linewidth=style["linewidth"],
        markersize=style["markersize"],
        alpha=style["alpha"],
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


def plot_hist(
    df: pd.DataFrame,
    out: Path,
    hist_spec: int | np.ndarray,
    grid: bool,
    dpi: int,
    bw: bool,
) -> None:
    fig, ax = plt.subplots()

    y = df["pressure"].to_numpy(dtype=float)
    theme = choose_plot_theme(bw)

    ax.hist(
        y,
        bins=hist_spec,
        rwidth=1.0,
        color=theme["hist_face"],
        edgecolor=theme["hist_edge"],
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
    bw: bool,
) -> None:
    fig, ax = plt.subplots()

    x = df["t_rel"].to_numpy(dtype=float)
    x_plot = convert_time_axis(x, time_factor)
    y = df["pressure"].to_numpy(dtype=float)
    style = choose_series_style(len(df))
    theme = choose_plot_theme(bw)

    ax.plot(
        x_plot,
        y,
        color=theme["series"],
        marker=style["marker"],
        linestyle="-",
        linewidth=style["linewidth"],
        markersize=style["markersize"],
        alpha=style["alpha"],
        label="Measured pressure",
    )

    xr = np.array([x.min(), x.max()], dtype=float)
    xr_plot = convert_time_axis(xr, time_factor)
    yr = reg["slope"] * xr + reg["intercept"]
    ax.plot(
        xr_plot,
        yr,
        color=theme["regression"],
        linestyle="--" if bw else "-",
        linewidth=regression_linewidth(bw, float(style["linewidth"])),
        label="Linear regression",
    )

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
        bbox={"boxstyle": "round", "facecolor": theme["textbox_face"], "alpha": 0.85},
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
    bw: bool,
    coarse_hist: bool,
) -> None:
    df = load_csv(csv_path)

    if len(df) == 0:
        print(f"{csv_path.name}: no valid t_rel/pressure rows")
        return

    y = df["pressure"].to_numpy(dtype=float)
    hist_spec = choose_histogram_spec(y, bins_override, coarse_hist)

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

    plot_pressure(df, pressure_png, grid, dpi, time_unit, time_factor, bw)
    plot_hist(df, hist_png, hist_spec, grid, dpi, bw)
    write_stats(csv_path, df, reg, slope_th, stats_txt)

    if reg is not None and abs(reg["slope"]) <= slope_th:
        plot_regression(df, reg, regression_png, grid, dpi, time_unit, time_factor, bw)

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
    parser.add_argument(
        "-l",
        "--last",
        action="store_true",
        help="Analyse only the latest CSV file in the target directory",
    )
    parser.add_argument(
        "-b",
        "--bw",
        action="store_true",
        help="Use black-and-white / grayscale style for all plots",
    )
    parser.add_argument(
        "--high-res",
        action="store_true",
        help="Save figures at 600 dpi for publication-quality output",
    )
    parser.add_argument(
        "--coarse-hist",
        action="store_true",
        help="Use a coarser histogram binning for a smoother distribution view",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    grid = not args.no_grid
    dpi = HIGH_RES_DPI if args.high_res else args.dpi

    try:
        targets = resolve_targets(args.dir, args.csv, last_only=args.last)
        for csv_path in targets:
            analyse_file(
                csv_path=csv_path,
                bins_override=args.bins,
                slope_th=args.slope_th,
                grid=grid,
                dpi=dpi,
                time_mode=args.time,
                bw=args.bw,
                coarse_hist=args.coarse_hist,
            )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
