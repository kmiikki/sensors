#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Apr 20 12:12:24 2025

@author: Kim Miikki


thp_calibrate.py
----------------
Post‑process an existing THP data log (CSV) created by *bme280logger‑v2.py* or
similar.  The utility

1. **Loads** the CSV into a *pandas* `DataFrame`.
2. **Applies** linear calibrations ( *y = slope·x + const* ) for the sensor(s)
   you specify with the `‑cal zone,num1[,num2]` option.
3. **Appends** calibrated columns following the column‑name conventions used by
   *bme280logger‑v2.py* (e.g. `Tcal1 (°C)`, `RHcal1% (%)`, `Pcal1 (hPa)`).
4. **Clamps** calibrated relative‑humidity values to the valid range 0 – 100 %.
5. **Writes** the augmented data back to **UTF‑8** CSV (default: `thp-cal.csv`).
6. **Generates** a concise **`thp-cal.log`** summarising which calibrations were
   applied and their parameters (slope, constant, `cal_id`).

Example usage
~~~~~~~~~~~~~
```bash
$ ./thp_calibrate.py                                  # read ./thp.csv → ./thp-cal.csv + log
$ ./thp_calibrate.py -i data/thp_20250215.csv         # custom input path
$ ./thp_calibrate.py -i thp.csv -o results/out.csv    # custom output
$ ./thp_calibrate.py -cal A,1,2                       # calibrate sensors A1 and A2
```
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from thpcaldb import Calibration, parse_zone_numbers

# ---------------------------------------------------------------------------
# Canonical column names used by the live logger
# ---------------------------------------------------------------------------
RAW_HDR = {
    "T": "t{idx} (°C)",
    "RH": "RH{idx}% (%)",
    "P": "p{idx} (hPa)",
}
CAL_HDR = {
    "T": "Tcal{idx} (°C)",
    "RH": "RHcal{idx}% (%)",
    "P": "Pcal{idx} (hPa)",
}
# Map logger‑style label -> our shorthand key
MEAS_MAP = {
    "Temperature": "T",
    "Relative Humidity": "RH",
    "Pressure": "P",
}

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _find_raw_column(df: pd.DataFrame, canonical: str) -> str | None:
    """Return the name of the *actual* DataFrame column that matches the
    *canonical* header pattern, ignoring case and allowing extra/missing
    spaces, underscores, or percent signs.
    """
    if canonical in df.columns:
        return canonical  # exact match

    # Build tolerant regex: replace every non‑alphanumeric char with "[\s_%]*"
    regex_parts: list[str] = []
    for ch in canonical:
        if ch.isalnum():
            regex_parts.append(re.escape(ch))
        else:
            regex_parts.append(r"[\s_%]*")
    regex = re.compile("".join(regex_parts), re.IGNORECASE)

    for col in df.columns:
        if regex.fullmatch(col):
            return col

    # Fallback: compare just the alphanumeric core
    core = re.sub(r"[^A-Za-z0-9]", "", canonical).lower()
    for col in df.columns:
        if core and core in re.sub(r"[^A-Za-z0-9]", "", col).lower():
            return col
    return None


def _clamp_rh(series: pd.Series) -> pd.Series:
    """Clamp RH values to 0–100 %."""
    return series.clip(lower=0, upper=100)


# ---------------------------------------------------------------------------
# Calibration application
# ---------------------------------------------------------------------------

def apply_calibrations(df: pd.DataFrame, sensor_cals: list[Calibration | None]):
    """Append calibrated columns to *df* in‑place using *sensor_cals* list."""
    warnings: list[str] = []
    added: list[str] = []

    for idx, cal in enumerate(sensor_cals, start=1):
        if cal is None:
            continue

        label = cal._cal_data["label"]  # type: ignore[attr-defined]
        key = MEAS_MAP.get(label)
        if key is None:
            warnings.append(
                f"Warning: unknown calibration label '{label}' for sensor {idx}; skipping."
            )
            continue

        raw_hdr_template = RAW_HDR[key]
        cal_hdr_template = CAL_HDR[key]

        raw_hdr = _find_raw_column(df, raw_hdr_template.format(idx=idx))
        if raw_hdr is None:
            warnings.append(
                f"Warning: '{raw_hdr_template.format(idx=idx)}' not found – skipping calibration for sensor {idx} ({label})."
            )
            continue

        slope = cal._cal_data["slope"]  # type: ignore[attr-defined]
        const = cal._cal_data["const"]  # type: ignore[attr-defined]

        cal_hdr = cal_hdr_template.format(idx=idx)
        df[cal_hdr] = df[raw_hdr] * slope + const
        if key == "RH":
            df[cal_hdr] = _clamp_rh(df[cal_hdr])
        added.append(cal_hdr)

    return warnings, added


