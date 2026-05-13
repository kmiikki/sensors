#!/usr/bin/env python3
"""Plot DPSlogger CSV files.

Supports both legacy single-sensor DPS CSV files and the DPSlogger v2.4
multi-sensor output layout:

- dps_addrNN_<session>.csv detail files
- dps_summary_<session>.csv summary files

Typical usage:

    dps-plot --latest --all
    dps-plot --session 20260511-083000 --all
    dps-plot dps_summary_20260511-083000.csv --combined
    dps-plot dps_addr01_20260511-083000.csv
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FormatStrFormatter, MaxNLocator, ScalarFormatter
from scipy import stats

DEFAULT_DPI = 300
HIGH_RES_DPI = 600
DEFAULT_SLOPE_TH = 1e-3
DEFAULT_BINS_MAX = 200
SUMMARY_PREFIX = "dps_summary_"
DETAIL_RE = re.compile(r"^dps_addr(?P<addr>\d{2})_(?P<session>.+)\.csv$")
SUMMARY_RE = re.compile(r"^dps_summary_(?P<session>.+)\.csv$")
LEGACY_TIME_COLUMNS = ("time", "t_rel")
LEGACY_TIMESTAMP_COLUMNS = ("timestamp", "t_epoch")


@dataclass(frozen=True)
class SessionFiles:
    """Files belonging to one DPSlogger measurement session."""

    session: str
    summary_csv: Path | None
    detail_csvs: tuple[Path, ...]


@dataclass(frozen=True)
class PlotModes:
    """Selected plotting modes."""

    combined: bool
    per_sensor: bool


def extract_summary_session(path: Path) -> str | None:
    """Return the session id from a summary CSV filename, if possible."""
    match = SUMMARY_RE.match(path.name)
    if match is None:
        return None
    return match.group("session")


def extract_detail_info(path: Path) -> tuple[str, str] | None:
    """Return ``(addrNN, session)`` from a detail CSV filename, if possible."""
    match = DETAIL_RE.match(path.name)
    if match is None:
        return None
    return f"addr{match.group('addr')}", match.group("session")


def is_summary_csv(path: Path) -> bool:
    """Return True when *path* looks like a DPS summary CSV."""
    return extract_summary_session(path) is not None


def is_detail_csv(path: Path) -> bool:
    """Return True when *path* looks like a DPS per-address detail CSV."""
    return extract_detail_info(path) is not None


def resolve_input_path(directory: Path, csv_name: str) -> Path:
    """Resolve a positional CSV argument relative to ``--dir``."""
    target = Path(csv_name)
    if not target.is_absolute():
        target = directory / target
    if not target.exists():
        raise FileNotFoundError(f"CSV file not found: {target}")
    return target


def find_summary_csv(directory: Path, session: str) -> Path | None:
    """Find the summary CSV for *session* in *directory*."""
    path = directory / f"dps_summary_{session}.csv"
    return path if path.exists() else None


def find_detail_csvs(directory: Path, session: str) -> tuple[Path, ...]:
    """Find all per-address detail CSV files for *session* in *directory*."""
    return tuple(sorted(directory.glob(f"dps_addr??_{session}.csv")))


def find_session(directory: Path, session: str) -> SessionFiles:
    """Collect summary and detail CSV files for *session*."""
    summary_csv = find_summary_csv(directory, session)
    detail_csvs = find_detail_csvs(directory, session)
    if summary_csv is None and not detail_csvs:
        raise FileNotFoundError(f"No DPS CSV files found for session {session!r} in {directory}")
    return SessionFiles(session=session, summary_csv=summary_csv, detail_csvs=detail_csvs)


def discover_sessions(directory: Path) -> dict[str, SessionFiles]:
    """Discover DPSlogger sessions in *directory*."""
    sessions: dict[str, dict[str, object]] = {}

    for path in sorted(directory.glob("dps_summary_*.csv")):
        session = extract_summary_session(path)
        if session is None:
            continue
        sessions.setdefault(session, {"summary": None, "details": []})["summary"] = path

    for path in sorted(directory.glob("dps_addr??_*.csv")):
        info = extract_detail_info(path)
        if info is None:
            continue
        _addr, session = info
        sessions.setdefault(session, {"summary": None, "details": []})["details"].append(path)

    return {
        session: SessionFiles(
            session=session,
            summary_csv=values["summary"] if isinstance(values["summary"], Path) else None,
            detail_csvs=tuple(sorted(values["details"])),  # type: ignore[arg-type]
        )
        for session, values in sessions.items()
    }


def find_latest_session(directory: Path) -> SessionFiles:
    """Find the latest DPSlogger session in *directory*.

    Session ids are timestamp-like in normal DPSlogger output, so lexical order is
    a good primary key. Modification time is used only as a fallback if filenames
    do not contain a recognizable session id.
    """
    sessions = discover_sessions(directory)
    if sessions:
        latest_key = sorted(sessions)[-1]
        return sessions[latest_key]

    csvs = sorted(directory.glob("*.csv"), key=lambda p: p.stat().st_mtime)
    if not csvs:
        raise FileNotFoundError(f"No CSV files found in {directory}")

    latest = csvs[-1]
    if is_summary_csv(latest):
        session = extract_summary_session(latest)
        assert session is not None
        return find_session(directory, session)
    if is_detail_csv(latest):
        info = extract_detail_info(latest)
        assert info is not None
        _addr, session = info
        return find_session(directory, session)

    return SessionFiles(session=latest.stem, summary_csv=None, detail_csvs=(latest,))


def choose_modes(args: argparse.Namespace, source_kind: str) -> PlotModes:
    """Resolve plotting mode flags into a concrete mode selection."""
    if args.all:
        return PlotModes(combined=True, per_sensor=True)

    if args.combined or args.summary or args.per_sensor:
        return PlotModes(
            combined=bool(args.combined or args.summary),
            per_sensor=bool(args.per_sensor),
        )

    # Sensible defaults:
    # - single detail CSV: one per-sensor plot
    # - explicit summary CSV: combined plot
    # - session/latest/directory workflow: all useful plots
    if source_kind == "detail":
        return PlotModes(combined=False, per_sensor=True)
    if source_kind == "summary":
        return PlotModes(combined=True, per_sensor=False)
    return PlotModes(combined=True, per_sensor=True)


def get_first_existing_column(df: pd.DataFrame, candidates: Iterable[str], csv_path: Path) -> str:
    """Return the first candidate column present in *df*."""
    for column in candidates:
        if column in df.columns:
            return column
    joined = ", ".join(candidates)
    raise ValueError(f"{csv_path.name}: CSV must contain one of these columns: {joined}")


def normalize_time_columns(df: pd.DataFrame, csv_path: Path) -> pd.DataFrame:
    """Normalize v2.4 and legacy time column names.

    v2.4 uses ``time`` and ``timestamp``. Legacy files may use ``t_rel`` and
    ``t_epoch``. Internally the plotter uses ``time_s`` and preserves an optional
    ``timestamp`` column.
    """
    df = df.copy()
    time_column = get_first_existing_column(df, LEGACY_TIME_COLUMNS, csv_path)
    df["time_s"] = pd.to_numeric(df[time_column], errors="coerce")

    for timestamp_column in LEGACY_TIMESTAMP_COLUMNS:
        if timestamp_column in df.columns:
            df["timestamp"] = pd.to_numeric(df[timestamp_column], errors="coerce")
            break

    return df


def auto_bins(values: np.ndarray, coarse: bool = False) -> int:
    """Select histogram bin count using the Freedman-Diaconis rule."""
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
    """Build histogram bin edges for quantized measurement data."""
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
    """Choose a plain integer histogram bin count."""
    if bins_override is not None:
        bins = bins_override
        if coarse_hist:
            bins = max(10, bins // 3)
        return max(1, min(DEFAULT_BINS_MAX, bins))
    return auto_bins(values, coarse=coarse_hist)


def coarse_grouping_for_quantized(values: np.ndarray, target_bins: int) -> int:
    """Choose quantized-level grouping for coarse histograms."""
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
    """Choose either integer bins or explicit edges for a histogram.

    Explicit user input wins over automatic quantized-data detection:
    ``--bins N`` must mean exactly N bins. Without ``--bins``, the
    automatic path may use quantized bin edges, optionally grouped by
    coarse mode for a more readable overview histogram.
    """
    if bins_override is not None:
        return max(1, min(DEFAULT_BINS_MAX, int(bins_override)))

    target_bins = choose_histogram_bins(values, None, coarse_hist)

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


def validate_pressure_unit(df: pd.DataFrame, csv_path: Path) -> str:
    """Validate and return the pressure unit from a detail CSV."""
    if "unit" not in df.columns:
        return ""

    units = (
        df["unit"]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", np.nan)
        .dropna()
        .unique()
    )

    if len(units) == 0:
        return ""

    if len(units) > 1:
        raise ValueError(
            f"{csv_path.name}: CSV contains multiple pressure units: "
            f"{', '.join(units)}. Normalize pressure values and unit column before plotting."
        )

    return str(units[0])


def load_sensor_csv(csv_path: Path) -> pd.DataFrame:
    """Load a single-sensor detail CSV and normalize column names."""
    df = pd.read_csv(csv_path)
    if "pressure" not in df.columns:
        raise ValueError(f"{csv_path.name}: CSV must contain column 'pressure'")

    df = normalize_time_columns(df, csv_path)
    df["pressure"] = pd.to_numeric(df["pressure"], errors="coerce")
    df = df.dropna(subset=["time_s", "pressure"]).copy()
    df.attrs["pressure_unit"] = validate_pressure_unit(df, csv_path)

    info = extract_detail_info(csv_path)
    if info is not None:
        addr_name, _session = info
        df.attrs["sensor_address"] = addr_name.replace("addr", "")
        df.attrs["sensor_name"] = addr_name
    else:
        df.attrs["sensor_address"] = "unknown"
        df.attrs["sensor_name"] = csv_path.stem

    return df


def summary_value_columns(df: pd.DataFrame) -> list[str]:
    """Return logical sensor columns from a summary dataframe."""
    excluded = {"ts_iso", "timestamp", "t_epoch", "time", "t_rel", "time_s", "cycle"}
    columns: list[str] = []
    for column in df.columns:
        if column in excluded:
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        if numeric.notna().any():
            columns.append(column)
    return columns


def load_summary_csv(csv_path: Path) -> pd.DataFrame:
    """Load a DPSlogger v2.4 summary CSV."""
    df = pd.read_csv(csv_path)
    df = normalize_time_columns(df, csv_path)

    for column in summary_value_columns(df):
        df[column] = pd.to_numeric(df[column], errors="coerce")

    value_columns = summary_value_columns(df)
    if not value_columns:
        raise ValueError(f"{csv_path.name}: no logical sensor columns found")

    df = df.dropna(subset=["time_s"], how="any").copy()
    df.attrs["value_columns"] = value_columns
    return df


def infer_unit_from_detail_files(detail_csvs: Iterable[Path]) -> str:
    """Infer pressure unit from matching detail CSV files when available."""
    units: list[str] = []
    for path in detail_csvs:
        try:
            df = load_sensor_csv(path)
        except Exception:
            continue
        unit = get_pressure_unit(df)
        if unit:
            units.append(unit)

    unique_units = sorted(set(units))
    if len(unique_units) == 1:
        return unique_units[0]
    return ""


def get_pressure_label(unit: str = "") -> str:
    """Return a y-axis label for pressure."""
    return f"Pressure ({unit})" if unit else "Pressure"


def get_pressure_unit(df: pd.DataFrame) -> str:
    """Return pressure unit stored in dataframe metadata."""
    return str(df.attrs.get("pressure_unit", ""))


def configure_plain_axis(ax: plt.Axes, axis: str = "y") -> None:
    """Use plain, non-offset tick labels on the selected axis."""
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
    """Calculate linear regression in a numerically stable centered x-space."""
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
        "r2": float(result.rvalue**2),
        "pvalue": float(result.pvalue),
        "stderr": float(result.stderr),
    }


def ci95(values: np.ndarray) -> dict[str, float | str | int]:
    """Return mean and 95% confidence interval for stable pressure values."""
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
    """Choose display unit and divisor for a time axis."""
    factors = {"s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0}

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
    """Convert seconds into the selected display unit."""
    return values / factor


def choose_series_style(n_points: int, markers: bool = True) -> dict[str, float | str | None]:
    """Choose line/marker style based on number of samples."""
    if not markers:
        if n_points <= 300:
            return {"linewidth": 1.0, "markersize": 0.0, "marker": None, "alpha": 1.0}
        if n_points <= 1000:
            return {"linewidth": 0.8, "markersize": 0.0, "marker": None, "alpha": 0.95}
        if n_points <= 3000:
            return {"linewidth": 0.55, "markersize": 0.0, "marker": None, "alpha": 0.9}
        if n_points <= 10000:
            return {"linewidth": 0.4, "markersize": 0.0, "marker": None, "alpha": 0.9}
        return {"linewidth": 0.25, "markersize": 0.0, "marker": None, "alpha": 0.9}
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
    """Choose plot colors."""
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
    """Choose readable regression line width."""
    if bw:
        return max(1.6, data_linewidth * 3.0)
    return max(1.2, data_linewidth * 1.5)


def output_path(out_dir: Path, filename: str) -> Path:
    """Build an output path and ensure its directory exists."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / filename




