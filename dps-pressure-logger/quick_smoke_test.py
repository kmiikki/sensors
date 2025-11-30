#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import time

from dps8000_adapter import DPS8000Adapter, DPS8000AdapterConfig, DPS8000Error
from rpi_thermal import read_thermal_sample
from csv_writer import CSVRotateConfig, CSVRotatingWriter

HEADERS = ["ts_iso","t_perf","pressure","unit","source",
           "cpu_temp_c","arm_freq_hz","throttled_raw"]

def main():
    cfg_csv = CSVRotateConfig(
        prefix="smoke",
        dirpath=Path.cwd(),
        headers=HEADERS,
        flush_every=10,
    )

    adp = DPS8000Adapter(DPS8000AdapterConfig(
        port="/dev/ttyLOG",
        device_unit="bar",
        target_unit="bar",
    ))

    with adp.opened(), CSVRotatingWriter(cfg_csv) as w:
        print("IDENT:", adp.identify())
        interval = 1.0
        next_t = time.perf_counter()
        for _ in range(30):  # 30 s test
            now = time.perf_counter()
            try:
                p = adp.read_sample()
            except DPS8000Error as e:
                p = {
                    "ts_iso": "",
                    "t_perf": now,
                    "pressure": float("nan"),
                    "unit": "bar",
                    "source": f"DPS8000_ERR:{e}",
                }
            th = read_thermal_sample()
            row = {
                "ts_iso": p.get("ts_iso") or th["ts_iso"],
                "t_perf": p.get("t_perf"),
                "pressure": p.get("pressure"),
                "unit": p.get("unit", "bar"),
                "source": p.get("source", "DPS8000"),
                "cpu_temp_c": th["cpu_temp_c"],
                "arm_freq_hz": th["arm_freq_hz"],
                "throttled_raw": th["throttled_raw"],
            }
            w.write(row)
            next_t += interval
            sleep = next_t - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t += int((-sleep)//interval + 1) * interval

if __name__ == "__main__":
    main()
