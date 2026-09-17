"""Public API for the standalone Jablotron 100+ client."""

from .client import JablotronClient
from .config import (
    DeviceDefinition,
    DeviceType,
    JablotronConfig,
    load_home_assistant_config,
)
from .errors import (
    ConfigurationError,
    JablotronError,
    ProtocolError,
    SerialPortNotDetected,
    TransportClosed,
)
from .models import (
    AlarmState,
    ArmMode,
    BatteryState,
    DeviceConnection,
    DeviceFault,
    DeviceInfo,
    DeviceInfoType,
    DeviceSnapshot,
    DeviceStateEvent,
    DeviceStateFlag,
    DeviceStatePacket,
    DeviceStatus,
    PacketEvent,
    SectionPrimaryState,
    SectionState,
    StateChange,
)
from .transport import HidrawTransport, Transport, detect_serial_port

__all__ = [
    "ArmMode",
    "AlarmState",
    "BatteryState",
    "ConfigurationError",
    "DeviceDefinition",
    "DeviceConnection",
    "DeviceFault",
    "DeviceInfo",
    "DeviceInfoType",
    "DeviceSnapshot",
    "DeviceStateEvent",
    "DeviceStateFlag",
    "DeviceStatePacket",
    "DeviceStatus",
    "DeviceType",
    "HidrawTransport",
    "JablotronClient",
    "JablotronConfig",
    "JablotronError",
    "PacketEvent",
    "ProtocolError",
    "SectionPrimaryState",
    "SectionState",
    "SerialPortNotDetected",
    "Transport",
    "TransportClosed",
    "StateChange",
    "detect_serial_port",
    "load_home_assistant_config",
]
