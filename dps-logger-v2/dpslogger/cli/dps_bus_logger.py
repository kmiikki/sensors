from __future__ import annotations

import argparse
import json
import signal
from datetime import datetime
from pathlib import Path
from time import perf_counter, sleep
from typing import Dict

from dpslogger.cli.common import build_configs
from dpslogger.csv_writer import CSVRotateConfig, CSVRotatingWriter
from dpslogger.protocol import DPS8000
from dpslogger.transport import SerialTransport


DEFAULT_INTERVAL = 1.0
DEFAULT_PREFIX = "dps"
DEFAULT_BASE_DIR = "."
DEFAULT_PORT = "/dev/ttyLOG"
DEFAULT_ADDRESS = 1

PROGRAM_NAME = "dpslogger"
PROGRAM_VERSION = "2.0"

disable_halt = False
stop_requested = False
_sig_installed = False


def get_sec_fractions(resolution: int = 5) -> float:
    now = datetime.now()
    return round(now.timestamp() % 1, resolution)


def _sig_handler(signum, frame) -> None:
    global disable_halt, stop_requested
    stop_requested = True

    if disable_halt:
        return

    print("\nTermination requested (Ctrl+C). Exiting...")
    raise SystemExit(0)


def install_signal_handlers_once() -> None:
    global _sig_installed
    if _sig_installed:
        return

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    signal.siginterrupt(signal.SIGINT, False)
    signal.siginterrupt(signal.SIGTERM, False)

    _sig_installed = True


def parse_addresses(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value < 0:
            raise argparse.ArgumentTypeError("Address must be >= 0")
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError("At least one address is required")
    return values


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid float value: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be > 0")
    return parsed


def non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid float value: {value}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be >= 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Multi-sensor DPS RS-485 bus logger.")
    parser.add_argument("--profile", default="real", help="Profile name")
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        help=f"Serial port (default: {DEFAULT_PORT})",
    )
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--timeout", type=float, default=1.0)

    parser.add_argument(
        "--addr",
        type=int,
        default=None,
        help=f"Single address shortcut (default: {DEFAULT_ADDRESS} if --addresses is not given)",
    )
    parser.add_argument(
        "--addresses",
        type=parse_addresses,
        default=None,
        help=f"Comma-separated address list (default: {DEFAULT_ADDRESS})",
    )

    parser.add_argument(
        "--interval",
        type=positive_float,
        default=DEFAULT_INTERVAL,
        help="Poll interval per full bus cycle in seconds",
    )
    parser.add_argument(
        "--duration",
        "--time",
        dest="duration",
        type=non_negative_float,
        default=None,
        help="Stop automatically after this many seconds from first sample",
    )
    parser.add_argument(
        "--base-dir",
        default=DEFAULT_BASE_DIR,
        help="Base output directory",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help="Filename prefix before _addrNN_YYYYMMDD.csv",
    )
    parser.add_argument(
        "--session-subdir",
        action="store_true",
        help="Create one session subdirectory for this run",
    )
    parser.add_argument(
        "--flush-every",
        type=int,
        default=1,
        help="Flush CSV files every N rows",
    )
    parser.add_argument(
        "--print-rows",
        action="store_true",
        help="Print each logged row to stdout",
    )
    parser.add_argument(
        "-p",
        "--pretty",
        action="store_true",
        help="Pretty terminal output (implies --print-rows)",
    )
    return parser


def _headers() -> list[str]:
    return [
        "ts_iso",
        "t_epoch",
        "t_rel",
        "cycle",
        "addr",
        "pressure",
        "unit",
        "latency_s",
        "source",
        "status",
    ]


def _pretty_header() -> str:
    return "time,t_rel,cycle,addr,pressure,unit,source,status"


