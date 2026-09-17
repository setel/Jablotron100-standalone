import json
import tempfile
import unittest
from pathlib import Path

from jablotron100 import (
    ConfigurationError,
    DeviceType,
    JablotronClient,
    load_config,
    load_home_assistant_config,
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


if __name__ == "__main__":
    unittest.main()
