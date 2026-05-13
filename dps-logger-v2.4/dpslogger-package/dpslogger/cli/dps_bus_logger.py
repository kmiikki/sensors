from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

from dpslogger.csv_writer import CSVRotateConfig, CSVRotatingWriter
from dpslogger.transport import SerialTransport, SerialTransportConfig
from dpslogger import __version__


DEFAULT_INTERVAL = 1.0
DEFAULT_PREFIX = "dps"
DEFAULT_BASE_DIR = "."
DEFAULT_PORT = "/dev/ttyLOG"
DEFAULT_ADDRESS = 1
DEFAULT_CONFIG_NAME = "dps_config.json"
DEFAULT_COMMAND_PREFIX = " "
DEFAULT_EOL = "cr"
DEFAULT_READ_COMMAND = "R"
DEFAULT_READ_MODE = "serial"
DEFAULT_COMMAND_GAP_S = 0.06
DEFAULT_COLLECT_TIMEOUT_S = 5.0
DEFAULT_PROFILE_ROUNDS = 10

PROGRAM_NAME = "dpslogger"
PROGRAM_VERSION = __version__

_ADDR_REPLY_RE = re.compile(r"^\s*(?P<addr>\d{1,2})\s*:\s*(?P<payload>.*?)\s*$")

disable_halt = False
stop_requested = False
_sig_installed = False
_child_process_active = False


@dataclass(frozen=True)
class SensorSpec:
    """One configured sensor on the DPS RS-485 bus."""

    address: int
    logical_id: str
    unit_code: int | None
    unit_symbol: str
    enabled: bool
    minimum_interval_s: float | None
    detail_filename: str | None = None


@dataclass(frozen=True)
class ResolvedConfig:
    """Runtime configuration after resolving CLI, config JSON and defaults."""

    config_path: Path | None
    config_search_order: list[Path]
    raw_config: dict[str, Any]
    port: str
    baudrate: int
    timeout_s: float
    eol: str
    command_prefix: str
    read_mode: str
    read_command: str
    command_gap_s: float
    collect_timeout_s: float
    interval_s: float
    interval_policy: str
    sensors: list[SensorSpec]
    unit_map: dict[str, str]


def get_sec_fractions(resolution: int = 5) -> float:
    now = datetime.now()
    return round(now.timestamp() % 1, resolution)


def _sig_handler(signum, frame) -> None:  # noqa: ANN001
    global disable_halt, stop_requested
    stop_requested = True

    if disable_halt:
        return

    # During auto-profile / profile-to-config subprocesses, the child command
    # handles Ctrl+C and prints the user-facing termination message. Keep the
    # parent logger quiet to avoid duplicate messages.
    if _child_process_active:
        raise SystemExit(130)

    print("\nTermination requested (Ctrl+C). Exiting...", file=sys.stderr)
    raise SystemExit(130)


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
        try:
            value = int(part)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"Invalid address: {part!r}") from exc
        if value < 0:
            raise argparse.ArgumentTypeError("Address must be >= 0")
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError("At least one address is required")
    if len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("Duplicate addresses are not allowed")
    return values


def parse_ids(text: str) -> list[str]:
    values = [part.strip() for part in text.split(",") if part.strip()]
    if not values:
        raise argparse.ArgumentTypeError("At least one id is required")
    if len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("Duplicate ids are not allowed")
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


def format_pressure_for_unit(value: float, unit: str) -> str:
    unit_lc = unit.strip().lower()

    if unit_lc == "pa":
        return f"{value:.0f}"
    if unit_lc in {"hpa", "kpa", "mbar"}:
        return f"{value:.3f}"
    if unit_lc in {"bar", "mpa"}:
        return f"{value:.6f}"

    return f"{value:.6f}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Multi-sensor DPS RS-485 bus logger.")
    parser.add_argument("--config", default=None, help="Path to dps_config.json")
    parser.add_argument("--profile", default="real", help="Profile name kept for old metadata compatibility")
    parser.add_argument("--port", default=None, help=f"Serial port override (default without config: {DEFAULT_PORT})")
    parser.add_argument("-b", "--baud", "--baudrate", dest="baudrate", type=int, default=None)
    parser.add_argument("--timeout", type=positive_float, default=None)
    parser.add_argument("-e", "--eol", choices=["cr", "lf", "crlf", "none"], default=None)
    parser.add_argument("-P", "--command-prefix", default=None)
    parser.add_argument("--read-mode", choices=["serial", "burst"], default=None)
    parser.add_argument("-r", "--read", "--read-command", dest="read_command", choices=["G", "R", "*G", "*R"], default=None)
    parser.add_argument("-g", "--command-gap", type=non_negative_float, default=None)
    parser.add_argument("-c", "--collect-timeout", type=positive_float, default=None)

    parser.add_argument("--addr", type=int, default=None, help="Single address shortcut")
    parser.add_argument("--addresses", type=parse_addresses, default=None, help="Comma-separated active address list")
    parser.add_argument("--ids", "--logical-ids", type=parse_ids, default=None, help="Comma-separated active logical ids")

    parser.add_argument("--interval", type=positive_float, default=None, help="Cycle interval in seconds")
    parser.add_argument("--interval-policy", choices=["warn", "error", "ignore"], default=None)
    parser.add_argument("--duration", "--time", dest="duration", type=non_negative_float, default=None)
    parser.add_argument("--base-dir", default=DEFAULT_BASE_DIR, help="Base output directory")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Filename prefix before _addrNN_YYYYMMDD.csv")
    parser.add_argument("--session-subdir", action="store_true", help="Create one session subdirectory for this run")
    parser.add_argument("--flush-every", type=int, default=1, help="Flush CSV files every N rows")

    parser.add_argument("--auto-profile", dest="auto_profile", action="store_true", default=True, help="Run commissioning profile automatically if config or active sensors are missing (default)")
    parser.add_argument("--no-auto-profile", dest="auto_profile", action="store_false", help="Fail instead of running automatic commissioning profile")
    parser.add_argument("--profile-rounds", type=int, default=DEFAULT_PROFILE_ROUNDS, help="Rounds for automatic dps-profile-cycle")
    parser.add_argument("--profile-only", action="store_true", help="Run automatic profiling/config update and exit without logging")
    parser.add_argument("--reprofile", action="store_true", help="Force profiling of the selected active sensors before logging")

    parser.add_argument("--summary", dest="summary", action="store_true", default=True, help="Write dps_summary_<session>.csv (default)")
    parser.add_argument("--no-summary", dest="summary", action="store_false", help="Do not write summary CSV")
    parser.add_argument("--print-rows", action="store_true", help="Print old detail CSV rows to stdout")
    parser.add_argument("-p", "--pretty", action="store_true", help="Pretty terminal output using logical ids")
    parser.add_argument("--verbose", action="store_true", help="Print extra per-sensor technical status")
    parser.add_argument("--quiet", action="store_true", help="Do not print cycle rows")
    parser.add_argument("--no-sync", action="store_true", help="Do not wait for a whole-second boundary before logging")
    return parser


