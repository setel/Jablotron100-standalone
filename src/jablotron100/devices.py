"""Decode status and event packets produced by Jablotron peripherals."""

from .errors import ProtocolError
from .models import (
    BatteryState,
    BusDiagnostics,
    DeviceConnection,
    DeviceFault,
    DeviceInfo,
    DeviceInfoType,
    DeviceStateEvent,
    DeviceStateFlag,
    DeviceStatePacket,
    DeviceStatus,
)
from .protocol import split_report

PACKET_COMMAND = 0x52
COMMAND_RESPONSE_DEVICE_STATUS = 0x8A
PACKET_DEVICE_STATE = 0x55
PACKET_DEVICE_INFO = 0x90
SIGNAL_STRENGTH_STEP = 5
BATTERY_LEVEL_STEP = 10
DEVICE_STATE_EVENT_MASK = 0x1F
DEVICE_STATE_FLAGS_MASK = 0xE0
DEVICE_INFO_SUBPACKET_WIRELESS = 0x01
DEVICE_INFO_SUBPACKET_REQUESTED = 0x0A
DEVICE_INFO_SUBPACKET_PERIODIC = 0x9C


def parse_device_status(packet: bytes) -> DeviceStatus:
    _validate_packet(packet)
    if (
        packet[0] != PACKET_COMMAND
        or len(packet) < 4
        or packet[2] != COMMAND_RESPONSE_DEVICE_STATUS
    ):
        raise ProtocolError("not a device status packet")

    connection = (
        DeviceConnection.WIRELESS
        if packet[1] == 9
        else DeviceConnection.WIRED
    )
    if connection is DeviceConnection.WIRED:
        return DeviceStatus(packet[3], connection, None, None)
    if len(packet) < 11:
        raise ProtocolError("wireless device status packet is truncated")

    return DeviceStatus(
        number=packet[3],
        connection=connection,
        signal_strength=(packet[9] & 0x1F) * SIGNAL_STRENGTH_STEP,
        battery=parse_battery_state(packet[10]),
    )


def parse_device_state(packet: bytes) -> DeviceStatePacket:
    _validate_packet(packet)
    if packet[0] != PACKET_DEVICE_STATE:
        raise ProtocolError("not a device state packet")
    if len(packet) < 6:
        raise ProtocolError("device state packet is truncated")

    number = (int.from_bytes(packet[4:6], byteorder="little") >> 6) & 0xFF
    event_value = packet[2] & DEVICE_STATE_EVENT_MASK
    try:
        event = DeviceStateEvent(event_value)
    except ValueError:
        event = None

    flags = DeviceStateFlag(packet[2] & DEVICE_STATE_FLAGS_MASK)
    fault = {
        DeviceStateEvent.BATTERY_FAULT: DeviceFault.BATTERY,
        DeviceStateEvent.POWER_SUPPLY_FAULT: DeviceFault.POWER_SUPPLY,
        DeviceStateEvent.SABOTAGE: DeviceFault.SABOTAGE,
        DeviceStateEvent.FAULT: DeviceFault.UNKNOWN,
    }.get(event)
    heartbeat = packet[2] == 0x33 or event is DeviceStateEvent.HEARTBEAT

    return DeviceStatePacket(
        number=number,
        active=_decode_active_state(packet[3], number),
        event=event,
        flags=flags,
        fault=fault,
        heartbeat=heartbeat,
        signal_strength=(
            packet[10] * SIGNAL_STRENGTH_STEP if len(packet) >= 11 else None
        ),
    )


