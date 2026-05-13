from __future__ import annotations

from typing import Tuple

from dpslogger.protocol import DPSConfig
from dpslogger.transport import SerialTransportConfig


def _default_port(port: str | None, default: str) -> str:
    return port or default


def real_sensor(port: str | None = None) -> Tuple[SerialTransportConfig, DPSConfig]:
    """Profile for a real DPS sensor connected to the main logger port."""
    transport = SerialTransportConfig(
        port=_default_port(port, "/dev/ttyLOG"),
        baud=9600,
        timeout_s=1.0,
        write_sleep_s=0.2,
        eol="crlf",
        reset_input_before_cmd=False,
    )
    protocol = DPSConfig(
        address=None,
        read_cmd="R",
        unit="bar",
        direct_mode=False,
        autosend_off=False,
        strict_init=False,
    )
    return transport, protocol


def simulator(port: str | None = None) -> Tuple[SerialTransportConfig, DPSConfig]:
    """Profile for the DPS simulator."""
    transport = SerialTransportConfig(
        port=_default_port(port, "/dev/ttySIM"),
        baud=9600,
        timeout_s=0.5,
        write_sleep_s=0.05,
        eol="cr",
        reset_input_before_cmd=True,
    )
    protocol = DPSConfig(
        address=None,
        read_cmd="*G",
        unit="bar",
        direct_mode=True,
        autosend_off=True,
        strict_init=True,
    )
    return transport, protocol


def bus_sensor(port: str | None, address: int) -> Tuple[SerialTransportConfig, DPSConfig]:
    """Profile for one addressed device on a shared RS-485 bus."""
    transport = SerialTransportConfig(
        port=_default_port(port, "/dev/ttyLOG"),
        baud=9600,
        timeout_s=1.0,
        write_sleep_s=0.2,
        eol="crlf",
        reset_input_before_cmd=False,
    )
    protocol = DPSConfig(
        address=address,
        read_cmd="R",
        unit="bar",
        direct_mode=False,
        autosend_off=False,
        strict_init=False,
    )
    return transport, protocol


def get_profile(profile: str, port: str | None = None) -> Tuple[SerialTransportConfig, DPSConfig]:
    """Return transport + protocol configs for a named profile."""
    if profile == "real":
        return real_sensor(port)
    if profile == "sim":
        return simulator(port)
    raise ValueError(f"Unknown profile: {profile}")
