#!/usr/bin/env python3
"""Query or change DPS pressure unit."""

from __future__ import annotations

import argparse
import sys
import time

from dpslogger.cli.common import add_device_args, add_transport_args, build_configs
from dpslogger.protocol import DPS8000
from dpslogger.transport import SerialTransport

VERIFY_DELAY_S = 0.2

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query or change DPS unit")

    add_transport_args(parser)
    add_device_args(parser)

    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "-u",
        "--unit-code",
        dest="unit_code",
        type=int,
        help="Target unit code (0..5)",
    )
    group.add_argument(
        "-n",
        "--unit-name",
        dest="unit_name",
        type=str,
        help="Target unit name (mbar, Pa, kPa, MPa, hPa, bar)",
    )

    return parser.parse_args()


def set_proto_address(proto: DPS8000, addr: int) -> None:
    if not (0 <= addr <= 32):
        raise ValueError("Address must be in range 0..32")

    if addr == 0:
        proto.set_address(None)
    else:
        proto.set_address(addr)


def query_current_unit(proto: DPS8000, addr: int) -> tuple[int, str]:
    old_addr = proto.cfg.address
    try:
        set_proto_address(proto, addr)
        code = proto.query_unit_code()
        name = proto.query_unit()
        return code, name
    finally:
        proto.set_address(old_addr)


def set_unit_code(proto: DPS8000, addr: int, code: int) -> None:
    if code not in UNIT_CODE_TO_NAME:
        allowed = ", ".join(str(k) for k in UNIT_CODE_TO_NAME)
        raise ValueError(f"Unsupported unit code {code}. Allowed: {allowed}")

    old_addr = proto.cfg.address
    try:
        set_proto_address(proto, addr)
        proto.send_command(f"U,{code}")
    finally:
        proto.set_address(old_addr)


def resolve_unit_code_from_name(name: str) -> int:
    key = name.strip().lower()
    try:
        return UNIT_NAME_TO_CODE[key]
    except KeyError as exc:
        allowed = ", ".join(UNIT_CODE_TO_NAME.values())
        raise ValueError(f"Unsupported unit name {name!r}. Allowed: {allowed}") from exc


def print_unit_menu(current_code: int, current_name: str) -> None:
    print(f"Current unit: {current_code} = {current_name}")
    print()
    print("Available units:")
    for code, name in UNIT_CODE_TO_NAME.items():
        marker = " (current)" if code == current_code else ""
        print(f"  {code}: {name}{marker}")


def prompt_unit_code() -> int:
    while True:
        raw = input("Select new unit code (0-5, Enter to cancel): ").strip()

        if raw == "":
            raise KeyboardInterrupt

        try:
            code = int(raw)
        except ValueError:
            print("Invalid selection. Enter an integer 0-5.")
            continue

        if code not in UNIT_CODE_TO_NAME:
            print("Invalid selection. Allowed values are 0-5.")
            continue

        return code


def verify_and_report(
    proto: DPS8000,
    addr: int,
    requested_code: int,
    requested_name: str,
) -> int:
    time.sleep(VERIFY_DELAY_S)
    new_code, new_name = query_current_unit(proto, addr)

    print(f"New unit: {new_code} = {new_name}")

    if new_code != requested_code:
        print(
            "WARNING: Queried unit code differs from requested unit code: "
            f"requested {requested_code} ({requested_name}), got {new_code} ({new_name})"
        )
        return 1

    normalized_requested = requested_name.strip().lower()
    normalized_actual = new_name.strip().lower()
    if normalized_actual != normalized_requested:
        print(
            "NOTE: Unit code matches, but queried unit name differs from requested name: "
            f"requested {requested_name}, got {new_name}"
        )

    return 0


def main() -> int:
    args = parse_args()

    if args.addr is None:
        print("ERROR: --addr is required", file=sys.stderr)
        return 2

    if not (0 <= args.addr <= 32):
        print("ERROR: address must be 0..32", file=sys.stderr)
        return 2

    if args.unit_code is not None and args.unit_code not in UNIT_CODE_TO_NAME:
        print("ERROR: unit code must be 0..5", file=sys.stderr)
        return 2

    try:
        transport_cfg, dps_cfg = build_configs(args)
        transport_cfg.eol = "cr"

        transport = SerialTransport(transport_cfg)
        proto = DPS8000(transport, dps_cfg)

        transport.open()
        try:
            current_code, current_name = query_current_unit(proto, args.addr)

            if args.unit_code is None and args.unit_name is None:
                print("Interactive mode")
                print_unit_menu(current_code, current_name)
                print()

                try:
                    target_code = prompt_unit_code()
                except KeyboardInterrupt:
                    print("Cancelled.")
                    return 0
            else:
                print(f"Current unit: {current_code} = {current_name}")

                if args.unit_code is not None:
                    target_code = args.unit_code
                else:
                    target_code = resolve_unit_code_from_name(args.unit_name)

            target_name = UNIT_CODE_TO_NAME[target_code]

            if target_code == current_code:
                print(f"Selected unit is already active: {target_code} = {target_name}")
                return 0

            print(f"Setting unit to {target_code} = {target_name}")
            set_unit_code(proto, args.addr, target_code)

            return verify_and_report(proto, args.addr, target_code, target_name)

        finally:
            transport.close()

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())