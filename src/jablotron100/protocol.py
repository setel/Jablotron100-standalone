"""Jablotron 100+ packet encoding shared with the upstream HA integration."""

from __future__ import annotations

from collections.abc import Iterable

from .errors import ProtocolError
from .models import ArmMode

STREAM_PACKET_SIZE = 64
EMPTY_PACKET = b"\x00"

PACKET_COMMAND = b"\x52"
PACKET_UI_CONTROL = b"\x80"
PACKET_GET_SYSTEM_INFO = b"\x30"
PACKET_DIAGNOSTICS = b"\x94"
PACKET_DIAGNOSTICS_COMMAND = b"\x96"
PACKET_GET_DEVICES_SECTIONS = b"\x3a"

COMMAND_HEARTBEAT = b"\x02"
COMMAND_GET_DEVICE_STATUS = b"\x0a"
COMMAND_GET_SECTIONS_AND_PG_OUTPUTS_STATES = b"\x0e"
COMMAND_ENABLE_DEVICE_STATE_PACKETS = b"\x13"

UI_CONTROL_AUTHORISATION_END = b"\x01"
UI_CONTROL_AUTHORISATION_CODE = b"\x03"
UI_CONTROL_MODIFY_SECTION = b"\x0d"
UI_CONTROL_TOGGLE_PG_OUTPUT = b"\x23"

TIMEOUT_FOR_DEVICE_STATE_PACKETS = 5

SYSTEM_INFO_MODEL = 2
SYSTEM_INFO_HARDWARE_VERSION = 8
SYSTEM_INFO_FIRMWARE_VERSION = 9


def split_report(report: bytes) -> list[bytes]:
    """Split a HID report containing one or more length-prefixed packets."""
    packets: list[bytes] = []
    start = 0

    while start < len(report):
        if report[start : start + 1] == EMPTY_PACKET:
            break
        if start + 2 > len(report):
            raise ProtocolError("packet header is truncated")

        end = start + report[start + 1] + 2
        if end > len(report):
            raise ProtocolError("packet payload is truncated")

        packets.append(report[start:end])
        start = end

    return packets


def create_packet(packet_type: bytes, data: bytes = b"") -> bytes:
    if len(packet_type) != 1:
        raise ProtocolError("packet type must contain exactly one byte")
    if len(data) > 255:
        raise ProtocolError("packet data is longer than 255 bytes")
    return packet_type + bytes((len(data),)) + data


def create_command(command: bytes, data: bytes = b"") -> bytes:
    return create_packet(PACKET_COMMAND, command + data)


def create_system_info_request(info_type: int) -> bytes:
    return create_packet(PACKET_GET_SYSTEM_INFO, bytes((info_type,)))


def create_device_status_request(device_number: int) -> bytes:
    if not 0 <= device_number <= 255:
        raise ProtocolError("device number must be between 0 and 255")
    return create_command(COMMAND_GET_DEVICE_STATUS, bytes((device_number,)))


def create_devices_sections_request(first: int, last: int) -> bytes:
    if not 1 <= first <= last <= 230:
        raise ProtocolError("device range must be between 1 and 230")
    return create_packet(PACKET_GET_DEVICES_SECTIONS, bytes((first, last)))


def create_device_diagnostics(device_number: int, enabled: bool) -> bytes:
    if not 0 <= device_number <= 255:
        raise ProtocolError("device number must be between 0 and 255")
    return create_packet(
        PACKET_DIAGNOSTICS, bytes((device_number, int(enabled)))
    )


def create_device_diagnostics_request(device_number: int) -> bytes:
    if not 0 <= device_number <= 255:
        raise ProtocolError("device number must be between 0 and 255")
    return create_packet(
        PACKET_DIAGNOSTICS_COMMAND, bytes((device_number, 0x09, 0x00))
    )


def create_ui_control(control: bytes, data: bytes = b"") -> bytes:
    return create_packet(PACKET_UI_CONTROL, control + data)


def create_authorisation_code(code: str) -> bytes:
    """Encode a Jablotron user code exactly as the upstream integration does."""
    _validate_code(code)
    magic_offset = 48

    if "*" in code:
        encoded = bytes(
            magic_offset + int(character)
            for character in code.rjust(8, "0")
            if character != "*"
        )
    else:
        encoded = b"\x39\x39\x39"
        values: list[int] = []
        for index in range(4):
            high_index = index + 4
            low = code[index]
            if high_index >= len(code):
                values.append(magic_offset + int(low))
            else:
                values.append(int(f"{code[high_index]}{low}", 16))
        encoded += bytes(values)

    return create_ui_control(UI_CONTROL_AUTHORISATION_CODE, encoded)


def create_keepalive(code: str) -> list[bytes]:
    return [
        create_authorisation_code(code),
        create_command(
            COMMAND_ENABLE_DEVICE_STATE_PACKETS,
            bytes((TIMEOUT_FOR_DEVICE_STATE_PACKETS,)),
        ),
    ]


def create_section_control(section: int, mode: ArmMode) -> bytes:
    if not 1 <= section <= 15:
        raise ProtocolError("section must be between 1 and 15")
    return create_ui_control(
        UI_CONTROL_MODIFY_SECTION,
        bytes((mode.value + section,)),
    )


def create_pg_control(pg_output: int, enabled: bool) -> bytes:
    if not 1 <= pg_output <= 128:
        raise ProtocolError("PG output must be between 1 and 128")
    return create_ui_control(
        UI_CONTROL_TOGGLE_PG_OUTPUT,
        bytes((pg_output - 1, int(enabled))),
    )


def pack_reports(packets: Iterable[bytes]) -> list[bytes]:
    """Batch protocol packets into writes no larger than one HID report."""
    reports: list[bytes] = []
    current = b""

    for packet in packets:
        if len(packet) > STREAM_PACKET_SIZE:
            raise ProtocolError("a packet cannot exceed 64 bytes")
        if current and len(current) + len(packet) > STREAM_PACKET_SIZE:
            reports.append(current)
            current = b""
        current += packet

    if current:
        reports.append(current)
    return reports


def _validate_code(code: str) -> None:
    if not 4 <= len(code) <= 10:
        raise ProtocolError("authorisation code must contain 4 to 10 characters")
    if code.count("*") > 1 or any(
        not (character.isdigit() or character == "*") for character in code
    ):
        raise ProtocolError("authorisation code may contain digits and one asterisk")