def set_time_axis_limits(ax: plt.Axes, x_plot: np.ndarray) -> None:
    """Use exact time limits for time-series plots.

    Matplotlib adds a small default x-margin, which is visually unhelpful for
    measurement series that naturally start at t=0.  Clamp the x-axis to the
    first and last finite time value instead.
    """
    finite_x = np.asarray(x_plot, dtype=float)
    finite_x = finite_x[np.isfinite(finite_x)]
    if len(finite_x) == 0:
        return

    x_min = float(np.min(finite_x))
    x_max = float(np.max(finite_x))

    if x_min == x_max:
        pad = 0.5 if x_min == 0.0 else abs(x_min) * 0.05
        ax.set_xlim(x_min - pad, x_max + pad)
        return

    ax.set_xlim(x_min, x_max)

def plot_pressure_series(
    time_s: np.ndarray,
    pressure: np.ndarray,
    out: Path,
    grid: bool,
    dpi: int,
    time_unit: str,
    time_factor: float,
    bw: bool,
    label: str | None,
    unit: str = "",
    markers: bool = True,
) -> None:
    """Write a pressure-vs-time plot for one sensor."""
    fig, ax = plt.subplots()

    x_plot = convert_time_axis(time_s, time_factor)
    style = choose_series_style(len(pressure), markers=markers)
    theme = choose_plot_theme(bw)

    ax.plot(
        x_plot,
        pressure,
        color=theme["series"],
        marker=style["marker"],
        linestyle="-",
        linewidth=style["linewidth"],
        markersize=style["markersize"],
        alpha=style["alpha"],
        label=label,
    )
    ax.set_xlabel(f"Time ({time_unit})")
    ax.set_ylabel(get_pressure_label(unit))
    configure_plain_axis(ax, axis="x")
    configure_plain_axis(ax, axis="y")
    set_time_axis_limits(ax, x_plot)

    if label:
        ax.legend()
    if grid:
        ax.grid(True)

    fig.tight_layout()
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


