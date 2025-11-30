#!/usr/bin/env python3
"""
DPS8000 (RS-485, ASCII) minimal driver for Raspberry Pi / Linux.

- Works in 'Direct mode' (no address). For network mode, pass address=int.
- Default baud: 9600 8N1.
- Default port: /dev/ttyLOG (udev-symlink, loggerin adapteri).

Key commands (each terminated by CR):
  I          -> identity block
  N,0        -> direct mode (N,<addr> for network mode)
  U,<unit>   -> pressure unit (e.g. bar, Pa, psi)
  A,0/1      -> autosend off/on
  R          -> read pressure (value only)
  *G         -> read pressure with unit "value,unit"
  *Z         -> raw data (if needed)

Typical replies end with CR or CRLF. We accept either.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Literal
import time
import serial


class DPS8000Error(Exception):
    """Generic DPS8000 communication or parsing error."""


@dataclass
class DPS8000Config:
    port: str = "/dev/ttyLOG"       # udev-symlink loggeriportille
    baud: int = 9600
    timeout_s: float = 0.5          # serial read timeout
    write_sleep_s: float = 0.05     # short gap after TX before RX
    unit: Literal["bar", "Pa", "psi", "kPa", "mbar"] = "bar"
    direct_mode: bool = True        # N,0 on open
    autosend_off: bool = True       # A,0 on open
    address: Optional[int] = None   # for network mode (0..31)
    retries: int = 2                # txrx retries


class DPS8000:
    """
    Minimal DPS8000 RS-485 ASCII client.

    Usage:
        dps = DPS8000(DPS8000Config())
        with dps.opened():
            ident = dps.identify()
            p_bar = dps.read_pressure()
    """
    def __init__(self, cfg: DPS8000Config):
        self.cfg = cfg
        self._ser: Optional[serial.Serial] = None

    # ---------- context mgmt ----------
    def open(self) -> None:
        if self._ser and self._ser.is_open:
            return
        self._ser = serial.Serial(
            self.cfg.port,
            self.cfg.baud,
            timeout=self.cfg.timeout_s,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
            write_timeout=self.cfg.timeout_s,
        )
        # init line: direct/network, unit, autosend
        if self.cfg.direct_mode and self.cfg.address in (None, 0):
            self._safe_cmd("N,0")  # direct mode
        elif self.cfg.address is not None:
            self._safe_cmd(f"N,{int(self.cfg.address)}")

        if self.cfg.unit:
            self._safe_cmd(f"U,{self.cfg.unit}")

        if self.cfg.autosend_off:
            self._safe_cmd("A,0")

    def close(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def opened(self):
        class _Ctx:
            def __init__(self, outer: "DPS8000"): self.o = outer
            def __enter__(self): self.o.open(); return self.o
            def __exit__(self, exc_type, exc, tb): self.o.close()
        return _Ctx(self)

    # ---------- public ops ----------
    def identify(self) -> str:
        """Return identity/info string from command 'I'."""
        return self._safe_cmd("I")

    def set_unit(self, unit: str) -> None:
        """Set pressure unit (e.g. 'bar', 'Pa', 'psi', 'kPa', 'mbar')."""
        self._safe_cmd(f"U,{unit}")
        self.cfg.unit = unit

    def set_autosend(self, on: bool) -> None:
        """Enable/disable autosend mode (A,1 / A,0)."""
        self._safe_cmd(f"A,{1 if on else 0}")

    def set_direct_mode(self) -> None:
        """Switch to direct mode (address 0)."""
        self._safe_cmd("N,0")
        self.cfg.direct_mode = True
        self.cfg.address = 0

    def set_address(self, addr: int) -> None:
        """Switch to network mode with address `addr` (0..31)."""
        if not (0 <= addr <= 31):
            raise ValueError("Address must be 0..31")
        self._safe_cmd(f"N,{addr}")
        self.cfg.direct_mode = (addr == 0)
        self.cfg.address = addr

    def read_pressure(self) -> float:
        """
        Read pressure using '*G' (value + unit) and return as float in current unit.
        Raises DPS8000Error on timeout or parse failure.
        """
        resp = self._safe_cmd("*G")
        value, unit = self._parse_value_unit(resp)
        if unit and self.cfg.unit and unit.lower() != self.cfg.unit.lower():
            raise DPS8000Error(f"Unit mismatch: device='{unit}' vs cfg='{self.cfg.unit}'")
        return value

    def read_raw(self) -> str:
        """
        Read raw diagnostic (*Z). Returned as raw ASCII string (device-specific).
        """
        return self._safe_cmd("*Z")

    # ---------- low-level ----------
    def _prefix_addr(self, cmd: str) -> str:
        """Add network address prefix if needed: 'addr:cmd'."""
        if self.cfg.address and not self.cfg.direct_mode:
            return f"{self.cfg.address}:{cmd}"
        return cmd

    def _txrx_once(self, cmd: str) -> str:
        if not self._ser or not self._ser.is_open:
            raise DPS8000Error("Serial not open")
        ser = self._ser
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        wire = (self._prefix_addr(cmd) + "\r").encode("ascii", errors="strict")
        ser.write(wire)
        ser.flush()
        time.sleep(self.cfg.write_sleep_s)
        resp = ser.readline()
        if not resp:
            resp = ser.read_until(expected=b"\r")
        if not resp:
            raise DPS8000Error(f"Timeout waiting response for '{cmd}'")
        txt = resp.decode("ascii", errors="ignore").strip("\r\n ").strip()
        if not txt:
            raise DPS8000Error(f"Empty response for '{cmd}'")
        return txt

    def _safe_cmd(self, cmd: str) -> str:
        """Send command with limited retries and simple backoff."""
        last_exc: Optional[Exception] = None
        for attempt in range(self.cfg.retries + 1):
            try:
                return self._txrx_once(cmd)
            except Exception as e:
                last_exc = e
                time.sleep(0.05 * (attempt + 1))
        raise DPS8000Error(f"Command '{cmd}' failed: {last_exc}")

    @staticmethod
    def _parse_value_unit(text: str) -> Tuple[float, Optional[str]]:
        """
        Accepts '123.456,bar' or '123.456'. Returns (value, unit|None).
        """
        if "," in text:
            v, u = text.split(",", 1)
            return float(v.strip()), u.strip()
        return float(text.strip()), None
