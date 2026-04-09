#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from typing import Iterable

from dpslogger.cli.common import build_base_parser, build_configs
from dpslogger.protocol import DPS8000, DPSProtocolError
from dpslogger.transport import SerialTransport, SerialTransportError, TransactionResult


@dataclass
class ScanResult:
    mode: str
    addr: int
    found: bool
    command: str
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
        if not 1 <= value <= 32:
            raise argparse.ArgumentTypeError(f"Address must be in range 1..32: {part!r}")
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError("At least one address must be provided")
    return sorted(dict.fromkeys(values))


def _iter_network_addresses(args: argparse.Namespace) -> list[int]:
    if args.addresses is not None:
        return args.addresses

    start = args.start
    end = args.end
    if start < 1 or end < 1:
        raise ValueError("Address range must be in 1..32")
    if start > 32 or end > 32:
        raise ValueError("Address range must be in 1..32")
    if end < start:
        raise ValueError("--end must be >= --start")

    return list(range(start, end + 1))


def _print_scan_header(*, port: str, profile: str) -> None:
    print(f"PORT: {port}")
    print(f"PROFILE: {profile}")
    print()


def _print_hex_debug(tag: str, result: TransactionResult) -> None:
    print(f"[{tag}] OUT {_hexdump(result.command_bytes)}")
    if result.reply_bytes:
        print(f"[{tag}] IN  {_hexdump(result.reply_bytes)}")
    else:
        print(f"[{tag}] IN  <timeout>")
    if result.reply_text:
        print(f"[{tag}] TXT {result.reply_text}")
    print(f"[{tag}] LAT {result.latency_s:.3f} s")


def _is_valid_address_reply(addr: int, reply_text: str) -> bool:
    text = reply_text.strip()
    if not text:
        return False

    expected = f"{addr:02d}:{addr:02d}"
    if text == expected:
        return True

    # Be slightly tolerant if protocol layer strips whitespace differently.
    parts = text.split(":", 1)
    if len(parts) != 2:
        return False
    try:
        left = int(parts[0])
        right = int(parts[1])
    except ValueError:
        return False
    return left == addr and right == addr


def _scan_direct(dps: DPS8000, *, hex_mode: bool) -> ScanResult:
    dps.set_address(0)
    command = "N,?"
    try:
        result = dps.send_command(command)
        if hex_mode:
            _print_hex_debug("direct", result)
        if result.ok and _is_valid_address_reply(0, result.reply_text):
            return ScanResult(
                mode="direct",
                addr=0,
                found=True,
                command=command,
                reply_text=result.reply_text.strip(),
                latency_s=result.latency_s,
                error=None,
            )
        return ScanResult(
            mode="direct",
            addr=0,
            found=False,
            command=command,
            reply_text=result.reply_text.strip(),
            latency_s=result.latency_s if result.reply_text else None,
            error="invalid reply" if result.reply_text else "timeout",
        )
    except DPSProtocolError as exc:
        return ScanResult(
            mode="direct",
            addr=0,
            found=False,
            command=command,
            reply_text="",
            latency_s=None,
            error=str(exc),
        )


def _scan_network_address(dps: DPS8000, addr: int, *, hex_mode: bool) -> ScanResult:
    dps.set_address(addr)
    command = "N,?"
    try:
        result = dps.send_command(command)
        if hex_mode:
            _print_hex_debug(f"addr {addr:02d}", result)
        if result.ok and _is_valid_address_reply(addr, result.reply_text):
            return ScanResult(
                mode="addressed",
                addr=addr,
                found=True,
                command=f"{addr}:N,?",
                reply_text=result.reply_text.strip(),
                latency_s=result.latency_s,
                error=None,
            )
        return ScanResult(
            mode="addressed",
            addr=addr,
            found=False,
            command=f"{addr}:N,?",
            reply_text=result.reply_text.strip(),
            latency_s=result.latency_s if result.reply_text else None,
            error="invalid reply" if result.reply_text else "timeout",
        )
    except DPSProtocolError as exc:
        return ScanResult(
            mode="addressed",
            addr=addr,
            found=False,
            command=f"{addr}:N,?",
            reply_text="",
            latency_s=None,
            error=str(exc),
        )


