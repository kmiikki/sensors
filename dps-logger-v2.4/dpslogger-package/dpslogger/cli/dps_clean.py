#!/usr/bin/env python3
"""Clean DPSlogger CSV files by detecting and handling spike-like artifacts.

This tool is designed to work with the DPSlogger v2.4 file naming layout:

- dps_summary_<session>.csv
- dps_addrNN_<session>.csv

It writes cleaned CSV files to an output subdirectory while preserving the
original DPS-compatible CSV filenames. This keeps the cleaned files directly
usable with dps_plot.py through --dir.

Typical usage:

    dps-clean
    dps-clean --plot-clean
    dps-clean --interpolate
    dps-clean --session 20260513-143623 --plot-clean

Default mode is conservative:

- hard spikes -> NaN
- soft spikes -> keep original value, but report them

The --plot-clean preset interpolates soft spikes for cleaner plots while
keeping hard spikes as NaN. The --interpolate preset interpolates both soft and
hard spikes when it is safe to do so.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

import numpy as np
import pandas as pd

VERSION = "0.1.1"

DETAIL_RE = re.compile(r"^dps_addr(?P<addr>\d{2})_(?P<session>.+)\.csv$")
SUMMARY_RE = re.compile(r"^dps_summary_(?P<session>.+)\.csv$")

DEFAULT_WINDOW = 5
DEFAULT_SOFT_THRESHOLD = 0.3
PLOT_CLEAN_SOFT_THRESHOLD = 0.10
INTERPOLATE_SOFT_THRESHOLD = 0.10
DEFAULT_HARD_THRESHOLD = 5.0
DEFAULT_MAX_INTERPOLATE_GAP = 1

Action = Literal["keep", "nan", "interpolate", "drop"]
SpikeType = Literal["OK", "SOFT_SPIKE", "HARD_SPIKE"]
SourceKind = Literal["summary", "detail"]


@dataclass(frozen=True)
class SessionFiles:
    """Files belonging to one DPSlogger measurement session."""

    session: str
    summary_csv: Path | None
    detail_csvs: tuple[Path, ...]


@dataclass(frozen=True)
class CleanMode:
    """Preset actions, thresholds, and output directory for a cleaning mode."""

    name: str
    out_dir_name: str
    hard_action: Action
    soft_action: Action
    soft_threshold: float
    hard_threshold: float = DEFAULT_HARD_THRESHOLD
    write_cleaned_csv: bool = True


@dataclass(frozen=True)
class RunInfo:
    """Information for one consecutive spike run."""

    run_id: int
    indices: tuple[int, ...]
    spike_type: SpikeType

    @property
    def length(self) -> int:
        """Return the number of points in this spike run."""
        return len(self.indices)


@dataclass
class CleanResult:
    """Result of cleaning one value column."""

    cleaned: pd.Series
    spike_rows: list[dict[str, object]] = field(default_factory=list)
    drop_indices: set[int] = field(default_factory=set)


def extract_summary_session(path: Path) -> str | None:
    """Return session id from a summary CSV filename."""
    match = SUMMARY_RE.match(path.name)
    return match.group("session") if match else None


def extract_detail_info(path: Path) -> tuple[str, str] | None:
    """Return (addrNN, session) from a detail CSV filename."""
    match = DETAIL_RE.match(path.name)
    if match is None:
        return None
    return f"addr{match.group('addr')}", match.group("session")


def find_summary_csv(directory: Path, session: str) -> Path | None:
    """Find the summary CSV for a session."""
    path = directory / f"dps_summary_{session}.csv"
    return path if path.exists() else None


def find_detail_csvs(directory: Path, session: str) -> tuple[Path, ...]:
    """Find per-address detail CSV files for a session."""
    return tuple(sorted(directory.glob(f"dps_addr??_{session}.csv")))


def discover_sessions(directory: Path) -> dict[str, SessionFiles]:
    """Discover DPSlogger sessions in a directory."""
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


def find_session(directory: Path, session: str) -> SessionFiles:
    """Return all files for a session."""
    summary_csv = find_summary_csv(directory, session)
    detail_csvs = find_detail_csvs(directory, session)
    if summary_csv is None and not detail_csvs:
        raise FileNotFoundError(f"No DPS CSV files found for session {session!r} in {directory}")
    return SessionFiles(session=session, summary_csv=summary_csv, detail_csvs=detail_csvs)


def find_latest_session(directory: Path) -> SessionFiles:
    """Find the latest session by lexicographic session id."""
    sessions = discover_sessions(directory)
    if not sessions:
        raise FileNotFoundError(f"No DPSlogger sessions found in {directory}")
    return sessions[sorted(sessions)[-1]]


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


def detail_sensor_name(path: Path) -> str:
    """Return a logical sensor label for a detail CSV."""
    info = extract_detail_info(path)
    if info is None:
        return path.stem
    addr_name, _session = info
    try:
        return f"p{int(addr_name.replace('addr', ''))}"
    except ValueError:
        return addr_name


def time_column(df: pd.DataFrame) -> str | None:
    """Return the preferred relative time column, if present."""
    for column in ("time", "t_rel", "time_s"):
        if column in df.columns:
            return column
    return None


def timestamp_column(df: pd.DataFrame) -> str | None:
    """Return the preferred timestamp column, if present."""
    for column in ("ts_iso", "timestamp", "t_epoch"):
        if column in df.columns:
            return column
    return None


def resolve_mode(args: argparse.Namespace) -> CleanMode:
    """Resolve CLI mode into default actions and output directory."""
    if args.detect_only:
        return CleanMode(
            name="detect-only",
            out_dir_name="spikes",
            hard_action="keep",
            soft_action="keep",
            soft_threshold=DEFAULT_SOFT_THRESHOLD,
            write_cleaned_csv=False,
        )
    if args.plot_clean:
        return CleanMode(
            name="plot-clean",
            out_dir_name="clean_plot",
            hard_action="nan",
            soft_action="interpolate",
            soft_threshold=PLOT_CLEAN_SOFT_THRESHOLD,
        )
    if args.interpolate:
        return CleanMode(
            name="interpolate",
            out_dir_name="clean_interpolated",
            hard_action="interpolate",
            soft_action="interpolate",
            soft_threshold=INTERPOLATE_SOFT_THRESHOLD,
        )
    return CleanMode(
        name="default",
        out_dir_name="clean_nan",
        hard_action="nan",
        soft_action="keep",
        soft_threshold=DEFAULT_SOFT_THRESHOLD,
    )


def local_median_reference(values: np.ndarray, index: int, radius: int) -> float:
    """Return the local median around index, excluding the index itself."""
    start = max(0, index - radius)
    stop = min(len(values), index + radius + 1)
    context = np.concatenate([values[start:index], values[index + 1 : stop]])
    context = context[np.isfinite(context)]
    if len(context) == 0:
        return float("nan")
    return float(np.median(context))


def classify_spikes(
    values: np.ndarray,
    *,
    radius: int,
    soft_threshold: float,
    hard_threshold: float,
    min_value: float | None,
    max_value: float | None,
) -> tuple[list[SpikeType], list[float], list[float], list[str], list[float]]:
    """Classify points as OK, soft spike, or hard spike."""
    spike_types: list[SpikeType] = []
    references: list[float] = []
    deltas: list[float] = []
    reasons: list[str] = []
    thresholds: list[float] = []

    for i, value in enumerate(values):
        if not np.isfinite(value):
            spike_types.append("OK")
            references.append(float("nan"))
            deltas.append(float("nan"))
            reasons.append("non_finite_input")
            thresholds.append(float("nan"))
            continue

        if min_value is not None and value < min_value:
            reference = local_median_reference(values, i, radius)
            spike_types.append("HARD_SPIKE")
            references.append(reference)
            deltas.append(abs(value - reference) if np.isfinite(reference) else float("nan"))
            reasons.append("below_min_value")
            thresholds.append(float(min_value))
            continue

        if max_value is not None and value > max_value:
            reference = local_median_reference(values, i, radius)
            spike_types.append("HARD_SPIKE")
            references.append(reference)
            deltas.append(abs(value - reference) if np.isfinite(reference) else float("nan"))
            reasons.append("above_max_value")
            thresholds.append(float(max_value))
            continue

        reference = local_median_reference(values, i, radius)
        references.append(reference)

        if not np.isfinite(reference):
            spike_types.append("OK")
            deltas.append(float("nan"))
            reasons.append("no_local_reference")
            thresholds.append(float("nan"))
            continue

        delta = abs(float(value) - reference)
        deltas.append(delta)

        if delta >= hard_threshold:
            spike_types.append("HARD_SPIKE")
            reasons.append("local_median_delta")
            thresholds.append(float(hard_threshold))
        elif delta >= soft_threshold:
            spike_types.append("SOFT_SPIKE")
            reasons.append("local_median_delta")
            thresholds.append(float(soft_threshold))
        else:
            spike_types.append("OK")
            reasons.append("ok")
            thresholds.append(float(soft_threshold))

    return spike_types, references, deltas, reasons, thresholds


def find_spike_runs(spike_types: list[SpikeType]) -> list[RunInfo]:
    """Group consecutive spike points into runs."""
    runs: list[RunInfo] = []
    current: list[int] = []
    current_type: SpikeType | None = None
    run_id = 0

    def flush() -> None:
        nonlocal run_id, current, current_type
        if current and current_type is not None:
            run_id += 1
            runs.append(RunInfo(run_id=run_id, indices=tuple(current), spike_type=current_type))
        current = []
        current_type = None

    for i, spike_type in enumerate(spike_types):
        if spike_type == "OK":
            flush()
            continue

        # Keep hard and soft runs separate. If a hard spike occurs adjacent to
        # a soft spike, the next logic may still process both safely, but the
        # report remains explicit about classification.
        if current and spike_type != current_type:
            flush()

        if not current:
            current = [i]
            current_type = spike_type
        else:
            current.append(i)

    flush()
    return runs


def nearest_valid_neighbor(
    values: np.ndarray,
    spike_mask: np.ndarray,
    start: int,
    step: int,
) -> int | None:
    """Find nearest finite non-spike neighbor from start moving by step."""
    i = start
    while 0 <= i < len(values):
        if not spike_mask[i] and np.isfinite(values[i]):
            return i
        i += step
    return None


def interpolate_run(
    cleaned: pd.Series,
    values: np.ndarray,
    x_values: np.ndarray,
    run: RunInfo,
    spike_mask: np.ndarray,
    max_interpolate_gap: int,
) -> tuple[bool, int | None, int | None]:
    """Interpolate a spike run in-place when safe."""
    if run.length > max_interpolate_gap:
        return False, None, None

    left = nearest_valid_neighbor(values, spike_mask, run.indices[0] - 1, -1)
    right = nearest_valid_neighbor(values, spike_mask, run.indices[-1] + 1, 1)
    if left is None or right is None:
        return False, left, right

    x_left = x_values[left]
    x_right = x_values[right]
    y_left = values[left]
    y_right = values[right]

    if not all(np.isfinite(v) for v in (x_left, x_right, y_left, y_right)):
        return False, left, right
    if x_left == x_right:
        return False, left, right

    for index in run.indices:
        x = x_values[index]
        if not np.isfinite(x):
            return False, left, right
        fraction = (x - x_left) / (x_right - x_left)
        cleaned.iloc[index] = y_left + fraction * (y_right - y_left)

    return True, left, right


def value_for_json(value: object) -> object:
    """Convert numpy/pandas scalars and NaN values to JSON-safe values."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if pd.isna(value):
        return None
    return value


