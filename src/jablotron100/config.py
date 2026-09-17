"""Standalone TOML configuration and Home Assistant config-entry importer."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from .errors import ConfigurationError


class DeviceType(StrEnum):
    KEYPAD = "keypad"
    KEYPAD_WITH_DOOR_OPENING_DETECTOR = "keypad_with_door_opening_detector"
    SIREN_OUTDOOR = "outdoor_siren"
    SIREN_INDOOR = "indoor_siren"
    MOTION_DETECTOR = "motion_detector"
    WINDOW_OPENING_DETECTOR = "window_opening_detector"
    DOOR_OPENING_DETECTOR = "door_opening_detector"
    GARAGE_DOOR_OPENING_DETECTOR = "garage_door_opening_detector"
    GLASS_BREAK_DETECTOR = "glass_break_detector"
    SMOKE_DETECTOR = "smoke_detector"
    FLOOD_DETECTOR = "flood_detector"
    GAS_DETECTOR = "gas_detector"
    THERMOSTAT = "thermostat"
    THERMOMETER = "thermometer"
    LOCK = "lock"
    TAMPER = "tamper"
    BUTTON = "button"
    KEY_FOB = "key_fob"
    ELECTRICITY_METER_WITH_PULSE_OUTPUT = "electricity_meter_with_pulse_output"
    RADIO_MODULE = "radio_module"
    VALVE = "valve"
    CUSTOM = "custom"
    OTHER = "other"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class DeviceDefinition:
    number: int
    device_type: DeviceType
    name: str | None = None


@dataclass(frozen=True, slots=True)
class JablotronConfig:
    serial_port: str = "auto"
    code: str | None = field(default=None, repr=False)
    code_env: str | None = "JABLOTRON_CODE"
    devices: tuple[DeviceDefinition, ...] = ()
    number_of_pg_outputs: int = 0
    partially_arming_mode: str = "night_mode"
    require_code_to_arm: bool = False
    require_code_to_disarm: bool = True
    source_entry_id: str | None = None

    @property
    def number_of_devices(self) -> int:
        return len(self.devices)

    def redacted_dict(self) -> dict[str, Any]:
        return {
            "serial_port": self.serial_port,
            "code_env": self.code_env,
            "number_of_devices": self.number_of_devices,
            "number_of_pg_outputs": self.number_of_pg_outputs,
            "devices": [device.device_type.value for device in self.devices],
            "partially_arming_mode": self.partially_arming_mode,
            "require_code_to_arm": self.require_code_to_arm,
            "require_code_to_disarm": self.require_code_to_disarm,
            "source_entry_id": self.source_entry_id,
        }

    def resolve_code(self) -> str | None:
        """Return the configured code, preferring its environment variable."""
        if self.code_env:
            value = os.environ.get(self.code_env)
            if value:
                return value
        return self.code


def load_config(path: str | Path) -> JablotronConfig:
    """Load the human-editable standalone TOML configuration."""
    source = Path(path)
    try:
        document = tomllib.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigurationError(f"cannot read configuration: {source}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"invalid TOML configuration: {source}") from error

    connection = _mapping(document.get("connection", {}), "connection")
    system = _mapping(document.get("system", {}), "system")
    security = _mapping(document.get("security", {}), "security")
    raw_devices = document.get("devices", [])
    if not isinstance(raw_devices, list):
        raise ConfigurationError("devices must be an array of tables")

    by_number: dict[int, DeviceDefinition] = {}
    for item in raw_devices:
        values = _mapping(item, "each device")
        number = _as_int(values.get("number"), "device number")
        if not 1 <= number <= 230:
            raise ConfigurationError("device number must be between 1 and 230")
        if number in by_number:
            raise ConfigurationError(f"duplicate device number: {number}")
        try:
            device_type = DeviceType(values.get("type"))
        except (TypeError, ValueError) as error:
            raise ConfigurationError(
                f"unknown device type for device {number}: {values.get('type')!r}"
            ) from error
        by_number[number] = DeviceDefinition(
            number, device_type, _optional_string(values.get("name"))
        )

    configured_count = _as_int(
        system.get("number_of_devices", max(by_number, default=0)),
        "number_of_devices",
    )
    pg_outputs = _as_int(
        system.get("number_of_pg_outputs", 0), "number_of_pg_outputs"
    )
    if not 0 <= configured_count <= 230:
        raise ConfigurationError("number_of_devices must be between 0 and 230")
    if not 0 <= pg_outputs <= 128:
        raise ConfigurationError("number_of_pg_outputs must be between 0 and 128")
    if any(number > configured_count for number in by_number):
        raise ConfigurationError("device number exceeds number_of_devices")

    devices = tuple(
        by_number.get(number, DeviceDefinition(number, DeviceType.EMPTY))
        for number in range(1, configured_count + 1)
    )
    code = connection.get("code")
    code_env = connection.get("code_env", "JABLOTRON_CODE")
    if code is not None and not isinstance(code, str):
        raise ConfigurationError("connection.code must be a string")
    if code_env is not None and not isinstance(code_env, str):
        raise ConfigurationError("connection.code_env must be a string")

    return JablotronConfig(
        serial_port=str(connection.get("port", "auto")),
        code=code,
        code_env=code_env,
        devices=devices,
        number_of_pg_outputs=pg_outputs,
        partially_arming_mode=str(
            security.get("partially_arming_mode", "night_mode")
        ),
        require_code_to_arm=bool(security.get("require_code_to_arm", False)),
        require_code_to_disarm=bool(
            security.get("require_code_to_disarm", True)
        ),
    )


def save_config(
    config: JablotronConfig,
    path: str | Path,
    *,
    include_code: bool = False,
) -> None:
    """Write a sparse TOML configuration; empty device slots are omitted."""
    lines = [
        "# Jablotron100-standalone configuration",
        "[connection]",
        f"port = {_toml_string(config.serial_port)}",
    ]
    code_env = config.code_env or ("JABLOTRON_CODE" if not include_code else None)
    if code_env:
        lines.append(f"code_env = {_toml_string(code_env)}")
    if include_code and config.code:
        lines.append(f"code = {_toml_string(config.code)}")
    lines.extend(
        [
            "",
            "[system]",
            f"number_of_devices = {config.number_of_devices}",
            f"number_of_pg_outputs = {config.number_of_pg_outputs}",
            "",
            "[security]",
            f"partially_arming_mode = {_toml_string(config.partially_arming_mode)}",
            f"require_code_to_arm = {str(config.require_code_to_arm).lower()}",
            f"require_code_to_disarm = {str(config.require_code_to_disarm).lower()}",
        ]
    )
    for device in config.devices:
        if device.device_type is DeviceType.EMPTY:
            continue
        lines.extend(
            [
                "",
                "[[devices]]",
                f"number = {device.number}",
                f"type = {_toml_string(device.device_type.value)}",
            ]
        )
        if device.name:
            lines.append(f"name = {_toml_string(device.name)}")
    try:
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as error:
        raise ConfigurationError(f"cannot write configuration: {path}") from error


def load_home_assistant_config(
    path: str | Path,
    *,
    entry_id: str | None = None,
) -> JablotronConfig:
    """Load Jablotron settings from core.config_entries or a filtered export."""
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigurationError(f"cannot read configuration: {source}") from error
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"invalid JSON configuration: {source}") from error

    entry = _select_entry(document, entry_id)
    data = entry.get("data", entry)
    options = entry.get("options", {})
    if not isinstance(data, Mapping) or not isinstance(options, Mapping):
        raise ConfigurationError("configuration data and options must be objects")

    raw_devices = data.get("devices", [])
    if not isinstance(raw_devices, list):
        raise ConfigurationError("devices must be a list")
    configured_count = _as_int(
        data.get("number_of_devices", len(raw_devices)),
        "number_of_devices",
    )
    if configured_count != len(raw_devices):
        raise ConfigurationError(
            "number_of_devices does not match the length of devices"
        )

    devices: list[DeviceDefinition] = []
    for index, value in enumerate(raw_devices, start=1):
        try:
            device_type = DeviceType(value)
        except (TypeError, ValueError) as error:
            raise ConfigurationError(
                f"unknown device type at position {index}: {value!r}"
            ) from error
        devices.append(DeviceDefinition(index, device_type))

    pg_outputs = _as_int(data.get("number_of_pg_outputs", 0), "number_of_pg_outputs")
    if not 0 <= configured_count <= 230:
        raise ConfigurationError("number_of_devices must be between 0 and 230")
    if not 0 <= pg_outputs <= 128:
        raise ConfigurationError("number_of_pg_outputs must be between 0 and 128")

    code = data.get("password")
    if code is not None and not isinstance(code, str):
        raise ConfigurationError("password must be a string")

    return JablotronConfig(
        serial_port=str(data.get("serial_port", "auto")),
        code=code,
        code_env=None,
        devices=tuple(devices),
        number_of_pg_outputs=pg_outputs,
        partially_arming_mode=str(
            options.get("partially_arming_mode", "night_mode")
        ),
        require_code_to_arm=bool(options.get("require_code_to_arm", False)),
        require_code_to_disarm=bool(options.get("require_code_to_disarm", True)),
        source_entry_id=_optional_string(entry.get("entry_id")),
    )


def _select_entry(document: Any, entry_id: str | None) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise ConfigurationError("configuration root must be an object")

    stored_data = document.get("data")
    if isinstance(stored_data, Mapping) and isinstance(
        stored_data.get("entries"), list
    ):
        candidates = [
            entry
            for entry in stored_data["entries"]
            if isinstance(entry, Mapping)
            and entry.get("domain") == "jablotron100"
            and (entry_id is None or entry.get("entry_id") == entry_id)
        ]
    elif document.get("domain") == "jablotron100":
        candidates = [document]
    elif "devices" in document or "number_of_devices" in document:
        candidates = [document]
    else:
        candidates = []

    if not candidates:
        suffix = f" with entry_id {entry_id!r}" if entry_id else ""
        raise ConfigurationError(f"Jablotron config entry not found{suffix}")
    if len(candidates) > 1:
        raise ConfigurationError(
            "multiple Jablotron entries found; select one with entry_id"
        )
    return candidates[0]


def _as_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ConfigurationError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"{name} must be an integer") from error


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{name} must be a table")
    return value


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
