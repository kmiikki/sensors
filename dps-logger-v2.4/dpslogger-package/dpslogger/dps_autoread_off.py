#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time

from dpslogger.transport import (
    SerialTransport,
    SerialTransportConfig,
    SerialTransportError,
)
from dpslogger.protocol import DPS8000


DEFAULT_PORT = "/dev/ttyLOG"
DEFAULT_BAUDRATE = 9600
DEFAULT_TIMEOUT = 1.0
DEFAULT_EOL = "cr"
DEFAULT_START_ADDR = 0
DEFAULT_END_ADDR = 32
DEFAULT_ATTEMPTS = 2
DEFAULT_DELAY_S = 0.2
DEFAULT_DIRECT_FIRST = True


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid integer value: {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be >= 0")
    return parsed


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid float value: {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be > 0")
    return parsed


def non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid float value: {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be >= 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Best-effort DPS autoread-off tool. Sends 'A 9999' in direct mode and "
            "for each RS-485 address in the selected range. Intended as a safe "
            "recovery/helper tool before interactive debugging, address changes, "
            "or logging."
        )
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        help=f"Serial port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"Baud rate (default: {DEFAULT_BAUDRATE})",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=DEFAULT_TIMEOUT,
        help=f"Serial timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--eol",
        choices=["cr", "crlf"],
        default=DEFAULT_EOL,
        help=f"Outgoing command line ending (default: {DEFAULT_EOL})",
    )
    parser.add_argument(
        "--start",
        type=positive_int,
        default=DEFAULT_START_ADDR,
        help=f"Start address inclusive (default: {DEFAULT_START_ADDR})",
    )
    parser.add_argument(
        "--end",
        type=positive_int,
        default=DEFAULT_END_ADDR,
        help=f"End address inclusive (default: {DEFAULT_END_ADDR})",
    )
    parser.add_argument(
        "--attempts",
        type=positive_int,
        default=DEFAULT_ATTEMPTS,
        help=(
            "Number of repeated sends per command form. Recommended default is 2, "
            "so the first try may quiet autoread and the second may land cleanly. "
            f"(default: {DEFAULT_ATTEMPTS})"
        ),
    )
    parser.add_argument(
        "--delay",
        type=non_negative_float,
        default=DEFAULT_DELAY_S,
        help=f"Delay between attempts in seconds (default: {DEFAULT_DELAY_S})",
    )
    parser.add_argument(
        "--skip-direct",
        action="store_true",
        help="Do not send the direct-mode command form 'A 9999' before address sweep.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-command progress output.",
    )
    return parser


def build_transport(args: argparse.Namespace) -> SerialTransport:
    cfg = SerialTransportConfig(
        port=args.port,
        baud=args.baudrate,
        timeout_s=args.timeout,
        write_sleep_s=0.0,
        eol=args.eol,
        reset_input_before_cmd=False,
    )
    return SerialTransport(cfg)


def write_line(transport: SerialTransport, text: str) -> None:
    if not transport.is_open:
        transport.open()
    transport.write_raw(text.encode(transport.cfg.encoding, errors=transport.cfg.errors) + _eol_bytes(transport))


def _eol_bytes(transport: SerialTransport) -> bytes:
    if transport.cfg.eol == "cr":
        return b"\r"
    if transport.cfg.eol == "crlf":
        return b"\r\n"
    raise SerialTransportError(f"Unsupported EOL mode: {transport.cfg.eol}")


def iter_autoread_off_commands(start_addr: int, end_addr: int, include_direct: bool = True) -> list[str]:
    commands: list[str] = []
    if include_direct:
        commands.append(" A,9999")
    commands.extend(f" {addr}:A,9999" for addr in range(start_addr, end_addr + 1))
    return commands


def send_command_repeated(
    transport: SerialTransport,
    cmd: str,
    attempts: int,
    delay_s: float,
    verbose: bool,
) -> None:
    for attempt in range(1, attempts + 1):
        write_line(transport, cmd)
        if verbose:
            print(f" {cmd}  [{attempt}/{attempts}]")
        if delay_s > 0:
            time.sleep(delay_s)


def send_autoread_off_sequence(
    transport: SerialTransport,
    start_addr: int = DEFAULT_START_ADDR,
    end_addr: int = DEFAULT_END_ADDR,
    attempts: int = DEFAULT_ATTEMPTS,
    delay_s: float = DEFAULT_DELAY_S,
    include_direct: bool = DEFAULT_DIRECT_FIRST,
    verbose: bool = True,
) -> list[str]:
    commands = iter_autoread_off_commands(
        start_addr=start_addr,
        end_addr=end_addr,
        include_direct=include_direct,
    )

    sent: list[str] = []
    for cmd in commands:
        send_command_repeated(
            transport=transport,
            cmd=cmd,
            attempts=attempts,
            delay_s=delay_s,
            verbose=verbose,
        )
        sent.append(cmd)
    return sent


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.end < args.start:
        parser.error("--end must be >= --start")
        return 2

    transport = build_transport(args)
    include_direct = not args.skip_direct
    verbose = not args.quiet

    if verbose:
        print(f"PORT: {args.port}")
        print(f"BAUD: {args.baudrate}")
        print(f"EOL: {args.eol}")
        print(f"ADDR RANGE: {args.start}..{args.end}")
        print(f"ATTEMPTS PER COMMAND: {args.attempts}")
        print(f"DELAY BETWEEN ATTEMPTS: {args.delay:.3f} s")
        print(f"DIRECT MODE COMMAND: {'yes' if include_direct else 'no'}")
        print()

    try:
        with transport.opened():
            sent = send_autoread_off_sequence(
                transport=transport,
                start_addr=args.start,
                end_addr=args.end,
                attempts=args.attempts,
                delay_s=args.delay,
                include_direct=include_direct,
                verbose=verbose,
            )
    except SerialTransportError as exc:
        print(f"ERROR: {exc}")
        return 1

    if verbose:
        total_writes = len(sent) * args.attempts
        print()
        print("Autoread-off sequence sent.")
        print(f"Command forms sent: {len(sent)}")
        print(f"Total writes: {total_writes}")
        print("Next step: try interactive serial debug or address change while the bus is calm.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
