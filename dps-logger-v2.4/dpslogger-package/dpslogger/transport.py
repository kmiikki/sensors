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
    poll_sleep_s: float = 0.01


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
    - short observation/drain helpers for unsolicited traffic
    """

    def __init__(self, cfg: SerialTransportConfig):
        self.cfg = cfg
        self._ser: Optional[object] = None
        self._rx_buffer = b""

    @property
    def is_open(self) -> bool:
        """Return ``True`` if the serial port is currently open."""
        return self._ser is not None and getattr(self._ser, "is_open", False)

    def __enter__(self) -> "SerialTransport":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

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
            self._rx_buffer = b""
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
            self._rx_buffer = b""

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

    def _require_open_serial(self) -> object:
        if not self.is_open:
            self.open()
        assert self._ser is not None
        return self._ser

    def _split_complete_lines(self, data: bytes) -> tuple[list[bytes], bytes]:
        """Split bytes into complete lines and trailing remainder.

        Accepts ``\n``, ``\r`` and ``\r\n`` as inbound line endings.
        Returned complete lines do not include trailing line-ending bytes.
        """
        lines: list[bytes] = []
        start = 0
        i = 0
        data_len = len(data)

        while i < data_len:
            byte = data[i]
            if byte == 0x0D:  # \r
                lines.append(data[start:i])
                if i + 1 < data_len and data[i + 1] == 0x0A:
                    i += 1
                start = i + 1
            elif byte == 0x0A:  # \n
                lines.append(data[start:i])
                start = i + 1
            i += 1

        remainder = data[start:]
        return lines, remainder

    def clear_buffers(self) -> None:
        """Reset serial input and output buffers and drop partial RX data."""
        ser = self._require_open_serial()
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            self._rx_buffer = b""
        except Exception as exc:
            raise SerialTransportError(f"Failed to clear serial buffers: {exc}") from exc

    def write_raw(self, data: bytes) -> int:
        """Write raw bytes to the serial port and flush output."""
        ser = self._require_open_serial()
        try:
            written = ser.write(data)
            ser.flush()
            return int(written)
        except Exception as exc:
            raise SerialTransportError(f"Failed to write serial data: {exc}") from exc

    def write_line(self, text: str) -> int:
        """Write one encoded command line using the configured outbound EOL."""
        return self.write_raw(self._encode_command(text))

    def read_available(self) -> bytes:
        """Read all currently available bytes without waiting for one full line.

        Returns empty bytes when no data is immediately available.
        """
        ser = self._require_open_serial()
        try:
            waiting = int(getattr(ser, "in_waiting", 0) or 0)
            if waiting <= 0:
                return b""
            data = ser.read(waiting)
        except Exception as exc:
            raise SerialTransportError(f"Failed to read available serial data: {exc}") from exc
        return data or b""

    def read_line(self) -> bytes:
        """Read one line from the serial port.

        Returns empty bytes on timeout. This is intentional because timeout is a
        normal event in passive listen mode.
        """
        ser = self._require_open_serial()
        try:
            data = ser.readline()
        except Exception as exc:
            raise SerialTransportError(f"Failed to read serial data: {exc}") from exc
        return data or b""

    def read_lines_for(self, duration_s: float) -> list[str]:
        """Collect complete lines arriving during a fixed observation window.

        Inbound data is handled tolerantly so the transport works with both real
        hardware and ttySIM regardless of whether the sender uses ``\n``,
        ``\r`` or ``\r\n`` line endings.
        """
        if duration_s < 0:
            raise ValueError("duration_s must be >= 0")

        lines: list[str] = []
        deadline = time.perf_counter() + duration_s

        while True:
            chunk = self.read_available()
            if chunk:
                combined = self._rx_buffer + chunk
                complete_lines, remainder = self._split_complete_lines(combined)
                self._rx_buffer = remainder
                lines.extend(
                    line.decode(self.cfg.encoding, errors=self.cfg.errors)
                    for line in complete_lines
                )

            if time.perf_counter() >= deadline:
                break

            if not chunk and self.cfg.poll_sleep_s > 0:
                time.sleep(min(self.cfg.poll_sleep_s, max(0.0, deadline - time.perf_counter())))

        return lines

    def drain_for(self, duration_s: float) -> list[str]:
        """Drain unsolicited traffic for a fixed time window."""
        return self.read_lines_for(duration_s)

    def line_is_quiet(self, duration_s: float, max_lines: int = 0) -> bool:
        """Return ``True`` when the line stays quiet during the window.

        Parameters
        ----------
        duration_s
            Observation window length in seconds.
        max_lines
            Maximum allowed number of complete incoming lines. The default of
            ``0`` means completely quiet.
        """
        if max_lines < 0:
            raise ValueError("max_lines must be >= 0")
        return len(self.read_lines_for(duration_s)) <= max_lines

    def transact(self, cmd: str) -> TransactionResult:
        """Send one command and read one line of reply.

        The transport does *not* treat an empty reply as an exception. Instead,
        ``ok`` in the returned :class:`TransactionResult` is set to ``False``.
        Higher layers decide whether lack of reply is fatal.
        """
        ser = self._require_open_serial()

        command_bytes = self._encode_command(cmd)

        if self.cfg.reset_input_before_cmd:
            try:
                ser.reset_input_buffer()
                self._rx_buffer = b""
            except Exception:
                pass

        t0 = time.perf_counter()
        try:
            ser.write(command_bytes)
            ser.flush()
        except Exception as exc:
            raise SerialTransportError(f"Failed to write command {cmd!r}: {exc}") from exc

        if self.cfg.write_sleep_s > 0:
            time.sleep(self.cfg.write_sleep_s)

        try:
            reply_bytes = ser.readline()
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
