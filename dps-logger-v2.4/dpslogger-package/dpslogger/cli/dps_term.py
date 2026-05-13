#!/usr/bin/env python3
from __future__ import annotations

import argparse
from typing import Optional

from dpslogger.cli.common import build_base_parser, build_configs
from dpslogger.protocol import DPS8000, DPSProtocolError
from dpslogger.transport import SerialTransport, SerialTransportError, TransactionResult


HELP_TEXT = """Local REPL commands:
  help            Show this help text
  exit | quit     Exit terminal
  addr N          Set default RS-485 address
  addr none       Clear default address
  hex on|off      Toggle hex dump output
  listen          Passive listen mode until Ctrl+C

Any other line is sent as a DPS command.
Examples:
  I
  R
  *G
  U,bar
  A,0
  2:R
"""


def _hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _print_transaction(result: TransactionResult, hex_mode: bool) -> None:
    if hex_mode:
        print(f"OUT  {_hexdump(result.command_bytes)}")
        if result.reply_bytes:
            print(f"IN   {_hexdump(result.reply_bytes)}")
        else:
            print("IN   <timeout>")
        if result.reply_text:
            print(f"TXT  {result.reply_text}")
        print(f"LAT  {result.latency_s:.3f} s")
    else:
        if result.reply_text:
            print(result.reply_text)
        elif result.ok:
            print("<empty reply>")
        else:
            print(f"ERROR: Timeout waiting response for {result.command_text!r}")


def _print_listen_line(data: bytes, hex_mode: bool, encoding: str, errors: str) -> None:
    if not data:
        return
    if hex_mode:
        print(f"IN   {_hexdump(data)}")
    text = data.decode(encoding, errors=errors).rstrip("\r\n")
    if text:
        print(f"TXT  {text}" if hex_mode else text)
    elif hex_mode:
        print("TXT  <empty>")


def _build_prompt(addr: Optional[int], hex_mode: bool) -> str:
    parts: list[str] = []
    if addr is not None:
        parts.append(f"addr={addr}")
    if hex_mode:
        parts.append("hex")
    if parts:
        return f"dps[{','.join(parts)}]> "
    return "dps> "


def _run_listen(transport: SerialTransport, hex_mode: bool) -> int:
    print(f"LISTEN {transport.cfg.port} @ {transport.cfg.baud} baud")
    print("Press Ctrl+C to stop")
    try:
        with transport.opened():
            while True:
                data = transport.read_line()
                _print_listen_line(
                    data,
                    hex_mode=hex_mode,
                    encoding=transport.cfg.encoding,
                    errors=transport.cfg.errors,
                )
    except KeyboardInterrupt:
        print()
        return 0
    except SerialTransportError as exc:
        print(f"ERROR: {exc}")
        return 1


def _run_single(dps: DPS8000, cmd: str, hex_mode: bool) -> int:
    try:
        with dps.opened():
            result = dps.send_command(cmd)
    except (DPSProtocolError, SerialTransportError) as exc:
        print(f"ERROR: {exc}")
        return 1

    _print_transaction(result, hex_mode=hex_mode)
    return 0 if result.ok else 1


def _run_repl(dps: DPS8000, transport: SerialTransport, hex_mode: bool) -> int:
    current_hex = hex_mode

    try:
        dps.open()
    except (DPSProtocolError, SerialTransportError) as exc:
        print(f"ERROR: {exc}")
        return 1

    try:
        while True:
            try:
                line = input(_build_prompt(dps.cfg.address, current_hex))
            except EOFError:
                print()
                break

            line = line.strip()
            if not line:
                continue

            low = line.lower()
            if low in {"exit", "quit"}:
                break
            if low == "help":
                print(HELP_TEXT)
                continue
            if low == "listen":
                try:
                    print(f"LISTEN {transport.cfg.port} @ {transport.cfg.baud} baud")
                    print("Press Ctrl+C to return to REPL")
                    while True:
                        data = transport.read_line()
                        _print_listen_line(
                            data,
                            hex_mode=current_hex,
                            encoding=transport.cfg.encoding,
                            errors=transport.cfg.errors,
                        )
                except KeyboardInterrupt:
                    print()
                    continue
                except SerialTransportError as exc:
                    print(f"ERROR: {exc}")
                    continue

            if low.startswith("addr "):
                value = line.split(None, 1)[1].strip()
                if value.lower() == "none":
                    dps.set_address(None)
                    print("Default address cleared")
                    continue
                try:
                    addr = int(value)
                except ValueError:
                    print(f"ERROR: Invalid address: {value!r}")
                    continue
                dps.set_address(addr)
                print(f"Default address set to {addr}")
                continue

            if low.startswith("hex "):
                value = line.split(None, 1)[1].strip().lower()
                if value == "on":
                    current_hex = True
                    print("Hex dump enabled")
                elif value == "off":
                    current_hex = False
                    print("Hex dump disabled")
                else:
                    print("ERROR: Use 'hex on' or 'hex off'")
                continue

            try:
                result = dps.send_command(line)
            except DPSProtocolError as exc:
                print(f"ERROR: {exc}")
                continue

            _print_transaction(result, hex_mode=current_hex)

    except KeyboardInterrupt:
        print()
    finally:
        try:
            dps.close()
        except Exception:
            pass

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = build_base_parser("DPS interactive terminal")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-i", "--interactive", action="store_true", help="Interactive REPL mode")
    mode.add_argument("-c", "--cmd", help="Send a single command and exit")
    mode.add_argument("--listen", action="store_true", help="Listen passively for incoming data")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.interactive and args.cmd is None and not args.listen:
        args.interactive = True

    transport_cfg, dps_cfg = build_configs(args)
    transport = SerialTransport(transport_cfg)
    dps = DPS8000(transport, dps_cfg)

    if args.listen:
        return _run_listen(transport, hex_mode=args.hex)
    if args.cmd is not None:
        return _run_single(dps, args.cmd, hex_mode=args.hex)
    return _run_repl(dps, transport, hex_mode=args.hex)


if __name__ == "__main__":
    raise SystemExit(main())
