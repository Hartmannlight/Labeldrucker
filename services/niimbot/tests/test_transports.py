import asyncio
from types import SimpleNamespace

import pytest

from niimbot_service.transports import BleTransport, SerialTransport


def test_ble_chunks_preserve_stream_and_notifications():
    async def run():
        characteristic = SimpleNamespace(max_write_without_response_size=20)
        writes = []
        async def write(_characteristic, data, response):
            assert not response
            writes.append(data)
        client = SimpleNamespace(services=SimpleNamespace(get_characteristic=lambda _: characteristic), write_gatt_char=write)
        transport = BleTransport(client)
        payload = bytes(range(55))
        await transport.write(payload)
        assert [len(chunk) for chunk in writes] == [20, 20, 15]
        assert b"".join(writes) == payload
        transport.notify(None, b"response")
        assert await transport.read() == b"response"
    asyncio.run(run())


def test_serial_partial_write_is_an_error():
    port = SimpleNamespace(write=lambda data: len(data) - 1)
    with pytest.raises(OSError, match="Incomplete"):
        asyncio.run(SerialTransport(port).write(b"a frame"))