def plot_combined_summary(
    df: pd.DataFrame,
    sensor_columns: list[str],
    out: Path,
    grid: bool,
    dpi: int,
    time_unit: str,
    time_factor: float,
    bw: bool,
    unit: str = "",
    markers: bool = False,
) -> None:
    """Write a combined plot from summary logical sensor columns."""
    fig, ax = plt.subplots()

    time_s = df["time_s"].to_numpy(dtype=float)
    x_plot = convert_time_axis(time_s, time_factor)
    style = choose_series_style(len(df), markers=markers)

    bw_linestyles = ["-", "--", ":", "-."]
    bw_markers = ["o", "s", "^", "D"]

    for index, sensor_column in enumerate(sensor_columns):
        y = pd.to_numeric(df[sensor_column], errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(time_s) & np.isfinite(y)
        if not np.any(valid):
            continue

        plot_kwargs = {
            "marker": style["marker"],
            "linestyle": "-",
            "linewidth": style["linewidth"],
            "markersize": style["markersize"],
            "alpha": style["alpha"],
            "label": sensor_column,
        }

        if bw:
            # In black-and-white mode the combined plot must not use the
            # matplotlib color cycle. Use one color and distinguish sensors
            # by line style. If markers are enabled, use distinct marker
            # shapes as an additional cue.
            plot_kwargs["color"] = "black"
            plot_kwargs["linestyle"] = bw_linestyles[index % len(bw_linestyles)]
            if markers:
                plot_kwargs["marker"] = bw_markers[index % len(bw_markers)]

        ax.plot(
            x_plot[valid],
            y[valid],
            **plot_kwargs,
        )

    ax.set_xlabel(f"Time ({time_unit})")
    ax.set_ylabel(get_pressure_label(unit))
    configure_plain_axis(ax, axis="x")
    configure_plain_axis(ax, axis="y")
    set_time_axis_limits(ax, x_plot)
    ax.legend()

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
    """Write a pressure histogram for one detail CSV."""
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

    ax.set_xlabel(get_pressure_label(get_pressure_unit(df)))
    ax.set_ylabel("Count")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))

    fig.canvas.draw()
    ticks = ax.get_xticks()
    tick_step = abs(float(ticks[1] - ticks[0])) if len(ticks) >= 2 else 1.0
    decimals = max(0, int(math.ceil(-math.log10(tick_step)))) if tick_step > 0 else 3
    decimals = min(decimals, 6)
    ax.xaxis.set_major_formatter(FormatStrFormatter(f"%.{decimals}f"))

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
    """Write a regression diagnostic plot for stable single-sensor data."""
    fig, ax = plt.subplots()

    x = df["time_s"].to_numpy(dtype=float)
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
    ax.set_ylabel(get_pressure_label(get_pressure_unit(df)))
    configure_plain_axis(ax, axis="x")
    configure_plain_axis(ax, axis="y")
    set_time_axis_limits(ax, x_plot)

    if grid:
        ax.grid(True)

    pressure_unit = get_pressure_unit(df) or "pressure_unit"
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
    """Write text statistics for a single-sensor detail CSV."""
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

    pressure_unit = get_pressure_unit(df) or "unknown"
    sensor_address = str(df.attrs.get("sensor_address", "unknown"))

    interval = 0.0
    if len(df) >= 2:
        diffs = np.diff(df["time_s"].to_numpy(dtype=float))
        if len(diffs) > 0:
            interval = float(np.median(diffs))

    duration = float(df["time_s"].iloc[-1]) if len(df) > 0 else 0.0
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