def make_spike_row(
    *,
    session: str,
    source_kind: SourceKind,
    source_file: Path,
    df: pd.DataFrame,
    row_index: int,
    sensor: str,
    value_column: str,
    original_value: float,
    cleaned_value: object,
    spike_type: SpikeType,
    action_requested: Action,
    action_applied: str,
    reason: str,
    local_reference: float,
    delta_abs: float,
    threshold: float,
    run: RunInfo,
    run_index: int,
    can_interpolate: bool,
    left_index: int | None,
    right_index: int | None,
) -> dict[str, object]:
    """Build one spike report row."""
    cycle = df.iloc[row_index]["cycle"] if "cycle" in df.columns else None
    t_col = time_column(df)
    ts_col = timestamp_column(df)
    time_value = df.iloc[row_index][t_col] if t_col is not None else None
    ts_value = df.iloc[row_index][ts_col] if ts_col is not None else None

    return {
        "session": session,
        "source_kind": source_kind,
        "source_file": source_file.name,
        "row_index": row_index,
        "cycle": value_for_json(cycle),
        "time": value_for_json(time_value),
        "timestamp": value_for_json(ts_value),
        "sensor": sensor,
        "value_column": value_column,
        "original_value": value_for_json(original_value),
        "cleaned_value": value_for_json(cleaned_value),
        "spike_type": spike_type,
        "action_requested": action_requested,
        "action_applied": action_applied,
        "reason": reason,
        "local_reference": value_for_json(local_reference),
        "delta_abs": value_for_json(delta_abs),
        "threshold": value_for_json(threshold),
        "run_id": run.run_id,
        "run_length": run.length,
        "run_index": run_index,
        "can_interpolate": can_interpolate,
        "left_index": value_for_json(left_index),
        "right_index": value_for_json(right_index),
    }


