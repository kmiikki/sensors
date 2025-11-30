#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
import glob
import argparse
import subprocess
from dataclasses import dataclass
from typing import Dict, Optional, List

RULES_PATH = "/etc/udev/rules.d/99-dps-logger.rules"

VENDOR_FTDI = "0403"
PRODUCT_FT232R = "6001"


# ============================================================
# Data structures & helpers
# ============================================================

@dataclass
class SerialDevice:
    devnode: str
    vendor_id: str
    product_id: str
    serial_short: str


def run(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def get_udev_props(devnode: str) -> Dict[str, str]:
    props: Dict[str, str] = {}
    try:
        out = run(["udevadm", "info", "-n", devnode, "-q", "property"])
    except subprocess.CalledProcessError:
        return props

    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    return props


def scan_ftdi_devices() -> Dict[str, SerialDevice]:
    """
    Scan /dev/ttyUSB* and return a mapping devnode -> SerialDevice
    for FTDI FT232R devices (0403:6001).
    """
    devices: Dict[str, SerialDevice] = {}
    for dev in sorted(glob.glob("/dev/ttyUSB*")):
        props = get_udev_props(dev)
        vendor = props.get("ID_VENDOR_ID", "").lower()
        product = props.get("ID_MODEL_ID", "").lower()
        serial_short = props.get("ID_SERIAL_SHORT") or props.get("ID_SERIAL")
        if vendor == VENDOR_FTDI and product == PRODUCT_FT232R and serial_short:
            devices[dev] = SerialDevice(
                devnode=dev,
                vendor_id=vendor,
                product_id=product,
                serial_short=serial_short
            )
    return devices


def print_devices(title: str, devices: Dict[str, SerialDevice]) -> None:
    print(f"\n{title}:")
    if not devices:
        print("  (none)")
        return
    for d in devices.values():
        print(f"  {d.devnode} vendor={d.vendor_id} product={d.product_id} serial={d.serial_short}")


def detect_new_device(
    baseline: Dict[str, SerialDevice],
    prompt: str,
    timeout_s: float = 0.3
) -> SerialDevice:
    """
    Ask user to plug a device, then detect exactly one new FTDI device
    compared to baseline.
    """
    print()
    print(prompt)
    input("Press Enter when the device is connected... ")
    if timeout_s > 0:
        time.sleep(timeout_s)

    now = scan_ftdi_devices()
    added = set(now.keys()) - set(baseline.keys())

    if len(added) == 0:
        raise RuntimeError("No new FTDI device detected.")
    if len(added) > 1:
        raise RuntimeError("More than one new FTDI device detected—plug only one.")

    devnode = next(iter(added))
    return now[devnode]


def make_rules_content(log_dev: SerialDevice, sim_dev: Optional[SerialDevice]) -> str:
    """
    Generate udev rules that bind roles to (vendor, product, serial).
    """
    lines: List[str] = []

    # LOGGER
    lines.append(
        '# FTDI: main logger port (ttyLOG)\n'
        'SUBSYSTEM=="tty", \\\n'
        f'  ATTRS{{idVendor}}=="{log_dev.vendor_id}", '
        f'ATTRS{{idProduct}}=="{log_dev.product_id}", '
        f'ATTRS{{serial}}=="{log_dev.serial_short}", \\\n'
        '  SYMLINK+="ttyLOG"\n'
    )

    # SIMULATOR
    if sim_dev is not None:
        lines.append(
            '\n# FTDI: simulator port (ttySIM)\n'
            'SUBSYSTEM=="tty", \\\n'
            f'  ATTRS{{idVendor}}=="{sim_dev.vendor_id}", '
            f'ATTRS{{idProduct}}=="{sim_dev.product_id}", '
            f'ATTRS{{serial}}=="{sim_dev.serial_short}", \\\n'
            '  SYMLINK+="ttySIM"\n'
        )

    return "\n".join(lines)


def get_existing_logger_from_udev(baseline: Dict[str, SerialDevice]) -> Optional[SerialDevice]:
    """
    If /dev/ttyLOG exists and maps (via udev) to one of the FTDI devices
    in the current baseline, return that SerialDevice. Otherwise None.
    """
    if not os.path.exists("/dev/ttyLOG"):
        return None

    props = get_udev_props("/dev/ttyLOG")
    if not props:
        return None

    vendor = props.get("ID_VENDOR_ID", "").lower()
    product = props.get("ID_MODEL_ID", "").lower()
    serial_short = props.get("ID_SERIAL_SHORT") or props.get("ID_SERIAL")

    if not serial_short or vendor != VENDOR_FTDI or product != PRODUCT_FT232R:
        return None

    for dev in baseline.values():
        if dev.serial_short == serial_short:
            return dev

    return None


# ============================================================
# Modes: reset + wizard
# ============================================================

def reset_rules() -> None:
    """
    Remove udev rules and reload udev.
    """
    if os.path.exists(RULES_PATH):
        print(f"Removing {RULES_PATH} ...")
        os.remove(RULES_PATH)
    else:
        print("No rules file to remove.")

    print("Reloading udev rules...")
    subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
    subprocess.run(["udevadm", "trigger"], check=True)

    print("\nReset complete. No ttyLOG or ttySIM will be created until the wizard is run again.")


def wizard() -> int:
    if os.geteuid() != 0:
        print("This script must be run as root (sudo).", file=sys.stderr)
        return 1

    print("DPS Logger Udev Setup Wizard")
    print("============================")

    # 1) Baseline scan
    baseline = scan_ftdi_devices()
    print_devices("Initial FTDI devices", baseline)

    logger_dev: Optional[SerialDevice] = None

    # 1a) Try to reuse an existing ttyLOG mapping, if present
    existing_logger = get_existing_logger_from_udev(baseline)
    if existing_logger is not None:
        print("\nExisting ttyLOG detected.")
        print(f"  /dev/ttyLOG -> {existing_logger.devnode}, serial={existing_logger.serial_short}")
        reuse_ans = input("Reuse this device as LOGGER? [Y/n]: ").strip().lower()
        if reuse_ans in ("", "y", "yes"):
            logger_dev = existing_logger
        else:
            print("Not reusing existing LOGGER. You can run with --reset if you want a clean setup.")
            return 1

    # 1b) No existing ttyLOG: decide LOGGER based on current baseline
    if logger_dev is None:
        if len(baseline) == 0:
            # No FTDI devices yet -> ask user to plug logger
            try:
                logger_dev = detect_new_device(
                    baseline,
                    "STEP 1: Plug in the LOGGER RS-485 adapter (main logging device).",
                )
            except RuntimeError as e:
                print(f"ERROR: {e}")
                return 1

        elif len(baseline) == 1:
            # One FTDI present -> offer to use it as logger, or pick a new one
            only_dev = next(iter(baseline.values()))
            print("\nOne FTDI device is already present.")
            reuse_ans = input(
                f"Use existing device {only_dev.devnode} (serial={only_dev.serial_short}) as LOGGER? [Y/n]: "
            ).strip().lower()

            if reuse_ans in ("", "y", "yes"):
                logger_dev = only_dev
            else:
                # user wants a different device as LOGGER
                try:
                    logger_dev = detect_new_device(
                        baseline,
                        "STEP 1: Plug in the NEW LOGGER RS-485 adapter (main logging device).",
                    )
                except RuntimeError as e:
                    print(f"ERROR: {e}")
                    return 1

        else:
            # More than one FTDI present and no ttyLOG mapping -> ambiguous
            print("\nERROR: Multiple FTDI devices are already connected and no existing ttyLOG was found.")
            print("Please either:")
            print("  - unplug all FTDI adapters and run the wizard again, OR")
            print("  - leave only the intended LOGGER adapter connected and rerun.")
            return 1

    # At this point logger_dev must be set
    print("\nDetected LOGGER:")
    print(f"  {logger_dev.devnode}, serial={logger_dev.serial_short}")

    # 2) Optional SIM device
    sim_dev: Optional[SerialDevice] = None
    ans = input("\nDo you want to add a SIMULATOR device (ttySIM)? [y/N]: ").strip().lower()
    if ans in ("y", "yes"):
        baseline2 = scan_ftdi_devices()

        # Candidates for SIM are FTDI devices that are *not* the logger
        sim_candidates = [
            dev for dev in baseline2.values()
            if dev.serial_short != logger_dev.serial_short
        ]

        if len(sim_candidates) == 1:
            # Exactly one other FTDI present -> offer to reuse it as SIM
            candidate = sim_candidates[0]
            print("\nOne additional FTDI device is already present.")
            reuse_sim = input(
                f"Use existing device {candidate.devnode} (serial={candidate.serial_short}) as SIMULATOR? [Y/n]: "
            ).strip().lower()
            if reuse_sim in ("", "y", "yes"):
                # Reuse current SIM as-is
                sim_dev = candidate
            else:
                # User wants a *different* SIM adapter:
                # tell them to unplug the current candidate and plug a new one.
                print("\nOK, we will select a different SIM adapter.")
                print(f"Please now UNPLUG {candidate.devnode} (serial={candidate.serial_short}),")
                print("then plug in the NEW SIMULATOR RS-485 adapter.")
                print("When the new adapter is connected, press Enter.")
                input()

                # Build a new baseline *without* the old candidate
                baseline3 = {
                    dev.devnode: dev
                    for dev in scan_ftdi_devices().values()
                    if dev.serial_short != candidate.serial_short
                }

                try:
                    sim_dev = detect_new_device(
                        baseline3,
                        "STEP 2b: Detecting the NEW SIMULATOR RS-485 adapter...",
                    )
                except RuntimeError as e:
                    print(f"ERROR: {e}")
                    return 1

        elif len(sim_candidates) == 0:
            # No other FTDI present yet -> ask user to plug SIM and detect new device
            try:
                sim_dev = detect_new_device(
                    baseline2,
                    "STEP 2: Plug in the SIMULATOR RS-485 adapter.",
                )
            except RuntimeError as e:
                print(f"ERROR: {e}")
                return 1

        else:
            # More than one non-logger FTDI present -> ambiguous
            print("\nERROR: Multiple FTDI devices (besides LOGGER) are already connected.")
            print("Please either:")
            print("  - unplug extra FTDI adapters and run the wizard again, OR")
            print("  - leave only the intended LOGGER and one SIMULATOR connected.")
            return 1

        if sim_dev.serial_short == logger_dev.serial_short:
            print("ERROR: Same adapter detected for both LOGGER and SIM. Use two distinct FTDI devices.")
            return 1

        print("\nDetected SIMULATOR:")
        print(f"  {sim_dev.devnode}, serial={sim_dev.serial_short}")

    # 3) Summary
    print("\nSummary:")
    print(f"  LOGGER   → ttyLOG → serial={logger_dev.serial_short}")
    if sim_dev:
        print(f"  SIMULATOR→ ttySIM → serial={sim_dev.serial_short}")
    else:
        print("  SIMULATOR→ (none)")

    confirm = input("\nApply these settings? [y/N]: ").strip().lower()
    if confirm not in ("y", "yes"):
        print("Aborted.")
        return 0

    # 4) Write udev rules
    rules = make_rules_content(logger_dev, sim_dev)
    print(f"\nWriting rules to {RULES_PATH} ...")
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        f.write(rules)

    subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
    subprocess.run(["udevadm", "trigger"], check=True)

    # 5) Check symlinks with wait-loop
    print("\nChecking resulting device symlinks (waiting for udev to settle):")
    paths = [("/dev/ttyLOG", logger_dev), ("/dev/ttySIM", sim_dev)]

    for path, devinfo in paths:
        if devinfo is None:
            if "SIM" in path:
                print(f"{path}: (SIM not configured)")
            continue

        deadline = time.time() + 2.0
        while time.time() < deadline:
            if os.path.exists(path):
                break
            time.sleep(0.10)

        if os.path.exists(path):
            print(run(["ls", "-l", path]))
        else:
            print(f"[WARN] {path} did not appear after 2 seconds.")
            print("       Device may be unplugged or udev may need manual trigger:")
            print(f"       sudo udevadm trigger /sys/class/tty/{os.path.basename(devinfo.devnode)}")

    print("\nDone.")
    return 0


# ============================================================
# Entry point
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="setup_dps_logger_udev.py",
        description=(
            "Interactive setup tool for assigning FTDI RS-485 USB adapters "
            "to ttyLOG (logger) and ttySIM (simulator) via udev rules."
        )
    )
    parser.add_argument(
        "-r", "--reset",
        action="store_true",
        help="Remove ttyLOG/ttySIM udev rules and reset to a clean state."
    )
    parser.add_argument(
        "-w", "--wizard",
        action="store_true",
        help="Run the interactive wizard (default if no flags are given)."
    )

    args = parser.parse_args()

    if args.reset:
        reset_rules()
        return 0

    # default mode is wizard
    return wizard()


if __name__ == "__main__":
    raise SystemExit(main())
