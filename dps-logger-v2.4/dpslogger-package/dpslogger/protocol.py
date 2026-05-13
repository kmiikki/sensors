from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional, TypeAlias

from dpslogger.transport import SerialTransport, SerialTransportError, TransactionResult

# Allowed day-to-day units for this project.
# Manual table B-3 currently maps:
#   1=mbar, 2=bar, 3=hPa, 4=kPa, 5=MPa, 6=psi
# Hardware-verified unit mapping for the current DPS device:
#   0=mbar, 1=Pa, 2=kPa, 3=MPa, 4=hPa, 5=bar
# This mapping is based on direct device tests using U,<code> followed by *G.
# Note: *G replies use textual units and may differ in capitalization.
# For example the device returns "Bar", but internally we normalize it to "bar".
Unit: TypeAlias = Literal["mbar", "Pa", "kPa", "MPa", "hPa", "bar"]
ReadCommand: TypeAlias = Literal["R", "*G"]

UNIT_CODE_TO_NAME: dict[int, str] = {
    0: "mbar",
    1: "Pa",
    2: "kPa",
    3: "MPa",
    4: "hPa",
    5: "bar",
}

UNIT_NAME_TO_CODE: dict[str, int] = {
    name.lower(): code for code, name in UNIT_CODE_TO_NAME.items()
}

@dataclass
class DPSConfig:
    """Protocol-level DPS client configuration."""

    address: Optional[int] = None
    read_cmd: ReadCommand = "R"
    unit: Unit = "kPa"
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
        if addr is not None and not 0 <= addr <= 32:
            raise ValueError("Address must be in range 0..32 or None")
        self.cfg.address = addr

    def _format_cmd(self, cmd: str) -> str:
        """
        Format a DPS command.

        DPS commands must begin with a leading stop/start character.
        In normal use we send a leading space. If the caller already provided
        a leading space or backspace, do not add another one.

        This method only formats the command body. The underlying transport is
        expected to append the configured EOL, which for DPS should be CR.
        """
        if cmd.startswith((" ", "\b")):
            return cmd

        if ":" in cmd:
            return f" {cmd}"

        if self.cfg.address is None or self.cfg.address == 0:
            return f" {cmd}"

        return f" {self.cfg.address}:{cmd}"

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

    def _unit_name_to_code(self, unit: str) -> int:
        try:
            return UNIT_NAME_TO_CODE[unit.lower()]
        except KeyError as exc:
            allowed = ", ".join(UNIT_CODE_TO_NAME.values())
            raise DPSProtocolError(f"Unsupported unit {unit!r}. Allowed: {allowed}") from exc

    def _unit_code_to_name(self, code: int) -> Unit:
        try:
            return UNIT_CODE_TO_NAME[code]  # type: ignore[return-value]
        except KeyError as exc:
            raise DPSProtocolError(f"Unsupported unit code {code}") from exc

    def _send_silent_command(self, cmd: str) -> None:
        """
        Send a command that may legitimately return no reply.

        DPS write commands such as N,<addr>, U,<code>, and A,<interval> often
        complete without a reply string.
        """
        try:
            self.send_command(cmd)
        except DPSProtocolError:
            if self.cfg.strict_init:
                raise

    def _initialize(self) -> None:
        steps: list[str] = []

        if self.cfg.autosend_off:
            steps.append("A,9999")

        if self.cfg.address is not None and self.cfg.address > 0:
            steps.append(f"N,{self.cfg.address}")

        if self.cfg.unit:
            code = self._unit_name_to_code(self.cfg.unit)
            steps.append(f"U,{code}")

        for cmd in steps:
            self._send_silent_command(cmd)

    def identify(self) -> str:
        result = self.send_command("I")
        self._require_reply(result, "I")
        return self._normalize_reply(result.reply_text, "I")


    def query_address(self) -> int:
        result = self.send_command("N,?")
        self._require_reply(result, "N,?")

        reply = result.reply_text.strip()
        if not reply:
            raise DPSProtocolError("Empty address reply")

        # DPS error replies start with '!'
        if reply.startswith("!"):
            raise DPSProtocolError(f"DPS error reply for N,?: {reply!r}")

        # Addressed reply, e.g. "01:01"
        match = re.fullmatch(r"(?P<echo>\d{2}):(?P<addr>\d{2})", reply)
        if match:
            return int(match.group("addr"))

        # Direct reply, e.g. "00"
        match = re.fullmatch(r"(?P<addr>\d{2})", reply)
        if match:
            return int(match.group("addr"))

        raise DPSProtocolError(f"Unexpected address reply: {reply!r}")


    def query_unit_code(self) -> int:
        result = self.send_command("U,?")
        self._require_reply(result, "U,?")
        reply = self._normalize_reply(result.reply_text, "U,?").strip()

        try:
            return int(reply)
        except ValueError as exc:
            raise DPSProtocolError(f"Unexpected unit reply: {reply!r}") from exc

    def query_unit(self) -> Unit:
        return self._unit_code_to_name(self.query_unit_code())

    def set_unit(self, unit: Unit) -> None:
        code = self._unit_name_to_code(unit)
        self._send_silent_command(f"U,{code}")
        self.cfg.unit = unit

    def disable_autosend(self) -> None:
        self._send_silent_command("A,9999")

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
            # Logger should read unit once before the measurement starts and then
            # reuse the cached cfg.unit value for all rows.
            return self.read_pressure_r(), self.cfg.unit
        return self.read_pressure_with_unit()

    def read_raw(self) -> str:
        result = self.send_command("*Z")
        self._require_reply(result, "*Z")
        return self._normalize_reply(result.reply_text, "*Z")