def detail_headers() -> list[str]:
    return [
        "ts_iso",
        "timestamp",
        "time",
        "cycle",
        "addr",
        "pressure",
        "unit",
        "latency_s",
        "source",
        "status",
    ]


def summary_headers(sensors: list[SensorSpec]) -> list[str]:
    return ["ts_iso", "timestamp", "time", "cycle", *[sensor.logical_id for sensor in sensors]]


def make_session_id() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def parse_addressed_reply(reply_text: str) -> tuple[int, str] | None:
    match = _ADDR_REPLY_RE.match(reply_text.strip())
    if not match:
        return None
    return int(match.group("addr")), match.group("payload").strip()


def command_for_address(address: int, read_command: str, command_prefix: str) -> str:
    return f"{command_prefix}{address}:{read_command}"


def _config_search_order(explicit_config: str | None, cwd: Path | None = None) -> list[Path]:
    if explicit_config:
        return [Path(explicit_config).expanduser().resolve()]

    root = (cwd or Path.cwd()).resolve()
    return [
        root / DEFAULT_CONFIG_NAME,
        root.parent / DEFAULT_CONFIG_NAME,
        root.parent.parent / DEFAULT_CONFIG_NAME,
    ]


def _load_first_config(explicit_config: str | None) -> tuple[Path | None, list[Path], dict[str, Any]]:
    search_order = _config_search_order(explicit_config)
    for path in search_order:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return path, search_order, json.load(f)
    return None, search_order, {}


def _unit_symbol_from_map(unit_code: int | None, unit_map: dict[str, str], fallback: str = "") -> str:
    if unit_code is None:
        return fallback or "unknown"
    return unit_map.get(str(unit_code), fallback or f"unit{unit_code}")


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _sensor_from_config(raw: dict[str, Any], unit_map: dict[str, str]) -> SensorSpec:
    address = int(raw["address"])
    logical_id = str(raw.get("id") or f"p{address}")
    unit_code_raw = raw.get("unit_code")
    unit_code = int(unit_code_raw) if unit_code_raw is not None else None
    unit_symbol = str(raw.get("unit_symbol") or _unit_symbol_from_map(unit_code, unit_map, ""))
    enabled = bool(raw.get("enabled", True))
    min_interval_raw = raw.get("minimum_interval_s")
    minimum_interval_s = float(min_interval_raw) if min_interval_raw is not None else None
    return SensorSpec(
        address=address,
        logical_id=logical_id,
        unit_code=unit_code,
        unit_symbol=unit_symbol,
        enabled=enabled,
        minimum_interval_s=minimum_interval_s,
    )


