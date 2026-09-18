import unittest

from jablotron100 import (
    DeviceConnection,
    DeviceFault,
    DeviceInfoType,
    DeviceStateEvent,
    DeviceStateFlag,
)
from jablotron100.devices import (
    parse_device_info,
    parse_device_state,
    parse_device_status,
    parse_system_info,
)


class DeviceStatusTests(unittest.TestCase):
    def test_wired_device_status(self) -> None:
        status = parse_device_status(bytes.fromhex("52078a0104000000f2"))

        self.assertEqual(status.number, 1)
        self.assertEqual(status.connection, DeviceConnection.WIRED)
        self.assertIsNone(status.signal_strength)
        self.assertIsNone(status.battery)

    def test_wireless_device_status(self) -> None:
        status = parse_device_status(bytes.fromhex("52098a180410b301fcab0a"))

        self.assertEqual(status.number, 24)
        self.assertEqual(status.connection, DeviceConnection.WIRELESS)
        self.assertEqual(status.signal_strength, 55)
        self.assertIsNotNone(status.battery)
        self.assertEqual(status.battery.level, 100)
        self.assertTrue(status.battery.ok)

    def test_low_battery_status(self) -> None:
        status = parse_device_status(bytes.fromhex("52098a184610fffffc4d08"))

        self.assertEqual(status.signal_strength, 65)
        self.assertEqual(status.battery.level, 80)
        self.assertTrue(status.battery.ok)


class DeviceStateTests(unittest.TestCase):
    def test_wireless_activity_packet(self) -> None:
        state = parse_device_state(bytes.fromhex("550900c90006b1cdf21c06"))

        self.assertEqual(state.number, 24)
        self.assertTrue(state.active)
        self.assertEqual(state.event, DeviceStateEvent.INSTANT_ALARM)
        self.assertIsNone(state.fault)
        self.assertFalse(state.heartbeat)
        self.assertEqual(state.signal_strength, 30)

    def test_sabotage_packet_with_flags(self) -> None:
        state = parse_device_state(bytes.fromhex("550986e08007e15deb0d13"))

        self.assertEqual(state.number, 30)
        self.assertTrue(state.active)
        self.assertEqual(state.event, DeviceStateEvent.SABOTAGE)
        self.assertEqual(state.fault, DeviceFault.SABOTAGE)
        self.assertTrue(
            state.flags & DeviceStateFlag.NO_REACTION_WHEN_PARTIALLY_ARMED
        )
        self.assertEqual(state.signal_strength, 95)

    def test_heartbeat_packet(self) -> None:
        state = parse_device_state(bytes.fromhex("55093308010ac5b6500b0d"))

        self.assertEqual(state.number, 40)
        self.assertTrue(state.heartbeat)
        self.assertIsNone(state.fault)
        self.assertEqual(state.signal_strength, 65)

    def test_device_number_boundaries(self) -> None:
        for number in (0, 1, 37, 38, 101, 102, 165, 166, 229, 230, 251, 254):
            with self.subTest(number=number):
                packet = _create_state_packet(number)
                self.assertEqual(parse_device_state(packet).number, number)


class DeviceInfoTests(unittest.TestCase):
    def test_captured_ja107k_extended_gsm_signal(self) -> None:
        # Uninterpreted radio fields are zeroed; preserve the confirmed signal.
        for value in (50, 60):
            with self.subTest(signal=value):
                packet = bytearray.fromhex("900cea0a090f84d5000000000000")
                packet[8] = value
                info = parse_device_info(bytes(packet))
                self.assertEqual(info.number, 234)
                self.assertEqual(info.info_types, (DeviceInfoType.GSM_EXTENDED,))
                self.assertIsNone(info.gsm_connected)
                self.assertEqual(info.gsm_signal_strength, value)

    def test_unknown_info_type_is_reported_without_guessing(self) -> None:
        info = parse_device_info(bytes.fromhex("900cea0a090f84d6320000000000"))
        self.assertEqual(info.unknown_info_types, (22,))
        self.assertIsNone(info.gsm_connected)
        self.assertIsNone(info.gsm_signal_strength)

    def test_thermometer_temperature(self) -> None:
        info = parse_device_info(
            bytes.fromhex("900e089c0b0f85ae0000ee00004f00ce")
        )

        self.assertEqual(info.number, 8)
        self.assertEqual(info.temperature, 23.8)
        self.assertEqual(
            info.info_types,
            (DeviceInfoType.INPUT_VALUE, DeviceInfoType.INPUT_EXTENDED),
        )

    def test_smoke_detector_temperature(self) -> None:
        info = parse_device_info(bytes.fromhex("900a140a070f87831a002521"))

        self.assertEqual(info.number, 20)
        self.assertTrue(info.requested)
        self.assertEqual(info.temperature, 26.0)
        self.assertEqual(info.info_types, (DeviceInfoType.SMOKE,))

    def test_siren_battery_and_power(self) -> None:
        info = parse_device_info(
            bytes.fromhex("900d050a0a0a896c003f026c012f02")
        )

        self.assertEqual(info.battery.level, 100)
        self.assertTrue(info.battery.ok)
        self.assertEqual(info.battery_standby_voltage, 57.5)
        self.assertEqual(info.battery_load_voltage, 55.9)

    def test_electricity_meter_pulses(self) -> None:
        info = parse_device_info(
            bytes.fromhex(
                "9023249c200c3d906023274091ec060020"
                "91a8b50310906523274091ec06002091a8b50310"
            )
        )

        self.assertEqual(info.number, 36)
        self.assertEqual(info.pulses, (1772, 46504))
        self.assertEqual(info.info_types, (DeviceInfoType.PULSE,) * 4)

    def test_central_unit_bus_diagnostics(self) -> None:
        info = parse_device_info(bytes.fromhex("9009000a0648006a017b02"))
        self.assertTrue(info.power_supply_ok)
        self.assertEqual(info.battery.level, 80)
        self.assertEqual(info.buses[0].number, 1)
        self.assertEqual(info.buses[0].voltage, 12.3)
        self.assertEqual(info.buses[0].devices_loss, 2)
        self.assertEqual(info.buses[0].current_ma, 2)

    def test_lan_and_gsm_diagnostics(self) -> None:
        lan = parse_device_info(
            bytes.fromhex("900be90a080f00a682c0a8010a")
        )
        gsm = parse_device_info(
            bytes.fromhex("900bea0a080f00a44900000001")
        )
        self.assertTrue(lan.lan_connected)
        self.assertTrue(lan.dhcp_ok)
        self.assertEqual(lan.ip_address, "192.168.1.10")
        self.assertTrue(gsm.gsm_connected)
        self.assertEqual(gsm.gsm_signal_strength, 73)

    def test_system_info(self) -> None:
        self.assertEqual(
            parse_system_info(bytes.fromhex("4008024a412d3130374b")),
            (2, "JA-107K"),
        )


def _create_state_packet(number: int, active: bool = True) -> bytes:
    packet = bytearray(11)
    packet[0] = 0x55
    packet[1] = 9
    packet[3] = _state_value(number, active)
    packet[4:6] = (number << 6).to_bytes(2, byteorder="little")
    return bytes(packet)


def _state_value(number: int, active: bool) -> int:
    if number <= 37:
        normalized = number
    elif number <= 101:
        normalized = number - 64
    elif number <= 165:
        normalized = number - 128
    elif number <= 229:
        normalized = number - 192
    else:
        normalized = number - 256
    return normalized * 4 + 104 + (0 if active else 2)


if __name__ == "__main__":
    unittest.main()