def _print_table(
    results: Iterable[ScanResult],
    *,
    port: str,
    profile: str,
    show_failures: bool,
) -> None:
    results_list = list(results)
    # print(f"PORT: {port}")
    # print(f"PROFILE: {profile}")
    print()
    print(f"{'MODE':<10} {'ADDR':<5} {'STATUS':<6} REPLY / ERROR")

    found_count = 0
    for row in results_list:
        if not row.found and not show_failures:
            continue

        status = "OK" if row.found else "NO"
        detail = row.reply_text if row.found else (row.error or "")
        addr_display = str(row.addr)
        print(f"{row.mode:<10} {addr_display:<5} {status:<6} {detail}")
        if row.found:
            found_count += 1

    if not show_failures:
        found_count = sum(1 for r in results_list if r.found)

    network_addrs = [r.addr for r in results_list if r.mode == "addressed" and r.found]
    direct_found = any(r.mode == "direct" and r.found for r in results_list)

    print()
    print(f"Direct mode: {'found' if direct_found else 'not found'}")
    print(
        "Addressed devices: "
        + (", ".join(str(a) for a in network_addrs) if network_addrs else "none")
    )
    print(f"Found {found_count} device(s) total.")


def build_parser() -> argparse.ArgumentParser:
    parser = build_base_parser("Scan DPS direct mode and RS-485 addresses")
    parser.add_argument("--start", type=int, default=1, help="Start addressed scan at this address (default: 1)")
    parser.add_argument("--end", type=int, default=32, help="End addressed scan at this address (default: 32)")
    parser.add_argument(
        "--addresses",
        type=_parse_address_list,
        help="Comma-separated addressed scan list, e.g. 1,2,5,9",
    )
    parser.add_argument(
        "--direct-only",
        action="store_true",
        help="Scan only direct mode (N,?)",
    )
    parser.add_argument(
        "--network-only",
        action="store_true",
        help="Scan only addressed mode (1..32)",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=0.2,
        help="Delay after each query before continuing (default: 0.2)",
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
        help="Suppress progress output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.direct_only and args.network_only:
        parser.error("--direct-only and --network-only are mutually exclusive")

    try:
        network_addresses = _iter_network_addresses(args)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    transport_cfg, dps_cfg = build_configs(args)
    transport = SerialTransport(transport_cfg)
    dps = DPS8000(transport, dps_cfg)

    if not args.json and not args.quiet:
        _print_scan_header(port=transport_cfg.port, profile=args.profile)

    results: list[ScanResult] = []
    try:
        with dps.opened():
            if not args.network_only:
                if not args.json and not args.quiet and not args.hex:
                    print("Trying direct mode: N,?", flush=True)
                results.append(_scan_direct(dps, hex_mode=args.hex))
                if args.settle_seconds > 0:
                    time.sleep(args.settle_seconds)

            if not args.direct_only:
                total = len(network_addresses)
                for idx, addr in enumerate(network_addresses, start=1):
                    if not args.json and not args.quiet and not args.hex:
                        print(f"Trying address {addr} ({idx}/{total}): {addr}:N,?", flush=True)
                    results.append(_scan_network_address(dps, addr, hex_mode=args.hex))
                    if args.settle_seconds > 0:
                        time.sleep(args.settle_seconds)
    except (SerialTransportError, DPSProtocolError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        payload = {
            "port": transport_cfg.port,
            "profile": args.profile,
            "direct_found": any(r.mode == "direct" and r.found for r in results),
            "found_addresses": [r.addr for r in results if r.mode == "addressed" and r.found],
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