def _resolve_sensors(args: argparse.Namespace, raw_config: dict[str, Any], unit_map: dict[str, str]) -> list[SensorSpec]:
    configured = [_sensor_from_config(item, unit_map) for item in raw_config.get("sensors", [])]
    by_addr = {sensor.address: sensor for sensor in configured}
    by_id = {sensor.logical_id: sensor for sensor in configured}

    if args.addresses is not None and args.ids is not None:
        if len(args.addresses) != len(args.ids):
            raise SystemExit("ERROR: --addresses and --ids must contain the same number of items")
        resolved: list[SensorSpec] = []
        for address, logical_id in zip(args.addresses, args.ids, strict=True):
            existing = by_addr.get(address) or by_id.get(logical_id)
            if existing is None:
                raise SystemExit(
                    f"ERROR: active sensor {logical_id}=addr{address:02d} is missing from dps_config.json.\n"
                    "Run dps-profile-cycle / dps-profile-to-config first, or add this sensor to config."
                )
            if existing.address != address or existing.logical_id != logical_id:
                raise SystemExit(
                    "ERROR: CLI address/id mapping conflicts with dps_config.json: "
                    f"requested {logical_id}=addr{address:02d}, config has "
                    f"{existing.logical_id}=addr{existing.address:02d}"
                )
            resolved.append(existing)
        return resolved

    if args.ids is not None:
        missing = [logical_id for logical_id in args.ids if logical_id not in by_id]
        if missing:
            raise SystemExit(
                "ERROR: active sensor id(s) missing from dps_config.json: " + ", ".join(missing)
            )
        return [by_id[logical_id] for logical_id in args.ids]

    if args.addresses is not None:
        resolved = []
        missing = []
        for address in args.addresses:
            sensor = by_addr.get(address)
            if sensor is None:
                missing.append(address)
            else:
                resolved.append(sensor)
        if missing:
            raise SystemExit(
                "ERROR: active address(es) missing from dps_config.json: "
                + ", ".join(f"addr{addr:02d}" for addr in missing)
            )
        return resolved

    if args.addr is not None:
        sensor = by_addr.get(args.addr)
        if sensor is None:
            if configured:
                raise SystemExit(f"ERROR: addr{args.addr:02d} is missing from dps_config.json")
            return [SensorSpec(args.addr, f"p{args.addr}", None, "", True, None)]
        return [sensor]

    if configured:
        enabled = [sensor for sensor in configured if sensor.enabled]
        return enabled or configured

    return [SensorSpec(DEFAULT_ADDRESS, f"p{DEFAULT_ADDRESS}", None, "", True, None)]


def resolve_config(args: argparse.Namespace) -> ResolvedConfig:
    config_path, search_order, raw_config = _load_first_config(args.config)

    transport_cfg = raw_config.get("transport", {})
    readout_cfg = raw_config.get("readout", {})
    unit_map_cfg = raw_config.get("unit_map", {})
    unit_map = {str(k): str(v) for k, v in unit_map_cfg.get("codes", {}).items()}

    port = str(_coalesce(args.port, transport_cfg.get("port"), DEFAULT_PORT))
    baudrate = int(_coalesce(args.baudrate, transport_cfg.get("baudrate"), transport_cfg.get("baud"), 9600))
    timeout_s = float(_coalesce(args.timeout, transport_cfg.get("timeout_s"), transport_cfg.get("timeout"), 1.0))
    eol = str(_coalesce(args.eol, transport_cfg.get("eol"), DEFAULT_EOL))
    command_prefix = str(_coalesce(args.command_prefix, transport_cfg.get("command_prefix"), DEFAULT_COMMAND_PREFIX))
    read_mode = str(_coalesce(args.read_mode, readout_cfg.get("read_mode"), DEFAULT_READ_MODE)).lower()
    read_command = str(_coalesce(args.read_command, readout_cfg.get("read_command"), DEFAULT_READ_COMMAND))
    command_gap_s = float(_coalesce(args.command_gap, readout_cfg.get("command_gap_s"), DEFAULT_COMMAND_GAP_S))
    collect_timeout_s = float(_coalesce(args.collect_timeout, readout_cfg.get("collect_timeout_s"), DEFAULT_COLLECT_TIMEOUT_S))
    interval_s = float(_coalesce(args.interval, readout_cfg.get("interval_s"), DEFAULT_INTERVAL))
    interval_policy = str(_coalesce(args.interval_policy, readout_cfg.get("interval_policy"), "warn"))

    if read_mode not in {"serial", "burst"}:
        raise SystemExit(f"ERROR: Unsupported read_mode: {read_mode!r}")

    sensors = _resolve_sensors(args, raw_config, unit_map)
    if not sensors:
        raise SystemExit("ERROR: No active sensors selected")

    return ResolvedConfig(
        config_path=config_path,
        config_search_order=search_order,
        raw_config=raw_config,
        port=port,
        baudrate=baudrate,
        timeout_s=timeout_s,
        eol=eol,
        command_prefix=command_prefix,
        read_mode=read_mode,
        read_command=read_command,
        command_gap_s=command_gap_s,
        collect_timeout_s=collect_timeout_s,
        interval_s=interval_s,
        interval_policy=interval_policy,
        sensors=sensors,
        unit_map=unit_map,
    )


def validate_interval(resolved: ResolvedConfig) -> None:
    values = [sensor.minimum_interval_s for sensor in resolved.sensors if sensor.minimum_interval_s is not None]
    if not values:
        return
    required = max(values)
    if resolved.interval_s >= required:
        return

    message = (
        f"Configured interval {resolved.interval_s:.3f} s is shorter than active sensor minimum "
        f"{required:.3f} s."
    )
    if resolved.interval_policy == "error":
        raise SystemExit("ERROR: " + message)
    if resolved.interval_policy == "warn":
        print("WARNING: " + message)


def _resolve_output_paths(base_dir: Path, session_id: str, use_subdir: bool) -> tuple[Path, str | None]:
    base_dir.mkdir(parents=True, exist_ok=True)

    if use_subdir:
        out_dir = base_dir / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir, None

    return base_dir, f"_{session_id}"


def _make_detail_writer(out_dir: Path, prefix: str, addr: int, flush_every: int, file_suffix: str | None) -> CSVRotatingWriter:
    writer_prefix = f"{prefix}_addr{addr:02d}" if file_suffix is None else f"{prefix}_addr{addr:02d}{file_suffix}"
    return CSVRotatingWriter(
        CSVRotateConfig(prefix=writer_prefix, dirpath=out_dir, headers=detail_headers(), flush_every=flush_every)
    )


