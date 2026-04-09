from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Literal, Optional, TypedDict, TypeAlias

from dpslogger.protocol import DPS8000, DPSConfig, DPSProtocolError, Unit
from dpslogger.transport import SerialTransport, SerialTransportConfig


@dataclass
class DPSAdapterConfig:
    """Adapter configuration for sample-oriented reading."""

    target_unit: Unit = "bar"
    include_raw: bool = False
    source_name: str = "DPS8000"


class PressureSample(TypedDict, total=False):
    """Normalized measurement sample returned by :class:`DPSAdapter`."""

    ts_iso: str
    t_cmd: float
    t_rx: float
    latency_s: float
    addr: int
    pressure: float
    unit: str
    source: str
    status: str
    raw: str


_BAR_TO: dict[Unit, float] = {
    "bar": 1.0,
    "Pa": 1e5,
    "kPa": 1e2,
    "mbar": 1e3,
    "psi": 14.503773773,
}
_TO_BAR: dict[Unit, float] = {u: 1.0 / k for u, k in _BAR_TO.items()}


def _iso_from_epoch(epoch_s: float) -> str:
    return dt.datetime.fromtimestamp(epoch_s, dt.timezone.utc).astimezone().isoformat()


def _convert_pressure(value: float, from_unit: Unit, to_unit: Unit) -> float:
    if from_unit == to_unit:
        return value
    bar_val = value * _TO_BAR[from_unit]
    return bar_val * _BAR_TO[to_unit]


class DPSAdapter:
    """Sample-oriented adapter on top of the DPS protocol client."""

    def __init__(
        self,
        transport_cfg: SerialTransportConfig,
        dps_cfg: DPSConfig,
        adapter_cfg: DPSAdapterConfig | None = None,
    ):
        self.transport = SerialTransport(transport_cfg)
        self.device = DPS8000(self.transport, dps_cfg)
        self.cfg = adapter_cfg or DPSAdapterConfig()

    def open(self) -> None:
        self.device.open()

    def close(self) -> None:
        self.device.close()

    def opened(self):
        class _Ctx:
            def __init__(self, outer: "DPSAdapter"):
                self._outer = outer

            def __enter__(self) -> "DPSAdapter":
                self._outer.open()
                return self._outer

            def __exit__(self, exc_type, exc, tb) -> None:
                self._outer.close()

        return _Ctx(self)

    def set_address(self, addr: Optional[int]) -> None:
        self.device.set_address(addr)

    def identify(self) -> str:
        return self.device.identify()

    def read_sample(self) -> PressureSample:
        """Read one sample.

        Measurement time is defined as command issue time (``t_cmd``), not reply
        arrival time. ``t_rx`` and ``latency_s`` are included for diagnostics.
        """
        addr = self.device.cfg.address or 0
        t_cmd_perf = time.perf_counter()
        t_cmd_epoch = time.time()
        value, unit = self.device.read_pressure_and_unit()
        t_rx_perf = time.perf_counter()

        target_unit = self.cfg.target_unit
        converted = _convert_pressure(value, unit, target_unit)
        sample: PressureSample = {
            "ts_iso": _iso_from_epoch(t_cmd_epoch),
            "t_cmd": t_cmd_perf,
            "t_rx": t_rx_perf,
            "latency_s": t_rx_perf - t_cmd_perf,
            "addr": addr,
            "pressure": converted,
            "unit": target_unit,
            "source": self.cfg.source_name,
            "status": "OK",
        }
        return sample

    def read_sample_safe(self) -> PressureSample:
        """Read one sample, returning a status-marked row even on failure."""
        addr = self.device.cfg.address or 0
        t_cmd_perf = time.perf_counter()
        t_cmd_epoch = time.time()
        try:
            value, unit = self.device.read_pressure_and_unit()
            t_rx_perf = time.perf_counter()
            converted = _convert_pressure(value, unit, self.cfg.target_unit)
            return {
                "ts_iso": _iso_from_epoch(t_cmd_epoch),
                "t_cmd": t_cmd_perf,
                "t_rx": t_rx_perf,
                "latency_s": t_rx_perf - t_cmd_perf,
                "addr": addr,
                "pressure": converted,
                "unit": self.cfg.target_unit,
                "source": self.cfg.source_name,
                "status": "OK",
            }
        except Exception as exc:
            t_rx_perf = time.perf_counter()
            return {
                "ts_iso": _iso_from_epoch(t_cmd_epoch),
                "t_cmd": t_cmd_perf,
                "t_rx": t_rx_perf,
                "latency_s": t_rx_perf - t_cmd_perf,
                "addr": addr,
                "pressure": float("nan"),
                "unit": self.cfg.target_unit,
                "source": self.cfg.source_name,
                "status": f"ERR:{exc}",
            }

    def read_sample_with_raw(self) -> PressureSample:
        """Read one sample and include raw device data when possible."""
        sample = self.read_sample_safe() if self.cfg.include_raw else self.read_sample()
        try:
            sample["raw"] = self.device.read_raw()
        except DPSProtocolError as exc:
            sample["raw"] = f"ERR:{exc}"
        return sample
