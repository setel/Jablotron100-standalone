"""Explicit hardware test: stop other USB clients before running this script.

Sends authorization, state queries, heartbeat and diagnostic requests only.
Does not arm/disarm sections or control PG outputs. Run from the repository:
PYTHONPATH=src python tools/hardware_smoke.py --seconds 45
"""

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path

from jablotron100 import CommunicationLog, HidrawTransport, JablotronClient, LoggedTransport, load_config


async def run(config_path: str, seconds: float, log_path: str | None = None, heartbeat: float = 0.5, reconnect: bool = False) -> None:
    config = load_config(config_path)
    log = None
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        log = CommunicationLog(log_path)
    transport = LoggedTransport(HidrawTransport(config.serial_port), log) if log else None
    client = JablotronClient.from_config(config, transport=transport, auto_reconnect=reconnect, keepalive_interval=heartbeat)
    packets: Counter[str] = Counter()
    changes: Counter[str] = Counter()
    diagnostic_responses: Counter[int] = Counter()

    def packet_received(event):
        packets[f"{event.packet_type:02x}"] += 1
        if event.packet_type == 0x90 and len(event.packet) >= 3:
            diagnostic_responses[event.packet[2]] += 1

    def state_changed(change):
        changes[change.kind] += 1
        if change.kind == "connection":
            print(f"Connected: {change.value}", flush=True)
        elif change.kind == "device" and change.value.active is not None:
            print(f"Device {change.number}: active={change.value.active}", flush=True)

    client.add_packet_listener(packet_received)
    client.add_state_listener(state_changed)
    try:
        await client.start()
        await asyncio.sleep(seconds)
        diagnostics = asdict(client.diagnostics)
        diagnostics.pop("lan_ip", None)
        print(json.dumps({
            "connected": client.connected,
            "initialization_complete": client.initialization_complete,
            "central_unit": asdict(client.central_unit),
            "diagnostics": diagnostics,
            "sections": {n: s.alarm_state.value for n, s in client.sections.items()},
            "pg_states_received": len(client.pg_outputs),
            "configured_devices": len(client.devices),
            "devices_with_status": sum(d.connection is not None for d in client.devices.values()),
            "packet_counts": dict(packets),
            "diagnostic_responses": dict(diagnostic_responses),
            "state_change_counts": dict(changes),
        }, indent=2), flush=True)
        if not (
            client.connected
            and client.initialization_complete
            and client.central_unit.model
            and client.sections
            and len(client.pg_outputs) == config.number_of_pg_outputs
            and all(d.connection is not None for d in client.devices.values())
        ):
            raise RuntimeError("Hardware smoke test did not receive all expected basic states")
    finally:
        await client.close()
        if log:
            log.close()
        print("Client closed.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/jablotron.toml")
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument("--log", help="readable protocol log file (codes are redacted)")
    parser.add_argument("--heartbeat", type=float, default=0.5, help="heartbeat interval in seconds")
    parser.add_argument("--reconnect", action="store_true", help="enable reconnect for manual USB unplug/replug testing")
    args = parser.parse_args()
    if not 0 < args.seconds <= 300:
        parser.error("--seconds must be between 0 and 300")
    if not 0 < args.heartbeat <= 300:
        parser.error("--heartbeat must be between 0 and 300")
    asyncio.run(run(args.config, args.seconds, args.log, args.heartbeat, args.reconnect))