def _make_summary_writer(
    out_dir: Path,
    sensors: list[SensorSpec],
    flush_every: int,
    file_suffix: str | None,
) -> CSVRotatingWriter:
    writer_prefix = "dps_summary" if file_suffix is None else f"dps_summary{file_suffix}"
    return CSVRotatingWriter(
        CSVRotateConfig(prefix=writer_prefix, dirpath=out_dir, headers=summary_headers(sensors), flush_every=flush_every)
    )


def detail_filename(prefix: str, addr: int, file_suffix: str | None) -> str:
    stem = f"{prefix}_addr{addr:02d}" if file_suffix is None else f"{prefix}_addr{addr:02d}{file_suffix}"
    return f"{stem}.csv"


def summary_filename(file_suffix: str | None) -> str:
    stem = "dps_summary" if file_suffix is None else f"dps_summary{file_suffix}"
    return f"{stem}.csv"


def write_run_metadata(
    out_dir: Path,
    args: argparse.Namespace,
    resolved: ResolvedConfig,
    session_id: str,
    file_suffix: str | None,
) -> Path:
    ts = datetime.now().astimezone()
    active_ids = [sensor.logical_id for sensor in resolved.sensors]
    summary_schema = summary_headers(resolved.sensors) if args.summary else None

    meta = {
        "program": PROGRAM_NAME,
        "version": PROGRAM_VERSION,
        "started_at": ts.isoformat(),
        "session_id": session_id,
        "config": {
            "path": str(resolved.config_path) if resolved.config_path else None,
            "search_order": [str(path) for path in resolved.config_search_order],
            "resolution_policy": "first_match_wins_no_merge_no_inheritance",
        },
        "transport": {
            "port": resolved.port,
            "baudrate": resolved.baudrate,
            "timeout_s": resolved.timeout_s,
            "eol": resolved.eol,
            "command_prefix": resolved.command_prefix,
        },
        "readout": {
            "read_mode": resolved.read_mode,
            "read_command": resolved.read_command,
            "command_gap_s": resolved.command_gap_s,
            "collect_timeout_s": resolved.collect_timeout_s,
            "interval_s": resolved.interval_s,
            "interval_policy": resolved.interval_policy,
        },
        "sensors": {
            "active_ids": active_ids,
            "addresses": [sensor.address for sensor in resolved.sensors],
            "details": {
                sensor.logical_id: {
                    "address": sensor.address,
                    "unit_code": sensor.unit_code,
                    "unit_symbol": sensor.unit_symbol,
                    "minimum_interval_s": sensor.minimum_interval_s,
                    "detail_csv": detail_filename(args.prefix, sensor.address, file_suffix),
                }
                for sensor in resolved.sensors
            },
        },
        "logging": {
            "interval_s": resolved.interval_s,
            "duration_s": args.duration,
            "base_dir": str(args.base_dir),
            "prefix": args.prefix,
            "flush_every": args.flush_every,
            "session_subdir": args.session_subdir,
        },
        "csv_schema": detail_headers(),
        "summary_csv": None,
        "output_files": {
            "detail_csv": {
                sensor.logical_id: detail_filename(args.prefix, sensor.address, file_suffix)
                for sensor in resolved.sensors
            },
        },
    }

    if args.summary:
        filename = summary_filename(file_suffix)
        meta["summary_csv"] = {
            "filename": filename,
            "schema": summary_schema,
            "aliases": {"timestamp": "timestamp", "time": "time"},
            "unit": _common_unit(resolved.sensors),
            "columns": {
                sensor.logical_id: {
                    "address": sensor.address,
                    "detail_csv": detail_filename(args.prefix, sensor.address, file_suffix),
                    "unit_code": sensor.unit_code,
                    "unit": sensor.unit_symbol,
                    "minimum_interval_s": sensor.minimum_interval_s,
                }
                for sensor in resolved.sensors
            },
        }
        meta["output_files"]["summary_csv"] = filename

    filename = "dps_run.json" if file_suffix is None else f"dps_run{file_suffix}.json"
    path = out_dir / filename
    with path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return path


def _common_unit(sensors: list[SensorSpec]) -> str | None:
    units = {sensor.unit_symbol for sensor in sensors if sensor.unit_symbol}
    if len(units) == 1:
        return next(iter(units))
    return None


def _transport_config(resolved: ResolvedConfig) -> SerialTransportConfig:
    return SerialTransportConfig(
        port=resolved.port,
        baud=resolved.baudrate,
        timeout_s=resolved.timeout_s,
        write_sleep_s=0.0,
        eol=resolved.eol,
        reset_input_before_cmd=False,
    )


def _row_template(sensor: SensorSpec, ts_iso: str, t_epoch: float, t_rel: float, cycle: int) -> dict[str, object]:
    return {
        "ts_iso": ts_iso,
        "timestamp": f"{t_epoch:.6f}",
        "time": f"{t_rel:.6f}",
        "cycle": cycle,
        "addr": sensor.address,
        "pressure": "",
        "unit": sensor.unit_symbol,
        "latency_s": "",
        "source": "DPS8000",
        "status": "MISS",
    }


