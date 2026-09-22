import asyncio

import pytest

from niimbot_service.protocol import B1Protocol, FrameDecoder, Page, frame, rows


class Printer:
    """Deterministic device peer with unsolicited and fragmented responses."""
    def __init__(self, *, model=b"\x10\x00", drop=None, reject=None, complete=True):
        self.model, self.drop, self.reject, self.complete = model, drop, reject, complete
        self.commands = []
        self.responses = asyncio.Queue()
        self.pages = 0

    async def write(self, raw):
        command, data = FrameDecoder().feed(raw)[0]
        self.commands.append((command, data))
        if command in (0x84, 0x85) or command == self.drop:
            return
        opcode = {0xA5: 0xB5, 0x21: 0x31, 0x23: 0x33, 0xDC: 0xD9, 0xA3: 0xB3}.get(command, command + 1)
        result = b"\x01"
        if command == 0x40:
            opcode = 0x40 + data[0]
            result = self.model if data == b"\x08" else b"\x01"
        if command == 0xE3:
            self.pages += 1
        if command == 0xA3:
            result = (self.pages if self.complete else 0).to_bytes(2, "big") + (b"\x64\x64" if self.complete else b"\x32\x32")
        if command == self.reject:
            result = b"\x00"
        response = frame(0xD3, b"\x00\x01\x00") + frame(opcode, result)
        for chunk in (response[:1], response[1:8], response[8:]):
            await self.responses.put(chunk)

    async def read(self):
        return await self.responses.get()


def test_known_wire_vectors_and_fragmentation():
    assert frame(0x21, b"\x03").hex() == "555521010323aaaa"
    assert frame(0xC1, b"\x01").hex() == "5555c10101c1aaaa"
    parser = FrameDecoder()
    assert parser.feed(b"noise\x55") == []
    assert parser.feed(bytes.fromhex("55c20101c2aaaa555531010131aaaa")) == [(0xC2, b"\x01"), (0x31, b"\x01")]


def test_bad_checksum_fails_closed():
    with pytest.raises(ValueError):
        FrameDecoder().feed(bytes.fromhex("555531010130aaaa"))


def test_rows_preserve_msb_polarity_odd_width_and_run_limits():
    assert list(rows(Page(9, 1, b"\x80\x80"))) == [frame(0x85, b"\x00\x00\x00\x02\x00\x01\x80\x80")]
    assert list(rows(Page(8, 201, bytes(201)))) == [frame(0x84, b"\x00\x00\xc8"), frame(0x84, b"\x00\xc8\x01")]
    payload = FrameDecoder().feed(next(rows(Page(384, 1, b"\xff" * 48))))[0][1]
    assert payload[:6] == b"\x00\x00\x00\x80\x01\x01"  # 384 black bits, LE total


@pytest.mark.parametrize("page", [(385, 1, b""), (0, 1, b""), (9, 1, b"\x00\x01"), (8, 2, b"\x00")])
def test_invalid_pages(page):
    with pytest.raises(ValueError):
        Page(*page)


def test_b1_handshake_collated_copies_and_completion_before_end():
    async def run():
        peer = Printer()
        await B1Protocol(peer).print_pages([Page(8, 1, b"\x80"), Page(8, 1, b"\x01")], 2)
        commands = peer.commands
        assert [c for c, _ in commands[:11]] == [0xC1, 0xA5] + [0x40] * 8 + [0xDC]
        assert (0x01, b"\x00\x04\x00\x00\x00\x00\x00") in commands
        assert [data[-1] for cmd, data in commands if cmd == 0x85] == [0x80, 0x01, 0x80, 0x01]
        assert [data for cmd, data in commands if cmd == 0x13] == [b"\x00\x01\x00\x08\x00\x01"] * 4
        assert commands[-2][0] == 0xA3 and commands[-1][0] == 0xF3
    asyncio.run(run())


@pytest.mark.parametrize("options", [{"model": b"\x10\x01"}, {"reject": 0x21}])
def test_wrong_model_or_rejected_setup_cannot_start_print(options):
    async def run():
        peer = Printer(**options)
        with pytest.raises((ValueError, RuntimeError)):
            await B1Protocol(peer).print_pages([Page(8, 1, b"\x80")], 1)
        assert 0x01 not in [cmd for cmd, _ in peer.commands]
    asyncio.run(run())


@pytest.mark.parametrize("options", [{"drop": 0xE3}, {"complete": False}])
def test_missing_confirmation_never_ends_early_or_reprints(options):
    async def run():
        peer = Printer(**options)
        protocol = B1Protocol(peer, timeout=.02, completion_timeout=.03)
        with pytest.raises(TimeoutError):
            await protocol.print_pages([Page(8, 1, b"\x80")], 1)
        commands = [cmd for cmd, _ in peer.commands]
        assert commands.count(0x01) == 1
        assert 0xF3 not in commands
        assert protocol.print_started
    asyncio.run(run())
