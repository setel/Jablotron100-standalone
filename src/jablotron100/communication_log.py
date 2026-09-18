"""Readable, rotating protocol logs with redaction and state-aware deduplication."""

from collections import OrderedDict
from dataclasses import asdict
import logging
import json
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import monotonic

from .devices import parse_device_info, parse_device_state, parse_device_status, parse_system_info
from .errors import ProtocolError
from .protocol import split_report
from .state import parse_device_states, parse_pg_output_states, parse_section_states
from .transport import Transport


def describe_packet(packet: bytes) -> str:
    """Explain known packets; unknown fields are deliberately not guessed."""
    kind = packet[0]
    if kind == 0x80:
        if packet[2:4] == b"\x1b\x03":
            return "Ústředna hlásí chybu autorizace — obsah skrytý"
        return "UI/autorizace — obsah skrytý"
    try:
        if kind == 0x40:
            field, value = parse_system_info(packet)
            return f"Identifikace ústředny: položka {field} = {value}"
        if kind == 0x30 and len(packet) == 3:
            return f"Dotaz na identifikaci: položka {packet[2]}"
        if kind == 0x52 and len(packet) >= 3:
            command = packet[2]
            names = {2: "Heartbeat", 10: "Dotaz na status zařízení", 14: "Dotaz na sekce a PG", 19: "Povolení událostí zařízení"}
            if command == 0x8A:
                return "Status zařízení: " + json.dumps(asdict(parse_device_status(packet)), ensure_ascii=False)
            return names.get(command, f"Příkaz/odpověď 0x{command:02x}") + (f"; parametr {packet[3:].hex(' ')}" if len(packet) > 3 else "")
        if kind in (0x94, 0x96) and len(packet) >= 4:
            return f"Diagnostika zařízení {packet[2]}: " + ("dotaz na hodnoty" if kind == 0x96 else ("zapnout" if packet[3] else "vypnout"))
        if kind == 0x90:
            info = parse_device_info(packet)
            values = {k: v for k, v in asdict(info).items() if v is not None and v != ()}
            if info.buses:
                values["buses"] = [
                    {"number": bus.number, "voltage": bus.voltage, "current_ma": bus.current_ma}
                    for bus in info.buses
                ]
            suffix = "; GSM 0x15: ověřen pouze signál, stav spojení neznámý" if 21 in info.info_types else ""
            return "Diagnostická odpověď: " + json.dumps(values, ensure_ascii=False) + suffix
        if kind == 0x55:
            return "Událost zařízení: " + json.dumps(asdict(parse_device_state(packet)), ensure_ascii=False)
        if kind == 0xD8:
            states = parse_device_states(packet)
            return f"Aktivní zařízení: {[n for n, active in states.items() if active]}; ostatní přítomné bity neaktivní"
        if kind == 0x51:
            return "Stavy sekcí: " + ", ".join(f"{n}={s.alarm_state.value}" for n, s in parse_section_states(packet).items())
        if kind == 0x50:
            states = parse_pg_output_states(packet)
            return f"PG zapnuto: {[n for n, on in states.items() if on]}; ostatní vypnuto ({len(states)} bitů)"
        if kind == 0x3A:
            return "Dotaz na přiřazení zařízení do sekcí"
        if kind == 0x3B:
            return "Odpověď přiřazení zařízení do sekcí (zatím nedekódováno)"
    except (ProtocolError, ValueError, IndexError) as error:
        return f"Nelze dekódovat ({type(error).__name__})"
    return f"Typ 0x{kind:02x}: význam zatím nedekódován"


def _key(packet: bytes) -> tuple:
    kind = packet[0]
    if kind == 0x80:
        return kind, packet[2:4] == b"\x1b\x03"
    if kind in (0x90, 0x94, 0x96, 0x40, 0x30) and len(packet) >= 3:
        return kind, packet[2]
    if kind == 0x52 and len(packet) >= 3:
        return kind, packet[2], packet[3] if len(packet) >= 4 else None
    if kind == 0x55 and len(packet) >= 6:
        return kind, (int.from_bytes(packet[4:6], "little") >> 6) & 0xFF
    return (kind,)


class CommunicationLog:
    """Log hex and meaning, suppressing unchanged packets per direction/device.

    Changes (including A → B → A) are always logged. Repeated unchanged packets
    are summarized after repeat_seconds or on flush/close. All 0x80 UI payloads
    are hidden in both directions, including authorization codes. Other packets
    may contain installation data, for example LAN addresses and sensor states.
    """

    def __init__(self, path: str | Path, *, repeat_seconds: float = 60, max_bytes: int = 2_000_000, backup_count: int = 3):
        self._logger = logging.Logger("jablotron100.communication", logging.INFO)
        self._handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        self._handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self._logger.addHandler(self._handler)
        self._repeat_seconds = repeat_seconds
        self._seen: OrderedDict[tuple, tuple[bytes, int, float]] = OrderedDict()

    def note(self, message: str) -> None:
        """Append a connection lifecycle message."""
        self._logger.info(message)

    def report(self, direction: str, report: bytes) -> None:
        """Record a HID report, splitting its protocol packets before logging."""
        try:
            packets = split_report(report)
        except ProtocolError:
            self.note(f"{direction}: neplatný HID report, délka {len(report)}; obsah skrytý")
            return
        for packet in packets:
            key = (direction, *_key(packet))
            # Never retain or print authorization payloads, even in the cache.
            safe = packet if packet[0] != 0x80 else b"\x80"
            now = monotonic()
            previous = self._seen.pop(key, None)
            if previous:
                old, count, last = previous
                if old == safe and now - last < self._repeat_seconds:
                    self._seen[key] = (old, count + 1, last)
                    continue
                if count:
                    self.note(f"{direction}: potlačeno {count} stejných opakování; hex {old.hex(' ')}")
            hex_text = safe.hex(" ") + (" [SKRYTO]" if packet[0] == 0x80 else "")
            self.note(f"{direction} hex {hex_text} — {describe_packet(packet)}")
            self._seen[key] = (safe, 0, now)
            if len(self._seen) > 512:
                old_key, (old, count, _) = self._seen.popitem(last=False)
                if count:
                    self.note(f"{old_key[0]}: potlačeno {count} stejných opakování; hex {old.hex(' ')}")

    def flush(self) -> None:
        """Summarize pending repeats and reset the cache between connections."""
        for key, (packet, count, _) in self._seen.items():
            if count:
                self.note(f"{key[0]}: potlačeno {count} stejných opakování; hex {packet.hex(' ')}")
        self._seen.clear()
        self._handler.flush()

    def close(self) -> None:
        self.flush()
        self._handler.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class LoggedTransport:
    """Wrap any transport, logging received and successfully written reports."""

    def __init__(self, transport: Transport, log: CommunicationLog):
        self.transport = transport
        self.log = log

    async def open(self) -> None:
        await self.transport.open()
        self.log.note("USB spojení otevřeno")

    async def close(self) -> None:
        await self.transport.close()
        self.log.flush()
        self.log.note("USB spojení zavřeno")

    async def read(self) -> bytes:
        try:
            report = await self.transport.read()
        except Exception as error:
            self.log.note(f"Chyba čtení USB: {type(error).__name__}")
            raise
        if not report:
            self.log.note("USB čtení skončilo (EOF)")
        self.log.report("PŘIJÍMÁM", report)
        return report

    async def write(self, data: bytes) -> None:
        try:
            await self.transport.write(data)
        except Exception as error:
            self.log.note(f"Chyba zápisu USB: {type(error).__name__}; data nebyla potvrzena jako odeslaná")
            raise
        self.log.report("ODESÍLÁM", data)
