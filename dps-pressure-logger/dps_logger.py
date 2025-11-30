#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dps_logger_stem.py — DPS823A (RS-485) + RPi thermal datalogger skeleton

This is a DPS-specific variant built on top of the generic datalogger-stem
pattern. The key properties are:

- Same time synchronization pattern:
    print("Synchronizing time.")
    while get_sec_fractions(4) != 0:
        pass
    next_deadline = perf_counter()
    ts_start = int(time.time())

- Same halt / CTRL+C semantics:
    * `disable_halt` is True only during a measurement cycle.
    * SIGINT handler ignores Ctrl+C when `disable_halt` is True.
    * When Ctrl+C is pressed between cycles (`disable_halt == False`),
      `halt_requested` is set to True and the main loop performs a clean stop.

- Uses DPS8000Adapter on /dev/ttyLOG (by default) to read DPS823A.
- Uses rpi_thermal.read_thermal_sample() to log CPU temperature etc.
- Writes daily-rotated CSV via DataLog.

CSV columns
-----------
ts_iso         ISO8601 timestamp (from DPS, fallback to RPi time)
t_perf         perf_counter() timestamp in seconds
pressure       pressure (target unit, e.g. bar)
unit           pressure unit
source         e.g. "DPS8000" or error marker
cpu_temp_c     CPU temperature in °C
arm_freq_hz    ARM frequency in Hz
throttled_raw  raw bitfield from `vcgencmd get_throttled`
raw            optional RAW data from *Z (if --with-raw)

Usage example
-------------
$ python dps_logger_stem.py \\
    --interval 1.0 \\
    --base-dir data \\
    --prefix dps \\
    --port /dev/ttyLOG \\
    --unit bar \\
    --with-raw
