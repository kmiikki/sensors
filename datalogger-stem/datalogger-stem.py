#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
datalogger-stem.py — sensor-agnostic datalogger skeleton

Principles
----------
- Align start to a clean second-decimal boundary with get_sec_fractions(k) == 0.
- Use perf_counter-based scheduling to minimize drift over long runs.
- CTRL+C should not cut a measurement mid-cycle; finish the current cycle if possible.
- CSV writing via DataLog (default csv_sep="," for machine-friendly CSV).
- Keep terminal output human-friendly (comma + space).
- No sensor-specific code here; replace `read_once()` in your project.

Usage
-----
$ python datalogger-stem.py --interval 1.0 --base-dir data --prefix data \
    --csv-sep "," --err-csv-sep ", " --decimals 3

Author: Kim Miikki (original) + small cleanups
License: MIT
"""
from __future__ import annotations

import argparse
import signal
import time
from datetime import datetime
from time import sleep, perf_counter
from typing import Iterable, Optional

from logfile import DataLog, ErrorLog

# Defaults (can be overridden via CLI)
DEFAULT_INTERVAL: float = 1.0      # seconds
DEFAULT_DECIMALS: int = 3
DEFAULT_CSV_SEP: str = ","         # machine-friendly CSV
DEFAULT_ERR_CSV_SEP: str = ", "    # human-friendly error log


# ──────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────────────────────────────────────
def format_data(data: Iterable[float], decimals: int, sep: str) -> str:
    """Round values and join with `sep` for CSV-like output."""
    out = []
    for value in data:
        v = float(value)
        out.append(f"{round(v, decimals):.{decimals}f}")
    return sep.join(out)


def format_pretty(data: Iterable[float], decimals: int) -> str:
    """Human-friendly terminal line (comma + space)."""
    return format_data(data, decimals, ", ")


# ──────────────────────────────────────────────────────────────────────────────
# Time alignment and drift-free scheduling
# ──────────────────────────────────────────────────────────────────────────────
def get_sec_fractions(resolution=5) -> float:
    """
    Returns the fractional part of the current second, 
    rounded to 'resolution' decimal places.
    Useful for waiting until the next full second to start logging.
    """
    now = datetime.now()
    return round(now.timestamp() % 1, resolution)

# ──────────────────────────────────────────────────────────────────────────────
# Signal handling (finish current cycle before stopping)
# ──────────────────────────────────────────────────────────────────────────────
halt_requested = False   # user requested stop (CTRL+C)
disable_halt = False     # True during a measurement cycle -> don't stop immediately
_sig_installed = False


def _sig_handler(signum, frame) -> None:
    """Arm a clean shutdown; the loop checks this between cycles."""
    global halt_requested
    halt_requested = True


def install_signal_handlers_once() -> None:
    global _sig_installed
    if _sig_installed:
        return
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
    _sig_installed = True


# ──────────────────────────────────────────────────────────────────────────────
# Placeholder for measurement — replace in your project
# ──────────────────────────────────────────────────────────────────────────────
def read_once() -> Iterable[float]:
    """
    Placeholder: return list-like measurement data.
    Replace with a real implementation in your project.
    """
    # Example only (remove/replace in your project):
    return [time.time()]


# ──────────────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────────────
def run_logger(
    base_dir: str,
    file_prefix: str,
    csv_sep: str,
    err_csv_sep: str,
    interval_s: float,
    decimals_out: int,
) -> int:
    """
    Run the datalogger until interrupted.

    Returns 0 on normal stop; non-zero on fatal error.
    """
    
    global disable_halt
    
    install_signal_handlers_once()

    # Wait until next full second
    print("Synchronizing time.")
    while get_sec_fractions(4) != 0:
        pass
    next_deadline = perf_counter()
    ts_start = int(time.time())
    
    data_log = DataLog(
        timestamp=ts_start,
        file_path=base_dir,
        name=file_prefix or "data",
        ext="csv",
        subdirs=True,
        ts_prefix=False,
        csv_sep=csv_sep,
    )
    err_log = ErrorLog(
        dir_path=data_log.dir_path,
        name="error",
        ext="log",
        dt_part=data_log.dt_part,
        ts_prefix=True,
        csv_sep=err_csv_sep,
    )

    # Minimal header example; adjust later in your project
    header = ["ts"]
    data_log.write(header)

    measurement_index = 0
    rows = 0

    try:
        while True:
            if halt_requested and not disable_halt:
                # Not in the middle of a measurement -> stop cleanly
                break

            # One measurement cycle
            try:
                disable_halt = True  # protect the cycle from immediate stop

                values = read_once()  # replace with your real reader
                csv_line = format_data(values, decimals_out, csv_sep)
                data_log.write(csv_line)

                # Human-friendly echo to terminal
                print(format_pretty(values, decimals_out))

                rows += 1
                measurement_index += 1
            except Exception as e:
                # Log error but keep the loop running
                err_log.write(timestamp=int(time.time()),
                              measurement=measurement_index,
                              error_text=str(e))
            finally:
                disable_halt = False  # cycle done -> stopping allowed

            # Compute next slot first (drift-resistant pattern)
            next_deadline += interval_s

            # Sleep until the next slot (may be <= 0 if running behind)
            delay = next_deadline - perf_counter()
            if delay > 0:
                sleep(delay)

    except Exception as e:
        err_log.write(timestamp=int(time.time()),
                      measurement=measurement_index,
                      error_text=f"fatal: {e}")
        return 2

    print(f"Stopped. Total rows written: {rows}")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sensor-agnostic datalogger skeleton (no sensor code here)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                   help="Measurement interval in seconds")
    p.add_argument("--base-dir", type=str, default="data",
                   help="Base directory for output files")
    p.add_argument("--prefix", type=str, default="data",
                   help="Filename prefix for the data log")
    p.add_argument("--csv-sep", type=str, default=DEFAULT_CSV_SEP,
                   help="CSV separator for measurement data")
    p.add_argument("--err-csv-sep", type=str, default=DEFAULT_ERR_CSV_SEP,
                   help="CSV separator for the error log")
    p.add_argument("--decimals", type=int, default=DEFAULT_DECIMALS,
                   help="Number of decimals in formatted outputs")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    return run_logger(
        base_dir=args.base_dir,
        file_prefix=args.prefix,
        csv_sep=args.csv_sep,
        err_csv_sep=args.err_csv_sep,
        interval_s=float(args.interval),
        decimals_out=int(args.decimals),
    )


if __name__ == "__main__":
    raise SystemExit(main())