def _format_pretty_row(row: dict[str, object]) -> str:
    ts_iso = str(row.get("ts_iso", ""))
    ts_human = ts_iso[:19].replace("T", " ")

    t_rel_raw = row.get("t_rel", "")
    try:
        t_rel = f"{float(t_rel_raw):.1f}"
    except Exception:
        t_rel = ""

    return ",".join(
        [
            ts_human,
            t_rel,
            str(row.get("cycle", "")),
            str(row.get("addr", "")),
            str(row.get("pressure", "")),
            str(row.get("unit", "")),
            str(row.get("source", "")),
            str(row.get("status", "")),
        ]
    )


def make_session_id() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _resolve_output_paths(base_dir: Path, session_id: str, use_subdir: bool) -> tuple[Path, str | None]:
    """
    Return:
        out_dir: directory where files are written
        file_suffix: None if filenames should not include session_id,
                     otherwise f"_{session_id}"
    """
    base_dir.mkdir(parents=True, exist_ok=True)

    if use_subdir:
        out_dir = base_dir / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir, None

    return base_dir, f"_{session_id}"


def _resolve_addresses(args: argparse.Namespace) -> list[int]:
    if args.addresses is not None:
        return args.addresses
    if args.addr is not None:
        if args.addr < 0:
            raise argparse.ArgumentTypeError("Address must be >= 0")
        return [args.addr]
    return [DEFAULT_ADDRESS]


def _build_dps_objects(args: argparse.Namespace) -> tuple[SerialTransport, Dict[int, DPS8000]]:
    temp_args = argparse.Namespace(**vars(args))
    temp_args.addr = args.addresses[0]
    transport_cfg, _ = build_configs(temp_args)
    transport = SerialTransport(transport_cfg)

    dps_map: Dict[int, DPS8000] = {}
    for addr in args.addresses:
        temp_args = argparse.Namespace(**vars(args))
        temp_args.addr = addr
        _, dps_cfg = build_configs(temp_args)
        dps_map[addr] = DPS8000(transport, dps_cfg)

    return transport, dps_map


def _make_writer(
    out_dir: Path,
    prefix: str,
    addr: int,
    flush_every: int,
    file_suffix: str | None,
) -> CSVRotatingWriter:
    if file_suffix is None:
        writer_prefix = f"{prefix}_addr{addr:02d}"
    else:
        writer_prefix = f"{prefix}_addr{addr:02d}{file_suffix}"

    return CSVRotatingWriter(
        CSVRotateConfig(
            prefix=writer_prefix,
            dirpath=out_dir,
            headers=_headers(),
            flush_every=flush_every,
        )
    )


def write_run_metadata(
    out_dir: Path,
    args: argparse.Namespace,
    session_id: str,
    file_suffix: str | None,
) -> Path:
    ts = datetime.now().astimezone()

    meta = {
        "program": PROGRAM_NAME,
        "version": PROGRAM_VERSION,
        "started_at": ts.isoformat(),
        "session_id": session_id,
        "transport": {
            "port": args.port,
            "baudrate": args.baudrate,
            "timeout": args.timeout,
        },
        "sensors": {
            "addresses": args.addresses,
            "profile": args.profile,
        },
        "logging": {
            "interval_s": args.interval,
            "duration_s": args.duration,
            "base_dir": str(args.base_dir),
            "prefix": args.prefix,
            "flush_every": args.flush_every,
            "session_subdir": args.session_subdir,
        },
        "csv_schema": _headers(),
    }

    if file_suffix is None:
        filename = "dps_run.json"
    else:
        filename = f"dps_run{file_suffix}.json"

    path = out_dir / filename
    with path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return path


