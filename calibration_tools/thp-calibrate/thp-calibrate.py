#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thp-calibrate.py – apply calibration to THP CSV
──────────────────────────────────────────────────────────────────────────────
*2025-06-19  –  **patch 3***

**What’s new**
--------------
* JSON integration now mirrors the original behaviour: for each **sensor** we
  take calibrations *either* from **thpcal.json** *or* from the SQLite
  database, **never a mix**.
* Fallback to the DB is triggered **only when the sensor has no JSON entries
  at all** (no special‑case for “Temperature”).  The database can therefore
  provide *Temperature, Humidity, or Pressure* – just like the original
  version.
* Docstring & log output updated accordingly.
"""
from __future__ import annotations

###############################################################################
# Imports
###############################################################################
import argparse, json, os, re, sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from thpcaldb import Calibration, parse_zone_numbers

###############################################################################
# Canonical headers used by the logger
###############################################################################
RAW_HDR = {
    "T":  "t{idx} (°C)",
    "RH": "RH{idx}% (%)",
    "P":  "p{idx} (hPa)",
}
CAL_HDR = {
    "T":  "Tcal{idx} (°C)",
    "RH": "RHcal{idx}% (%)",
    "P":  "Pcal{idx} (hPa)",
}
MEAS_MAP = {
    "Temperature":        "T",
    "Relative Humidity":  "RH",
    "Humidity":           "RH",
    "Pressure":           "P",
}
LABEL_FROM_CODE = {v: k for k, v in MEAS_MAP.items()}

###############################################################################
# JSON helpers
###############################################################################

def find_thpcal_json() -> Tuple[Path, bool]:
    fname = "thpcal.json"
    for d in (Path.cwd(), Path.cwd().parent, Path("/opt/tools")):
        p = d / fname
        if p.is_file():
            return p, True
    return Path.cwd() / fname, False


def read_thpcal_json(path: Path) -> Dict[int, Dict[str, Dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return {int(k): v for k, v in raw.items()}


def collect_json_cals(js: Dict[int, Dict[str, Dict[str, Any]]],
                       sensor_code: str,
                       json_path: Path) -> Dict[str, "JsonCal"]:
    """Return mapping {code → JsonCal} for *sensor_code*. Empty if absent."""
    for sens_block in js.values():
        entry = sens_block.get(sensor_code)
        if not entry:
            continue
        out: Dict[str, JsonCal] = {}
        for key in ("T", "H", "RH", "P"):
            if key not in entry:
                continue
            data = entry[key]
            meas_code = "RH" if key in ("H", "RH") else key
            data.setdefault("label", LABEL_FROM_CODE[meas_code])
            out[meas_code] = JsonCal(data, sensor_code, json_path)
        return out
    return {}

###############################################################################
# Wrapper class – makes JSON look like thpcaldb.Calibration
###############################################################################
class JsonCal:
    def __init__(self, entry: Dict[str, Any], sensor_code: str, json_path: Path):
        self._cal_data = {
            "label": entry.get("label", "Temperature"),
            "slope": entry["slope"],
            "const": entry.get("constant", entry.get("const", 0.0)),
            "cal_id": f"json:{sensor_code}",
        }
        self._json_path = json_path
        self._from_json = True  # flag for logging

###############################################################################
# Column matching & RH clamp
###############################################################################

def _find_raw_column(df: pd.DataFrame, canonical: str) -> str | None:
    if canonical in df.columns:
        return canonical
    rx_parts = [re.escape(c) if c.isalnum() else r"[\s_%]*" for c in canonical]
    rx = re.compile("".join(rx_parts), re.IGNORECASE)
    for col in df.columns:
        if rx.fullmatch(col):
            return col
    core = re.sub(r"[^A-Za-z0-9]", "", canonical).lower()
    for col in df.columns:
        if core and core in re.sub(r"[^A-Za-z0-9]", "", col).lower():
            return col
    return None

def _clamp_rh(series: pd.Series) -> pd.Series:
    return series.clip(lower=0, upper=100)

###############################################################################
# Calibration application – dict per sensor {code → Calibration}
###############################################################################

def apply_calibrations(df: pd.DataFrame,
                       sensor_cals: List[Dict[str, Calibration | JsonCal]]):
    warnings: List[str] = []
    for idx, cal_map in enumerate(sensor_cals, start=1):
        for code, cal in cal_map.items():
            label = LABEL_FROM_CODE[code]
            raw_hdr = _find_raw_column(df, RAW_HDR[code].format(idx=idx))
            if raw_hdr is None:
                warnings.append(f"Warning: missing column '{RAW_HDR[code].format(idx=idx)}' for sensor {idx}")
                continue
            cal_hdr = CAL_HDR[code].format(idx=idx)
            slope, const = cal._cal_data["slope"], cal._cal_data["const"]
            df[cal_hdr] = df[raw_hdr] * slope + const
            if code == "RH":
                df[cal_hdr] = _clamp_rh(df[cal_hdr])
    return warnings

###############################################################################
# Log writer
###############################################################################

def write_calibration_log(path: Path, src_csv: Path,
                          sensor_cals: List[Dict[str, Calibration | JsonCal]],
                          zone: str | None, num1: int | None, num2: int | None,
                          json_path: Path | None):
    now = datetime.now()
    with path.open("w", encoding="utf-8") as f:
        f.write("=== THP CSV Calibration Report ===\n\n")
        f.write(f"Source CSV : {src_csv.name}\n")
        f.write(f"Generated  : {now:%Y-%m-%d %H:%M:%S}\n\n")

        for i, cal_map in enumerate(sensor_cals, start=1):
            if not cal_map:
                continue
            sens_num = num1 if i == 1 else num2
            f.write(f"--- Sensor {i} (Zone {zone}, Number {sens_num}) ---\n")
            for code, cal in cal_map.items():
                label = LABEL_FROM_CODE[code]
                slope = cal._cal_data["slope"]
                const = cal._cal_data["const"]
                f.write(f"  {label}:\n")
                f.write(f"     slope    = {slope:.6g}\n")
                f.write(f"     constant = {const:.6g}\n")
                if getattr(cal, "_from_json", False) and json_path is not None:
                    f.write(f"     cal      = {json_path.parent}/thpcal.json\n")
                else:
                    f.write(f"     cal_id   = {cal._cal_data.get('cal_id','-')}\n")
            f.write("\n")

        f.write("RH values are clamped to 0-100 %.\n")
        f.write("=== End of Report ===\n")

###############################################################################
# Main entry
###############################################################################

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="thp.csv")
    ap.add_argument("-o", "--output", default="thp-cal.csv")
    ap.add_argument("-cal", help="Calibration spec zone,num1[,num2] e.g. -cal C11,12")
    args = ap.parse_args()

    src_csv = Path(args.input).expanduser().resolve()
    dst_csv = Path(args.output).expanduser().resolve()
    if not src_csv.is_file():
        print(f"Error: '{src_csv}' not found", file=sys.stderr); sys.exit(1)

    df = pd.read_csv(src_csv, encoding="utf-8")

    # Two‑sensor container, each value is {code → Calibration}
    sensor_cals: List[Dict[str, Calibration | JsonCal]] = [{}, {}]
    zone = num1 = num2 = None
    json_used: Path | None = None

    if args.cal:
        zone, num1, num2 = parse_zone_numbers(args.cal)
        # JSON first ---------------------------------------------------
        json_path, json_ok = find_thpcal_json()
        json_dict = read_thpcal_json(json_path) if json_ok else None
        if json_ok:
            json_used = json_path

        def json_for(sensor_idx: int, num: int | None):
            if json_dict is None or num is None:
                return {}
            return collect_json_cals(json_dict, f"{zone}{num}", json_path)

        sensor_cals[0].update(json_for(1, num1))
        sensor_cals[1].update(json_for(2, num2))

        # DB fallback only if sensor has *no* JSON entries -------------
        db_file = Path(__file__).with_name("calibration.db")
        def db_cal(num: int | None):
            if num is None:
                return None
            try:
                return Calibration(str(db_file), zone, num)
            except Exception as e:
                print("DB error:", e); return None

        if not sensor_cals[0]:
            cal_obj = db_cal(num1)
            if cal_obj:
                code = MEAS_MAP.get(cal_obj._cal_data["label"], None)  # type: ignore
                if code:
                    sensor_cals[0][code] = cal_obj
        if not sensor_cals[1]:
            cal_obj = db_cal(num2)
            if cal_obj:
                code = MEAS_MAP.get(cal_obj._cal_data["label"], None)
                if code:
                    sensor_cals[1][code] = cal_obj

    # ------------------------------------------------ apply + write outputs
    warnings = apply_calibrations(df, sensor_cals)
    for w in warnings:
        print(w)

    df.to_csv(dst_csv, index=False, encoding="utf-8")
    print(f"Calibrated data written to {dst_csv.name}")

    log_path = dst_csv.with_suffix(".log")
    write_calibration_log(
        log_path,
        src_csv,
        sensor_cals,
        zone,
        num1,
        num2,
        json_used
    )
    print(f"Calibration report written to {log_path.name}")


###############################################################################
if __name__ == "__main__":
    main()
