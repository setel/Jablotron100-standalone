"""High-level asynchronous client independent of Home Assistant."""

from __future__ import annotations

import asyncio
import inspect
import logging
from time import monotonic
from collections.abc import Awaitable, Callable
from dataclasses import replace

from .config import (
    DeviceDefinition,
    DeviceType,
    JablotronConfig,
    PGOutputDefinition,
    SectionDefinition,
)
from .devices import (
    parse_device_info,
    parse_device_state,
    parse_device_status,
    parse_system_info,
)
from .errors import ConfigurationError
from .models import (
    ArmMode,
    CentralUnitDiagnostics,
    CentralUnitInfo,
    DeviceFault,
    DeviceSnapshot,
    PacketEvent,
    SectionState,
    StateChange,
)
from .protocol import (
    COMMAND_GET_SECTIONS_AND_PG_OUTPUTS_STATES,
    COMMAND_HEARTBEAT,
    UI_CONTROL_AUTHORISATION_END,
    create_authorisation_code,
    create_command,
    create_device_diagnostics,
    create_device_diagnostics_request,
    create_device_status_request,
    create_devices_sections_request,
    create_keepalive,
    create_pg_control,
    create_section_control,
    create_system_info_request,
    create_ui_control,
    pack_reports,
    split_report,
    SYSTEM_INFO_FIRMWARE_VERSION,
    SYSTEM_INFO_HARDWARE_VERSION,
    SYSTEM_INFO_MODEL,
)
from .transport import HidrawTransport, Transport
from .state import (
    PACKET_PG_OUTPUTS_STATES,
    PACKET_SECTIONS_STATES,
    parse_pg_output_states,
    parse_device_states,
    parse_section_states,
)

LOGGER = logging.getLogger(__name__)
PacketListener = Callable[[PacketEvent], None | Awaitable[None]]
StateListener = Callable[[StateChange], None | Awaitable[None]]


