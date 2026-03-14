from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional, TypeAlias

from dpslogger.transport import SerialTransport, SerialTransportError, TransactionResult

Unit: TypeAlias = Literal["bar", "Pa", "kPa", "mbar", "psi"]
ReadCommand: TypeAlias = Literal["R", "*G"]


@dataclass
class DPSConfig:
    """Protocol-level DPS client configuration."""

    address: Optional[int] = None
    read_cmd: ReadCommand = "R"
    unit: Unit = "bar"
    direct_mode: bool = False
    autosend_off: bool = False
    strict_init: bool = False


class DPSProtocolError(Exception):
    """Generic DPS protocol or parsing error."""


_ADDR_ECHO_RE = re.compile(r"^(?P<addr>\d{2}):(?P<payload>.*)$")


class DPS8000:
    """DPS8000 client on top of :class:`~dpslogger.transport.SerialTransport`."""

    def __init__(self, transport: SerialTransport, cfg: DPSConfig):
        self.transport = transport
        self.cfg = cfg

    def open(self) -> None:
        self.transport.open()
        self._initialize()

    def close(self) -> None:
        self.transport.close()

    def opened(self):
        class _Ctx:
            def __init__(self, outer: "DPS8000"):
                self._outer = outer

            def __enter__(self) -> "DPS8000":
                self._outer.open()
                return self._outer

            def __exit__(self, exc_type, exc, tb) -> None:
                self._outer.close()

        return _Ctx(self)

    def set_address(self, addr: Optional[int]) -> None:
        if addr is not None and addr < 0:
            raise ValueError("Address must be >= 0 or None")
        self.cfg.address = addr

    def _format_cmd(self, cmd: str) -> str:
        if ":" in cmd:
            return cmd
        if self.cfg.address is None or self.cfg.address == 0:
            return cmd
        return f"{self.cfg.address}:{cmd}"

    def send_command(self, cmd: str) -> TransactionResult:
        final_cmd = self._format_cmd(cmd)
        try:
            return self.transport.transact(final_cmd)
        except SerialTransportError as exc:
            raise DPSProtocolError(str(exc)) from exc

    def _require_reply(self, result: TransactionResult, cmd: str) -> TransactionResult:
        if not result.ok or not result.reply_bytes:
            raise DPSProtocolError(f"Timeout waiting response for {cmd!r}")
        return result

    def _split_address_echo(self, text: str) -> tuple[Optional[int], str]:
        """Split optional address echo prefix from reply text."""
        stripped = text.strip()
        if not stripped:
            raise DPSProtocolError("Empty reply")

        match = _ADDR_ECHO_RE.match(stripped)
        if not match:
            return None, stripped

        echoed_addr = int(match.group("addr"))
        payload = match.group("payload").strip()
        return echoed_addr, payload

    def _normalize_reply(self, text: str, cmd: str) -> str:
        """Normalize reply by stripping optional address echo."""
        echoed_addr, payload = self._split_address_echo(text)

        if (
            echoed_addr is not None
            and self.cfg.address is not None
            and self.cfg.address > 0
            and echoed_addr != self.cfg.address
        ):
            raise DPSProtocolError(
                f"Reply address mismatch for {cmd!r}: "
                f"expected {self.cfg.address}, got {echoed_addr}"
            )

        return payload

    def _initialize(self) -> None:
        steps: list[str] = []
        if self.cfg.direct_mode:
            steps.append("N,0")
        elif self.cfg.address is not None and self.cfg.address > 0:
            steps.append(f"N,{self.cfg.address}")

        if self.cfg.unit:
            steps.append(f"U,{self.cfg.unit}")
        if self.cfg.autosend_off:
            steps.append("A,0")

        for cmd in steps:
            if self.cfg.strict_init:
                result = self.send_command(cmd)
                self._require_reply(result, cmd)
            else:
                try:
                    self.send_command(cmd)
                except DPSProtocolError:
                    pass

    def identify(self) -> str:
        result = self.send_command("I")
        self._require_reply(result, "I")
        return self._normalize_reply(result.reply_text, "I")

    def set_unit(self, unit: Unit) -> str:
        cmd = f"U,{unit}"
        result = self.send_command(cmd)
        self._require_reply(result, cmd)
        self.cfg.unit = unit
        return self._normalize_reply(result.reply_text, cmd)

    def set_autosend(self, on: bool) -> str:
        cmd = f"A,{1 if on else 0}"
        result = self.send_command(cmd)
        self._require_reply(result, cmd)
        return self._normalize_reply(result.reply_text, cmd)

    def _parse_float_reply(self, text: str, cmd: str) -> float:
        try:
            return float(text.strip())
        except Exception as exc:
            raise DPSProtocolError(
                f"Failed to parse numeric reply for {cmd!r}: {text!r}"
            ) from exc

    def _parse_value_unit_reply(self, text: str, cmd: str) -> tuple[float, str]:
        text = text.strip()
        if not text:
            raise DPSProtocolError(f"Empty value+unit reply for {cmd!r}")

        if "," in text:
            parts = [p.strip() for p in text.split(",", 1)]
        else:
            parts = text.split(None, 1)

        if len(parts) != 2:
            raise DPSProtocolError(
                f"Failed to parse value+unit reply for {cmd!r}: {text!r}"
            )

        try:
            value = float(parts[0])
        except Exception as exc:
            raise DPSProtocolError(
                f"Failed to parse numeric part for {cmd!r}: {text!r}"
            ) from exc

        unit = parts[1].strip()
        if not unit:
            raise DPSProtocolError(f"Missing unit in reply for {cmd!r}: {text!r}")

        return value, unit

    def read_pressure_r(self) -> float:
        result = self.send_command("R")
        self._require_reply(result, "R")
        reply = self._normalize_reply(result.reply_text, "R")
        return self._parse_float_reply(reply, "R")

    def read_pressure_with_unit(self) -> tuple[float, str]:
        result = self.send_command("*G")
        self._require_reply(result, "*G")
        reply = self._normalize_reply(result.reply_text, "*G")
        return self._parse_value_unit_reply(reply, "*G")

    def read_pressure(self) -> float:
        if self.cfg.read_cmd == "R":
            return self.read_pressure_r()
        value, _unit = self.read_pressure_with_unit()
        return value

    def read_pressure_and_unit(self) -> tuple[float, str]:
        if self.cfg.read_cmd == "R":
            return self.read_pressure_r(), self.cfg.unit
        return self.read_pressure_with_unit()

    def read_raw(self) -> str:
        result = self.send_command("*Z")
        self._require_reply(result, "*Z")
        return self._normalize_reply(result.reply_text, "*Z")
