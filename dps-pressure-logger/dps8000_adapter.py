#!/usr/bin/env python3
from __future__ import annotations

import time
import datetime as dt
from dataclasses import dataclass
from typing import Dict, Optional, Literal, Any

from dps8000 import DPS8000, DPS8000Config, DPS8000Error

Unit = Literal["bar", "Pa", "kPa", "mbar", "psi"]


@dataclass
class DPS8000AdapterConfig:
    """
    Adapter-tason asetukset. `target_unit` määrittää, missä yksikössä arvo
    palautetaan (konversio tehdään automaattisesti, vaikka anturi olisi
    eri yksikössä).
    """
    port: str = "/dev/ttyLOG"   # loggeri käyttää udev-symlinkkiä /dev/ttyLOG
    baud: int = 9600
    device_unit: Unit = "bar"   # mitä komennamme anturille (U,<unit>)
    target_unit: Unit = "bar"   # missä yksikössä sinä haluat logittaa
    address: Optional[int] = None
    direct_mode: bool = True
    autosend_off: bool = True
    retries: int = 2
    timeout_s: float = 0.5


def _iso_now_local() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


_BAR_TO: Dict[Unit, float] = {
    "bar": 1.0,
    "Pa": 1e5,
    "kPa": 1e2,
    "mbar": 1e3,
    "psi": 14.503773773,
}
_TO_BAR: Dict[Unit, float] = {u: 1.0 / k for u, k in _BAR_TO.items()}


def _convert(value: float, from_unit: Unit, to_unit: Unit) -> float:
    if from_unit == to_unit:
        return value
    bar_val = value * _TO_BAR[from_unit]
    return bar_val * _BAR_TO[to_unit]


class DPS8000Adapter:
    """
    Kevyt adapteri perfcounter-pohjaiseen loggeriin.

    `read_sample()` palauttaa dictin:
      {
        "ts_iso": str,
        "t_perf": float,
        "pressure": float,  # target_unit
        "unit": str,
        "source": "DPS8000",
      }
    """

    def __init__(self, cfg: DPS8000AdapterConfig):
        self.cfg = cfg
        self._client = DPS8000(
            DPS8000Config(
                port=cfg.port,
                baud=cfg.baud,
                unit=cfg.device_unit,
                direct_mode=cfg.direct_mode,
                autosend_off=cfg.autosend_off,
                address=cfg.address,
                retries=cfg.retries,
                timeout_s=cfg.timeout_s,
            )
        )

    def open(self) -> None:
        self._client.open()

    def close(self) -> None:
        self._client.close()

    def opened(self):
        class _Ctx:
            def __init__(self, outer: "DPS8000Adapter"): self.o = outer
            def __enter__(self): self.o.open(); return self.o
            def __exit__(self, exc_type, exc, tb): self.o.close()
        return _Ctx(self)

    def identify(self) -> str:
        return self._client.identify()

    def read_sample(self) -> Dict[str, Any]:
        t_perf = time.perf_counter()
        val_device_unit = self._client.read_pressure()
        val_target = _convert(val_device_unit, self.cfg.device_unit, self.cfg.target_unit)
        return {
            "ts_iso": _iso_now_local(),
            "t_perf": t_perf,
            "pressure": float(val_target),
            "unit": self.cfg.target_unit,
            "source": "DPS8000",
        }

    def read_sample_with_raw(self) -> Dict[str, Any]:
        sample = self.read_sample()
        try:
            raw = self._client.read_raw()
        except DPS8000Error as e:
            raw = f"RAW_ERR:{e}"
        sample["raw"] = raw
        return sample