def _read_cycle_burst(
    transport: SerialTransport,
    resolved: ResolvedConfig,
    cycle: int,
    t0_epoch: float | None,
) -> tuple[dict[str, dict[str, object]], float]:
    wall_now = datetime.now().astimezone()
    ts_iso = wall_now.isoformat()
    t_epoch = wall_now.timestamp()
    if t0_epoch is None:
        t0_epoch = t_epoch
    t_rel = t_epoch - t0_epoch

    rows = {sensor.logical_id: _row_template(sensor, ts_iso, t_epoch, t_rel, cycle) for sensor in resolved.sensors}
    send_times: dict[int, float] = {}
    sensor_by_addr = {sensor.address: sensor for sensor in resolved.sensors}

    transport.clear_buffers()
    for sensor in resolved.sensors:
        command = command_for_address(sensor.address, resolved.read_command, resolved.command_prefix)
        send_times[sensor.address] = perf_counter()
        transport.write_line(command)
        if resolved.command_gap_s > 0:
            sleep(resolved.command_gap_s)

    deadline = perf_counter() + resolved.collect_timeout_s
    seen: set[int] = set()
    while perf_counter() < deadline and len(seen) < len(resolved.sensors):
        remaining = max(0.0, deadline - perf_counter())
        lines = transport.read_lines_for(min(0.05, remaining))
        if not lines:
            continue
        now = perf_counter()
        for line in lines:
            parsed = parse_addressed_reply(line)
            if parsed is None:
                continue
            address, payload = parsed
            sensor = sensor_by_addr.get(address)
            if sensor is None or address in seen:
                continue
            seen.add(address)
            row = rows[sensor.logical_id]
            try:
                pressure = float(payload)
                row["pressure"] = format_pressure_for_unit(pressure, sensor.unit_symbol)
                row["status"] = "OK"
            except ValueError:
                row["pressure"] = ""
                row["status"] = f"ERR:bad payload {payload!r}"
            row["latency_s"] = f"{now - send_times[address]:.6f}"

    return rows, t0_epoch


def _read_one_serial(
    transport: SerialTransport,
    resolved: ResolvedConfig,
    sensor: SensorSpec,
    cycle: int,
    t0_epoch: float | None,
) -> tuple[dict[str, object], float]:
    wall_now = datetime.now().astimezone()
    ts_iso = wall_now.isoformat()
    t_epoch = wall_now.timestamp()
    if t0_epoch is None:
        t0_epoch = t_epoch
    t_rel = t_epoch - t0_epoch
    row = _row_template(sensor, ts_iso, t_epoch, t_rel, cycle)

    command = command_for_address(sensor.address, resolved.read_command, resolved.command_prefix)
    transport.clear_buffers()
    t_cmd = perf_counter()
    try:
        transport.write_line(command)
        deadline = perf_counter() + resolved.collect_timeout_s
        while perf_counter() < deadline:
            remaining = max(0.0, deadline - perf_counter())
            lines = transport.read_lines_for(min(0.05, remaining))
            if not lines:
                continue
            now = perf_counter()
            for line in lines:
                parsed = parse_addressed_reply(line)
                if parsed is None:
                    continue
                address, payload = parsed
                if address != sensor.address:
                    continue
                try:
                    pressure = float(payload)
                    row["pressure"] = format_pressure_for_unit(pressure, sensor.unit_symbol)
                    row["status"] = "OK"
                except ValueError:
                    row["status"] = f"ERR:bad payload {payload!r}"
                row["latency_s"] = f"{now - t_cmd:.6f}"
                return row, t0_epoch
        row["status"] = "ERR:timeout"
        row["latency_s"] = f"{perf_counter() - t_cmd:.6f}"
        return row, t0_epoch
    except Exception as exc:
        row["status"] = f"ERR:{exc}"
        row["latency_s"] = f"{perf_counter() - t_cmd:.6f}"
        return row, t0_epoch


def _read_cycle_serial(
    transport: SerialTransport,
    resolved: ResolvedConfig,
    cycle: int,
    t0_epoch: float | None,
) -> tuple[dict[str, dict[str, object]], float]:
    rows: dict[str, dict[str, object]] = {}
    for sensor in resolved.sensors:
        row, t0_epoch = _read_one_serial(transport, resolved, sensor, cycle, t0_epoch)
        rows[sensor.logical_id] = row
    if t0_epoch is None:
        t0_epoch = datetime.now().astimezone().timestamp()
    return rows, t0_epoch


def _summary_row(rows_by_id: dict[str, dict[str, object]], sensors: list[SensorSpec]) -> dict[str, object]:
    first = rows_by_id[sensors[0].logical_id]
    row: dict[str, object] = {
        "ts_iso": first.get("ts_iso", ""),
        "timestamp": first.get("timestamp", ""),
        "time": first.get("time", ""),
        "cycle": first.get("cycle", ""),
    }
    for sensor in sensors:
        row[sensor.logical_id] = rows_by_id[sensor.logical_id].get("pressure", "")
    return row


def _status_for_cycle(rows_by_id: dict[str, dict[str, object]]) -> str:
    bad = [logical_id for logical_id, row in rows_by_id.items() if row.get("status") != "OK"]
    if not bad:
        return "OK"
    return "WARN missing=" + ",".join(bad)


