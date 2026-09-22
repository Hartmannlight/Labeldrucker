from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

CHARACTERISTIC = "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"


class SerialTransport:
    def __init__(self, port):
        self.port = port

    async def read(self):
        return await asyncio.to_thread(self.port.read, max(1, min(self.port.in_waiting, 4096)))

    async def write(self, data):
        count = await asyncio.to_thread(self.port.write, data)
        if count != len(data):
            raise OSError("Incomplete NIIMBOT serial write")


class BleTransport:
    def __init__(self, client):
        self.client = client
        self.received = asyncio.Queue(maxsize=1024)
        self.overflow = False

    def notify(self, _sender, data):
        try:
            self.received.put_nowait(bytes(data))
        except asyncio.QueueFull:
            self.overflow = True

    async def read(self):
        if self.overflow:
            raise OSError("NIIMBOT notification buffer overflow")
        return await self.received.get()

    async def write(self, data):
        characteristic = self.client.services.get_characteristic(CHARACTERISTIC)
        size = characteristic.max_write_without_response_size
        for offset in range(0, len(data), size):
            await self.client.write_gatt_char(characteristic, data[offset:offset + size], response=False)
            await asyncio.sleep(0.01)


@asynccontextmanager
async def connect(kind: str, address: str):
    if kind == "serial":
        import serial
        port = await asyncio.to_thread(serial.Serial, address, baudrate=115200, timeout=0.2, write_timeout=5)
        try:
            yield SerialTransport(port)
        finally:
            await asyncio.to_thread(port.close)
    elif kind == "ble":
        from bleak import BleakClient
        async with BleakClient(address, timeout=20) as client:
            transport = BleTransport(client)
            await client.start_notify(CHARACTERISTIC, transport.notify)
            await asyncio.sleep(0.5)
            yield transport
    else:
        raise ValueError("NIIMBOT_TRANSPORT must be serial or ble")