def session_from_detail_or_stem(csv_path: Path) -> str:
    """Return session id from detail/summary filename or fall back to stem."""
    summary_session = extract_summary_session(csv_path)
    if summary_session is not None:
        return summary_session
    detail_info = extract_detail_info(csv_path)
    if detail_info is not None:
        _addr, session = detail_info
        return session
    return csv_path.stem


def detail_plot_name(csv_path: Path, session: str) -> str:
    """Return required per-sensor pressure plot filename."""
    info = extract_detail_info(csv_path)
    if info is None:
        return f"{csv_path.stem}_plot.png"
    addr_name, _session = info
    return f"dps_{addr_name}_plot_{session}.png"


def analyse_detail_file(
    csv_path: Path,
    out_dir: Path,
    bins_override: int | None,
    slope_th: float,
    grid: bool,
    dpi: int,
    time_mode: str,
    bw: bool,
    coarse_hist: bool,
    markers: bool,
) -> None:
    """Create plots and statistics for one per-address detail CSV."""
    df = load_sensor_csv(csv_path)

    if len(df) == 0:
        print(f"{csv_path.name}: no valid time/pressure rows")
        return

    y = df["pressure"].to_numpy(dtype=float)
    hist_spec = choose_histogram_spec(y, bins_override, coarse_hist)
    x = df["time_s"].to_numpy(dtype=float)
    reg = regression(x, y) if len(df) >= 2 else None

    duration_s = float(df["time_s"].iloc[-1]) if len(df) > 0 else 0.0
    time_override = None if time_mode == "auto" else time_mode
    time_unit, time_factor = choose_time_unit(duration_s, time_override)

    session = session_from_detail_or_stem(csv_path)
    plot_png = output_path(out_dir, detail_plot_name(csv_path, session))
    hist_png = output_path(out_dir, f"{csv_path.stem}_hist.png")
    stats_txt = output_path(out_dir, f"{csv_path.stem}_stats.txt")
    regression_png = output_path(out_dir, f"{csv_path.stem}_regression.png")

    label = str(df.attrs.get("sensor_name", csv_path.stem))
    plot_pressure_series(
        time_s=x,
        pressure=y,
        out=plot_png,
        grid=grid,
        dpi=dpi,
        time_unit=time_unit,
        time_factor=time_factor,
        bw=bw,
        label=label,
        unit=get_pressure_unit(df),
        markers=markers,
    )
    plot_hist(df, hist_png, hist_spec, grid, dpi, bw)
    write_stats(csv_path, df, reg, slope_th, stats_txt)

    if reg is not None and abs(reg["slope"]) <= slope_th:
        plot_regression(df, reg, regression_png, grid, dpi, time_unit, time_factor, bw)

    print(f"Analysed detail: {csv_path.name}")
    print(f"  wrote: {plot_png.name}")
    print(f"  wrote: {hist_png.name}")
    print(f"  wrote: {stats_txt.name}")
    if reg is not None and abs(reg["slope"]) <= slope_th:
        print(f"  wrote: {regression_png.name}")