def _format_compact_cycle(rows_by_id: dict[str, dict[str, object]], sensors: list[SensorSpec]) -> str:
    first = rows_by_id[sensors[0].logical_id]
    cycle = int(first.get("cycle", 0))
    try:
        t_rel = float(first.get("time", 0.0))
    except Exception:
        t_rel = 0.0
    parts = [f"{cycle:03d}", f"time={t_rel:.3f}s"]
    for sensor in sensors:
        value = rows_by_id[sensor.logical_id].get("pressure", "") or "---"
        parts.append(f"{sensor.logical_id}={value}")
    parts.append(_status_for_cycle(rows_by_id))
    return " ".join(parts)


def _pretty_header(sensors: list[SensorSpec]) -> str:
    columns = ["Cycle", "time_s", *[sensor.logical_id for sensor in sensors], "Status"]
    return "  ".join(f"{col:>10}" for col in columns)


def _format_pretty_cycle(rows_by_id: dict[str, dict[str, object]], sensors: list[SensorSpec]) -> str:
    first = rows_by_id[sensors[0].logical_id]
    try:
        cycle = int(first.get("cycle", 0))
    except Exception:
        cycle = 0
    try:
        t_rel = float(first.get("time", 0.0))
    except Exception:
        t_rel = 0.0
    columns = [f"{cycle:10d}", f"{t_rel:10.3f}"]
    for sensor in sensors:
        value = str(rows_by_id[sensor.logical_id].get("pressure", "") or "---")
        columns.append(f"{value:>10}")
    columns.append(f"{_status_for_cycle(rows_by_id):>10}")
    return "  ".join(columns)


def _format_detail_csv_row(row: dict[str, object]) -> str:
    return ",".join(str(row.get(header, "")) for header in detail_headers())




def _active_selection_for_profile(
    args: argparse.Namespace,
    config_path: Path | None,
    raw_config: dict[str, Any],
) -> tuple[list[int], list[str]]:
    """Return addresses and logical ids for automatic commissioning profiling."""

    configured = raw_config.get("sensors", []) if isinstance(raw_config.get("sensors"), list) else []
    by_addr: dict[int, str] = {}
    by_id: dict[str, int] = {}
    for item in configured:
        if not isinstance(item, dict) or "address" not in item:
            continue
        address = int(item["address"])
        logical_id = str(item.get("id") or f"p{address}")
        by_addr[address] = logical_id
        by_id[logical_id] = address

    if args.addresses is not None and args.ids is not None:
        if len(args.addresses) != len(args.ids):
            raise SystemExit("ERROR: --addresses and --ids must contain the same number of items")
        return list(args.addresses), list(args.ids)

    if args.addresses is not None:
        addresses = list(args.addresses)
        ids = [by_addr.get(address, f"p{address}") for address in addresses]
        return addresses, ids

    if args.addr is not None:
        address = int(args.addr)
        return [address], [by_addr.get(address, f"p{address}")]

    if args.ids is not None:
        missing = [logical_id for logical_id in args.ids if logical_id not in by_id]
        if missing:
            raise SystemExit(
                "ERROR: Cannot auto-profile missing id(s) without addresses: " + ", ".join(missing) +
                "\nProvide both --addresses and --ids for new sensors."
            )
        return [by_id[logical_id] for logical_id in args.ids], list(args.ids)

    if configured:
        enabled_items = [item for item in configured if isinstance(item, dict) and bool(item.get("enabled", True))]
        selected = enabled_items or configured
        addresses = [int(item["address"]) for item in selected if isinstance(item, dict) and "address" in item]
        ids = [str(item.get("id") or f"p{int(item['address'])}") for item in selected if isinstance(item, dict) and "address" in item]
        return addresses, ids

    # No config and no explicit selection. Keep the old single-address fallback,
    # but make it visible in terminal output before profiling.
    return [DEFAULT_ADDRESS], [f"p{DEFAULT_ADDRESS}"]


def _target_config_path(args: argparse.Namespace, found_config_path: Path | None) -> Path:
    """Return the config file that auto-profile should create or update."""

    if found_config_path is not None:
        return found_config_path
    if args.config:
        return Path(args.config).expanduser().resolve()
    return (Path.cwd() / DEFAULT_CONFIG_NAME).resolve()


def _latest_profile_json(profile_dir: Path, previous: set[Path]) -> Path | None:
    candidates = sorted(profile_dir.glob("dps_profile_*.json"), key=lambda path: path.stat().st_mtime)
    for path in reversed(candidates):
        if path not in previous:
            return path
    return candidates[-1] if candidates else None


def _is_interrupt_returncode(returncode: int) -> bool:
    """Return True if a subprocess exit code indicates Ctrl+C/SIGINT."""
    return returncode in {130, -signal.SIGINT}




