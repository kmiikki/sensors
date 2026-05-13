from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dpslogger import __version__
from dpslogger.transport import SerialTransport, SerialTransportConfig, SerialTransportError

PROGRAM_NAME = "dps-profile-cycle"
PROGRAM_VERSION = __version__

DEFAULT_CONFIG_FILENAME = "dps_config.json"
DEFAULT_BAUDRATE = 9600
DEFAULT_TIMEOUT_S = 1.0
DEFAULT_ROUNDS = 10
DEFAULT_COMMAND_GAP_S = 0.06
DEFAULT_COLLECT_TIMEOUT_S = 5.0
DEFAULT_EOL = "cr"
DEFAULT_COMMAND_PREFIX = " "
DEFAULT_PREFIX = "dps_profile"
DEFAULT_OUTPUT_DIR = "."
DEFAULT_COLLECT_MARGIN_S = 0.25
DEFAULT_INTERVAL_PRESETS_S = (1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 30.0, 60.0)
DEFAULT_UNIT_MAP = {
    "0": "mbar",
    "1": "Pa",
    "2": "kPa",
    "3": "MPa",
    "4": "hPa",
    "5": "bar",
}
DEFAULT_UNIT_PROBE_CODES = (0, 1, 2, 3, 4, 5)

_ADDR_REPLY_RE = re.compile(r"^\s*(?P<addr>\d{1,2})\s*:\s*(?P<payload>.*?)\s*$")


@dataclass(frozen=True)
class BurstReply:
    """One reply collected during a burst profiling round."""

    address: int
    payload: str
    reply_text: str
    latency_s: float
    round_index: int


@dataclass(frozen=True)
class SensorTimingSummary:
    """Per-sensor timing statistics from burst profiling."""

    address: int
    logical_id: str
    replies: int
    missing: int
    success_rate: float
    min_latency_s: float | None
    avg_latency_s: float | None
    median_latency_s: float | None
    max_latency_s: float | None
    recommended_minimum_interval_s: float | None


@dataclass(frozen=True)
class ProfileRecommendations:
    """Recommended logger timing values derived from the profiling result."""

    recommended_collect_timeout_s: float
    recommended_interval_s: float
    recommended_cycle_interval_s: float
    minimum_safe_interval_s: float
    interval_presets_s: list[float]
    too_short_interval_presets_s: list[float]
    worst_latency_s: float | None
    slowest_address: int | None


@dataclass(frozen=True)
class EffectiveConfig:
    """Resolved profiler settings after applying CLI > JSON > defaults."""

    port: str
    baudrate: int
    timeout_s: float
    eol: str
    command_prefix: str
    addresses: list[int]
    address_to_logical_id: dict[int, str]
    read_command: str
    command_gap_s: float
    collect_timeout_s: float
    rounds: int
    settle_s: float
    collect_margin_s: float
    interval_presets_s: list[float]
    out_dir: Path
    filename_prefix: str
    config_path: Path | None
    config_search_paths: list[Path]
    unit_map: dict[str, str]
    unit_map_source: str
    raw_config: dict[str, Any]
    unit_probe_codes: list[int]
    force_unit_probe: bool


def parse_addresses(text: str) -> list[int]:
    """Parse a comma-separated DPS address list."""

    addresses: list[int] = []
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            address = int(part)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"Invalid address: {part!r}") from exc
        if not 0 <= address <= 32:
            raise argparse.ArgumentTypeError("Address must be in range 0..32")
        addresses.append(address)

    if not addresses:
        raise argparse.ArgumentTypeError("At least one address is required")

    if len(set(addresses)) != len(addresses):
        raise argparse.ArgumentTypeError("Duplicate addresses are not allowed")

    return addresses


def parse_ids(text: str | None) -> list[str] | None:
    """Parse comma-separated logical sensor ids."""

    if text is None:
        return None
    ids = [part.strip() for part in text.split(",") if part.strip()]
    if not ids:
        raise argparse.ArgumentTypeError("At least one id is required")
    if len(set(ids)) != len(ids):
        raise argparse.ArgumentTypeError("Duplicate ids are not allowed")
    return ids


