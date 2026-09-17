"""High-level asynchronous client independent of Home Assistant."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace

from .config import DeviceDefinition, DeviceType, JablotronConfig
from .devices import parse_device_info, parse_device_state, parse_device_status
from .errors import ConfigurationError
from .models import (
    ArmMode,
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
    create_keepalive,
    create_pg_control,
    create_section_control,
    create_ui_control,
    pack_reports,
    split_report,
)
from .transport import HidrawTransport, Transport
from .state import (
    PACKET_PG_OUTPUTS_STATES,
    PACKET_SECTIONS_STATES,
    parse_pg_output_states,
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
        keepalive_interval: float = 30.0,
        number_of_pg_outputs: int | None = None,
        devices: tuple[DeviceDefinition, ...] = (),
    ) -> None:
        self._code = code
        self._transport = transport or HidrawTransport(port)
        self._keepalive_interval = keepalive_interval
        self._number_of_pg_outputs = number_of_pg_outputs
        self._device_definitions = devices
        self._listeners: set[PacketListener] = set()
        self._state_listeners: set[StateListener] = set()
        self._sections: dict[int, SectionState] = {}
        self._pg_outputs: dict[int, bool] = {}
        self._devices: dict[int, DeviceSnapshot] = {
            definition.number: DeviceSnapshot(
                number=definition.number,
                device_type=definition.device_type.value,
            )
            for definition in devices
            if definition.device_type not in (DeviceType.EMPTY, DeviceType.OTHER)
        }
        self._reader_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

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
    def devices(self) -> dict[int, DeviceSnapshot]:
        return dict(self._devices)

    @classmethod
    def from_config(
        cls,
        config: JablotronConfig,
        *,
        code: str | None = None,
        transport: Transport | None = None,
        keepalive_interval: float = 30.0,
    ) -> "JablotronClient":
        effective_code = config.code if code is None else code
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
        await self._transport.open()
        self._running = True
        self._reader_task = asyncio.create_task(
            self._read_loop(), name="jablotron-reader"
        )
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(), name="jablotron-keepalive"
        )
        await self._send_packets(create_keepalive(self._code))
        await self.refresh()

    async def close(self) -> None:
        self._running = False
        tasks = [task for task in (self._reader_task, self._keepalive_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._reader_task = None
        self._keepalive_task = None
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
        except Exception:
            LOGGER.exception("Jablotron read loop stopped")
            self._running = False

    async def _keepalive_loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self._keepalive_interval)
                await self._send_packets([create_command(COMMAND_HEARTBEAT)])
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Jablotron keepalive loop stopped")
            self._running = False

    async def _publish(self, event: PacketEvent) -> None:
        for listener in tuple(self._listeners):
            try:
                result = listener(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                LOGGER.exception("Jablotron packet listener failed")

    async def _handle_state_packet(self, packet: bytes) -> None:
        if packet[0] == PACKET_SECTIONS_STATES:
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
            if self._accept_device(status.number):
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
            if self._accept_device(state.number):
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
            if self._accept_device(info.number):
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
