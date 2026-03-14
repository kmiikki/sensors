from __future__ import annotations

import argparse
import time

from dpslogger.cli.common import build_configs
from dpslogger.protocol import DPS8000
from dpslogger.transport import SerialTransport


def positive_int(value: str) -> int:
    """Parse a non-negative integer address."""
    try:
        ivalue = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid integer: {value}") from exc
    if ivalue < 0:
        raise argparse.ArgumentTypeError("Address must be >= 0")
    return ivalue


def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser."""
    parser = argparse.ArgumentParser(
        description="Safely change DPS sensor address with pre/post verification."
    )
    parser.add_argument("--profile", default="real", help="Profile name")
    parser.add_argument("--port", required=True, help="Serial port (e.g. /dev/ttyLOG)")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--current-addr", type=positive_int, required=True)
    parser.add_argument("--new-addr", type=positive_int, required=True)
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=0.3,
        help="Delay after address change before verification (default: 0.3)",
    )
    parser.add_argument(
        "--allow-target-exists",
        action="store_true",
        help=(
            "Allow proceeding even if a device already responds at the target "
            "address before the change. Not recommended."
        ),
    )
    return parser


def make_dps(args: argparse.Namespace, addr: int) -> DPS8000:
    """Build DPS client exactly like the working CLI tools do."""
    temp_args = argparse.Namespace(**vars(args))
    temp_args.addr = addr
    transport_cfg, dps_cfg = build_configs(temp_args)
    transport = SerialTransport(transport_cfg)
    return DPS8000(transport, dps_cfg)


def probe_ident(args: argparse.Namespace, addr: int) -> tuple[bool, str]:
    """Return whether a device responds at the address, plus info/error text."""
    dps = make_dps(args, addr)
    try:
        ident = dps.identify()
        return True, ident
    except Exception as exc:
        return False, str(exc)


def change_address(args: argparse.Namespace) -> int:
    """Safely change address with pre-check and post-check."""
    current_addr = args.current_addr
    new_addr = args.new_addr

    if current_addr == new_addr:
        print(f"No change needed: device already expected at address {current_addr}.")
        return 2

    current_ok, current_info = probe_ident(args, current_addr)
    if not current_ok:
        print(
            f"Abort: no device responded at current address {current_addr}. "
            f"Error: {current_info}"
        )
        return 1

    print(f"Pre-check OK: current address {current_addr} responded: {current_info}")

    target_ok_before, target_info_before = probe_ident(args, new_addr)
    if target_ok_before and not args.allow_target_exists:
        print(
            f"Abort: target address {new_addr} already responds before change: "
            f"{target_info_before}"
        )
        return 1
    if target_ok_before:
        print(
            f"Warning: target address {new_addr} already responds before change: "
            f"{target_info_before}"
        )
        print("Continuing because --allow-target-exists was given.")

    dps = make_dps(args, current_addr)
    cmd = f"N,{new_addr}"

    try:
        result = dps.send_command(cmd)
        if result.reply_bytes:
            print(f"Reply to {cmd}: {result.reply_text}")
        else:
            print(f"No reply received for {cmd} (device may accept silently).")
    except Exception as exc:
        print(f"Failed to send {cmd} to address {current_addr}: {exc}")
        return 1

    if args.settle_seconds > 0:
        time.sleep(args.settle_seconds)

    current_ok_after, current_info_after = probe_ident(args, current_addr)
    target_ok_after, target_info_after = probe_ident(args, new_addr)

    if target_ok_after and not current_ok_after:
        print(f"Post-check OK: target address {new_addr} responds: {target_info_after}")
        print(f"Post-check OK: current address {current_addr} no longer responds.")
        print("Address change successful.")
        return 0

    print("Address change could not be verified safely.")
    print(
        f"Post-check current {current_addr}: "
        f"{'RESPONDS' if current_ok_after else 'NO RESPONSE'} - {current_info_after}"
    )
    print(
        f"Post-check target  {new_addr}: "
        f"{'RESPONDS' if target_ok_after else 'NO RESPONSE'} - {target_info_after}"
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return change_address(args)


if __name__ == "__main__":
    raise SystemExit(main())
