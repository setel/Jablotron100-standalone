"""Replaceable byte transport and Linux hidraw implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

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
    """Asynchronous wrapper over the blocking Linux hidraw character device."""

    def __init__(
        self,
        port: str = "auto",
        *,
        detector: Callable[[], str | None] = detect_serial_port,
    ) -> None:
        self._configured_port = port
        self._detector = detector
        self._port: str | None = None
        self._reader: BinaryIO | None = None
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
        self._reader = await asyncio.to_thread(open, port, "rb", 0)
        self._port = port

    async def close(self) -> None:
        reader, self._reader = self._reader, None
        if reader is not None:
            await asyncio.to_thread(reader.close)
        self._port = None

    async def read(self) -> bytes:
        if self._reader is None:
            raise TransportClosed("transport is not open")
        return await asyncio.to_thread(self._reader.read, STREAM_PACKET_SIZE)

    async def write(self, data: bytes) -> None:
        if self._port is None or self._reader is None:
            raise TransportClosed("transport is not open")
        async with self._write_lock:
            await asyncio.to_thread(self._write_blocking, self._port, data)

    @staticmethod
    def _write_blocking(port: str, data: bytes) -> None:
        with open(port, "wb", buffering=0) as stream:
            stream.write(data)