def analyse_summary_file(
    summary_csv: Path,
    out_dir: Path,
    modes: PlotModes,
    grid: bool,
    dpi: int,
    time_mode: str,
    bw: bool,
    unit: str = "",
    per_sensor_markers: bool = True,
    combined_markers: bool = False,
) -> None:
    """Create combined and/or per-logical-sensor plots from a summary CSV."""
    df = load_summary_csv(summary_csv)
    sensor_columns = list(df.attrs["value_columns"])
    session = session_from_detail_or_stem(summary_csv)

    duration_s = float(df["time_s"].iloc[-1]) if len(df) > 0 else 0.0
    time_override = None if time_mode == "auto" else time_mode
    time_unit, time_factor = choose_time_unit(duration_s, time_override)
    time_s = df["time_s"].to_numpy(dtype=float)

    if modes.combined:
        combined_png = output_path(out_dir, f"dps_summary_plot_{session}.png")
        plot_combined_summary(
            df=df,
            sensor_columns=sensor_columns,
            out=combined_png,
            grid=grid,
            dpi=dpi,
            time_unit=time_unit,
            time_factor=time_factor,
            bw=bw,
            unit=unit,
            markers=combined_markers,
        )
        print(f"Analysed summary: {summary_csv.name}")
        print(f"  wrote: {combined_png.name}")

    if modes.per_sensor:
        for sensor_column in sensor_columns:
            pressure = pd.to_numeric(df[sensor_column], errors="coerce").to_numpy(dtype=float)
            valid = np.isfinite(time_s) & np.isfinite(pressure)
            if not np.any(valid):
                print(f"  skipped: {sensor_column} has no valid values")
                continue
            out = output_path(out_dir, f"dps_{sensor_column}_plot_{session}.png")
            plot_pressure_series(
                time_s=time_s[valid],
                pressure=pressure[valid],
                out=out,
                grid=grid,
                dpi=dpi,
                time_unit=time_unit,
                time_factor=time_factor,
                bw=bw,
                label=sensor_column,
                unit=unit,
                markers=per_sensor_markers,
            )
            print(f"  wrote: {out.name}")