"""

from __future__ import annotations

import argparse
import signal
import sys
import subprocess
import time
from datetime import datetime
from time import sleep, perf_counter
from typing import List, Optional

from logfile import DataLog, ErrorLog
from dps8000_adapter import DPS8000Adapter, DPS8000AdapterConfig, DPS8000Error
from rpi_thermal import read_thermal_sample

# Defaults
DEFAULT_INTERVAL: float = 1.0
DEFAULT_CSV_SEP: str = ","
DEFAULT_ERR_CSV_SEP: str = ", "
DEFAULT_UNIT: str = "bar"
DEFAULT_PORT: str = "/dev/ttyLOG"


# ──────────────────────────────────────────────────────────────────────────────
# Time alignment and drift-free scheduling
# ──────────────────────────────────────────────────────────────────────────────
def get_sec_fractions(resolution: int = 5) -> float:
    """
    Return the fractional part of the current second.

    The fractional part is rounded to `resolution` decimal places.
    This is used to wait until the next full second before starting
    the measurement loop.
    """
    now = datetime.now()
    return round(now.timestamp() % 1, resolution)


# ──────────────────────────────────────────────────────────────────────────────
# Signal handling (finish current cycle before stopping)
# ──────────────────────────────────────────────────────────────────────────────
disable_halt = False     # True during a measurement cycle → ignore SIGINT
_sig_installed = False


def _sig_handler(signum, frame) -> None:
    """
    SIGINT/SIGTERM handler, BME-style:

    - If `disable_halt` is True, we are in the middle of a measurement cycle.
      Ignore the signal and return immediately. The user can press Ctrl+C
      again when the program is between cycles.

    - If `disable_halt` is False, we are between cycles (safe point).
      Print a message and terminate the process immediately via SystemExit.
    """
    global disable_halt

    if disable_halt:
        # Measurement cycle is in progress → ignore this signal.
        return

    # Safe point: no measurement is running. Terminate immediately.
    print("\nTermination requested (Ctrl+C). Exiting...")
    raise SystemExit(0)


def install_signal_handlers_once() -> None:
    """
    Install SIGINT and SIGTERM handlers exactly once.
    """
    global _sig_installed
    if _sig_installed:
        return
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
    _sig_installed = True



# ──────────────────────────────────────────────────────────────────────────────
# DPS + RPi thermal: single measurement cycle
# ──────────────────────────────────────────────────────────────────────────────
class DPSRuntime:
    """
    Small container for DPS-logger runtime configuration and adapter.
    """
    def __init__(self, port: str, unit: str, with_raw: bool):
        self.port = port
        self.unit = unit
        self.with_raw = with_raw

        cfg = DPS8000AdapterConfig(
            port=port,
            baud=9600,
            device_unit=unit,
            target_unit=unit,
        )
        self.adapter = DPS8000Adapter(cfg)


def dps_read_once(rt: DPSRuntime, t_perf: float, ts_iso: str) -> List[str]:
    """
    Perform one DPS + RPi-thermal measurement cycle.

    Parameters
    ----------
    rt:
        DPSRuntime instance (adapter, config).
    t_perf:
        Measurement time from perf_counter(), taken at the *start* of
        this measurement cycle.
    ts_iso:
        Measurement wallclock time (ISO8601), taken at the *start* of
        this measurement cycle.

    Returns
    -------
    list[str]
        [ts_iso, t_perf, pressure, unit, source,
         cpu_temp_c, arm_freq_hz, throttled_raw, raw]
    """
    # DPS reading
    try:
        if rt.with_raw:
            s = rt.adapter.read_sample_with_raw()
        else:
            s = rt.adapter.read_sample()
    except DPS8000Error as e:
        # Map DPS error to a row with NaN pressure and error source.
        s = {
            "ts_iso": "",
            "t_perf": t_perf,
            "pressure": float("nan"),
            "unit": rt.unit,
            "source": f"DPS8000_ERR:{e}",
            "raw": f"ERR:{e}",
        }

    # RPi thermal reading (for diagnostics)
    th = read_thermal_sample()

    # Logging time = ts_iso (from caller), NOT device ts
    pressure = s.get("pressure", float("nan"))
    unit = s.get("unit", rt.unit)
    source = s.get("source", "DPS8000")
    raw = s.get("raw", "") if rt.with_raw else ""

    row = [
        ts_iso,
        f"{t_perf:.6f}",
        f"{float(pressure):.6f}" if pressure == pressure else "",  # NaN → empty
        unit,
        source,
        f"{th['cpu_temp_c']:.2f}",
        f"{th['arm_freq_hz']:.0f}",
        str(th["throttled_raw"]),
    ]

    if rt.with_raw:
        raw = s.get("raw", "")
        row.append(raw)
        
    return row


# ──────────────────────────────────────────────────────────────────────────────
# Main loop (timing + halt logic follows datalogger-stem)
# ──────────────────────────────────────────────────────────────────────────────
def run_logger(
    base_dir: str,
    file_prefix: str,
    csv_sep: str,
    err_csv_sep: str,
    interval_s: float,
    port: str,
    unit: str,
    with_raw: bool,
) -> int:
    """
    Run the DPS + RPi-thermal datalogger until interrupted.

    Parameters
    ----------
    base_dir:
        Directory where log files will be written.
    file_prefix:
        Prefix for the data-log filename.
    csv_sep:
        Separator used for data CSV.
    err_csv_sep:
        Separator used for error-log entries.
    interval_s:
        Measurement interval in seconds.
    port:
        Serial port for DPS823A, e.g. /dev/ttyLOG.
    unit:
        Pressure unit (both device_unit and target_unit).
    with_raw:
        If True, read and store RAW data from *Z command.

    Returns
    -------
    int
        0 on a clean stop, non-zero on a fatal error.
    """
    global disable_halt

    install_signal_handlers_once()
    
    # Timestamp for log file naming (independent of scheduling)
    ts_start_for_file = int(time.time())
	
	# Reference time for drift-free scheduling
    tp0 = perf_counter()     # perf_counter at (roughly) whole second
    count = 0                # measurement index, like in BME-logger

	# Wallclock timestamp for log file naming (independent of scheduling)
    ts_start = int(time.time())

    data_log = DataLog(
        timestamp=ts_start,
        file_path=base_dir,
        name=file_prefix or "dps",
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

    # Fixed header for DPS logger
    header = [
        "ts_iso",
        "t_perf",
        "pressure",
        "unit",
        "source",
        "cpu_temp_c",
        "arm_freq_hz",
        "throttled_raw",
    ]
    if with_raw:
        header.append("raw")
        
    data_log.write(header)

    rt = DPSRuntime(port=port, unit=unit, with_raw=with_raw)

    count = 0  # measurement index

    # Open adapter once, and make sure it's closed on exit
    try:
        rt.adapter.open()

        # IDENT once
        try:
            ident = rt.adapter.identify()
        except DPS8000Error as e:
            ident = f"IDENT_ERR:{e}"
        print(f"DPS IDENT: {ident}")
        print(f"Logging to {data_log.dir_path} with prefix '{file_prefix or 'dps'}'")
        print(f"Interval: {interval_s} s, unit: {unit}, port: {port}")
        if with_raw:
            print("RAW data logging: enabled (*Z).")
        print("Stop with Ctrl+C (logger will finish current cycle before stopping).")

        # ── NOW do time sync, just before measurements ──
        print("Synchronizing time.")
        while get_sec_fractions(4) != 0:
            pass

        tp0 = perf_counter()  # reference for drift-free scheduling

        try:
            while True:
                try:
                    disable_halt = True  # protect the cycle from immediate stop

                    # ---- Actual measurement times (like BME-logger) ----
                    tp_now = perf_counter()
                    t_now = datetime.now().astimezone()
                    ts_iso = t_now.isoformat()

                    row = dps_read_once(rt, tp_now, ts_iso)
                    data_log.write(row)

                    print(", ".join(row))

                    count += 1
                except Exception as e:
                    err_log.write(
                        timestamp=int(time.time()),
                        measurement=count,
                        error_text=str(e),
                    )
                finally:
                    disable_halt = False  # safe point for SIGINT

                # ---- Wait for next interval (original formula) ----
                tp_end = perf_counter()
                wait_time = count * interval_s - (tp_end - tp0)
                if wait_time > 0:
                    sleep(wait_time)

        except Exception as e:
            err_log.write(
                timestamp=int(time.time()),
                measurement=count,
                error_text=f"fatal: {e}",
            )
            return 2

    finally:
        try:
            rt.adapter.close()
        except Exception:
            pass

    print(f"Stopped. Total rows written: {count}")
    return 0
# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def build_arg_parser() -> argparse.ArgumentParser:
    """
    Build command-line argument parser for the DPS logger stem.
    """
    p = argparse.ArgumentParser(
        description="DPS823A RS-485 + RPi thermal datalogger (stem variant)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="Measurement interval in seconds.",
    )
    p.add_argument(
        "--base-dir",
        type=str,
        default="data",
        help="Base directory for output files.",
    )
    p.add_argument(
        "--prefix",
        type=str,
        default="dps",
        help="Filename prefix for the data log.",
    )
    p.add_argument(
        "--csv-sep",
        type=str,
        default=DEFAULT_CSV_SEP,
        help="CSV separator for measurement data.",
    )
    p.add_argument(
        "--err-csv-sep",
        type=str,
        default=DEFAULT_ERR_CSV_SEP,
        help="CSV separator for the error log.",
    )
    p.add_argument(
        "--port",
        type=str,
        default=DEFAULT_PORT,
        help="Serial port for DPS823A (udev symlink, e.g. /dev/ttyLOG).",
    )
    p.add_argument(
        "--unit",
        type=str,
        default=DEFAULT_UNIT,
        choices=["bar", "Pa", "kPa", "mbar", "psi"],
        help="Pressure unit for both device and logger.",
    )
    p.add_argument(
        "--with-raw",
        action="store_true",
        help="Enable reading and logging of RAW (*Z) data into 'raw' column.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    """
    Entry point for command-line execution.

    Additionally:
    - If stdin is a TTY, temporarily disable echo of control characters
      (so that Ctrl+C does not show as '^C' in the terminal).
    """
    orig_tty_state: Optional[str] = None
    stdin_is_tty = sys.stdin.isatty()

    if stdin_is_tty:
        try:
            # Save current TTY settings and disable echoctl
            orig_tty_state = subprocess.check_output(
                ["stty", "-g"], text=True
            ).strip()
            subprocess.run(["stty", "-echoctl"], check=False)
        except Exception:
            # If anything goes wrong, just continue without modifying TTY
            orig_tty_state = None

    exit_code = 0
    try:
        args = build_arg_parser().parse_args(argv)
        exit_code = run_logger(
            base_dir=args.base_dir,
            file_prefix=args.prefix,
            csv_sep=args.csv_sep,
            err_csv_sep=args.err_csv_sep,
            interval_s=float(args.interval),
            port=args.port,
            unit=args.unit,
            with_raw=bool(args.with_raw),
        )
    finally:
        # Restore original TTY settings if we modified them
        if stdin_is_tty and orig_tty_state:
            try:
                subprocess.run(["stty", orig_tty_state], check=False)
            except Exception:
                pass

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
