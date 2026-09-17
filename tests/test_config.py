import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from jablotron100 import (
    ConfigurationError,
    DeviceDefinition,
    DeviceType,
    JablotronClient,
    JablotronConfig,
    create_config_from_flink,
    load_config,
    load_flink_csv,
    load_flink_pg_outputs_csv,
    load_flink_sections_csv,
    load_home_assistant_config,
    merge_flink_devices,
    merge_flink_names,
    save_config,
)


class ConfigImportTests(unittest.TestCase):
    def _write(self, document: object) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "core.config_entries"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_imports_jablotron_entry_from_home_assistant_storage(self) -> None:
        path = self._write(
            {
                "version": 1,
                "data": {
                    "entries": [
                        {"domain": "unrelated", "data": {}},
                        {
                            "entry_id": "jab-entry",
                            "domain": "jablotron100",
                            "data": {
                                "serial_port": "auto",
                                "password": "1234",
                                "number_of_devices": 3,
                                "number_of_pg_outputs": 2,
                                "devices": [
                                    "keypad",
                                    "motion_detector",
                                    "empty",
                                ],
                            },
                            "options": {
                                "partially_arming_mode": "home_mode",
                                "require_code_to_arm": True,
                            },
                        },
                    ]
                },
            }
        )

        config = load_home_assistant_config(path)

        self.assertEqual(config.source_entry_id, "jab-entry")
        self.assertEqual(config.number_of_devices, 3)
        self.assertEqual(config.number_of_pg_outputs, 2)
        self.assertEqual(config.devices[1].device_type, DeviceType.MOTION_DETECTOR)
        self.assertEqual(config.partially_arming_mode, "home_mode")
        self.assertTrue(config.require_code_to_arm)
        self.assertNotIn("1234", repr(config))
        self.assertNotIn("password", config.redacted_dict())

    def test_accepts_sanitized_single_entry_export(self) -> None:
        path = self._write(
            {
                "domain": "jablotron100",
                "entry_id": "sanitized",
                "data": {
                    "serial_port": "auto",
                    "number_of_devices": 1,
                    "number_of_pg_outputs": 0,
                    "devices": ["door_opening_detector"],
                },
                "options": {},
            }
        )
        config = load_home_assistant_config(path)

        self.assertIsNone(config.code)
        self.assertEqual(
            config.devices[0].device_type, DeviceType.DOOR_OPENING_DETECTOR
        )
        with self.assertRaisesRegex(ConfigurationError, "code is missing"):
            JablotronClient.from_config(config)

    def test_rejects_mismatched_device_count(self) -> None:
        path = self._write(
            {
                "number_of_devices": 2,
                "devices": ["keypad"],
            }
        )
        with self.assertRaisesRegex(ConfigurationError, "does not match"):
            load_home_assistant_config(path)

    def test_standalone_toml_is_sparse_and_round_trips(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "jablotron.toml"
        path.write_text(
            """
[connection]
port = "auto"
code_env = "TEST_JABLOTRON_CODE"

[system]
number_of_devices = 4
number_of_pg_outputs = 2

[[devices]]
number = 2
type = "motion_detector"
name = "Hall"
""",
            encoding="utf-8",
        )
        config = load_config(path)
        self.assertEqual(config.number_of_devices, 4)
        self.assertEqual(config.devices[0].device_type, DeviceType.EMPTY)
        self.assertEqual(config.devices[1].name, "Hall")

        exported = Path(directory.name) / "exported.toml"
        save_config(config, exported)
        text = exported.read_text(encoding="utf-8")
        self.assertNotIn("code =", text)
        self.assertEqual(load_config(exported), config)

    def test_merges_windows_1250_flink_names_and_models(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        csv_path = Path(directory.name) / "Periferie.csv"
        csv_path.write_bytes(
            (
                '"Pozice";"Jméno";"Typ";"Sériové číslo"\n'
                '"0";"Ústředna";"JA-107K";"1000"\n'
                '"1";"Pohyb zádveří";"JA-110P";"2000"\n'
                '"2";"Periferie 2";"";""\n'
                '"3";"Otevřené okno";"JA-118M [1]";"3000"\n'
            ).encode("cp1250")
        )
        flink = load_flink_csv(csv_path)
        base = JablotronConfig(
            devices=(
                DeviceDefinition(1, DeviceType.MOTION_DETECTOR),
                DeviceDefinition(2, DeviceType.EMPTY),
                DeviceDefinition(3, DeviceType.WINDOW_OPENING_DETECTOR),
            )
        )

        merged = merge_flink_devices(base, flink)
        self.assertEqual(merged.devices[0].name, "Pohyb zádveří")
        self.assertEqual(merged.devices[0].model, "JA-110P")
        self.assertIsNone(merged.devices[0].serial_number)
        self.assertEqual(
            merged.devices[2].device_type,
            DeviceType.WINDOW_OPENING_DETECTOR,
        )
        self.assertEqual(merged.devices[2].name, "Otevřené okno")

        starter = create_config_from_flink(
            flink, number_of_devices=3, number_of_pg_outputs=2
        )
        self.assertEqual(
            starter.devices[0].device_type, DeviceType.MOTION_DETECTOR
        )
        self.assertEqual(starter.devices[2].device_type, DeviceType.CUSTOM)

        sections_path = Path(directory.name) / "Sekce.csv"
        sections_path.write_bytes(
            (
                '"Pozice";"Název sekce";"Stav"\n'
                '"1";"Dům";"OK"\n'
                '"2";"Kůlna";"OK"\n'
            ).encode("cp1250")
        )
        pg_path = Path(directory.name) / "PGvystupy.csv"
        pg_path.write_bytes(
            (
                '"Pozice";"Jméno";"Logika"\n'
                '"1";"Vrata";"Spínací"\n'
                '"2";"Světlo";"Spínací"\n'
            ).encode("cp1250")
        )
        named = merge_flink_names(
            replace(merged, number_of_pg_outputs=2),
            sections=load_flink_sections_csv(sections_path),
            pg_outputs=load_flink_pg_outputs_csv(pg_path),
        )
        self.assertEqual(named.sections[0].name, "Dům")
        self.assertEqual(named.pg_outputs[1].name, "Světlo")

        exported = Path(directory.name) / "named.toml"
        save_config(named, exported)
        self.assertEqual(load_config(exported), named)


if __name__ == "__main__":
    unittest.main()
