import asyncio
import unittest

from jablotron100 import (
    ArmMode,
    DeviceDefinition,
    DeviceType,
    JablotronClient,
)


class FakeTransport:
    def __init__(self) -> None:
        self.opened = False
        self.reads: asyncio.Queue[bytes] = asyncio.Queue()
        self.writes: list[bytes] = []

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.opened = False

    async def read(self) -> bytes:
        return await self.reads.get()

    async def write(self, data: bytes) -> None:
        self.writes.append(data)


class ClientTests(unittest.IsolatedAsyncioTestCase):
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
                DeviceDefinition(3, DeviceType.MOTION_DETECTOR),
                DeviceDefinition(4, DeviceType.EMPTY),
            ),
        )

        self.assertEqual(set(client.devices), {1, 2, 3})
        self.assertEqual(client.devices[3].device_type, "motion_detector")

        await client.start()
        await transport.reads.put(_device_packet(1) + _device_packet(3) + b"\x00")
        await asyncio.sleep(0)
        await client.close()

        self.assertIsNone(client.devices[1].active)
        self.assertTrue(client.devices[3].active)


def _device_packet(number: int) -> bytes:
    packet = bytearray(11)
    packet[0] = 0x55
    packet[1] = 9
    packet[3] = number * 4 + 104
    packet[4:6] = (number << 6).to_bytes(2, byteorder="little")
    return bytes(packet)


if __name__ == "__main__":
    unittest.main()