def analyse_session(
    session_files: SessionFiles,
    out_dir: Path,
    modes: PlotModes,
    bins_override: int | None,
    slope_th: float,
    grid: bool,
    dpi: int,
    time_mode: str,
    bw: bool,
    coarse_hist: bool,
    per_sensor_markers: bool,
    combined_markers: bool,
) -> None:
    """Analyse all requested outputs for a DPSlogger session."""
    unit = infer_unit_from_detail_files(session_files.detail_csvs)

    if modes.per_sensor:
        if session_files.detail_csvs:
            for detail_csv in session_files.detail_csvs:
                analyse_detail_file(
                    csv_path=detail_csv,
                    out_dir=out_dir,
                    bins_override=bins_override,
                    slope_th=slope_th,
                    grid=grid,
                    dpi=dpi,
                    time_mode=time_mode,
                    bw=bw,
                    coarse_hist=coarse_hist,
                    markers=per_sensor_markers,
                )
        elif session_files.summary_csv is not None:
            analyse_summary_file(
                summary_csv=session_files.summary_csv,
                out_dir=out_dir,
                modes=PlotModes(combined=False, per_sensor=True),
                grid=grid,
                dpi=dpi,
                time_mode=time_mode,
                bw=bw,
                unit=unit,
                per_sensor_markers=per_sensor_markers,
                combined_markers=combined_markers,
            )

    if modes.combined:
        if session_files.summary_csv is not None:
            analyse_summary_file(
                summary_csv=session_files.summary_csv,
                out_dir=out_dir,
                modes=PlotModes(combined=True, per_sensor=False),
                grid=grid,
                dpi=dpi,
                time_mode=time_mode,
                bw=bw,
                unit=unit,
                per_sensor_markers=per_sensor_markers,
                combined_markers=combined_markers,
            )
        elif session_files.detail_csvs:
            # Fallback for old data without summary CSV: create a temporary combined
            # dataframe with p<addr> labels inferred from dps_addrNN filenames.
            dfs: list[pd.DataFrame] = []
            for detail_csv in session_files.detail_csvs:
                df = load_sensor_csv(detail_csv)
                info = extract_detail_info(detail_csv)
                if info is None:
                    label = detail_csv.stem
                else:
                    addr_name, _session = info
                    label = f"p{int(addr_name.replace('addr', ''))}"
                dfs.append(df[["time_s", "pressure"]].rename(columns={"pressure": label}))

            if dfs:
                combined = dfs[0]
                for df in dfs[1:]:
                    combined = pd.merge(combined, df, on="time_s", how="outer")
                combined = combined.sort_values("time_s")
                combined.attrs["value_columns"] = [c for c in combined.columns if c != "time_s"]

                synthetic_summary = out_dir / f"dps_summary_{session_files.session}.csv"
                analyse_summary_file(
                    summary_csv=write_temp_summary(combined, synthetic_summary),
                    out_dir=out_dir,
                    modes=PlotModes(combined=True, per_sensor=False),
                    grid=grid,
                    dpi=dpi,
                    time_mode=time_mode,
                    bw=bw,
                    unit=unit,
                    per_sensor_markers=per_sensor_markers,
                    combined_markers=combined_markers,
                )
                try:
                    synthetic_summary.unlink()
                except OSError:
                    pass


