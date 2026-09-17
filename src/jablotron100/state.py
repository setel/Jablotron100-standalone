"""Decode state packets into Home Assistant independent data models."""

from .errors import ProtocolError
from .models import SectionPrimaryState, SectionState

PACKET_SECTIONS_STATES = 0x51
PACKET_PG_OUTPUTS_STATES = 0x50
MAX_SECTIONS = 15


def parse_section_states(packet: bytes) -> dict[int, SectionState]:
    if not packet or packet[0] != PACKET_SECTIONS_STATES:
        raise ProtocolError("not a sections state packet")
    _validate_declared_length(packet)

    result: dict[int, SectionState] = {}
    for section in range(1, MAX_SECTIONS + 1):
        offset = section * 2
        state_bytes = packet[offset : offset + 2]
        if len(state_bytes) < 2:
            break
        if state_bytes == b"\x07\x00":
            break

        bits = "".join(f"{byte:08b}" for byte in state_bytes)
        try:
            primary = SectionPrimaryState(int(bits[5:8], 2))
        except ValueError as error:
            raise ProtocolError(
                f"unknown primary state for section {section}"
            ) from error

        result[section] = SectionState(
            number=section,
            primary=primary,
            arming=bits[0] == "1",
            pending=bits[1] == "1",
            triggered=any(bits[index] == "1" for index in (3, 4, 9, 12, 13)),
            problem=bits[2] == "1",
            sabotage=bits[11] == "1",
            fire=bits[14] == "1",
        )

    return result


def parse_pg_output_states(
    packet: bytes, number_of_outputs: int | None = None
) -> dict[int, bool]:
    if not packet or packet[0] != PACKET_PG_OUTPUTS_STATES:
        raise ProtocolError("not a PG outputs state packet")
    _validate_declared_length(packet)

    payload = packet[2:]
    available_outputs = len(payload) * 8
    count = available_outputs if number_of_outputs is None else number_of_outputs
    if not 0 <= count <= 128:
        raise ProtocolError("number of PG outputs must be between 0 and 128")
    if count > available_outputs:
        raise ProtocolError("incomplete PG outputs state packet")

    bits = f"{int.from_bytes(payload, byteorder='little'):0{available_outputs}b}"[::-1]
    return {index + 1: bits[index] == "1" for index in range(count)}


def _validate_declared_length(packet: bytes) -> None:
    if len(packet) < 2:
        raise ProtocolError("packet header is truncated")
    if packet[1] + 2 != len(packet):
        raise ProtocolError("packet length does not match its payload")
