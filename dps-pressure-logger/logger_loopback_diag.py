#!/usr/bin/env python3
"""
Loopback diagnostics between two serial ports (default: /dev/ttyLOG and /dev/ttySIM).

- Tests one or more baud rates
- Sends test frames from TX port to RX port
- Verifies that the received data matches what was sent
- Reports per-baud statistics (success / failure)

Usage examples:

  # Default ports, default baud list (9600,19200,38400,57600,115200), 10 frames each
  logger_loopback_diag.py

  # Only 9600 and 115200 baud, 20 frames
  logger_loopback_diag.py --bauds 9600,115200 --frames 20

  # Custom ports
  logger_loopback_diag.py --tx /dev/ttyLOG --rx /dev/ttySIM
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class LoopbackStats:
    baud: int
    frames: int
    ok: int
    fail: int


def parse_baud_list(s: str) -> List[int]:
    bauds: List[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            bauds.append(int(part))
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid baud value: {part}")
    if not bauds:
        raise argparse.ArgumentTypeError("At least one baud rate must be provided.")
    return bauds


def try_import_serial():
    try:
        import serial  # type: ignore
    except ImportError as e:
        print("[ERROR] pyserial is not installed in this environment.")
        print("        Install it, for example:")
        print("          micromamba activate logger")
        print("          micromamba install pyserial")
        raise SystemExit(1)
    return serial


def open_port(serial_mod, dev: str, baud: int, timeout: float):
    try:
        ser = serial_mod.Serial(
            port=dev,
            baudrate=baud,
            timeout=timeout,
            bytesize=serial_mod.EIGHTBITS,
            parity=serial_mod.PARITY_NONE,
            stopbits=serial_mod.STOPBITS_ONE,
        )
    except serial_mod.SerialException as e:  # type: ignore[attr-defined]
        print(f"[ERROR] Failed to open {dev} at {baud} baud: {e}")
        return None
    return ser


def build_frame(index: int, length: int) -> bytes:
    """
    Build a simple ASCII test frame with a sequence number and padding.
    Example: b'FRAME#0001: XXXXX...\\n'
    """
    header = f"FRAME#{index:04d}: ".encode("ascii")
    payload_len = max(0, length - len(header) - 1)
    payload = (b"X" * payload_len)
    return header + payload + b"\n"


def send_and_receive(
    ser_tx,
    ser_rx,
    frame: bytes,
    read_timeout: float,
) -> Tuple[bool, bytes]:
    """
    Send one frame on ser_tx and try to receive the same frame from ser_rx.
    Returns (ok, received_data).
    """
    # Reset RX input buffer before sending
    ser_rx.reset_input_buffer()

    # Send frame
    ser_tx.write(frame)
    ser_tx.flush()

    # Try to read the same number of bytes
    expected_len = len(frame)
    received = bytearray()
    deadline = time.time() + read_timeout

    while len(received) < expected_len and time.time() < deadline:
        chunk = ser_rx.read(expected_len - len(received))
        if not chunk:
            # no more data this moment, short sleep to avoid busy loop
            time.sleep(0.01)
            continue
        received.extend(chunk)

    ok = bytes(received) == frame
    return ok, bytes(received)


def run_loopback(
    tx_dev: str,
    rx_dev: str,
    bauds: List[int],
    frames_per_baud: int,
    frame_length: int,
    serial_timeout: float,
    read_timeout: float,
    pause_between_frames: float,
) -> List[LoopbackStats]:
    serial_mod = try_import_serial()

    stats: List[LoopbackStats] = []

    for baud in bauds:
        print(f"\n=== Testing baud {baud} on TX={tx_dev}, RX={rx_dev} ===")

        ser_tx = open_port(serial_mod, tx_dev, baud, serial_timeout)
        ser_rx = open_port(serial_mod, rx_dev, baud, serial_timeout)

        if ser_tx is None or ser_rx is None:
            print(f"[ERROR] Skipping baud {baud} due to open failure.")
            if ser_tx is not None:
                ser_tx.close()
            if ser_rx is not None:
                ser_rx.close()
            stats.append(LoopbackStats(baud=baud, frames=0, ok=0, fail=0))
            continue

        # Clear buffers
        ser_tx.reset_input_buffer()
        ser_tx.reset_output_buffer()
        ser_rx.reset_input_buffer()
        ser_rx.reset_output_buffer()

        ok_count = 0
        fail_count = 0

        for i in range(1, frames_per_baud + 1):
            frame = build_frame(i, frame_length)
            ok, received = send_and_receive(ser_tx, ser_rx, frame, read_timeout=read_timeout)

            if ok:
                ok_count += 1
                print(f"  [{i:03d}] OK")
            else:
                fail_count += 1
                print(f"  [{i:03d}] FAIL")
                print(f"       Sent    : {frame!r}")
                print(f"       Received: {received!r}")

            if pause_between_frames > 0.0:
                time.sleep(pause_between_frames)

        ser_tx.close()
        ser_rx.close()

        stats.append(LoopbackStats(baud=baud, frames=frames_per_baud, ok=ok_count, fail=fail_count))

    return stats


def print_summary(stats: List[LoopbackStats]) -> None:
    print("\n=== Summary ===")
    if not stats:
        print("No tests were run.")
        return

    print(f"{'Baud':>8}  {'Frames':>6}  {'OK':>6}  {'Fail':>6}")
    print("-" * 32)
    for s in stats:
        print(f"{s.baud:8d}  {s.frames:6d}  {s.ok:6d}  {s.fail:6d}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="logger_loopback_diag.py",
        description=(
            "Loopback diagnostics between two serial ports, e.g. /dev/ttyLOG and /dev/ttySIM. "
            "Sends test frames at one or more baud rates and verifies that data is received correctly."
        ),
    )
    parser.add_argument(
        "--tx",
        default="/dev/ttyLOG",
        help="Transmitter device (default: /dev/ttyLOG).",
    )
    parser.add_argument(
        "--rx",
        default="/dev/ttySIM",
        help="Receiver device (default: /dev/ttySIM).",
    )
    parser.add_argument(
        "--bauds",
        type=parse_baud_list,
        default=[9600, 19200, 38400, 57600, 115200],
        help="Comma-separated list of baud rates to test, e.g. '9600,19200,115200'. "
             "Default: 9600,19200,38400,57600,115200.",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=10,
        help="Number of frames to send per baud rate (default: 10).",
    )
    parser.add_argument(
        "--length",
        type=int,
        default=32,
        help="Length of each frame in bytes (default: 32).",
    )
    parser.add_argument(
        "--serial-timeout",
        type=float,
        default=0.2,
        help="Serial port timeout in seconds for pyserial (default: 0.2).",
    )
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=0.5,
        help="Maximum time to wait for each frame on RX side (default: 0.5 seconds).",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.05,
        help="Pause between frames in seconds (default: 0.05).",
    )

    args = parser.parse_args(argv)

    print("=== Serial loopback diagnostics ===")
    print(f"TX device      : {args.tx}")
    print(f"RX device      : {args.rx}")
    print(f"Baud rates     : {', '.join(str(b) for b in args.bauds)}")
    print(f"Frames / baud  : {args.frames}")
    print(f"Frame length   : {args.length} bytes")
    print(f"Serial timeout : {args.serial_timeout} s")
    print(f"Read timeout   : {args.read_timeout} s")
    print(f"Pause between  : {args.pause} s")

    if not os.path.exists(args.tx):
        print(f"[ERROR] TX device {args.tx} does not exist.")
        return 1
    if not os.path.exists(args.rx):
        print(f"[ERROR] RX device {args.rx} does not exist.")
        return 1

    stats = run_loopback(
        tx_dev=args.tx,
        rx_dev=args.rx,
        bauds=args.bauds,
        frames_per_baud=args.frames,
        frame_length=args.length,
        serial_timeout=args.serial_timeout,
        read_timeout=args.read_timeout,
        pause_between_frames=args.pause,
    )

    print_summary(stats)

    # Exit with non-zero if any failures
    any_fail = any(s.fail > 0 for s in stats)
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
