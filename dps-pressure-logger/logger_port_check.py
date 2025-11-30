#!/usr/bin/env python3
"""
Simple diagnostic tool to verify that the logger serial port is usable.

By default it checks /dev/ttyLOG:
  - prints basic file information (owner, group, permissions)
  - checks read/write access for the current user
  - tries to open the port using pyserial

If the tested port is /dev/ttyLOG, the script will also (optionally) inspect
/dev/ttySIM if it exists. The ttySIM check is informational only and does NOT
affect the exit code (intended for CI use where only ttyLOG must succeed).

Exit codes:
  0 = success (port opened successfully)
  1 = generic error (e.g. missing port, no permissions, pyserial not installed)
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from typing import Optional

import pwd
import grp


def format_mode(mode: int) -> str:
    """Return a human-readable rwx string for the file mode."""
    return stat.filemode(mode)


def get_username(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def get_groupname(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def print_file_info(path: str) -> None:
    """Print owner, group and permissions for a device node."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        print(f"[ERROR] Device node {path} does not exist.")
        return

    owner = get_username(st.st_uid)
    group = get_groupname(st.st_gid)
    mode_str = format_mode(st.st_mode)

    print(f"Device node: {path}")
    print(f"  Owner   : {owner} (uid={st.st_uid})")
    print(f"  Group   : {group} (gid={st.st_gid})")
    print(f"  Mode    : {mode_str}")


def check_access(path: str) -> bool:
    """Check read/write access for the current user."""
    can_read = os.access(path, os.R_OK)
    can_write = os.access(path, os.W_OK)

    print("\nAccess check for current user:")
    print(f"  Read   : {'YES' if can_read else 'NO'}")
    print(f"  Write  : {'YES' if can_write else 'NO'}")

    if not (can_read and can_write):
        print("  -> You may need to adjust group membership or udev permissions.")
        return False

    return True


def try_open_serial(port: str, baudrate: int, timeout: float) -> bool:
    """Try to open the serial port using pyserial."""
    try:
        import serial  # type: ignore
    except ImportError:
        print("\n[ERROR] Python package 'pyserial' is not installed in this environment.")
        print("        Install it, for example:")
        print("          micromamba activate logger")
        print("          micromamba install pyserial")
        return False

    print("\nAttempting to open serial port:")
    print(f"  Port    : {port}")
    print(f"  Baudrate: {baudrate}")
    print(f"  Timeout : {timeout} s")

    try:
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
    except serial.SerialException as e:  # type: ignore[attr-defined]
        print(f"[ERROR] Failed to open serial port {port}: {e}")
        return False
    except OSError as e:
        print(f"[ERROR] OS error while opening {port}: {e}")
        return False

    print(f"[OK] Serial port {port} opened successfully.")
    print("Port parameters:")
    print(f"  Name    : {ser.name}")
    print(f"  Baudrate: {ser.baudrate}")
    print(f"  Bytesize: {ser.bytesize}")
    print(f"  Parity  : {ser.parity}")
    print(f"  Stopbits: {ser.stopbits}")

    ser.close()
    print("[OK] Serial port closed cleanly.")
    return True


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="logger_port_check.py",
        description=(
            "Check that the logger serial port is available and can be opened "
            "by the current user."
        ),
    )
    parser.add_argument(
        "-p",
        "--port",
        default="/dev/ttyLOG",
        help="Serial device to test (default: /dev/ttyLOG).",
    )
    parser.add_argument(
        "-b",
        "--baudrate",
        type=int,
        default=9600,
        help="Baud rate used for the test open (default: 9600).",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=1.0,
        help="Read timeout in seconds for the test open (default: 1.0).",
    )

    args = parser.parse_args(argv)

    port = args.port

    print(f"=== Logger serial port diagnostic ===")
    print(f"Target port: {port}")

    if not os.path.exists(port):
        print(f"\n[ERROR] Device {port} does not exist.")
        # Even if logger is missing, we may still show SIM info later,
        # but for CI this is a hard failure.
        # Optional SIM check will still not change the exit code.
        sim_status_done = _optional_sim_check(args, main_failed=True)
        return 1

    print_file_info(port)
    ok_access = check_access(port)

    if not ok_access:
        # Still try to open the port, in case ACLs or capabilities allow it
        print("\n[WARN] Access checks failed, but trying to open the port anyway...")
    else:
        print("\nAccess checks look OK.")

    ok_open = try_open_serial(port, baudrate=args.baudrate, timeout=args.timeout)

    if ok_open:
        print("\n[RESULT] SUCCESS: Serial port is usable by the current user.")
        exit_code = 0
    else:
        print("\n[RESULT] FAILURE: Serial port could not be opened successfully.")
        exit_code = 1

    # Optional: if main port is /dev/ttyLOG, also show ttySIM status
    _optional_sim_check(args, main_failed=(exit_code != 0))

    return exit_code


def _optional_sim_check(args: argparse.Namespace, main_failed: bool) -> None:
    """
    Optionally check /dev/ttySIM when the main port is /dev/ttyLOG.

    This is purely informational and MUST NOT change the overall exit code,
    so that CI can rely only on the ttyLOG result.
    """
    # Only do the SIM check if user did not explicitly override the port
    if args.port != "/dev/ttyLOG":
        return

    sim_path = "/dev/ttySIM"
    print("\n=== Simulator serial port (ttySIM) diagnostic (informational) ===")

    if not os.path.exists(sim_path):
        print(f"[INFO] {sim_path} does not exist (simulator not connected/configured).")
        return

    print_file_info(sim_path)
    sim_access = check_access(sim_path)

    if not sim_access:
        print("\n[INFO] Access checks for ttySIM failed.")
        print("       This does not affect the main result (ttyLOG).")
        print("       Still attempting to open the port for diagnostics...")
    else:
        print("\nAccess checks for ttySIM look OK (informational).")

    sim_ok = try_open_serial(sim_path, baudrate=args.baudrate, timeout=args.timeout)

    if sim_ok:
        print("\n[INFO] Simulator port appears usable.")
    else:
        print("\n[INFO] Simulator port could not be opened successfully.")
        print("       This does NOT change the overall result for ttyLOG.")


if __name__ == "__main__":
    raise SystemExit(main())
