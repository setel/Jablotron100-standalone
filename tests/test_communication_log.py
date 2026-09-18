import asyncio
from pathlib import Path
import tempfile
import unittest

from jablotron100 import CommunicationLog, LoggedTransport
from jablotron100.protocol import create_authorisation_code


class CommunicationLogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=".")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "communication.log"

    def test_redacts_authorization_both_directions_and_malformed_reports(self):
        secret = create_authorisation_code("87654321")
        with CommunicationLog(self.path) as log:
            for direction in ("TX", "RX"):
                log.report(direction, secret + bytes.fromhex("520102"))
                log.report(direction, secret + b"\xff")
        content = self.path.read_text()
        self.assertNotIn(secret.hex(" "), content)
        self.assertNotIn(secret[3:].hex(" "), content)
        self.assertIn("SKRYTO", content)
        self.assertIn("Heartbeat", content)

    def test_deduplicates_interleaved_repeats_but_preserves_changes(self):
        with CommunicationLog(self.path) as log:
            for _ in range(3):
                log.report("TX", bytes.fromhex("520102"))
                log.report("RX", bytes.fromhex("500100"))
            log.report("RX", bytes.fromhex("500101"))
            log.report("RX", bytes.fromhex("500100"))
        content = self.path.read_text()
        self.assertEqual(content.count("Heartbeat"), 1)
        self.assertEqual(content.count("PG zapnuto"), 3)
        self.assertEqual(content.count("potlačeno 2"), 2)

    def test_repeat_interval_and_rotation(self):
        with CommunicationLog(self.path, repeat_seconds=0, max_bytes=200, backup_count=2) as log:
            for _ in range(20):
                log.report("TX", bytes.fromhex("520102"))
        self.assertTrue(self.path.with_suffix(".log.1").exists())
        self.assertLessEqual(len(list(self.path.parent.iterdir())), 3)

    def test_wrapper_preserves_reports_and_logs_only_successful_writes(self):
        class Fake:
            async def open(self): pass
            async def close(self): pass
            async def read(self): return bytes.fromhex("500100")
            async def write(self, data): raise OSError("disconnected")

        async def exercise(log):
            transport = LoggedTransport(Fake(), log)
            await transport.open()
            self.assertEqual(await transport.read(), bytes.fromhex("500100"))
            with self.assertRaises(OSError):
                await transport.write(bytes.fromhex("520102"))
            await transport.close()

        with CommunicationLog(self.path) as log:
            asyncio.run(exercise(log))
        content = self.path.read_text()
        self.assertIn("PŘIJÍMÁM", content)
        self.assertNotIn("ODESÍLÁM", content)
