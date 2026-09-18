"""Replaceable byte transport and Linux hidraw implementation."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from .errors import SerialPortNotDetected, TransportClosed
from .protocol import STREAM_PACKET_SIZE

HIDRAW_SYSFS = Path("/sys/class/hidraw")
JABLOTRON_USB_ID = "16D6:0008"


@runtime_checkable
class Transport(Protocol):
    """Minimal transport required by JablotronClient."""

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def read(self) -> bytes: ...

    async def write(self, data: bytes) -> None: ...


def detect_serial_port(sysfs: Path = HIDRAW_SYSFS) -> str | None:
    """Return the hidraw device whose sysfs path contains Jablotron's USB ID."""
    try:
        candidates = sorted(sysfs.iterdir())
    except OSError:
        return None

    for candidate in candidates:
        try:
            real_path = str(candidate.resolve())
        except OSError:
            continue
        if JABLOTRON_USB_ID in real_path.upper():
            return f"/dev/{candidate.name}"
    return None


class HidrawTransport:
    """Linux hidraw transport with cancellable, nonblocking reads.

    A blocked worker-thread read survives task cancellation and can prevent
    asyncio.run() from exiting. Wait for readability in the event loop instead.
    """

    def __init__(
        self,
        port: str = "auto",
        *,
        detector: Callable[[], str | None] = detect_serial_port,
    ) -> None:
        self._configured_port = port
        self._detector = detector
        self._port: str | None = None
        self._reader: int | None = None
        self._read_ready: asyncio.Future[None] | None = None
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    @property
    def port(self) -> str | None:
        return self._port

    async def open(self) -> None:
        if self._reader is not None:
            return
        port = (
            self._detector()
            if self._configured_port == "auto"
            else self._configured_port
        )
        if port is None:
            raise SerialPortNotDetected("no Jablotron USB device was detected")
        self._reader = os.open(port, os.O_RDONLY | os.O_NONBLOCK)
        self._port = port

    async def close(self) -> None:
        reader, self._reader = self._reader, None
        if reader is not None:
            asyncio.get_running_loop().remove_reader(reader)
            ready, self._read_ready = self._read_ready, None
            if ready is not None and not ready.done():
                ready.set_exception(TransportClosed("transport is closed"))
            os.close(reader)
        self._port = None

    async def read(self) -> bytes:
        async with self._read_lock:
            reader = self._reader
            if reader is None:
                raise TransportClosed("transport is not open")
            loop = asyncio.get_running_loop()
            while self._reader == reader:
                try:
                    return os.read(reader, STREAM_PACKET_SIZE)
                except BlockingIOError:
                    pass
                ready = loop.create_future()
                self._read_ready = ready

                def readable() -> None:
                    if not ready.done():
                        ready.set_result(None)

                try:
                    loop.add_reader(reader, readable)
                    await ready
                finally:
                    if self._read_ready is ready:
                        loop.remove_reader(reader)
                        self._read_ready = None
            raise TransportClosed("transport is closed")

    async def write(self, data: bytes) -> None:
        if self._port is None or self._reader is None:
            raise TransportClosed("transport is not open")
        async with self._write_lock:
            await asyncio.to_thread(self._write_blocking, self._port, data)

    @staticmethod
    def _write_blocking(port: str, data: bytes) -> None:
        with open(port, "wb", buffering=0) as stream:
            stream.write(data)