# ---------------------------------------------------------------------------
# Log‑file writer (compact version of write_calibration_log)
# ---------------------------------------------------------------------------

def write_calibration_log(path: Path, src_csv: Path, sensor_cals, zone, num1, num2):
    now = datetime.now()
    with path.open("w", encoding="utf-8") as f:
        f.write("=== THP CSV Calibration Report ===\n\n")
        f.write(f"Source CSV : {src_csv.name}\n")
        f.write(f"Generated  : {now:%Y-%m-%d %H:%M:%S}\n\n")

        if any(sensor_cals):
            f.write("--- Calibration Data ---\n")
            for i, cal in enumerate(sensor_cals, start=1):
                if cal is None:
                    continue
                sens_num = num1 if i == 1 else num2
                label = cal._cal_data["label"]  # type: ignore[attr-defined]
                slope = cal._cal_data["slope"]  # type: ignore[attr-defined]
                const = cal._cal_data["const"]  # type: ignore[attr-defined]
                cal_id = cal._cal_data["cal_id"]  # type: ignore[attr-defined]
                f.write(f"Sensor {i} (Zone {zone}, Number {sens_num}) – {label}:\n")
                f.write(f"   slope    = {slope:.6g}\n")
                f.write(f"   constant = {const:.6g}\n")
                f.write(f"   cal_id   = {cal_id}\n\n")
        else:
            f.write("No calibration data were applied.\n\n")

        f.write("--- Summary ---\n")
        f.write(f"Output CSV : {path.with_suffix('.csv').name}\n")
        f.write("RH values are clamped to 0‑100 %.\n")
        f.write("=== End of Report ===\n")


# ---------------------------------------------------------------------------
# Main program
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="thp.csv", help="Input CSV file (default: thp.csv)")
    ap.add_argument("-o", "--output", default="thp-cal.csv", help="Output CSV file (default: thp-cal.csv)")
    ap.add_argument("-cal", type=str, help="Calibration spec zone,num1[,num2] e.g. -cal C11,12")
    args = ap.parse_args()

    src = Path(args.input).expanduser().resolve()
    dst = Path(args.output).expanduser().resolve()

    if not src.exists():
        print(f"Error: input file '{src}' not found.", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(src, encoding="utf-8")

    sensor_cals = [None, None]
    zone = num1 = num2 = None
    if args.cal:
        zone, num1, num2 = parse_zone_numbers(args.cal)
        if zone:
            db_file = Path(__file__).with_name("calibration.db")
            if num1:
                sensor_cals[0] = Calibration(str(db_file), zone, num1)
                if sensor_cals[0] is not None:
                    print(f"Calibration loaded for sensor 1 ({zone}{num1}) – {sensor_cals[0]._cal_data['label']}")
            if num2:
                sensor_cals[1] = Calibration(str(db_file), zone, num2)
                if sensor_cals[1] is not None:
                    print(f"Calibration loaded for sensor 2 ({zone}{num2}) – {sensor_cals[1]._cal_data['label']}")

    warnings, added = apply_calibrations(df, sensor_cals)
    for w in warnings:
        print(w)

    df.to_csv(dst, index=False, encoding="utf-8")
    print(f"Calibrated data written to {dst.name}")

    log_path = dst.with_suffix('.log')
    write_calibration_log(log_path, src, sensor_cals, zone, num1, num2)
    print(f"Calibration report written to {log_path.name}")


if __name__ == "__main__":
    main()