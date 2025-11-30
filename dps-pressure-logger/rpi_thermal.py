#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import re
import time
import datetime as dt
from typing import Dict, Any, Tuple, Optional


def _run_cmd(args: list[str], timeout: float = 0.5) -> Optional[str]:
    try:
        out = subprocess.check_output(args, timeout=timeout).decode()
        return out.strip()
    except Exception:
        return None


def _iso_now_local() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def read_cpu_temp_c() -> float:
    """Palauttaa CPU-lämpötilan °C. Käyttää vcgencmd:iä, fallback sysfs:ään."""
    s = _run_cmd(["vcgencmd", "measure_temp"])
    if s:
        m = re.search(r"([\d.]+)", s)
        if m:
            return float(m.group(1))
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            raw = f.read().strip()
        v = float(raw)
        return v / 1000.0 if v > 200 else v
    except Exception:
        return float("nan")


def read_throttled_bits() -> Tuple[int, Dict[str, bool]]:
    """Palauttaa (raw_int, flags) throttlaus- ja undervolt-biteistä."""
    s = _run_cmd(["vcgencmd", "get_throttled"]) or ""
    m = re.search(r"0x([0-9A-Fa-f]+)", s)
    raw = int(m.group(1), 16) if m else 0

    def bit(n: int) -> bool: return bool(raw & (1 << n))

    flags = {
        "under_voltage":          bit(0),
        "arm_freq_capped":        bit(1),
        "currently_throttled":    bit(2),
        "soft_temp_limit_active": bit(3),
        "under_voltage_occurred":       bit(16),
        "arm_freq_capped_occurred":     bit(17),
        "throttled_occurred":           bit(18),
        "soft_temp_limit_occurred":     bit(19),
    }
    return raw, flags


def read_arm_freq_hz() -> float:
    s = _run_cmd(["vcgencmd", "measure_clock", "arm"])
    if s:
        m = re.search(r"=(\d+)", s)
        if m:
            return float(m.group(1))
    return float("nan")


def read_core_volts_v() -> float:
    s = _run_cmd(["vcgencmd", "measure_volts", "core"])
    if s:
        m = re.search(r"([\d.]+)", s)
        if m:
            return float(m.group(1))
    return float("nan")


def read_thermal_sample() -> Dict[str, Any]:
    """Palauttaa valmiin loggeri-näytteen RPI_THERMAL-lähteestä."""
    t_perf = time.perf_counter()
    temp_c = read_cpu_temp_c()
    freq = read_arm_freq_hz()
    volts = read_core_volts_v()
    raw, flags = read_throttled_bits()
    return {
        "ts_iso": _iso_now_local(),
        "t_perf": t_perf,
        "cpu_temp_c": temp_c,
        "arm_freq_hz": freq,
        "core_volts_v": volts,
        "throttled_raw": raw,
        "throttled": flags,
        "source": "RPI_THERMAL",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(read_thermal_sample(), ensure_ascii=False, indent=2))