def clean_value_column(
    *,
    df: pd.DataFrame,
    source_file: Path,
    source_kind: SourceKind,
    session: str,
    sensor: str,
    value_column: str,
    soft_threshold: float,
    hard_threshold: float,
    window: int,
    max_interpolate_gap: int,
    hard_action: Action,
    soft_action: Action,
    min_value: float | None,
    max_value: float | None,
) -> CleanResult:
    """Detect and clean spikes in a single numeric column."""
    if window < 3 or window % 2 == 0:
        raise ValueError("window must be an odd integer >= 3")

    radius = window // 2
    original = pd.to_numeric(df[value_column], errors="coerce")
    cleaned = original.copy()
    values = original.to_numpy(dtype=float)

    t_col = time_column(df)
    if t_col is None:
        x_values = np.arange(len(df), dtype=float)
    else:
        x_values = pd.to_numeric(df[t_col], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(x_values).any():
            x_values = np.arange(len(df), dtype=float)

    spike_types, references, deltas, reasons, thresholds = classify_spikes(
        values,
        radius=radius,
        soft_threshold=soft_threshold,
        hard_threshold=hard_threshold,
        min_value=min_value,
        max_value=max_value,
    )
    runs = find_spike_runs(spike_types)
    spike_mask = np.asarray([spike_type != "OK" for spike_type in spike_types], dtype=bool)

    result = CleanResult(cleaned=cleaned)

    for run in runs:
        action = hard_action if run.spike_type == "HARD_SPIKE" else soft_action
        can_interpolate = False
        left_index: int | None = None
        right_index: int | None = None
        action_applied = action

        if action == "interpolate":
            can_interpolate, left_index, right_index = interpolate_run(
                cleaned=cleaned,
                values=values,
                x_values=x_values,
                run=run,
                spike_mask=spike_mask,
                max_interpolate_gap=max_interpolate_gap,
            )
            if not can_interpolate:
                # Conservative fallback: do not silently keep a point the user
                # asked to interpolate when interpolation is unsafe.
                for index in run.indices:
                    cleaned.iloc[index] = np.nan
                action_applied = "nan_fallback"
        elif action == "nan":
            for index in run.indices:
                cleaned.iloc[index] = np.nan
        elif action == "drop":
            result.drop_indices.update(run.indices)
        elif action == "keep":
            pass
        else:
            raise ValueError(f"Unsupported action: {action}")

        for pos, index in enumerate(run.indices, start=1):
            result.spike_rows.append(
                make_spike_row(
                    session=session,
                    source_kind=source_kind,
                    source_file=source_file,
                    df=df,
                    row_index=index,
                    sensor=sensor,
                    value_column=value_column,
                    original_value=float(values[index]),
                    cleaned_value=cleaned.iloc[index],
                    spike_type=run.spike_type,
                    action_requested=action,
                    action_applied=action_applied,
                    reason=reasons[index],
                    local_reference=references[index],
                    delta_abs=deltas[index],
                    threshold=thresholds[index],
                    run=run,
                    run_index=pos,
                    can_interpolate=can_interpolate,
                    left_index=left_index,
                    right_index=right_index,
                )
            )

    return result


def clean_csv_file(
    *,
    csv_path: Path,
    session: str,
    source_kind: SourceKind,
    out_dir: Path,
    write_cleaned_csv: bool,
    soft_threshold: float,
    hard_threshold: float,
    window: int,
    max_interpolate_gap: int,
    hard_action: Action,
    soft_action: Action,
    min_value: float | None,
    max_value: float | None,
) -> tuple[list[dict[str, object]], Path | None]:
    """Clean one summary or detail CSV file."""
    df = pd.read_csv(csv_path)
    cleaned_df = df.copy()
    all_spike_rows: list[dict[str, object]] = []
    all_drop_indices: set[int] = set()

    if source_kind == "summary":
        value_columns = summary_value_columns(df)
        if not value_columns:
            raise ValueError(f"{csv_path.name}: no numeric summary value columns found")
        sensor_columns = [(column, column) for column in value_columns]
    else:
        if "pressure" not in df.columns:
            raise ValueError(f"{csv_path.name}: detail CSV must contain 'pressure' column")
        sensor_columns = [(detail_sensor_name(csv_path), "pressure")]

    for sensor, value_column in sensor_columns:
        clean_result = clean_value_column(
            df=df,
            source_file=csv_path,
            source_kind=source_kind,
            session=session,
            sensor=sensor,
            value_column=value_column,
            soft_threshold=soft_threshold,
            hard_threshold=hard_threshold,
            window=window,
            max_interpolate_gap=max_interpolate_gap,
            hard_action=hard_action,
            soft_action=soft_action,
            min_value=min_value,
            max_value=max_value,
        )
        cleaned_df[value_column] = clean_result.cleaned
        all_spike_rows.extend(clean_result.spike_rows)
        all_drop_indices.update(clean_result.drop_indices)

    if all_drop_indices:
        cleaned_df = cleaned_df.drop(index=sorted(all_drop_indices)).reset_index(drop=True)

    output_csv: Path | None = None
    if write_cleaned_csv:
        out_dir.mkdir(parents=True, exist_ok=True)
        output_csv = out_dir / csv_path.name
        cleaned_df.to_csv(output_csv, index=False)

    return all_spike_rows, output_csv


def write_spikes_csv(spike_rows: list[dict[str, object]], path: Path) -> None:
    """Write detailed spike report CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(spike_rows)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "session",
                "source_kind",
                "source_file",
                "row_index",
                "cycle",
                "time",
                "timestamp",
                "sensor",
                "value_column",
                "original_value",
                "cleaned_value",
                "spike_type",
                "action_requested",
                "action_applied",
                "reason",
                "local_reference",
                "delta_abs",
                "threshold",
                "run_id",
                "run_length",
                "run_index",
                "can_interpolate",
                "left_index",
                "right_index",
            ]
        )
    df.to_csv(path, index=False)


def write_clean_report(spike_rows: list[dict[str, object]], path: Path) -> pd.DataFrame:
    """Write compact per-file/per-sensor report CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not spike_rows:
        report = pd.DataFrame(
            columns=["source_file", "sensor", "spike_type", "action_applied", "count"]
        )
    else:
        df = pd.DataFrame(spike_rows)
        report = (
            df.groupby(["source_file", "sensor", "spike_type", "action_applied"], dropna=False)
            .size()
            .reset_index(name="count")
            .sort_values(["source_file", "sensor", "spike_type", "action_applied"])
        )
    report.to_csv(path, index=False)
    return report


def build_metadata(
    *,
    args: argparse.Namespace,
    mode: CleanMode,
    session_files: SessionFiles,
    out_dir: Path,
    output_csvs: list[Path],
    spikes_csv: Path,
    clean_report_csv: Path,
    spike_rows: list[dict[str, object]],
) -> dict[str, object]:
    """Build JSON metadata for one clean run."""
    counts: dict[str, int] = {"SOFT_SPIKE": 0, "HARD_SPIKE": 0}
    action_counts: dict[str, int] = {}
    for row in spike_rows:
        spike_type = str(row.get("spike_type", ""))
        action_applied = str(row.get("action_applied", ""))
        if spike_type in counts:
            counts[spike_type] += 1
        action_counts[action_applied] = action_counts.get(action_applied, 0) + 1

    input_files: list[str] = []
    if session_files.summary_csv is not None:
        input_files.append(session_files.summary_csv.name)
    input_files.extend(path.name for path in session_files.detail_csvs)

    return {
        "tool": "dps-clean",
        "version": VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "session": session_files.session,
        "mode": mode.name,
        "input_directory": str(args.dir.resolve()),
        "output_directory": str(out_dir.resolve()),
        "input_files": input_files,
        "output_csvs": [path.name for path in output_csvs],
        "spikes_csv": spikes_csv.name,
        "clean_report_csv": clean_report_csv.name,
        "parameters": {
            "method": "local-median",
            "window": args.window,
            "soft_threshold": args.soft_threshold,
            "hard_threshold": args.hard_threshold,
            "hard_action": args.hard_action,
            "soft_action": args.soft_action,
            "max_interpolate_gap": args.max_interpolate_gap,
            "min_value": args.min_value,
            "max_value": args.max_value,
        },
        "spike_counts": counts,
        "action_counts": action_counts,
        "total_spikes": len(spike_rows),
    }


def print_summary(
    *,
    mode: CleanMode,
    session_files: SessionFiles,
    out_dir: Path,
    spikes_csv: Path,
    clean_report_csv: Path,
    json_path: Path,
    report: pd.DataFrame,
) -> None:
    """Print a concise user-facing run summary."""
    print()
    print("Done.")
    print()
    print(f"Clean mode: {mode.name}")
    print(f"Session: {session_files.session}")
    print(f"Output directory: {out_dir}")
    print(f"Spike report: {spikes_csv}")
    print(f"Clean report: {clean_report_csv}")
    print(f"JSON log: {json_path}")

    if not report.empty:
        print()
        summary_report = report
        if session_files.summary_csv is not None and "source_file" in report.columns:
            summary_only = report[report["source_file"] == session_files.summary_csv.name]
            if not summary_only.empty:
                summary_report = summary_only
                print("Spike summary from summary CSV:")
            else:
                print("Spike summary:")
        else:
            print("Spike summary:")

        for row in summary_report.itertuples(index=False):
            print(f"  {row.sensor} {row.spike_type} {row.action_applied} = {row.count}")
    else:
        print()
        print("Spike summary: no spikes detected")

    if mode.write_cleaned_csv:
        print()
        print("To plot cleaned data, run:")
        print(f"  dps-plot --dir {out_dir} --session {session_files.session} --all")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Clean DPSlogger CSV spike artifacts")

    parser.add_argument(
        "--dir",
        type=Path,
        default=Path.cwd(),
        help="Input directory containing DPSlogger CSV files (default: current directory)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default depends on mode: clean_nan, clean_plot, clean_interpolated)",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Session id, for example 20260513-143623 (default: latest session)",
    )
    parser.add_argument(
        "-l",
        "--latest",
        action="store_true",
        help="Clean the latest DPSlogger session (default when --session is omitted)",
    )

    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--plot-clean",
        action="store_true",
        help="Preset for clean plots: hard spikes -> NaN, soft spikes -> interpolate",
    )
    modes.add_argument(
        "--interpolate",
        action="store_true",
        help="Preset: hard and soft spikes -> interpolate when safe",
    )
    modes.add_argument(
        "--detect-only",
        action="store_true",
        help="Only write spike reports, do not write cleaned DPS CSV files",
    )

    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW,
        help=f"Local median window size, odd integer >= 3 (default: {DEFAULT_WINDOW})",
    )
    parser.add_argument(
        "--soft-threshold",
        type=float,
        default=None,
        help=(
            "Soft spike threshold in data units. "
            f"Defaults by mode: default/detect-only={DEFAULT_SOFT_THRESHOLD}, "
            f"plot-clean/interpolate={PLOT_CLEAN_SOFT_THRESHOLD}."
        ),
    )
    parser.add_argument(
        "--hard-threshold",
        type=float,
        default=None,
        help=f"Hard spike threshold in data units (default: {DEFAULT_HARD_THRESHOLD})",
    )
    parser.add_argument(
        "--max-interpolate-gap",
        type=int,
        default=DEFAULT_MAX_INTERPOLATE_GAP,
        help=(
            "Maximum consecutive spike-run length that may be interpolated "
            f"(default: {DEFAULT_MAX_INTERPOLATE_GAP})"
        ),
    )
    parser.add_argument(
        "--min-value",
        type=float,
        default=None,
        help="Optional physical lower limit; values below this are hard spikes",
    )
    parser.add_argument(
        "--max-value",
        type=float,
        default=None,
        help="Optional physical upper limit; values above this are hard spikes",
    )
    parser.add_argument(
        "--hard-action",
        choices=["keep", "nan", "interpolate", "drop"],
        default=None,
        help="Override hard spike action",
    )
    parser.add_argument(
        "--soft-action",
        choices=["keep", "nan", "interpolate", "drop"],
        default=None,
        help="Override soft spike action",
    )

    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """Validate CLI arguments."""
    if args.window < 3 or args.window % 2 == 0:
        raise ValueError("--window must be an odd integer >= 3")
    if args.soft_threshold <= 0:
        raise ValueError("--soft-threshold must be > 0")
    if args.hard_threshold <= 0:
        raise ValueError("--hard-threshold must be > 0")
    if args.hard_threshold <= args.soft_threshold:
        raise ValueError("--hard-threshold must be greater than --soft-threshold")
    if args.max_interpolate_gap < 1:
        raise ValueError("--max-interpolate-gap must be >= 1")
    if args.min_value is not None and args.max_value is not None and args.min_value >= args.max_value:
        raise ValueError("--min-value must be smaller than --max-value")


