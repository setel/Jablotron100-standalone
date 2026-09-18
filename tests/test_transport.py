"""Exercise actual descriptor readiness without physical alarm hardware."""

import asyncio
import os
import unittest
from unittest.mock import patch

from jablotron100.errors import TransportClosed
from jablotron100.transport import HidrawTransport


class HidrawTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reader, self.writer = os.pipe()
        os.set_blocking(self.reader, False)
        self.transport = HidrawTransport("/fake/hidraw")
        with patch("jablotron100.transport.os.open", return_value=self.reader):
            await self.transport.open()

    async def asyncTearDown(self):
        await self.transport.close()
        if self.writer is not None:
            os.close(self.writer)

    async def test_read_waits_for_data(self):
        task = asyncio.create_task(self.transport.read())
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        os.write(self.writer, b"report")
        self.assertEqual(await asyncio.wait_for(task, 1), b"report")

    async def test_cancel_idle_read_then_read_again(self):
        task = asyncio.create_task(self.transport.read())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        os.write(self.writer, b"next report")
        self.assertEqual(await self.transport.read(), b"next report")

    async def test_close_wakes_idle_read(self):
        task = asyncio.create_task(self.transport.read())
        await asyncio.sleep(0)
        await self.transport.close()
        with self.assertRaises(TransportClosed):
            await asyncio.wait_for(task, 1)
        self.assertIsNone(self.transport.port)

    async def test_read_returns_eof_when_peer_closes(self):
        task = asyncio.create_task(self.transport.read())
        await asyncio.sleep(0)
        os.close(self.writer)
        self.writer = None
        self.assertEqual(await asyncio.wait_for(task, 1), b"")
