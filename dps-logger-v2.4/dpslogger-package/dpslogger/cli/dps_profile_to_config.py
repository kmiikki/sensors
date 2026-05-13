#!/usr/bin/env python3
"""Create or update dps_config.json from a dps_profile_<session>.json file.

This tool is intentionally offline: it does not talk to sensors. It imports a
known-good commissioning/profile JSON into the persistent dpslogger config.

Policy:
- dps_profile_*.json is an audit trail / measured commissioning result.
- dps_config.json is the persistent truth used by dpslogger.
- Existing config files are backed up before modification.
- Writes are atomic: write *.tmp first, then replace target config.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from dpslogger import __version__

DEFAULT_CONFIG_NAME = "dps_config.json"
DEFAULT_INTERVAL_S = 10.0
DEFAULT_COLLECT_TIMEOUT_S = 5.0
DEFAULT_UNIT_MAP = {
    "0": "mbar",
    "1": "Pa",
    "2": "kPa",
    "3": "MPa",
    "4": "hPa",
    "5": "bar",
}

IDENTITY_RE = re.compile(r"^(?P<series>\d+),(?P<serial>[^,]+),(?P<rest>.*)$")


class ConfigBuildError(RuntimeError):
    """Raised when profile JSON cannot be converted safely."""


def iso_now() -> str:
    """Return local ISO 8601 timestamp."""

    return datetime.now().astimezone().isoformat()


def make_backup_suffix() -> str:
    """Return timestamp suffix suitable for backup filenames."""

    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from path."""

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as exc:
        raise ConfigBuildError(f"Could not read JSON file: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigBuildError(f"Invalid JSON file: {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigBuildError(f"Expected JSON object in {path}")
    return data


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically by writing to a temporary file first."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, path)


def backup_existing_config(path: Path) -> Path | None:
    """Back up existing config next to itself. Return backup path or None."""

    if not path.exists():
        return None

    backup_path = path.with_name(f"{path.name}.bak-{make_backup_suffix()}")
    backup_path.write_bytes(path.read_bytes())
    return backup_path


def get_nested(data: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    """Safely read a nested dict path."""

    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def coalesce(*values: Any, default: Any = None) -> Any:
    """Return the first value that is not None."""

    for value in values:
        if value is not None:
            return value
    return default


def parse_identity(identity: dict[str, Any] | None) -> dict[str, Any]:
    """Parse a small subset of the raw I-command identity payload.

    The raw identity string remains the authoritative metadata in the config.
    Parsed fields are convenience metadata only.
    """

    if not identity:
        return {}

    payload = str(identity.get("payload") or "").strip()
    raw = str(identity.get("identify_raw") or "").strip()
    result: dict[str, Any] = {}

    if raw:
        result["identity_raw"] = raw
    if payload:
        result["identity_payload"] = payload
        match = IDENTITY_RE.match(payload)
        if match:
            result["model"] = match.group("series")
            result["series"] = match.group("series")
            result["serial_number"] = match.group("serial").strip()

            parts = payload.split(",")
            if len(parts) >= 8:
                # Keep these as strings because their exact semantics are model-specific.
                result["identity_fields"] = {
                    "series": parts[0],
                    "serial_number": parts[1],
                    "firmware_or_date_fields_raw": parts[6:8],
                }
    return result


def normalized_unit_map(profile: dict[str, Any]) -> dict[str, Any]:
    """Return unit_map block for config."""

    profile_unit_map = profile.get("unit_map")
    units_unit_map = get_nested(profile, ("units", "unit_map"))

    codes = None
    source = None
    verified_codes = None

    if isinstance(profile_unit_map, dict):
        codes = profile_unit_map.get("codes")
        source = profile_unit_map.get("source")
        verified_codes = profile_unit_map.get("verified_codes")

    if codes is None and isinstance(units_unit_map, dict):
        codes = units_unit_map
        source = get_nested(profile, ("units", "unit_map_source"))

    if not isinstance(codes, dict):
        codes = DEFAULT_UNIT_MAP
        source = "default_fallback_used_by_importer"

    string_codes = {str(key): str(value) for key, value in codes.items()}

    block: dict[str, Any] = {
        "source": source or "profile",
        "codes": string_codes,
    }
    if verified_codes is not None:
        block["verified_codes"] = verified_codes

    # Promote successful unit probe status to make config validation simple.
    if get_nested(profile, ("units", "probe_units")) is True:
        block["probe_units"] = True
        block["all_requested_codes_verified"] = bool(
            get_nested(profile, ("units", "all_requested_codes_verified"), False)
        )
        block["all_probed_sensors_restored"] = bool(
            get_nested(profile, ("units", "all_probed_sensors_restored"), False)
        )
        block["probe_policy"] = get_nested(profile, ("units", "probe_policy"))

    return block


def sensor_blocks_from_profile(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Build config sensors list from profile JSON."""

    sensors = profile.get("sensors")
    if not isinstance(sensors, dict) or not sensors:
        raise ConfigBuildError("Profile does not contain sensors object")

    unit_probe = get_nested(profile, ("units", "unit_probe"), {})
    if not isinstance(unit_probe, dict):
        unit_probe = {}

    result: list[dict[str, Any]] = []

    for logical_id, sensor in sensors.items():
        if not isinstance(sensor, dict):
            continue

        address = sensor.get("address")
        if address is None:
            raise ConfigBuildError(f"Sensor {logical_id!r} is missing address")

        unit = sensor.get("unit") if isinstance(sensor.get("unit"), dict) else {}
        identity = sensor.get("identity") if isinstance(sensor.get("identity"), dict) else {}
        timing = sensor.get("timing") if isinstance(sensor.get("timing"), dict) else {}

        parsed_identity = parse_identity(identity)

        block: dict[str, Any] = {
            "id": str(logical_id),
            "address": address,
            "enabled": True,
            "unit_code": unit.get("unit_code"),
            "unit_symbol": unit.get("unit_symbol"),
            "unit_verified_by_command": unit.get("verified_by_command", "U,?"),
            "minimum_interval_s": timing.get("recommended_minimum_interval_s"),
            "timing": {
                "profiled_replies": timing.get("replies"),
                "missing": timing.get("missing"),
                "success_rate": timing.get("success_rate"),
                "min_latency_s": timing.get("min_latency_s"),
                "avg_latency_s": timing.get("avg_latency_s"),
                "median_latency_s": timing.get("median_latency_s"),
                "max_latency_s": timing.get("max_latency_s"),
                "recommended_minimum_interval_s": timing.get("recommended_minimum_interval_s"),
            },
        }

        block.update(parsed_identity)

        probe = unit_probe.get(str(logical_id))
        if isinstance(probe, dict):
            block["unit_probe"] = {
                "codes_tested": probe.get("codes_tested"),
                "all_requested_codes_verified": probe.get("all_requested_codes_verified"),
                "restored": probe.get("restored"),
                "restore_policy": probe.get("restore_policy"),
                "initial_unit_code": probe.get("initial_unit_code"),
                "final_unit_code": probe.get("final_unit_code"),
                "verification_policy": "accepted_if_followup_U_query_reports_requested_code",
            }

        # Remove None values from shallow timing block for readability.
        block["timing"] = {
            key: value for key, value in block["timing"].items() if value is not None
        }
        block = {key: value for key, value in block.items() if value is not None}
        result.append(block)

    result.sort(key=lambda item: (int(item.get("address", 9999)), str(item.get("id", ""))))
    return result


def build_config_from_profile(
    profile: dict[str, Any],
    *,
    profile_path: Path,
    interval_s: float,
    collect_timeout_s: float | None,
    existing_config: dict[str, Any] | None = None,
    merge_existing: bool = True,
) -> dict[str, Any]:
    """Build final dps_config.json payload."""

    base: dict[str, Any]
    if existing_config is not None and merge_existing:
        base = copy.deepcopy(existing_config)
    else:
        base = {}

    profiled_at = profile.get("profiled_at")
    session_id = profile.get("session_id")
    recommendations = get_nested(profile, ("timing", "recommendations"), {})
    if not isinstance(recommendations, dict):
        recommendations = profile.get("recommendations", {}) if isinstance(profile.get("recommendations"), dict) else {}

    transport = profile.get("transport") if isinstance(profile.get("transport"), dict) else {}
    readout = profile.get("readout") if isinstance(profile.get("readout"), dict) else {}

    chosen_collect_timeout = coalesce(
        collect_timeout_s,
        readout.get("collect_timeout_s"),
        DEFAULT_COLLECT_TIMEOUT_S,
    )

    # Use explicit interval argument by default. The profile's recommended interval
    # can be too aggressive for production; keep it as recommendation metadata.
    chosen_interval = interval_s

    base.update(
        {
            "program": "dpslogger",
            "config_version": __version__,
            "created_or_updated_at": iso_now(),
            "created_or_updated_from_profile": profile_path.name,
            "profile_session_id": session_id,
            "profiled_at": profiled_at,
            "config_policy": {
                "resolution": "first_match_wins_no_merge_no_inheritance",
                "unit_map_truth_source": "dps_config.json",
                "profile_json_role": "audit_trail_and_commissioning_measurement",
            },
            "transport": {
                "port": transport.get("port"),
                "baudrate": transport.get("baudrate", 9600),
                "timeout_s": transport.get("timeout_s", transport.get("timeout", 1.0)),
                "eol": transport.get("eol", "cr"),
                "command_prefix": transport.get("command_prefix", " "),
            },
            "readout": {
                "read_mode": readout.get("read_mode", profile.get("read_mode", "burst")),
                "read_command": readout.get("read_command", profile.get("read_command", "G")),
                "command_gap_s": readout.get("command_gap_s", profile.get("command_gap_s", 0.06)),
                "collect_timeout_s": chosen_collect_timeout,
                "interval_s": chosen_interval,
                "interval_policy": "warn",
            },
            "unit_map": normalized_unit_map(profile),
            "sensors": sensor_blocks_from_profile(profile),
            "profile": {
                "last_profile_file": profile_path.name,
                "last_profile_session_id": session_id,
                "last_profiled_at": profiled_at,
                "last_imported_at": iso_now(),
                "recommendations": recommendations,
            },
        }
    )

    # Drop null transport port only if missing. Usually it should always be present.
    base["transport"] = {k: v for k, v in base["transport"].items() if v is not None}
    return base


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or update dps_config.json from a dps_profile_<session>.json file."
    )
    parser.add_argument(
        "profile",
        nargs="?",
        type=Path,
        help="Input dps_profile_<session>.json file",
    )
    parser.add_argument(
        "--profile",
        dest="profile_opt",
        type=Path,
        help="Input dps_profile_<session>.json file; alternative to positional argument",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path(DEFAULT_CONFIG_NAME),
        help="Output config path. Default: ./dps_config.json",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_S,
        help="Production logging interval_s to write. Default: 10.0",
    )
    parser.add_argument(
        "--collect-timeout",
        type=float,
        default=None,
        help="Override collect_timeout_s. Default: use profile value, normally 5.0 in current workflow.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace config instead of merging/updating existing top-level config fields.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not back up existing config before writing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print config JSON to stdout instead of writing a file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    profile_path = args.profile_opt or args.profile
    if profile_path is None:
        parser.error("profile JSON file is required")

    profile_path = profile_path.expanduser().resolve()
    config_path = args.config.expanduser().resolve()

    try:
        profile = load_json(profile_path)
        existing_config = load_json(config_path) if config_path.exists() else None
        config = build_config_from_profile(
            profile,
            profile_path=profile_path,
            interval_s=args.interval,
            collect_timeout_s=args.collect_timeout,
            existing_config=existing_config,
            merge_existing=not args.replace,
        )

        if args.dry_run:
            json.dump(config, sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
            return 0

        backup_path = None
        if existing_config is not None and not args.no_backup:
            backup_path = backup_existing_config(config_path)

        write_json_atomic(config_path, config)

    except ConfigBuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: File operation failed: {exc}", file=sys.stderr)
        return 2

    print(f"Profile: {profile_path}")
    if backup_path is not None:
        print(f"Backup:  {backup_path}")
    print(f"Config:  {config_path}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
