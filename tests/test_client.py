import asyncio
import unittest
from unittest.mock import patch
from jablotron100.protocol import create_authorisation_code

from jablotron100 import (
    ArmMode,
    DeviceDefinition,
    DeviceType,
    JablotronClient,
    PGOutputDefinition,
    SectionDefinition,
)


class FakeTransport:
    def __init__(self) -> None:
        self.opened = False
        self.open_count = 0
        self.reads: asyncio.Queue[bytes] = asyncio.Queue()
        self.writes: list[bytes] = []

    async def open(self) -> None:
        self.opened = True
        self.open_count += 1

    async def close(self) -> None:
        self.opened = False

    async def read(self) -> bytes:
        return await self.reads.get()

    async def write(self, data: bytes) -> None:
        self.writes.append(data)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_captured_front_door_open_and_close(self):
        client = JablotronClient(code="1234", transport=FakeTransport())
        changes = []
        client.add_state_listener(lambda change: changes.append(change))
        await client._handle_state_packet(bytes.fromhex("d8110000040200000000000000000000000000"))
        self.assertTrue(client.devices[10].active)
        await client._handle_state_packet(bytes.fromhex("550844928002d074802e"))
        self.assertFalse(client.devices[10].active)
        await client._handle_state_packet(bytes.fromhex("d8110008000200000000000000000000000000"))
        self.assertFalse(client.devices[10].active)
        self.assertTrue(client.devices[3].active)
        self.assertEqual([c.value.active for c in changes if c.kind == "device" and c.number == 10], [True, False])

    async def test_device_bitmap_updates_only_state_capable_devices(self):
        client = JablotronClient(code="1234", transport=FakeTransport(), devices=(
            DeviceDefinition(1, DeviceType.MOTION_DETECTOR),
            DeviceDefinition(2, DeviceType.KEYPAD),
            DeviceDefinition(3, DeviceType.EMPTY),
        ))
        await client._handle_state_packet(bytes.fromhex("d802000e"))
        self.assertTrue(client.devices[1].active)
        self.assertIsNone(client.devices[2].active)
        self.assertNotIn(3, client.devices)
        await client._handle_state_packet(bytes.fromhex("d8020000"))
        self.assertFalse(client.devices[1].active)

    async def test_keepalive_renews_session_but_not_during_entry_delay(self):
        for packet, should_authorize in (("510401000700", True), ("510441000700", False)):
            with self.subTest(packet=packet):
                transport = FakeTransport()
                client = JablotronClient(code="1234", transport=transport, keepalive_interval=0.001)
                await client._handle_state_packet(bytes.fromhex(packet))
                client._running = True
                with patch("jablotron100.client.monotonic", side_effect=[0, 31, 31, 31, 31]):
                    task = asyncio.create_task(client._keepalive_loop())
                    for _ in range(10):
                        if transport.writes:
                            break
                        await asyncio.sleep(0.001)
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                client._running = False
                self.assertTrue(transport.writes)
                self.assertEqual(create_authorisation_code("1234") in b"".join(transport.writes), should_authorize)

    async def test_generic_gsm_status_does_not_invent_zero_signal(self) -> None:
        client = JablotronClient(code="1234", transport=FakeTransport())
        await client._handle_state_packet(bytes.fromhex("4008024a412d3130374b"))
        await client._handle_state_packet(bytes.fromhex("52078aea05000000f2"))
        self.assertIsNone(client.diagnostics.gsm_signal_strength)
        await client._handle_state_packet(bytes.fromhex("52048aead532"))
        self.assertEqual(client.diagnostics.gsm_signal_strength, 50)
        await client._handle_state_packet(bytes.fromhex("900cea0a090f84d5320000000000"))
        self.assertEqual(client.diagnostics.gsm_signal_strength, 50)
        self.assertIsNone(client.diagnostics.gsm_connected)

    async def test_client_publishes_packets_and_sends_controls(self) -> None:
        transport = FakeTransport()
        client = JablotronClient(
            code="1234", transport=transport, keepalive_interval=3600
        )
        received: list[bytes] = []
        client.add_packet_listener(lambda event: received.append(event.packet))

        await client.start()
        await transport.reads.put(bytes.fromhex("5201020000"))
        await asyncio.sleep(0)
        await client.set_pg_output(2, True)
        await client.set_section(1, ArmMode.ARMED_FULL)
        await client.close()

        self.assertEqual(received, [bytes.fromhex("520102")])
        self.assertIn(bytes.fromhex("8003230101"), transport.writes)
        self.assertIn(bytes.fromhex("80020da0"), transport.writes)
        self.assertFalse(transport.opened)

    async def test_client_builds_device_snapshot_from_captured_packets(self) -> None:
        transport = FakeTransport()
        client = JablotronClient(
            code="1234", transport=transport, keepalive_interval=3600
        )
        await client.start()
        await transport.reads.put(
            bytes.fromhex("52098a180410b301fcab0a")
            + bytes.fromhex("900b189c080419ae00004a0000")
            + b"\x00"
        )
        await asyncio.sleep(0)
        await client.close()

        snapshot = client.devices[24]
        self.assertEqual(snapshot.signal_strength, 55)
        self.assertEqual(snapshot.battery_level, 40)
        self.assertTrue(snapshot.battery_ok)
        self.assertEqual(snapshot.temperature, 7.4)

    async def test_configured_devices_exist_before_packets(self) -> None:
        transport = FakeTransport()
        client = JablotronClient(
            code="1234",
            transport=transport,
            devices=(
                DeviceDefinition(1, DeviceType.RADIO_MODULE),
                DeviceDefinition(2, DeviceType.KEYPAD),
                DeviceDefinition(
                    3,
                    DeviceType.MOTION_DETECTOR,
                    name="Hall motion",
                    model="JA-110P",
                ),
                DeviceDefinition(4, DeviceType.EMPTY),
            ),
            sections=(SectionDefinition(1, "House"),),
            pg_outputs=(PGOutputDefinition(1, "Gate"),),
        )

        self.assertEqual(set(client.devices), {1, 2, 3})
        self.assertEqual(client.devices[3].device_type, "motion_detector")
        self.assertEqual(client.devices[3].name, "Hall motion")
        self.assertEqual(client.devices[3].model, "JA-110P")
        self.assertEqual(client.section_names, {1: "House"})
        self.assertEqual(client.pg_output_names, {1: "Gate"})

        await client.start()
        await transport.reads.put(_device_packet(1) + _device_packet(3) + b"\x00")
        await asyncio.sleep(0)
        await client.close()

        self.assertIsNone(client.devices[1].active)
        self.assertTrue(client.devices[3].active)

    async def test_reconnects_after_transport_eof(self) -> None:
        transport = FakeTransport()
        client = JablotronClient(
            code="1234",
            transport=transport,
            keepalive_interval=3600,
            reconnect_delay=0.001,
            reconnect_max_delay=0.005,
        )
        changes: list[bool] = []
        client.add_state_listener(
            lambda change: (
                changes.append(change.value)
                if change.kind == "connection"
                else None
            )
        )

        await client.start()
        await transport.reads.put(b"")
        for _ in range(100):
            if transport.open_count >= 2 and client.connected:
                break
            await asyncio.sleep(0.002)
        await client.close()

        self.assertGreaterEqual(transport.open_count, 2)
        self.assertIn(False, changes)
        self.assertGreaterEqual(changes.count(True), 2)

    async def test_initialization_requests_identity_and_device_status(self) -> None:
        transport = FakeTransport()
        client = JablotronClient(
            code="1234",
            transport=transport,
            devices=(
                DeviceDefinition(1, DeviceType.RADIO_MODULE),
                DeviceDefinition(2, DeviceType.MOTION_DETECTOR),
            ),
        )
        await client.start()
        await client.close()

        combined = b"".join(transport.writes)
        self.assertIn(bytes.fromhex("300102"), combined)
        self.assertIn(bytes.fromhex("52020a01"), combined)
        self.assertIn(bytes.fromhex("52020a02"), combined)
        self.assertIn(bytes.fromhex("3a020102"), combined)

    async def test_exposes_central_unit_and_lan_diagnostics(self) -> None:
        transport = FakeTransport()
        client = JablotronClient(
            code="1234", transport=transport, keepalive_interval=3600
        )
        await client.start()
        await transport.reads.put(
            bytes.fromhex(
                "4008024a412d3130374b"
                "4003084831"
                "4003094631"
                "900be90a080f00a682c0a8010a"
                "00"
            )
        )
        await asyncio.sleep(0)

        self.assertEqual(client.central_unit.model, "JA-107K")
        self.assertEqual(client.central_unit.hardware_version, "H1")
        self.assertEqual(client.central_unit.firmware_version, "F1")
        self.assertTrue(client.diagnostics.lan_connected)
        self.assertEqual(client.diagnostics.lan_ip, "192.168.1.10")
        await client.close()


def _device_packet(number: int) -> bytes:
    packet = bytearray(11)
    packet[0] = 0x55
    packet[1] = 9
    packet[3] = number * 4 + 104
    packet[4:6] = (number << 6).to_bytes(2, byteorder="little")
    return bytes(packet)


if __name__ == "__main__":
    unittest.main()
