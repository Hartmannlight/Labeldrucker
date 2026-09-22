"""B1 protocol, independently implemented from the references in README.md."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import reduce
from operator import xor
import struct
from typing import Protocol


def frame(command: int, data: bytes) -> bytes:
    if not 0 <= command <= 255 or len(data) > 255:
        raise ValueError("Invalid NIIMBOT frame")
    body = bytes((command, len(data))) + data
    return b"\x55\x55" + body + bytes((reduce(xor, body),)) + b"\xaa\xaa"


class FrameDecoder:
    """Reassemble fragmented/coalesced transport reads; reject bad checksums."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self.buffer.extend(data)
        packets = []
        while len(self.buffer) >= 2:
            if self.buffer[:2] != b"\x55\x55":
                del self.buffer[0]
                continue
            if len(self.buffer) < 4:
                break
            length = self.buffer[3] + 7
            if len(self.buffer) < length:
                break
            packet = bytes(self.buffer[:length])
            if packet[-2:] != b"\xaa\xaa" or reduce(xor, packet[2:-2]):
                raise ValueError("Invalid NIIMBOT response checksum or trailer")
            packets.append((packet[2], packet[4:-3]))
            del self.buffer[:length]
        return packets


@dataclass(frozen=True)
class Page:
    width: int
    height: int
    bits: bytes

    def __post_init__(self):
        if not 1 <= self.width <= 384 or not 1 <= self.height <= 65535:
            raise ValueError("B1 raster dimensions out of range")
        stride = (self.width + 7) // 8
        if len(self.bits) != stride * self.height:
            raise ValueError("Raster byte length mismatch")
        if self.width % 8:
            mask = (1 << (8 - self.width % 8)) - 1
            if any(self.bits[y * stride + stride - 1] & mask for y in range(self.height)):
                raise ValueError("Raster padding must be white")


def rows(page: Page):
    stride = (page.width + 7) // 8
    y = 0
    while y < page.height:
        row = page.bits[y * stride:(y + 1) * stride]
        run = 1
        while run < 200 and y + run < page.height:
            if page.bits[(y + run) * stride:(y + run + 1) * stride] != row:
                break
            run += 1
        count = sum(byte.bit_count() for byte in row)
        if count:
            yield frame(0x85, struct.pack(">H", y) + bytes((0, count & 255, count >> 8, run)) + row)
        else:
            yield frame(0x84, struct.pack(">HB", y, run))
        y += run


class Transport(Protocol):
    async def write(self, data: bytes) -> None: ...
    async def read(self) -> bytes: ...


class B1Protocol:
    def __init__(self, transport: Transport, *, timeout=8.0, completion_timeout=90.0):
        self.transport = transport
        self.decoder = FrameDecoder()
        self.timeout = timeout
        self.completion_timeout = completion_timeout
        self.bytes_sent = 0
        self.print_started = False

    async def write(self, data: bytes):
        await self.transport.write(data)
        self.bytes_sent += len(data)

    async def request(self, command, data=b"\x01", *, response=None, prefix=b"", ack=False):
        await self.write(prefix + frame(command, data))
        expected = command + 1 if response is None else response

        async def receive():
            while True:
                for opcode, payload in self.decoder.feed(await self.transport.read()):
                    if opcode in (0x00, 0xDB):
                        raise RuntimeError(f"NIIMBOT rejected command 0x{command:02x}")
                    if opcode == expected:
                        if ack and payload != b"\x01":
                            raise RuntimeError(f"NIIMBOT did not acknowledge 0x{command:02x}")
                        return payload
        return await asyncio.wait_for(receive(), self.timeout)

    async def initialize(self):
        # Retrying connection is safe: it cannot print a label.
        for attempt in range(3):
            try:
                await self.request(0xC1, prefix=b"\x03", ack=True)
                break
            except TimeoutError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.3)
        await self.request(0xA5, response=0xB5)
        model = await self.request(0x40, b"\x08", response=0x48)
        model_id = int.from_bytes(model, "big") << (8 if len(model) == 1 else 0)
        if model_id != 0x1000:
            raise ValueError(f"Expected NIIMBOT B1 (4096), device reports {model_id}")
        for sub in (0x0B, 0x0D, 0x0A, 0x07, 0x03, 0x0C, 0x09):
            await self.request(0x40, bytes((sub,)), response=0x40 + sub)
        await self.request(0xDC, b"\x04", response=0xD9)

    async def print_pages(self, pages: list[Page], copies: int, *, density=3, label_type=1):
        if not pages or not 1 <= copies <= 999 or len(pages) * copies > 65535:
            raise ValueError("Invalid page count")
        if not 1 <= density <= 5 or label_type not in (1, 2, 3):
            raise ValueError("Invalid B1 density or label type")
        await self.initialize()
        await self.request(0x21, bytes((density,)), response=0x31, ack=True)
        await self.request(0x23, bytes((label_type,)), response=0x33, ack=True)
        self.print_started = True  # Set before writing: even a failed write may be partial.
        await self.request(0x01, struct.pack(">H", len(pages) * copies) + bytes(5), ack=True)
        completed = 0
        for _ in range(copies):
            for page in pages:
                await self.request(0x03, ack=True)
                await self.request(0x13, struct.pack(">HHH", page.height, page.width, 1), ack=True)
                for packet in rows(page):
                    await self.write(packet)
                    await asyncio.sleep(0.01)
                await self.request(0xE3, ack=True)
                completed += 1

                async def wait_for_page():
                    while True:
                        status = await self.request(0xA3, response=0xB3)
                        if len(status) < 4:
                            raise ValueError("Truncated NIIMBOT print status")
                        # The completed-page counter is the documented evidence.
                        # Intermediate pages can stop at the head awaiting the next
                        # page; requiring feed=100 here can deadlock multi-page jobs.
                        if int.from_bytes(status[:2], "big") >= completed:
                            return
                        await asyncio.sleep(0.3)
                await asyncio.wait_for(wait_for_page(), self.completion_timeout)
        # Never end a job early: doing so can cut off the label.
        await self.request(0xF3, ack=True)
