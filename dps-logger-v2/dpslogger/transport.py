from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional


@dataclass
class SerialTransportConfig:
    """Serial transport settings.

    Parameters are intentionally minimal and map directly to pyserial usage.
    Protocol-specific concerns (addresses, DPS commands, units) belong in
    :mod:`dpslogger.protocol`, not here.
    """

    port: str = "/dev/ttyLOG"
    baud: int = 9600
    timeout_s: float = 1.0
    write_sleep_s: float = 0.2
    eol: str = "crlf"  # "cr" | "crlf"
    reset_input_before_cmd: bool = False
    encoding: str = "ascii"
    errors: str = "replace"


@dataclass
class TransactionResult:
    """Result of one request/response transaction."""

    command_text: str
    command_bytes: bytes
    reply_text: str
    reply_bytes: bytes
    latency_s: float
    ok: bool


class SerialTransportError(Exception):
    """Generic serial transport error."""


class SerialTransport:
    """Thin serial transport for line-oriented request/response protocols.

    This class deliberately knows nothing about DPS commands. It only handles:

    - port open / close
    - command encoding + line endings
    - single-line request/response transactions
    - passive line reading for listen mode
    """

    def __init__(self, cfg: SerialTransportConfig):
        self.cfg = cfg
        self._ser: Optional[object] = None

    @property
    def is_open(self) -> bool:
        """Return ``True`` if the serial port is currently open."""
        return self._ser is not None and getattr(self._ser, "is_open", False)

    def open(self) -> None:
        """Open the configured serial port if it is not already open."""
        if self.is_open:
            return

        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise SerialTransportError("pyserial is not installed.") from exc

        try:
            self._ser = serial.Serial(
                port=self.cfg.port,
                baudrate=self.cfg.baud,
                timeout=self.cfg.timeout_s,
                write_timeout=self.cfg.timeout_s,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
        except Exception as exc:
            raise SerialTransportError(
                f"Failed to open serial port {self.cfg.port}: {exc}"
            ) from exc

    def close(self) -> None:
        """Close the serial port if open."""
        if self._ser is None:
            return
        try:
            if getattr(self._ser, "is_open", False):
                self._ser.close()
        except Exception as exc:
            raise SerialTransportError(f"Failed to close serial port: {exc}") from exc
        finally:
            self._ser = None

    def opened(self):
        """Context manager wrapper around :meth:`open` / :meth:`close`."""

        class _Ctx:
            def __init__(self, outer: "SerialTransport"):
                self._outer = outer

            def __enter__(self) -> "SerialTransport":
                self._outer.open()
                return self._outer

            def __exit__(self, exc_type, exc, tb) -> None:
                self._outer.close()

        return _Ctx(self)

    def _eol_bytes(self) -> bytes:
        if self.cfg.eol == "cr":
            return b"\r"
        if self.cfg.eol == "crlf":
            return b"\r\n"
        raise SerialTransportError(f"Unsupported EOL mode: {self.cfg.eol}")

    def _encode_command(self, cmd: str) -> bytes:
        return cmd.encode(self.cfg.encoding, errors=self.cfg.errors) + self._eol_bytes()

    def _decode_bytes(self, data: bytes) -> str:
        text = data.decode(self.cfg.encoding, errors=self.cfg.errors)
        return text.rstrip("\r\n")

    def write_raw(self, data: bytes) -> int:
        """Write raw bytes to the serial port and flush output."""
        if not self.is_open:
            self.open()
        assert self._ser is not None
        try:
            written = self._ser.write(data)
            self._ser.flush()
            return int(written)
        except Exception as exc:
            raise SerialTransportError(f"Failed to write serial data: {exc}") from exc

    def read_line(self) -> bytes:
        """Read one line from the serial port.

        Returns empty bytes on timeout. This is intentional because timeout is a
        normal event in passive listen mode.
        """
        if not self.is_open:
            self.open()
        assert self._ser is not None
        try:
            data = self._ser.readline()
        except Exception as exc:
            raise SerialTransportError(f"Failed to read serial data: {exc}") from exc
        return data or b""

    def transact(self, cmd: str) -> TransactionResult:
        """Send one command and read one line of reply.

        The transport does *not* treat an empty reply as an exception. Instead,
        ``ok`` in the returned :class:`TransactionResult` is set to ``False``.
        Higher layers decide whether lack of reply is fatal.
        """
        if not self.is_open:
            self.open()
        assert self._ser is not None

        command_bytes = self._encode_command(cmd)

        if self.cfg.reset_input_before_cmd:
            try:
                self._ser.reset_input_buffer()
            except Exception:
                pass

        t0 = time.perf_counter()
        try:
            self._ser.write(command_bytes)
            self._ser.flush()
        except Exception as exc:
            raise SerialTransportError(f"Failed to write command {cmd!r}: {exc}") from exc

        if self.cfg.write_sleep_s > 0:
            time.sleep(self.cfg.write_sleep_s)

        try:
            reply_bytes = self._ser.readline()
        except Exception as exc:
            raise SerialTransportError(f"Failed to read reply for {cmd!r}: {exc}") from exc
        t1 = time.perf_counter()

        reply_bytes = reply_bytes or b""
        reply_text = self._decode_bytes(reply_bytes) if reply_bytes else ""

        return TransactionResult(
            command_text=cmd,
            command_bytes=command_bytes,
            reply_text=reply_text,
            reply_bytes=reply_bytes,
            latency_s=t1 - t0,
            ok=bool(reply_bytes),
        )