def parse_device_info(packet: bytes) -> DeviceInfo:
    _validate_packet(packet)
    if packet[0] != PACKET_DEVICE_INFO or len(packet) < 3:
        raise ProtocolError("not a device info packet")

    number = packet[2]
    try:
        subpackets = split_report(packet[3:])
    except ProtocolError as error:
        raise ProtocolError("invalid device info subpacket") from error
    if not subpackets:
        raise ProtocolError("device info packet has no subpackets")

    battery: BatteryState | None = None
    signal_strength: int | None = None
    temperature: float | None = None
    standby_voltage: float | None = None
    load_voltage: float | None = None
    pulses: list[int | None] = []
    info_types: list[DeviceInfoType] = []
    unknown_info_types: list[int] = []
    lan_connected: bool | None = None
    dhcp_ok: bool | None = None
    ip_address: str | None = None
    gsm_connected: bool | None = None
    gsm_signal_strength: int | None = None
    power_supply_ok: bool | None = None
    buses: list[BusDiagnostics] = []

    for subpacket in subpackets:
        subpacket_type = subpacket[0]
        if subpacket_type == DEVICE_INFO_SUBPACKET_WIRELESS:
            if len(subpacket) >= 3:
                signal_strength = subpacket[2] * SIGNAL_STRENGTH_STEP
            continue
        if subpacket_type not in (
            DEVICE_INFO_SUBPACKET_REQUESTED,
            DEVICE_INFO_SUBPACKET_PERIODIC,
        ):
            continue

        data = subpacket[2:]
        if number == 0 and data:
            power_supply_ok = bool(data[0] & 0x40)
        if data:
            parsed_battery = parse_battery_state(data[0])
            if parsed_battery is not None:
                battery = parsed_battery

        for info_type, raw in _parse_info_values(data):
            if not isinstance(info_type, DeviceInfoType):
                unknown_info_types.append(info_type)
                continue
            info_types.append(info_type)
            if info_type is DeviceInfoType.SMOKE and len(raw) >= 2:
                smoke_temperature = float(raw[1])
                temperature = (
                    smoke_temperature - 128
                    if smoke_temperature > 100
                    else smoke_temperature
                )
            elif info_type is DeviceInfoType.INPUT_VALUE and len(raw) >= 5:
                if raw[2] == 0:
                    modifier = raw[4] - 256 if raw[4] >= 128 else raw[4]
                    temperature = round((raw[3] + 256 * modifier) / 10, 1)
            elif info_type in (
                DeviceInfoType.POWER,
                DeviceInfoType.POWER_PRECISE,
            ) and len(raw) >= 3:
                channel = raw[1]
                value_size = 2 if info_type is DeviceInfoType.POWER_PRECISE else 1
                if len(raw) >= 2 + value_size:
                    voltage = round(
                        int.from_bytes(raw[2 : 2 + value_size], "little") / 10,
                        1,
                    )
                    if number == 0:
                        if channel == 0:
                            load_voltage = voltage
                        elif channel == 0x10:
                            standby_voltage = voltage
                        elif channel in (1, 2, 3) and len(raw) >= 4:
                            buses.append(
                                BusDiagnostics(channel, voltage, raw[3])
                            )
                    elif channel == 0:
                        standby_voltage = voltage
                    elif channel == 1:
                        load_voltage = voltage
            elif info_type is DeviceInfoType.LAN and len(raw) >= 6:
                lan_connected = bool(raw[1] & 0x80)
                dhcp_ok = bool(raw[1] & 0x02)
                ip_address = ".".join(str(part) for part in raw[2:6])
            elif info_type is DeviceInfoType.GSM and len(raw) >= 6:
                gsm_signal_strength = raw[1]
                gsm_connected = bool(raw[5] & 0x01)
            elif info_type is DeviceInfoType.GSM_EXTENDED and len(raw) >= 2:
                # JA-107K captures: d5 32 ... / d5 3c ..., with user-confirmed
                # signal readings of 50% / 60%. Only this field is corroborated;
                # do not reuse type 4's connection-status bit layout here.
                gsm_signal_strength = raw[1]
            elif info_type is DeviceInfoType.PULSE and len(pulses) < 2:
                pulses.append(
                    int.from_bytes(raw[1:3], "little")
                    if len(raw) >= 3 and raw[1] != 0
                    else None
                )

    return DeviceInfo(
        number=number,
        requested=subpackets[0][0] == DEVICE_INFO_SUBPACKET_REQUESTED,
        battery=battery,
        signal_strength=signal_strength,
        temperature=temperature,
        battery_standby_voltage=standby_voltage,
        battery_load_voltage=load_voltage,
        pulses=tuple(pulses),
        info_types=tuple(info_types),
        lan_connected=lan_connected,
        dhcp_ok=dhcp_ok,
        ip_address=ip_address,
        gsm_connected=gsm_connected,
        gsm_signal_strength=gsm_signal_strength,
        power_supply_ok=power_supply_ok,
        buses=tuple(buses),
        unknown_info_types=tuple(unknown_info_types),
    )


def parse_system_info(packet: bytes) -> tuple[int, str]:
    """Decode one 0x40 response into (information type, text)."""
    _validate_packet(packet)
    if packet[0] != 0x40 or len(packet) < 3:
        raise ProtocolError("not a system info packet")
    try:
        value = packet[3:].split(b"\x00", 1)[0].decode("ascii")
    except UnicodeDecodeError as error:
        raise ProtocolError("system info is not ASCII") from error
    return packet[2], value


def parse_battery_state(value: int) -> BatteryState | None:
    level_value = value & 0x0F
    if level_value in (0x0B, 0x0C, 0x0D, 0x0E, 0x0F):
        return None

    level = level_value * BATTERY_LEVEL_STEP
    if level > 100:
        raise ProtocolError(f"invalid battery level nibble: {level_value}")
    return BatteryState(ok=(value & 0x30) == 0, level=level)


def _parse_info_values(
    data: bytes,
) -> list[tuple[DeviceInfoType | int, bytes]]:
    values: list[tuple[DeviceInfoType | int, bytes]] = []
    start = 2
    while start < len(data):
        header = data[start]
        if header == 0:
            break
        length = header >> 5
        end = start + length + 1
        if end > len(data):
            raise ProtocolError("device info value is truncated")
        try:
            info_type = DeviceInfoType(header & 0x1F)
        except ValueError:
            info_type = header & 0x1F
        values.append((info_type, data[start:end]))
        start = end
    return values


def _decode_active_state(value: int, device_number: int) -> bool | None:
    if device_number <= 37:
        normalized_number = device_number
    elif device_number <= 101:
        normalized_number = device_number - 64
    elif device_number <= 165:
        normalized_number = device_number - 128
    elif device_number <= 229:
        normalized_number = device_number - 192
    else:
        normalized_number = device_number - 256

    active_value = normalized_number * 4 + 104
    if value in (active_value, active_value + 1):
        return True
    if value in (active_value + 2, active_value + 3):
        return False
    return None


def _validate_packet(packet: bytes) -> None:
    if len(packet) < 2:
        raise ProtocolError("packet header is truncated")
    if len(packet) != packet[1] + 2:
        raise ProtocolError("packet length does not match its payload")
