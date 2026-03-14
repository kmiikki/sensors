from __future__ import annotations

import argparse
from datetime import datetime, timezone

from dpslogger.cli.common import build_configs
from dpslogger.protocol import DPS8000
from dpslogger.transport import SerialTransport


def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for single-shot DPS reads."""
    parser = argparse.ArgumentParser(
        description="Read a single pressure value from a DPS sensor."
    )
    parser.add_argument("--profile", default="real", help="Profile name")
    parser.add_argument("--port", required=True, help="Serial port (e.g. /dev/ttyLOG)")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--addr", type=int, default=0, help="Sensor address")
    parser.add_argument(
        "--mode",
        choices=("R", "G"),
        default="R",
        help="Read mode: R = pressure only, G = value + unit via *G",
    )
    parser.add_argument(
        "--timestamp",
        action="store_true",
        help="Prefix output with ISO-8601 timestamp",
    )
    parser.add_argument(
        "--utc",
        action="store_true",
        help="Use UTC timestamp instead of local time",
    )
    return parser


def make_dps(args: argparse.Namespace) -> DPS8000:
    """Build DPS client using the same config path as the other CLI tools."""
    transport_cfg, dps_cfg = build_configs(args)
    transport = SerialTransport(transport_cfg)
    return DPS8000(transport, dps_cfg)


def iso_timestamp(use_utc: bool) -> str:
    """Return current timestamp in ISO-8601 format."""
    if use_utc:
        return datetime.now(timezone.utc).isoformat()
    return datetime.now().astimezone().isoformat()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    dps = make_dps(args)

    try:
        if args.mode == "R":
            value = dps.read_pressure_r()
            output = f"{value:.5f}"
        else:
            value, unit = dps.read_pressure_with_unit()
            output = f"{value:.5f},{unit}"

        if args.timestamp:
            print(f"{iso_timestamp(args.utc)},{output}")
        else:
            print(output)

        return 0

    except Exception as exc:
        print(f"ERROR: {exc}")
        print(
            f"No response received from sensor at address {args.addr} "
            f"on port {args.port}."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
    