def positive_float(value: str) -> float:
    """Parse a strictly positive float for argparse."""

    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid float value: {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be > 0")
    return parsed


def non_negative_float(value: str) -> float:
    """Parse a non-negative float for argparse."""

    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid float value: {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be >= 0")
    return parsed


def parse_interval_presets(text: str) -> list[float]:
    """Parse comma-separated positive interval presets in seconds."""

    presets: list[float] = []
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        presets.append(positive_float(part))

    if not presets:
        raise argparse.ArgumentTypeError("At least one interval preset is required")

    return sorted(set(presets))


def format_seconds(value: float) -> str:
    """Return a compact human-readable duration string."""

    if value < 60:
        return f"{value:.1f} s"

    minutes, seconds = divmod(value, 60.0)
    if minutes < 60:
        return f"{int(minutes)} min {seconds:.1f} s"

    hours, minutes = divmod(minutes, 60.0)
    return f"{int(hours)} h {int(minutes)} min {seconds:.1f} s"


def next_preset_at_least(value: float, presets: list[float]) -> float:
    """Return the first preset that is at least value."""

    for preset in sorted(presets):
        if preset >= value:
            return preset
    return round_up(value, 1.0)


def make_session_id() -> str:
    """Return a logger-style session id."""

    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def iso_now() -> str:
    """Return current local ISO 8601 timestamp."""

    return datetime.now().astimezone().isoformat()


def command_for_address(address: int, read_command: str, command_prefix: str) -> str:
    """Build an addressed DPS command."""

    return f"{command_prefix}{address}:{read_command}"


def parse_addressed_reply(reply_text: str) -> tuple[int, str] | None:
    """Parse replies like '01:101.123' and return address plus payload."""

    match = _ADDR_REPLY_RE.match(reply_text.strip())
    if not match:
        return None
    return int(match.group("addr")), match.group("payload").strip()


def parse_unit_code(payload: str) -> int | None:
    """Parse a DPS unit-code payload such as '2'."""

    stripped = payload.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def round_up(value: float, step: float) -> float:
    """Round value upward to the next multiple of step."""

    if step <= 0:
        raise ValueError("step must be > 0")
    return math.ceil(value / step) * step


def load_json_file(path: Path) -> dict[str, Any]:
    """Load a JSON object from path."""

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config JSON must contain an object: {path}")
    return data


def config_search_paths(explicit_path: str | None) -> list[Path]:
    """Return config search path candidates.

    CWD > parent > grandparent is only a search order. The first found file is
    the complete truth; values are not inherited from higher directories.
    """

    if explicit_path:
        return [Path(explicit_path).expanduser()]

    cwd = Path.cwd()
    return [
        cwd / DEFAULT_CONFIG_FILENAME,
        cwd.parent / DEFAULT_CONFIG_FILENAME,
        cwd.parent.parent / DEFAULT_CONFIG_FILENAME,
    ]


def find_config(explicit_path: str | None) -> tuple[Path | None, dict[str, Any], list[Path]]:
    """Find and load a DPS config JSON if available."""

    paths = config_search_paths(explicit_path)
    if explicit_path:
        path = paths[0]
        if not path.exists():
            raise FileNotFoundError(f"Config file does not exist: {path}")
        return path.resolve(), load_json_file(path), paths

    for path in paths:
        if path.exists():
            return path.resolve(), load_json_file(path), paths

    return None, {}, paths


def nested_get(data: dict[str, Any], *keys: str) -> Any:
    """Return nested config value, or None if any key is missing."""

    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def first_not_none(*values: Any) -> Any:
    """Return first value that is not None."""

    for value in values:
        if value is not None:
            return value
    return None


def as_float(value: Any, *, name: str) -> float:
    """Convert value to float with a readable error."""

    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid float for {name}: {value!r}") from exc


def as_int(value: Any, *, name: str) -> int:
    """Convert value to int with a readable error."""

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid integer for {name}: {value!r}") from exc


def normalize_unit_map(config: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Return unit code -> symbol map and source label.

    The unit-map truth source should be JSON after commissioning. Before a
    config exists, the profiler uses the small built-in 0..5 map only as
    labels while it verifies those codes on every active sensor.
    """

    raw_map = nested_get(config, "unit_map", "codes")
    source = nested_get(config, "unit_map", "source") or "config"
    if raw_map is None:
        raw_map = nested_get(config, "units", "unit_map")
        if raw_map is not None:
            source = nested_get(config, "units", "unit_map_source") or "config.units"
    if raw_map is None:
        raw_map = config.get("unit_map")
        if raw_map is not None:
            source = "config.unit_map"

    if isinstance(raw_map, dict) and "codes" in raw_map and isinstance(raw_map["codes"], dict):
        source = str(raw_map.get("source", source))
        raw_map = raw_map["codes"]

    if raw_map is None:
        return dict(DEFAULT_UNIT_MAP), "builtin_labels_pending_probe"

    if not isinstance(raw_map, dict):
        raise ValueError("unit_map must be a JSON object")

    return {str(key): str(value) for key, value in raw_map.items()}, str(source)


def parse_unit_probe_codes(text: str | None) -> list[int]:
    """Parse unit probe code list/range such as '0-5' or '0,1,2,3,4,5'."""

    if text is None or not text.strip():
        return list(DEFAULT_UNIT_PROBE_CODES)

    codes: list[int] = []
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())
            if end < start:
                raise argparse.ArgumentTypeError("Unit probe range end must be >= start")
            codes.extend(range(start, end + 1))
        else:
            codes.append(int(part))

    if not codes:
        raise argparse.ArgumentTypeError("At least one unit code is required")
    if any(code < 0 for code in codes):
        raise argparse.ArgumentTypeError("Unit codes must be non-negative")
    return sorted(set(codes))


def sensor_has_verified_unit_probe(entry: dict[str, Any], required_codes: list[int]) -> bool:
    """Return True if a config sensor entry already has unit probe results for required codes."""

    candidates: list[Any] = []
    for key in ("unit_probe", "unit_map", "units"):
        if key in entry:
            candidates.append(entry[key])

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("verified") is False:
            continue
        probe_results = candidate.get("probe_results") or candidate.get("codes")
        if isinstance(probe_results, dict):
            present = set()
            for code in required_codes:
                item = probe_results.get(str(code), probe_results.get(code))
                if isinstance(item, dict):
                    if item.get("accepted", True) and item.get("status", "OK") == "OK":
                        present.add(code)
                elif item is not None:
                    present.add(code)
            if all(code in present for code in required_codes):
                return True

    return False


def unit_probe_needed_addresses(
    entries: list[dict[str, Any]],
    active_addresses: list[int],
    required_codes: list[int],
    *,
    force: bool,
) -> list[int]:
    """Return active addresses whose per-sensor unit probe is missing."""

    if force:
        return list(active_addresses)

    by_address = {int(entry["address"]): entry for entry in entries if "address" in entry}
    needed: list[int] = []
    for address in active_addresses:
        entry = by_address.get(address)
        if entry is None or not sensor_has_verified_unit_probe(entry, required_codes):
            needed.append(address)
    return needed


def extract_sensor_list(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return sensor entries from supported config forms."""

    sensors = config.get("sensors")
    if isinstance(sensors, list):
        return [item for item in sensors if isinstance(item, dict)]

    if isinstance(sensors, dict):
        # Newer/alternative form: {"items": [...]}.
        items = sensors.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]

        # Compact form: {"addresses": [1, 2], "ids": ["p1", "p2"]}.
        addresses = sensors.get("addresses")
        if isinstance(addresses, list):
            ids = sensors.get("ids") or sensors.get("logical_ids")
            entries: list[dict[str, Any]] = []
            for index, address in enumerate(addresses):
                entry: dict[str, Any] = {"address": address}
                if isinstance(ids, list) and index < len(ids):
                    entry["id"] = ids[index]
                entries.append(entry)
            return entries

        # Mapping form: {"p1": {"address": 1}, ...}.
        entries = []
        for key, value in sensors.items():
            if not isinstance(value, dict) or "address" not in value:
                continue
            entry = dict(value)
            entry.setdefault("id", key)
            entries.append(entry)
        return entries

    return []


def addresses_from_sensor_entries(entries: list[dict[str, Any]], *, enabled_only: bool) -> list[int]:
    """Extract addresses from sensor entries."""

    addresses: list[int] = []
    for entry in entries:
        if enabled_only and entry.get("enabled", True) is False:
            continue
        if "address" not in entry:
            continue
        address = int(entry["address"])
        if address not in addresses:
            addresses.append(address)
    return addresses


def id_map_from_sensor_entries(entries: list[dict[str, Any]]) -> dict[int, str]:
    """Extract address -> logical id mapping from sensor entries."""

    mapping: dict[int, str] = {}
    for entry in entries:
        if "address" not in entry:
            continue
        address = int(entry["address"])
        logical_id = entry.get("id") or entry.get("logical_id") or f"p{address}"
        mapping[address] = str(logical_id)
    return mapping


def resolve_addresses_and_ids(
    *,
    config: dict[str, Any],
    cli_addresses: list[int] | None,
    cli_ids: list[str] | None,
) -> tuple[list[int], dict[int, str]]:
    """Resolve active addresses and logical ids from CLI and JSON config."""

    entries = extract_sensor_list(config)
    configured_id_map = id_map_from_sensor_entries(entries)
    id_to_address = {logical_id: address for address, logical_id in configured_id_map.items()}

    if cli_addresses is not None:
        addresses = cli_addresses
    elif cli_ids is not None:
        missing_ids = [logical_id for logical_id in cli_ids if logical_id not in id_to_address]
        if missing_ids:
            raise ValueError(
                "--ids can select configured sensors only; unknown id(s): "
                + ", ".join(missing_ids)
            )
        addresses = [id_to_address[logical_id] for logical_id in cli_ids]
    else:
        enabled_addresses = addresses_from_sensor_entries(entries, enabled_only=True)
        all_addresses = addresses_from_sensor_entries(entries, enabled_only=False)
        addresses = enabled_addresses or all_addresses

    if not addresses:
        raise ValueError(
            "No active DPS addresses found. Use --addresses or provide sensors in dps_config.json."
        )

    if cli_ids is not None and cli_addresses is not None:
        if len(cli_ids) != len(cli_addresses):
            raise ValueError("Number of --ids must match number of --addresses")
        address_to_logical_id = dict(zip(cli_addresses, cli_ids, strict=True))
    else:
        address_to_logical_id = {
            address: configured_id_map.get(address, f"p{address}") for address in addresses
        }

    return addresses, address_to_logical_id


def resolve_effective_config(args: argparse.Namespace) -> EffectiveConfig:
    """Resolve effective settings using CLI > JSON > defaults."""

    config_path, config, searched_paths = find_config(args.config)
    transport_cfg = config.get("transport") if isinstance(config.get("transport"), dict) else {}
    readout_cfg = config.get("readout") if isinstance(config.get("readout"), dict) else {}
    logging_cfg = config.get("logging") if isinstance(config.get("logging"), dict) else {}

    cli_ids = parse_ids(args.ids) if args.ids is not None else None
    addresses, address_to_logical_id = resolve_addresses_and_ids(
        config=config,
        cli_addresses=args.addresses,
        cli_ids=cli_ids,
    )

    port = first_not_none(args.port, transport_cfg.get("port"))
    if not port:
        raise ValueError("Serial port is required. Use --port or set transport.port in config.")

    baudrate = as_int(
        first_not_none(args.baudrate, transport_cfg.get("baudrate"), transport_cfg.get("baud"), DEFAULT_BAUDRATE),
        name="baudrate",
    )
    timeout_s = as_float(
        first_not_none(args.timeout, transport_cfg.get("timeout_s"), transport_cfg.get("timeout"), DEFAULT_TIMEOUT_S),
        name="timeout_s",
    )
    eol = str(first_not_none(args.eol, transport_cfg.get("eol"), DEFAULT_EOL))
    command_prefix = str(
        first_not_none(args.command_prefix, transport_cfg.get("command_prefix"), DEFAULT_COMMAND_PREFIX)
    )

    read_command = str(first_not_none(args.read_command, readout_cfg.get("read_command"), "G"))
    if read_command not in {"G", "R", "*G", "*R"}:
        raise ValueError(f"Invalid read command: {read_command!r}")

    command_gap_s = as_float(
        first_not_none(args.command_gap, readout_cfg.get("command_gap_s"), DEFAULT_COMMAND_GAP_S),
        name="command_gap_s",
    )
    collect_timeout_s = as_float(
        first_not_none(args.collect_timeout, readout_cfg.get("collect_timeout_s"), DEFAULT_COLLECT_TIMEOUT_S),
        name="collect_timeout_s",
    )
    rounds = as_int(first_not_none(args.rounds, readout_cfg.get("rounds"), DEFAULT_ROUNDS), name="rounds")
    settle_s = as_float(first_not_none(args.settle, readout_cfg.get("settle_s"), 0.5), name="settle_s")
    collect_margin_s = as_float(
        first_not_none(args.collect_margin, readout_cfg.get("collect_margin_s"), DEFAULT_COLLECT_MARGIN_S),
        name="collect_margin_s",
    )

    if args.interval_presets is not None:
        interval_presets_s = args.interval_presets
    else:
        raw_presets = readout_cfg.get("interval_presets_s") or logging_cfg.get("interval_presets_s")
        if raw_presets is None:
            interval_presets_s = list(DEFAULT_INTERVAL_PRESETS_S)
        elif isinstance(raw_presets, list):
            interval_presets_s = sorted({float(value) for value in raw_presets})
        elif isinstance(raw_presets, str):
            interval_presets_s = parse_interval_presets(raw_presets)
        else:
            raise ValueError("interval_presets_s must be a list or comma-separated string")

    out_dir = Path(first_not_none(args.base_dir, DEFAULT_OUTPUT_DIR)).expanduser().resolve()
    filename_prefix = str(first_not_none(args.prefix, DEFAULT_PREFIX))
    unit_map, unit_map_source = normalize_unit_map(config)
    probe_codes = parse_unit_probe_codes(args.probe_units)

    return EffectiveConfig(
        port=str(port),
        baudrate=baudrate,
        timeout_s=timeout_s,
        eol=eol,
        command_prefix=command_prefix,
        addresses=addresses,
        address_to_logical_id=address_to_logical_id,
        read_command=read_command,
        command_gap_s=command_gap_s,
        collect_timeout_s=collect_timeout_s,
        rounds=rounds,
        settle_s=settle_s,
        collect_margin_s=collect_margin_s,
        interval_presets_s=interval_presets_s,
        out_dir=out_dir,
        filename_prefix=filename_prefix,
        config_path=config_path,
        config_search_paths=[path.resolve() for path in searched_paths],
        unit_map=unit_map,
        unit_map_source=unit_map_source,
        raw_config=config,
        unit_probe_codes=probe_codes,
        force_unit_probe=bool(args.force_unit_probe),
    )


def collect_burst_round(
    transport: SerialTransport,
    addresses: list[int],
    *,
    read_command: str,
    command_prefix: str,
    command_gap_s: float,
    collect_timeout_s: float,
    round_index: int,
) -> tuple[dict[int, BurstReply], list[str]]:
    """Send one burst of read commands and collect addressed replies."""

    send_times: dict[int, float] = {}
    unexpected_lines: list[str] = []

    transport.clear_buffers()

    for address in addresses:
        command = command_for_address(address, read_command, command_prefix)
        send_times[address] = time.perf_counter()
        transport.write_line(command)
        if command_gap_s > 0:
            time.sleep(command_gap_s)

    deadline = time.perf_counter() + collect_timeout_s
    replies: dict[int, BurstReply] = {}

    while time.perf_counter() < deadline and len(replies) < len(addresses):
        remaining = max(0.0, deadline - time.perf_counter())
        lines = transport.read_lines_for(min(0.05, remaining))
        if not lines:
            continue

        now = time.perf_counter()
        for line in lines:
            line_clean = line.strip()
            if not line_clean:
                continue

            parsed = parse_addressed_reply(line_clean)
            if parsed is None:
                unexpected_lines.append(line_clean)
                continue

            address, payload = parsed
            if address not in send_times:
                unexpected_lines.append(line_clean)
                continue

            if address in replies:
                unexpected_lines.append(line_clean)
                continue

            replies[address] = BurstReply(
                address=address,
                payload=payload,
                reply_text=line_clean,
                latency_s=now - send_times[address],
                round_index=round_index,
            )

    return replies, unexpected_lines


def summarize_sensor_timing(
    addresses: list[int],
    logical_ids: dict[int, str],
    per_round: list[dict[int, BurstReply]],
) -> dict[int, SensorTimingSummary]:
    """Create per-address timing summaries."""

    summaries: dict[int, SensorTimingSummary] = {}
    total_rounds = len(per_round)

    for address in addresses:
        latencies = [round_data[address].latency_s for round_data in per_round if address in round_data]
        replies = len(latencies)
        missing = total_rounds - replies
        success_rate = replies / total_rounds if total_rounds else 0.0

        if latencies:
            min_latency = min(latencies)
            avg_latency = statistics.fmean(latencies)
            median_latency = statistics.median(latencies)
            max_latency = max(latencies)
            recommended_minimum_interval = round_up(max_latency + 1.0, 1.0)
        else:
            min_latency = None
            avg_latency = None
            median_latency = None
            max_latency = None
            recommended_minimum_interval = None

        summaries[address] = SensorTimingSummary(
            address=address,
            logical_id=logical_ids[address],
            replies=replies,
            missing=missing,
            success_rate=success_rate,
            min_latency_s=min_latency,
            avg_latency_s=avg_latency,
            median_latency_s=median_latency,
            max_latency_s=max_latency,
            recommended_minimum_interval_s=recommended_minimum_interval,
        )

    return summaries


def make_recommendations(
    summaries: dict[int, SensorTimingSummary],
    *,
    collect_margin_s: float,
    interval_presets_s: list[float],
) -> ProfileRecommendations:
    """Derive profile-level timing recommendations."""

    presets = sorted(interval_presets_s)
    valid = [s for s in summaries.values() if s.max_latency_s is not None]
    if not valid:
        minimum_safe_interval = next_preset_at_least(collect_margin_s, presets)
        recommended_interval = next_preset_at_least(minimum_safe_interval, presets)
        too_short = [preset for preset in presets if preset < minimum_safe_interval]
        return ProfileRecommendations(
            recommended_collect_timeout_s=minimum_safe_interval,
            recommended_interval_s=recommended_interval,
            recommended_cycle_interval_s=recommended_interval,
            minimum_safe_interval_s=minimum_safe_interval,
            interval_presets_s=presets,
            too_short_interval_presets_s=too_short,
            worst_latency_s=None,
            slowest_address=None,
        )

    slowest = max(valid, key=lambda item: item.max_latency_s or 0.0)
    worst_latency = float(slowest.max_latency_s or 0.0)

    recommended_collect_timeout = round_up(worst_latency + collect_margin_s, 1.0)
    minimum_safe_interval = recommended_collect_timeout
    recommended_interval = next_preset_at_least(minimum_safe_interval, presets)
    too_short = [preset for preset in presets if preset < minimum_safe_interval]

    return ProfileRecommendations(
        recommended_collect_timeout_s=recommended_collect_timeout,
        recommended_interval_s=recommended_interval,
        recommended_cycle_interval_s=recommended_interval,
        minimum_safe_interval_s=minimum_safe_interval,
        interval_presets_s=presets,
        too_short_interval_presets_s=too_short,
        worst_latency_s=worst_latency,
        slowest_address=slowest.address,
    )


def maybe_query_units(
    transport: SerialTransport,
    addresses: list[int],
    *,
    command_prefix: str,
    unit_map: dict[str, str],
) -> dict[int, dict[str, Any]]:
    """Best-effort unit query before profiling.

    This sends U,? only. It does not change the sensor unit setting.
    """

    units: dict[int, dict[str, Any]] = {}

    for address in addresses:
        command = command_for_address(address, "U,?", command_prefix)
        try:
            result = transport.transact(command)
            parsed = parse_addressed_reply(result.reply_text)
            if result.ok and parsed is not None:
                reply_addr, payload = parsed
                unit_code = parse_unit_code(payload)
                unit_symbol = unit_map.get(str(unit_code)) if unit_code is not None else None
                units[address] = {
                    "address": address,
                    "reply_address": reply_addr,
                    "unit_code": unit_code,
                    "unit_symbol": unit_symbol,
                    "raw_payload": payload,
                    "reply": result.reply_text.strip(),
                    "verified_by_command": "U,?",
                    "changed_during_profile": False,
                    "restored": True,
                    "status": "OK" if unit_code is not None else "ERR:invalid unit code",
                }
            else:
                units[address] = {
                    "address": address,
                    "unit_code": None,
                    "unit_symbol": None,
                    "raw_payload": None,
                    "reply": result.reply_text.strip(),
                    "verified_by_command": "U,?",
                    "changed_during_profile": False,
                    "restored": True,
                    "status": "ERR:unexpected reply",
                }
        except Exception as exc:
            units[address] = {
                "address": address,
                "unit_code": None,
                "unit_symbol": None,
                "raw_payload": None,
                "reply": "",
                "verified_by_command": "U,?",
                "changed_during_profile": False,
                "restored": True,
                "status": f"ERR:{exc}",
            }

    return units




def _query_unit_code(
    transport: SerialTransport,
    address: int,
    *,
    command_prefix: str,
) -> dict[str, Any]:
    """Query one sensor's current unit using U,?."""

    command = command_for_address(address, "U,?", command_prefix)
    result = transport.transact(command)
    parsed = parse_addressed_reply(result.reply_text)
    if not result.ok or parsed is None:
        return {
            "address": address,
            "unit_code": None,
            "raw_payload": None,
            "reply": result.reply_text.strip(),
            "status": "ERR:unexpected reply",
        }
    reply_addr, payload = parsed
    unit_code = parse_unit_code(payload)
    return {
        "address": address,
        "reply_address": reply_addr,
        "unit_code": unit_code,
        "raw_payload": payload,
        "reply": result.reply_text.strip(),
        "status": "OK" if unit_code is not None else "ERR:invalid unit code",
    }


def _set_unit_code(
    transport: SerialTransport,
    address: int,
    code: int,
    *,
    command_prefix: str,
) -> dict[str, Any]:
    """Set one sensor's unit code using U,<code> and return raw command result."""

    command = command_for_address(address, f"U,{code}", command_prefix)
    result = transport.transact(command)
    parsed = parse_addressed_reply(result.reply_text)
    payload = parsed[1] if parsed else result.reply_text.strip()
    return {
        "address": address,
        "requested_code": code,
        "reply_address": parsed[0] if parsed else None,
        "raw_payload": payload,
        "reply": result.reply_text.strip(),
        "status": "OK" if result.ok else "ERR:timeout",
    }


def probe_units_for_sensor(
    transport: SerialTransport,
    address: int,
    *,
    command_prefix: str,
    unit_map: dict[str, str],
    codes: list[int],
    logical_id: str | None = None,
    show_progress: bool = True,
) -> dict[str, Any]:
    """Verify unit codes for one sensor and restore the initial unit.

    The probe deliberately changes the sensor's active unit while testing. It
    therefore always attempts to restore the initial unit and then verifies
    the final unit with U,?.
    """

    label = logical_id or f"addr{address:02d}"
    if show_progress:
        print(f"  {label} / addr{address:02d}: query initial unit...", flush=True)
    initial = _query_unit_code(transport, address, command_prefix=command_prefix)
    if show_progress:
        print(
            f"  {label} / addr{address:02d}: initial unit="
            f"{initial.get('unit_code')} ({unit_map.get(str(initial.get('unit_code')), 'unknown')})",
            flush=True,
        )
    initial_code = initial.get("unit_code")
    results: dict[str, Any] = {}
    restore_result: dict[str, Any] | None = None
    final: dict[str, Any] | None = None

    try:
        for code in codes:
            symbol = unit_map.get(str(code))
            if show_progress:
                print(f"  {label} / addr{address:02d}: set U,{code} ({symbol or 'unknown'})...", end="", flush=True)
            set_result = _set_unit_code(
                transport,
                address,
                code,
                command_prefix=command_prefix,
            )
            verify = _query_unit_code(
                transport,
                address,
                command_prefix=command_prefix,
            )
            verified_code = verify.get("unit_code")
            # Some DPS sensors appear not to reply to U,<code> set commands,
            # but the setting is nevertheless applied. Treat the follow-up
            # U,? verification as the source of truth.
            accepted = verified_code == code
            if show_progress:
                set_status = set_result.get("status")
                verify_status = verify.get("status")
                marker = "OK" if accepted else "FAIL"
                print(
                    f" {marker} (set={set_status}, verify={verify_status}, readback={verified_code})",
                    flush=True,
                )
            results[str(code)] = {
                "code": code,
                "symbol": symbol,
                "accepted": accepted,
                "set_result": set_result,
                "verify_result": verify,
                "verification_policy": "accepted_if_followup_U_query_reports_requested_code",
                "status": "OK" if accepted else "ERR:not verified",
            }
    except Exception as exc:
        results["error"] = {"status": f"ERR:{exc}"}
    finally:
        if initial_code is not None:
            try:
                if show_progress:
                    print(f"  {label} / addr{address:02d}: restore U,{initial_code}...", end="", flush=True)
                restore_result = _set_unit_code(
                    transport,
                    address,
                    int(initial_code),
                    command_prefix=command_prefix,
                )
                final = _query_unit_code(
                    transport,
                    address,
                    command_prefix=command_prefix,
                )
                if show_progress:
                    final_code_for_print = final.get("unit_code") if isinstance(final, dict) else None
                    marker = "OK" if final_code_for_print == initial_code else "FAIL"
                    print(
                        f" {marker} (set={restore_result.get('status')}, final={final_code_for_print})",
                        flush=True,
                    )
            except Exception as exc:
                restore_result = {
                    "address": address,
                    "requested_code": initial_code,
                    "status": f"ERR:{exc}",
                }
                final = None

    final_code = final.get("unit_code") if isinstance(final, dict) else None
    restored = initial_code is not None and final_code == initial_code
    all_requested_codes_verified = all(
        isinstance(results.get(str(code)), dict) and results[str(code)].get("accepted") is True
        for code in codes
    )

    return {
        "address": address,
        "enabled": True,
        "codes_tested": codes,
        "initial_unit_code": initial_code,
        "initial_unit_symbol": unit_map.get(str(initial_code)) if initial_code is not None else None,
        "initial_query": initial,
        "probe_results": results,
        "restore_result": restore_result,
        "final_unit_code": final_code,
        "final_unit_symbol": unit_map.get(str(final_code)) if final_code is not None else None,
        "final_query": final,
        "restore_policy": "restore_initial_unit",
        "restored": restored,
        "changed_during_profile": True,
        "all_requested_codes_verified": all_requested_codes_verified,
        "status": "OK" if restored and all_requested_codes_verified else "ERR:unit probe incomplete",
    }


def probe_units_if_needed(
    transport: SerialTransport,
    effective: EffectiveConfig,
) -> tuple[dict[int, dict[str, Any]], list[int]]:
    """Probe unit codes for active sensors that do not already have verified mapping."""

    entries = extract_sensor_list(effective.raw_config)
    needed_addresses = unit_probe_needed_addresses(
        entries,
        effective.addresses,
        effective.unit_probe_codes,
        force=effective.force_unit_probe,
    )
    probe_results: dict[int, dict[str, Any]] = {}

    for address in needed_addresses:
        logical_id = effective.address_to_logical_id.get(address, f"p{address}")
        probe_results[address] = probe_units_for_sensor(
            transport,
            address,
            command_prefix=effective.command_prefix,
            unit_map=effective.unit_map,
            codes=effective.unit_probe_codes,
            logical_id=logical_id,
            show_progress=True,
        )

    return probe_results, needed_addresses


def units_from_probe_or_query(
    addresses: list[int],
    unit_queries: dict[int, dict[str, Any]],
    unit_probes: dict[int, dict[str, Any]],
    unit_map: dict[str, str],
) -> dict[int, dict[str, Any]]:
    """Build current-unit records, preferring verified final probe state."""

    units: dict[int, dict[str, Any]] = {}
    for address in addresses:
        probe = unit_probes.get(address)
        if probe and isinstance(probe.get("final_query"), dict):
            final_query = dict(probe["final_query"])
            code = final_query.get("unit_code")
            units[address] = {
                "address": address,
                "reply_address": final_query.get("reply_address"),
                "unit_code": code,
                "unit_symbol": unit_map.get(str(code)) if code is not None else None,
                "raw_payload": final_query.get("raw_payload"),
                "reply": final_query.get("reply", ""),
                "verified_by_command": "U,?",
                "changed_during_profile": True,
                "restored": bool(probe.get("restored")),
                "status": "OK" if probe.get("restored") else "ERR:not restored",
            }
            continue
        if address in unit_queries:
            units[address] = unit_queries[address]
    return units

def maybe_identify_sensors(
    transport: SerialTransport,
    addresses: list[int],
    *,
    command_prefix: str,
) -> dict[int, dict[str, Any]]:
    """Best-effort raw I-command metadata query before profiling."""

    identities: dict[int, dict[str, Any]] = {}

    for address in addresses:
        command = command_for_address(address, "I", command_prefix)
        try:
            result = transport.transact(command)
            parsed = parse_addressed_reply(result.reply_text)
            identities[address] = {
                "address": address,
                "identify_raw": result.reply_text.strip(),
                "payload": parsed[1] if parsed else result.reply_text.strip(),
                "status": "OK" if result.ok else "ERR:timeout",
            }
        except Exception as exc:
            identities[address] = {
                "address": address,
                "identify_raw": "",
                "payload": "",
                "status": f"ERR:{exc}",
            }

    return identities


def write_profile_json(
    out_dir: Path,
    filename_prefix: str,
    session_id: str,
    payload: dict[str, Any],
) -> Path | None:
    """Write profile JSON using the shared session id."""

    path = out_dir / f"{filename_prefix}_{session_id}.json"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as exc:
        print()
        print(f"WARNING: Could not write profile JSON: {path}")
        print(f"WARNING: {exc}")
        return None

    return path


def build_parser() -> argparse.ArgumentParser:
    """Build command-line parser."""

    parser = argparse.ArgumentParser(
        description="Profile DPS8000 RS-485 burst cycle timing."
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "DPS config JSON. If omitted, search order is "
            "./dps_config.json, ../dps_config.json, ../../dps_config.json. "
            "First match wins; no merge or inheritance is performed."
        ),
    )
    parser.add_argument("-p", "--port", default=None, help="Serial port, for example /dev/ttyUSB0")
    parser.add_argument("-b", "--baud", "--baudrate", dest="baudrate", type=int, default=None)
    parser.add_argument("-t", "--timeout", type=positive_float, default=None)
    parser.add_argument("-e", "--eol", choices=["cr", "lf", "crlf", "none"], default=None)
    parser.add_argument(
        "-P",
        "--command-prefix",
        default=None,
        help="Prefix before address; default is one leading space for DPS8000",
    )
    parser.add_argument(
        "-a",
        "--addresses",
        default=None,
        type=parse_addresses,
        help="Comma-separated active addresses, for example 1,2,3,4",
    )
    parser.add_argument(
        "-i",
        "--ids",
        "--logical-ids",
        default=None,
        help=(
            "Optional comma-separated active logical ids, for example p1,p2,p3,p4. "
            "With --addresses this names the provided addresses. Without --addresses, "
            "ids are selected from config."
        ),
    )
    parser.add_argument("-n", "--rounds", type=int, default=None)
    parser.add_argument(
        "-r",
        "--read",
        "--read-command",
        dest="read_command",
        choices=["G", "R", "*G", "*R"],
        default=None,
        help=(
            "Read command used for profiling. G requests a new reading and is "
            "the conservative DPS8000 default; R may return the current/latest reading faster."
        ),
    )
    parser.add_argument(
        "-g",
        "--command-gap",
        type=non_negative_float,
        default=None,
        help="Delay between burst commands in seconds",
    )
    parser.add_argument(
        "-c",
        "--collect-timeout",
        type=positive_float,
        default=None,
        help="Reply collection window per burst round in seconds",
    )
    parser.add_argument(
        "-s",
        "--settle",
        type=non_negative_float,
        default=None,
        help="Delay between profiling rounds in seconds",
    )
    parser.add_argument(
        "-m",
        "--collect-margin",
        type=non_negative_float,
        default=None,
        help="Safety margin added to worst latency for collect timeout recommendation",
    )
    parser.add_argument(
        "--cycle-margin",
        type=non_negative_float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-I",
        "--interval-presets",
        type=parse_interval_presets,
        default=None,
        help=(
            "Comma-separated practical interval presets in seconds. "
            "Default: 1,2,5,10,15,20,30,60"
        ),
    )
    parser.add_argument(
        "-o",
        "--base-dir",
        default=None,
        help="Output directory. Default: current working directory.",
    )
    parser.add_argument("-f", "--prefix", default=None, help="Output filename prefix")
    parser.add_argument(
        "--probe-units",
        nargs="?",
        const="0-5",
        default=None,
        help=(
            "Probe unit codes for active sensors. Default commissioning probe is 0-5. "
            "The profiler automatically probes sensors whose per-sensor 0-5 mapping is missing."
        ),
    )
    parser.add_argument(
        "--force-unit-probe",
        action="store_true",
        help="Probe unit codes even if config already contains verified per-sensor unit probe results.",
    )
    parser.add_argument("--no-identify", action="store_true", help="Do not run I metadata queries")
    parser.add_argument("--no-unit-query", action="store_true", help="Do not run U,? unit queries before probing")
    parser.add_argument("-v", "--print-replies", action="store_true", help="Print raw replies during profiling")
    return parser


def build_sensor_profile_block(
    effective: EffectiveConfig,
    summaries: dict[int, SensorTimingSummary],
    units: dict[int, dict[str, Any]],
    identities: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Build logical-id keyed sensor block for profile JSON."""

    sensors: dict[str, Any] = {}
    for address in effective.addresses:
        logical_id = effective.address_to_logical_id[address]
        unit_data = units.get(address, {})
        identity_data = identities.get(address, {})
        sensors[logical_id] = {
            "address": address,
            "unit": unit_data or None,
            "identity": identity_data or None,
            "timing": asdict(summaries[address]),
        }
    return sensors


def run_profile(args: argparse.Namespace) -> int:
    """Run burst timing profiling and write profile JSON."""

    try:
        effective = resolve_effective_config(args)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2

    if effective.rounds <= 0:
        print("ERROR: --rounds must be > 0")
        return 2

    session_id = make_session_id()
    profile_started_at = iso_now()
    profile_start_perf = time.perf_counter()

    transport_cfg = SerialTransportConfig(
        port=effective.port,
        baud=effective.baudrate,
        timeout_s=effective.timeout_s,
        write_sleep_s=0.0,
        eol=effective.eol,
        reset_input_before_cmd=False,
    )

    transport = SerialTransport(transport_cfg)
    per_round: list[dict[int, BurstReply]] = []
    unexpected_by_round: list[list[str]] = []

    print(f"{PROGRAM_NAME} v{PROGRAM_VERSION}")
    print(f"Session ID: {session_id}")
    if effective.config_path is not None:
        print(f"Config: {effective.config_path}")
    else:
        print("Config: not found; using CLI/defaults")
        print("Config search order:")
        for path in effective.config_search_paths:
            print(f"  {path}")
    print(f"Port: {effective.port}, baudrate: {effective.baudrate}, EOL: {effective.eol}")
    print(
        "Sensors: "
        + ", ".join(
            f"{effective.address_to_logical_id[a]}=addr{a:02d}" for a in effective.addresses
        )
    )
    print(f"Read command: {effective.read_command}")
    print(f"Command prefix: {effective.command_prefix!r}")
    print(f"Rounds: {effective.rounds}")
    print(f"Command gap: {effective.command_gap_s:.3f} s")
    print(f"Collect timeout: {effective.collect_timeout_s:.3f} s")
    print("Interval presets: " + ", ".join(f"{preset:g}s" for preset in effective.interval_presets_s))
    print("Unit probe codes: " + ", ".join(str(code) for code in effective.unit_probe_codes))

    units: dict[int, dict[str, Any]] = {}
    unit_queries: dict[int, dict[str, Any]] = {}
    unit_probes: dict[int, dict[str, Any]] = {}
    unit_probe_needed: list[int] = []
    identities: dict[int, dict[str, Any]] = {}

    try:
        with transport.opened():
            if not args.no_unit_query:
                unit_queries = maybe_query_units(
                    transport,
                    effective.addresses,
                    command_prefix=effective.command_prefix,
                    unit_map=effective.unit_map,
                )

            unit_probes, unit_probe_needed = probe_units_if_needed(transport, effective)
            if unit_probe_needed:
                print("Unit probe completed.", flush=True)
            units = units_from_probe_or_query(
                effective.addresses,
                unit_queries,
                unit_probes,
                effective.unit_map,
            )

            if not args.no_identify:
                identities = maybe_identify_sensors(
                    transport,
                    effective.addresses,
                    command_prefix=effective.command_prefix,
                )

            for round_index in range(1, effective.rounds + 1):
                replies, unexpected = collect_burst_round(
                    transport,
                    effective.addresses,
                    read_command=effective.read_command,
                    command_prefix=effective.command_prefix,
                    command_gap_s=effective.command_gap_s,
                    collect_timeout_s=effective.collect_timeout_s,
                    round_index=round_index,
                )
                per_round.append(replies)
                unexpected_by_round.append(unexpected)

                parts: list[str] = []
                for address in effective.addresses:
                    logical_id = effective.address_to_logical_id[address]
                    reply = replies.get(address)
                    if reply is None:
                        parts.append(f"{logical_id}=MISS")
                    else:
                        parts.append(f"{logical_id}={reply.latency_s:.3f}s")

                print(f"Round {round_index:02d}: " + "  ".join(parts))

                if args.print_replies:
                    for address in effective.addresses:
                        reply = replies.get(address)
                        if reply is not None:
                            logical_id = effective.address_to_logical_id[address]
                            print(f"  {logical_id} / addr{address:02d}: {reply.reply_text}")
                    for line in unexpected:
                        print(f"  unexpected: {line}")

                if effective.settle_s > 0 and round_index < effective.rounds:
                    time.sleep(effective.settle_s)

    except SerialTransportError as exc:
        print(f"ERROR: {exc}")
        return 2

    elapsed_s = time.perf_counter() - profile_start_perf
    completed_rounds = len(per_round)

    summaries = summarize_sensor_timing(
        effective.addresses,
        effective.address_to_logical_id,
        per_round,
    )
    recommendations = make_recommendations(
        summaries,
        collect_margin_s=effective.collect_margin_s,
        interval_presets_s=effective.interval_presets_s,
    )

    sensors_block = build_sensor_profile_block(effective, summaries, units, identities)

    profile_payload: dict[str, Any] = {
        "program": PROGRAM_NAME,
        "version": PROGRAM_VERSION,
        "profiled_at": profile_started_at,
        "session_id": session_id,
        "config": {
            "path": str(effective.config_path) if effective.config_path is not None else None,
            "search_order": [str(path) for path in effective.config_search_paths],
            "resolution_policy": "first_match_wins_no_merge_no_inheritance",
        },
        "transport": {
            "port": effective.port,
            "baudrate": effective.baudrate,
            "timeout_s": effective.timeout_s,
            "timeout": effective.timeout_s,
            "eol": effective.eol,
            "command_prefix": effective.command_prefix,
        },
        "readout": {
            "read_mode": "burst",
            "read_command": effective.read_command,
            "command_gap_s": effective.command_gap_s,
            "collect_timeout_s": effective.collect_timeout_s,
            "rounds_requested": effective.rounds,
            "rounds_completed": completed_rounds,
            "settle_s": effective.settle_s,
            "collect_margin_s": effective.collect_margin_s,
        },
        "sensors": sensors_block,
        "unit_map": {
            "source": (
                "verified_by_unit_probe"
                if unit_probes
                else effective.unit_map_source
            ),
            "codes": effective.unit_map,
            "verified_codes": effective.unit_probe_codes,
        },
        "units": {
            "unit_map_source": (
                "verified_by_unit_probe"
                if unit_probes
                else effective.unit_map_source
            ),
            "unit_map": effective.unit_map,
            "queried_units": not args.no_unit_query,
            "probe_units": bool(unit_probes),
            "probe_policy": "probe_missing_per_sensor_unit_map_0_5",
            "probe_required_for_addresses": [
                effective.address_to_logical_id[address] for address in unit_probe_needed
            ],
            "codes_tested": effective.unit_probe_codes,
            "all_probed_sensors_restored": all(
                probe.get("restored") is True for probe in unit_probes.values()
            ) if unit_probes else True,
            "all_requested_codes_verified": all(
                probe.get("all_requested_codes_verified") is True for probe in unit_probes.values()
            ) if unit_probes else True,
            "sensors": {
                effective.address_to_logical_id[address]: data for address, data in units.items()
            },
            "unit_probe": {
                effective.address_to_logical_id[address]: data
                for address, data in unit_probes.items()
            },
        },
        "identities": {
            effective.address_to_logical_id[address]: data for address, data in identities.items()
        },
        "timing": {
            "sensor_timing": {
                effective.address_to_logical_id[address]: asdict(summary)
                for address, summary in summaries.items()
            },
            "recommendations": asdict(recommendations),
        },
        "elapsed_s": elapsed_s,
        "elapsed_human": format_seconds(elapsed_s),
        "raw_rounds": [
            {
                effective.address_to_logical_id[address]: asdict(reply)
                for address, reply in sorted(round_data.items())
            }
            for round_data in per_round
        ],
        "unexpected_lines": unexpected_by_round,
        "notes": [
            "Unit code is recorded from U,? when available; do not infer active unit from I metadata.",
            "Unit map truth source is JSON after commissioning; sensors without verified per-sensor unit mapping are probed for codes 0-5.",
            "Unit probing changes sensor units during the test, then restores each sensor to its initial unit and verifies restoration with U,?.",
            "G and R are profiled separately because G likely requests a new measurement while R may read the current/latest value.",
            "recommended_minimum_interval_s is a conservative per-sensor value derived from measured max latency plus margin.",
            "recommended_collect_timeout_s is rounded from worst latency plus collect margin.",
            "recommended_interval_s is the next practical preset at or above the collect timeout.",
            "Config files are not modified by this profiler.",
            "Config resolution uses first match only: CWD, parent, grandparent; no merge or inheritance.",
        ],
        # Backward-compatible top-level fields retained for older readers.
        "read_mode": "burst",
        "read_command": effective.read_command,
        "command_prefix": effective.command_prefix,
        "addresses": effective.addresses,
        "logical_ids": {
            str(address): logical_id for address, logical_id in effective.address_to_logical_id.items()
        },
        "command_gap_s": effective.command_gap_s,
        "collect_timeout_s": effective.collect_timeout_s,
        "rounds_requested": effective.rounds,
        "rounds_completed": completed_rounds,
        "rounds": completed_rounds,
        "interval_presets_s": effective.interval_presets_s,
        "sensor_timing": {
            str(address): asdict(summary) for address, summary in summaries.items()
        },
        "recommendations": asdict(recommendations),
    }

    profile_path = write_profile_json(
        effective.out_dir,
        effective.filename_prefix,
        session_id,
        profile_payload,
    )

    print()
    if unit_probes:
        print("Unit probe:")
        for address in effective.addresses:
            logical_id = effective.address_to_logical_id[address]
            probe = unit_probes.get(address)
            if probe is None:
                print(f"  {logical_id} / addr{address:02d}: already available in config")
                continue
            status = probe.get("status")
            restored = probe.get("restored")
            verified = probe.get("all_requested_codes_verified")
            final_code = probe.get("final_unit_code")
            final_symbol = probe.get("final_unit_symbol")
            print(
                f"  {logical_id} / addr{address:02d}: "
                f"status={status}, verified={verified}, restored={restored}, "
                f"final_unit={final_code} ({final_symbol})"
            )

    print()
    print("Summary:")
    print(f"  Rounds requested: {effective.rounds}")
    print(f"  Rounds completed: {completed_rounds}")
    print(f"  Time elapsed: {format_seconds(elapsed_s)} ({elapsed_s:.3f} s)")
    for address in effective.addresses:
        summary = summaries[address]
        logical_id = effective.address_to_logical_id[address]
        unit_data = units.get(address)
        unit_text = ""
        if unit_data and unit_data.get("unit_symbol"):
            unit_text = f", unit={unit_data['unit_symbol']}"
        elif unit_data and unit_data.get("unit_code") is not None:
            unit_text = f", unit_code={unit_data['unit_code']}"

        if summary.max_latency_s is None:
            print(
                f"  {logical_id} / addr{address:02d}: "
                f"no replies ({summary.missing}/{completed_rounds} missing){unit_text}"
            )
            continue
        print(
            f"  {logical_id} / addr{address:02d}: "
            f"min={summary.min_latency_s:.3f}s "
            f"avg={summary.avg_latency_s:.3f}s "
            f"max={summary.max_latency_s:.3f}s "
            f"missing={summary.missing} "
            f"recommended_minimum_interval={summary.recommended_minimum_interval_s:.1f}s"
            f"{unit_text}"
        )

    print()
    if recommendations.worst_latency_s is not None:
        slowest_id = effective.address_to_logical_id.get(recommendations.slowest_address or -1, "n/a")
        print(f"Slowest sensor: {slowest_id} / addr{recommendations.slowest_address:02d}")
        print(f"Worst latency: {recommendations.worst_latency_s:.3f} s")
    else:
        print("Slowest sensor: n/a")
        print("Worst latency: n/a")
    print(f"Recommended collect timeout: {recommendations.recommended_collect_timeout_s:.1f} s")
    print(f"Recommended interval: {recommendations.recommended_interval_s:.1f} s")
    print(
        "Interval presets: "
        + ", ".join(f"{preset:g}s" for preset in recommendations.interval_presets_s)
    )
    if recommendations.too_short_interval_presets_s:
        print(
            "Too short for this setup: "
            + ", ".join(f"{preset:g}s" for preset in recommendations.too_short_interval_presets_s)
        )
    if profile_path is None:
        print("Profile JSON: not written")
    else:
        print(f"Profile JSON: {profile_path}")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Ctrl+C is a normal way to stop profiling, especially when the profiler is
    launched automatically by dps-logger. Handle KeyboardInterrupt here so the
    user does not see a Python traceback from deep inside serial polling or
    sleep calls.
    """

    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        return run_profile(args)
    except KeyboardInterrupt:
        print("\nTermination requested (Ctrl+C). Exiting...", file=sys.stderr)
        return 130
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
