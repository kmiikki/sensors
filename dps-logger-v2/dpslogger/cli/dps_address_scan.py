#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Iterable

from dpslogger.cli.common import build_base_parser, build_configs
from dpslogger.protocol import DPS8000, DPSProtocolError
from dpslogger.transport import SerialTransport, SerialTransportError, TransactionResult


@dataclass
class ScanResult:
    addr: int
    found: bool
    cmd_used: str | None
    reply_text: str
    latency_s: float | None
    error: str | None


def _hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _parse_address_list(spec: str) -> list[int]:
    values: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"Invalid address: {part!r}") from exc
        if value < 0:
            raise argparse.ArgumentTypeError(f"Address must be >= 0: {part!r}")
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError("At least one address must be provided")
    return values


def _iter_addresses(args: argparse.Namespace) -> list[int]:
    if args.addresses is not None:
        return sorted(dict.fromkeys(args.addresses))

    start = args.start
    end = args.end
    if start < 0 or end < 0:
        raise ValueError("Address range must be >= 0")
    if end < start:
        raise ValueError("--end must be >= --start")

    addresses = list(range(start, end + 1))
    if args.direct_only:
        return [a for a in addresses if a == 0]
    if args.network_only:
        return [a for a in addresses if a > 0]
    return addresses


def _print_scan_header(*, port: str, profile: str) -> None:
    print(f"PORT: {port}")
    print(f"PROFILE: {profile}")
    print()


def _print_hex_debug(addr: int, result: TransactionResult) -> None:
    tag = f"[addr {addr:02d}]"
    print(f"{tag} OUT {_hexdump(result.command_bytes)}")
    if result.reply_bytes:
        print(f"{tag} IN  {_hexdump(result.reply_bytes)}")
    else:
        print(f"{tag} IN  <timeout>")
    if result.reply_text:
        print(f"{tag} TXT {result.reply_text}")
    print(f"{tag} LAT {result.latency_s:.3f} s")


def _scan_one_command(dps: DPS8000, addr: int, cmd: str, hex_mode: bool) -> TransactionResult:
    result = dps.send_command(cmd)
    if hex_mode:
        _print_hex_debug(addr, result)
    return result


def _scan_address(dps: DPS8000, addr: int, cmd_mode: str, hex_mode: bool) -> ScanResult:
    dps.set_address(addr)

    cmds: list[str]
    if cmd_mode == "I":
        cmds = ["I"]
    elif cmd_mode == "R":
        cmds = ["R"]
    else:
        cmds = ["I", "R"]

    last_error: str | None = None
    for cmd in cmds:
        try:
            result = _scan_one_command(dps, addr, cmd, hex_mode)
        except DPSProtocolError as exc:
            last_error = str(exc)
            continue

        if result.ok and result.reply_text.strip():
            return ScanResult(
                addr=addr,
                found=True,
                cmd_used=cmd,
                reply_text=result.reply_text,
                latency_s=result.latency_s,
                error=None,
            )

        last_error = "timeout"

    return ScanResult(
        addr=addr,
        found=False,
        cmd_used=None,
        reply_text="",
        latency_s=None,
        error=last_error or "timeout",
    )


def _print_table(
    results: Iterable[ScanResult],
    *,
    port: str,
    profile: str,
    show_failures: bool,
) -> None:
    results_list = list(results)
    print(f"PORT: {port}")
    print(f"PROFILE: {profile}")
    print()
    print(f"{'ADDR':<5} {'STATUS':<6} {'CMD':<4} REPLY / ERROR")

    found_count = 0
    for row in results_list:
        if not row.found and not show_failures:
            continue

        status = "OK" if row.found else "NO"
        cmd = row.cmd_used or "-"
        detail = row.reply_text if row.found else (row.error or "")
        print(f"{row.addr:02d}    {status:<6} {cmd:<4} {detail}")
        if row.found:
            found_count += 1

    if not show_failures:
        found_count = sum(1 for r in results_list if r.found)

    print()
    print(f"Found {found_count} device(s).")


def build_parser() -> argparse.ArgumentParser:
    parser = build_base_parser("Scan RS-485 addresses for DPS devices")
    parser.add_argument("--start", type=int, default=0, help="Start address (default: 0)")
    parser.add_argument("--end", type=int, default=31, help="End address inclusive (default: 31)")
    parser.add_argument(
        "--addresses",
        type=_parse_address_list,
        help="Comma-separated address list, e.g. 0,2,5,9",
    )
    parser.add_argument(
        "--cmd",
        choices=["I", "R", "both"],
        default="both",
        help="Command strategy per address (default: both)",
    )
    parser.add_argument(
        "--direct-only",
        action="store_true",
        help="Scan only address 0",
    )
    parser.add_argument(
        "--network-only",
        action="store_true",
        help="Scan only addresses > 0",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--show-failures",
        action="store_true",
        help="Show addresses that did not answer",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress initial header/progress output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.direct_only and args.network_only:
        parser.error("--direct-only and --network-only are mutually exclusive")

    try:
        addresses = _iter_addresses(args)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    if not addresses:
        parser.error("No addresses selected")
        return 2

    transport_cfg, dps_cfg = build_configs(args)
    transport = SerialTransport(transport_cfg)
    dps = DPS8000(transport, dps_cfg)

    if not args.json and not args.quiet:
        _print_scan_header(port=transport_cfg.port, profile=args.profile)

    results: list[ScanResult] = []
    try:
        with dps.opened():
            total = len(addresses)
            for idx, addr in enumerate(addresses, start=1):
                if not args.json and not args.quiet and not args.hex:
                    print(f"Scanning {idx}/{total}", flush=True)
                results.append(_scan_address(dps, addr, args.cmd, args.hex))
    except (SerialTransportError, DPSProtocolError) as exc:
        print(f"ERROR: {exc}")
        return 1

    if args.json:
        payload = {
            "port": transport_cfg.port,
            "profile": args.profile,
            "results": [asdict(r) for r in results],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_table(
            results,
            port=transport_cfg.port,
            profile=args.profile,
            show_failures=args.show_failures,
        )

    return 0 if any(r.found for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())