def _read_sample(dps: DPS8000, addr: int, t0_epoch: float | None) -> tuple[dict[str, object], float]:
    wall_now = datetime.now().astimezone()
    ts_iso = wall_now.isoformat()
    t_epoch = wall_now.timestamp()

    if t0_epoch is None:
        t0_epoch = t_epoch

    t_rel = t_epoch - t0_epoch
    t_cmd = perf_counter()

    try:
        pressure = dps.read_pressure_r()
        t_rx = perf_counter()
        latency_s = t_rx - t_cmd

        row = {
            "ts_iso": ts_iso,
            "t_epoch": f"{t_epoch:.6f}",
            "t_rel": f"{t_rel:.6f}",
            "addr": addr,
            "pressure": f"{float(pressure):.6f}",
            "unit": "bar",
            "latency_s": f"{latency_s:.6f}",
            "source": "DPS8000",
            "status": "OK",
        }
        return row, t0_epoch

    except Exception as exc:
        t_rx = perf_counter()
        latency_s = t_rx - t_cmd

        row = {
            "ts_iso": ts_iso,
            "t_epoch": f"{t_epoch:.6f}",
            "t_rel": f"{t_rel:.6f}",
            "addr": addr,
            "pressure": "",
            "unit": "",
            "latency_s": f"{latency_s:.6f}",
            "source": "DPS8000",
            "status": f"ERR:{exc}",
        }
        return row, t0_epoch


def run_logger(args: argparse.Namespace) -> int:
    global disable_halt, stop_requested

    install_signal_handlers_once()
    stop_requested = False

    base_dir = Path(args.base_dir).expanduser().resolve()
    session_id = make_session_id()
    out_dir, file_suffix = _resolve_output_paths(base_dir, session_id, args.session_subdir)

    meta_path = write_run_metadata(out_dir, args, session_id, file_suffix)

    transport, dps_map = _build_dps_objects(args)
    writers = {
        addr: _make_writer(out_dir, args.prefix, addr, args.flush_every, file_suffix)
        for addr in args.addresses
    }

    entered_writers: Dict[int, CSVRotatingWriter] = {}

    try:
        with transport.opened():
            for addr, writer in writers.items():
                entered_writers[addr] = writer.__enter__()

            print(f"{PROGRAM_NAME} v{PROGRAM_VERSION}")

            for addr, dps in dps_map.items():
                try:
                    ident = dps.identify()
                except Exception as exc:
                    ident = f"IDENT_ERR:{exc}"
                print(f"ADDR {addr:02d} IDENT: {ident}")

            print(f"Session ID: {session_id}")
            print(f"Logging directory: {out_dir}")
            print(f"Run metadata: {meta_path}")
            print(f"Addresses: {', '.join(f'{a:02d}' for a in args.addresses)}")
            print(f"Interval per cycle: {args.interval} s")
            if args.duration is None:
                print("Duration: unlimited")
            else:
                print(f"Duration: {args.duration} s")
            print("Stop with Ctrl+C (logger will finish current cycle before stopping).")

            print("Synchronizing time.")
            if args.pretty:
                print(_pretty_header())
            while get_sec_fractions(4) != 0:
                pass

            tp0 = perf_counter()
            cycle = 0
            t0_epoch: float | None = None

            while True:
                disable_halt = True
                duration_reached = False

                try:
                    for addr in args.addresses:
                        row, t0_epoch = _read_sample(dps_map[addr], addr, t0_epoch)
                        row["cycle"] = cycle + 1

                        # TODO: Future IoT handler.
                        # Hook point for publishing the current sample to an external IoT pipeline.

                        entered_writers[addr].write(row)

                        if args.print_rows:
                            if args.pretty:
                                print(_format_pretty_row(row))
                            else:
                                print(",".join(str(row.get(h, "")) for h in _headers()))

                        if args.duration is not None:
                            if float(row["t_rel"]) >= args.duration:
                                duration_reached = True

                    cycle += 1

                finally:
                    disable_halt = False

                if stop_requested:
                    print("Termination requested. Stopping after completed cycle.")
                    break

                if duration_reached:
                    print(f"Requested duration reached ({args.duration} s). Stopping.")
                    break

                tp_end = perf_counter()
                wait_time = cycle * args.interval - (tp_end - tp0)
                if wait_time > 0:
                    sleep(wait_time)

    finally:
        for writer in entered_writers.values():
            writer.__exit__(None, None, None)
        for writer in writers.values():
            try:
                writer.close()
            except Exception:
                pass

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.pretty:
        args.print_rows = True

    args.addresses = _resolve_addresses(args)

    return run_logger(args)


if __name__ == "__main__":
    raise SystemExit(main())
