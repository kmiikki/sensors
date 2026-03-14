from __future__ import annotations

import argparse
from typing import Tuple

from dpslogger.protocol import DPSConfig
from dpslogger.transport import SerialTransportConfig
from dpslogger import profiles


def add_transport_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--port",
        help="Serial port (e.g. /dev/ttyLOG or /dev/ttyUSB0)",
    )
    parser.add_argument(
        "-b",
        "--baud",
        type=int,
        help="Baud rate (default from profile)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="Serial read timeout in seconds",
    )
    parser.add_argument(
        "--write-sleep",
        type=float,
        help="Delay after command write in seconds",
    )
    parser.add_argument(
        "--eol",
        choices=["cr", "crlf"],
        help="Command line ending",
    )
    parser.add_argument(
        "--hex",
        action="store_true",
        help="Show raw hex dump of traffic",
    )
    parser.add_argument(
        "--no-reset-input",
        action="store_true",
        help="Do not clear input buffer before command transactions",
    )


def add_device_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-a",
        "--addr",
        type=int,
        help="Device address (RS485)",
    )
    parser.add_argument(
        "--profile",
        choices=["real", "sim"],
        default="real",
        help="Device profile (default: real)",
    )


def add_logging_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-dir",
        default="data",
        help="Base directory for output files",
    )
    parser.add_argument(
        "--session-subdir",
        action="store_true",
        help="Create timestamped subdirectory for this session",
    )
    parser.add_argument(
        "--prefix",
        default="dps",
        help="Filename prefix",
    )


def build_base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    add_transport_args(parser)
    add_device_args(parser)
    return parser


def get_profile_configs(profile: str, port: str | None) -> Tuple[SerialTransportConfig, DPSConfig]:
    if profile == "real":
        return profiles.real_sensor(port)
    if profile == "sim":
        return profiles.simulator(port)
    raise ValueError(f"Unknown profile: {profile}")


def build_configs(args: argparse.Namespace) -> Tuple[SerialTransportConfig, DPSConfig]:
    transport_cfg, dps_cfg = get_profile_configs(args.profile, args.port)

    if getattr(args, "baud", None) is not None:
        transport_cfg.baud = args.baud
    if getattr(args, "timeout", None) is not None:
        transport_cfg.timeout_s = args.timeout
    if getattr(args, "write_sleep", None) is not None:
        transport_cfg.write_sleep_s = args.write_sleep
    if getattr(args, "eol", None) is not None:
        transport_cfg.eol = args.eol
    if getattr(args, "no_reset_input", False):
        transport_cfg.reset_input_before_cmd = False
    if getattr(args, "addr", None) is not None:
        dps_cfg.address = args.addr

    return transport_cfg, dps_cfg
