"""Set or change DPS sensor address."""

from __future__ import annotations

import argparse
import sys
import time

from dpslogger.cli.common import (
    add_device_args,
    add_transport_args,
    build_configs,
)
from dpslogger.protocol import DPS8000
from dpslogger.transport import SerialTransport


SCAN_MIN = 1
SCAN_MAX = 32
VERIFY_DELAY_S = 0.2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set DPS device address")

    add_transport_args(parser)
    add_device_args(parser)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--from",
        dest="source_addr",
        type=int,
        help="Current DPS address",
    )
    group.add_argument(
        "--scan",
        action="store_true",
        help="Scan source address automatically",
    )

    parser.add_argument(
        "--to",
        dest="target_addr",
        required=True,
        type=int,
        help="New DPS address",
    )

    return parser.parse_args()


def query_address(proto: DPS8000, addr: int | None) -> int | None:
    """Query DPS address in direct or addressed mode."""
    old_addr = proto.cfg.address

    try:
        if addr == 0:
            proto.set_address(None)
        else:
            proto.set_address(addr)

        return proto.query_address()

    except Exception:
        return None

    finally:
        proto.set_address(old_addr)


def scan_for_single_device(proto: DPS8000) -> int:
    """Find exactly one DPS device."""
    print("Scanning for DPS device...")

    print("  trying direct mode")
    addr = query_address(proto, 0)
    if addr is not None:
        print(f"  found device in direct mode -> address {addr}")
        return addr

    found: list[int] = []

    for candidate in range(SCAN_MIN, SCAN_MAX + 1):
        print(f"  trying address {candidate:02d}")

        detected = query_address(proto, candidate)
        if detected is not None:
            print(f"  found response from address {detected}")
            found.append(detected)

    unique_found = sorted(set(found))

    if not unique_found:
        raise RuntimeError("No DPS device found")

    if len(unique_found) > 1:
        raise RuntimeError(
            f"Multiple DPS devices found: {unique_found}. "
            "Use --from explicitly."
        )

    return unique_found[0]


def ensure_target_free(proto: DPS8000, target_addr: int) -> None:
    """Verify that target address is unused."""
    detected = query_address(proto, target_addr)

    if detected is None:
        return

    if detected == target_addr:
        raise RuntimeError(f"Target address {target_addr} is already in use")

    raise RuntimeError(
        f"Unexpected reply while probing target address {target_addr}: "
        f"device responded as address {detected}"
    )


def verify_new_address(
    proto: DPS8000,
    target_addr: int,
    retries: int = 3,
) -> bool:
    """Verify normal address change."""
    for _ in range(retries):
        time.sleep(VERIFY_DELAY_S)

        detected = query_address(proto, target_addr)
        if detected == target_addr:
            return True

    return False


def verify_after_zero_to_nonzero(
    proto: DPS8000,
    target_addr: int,
    retries: int = 5,
) -> bool:
    """
    Verify address change from direct-mode address 0 to a normal address.

    Some DPS devices behave oddly when leaving direct mode, so try both:
    - addressed query to new address
    - direct query again
    """
    for _ in range(retries):
        time.sleep(VERIFY_DELAY_S)

        detected_target = query_address(proto, target_addr)
        if detected_target == target_addr:
            return True

        detected_direct = query_address(proto, 0)
        if detected_direct == target_addr:
            return True

    return False


def main() -> int:
    args = parse_args()

    if not (0 <= args.target_addr <= 32):
        print("ERROR: target address must be 0..32", file=sys.stderr)
        return 2

    try:
        transport_cfg, dps_cfg = build_configs(args)
        transport_cfg.eol = "cr"

        transport = SerialTransport(transport_cfg)
        proto = DPS8000(transport, dps_cfg)

        transport.open()
        try:
            if args.scan:
                source_addr = scan_for_single_device(proto)
            else:
                source_addr = args.source_addr

                detected = query_address(proto, source_addr)
                if detected is None:
                    raise RuntimeError(
                        f"No device responding at address {source_addr}"
                    )

                if detected != source_addr:
                    raise RuntimeError(
                        f"Source probe mismatch: asked {source_addr}, "
                        f"got {detected}"
                    )

            print(f"Source address: {source_addr}")
            print(f"Target address: {args.target_addr}")

            if source_addr == args.target_addr:
                print("Source and target are already the same")
                return 0

            ensure_target_free(proto, args.target_addr)

            print(f"Setting address {source_addr} -> {args.target_addr}")

            old_addr = proto.cfg.address
            try:
                if source_addr == 0:
                    proto.set_address(None)
                else:
                    proto.set_address(source_addr)

                # Silent set command: may succeed without reply.
                proto.send_command(f"N,{args.target_addr}")

            finally:
                proto.set_address(old_addr)

            if source_addr == 0 and args.target_addr != 0:
                ok = verify_after_zero_to_nonzero(proto, args.target_addr)
            else:
                ok = verify_new_address(proto, args.target_addr)

            if not ok:
                raise RuntimeError("Address change could not be verified")

            print(f"Address successfully changed to {args.target_addr}")
            return 0

        finally:
            transport.close()

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
