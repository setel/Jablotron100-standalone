import unittest

from jablotron100 import ArmMode, ProtocolError
from jablotron100.protocol import (
    create_authorisation_code,
    create_device_diagnostics,
    create_device_diagnostics_request,
    create_device_status_request,
    create_devices_sections_request,
    create_pg_control,
    create_section_control,
    pack_reports,
    split_report,
)


class ProtocolTests(unittest.TestCase):
    def test_split_report_uses_length_byte_and_stops_at_padding(self) -> None:
        report = bytes.fromhex("52010280022301000000")
        self.assertEqual(
            split_report(report),
            [bytes.fromhex("520102"), bytes.fromhex("80022301")],
        )

    def test_split_report_rejects_truncated_packet(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "truncated"):
            split_report(bytes.fromhex("520501"))

    def test_control_packets_match_upstream_format(self) -> None:
        self.assertEqual(
            create_section_control(1, ArmMode.DISARMED),
            bytes.fromhex("80020d90"),
        )
        self.assertEqual(
            create_section_control(1, ArmMode.ARMED_FULL),
            bytes.fromhex("80020da0"),
        )
        self.assertEqual(create_pg_control(2, True), bytes.fromhex("8003230101"))

    def test_initialization_packets_match_upstream_format(self) -> None:
        self.assertEqual(
            create_device_status_request(24), bytes.fromhex("52020a18")
        )
        self.assertEqual(
            create_devices_sections_request(1, 120),
            bytes.fromhex("3a020178"),
        )
        self.assertEqual(
            create_device_diagnostics(24, True),
            bytes.fromhex("94021801"),
        )
        self.assertEqual(
            create_device_diagnostics_request(24),
            bytes.fromhex("9603180900"),
        )
        self.assertEqual(
            create_device_diagnostics(24, False),
            bytes.fromhex("94021800"),
        )

    def test_four_digit_authorisation_matches_upstream_algorithm(self) -> None:
        self.assertEqual(
            create_authorisation_code("1234"),
            bytes.fromhex("80080339393931323334"),
        )

    def test_pack_reports_never_exceeds_hid_report_size(self) -> None:
        packets = [
            bytes((1, 29)) + bytes(29),
            bytes((2, 29)) + bytes(29),
            b"\x03\x01\xff",
        ]
        reports = pack_reports(packets)
        self.assertEqual(reports, [packets[0] + packets[1], packets[2]])
        self.assertTrue(all(len(report) <= 64 for report in reports))


if __name__ == "__main__":
    unittest.main()
