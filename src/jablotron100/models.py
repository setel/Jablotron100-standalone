"""Home Assistant independent public data types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum, IntFlag, StrEnum
from time import monotonic


class ArmMode(Enum):
    """Requested state of one alarm section."""

    DISARMED = 143
    ARMED_FULL = 159
    ARMED_PARTIAL = 175


class SectionPrimaryState(Enum):
    DISARMED = 1
    ARMED_PARTIALLY = 2
    ARMED_FULL = 3
    MAINTENANCE = 4
    SERVICE = 5
    BLOCKED = 6
    OFF = 7


class AlarmState(StrEnum):
    DISARMED = "disarmed"
    ARMING = "arming"
    PENDING = "pending"
    ARMED_PARTIAL = "armed_partial"
    ARMED_FULL = "armed_full"
    TRIGGERED = "triggered"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class SectionState:
    number: int
    primary: SectionPrimaryState
    arming: bool
    pending: bool
    triggered: bool
    problem: bool
    sabotage: bool
    fire: bool

    @property
    def alarm_state(self) -> AlarmState:
        if self.primary in (SectionPrimaryState.SERVICE, SectionPrimaryState.BLOCKED):
            return AlarmState.UNAVAILABLE
        if self.triggered or self.sabotage:
            return AlarmState.TRIGGERED
        if self.pending:
            return AlarmState.PENDING
        if self.arming:
            return AlarmState.ARMING
        if self.primary is SectionPrimaryState.ARMED_FULL:
            return AlarmState.ARMED_FULL
        if self.primary is SectionPrimaryState.ARMED_PARTIALLY:
            return AlarmState.ARMED_PARTIAL
        return AlarmState.DISARMED


@dataclass(frozen=True, slots=True)
class StateChange:
    kind: str
    number: int
    value: SectionState | DeviceSnapshot | bool


class DeviceConnection(StrEnum):
    WIRED = "wired"
    WIRELESS = "wireless"


class DeviceFault(StrEnum):
    BATTERY = "battery"
    POWER_SUPPLY = "power_supply"
    SABOTAGE = "sabotage"
    UNKNOWN = "unknown"


class DeviceStateEvent(IntEnum):
    INSTANT_ALARM = 0x00
    DELAYED_ALARM_A = 0x01
    DELAYED_ALARM_B = 0x02
    DELAYED_ALARM_C = 0x03
    ACTIVITY = 0x04
    POWER_SUPPLY_FAULT = 0x05
    SABOTAGE = 0x06
    FAULT = 0x07
    REPEATED_ALARM = 0x08
    HEARTBEAT = 0x0F
    BATTERY_FAULT = 0x14


class DeviceStateFlag(IntFlag):
    NONE = 0
    NO_REACTION_WHEN_PARTIALLY_ARMED = 0x80


class DeviceInfoType(IntEnum):
    SMOKE = 3
    GSM = 4
    LAN = 6
    POWER = 10
    POWER_PRECISE = 12
    INPUT_VALUE = 14
    INPUT_EXTENDED = 15
    PULSE = 17


@dataclass(frozen=True, slots=True)
class BatteryState:
    ok: bool
    level: int


@dataclass(frozen=True, slots=True)
class DeviceStatus:
    number: int
    connection: DeviceConnection
    signal_strength: int | None
    battery: BatteryState | None


@dataclass(frozen=True, slots=True)
class DeviceStatePacket:
    number: int
    active: bool | None
    event: DeviceStateEvent | None
    flags: DeviceStateFlag
    fault: DeviceFault | None
    heartbeat: bool
    signal_strength: int | None


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    number: int
    requested: bool
    battery: BatteryState | None = None
    signal_strength: int | None = None
    temperature: float | None = None
    battery_standby_voltage: float | None = None
    battery_load_voltage: float | None = None
    pulses: tuple[int | None, ...] = ()
    info_types: tuple[DeviceInfoType, ...] = ()


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    number: int
    device_type: str | None = None
    active: bool | None = None
    connection: DeviceConnection | None = None
    signal_strength: int | None = None
    battery_level: int | None = None
    battery_ok: bool | None = None
    problem: bool = False
    sabotage: bool = False
    last_event: DeviceStateEvent | None = None
    temperature: float | None = None
    battery_standby_voltage: float | None = None
    battery_load_voltage: float | None = None
    pulses: tuple[int | None, ...] = ()


@dataclass(frozen=True, slots=True)
class PacketEvent:
    """One packet received from the alarm panel."""

    packet: bytes
    received_at: float

    @classmethod
    def now(cls, packet: bytes) -> "PacketEvent":
        return cls(packet=packet, received_at=monotonic())

    @property
    def packet_type(self) -> int:
        return self.packet[0]