def main() -> int:
    """CLI entry point."""
    args = parse_args()

    try:
        mode = resolve_mode(args)

        # Expert overrides are applied after the user-friendly preset has been
        # resolved. This keeps normal use simple while still supporting tuning.
        args.hard_action = args.hard_action or mode.hard_action
        args.soft_action = args.soft_action or mode.soft_action
        args.soft_threshold = args.soft_threshold if args.soft_threshold is not None else mode.soft_threshold
        args.hard_threshold = args.hard_threshold if args.hard_threshold is not None else mode.hard_threshold

        validate_args(args)

        input_dir = args.dir.resolve()
        if args.session:
            session_files = find_session(input_dir, args.session)
        else:
            session_files = find_latest_session(input_dir)

        out_dir = args.out_dir if args.out_dir is not None else Path(mode.out_dir_name)
        if not out_dir.is_absolute():
            out_dir = input_dir / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"dps-clean v{VERSION}")
        print(f"Input directory: {input_dir}")
        print(f"Session: {session_files.session}")
        print(f"Output directory: {out_dir}")
        print(f"Mode: {mode.name}")
        print(f"Method: local-median, window={args.window}")
        print(
            f"Soft spike: delta >= {args.soft_threshold:g}, "
            f"action={args.soft_action}"
        )
        print(
            f"Hard spike: delta >= {args.hard_threshold:g}, "
            f"action={args.hard_action}"
        )
        print(f"Max interpolate gap: {args.max_interpolate_gap}")

        all_spike_rows: list[dict[str, object]] = []
        output_csvs: list[Path] = []

        if session_files.summary_csv is not None:
            spike_rows, output_csv = clean_csv_file(
                csv_path=session_files.summary_csv,
                session=session_files.session,
                source_kind="summary",
                out_dir=out_dir,
                write_cleaned_csv=mode.write_cleaned_csv,
                soft_threshold=args.soft_threshold,
                hard_threshold=args.hard_threshold,
                window=args.window,
                max_interpolate_gap=args.max_interpolate_gap,
                hard_action=args.hard_action,
                soft_action=args.soft_action,
                min_value=args.min_value,
                max_value=args.max_value,
            )
            all_spike_rows.extend(spike_rows)
            if output_csv is not None:
                output_csvs.append(output_csv)
                print(f"  wrote: {output_csv.name}")

        for detail_csv in session_files.detail_csvs:
            spike_rows, output_csv = clean_csv_file(
                csv_path=detail_csv,
                session=session_files.session,
                source_kind="detail",
                out_dir=out_dir,
                write_cleaned_csv=mode.write_cleaned_csv,
                soft_threshold=args.soft_threshold,
                hard_threshold=args.hard_threshold,
                window=args.window,
                max_interpolate_gap=args.max_interpolate_gap,
                hard_action=args.hard_action,
                soft_action=args.soft_action,
                min_value=args.min_value,
                max_value=args.max_value,
            )
            all_spike_rows.extend(spike_rows)
            if output_csv is not None:
                output_csvs.append(output_csv)
                print(f"  wrote: {output_csv.name}")

        spikes_csv = out_dir / f"dps_spikes_{session_files.session}.csv"
        clean_report_csv = out_dir / f"dps_clean_report_{session_files.session}.csv"
        json_path = out_dir / f"dps_clean_{session_files.session}.json"

        write_spikes_csv(all_spike_rows, spikes_csv)
        report = write_clean_report(all_spike_rows, clean_report_csv)
        metadata = build_metadata(
            args=args,
            mode=mode,
            session_files=session_files,
            out_dir=out_dir,
            output_csvs=output_csvs,
            spikes_csv=spikes_csv,
            clean_report_csv=clean_report_csv,
            spike_rows=all_spike_rows,
        )
        json_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

        print_summary(
            mode=mode,
            session_files=session_files,
            out_dir=out_dir,
            spikes_csv=spikes_csv,
            clean_report_csv=clean_report_csv,
            json_path=json_path,
            report=report,
        )

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