def _run_auto_profile_and_update_config(
    args: argparse.Namespace,
    *,
    found_config_path: Path | None,
    raw_config: dict[str, Any],
    reason: str,
) -> Path:
    """Run dps-profile-cycle and import the resulting profile into dps_config.json."""

    profile_dir = Path(args.base_dir).expanduser().resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    previous_profiles = set(profile_dir.glob("dps_profile_*.json"))

    addresses, ids = _active_selection_for_profile(args, found_config_path, raw_config)
    config_path = _target_config_path(args, found_config_path)

    transport_cfg = raw_config.get("transport", {}) if isinstance(raw_config.get("transport"), dict) else {}
    readout_cfg = raw_config.get("readout", {}) if isinstance(raw_config.get("readout"), dict) else {}

    port = str(_coalesce(args.port, transport_cfg.get("port"), DEFAULT_PORT))
    baudrate = int(_coalesce(args.baudrate, transport_cfg.get("baudrate"), transport_cfg.get("baud"), 9600))
    timeout_s = float(_coalesce(args.timeout, transport_cfg.get("timeout_s"), transport_cfg.get("timeout"), 1.0))
    eol = str(_coalesce(args.eol, transport_cfg.get("eol"), DEFAULT_EOL))
    command_prefix = str(_coalesce(args.command_prefix, transport_cfg.get("command_prefix"), DEFAULT_COMMAND_PREFIX))
    read_command = str(_coalesce(args.read_command, readout_cfg.get("read_command"), "G"))
    command_gap_s = float(_coalesce(args.command_gap, readout_cfg.get("command_gap_s"), DEFAULT_COMMAND_GAP_S))
    collect_timeout_s = float(_coalesce(args.collect_timeout, readout_cfg.get("collect_timeout_s"), DEFAULT_COLLECT_TIMEOUT_S))
    interval_s = float(_coalesce(args.interval, readout_cfg.get("interval_s"), 10.0))

    print(f"Auto-profile: {reason}")
    print(f"Auto-profile config target: {config_path}")
    print("Auto-profile sensors: " + ", ".join(f"{logical_id}=addr{address:02d}" for address, logical_id in zip(addresses, ids, strict=True)))

    profile_cmd = [
        sys.executable,
        "-m",
        "dpslogger.cli.dps_profile_cycle",
        "--port",
        port,
        "--baudrate",
        str(baudrate),
        "--timeout",
        str(timeout_s),
        "--eol",
        eol,
        "--command-prefix",
        command_prefix,
        "--addresses",
        ",".join(str(address) for address in addresses),
        "--ids",
        ",".join(ids),
        "--rounds",
        str(args.profile_rounds),
        "--read-command",
        read_command,
        "--command-gap",
        str(command_gap_s),
        "--collect-timeout",
        str(collect_timeout_s),
        "--base-dir",
        str(profile_dir),
    ]

    global _child_process_active
    try:
        _child_process_active = True
        subprocess.run(profile_cmd, check=True)
    except KeyboardInterrupt as exc:
        raise SystemExit(130) from exc
    except subprocess.CalledProcessError as exc:
        if _is_interrupt_returncode(exc.returncode):
            raise SystemExit(130) from exc
        raise SystemExit(f"ERROR: automatic profiling failed with exit code {exc.returncode}") from exc
    finally:
        _child_process_active = False

    profile_path = _latest_profile_json(profile_dir, previous_profiles)
    if profile_path is None:
        raise SystemExit(f"ERROR: automatic profiling did not create dps_profile_*.json in {profile_dir}")

    config_cmd = [
        sys.executable,
        "-m",
        "dpslogger.cli.dps_profile_to_config",
        "--profile",
        str(profile_path),
        "--config",
        str(config_path),
        "--interval",
        str(interval_s),
        "--collect-timeout",
        str(collect_timeout_s),
    ]

    try:
        _child_process_active = True
        subprocess.run(config_cmd, check=True)
    except KeyboardInterrupt as exc:
        raise SystemExit(130) from exc
    except subprocess.CalledProcessError as exc:
        if _is_interrupt_returncode(exc.returncode):
            raise SystemExit(130) from exc
        raise SystemExit(
            "ERROR: profile-to-config import failed. Make sure dpslogger.cli.dps_profile_to_config is installed. "
            f"Exit code: {exc.returncode}"
        ) from exc
    finally:
        _child_process_active = False

    print(f"Auto-profile profile JSON: {profile_path}")
    print(f"Auto-profile config JSON:  {config_path}")
    return config_path


def ensure_config_ready(args: argparse.Namespace) -> None:
    """Apply auto-profile policy before resolving final logger config."""

    found_config_path, _search_order, raw_config = _load_first_config(args.config)

    if args.reprofile:
        if not args.auto_profile:
            raise SystemExit("ERROR: --reprofile requires auto-profile support; remove --no-auto-profile")
        _run_auto_profile_and_update_config(
            args,
            found_config_path=found_config_path,
            raw_config=raw_config,
            reason="--reprofile requested",
        )
        return

    if found_config_path is None:
        if not args.auto_profile:
            raise SystemExit(
                "ERROR: dps_config.json not found and --no-auto-profile was used. "
                "Run dps-profile-cycle / dps-profile-to-config first."
            )
        _run_auto_profile_and_update_config(
            args,
            found_config_path=None,
            raw_config={},
            reason="dps_config.json not found",
        )
        return

    # Config exists. It is authoritative for known sensors; only missing active
    # sensors trigger automatic profiling/update.
    unit_map_cfg = raw_config.get("unit_map", {}) if isinstance(raw_config.get("unit_map"), dict) else {}
    unit_map = {str(k): str(v) for k, v in unit_map_cfg.get("codes", {}).items()}
    try:
        _resolve_sensors(args, raw_config, unit_map)
    except SystemExit as exc:
        message = str(exc)
        if "missing" not in message.lower():
            raise
        if not args.auto_profile:
            raise
        _run_auto_profile_and_update_config(
            args,
            found_config_path=found_config_path,
            raw_config=raw_config,
            reason="active sensor missing from dps_config.json",
        )