class JablotronClient:
    """Own the panel connection and expose a stable, HA-free public API."""

    def __init__(
        self,
        *,
        code: str,
        port: str = "auto",
        transport: Transport | None = None,
        keepalive_interval: float = 0.5,
        number_of_pg_outputs: int | None = None,
        devices: tuple[DeviceDefinition, ...] = (),
        sections: tuple[SectionDefinition, ...] = (),
        pg_outputs: tuple[PGOutputDefinition, ...] = (),
        auto_reconnect: bool = True,
        reconnect_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
    ) -> None:
        self._code = code
        self._transport = transport or HidrawTransport(port)
        self._keepalive_interval = keepalive_interval
        self._number_of_pg_outputs = number_of_pg_outputs
        self._device_definitions = devices
        self._section_definitions = sections
        self._pg_output_definitions = pg_outputs
        self._auto_reconnect = auto_reconnect
        self._reconnect_delay = reconnect_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._listeners: set[PacketListener] = set()
        self._state_listeners: set[StateListener] = set()
        self._sections: dict[int, SectionState] = {}
        self._pg_outputs: dict[int, bool] = {}
        self._devices: dict[int, DeviceSnapshot] = {
            definition.number: DeviceSnapshot(
                number=definition.number,
                device_type=definition.device_type.value,
                name=definition.name,
                model=definition.model,
                serial_number=definition.serial_number,
            )
            for definition in devices
            if definition.device_type not in (DeviceType.EMPTY, DeviceType.OTHER)
        }
        self._central_unit = CentralUnitInfo()
        self._diagnostics = CentralUnitDiagnostics()
        self._reader_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._initialization_task: asyncio.Task[None] | None = None
        self._diagnostic_events: dict[int, asyncio.Event] = {}
        self._system_info_event = asyncio.Event()
        self._connection_lock = asyncio.Lock()
        self._running = False
        self._connected = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def initialization_complete(self) -> bool:
        task = self._initialization_task
        return bool(
            task
            and task.done()
            and not task.cancelled()
            and task.exception() is None
        )

    @property
    def central_unit(self) -> CentralUnitInfo:
        return self._central_unit

    @property
    def diagnostics(self) -> CentralUnitDiagnostics:
        return replace(
            self._diagnostics, buses=dict(self._diagnostics.buses)
        )

    @property
    def sections(self) -> dict[int, SectionState]:
        return dict(self._sections)

    @property
    def pg_outputs(self) -> dict[int, bool]:
        return dict(self._pg_outputs)

    @property
    def device_definitions(self) -> tuple[DeviceDefinition, ...]:
        return self._device_definitions

    @property
    def section_definitions(self) -> tuple[SectionDefinition, ...]:
        return self._section_definitions

    @property
    def pg_output_definitions(self) -> tuple[PGOutputDefinition, ...]:
        return self._pg_output_definitions

    @property
    def section_names(self) -> dict[int, str]:
        return {item.number: item.name for item in self._section_definitions}

    @property
    def pg_output_names(self) -> dict[int, str]:
        return {item.number: item.name for item in self._pg_output_definitions}

    @property
    def devices(self) -> dict[int, DeviceSnapshot]:
        return dict(self._devices)

    @classmethod
    def from_config(
        cls,
        config: JablotronConfig,
        *,
        code: str | None = None,
        transport: Transport | None = None,
        keepalive_interval: float = 0.5,
        auto_reconnect: bool = True,
        reconnect_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
    ) -> "JablotronClient":
        effective_code = config.resolve_code() if code is None else code
        if not effective_code:
            raise ConfigurationError(
                "authorisation code is missing; pass code= or import an unredacted entry"
            )
        return cls(
            code=effective_code,
            port=config.serial_port,
            transport=transport,
            keepalive_interval=keepalive_interval,
            number_of_pg_outputs=config.number_of_pg_outputs,
            devices=config.devices,
            sections=config.sections,
            pg_outputs=config.pg_outputs,
            auto_reconnect=auto_reconnect,
            reconnect_delay=reconnect_delay,
            reconnect_max_delay=reconnect_max_delay,
        )

    def add_packet_listener(self, listener: PacketListener) -> Callable[[], None]:
        self._listeners.add(listener)

        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    def add_state_listener(self, listener: StateListener) -> Callable[[], None]:
        self._state_listeners.add(listener)

        def unsubscribe() -> None:
            self._state_listeners.discard(listener)

        return unsubscribe

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            await self._connect()
        except Exception:
            if not self._auto_reconnect:
                self._running = False
                raise
            LOGGER.exception("Initial Jablotron connection failed; retrying")
            self._schedule_reconnect()

    async def close(self) -> None:
        self._running = False
        tasks = [
            task
            for task in (
                self._reader_task,
                self._keepalive_task,
                self._reconnect_task,
                self._initialization_task,
            )
            if task
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._reader_task = None
        self._keepalive_task = None
        self._reconnect_task = None
        self._initialization_task = None
        self._connected = False
        await self._transport.close()

    async def __aenter__(self) -> "JablotronClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

    async def refresh(self) -> None:
        await self._send_packets(
            [create_command(COMMAND_GET_SECTIONS_AND_PG_OUTPUTS_STATES)]
        )

    async def initialize_devices(self) -> None:
        """Request identity, states and status for every configured device."""
        packets = [
            create_system_info_request(SYSTEM_INFO_MODEL),
            create_system_info_request(SYSTEM_INFO_HARDWARE_VERSION),
            create_system_info_request(SYSTEM_INFO_FIRMWARE_VERSION),
            *create_keepalive(self._code),
            create_command(COMMAND_GET_SECTIONS_AND_PG_OUTPUTS_STATES),
            create_device_status_request(0),
        ]
        active = [
            definition.number
            for definition in self._device_definitions
            if definition.device_type not in (DeviceType.EMPTY, DeviceType.OTHER)
        ]
        packets.extend(create_device_status_request(number) for number in active)
        if active:
            packets.append(create_devices_sections_request(1, max(active)))
        await self._send_packets(packets)

        self._initialization_task = asyncio.create_task(
            self.refresh_diagnostics(), name="jablotron-initial-diagnostics"
        )

    async def refresh_diagnostics(self, *, timeout: float = 2.0) -> None:
        """Refresh diagnostic data for the panel and capable peripherals."""
        if self._central_unit.model is None:
            try:
                await asyncio.wait_for(self._system_info_event.wait(), timeout)
            except TimeoutError:
                LOGGER.debug("Central unit identity was not received in time")
        numbers = [0, *self._system_module_numbers()]
        diagnostic_types = {
            DeviceType.THERMOMETER,
            DeviceType.THERMOSTAT,
            DeviceType.SMOKE_DETECTOR,
            DeviceType.SIREN_OUTDOOR,
            DeviceType.SIREN_INDOOR,
            DeviceType.ELECTRICITY_METER_WITH_PULSE_OUTPUT,
        }
        numbers.extend(
            item.number
            for item in self._device_definitions
            if item.device_type in diagnostic_types
        )
        for number in dict.fromkeys(numbers):
            if not self._running or not self._connected:
                return
            event = self._diagnostic_events.setdefault(number, asyncio.Event())
            event.clear()
            await self._send_packets(
                [
                    create_device_diagnostics(number, True),
                    create_device_diagnostics_request(number),
                ]
            )
            try:
                await asyncio.wait_for(event.wait(), timeout)
            except TimeoutError:
                LOGGER.debug("No diagnostic response from device %d", number)
            finally:
                if self._connected:
                    await self._send_packets(
                        [create_device_diagnostics(number, False)]
                    )

    async def set_section(
        self,
        section: int,
        mode: ArmMode,
        *,
        code: str | None = None,
    ) -> None:
        """Change one section, temporarily authorising another user if needed."""
        active_code = self._code if code is None else code
        restore_session = active_code != self._code

        if restore_session:
            await self._send_packets(
                [
                    create_ui_control(UI_CONTROL_AUTHORISATION_END),
                    create_authorisation_code(active_code),
                ]
            )
            await asyncio.sleep(1.0)

        await self._send_packets([create_section_control(section, mode)])

        if restore_session:
            await self._send_packets(
                [
                    create_ui_control(UI_CONTROL_AUTHORISATION_END),
                    *create_keepalive(self._code),
                ]
            )

        await asyncio.sleep(1.0)
        await self.refresh()

    async def set_pg_output(self, pg_output: int, enabled: bool) -> None:
        await self._send_packets([create_pg_control(pg_output, enabled)])

    async def _send_packets(self, packets: list[bytes]) -> None:
        for report in pack_reports(packets):
            await self._transport.write(report)

    async def _connect(self) -> None:
        async with self._connection_lock:
            if not self._running or self._connected:
                return
            await self._transport.open()
            self._connected = True
            self._reader_task = asyncio.create_task(
                self._read_loop(), name="jablotron-reader"
            )
            self._keepalive_task = asyncio.create_task(
                self._keepalive_loop(), name="jablotron-keepalive"
            )
            try:
                await self.initialize_devices()
            except Exception:
                self._connected = False
                await self._transport.close()
                raise
            await self._publish_state(StateChange("connection", 0, True))

    def _schedule_reconnect(self) -> None:
        if not self._running:
            return
        self._connected = False
        if not self._auto_reconnect:
            self._running = False
            return
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(
                self._reconnect_loop(), name="jablotron-reconnect"
            )

    async def _reconnect_loop(self) -> None:
        await self._publish_state(StateChange("connection", 0, False))
        current = asyncio.current_task()
        for task in (self._reader_task, self._keepalive_task):
            if task and task is not current and not task.done():
                task.cancel()
        if self._initialization_task and not self._initialization_task.done():
            self._initialization_task.cancel()
        try:
            await self._transport.close()
        except Exception:
            LOGGER.debug("Error while closing failed transport", exc_info=True)

        delay = self._reconnect_delay
        while self._running:
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                await self._connect()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "Jablotron reconnect failed; retrying in %.1f seconds",
                    min(delay * 2, self._reconnect_max_delay),
                )
                delay = min(
                    max(delay * 2, self._reconnect_delay),
                    self._reconnect_max_delay,
                )
            else:
                return

    async def _read_loop(self) -> None:
        try:
            while self._running:
                report = await self._transport.read()
                if not report:
                    raise ConnectionError("Jablotron transport returned EOF")
                for packet in split_report(report):
                    await self._handle_state_packet(packet)
                    await self._publish(PacketEvent.now(packet))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if isinstance(error, ConnectionError):
                LOGGER.warning("Jablotron read loop lost the connection: %s", error)
            else:
                LOGGER.exception("Jablotron read loop lost the connection")
            self._schedule_reconnect()

    async def _keepalive_loop(self) -> None:
        last_refresh = monotonic()
        try:
            while self._running:
                await asyncio.sleep(self._keepalive_interval)
                # Match upstream's half-second heartbeat and 30-second session
                # renewal. Never reauthorize during an alarm or entry delay.
                now = monotonic()
                if now - last_refresh >= 30 and not any(
                    state.triggered or state.sabotage or state.pending
                    for state in self._sections.values()
                ):
                    await self._send_packets(create_keepalive(self._code))
                    last_refresh = now
                else:
                    await self._send_packets([create_command(COMMAND_HEARTBEAT)])
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Jablotron keepalive lost the connection")
            self._schedule_reconnect()

    async def _publish(self, event: PacketEvent) -> None:
        for listener in tuple(self._listeners):
            try:
                result = listener(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                LOGGER.exception("Jablotron packet listener failed")

    async def _handle_state_packet(self, packet: bytes) -> None:
        if packet[0] == 0x40:
            info_type, value = parse_system_info(packet)
            changes: dict[str, str] = {}
            if info_type == SYSTEM_INFO_MODEL:
                changes["model"] = value
            elif info_type == SYSTEM_INFO_HARDWARE_VERSION:
                changes["hardware_version"] = value
            elif info_type == SYSTEM_INFO_FIRMWARE_VERSION:
                changes["firmware_version"] = value
            if changes:
                old = self._central_unit
                self._central_unit = replace(old, **changes)
                if old != self._central_unit:
                    await self._publish_state(
                        StateChange("central_unit", 0, self._central_unit)
                    )
                if all(
                    (
                        self._central_unit.model,
                        self._central_unit.hardware_version,
                        self._central_unit.firmware_version,
                    )
                ):
                    self._system_info_event.set()
                    modules = self._system_module_numbers()
                    if modules:
                        await self._send_packets(
                            [
                                create_device_status_request(number)
                                for number in modules
                            ]
                        )
        elif packet[0] == 0xD8:
            for number, active in parse_device_states(packet).items():
                if self._accept_device(number) and self._device_has_state(number):
                    old = self._devices.get(number, DeviceSnapshot(number=number))
                    await self._store_device_snapshot(old, replace(old, active=active))
        elif packet[0] == PACKET_SECTIONS_STATES:
            new_states = parse_section_states(packet)
            old_states, self._sections = self._sections, new_states
            for number, state in new_states.items():
                if old_states.get(number) != state:
                    await self._publish_state(StateChange("section", number, state))
        elif packet[0] == PACKET_PG_OUTPUTS_STATES:
            new_states = parse_pg_output_states(
                packet, self._number_of_pg_outputs
            )
            old_states, self._pg_outputs = self._pg_outputs, new_states
            for number, state in new_states.items():
                if old_states.get(number) != state:
                    await self._publish_state(StateChange("pg_output", number, state))
        elif packet[0] == 0x52 and len(packet) >= 3 and packet[2] == 0x8A:
            status = parse_device_status(packet)
            role = self._system_module_role(status.number)
            if role == "lan" and len(packet) >= 10:
                await self._update_diagnostics(
                    lan_ip=".".join(str(part) for part in packet[6:10])
                )
            elif (
                role == "gsm"
                and len(packet) >= 6
                and packet[4] in (0xA4, 0xD5)
            ):
                await self._update_diagnostics(gsm_signal_strength=packet[5])
            elif self._accept_device(status.number):
                old = self._devices.get(
                    status.number, DeviceSnapshot(number=status.number)
                )
                changes = {
                    "connection": status.connection,
                    "signal_strength": status.signal_strength,
                }
                if status.battery is not None:
                    changes["battery_level"] = status.battery.level
                    changes["battery_ok"] = status.battery.ok
                new = replace(old, **changes)
                await self._store_device_snapshot(old, new)
        elif packet[0] == 0x55:
            state = parse_device_state(packet)
            role = self._system_module_role(state.number)
            if state.number == 0 and state.fault is DeviceFault.POWER_SUPPLY:
                await self._update_diagnostics(
                    power_supply_ok=not bool(state.active)
                )
            elif role == "lan" and state.active is not None:
                await self._update_diagnostics(lan_connected=not state.active)
            elif role == "gsm" and state.active is not None:
                await self._update_diagnostics(gsm_connected=not state.active)
            elif self._accept_device(state.number):
                old = self._devices.get(
                    state.number, DeviceSnapshot(number=state.number)
                )
                changes: dict[str, object] = {"last_event": state.event}
                if state.signal_strength is not None:
                    changes["signal_strength"] = state.signal_strength
                if not state.heartbeat:
                    if (
                        state.fault is DeviceFault.BATTERY
                        and old.battery_level is not None
                    ):
                        changes["battery_ok"] = not bool(state.active)
                    elif state.fault is not None:
                        changes["problem"] = bool(state.active)
                        if state.fault is DeviceFault.SABOTAGE:
                            changes["sabotage"] = bool(state.active)
                    elif state.active is not None and self._device_has_state(
                        state.number
                    ):
                        changes["active"] = state.active
                new = replace(old, **changes)
                await self._store_device_snapshot(old, new)
        elif packet[0] == 0x90:
            info = parse_device_info(packet)
            event = self._diagnostic_events.get(info.number)
            if event:
                event.set()
            role = self._system_module_role(info.number)
            if info.number == 0:
                changes = {
                    name: value
                    for name, value in (
                        ("power_supply_ok", info.power_supply_ok),
                        (
                            "battery_level",
                            info.battery.level if info.battery else None,
                        ),
                        (
                            "battery_ok",
                            info.battery.ok if info.battery else None,
                        ),
                        (
                            "battery_standby_voltage",
                            info.battery_standby_voltage,
                        ),
                        ("battery_load_voltage", info.battery_load_voltage),
                    )
                    if value is not None
                }
                if info.buses:
                    changes["buses"] = {
                        bus.number: bus for bus in info.buses
                    }
                await self._update_diagnostics(**changes)
            elif role == "lan":
                await self._update_diagnostics(
                    **{
                        name: value
                        for name, value in (
                            ("lan_connected", info.lan_connected),
                            ("dhcp_ok", info.dhcp_ok),
                            ("lan_ip", info.ip_address),
                        )
                        if value is not None
                    }
                )
            elif role == "gsm":
                await self._update_diagnostics(
                    **{
                        name: value
                        for name, value in (
                            ("gsm_connected", info.gsm_connected),
                            (
                                "gsm_signal_strength",
                                info.gsm_signal_strength,
                            ),
                        )
                        if value is not None
                    }
                )
            elif self._accept_device(info.number):
                old = self._devices.get(
                    info.number, DeviceSnapshot(number=info.number)
                )
                changes = {}
                if info.signal_strength is not None:
                    changes["signal_strength"] = info.signal_strength
                if info.battery is not None:
                    changes["battery_level"] = info.battery.level
                    changes["battery_ok"] = info.battery.ok
                for field_name in (
                    "temperature",
                    "battery_standby_voltage",
                    "battery_load_voltage",
                ):
                    value = getattr(info, field_name)
                    if value is not None:
                        changes[field_name] = value
                if info.pulses:
                    changes["pulses"] = info.pulses
                new = replace(old, **changes)
                await self._store_device_snapshot(old, new)

    def _system_module_numbers(self) -> tuple[int, ...]:
        if self._central_unit.model in (
            "JA-103K",
            "JA-103KRY",
            "JA-107K",
        ):
            return (233, 234)
        if self._central_unit.model in (
            "JA-101K",
            "JA-101K-LAN",
            "JA-106K-3G",
            "JA-14K",
        ):
            return (124, 125, 127)
        return ()

    def _system_module_role(self, number: int) -> str | None:
        modules = self._system_module_numbers()
        if modules == (233, 234):
            return {233: "lan", 234: "gsm"}.get(number)
        if modules == (124, 125, 127):
            return {124: "power", 125: "lan", 127: "gsm"}.get(number)
        return None

    async def _update_diagnostics(self, **changes: object) -> None:
        if not changes:
            return
        old = self._diagnostics
        if "buses" in changes:
            merged = dict(old.buses)
            merged.update(changes["buses"])  # type: ignore[arg-type]
            changes["buses"] = merged
        self._diagnostics = replace(old, **changes)
        if old != self._diagnostics:
            await self._publish_state(
                StateChange("diagnostics", 0, self.diagnostics)
            )

    def _accept_device(self, number: int) -> bool:
        if not 1 <= number <= 230:
            return False
        if not self._device_definitions:
            return True
        if number > len(self._device_definitions):
            return False
        return self._device_definitions[number - 1].device_type not in (
            DeviceType.EMPTY,
            DeviceType.OTHER,
        )

    def _device_has_state(self, number: int) -> bool:
        if not self._device_definitions:
            return True
        device_type = self._device_definitions[number - 1].device_type
        return device_type not in (
            DeviceType.KEYPAD,
            DeviceType.SIREN_OUTDOOR,
            DeviceType.ELECTRICITY_METER_WITH_PULSE_OUTPUT,
            DeviceType.RADIO_MODULE,
        )

    async def _store_device_snapshot(
        self, old: DeviceSnapshot, new: DeviceSnapshot
    ) -> None:
        self._devices[new.number] = new
        if old != new:
            await self._publish_state(StateChange("device", new.number, new))

    async def _publish_state(self, change: StateChange) -> None:
        for listener in tuple(self._state_listeners):
            try:
                result = listener(change)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                LOGGER.exception("Jablotron state listener failed")