def write_temp_summary(df: pd.DataFrame, path: Path) -> Path:
    """Write a temporary summary CSV for the detail-only combined fallback."""
    tmp = df.copy()
    tmp = tmp.rename(columns={"time_s": "time"})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.to_csv(path, index=False)
    return path


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="DPSlogger CSV plotting tool")

    parser.add_argument("csv", nargs="?", help="CSV file to analyse")
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path.cwd(),
        help="Directory where CSV files are searched",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory where output files are written (default: same as input directory)",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Session id, for example 20260511-083000",
    )

    parser.add_argument("--summary", action="store_true", help="Create the combined summary plot")
    parser.add_argument("--combined", action="store_true", help="Create the combined summary plot")
    parser.add_argument("--per-sensor", action="store_true", help="Create one plot per sensor")
    parser.add_argument("--all", action="store_true", help="Create combined and per-sensor plots")

    parser.add_argument("--bins", type=int, default=None)
    parser.add_argument("--slope-th", type=float, default=DEFAULT_SLOPE_TH)
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--no-grid", action="store_true")
    parser.add_argument(
        "--time",
        "--time-unit",
        dest="time",
        choices=["auto", "s", "min", "h", "d"],
        default="auto",
        help="Time unit for plots: auto, s, min, h, or d (default: auto)",
    )
    parser.add_argument(
        "-l",
        "--last",
        "--latest",
        dest="latest",
        action="store_true",
        help="Analyse the latest DPSlogger session in the target directory",
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
        help="Use coarse histogram binning (default; kept for explicitness)",
    )
    parser.add_argument(
        "--fine-hist",
        action="store_true",
        help="Use fine automatic histogram binning, including quantized bin edges when detected",
    )

    parser.add_argument(
        "--no-markers",
        action="store_true",
        help="Disable point markers in pressure time-series plots",
    )
    parser.add_argument(
        "--combined-markers",
        action="store_true",
        help="Show point markers in the combined summary plot",
    )
    parser.add_argument(
        "--combined-no-markers",
        action="store_true",
        help="Disable point markers in the combined summary plot (default)",
    )

    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    grid = not args.no_grid
    dpi = HIGH_RES_DPI if args.high_res else args.dpi
    # Coarse histograms are the default because DPS sensors may return
    # visibly quantized values. Fine/quantized histograms remain available
    # for diagnostics with --fine-hist. Explicit --bins N always wins.
    coarse_hist = not args.fine_hist
    directory = args.dir.resolve()
    out_dir = (args.out_dir if args.out_dir is not None else directory).resolve()
    per_sensor_markers = not args.no_markers
    if args.no_markers or args.combined_no_markers:
        combined_markers = False
    else:
        combined_markers = bool(args.combined_markers)

    try:
        if args.csv:
            csv_path = resolve_input_path(directory, args.csv)
            out_dir = args.out_dir.resolve() if args.out_dir is not None else csv_path.parent.resolve()

            if is_summary_csv(csv_path):
                modes = choose_modes(args, source_kind="summary")
                session = extract_summary_session(csv_path)
                assert session is not None
                unit = infer_unit_from_detail_files(find_detail_csvs(csv_path.parent, session))
                analyse_summary_file(
                    summary_csv=csv_path,
                    out_dir=out_dir,
                    modes=modes,
                    grid=grid,
                    dpi=dpi,
                    time_mode=args.time,
                    bw=args.bw,
                    unit=unit,
                    per_sensor_markers=per_sensor_markers,
                    combined_markers=combined_markers,
                )
            else:
                modes = choose_modes(args, source_kind="detail")
                if modes.per_sensor:
                    analyse_detail_file(
                        csv_path=csv_path,
                        out_dir=out_dir,
                        bins_override=args.bins,
                        slope_th=args.slope_th,
                        grid=grid,
                        dpi=dpi,
                        time_mode=args.time,
                        bw=args.bw,
                        coarse_hist=coarse_hist,
                        markers=per_sensor_markers,
                    )
                if modes.combined:
                    session = session_from_detail_or_stem(csv_path)
                    analyse_session(
                        session_files=find_session(csv_path.parent, session),
                        out_dir=out_dir,
                        modes=PlotModes(combined=True, per_sensor=False),
                        bins_override=args.bins,
                        slope_th=args.slope_th,
                        grid=grid,
                        dpi=dpi,
                        time_mode=args.time,
                        bw=args.bw,
                        coarse_hist=coarse_hist,
                        per_sensor_markers=per_sensor_markers,
                        combined_markers=combined_markers,
                    )
            return 0

        if args.session:
            session_files = find_session(directory, args.session)
            modes = choose_modes(args, source_kind="session")
        elif args.latest:
            session_files = find_latest_session(directory)
            modes = choose_modes(args, source_kind="session")
        else:
            # Backward-compatible default: analyse all CSVs in the directory, but
            # prefer DPSlogger sessions when they can be discovered.
            sessions = discover_sessions(directory)
            if sessions:
                modes = choose_modes(args, source_kind="session")
                for session_key in sorted(sessions):
                    analyse_session(
                        session_files=sessions[session_key],
                        out_dir=out_dir,
                        modes=modes,
                        bins_override=args.bins,
                        slope_th=args.slope_th,
                        grid=grid,
                        dpi=dpi,
                        time_mode=args.time,
                        bw=args.bw,
                        coarse_hist=coarse_hist,
                        per_sensor_markers=per_sensor_markers,
                        combined_markers=combined_markers,
                    )
                return 0

            csvs = sorted(directory.glob("*.csv"))
            if not csvs:
                raise FileNotFoundError(f"No CSV files found in {directory}")
            modes = choose_modes(args, source_kind="detail")
            for csv_path in csvs:
                if modes.per_sensor:
                    analyse_detail_file(
                        csv_path=csv_path,
                        out_dir=out_dir,
                        bins_override=args.bins,
                        slope_th=args.slope_th,
                        grid=grid,
                        dpi=dpi,
                        time_mode=args.time,
                        bw=args.bw,
                        coarse_hist=coarse_hist,
                        markers=per_sensor_markers,
                    )
            return 0

        analyse_session(
            session_files=session_files,
            out_dir=out_dir,
            modes=modes,
            bins_override=args.bins,
            slope_th=args.slope_th,
            grid=grid,
            dpi=dpi,
            time_mode=args.time,
            bw=args.bw,
            coarse_hist=coarse_hist,
            per_sensor_markers=per_sensor_markers,
            combined_markers=combined_markers,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