def run_logger(args: argparse.Namespace) -> int:
    global disable_halt, stop_requested

    install_signal_handlers_once()
    stop_requested = False

    ensure_config_ready(args)
    if args.profile_only:
        return 0

    resolved = resolve_config(args)
    validate_interval(resolved)

    base_dir = Path(args.base_dir).expanduser().resolve()
    session_id = make_session_id()
    out_dir, file_suffix = _resolve_output_paths(base_dir, session_id, args.session_subdir)

    transport = SerialTransport(_transport_config(resolved))

    detail_writers = {
        sensor.logical_id: _make_detail_writer(out_dir, args.prefix, sensor.address, args.flush_every, file_suffix)
        for sensor in resolved.sensors
    }
    summary_writer = _make_summary_writer(out_dir, resolved.sensors, args.flush_every, file_suffix) if args.summary else None

    entered_detail_writers: dict[str, CSVRotatingWriter] = {}
    entered_summary_writer: CSVRotatingWriter | None = None

    try:
        with transport.opened():
            for logical_id, writer in detail_writers.items():
                entered_detail_writers[logical_id] = writer.__enter__()
            if summary_writer is not None:
                entered_summary_writer = summary_writer.__enter__()

            print(f"{PROGRAM_NAME} v{PROGRAM_VERSION}")
            if resolved.config_path:
                print(f"Config: {resolved.config_path}")
            else:
                print("Config: not found; using CLI/defaults")
                print("Config search order:")
                for path in resolved.config_search_order:
                    print(f"  {path}")
            print(f"Session ID: {session_id}")
            print(f"Logging directory: {out_dir}")
            print(f"Port: {resolved.port}, baudrate: {resolved.baudrate}, EOL: {resolved.eol}")
            print("Sensors: " + ", ".join(f"{s.logical_id}=addr{s.address:02d}" for s in resolved.sensors))
            print(f"Read mode: {resolved.read_mode}, command: {resolved.read_command}")
            if resolved.read_mode == "burst":
                print(f"Command gap: {resolved.command_gap_s:.3f} s")
            print(f"Collect timeout: {resolved.collect_timeout_s:.3f} s")
            print(f"Interval per cycle: {resolved.interval_s:g} s")
            if args.duration is None:
                print("Duration: unlimited")
            else:
                print(f"Duration: {args.duration} s")

            meta_path = write_run_metadata(out_dir, args, resolved, session_id, file_suffix)
            print(f"Run metadata: {meta_path}")
            if args.summary:
                print(f"Summary CSV: {out_dir / summary_filename(file_suffix)}")
            print("Stop with Ctrl+C (logger will finish current cycle before stopping).")

            if not args.no_sync:
                print("Synchronizing time.")
                while get_sec_fractions(4) != 0:
                    pass

            if args.pretty and not args.quiet:
                print(_pretty_header(resolved.sensors))

            tp0 = perf_counter()
            cycle = 0
            t0_epoch: float | None = None

            while True:
                disable_halt = True
                duration_reached = False

                try:
                    cycle += 1
                    if resolved.read_mode == "burst":
                        rows_by_id, t0_epoch = _read_cycle_burst(transport, resolved, cycle, t0_epoch)
                    else:
                        rows_by_id, t0_epoch = _read_cycle_serial(transport, resolved, cycle, t0_epoch)

                    for sensor in resolved.sensors:
                        row = rows_by_id[sensor.logical_id]
                        entered_detail_writers[sensor.logical_id].write(row)

                    if entered_summary_writer is not None:
                        entered_summary_writer.write(_summary_row(rows_by_id, resolved.sensors))

                    if args.print_rows:
                        for sensor in resolved.sensors:
                            print(_format_detail_csv_row(rows_by_id[sensor.logical_id]))
                    elif not args.quiet:
                        if args.pretty:
                            print(_format_pretty_cycle(rows_by_id, resolved.sensors))
                        else:
                            print(_format_compact_cycle(rows_by_id, resolved.sensors))

                    if args.verbose:
                        for sensor in resolved.sensors:
                            row = rows_by_id[sensor.logical_id]
                            print(
                                f"  {sensor.logical_id}/addr{sensor.address:02d}: "
                                f"status={row.get('status')} latency={row.get('latency_s')} unit={sensor.unit_symbol}"
                            )

                    if args.duration is not None:
                        first = rows_by_id[resolved.sensors[0].logical_id]
                        if float(first["time"]) >= args.duration:
                            duration_reached = True

                finally:
                    disable_halt = False

                if stop_requested:
                    print("Termination requested. Stopping after completed cycle.")
                    break

                if duration_reached:
                    print(f"Requested duration reached ({args.duration} s). Stopping.")
                    break

                tp_end = perf_counter()
                wait_time = cycle * resolved.interval_s - (tp_end - tp0)
                if wait_time > 0:
                    sleep(wait_time)

    finally:
        for writer in entered_detail_writers.values():
            writer.__exit__(None, None, None)
        if entered_summary_writer is not None:
            entered_summary_writer.__exit__(None, None, None)
        for writer in detail_writers.values():
            try:
                writer.close()
            except Exception:
                pass
        if summary_writer is not None:
            try:
                summary_writer.close()
            except Exception:
                pass

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    This small compatibility wrapper keeps older install/post-install checks and
    external callers working while the actual parser construction remains in
    build_parser().
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.pretty:
        args.print_rows = False

    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        return run_logger(args)
    except KeyboardInterrupt:
        print("\nTermination requested (Ctrl+C). Exiting...", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
