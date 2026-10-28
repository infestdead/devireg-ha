"""In-process fake of the SDG grid and a DEVIreg thermostat, for tests.

Implements the server side of the handshake so the client is exercised
end to end over real sockets. It mirrors our reading of OpenSDG; it cannot
prove compatibility with Danfoss's servers.
"""

from __future__ import annotations

import asyncio
import os

from nacl.bindings import (
    crypto_box,
    crypto_box_afternm,
    crypto_box_beforenm,
    crypto_box_keypair,
    crypto_box_open,
    crypto_box_open_afternm,
)

from custom_components.devireg.sdg import proto
from custom_components.devireg.sdg.tunnel import PACKET_MAGIC


class ServerTunnel:
    """Server side of one SDG connection."""

    def __init__(self, reader, writer, keypair):
        self.reader, self.writer = reader, writer
        self.pk, self.sk = keypair
        self.nonce = 0
        self.key = None
        self.client_pk = None
        self.had_certificate = None

    async def frame(self) -> bytes:
        size = int.from_bytes(await self.reader.readexactly(2), "big")
        return await self.reader.readexactly(size)

    def write_frame(self, content: bytes) -> None:
        self.writer.write(len(content).to_bytes(2, "big") + content)

    def write_packet(self, cmd: bytes, payload: bytes) -> None:
        self.write_frame(PACKET_MAGIC + cmd + payload)

    async def packet(self, expect: bytes) -> bytes:
        frame = await self.frame()
        assert frame[:4] == PACKET_MAGIC, frame
        assert frame[4:8] == expect, (frame[4:8], expect)
        return frame[8:]

    def next_nonce(self, prefix: bytes) -> bytes:
        self.nonce += 1
        return prefix + self.nonce.to_bytes(8, "big")

    async def handshake(self) -> None:
        await self.packet(b"TELL")
        self.write_packet(b"WELC", self.pk)

        helo = await self.packet(b"HELO")
        temp_pk, n, box = helo[:32], helo[32:40], helo[40:]
        assert crypto_box_open(box, b"CurveCP-client-H" + n, temp_pk, self.sk) == bytes(64)

        short_pk, short_sk = crypto_box_keypair()
        cookie = os.urandom(96)
        n16 = os.urandom(16)
        self.write_packet(b"COOK", n16 + crypto_box(short_pk + cookie, b"CurveCPK" + n16, temp_pk, self.sk))

        voch = await self.packet(b"VOCH")
        assert voch[:96] == cookie
        self.key = crypto_box_beforenm(temp_pk, short_sk)
        outer = crypto_box_open_afternm(voch[104:], b"CurveCP-client-I" + voch[96:104], self.key)
        self.client_pk = outer[:32]
        inner = crypto_box_open(outer[96 - 48 : 96], b"CurveCPV" + outer[32:48], self.client_pk, self.sk)
        assert inner == temp_pk
        self.had_certificate = outer[96] == 1

        n = self.next_nonce(b"CurveCP-server-R")
        self.write_packet(b"REDY", n[16:] + crypto_box_afternm(b"\x00", n, self.key))
        await self.writer.drain()

    async def send(self, data: bytes) -> None:
        n = self.next_nonce(b"CurveCP-server-M")
        plain = len(data).to_bytes(2, "big") + data
        self.write_packet(b"MESG", n[16:] + crypto_box_afternm(plain, n, self.key))
        await self.writer.drain()

    async def recv(self) -> bytes:
        payload = await self.packet(b"MESG")
        plain = crypto_box_open_afternm(payload[8:], b"CurveCP-client-M" + payload[:8], self.key)
        return plain[2 : 2 + int.from_bytes(plain[:2], "big")]


class FakeThermostat:
    """Answers on the relay port as a DEVIreg Smart thermostat."""

    def __init__(self, initial: bytes):
        self.keypair = crypto_box_keypair()
        self.initial = initial
        self.received: list[bytes] = []
        self.got_data = asyncio.Event()

    @property
    def peer_id(self) -> str:
        return self.keypair[0].hex()

    async def handle(self, reader, writer) -> None:
        tunnel = ServerTunnel(reader, writer, self.keypair)
        frame = await tunnel.frame()
        assert frame[0] == 0  # MSG_FORWARD_REMOTE
        fields = proto.decode(frame[1:])
        assert fields[5] == b"Mdg-NaCl/binary"
        tunnel.write_frame(b"\x01")  # FORWARD_HOLD, should be ignored
        tunnel.write_frame(b"\x02" + proto.encode([(1, proto.LENGTH, "Mdg-NaCl/binary")]))
        await tunnel.handshake()
        assert tunnel.had_certificate is False
        await tunnel.send(b"\x00" + self.initial)  # leading garbage byte quirk
        try:
            while True:
                self.received.append(await tunnel.recv())
                self.got_data.set()
        except asyncio.IncompleteReadError:
            pass


class FakeGrid:
    """A grid server that forwards CALL_REMOTE to one fake thermostat."""

    def __init__(self, thermostat: FakeThermostat):
        self.keypair = crypto_box_keypair()
        self.thermostat = thermostat
        self.calls: list[dict] = []
        self.pings = 0

    async def start(self) -> list[tuple[str, int]]:
        self._grid = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self._relay = await asyncio.start_server(self.thermostat.handle, "127.0.0.1", 0)
        self.relay_port = self._relay.sockets[0].getsockname()[1]
        return [("127.0.0.1", self._grid.sockets[0].getsockname()[1])]

    async def stop(self) -> None:
        self._grid.close()
        self._relay.close()

    async def handle(self, reader, writer) -> None:
        tunnel = ServerTunnel(reader, writer, self.keypair)
        await tunnel.handshake()
        assert tunnel.had_certificate is True
        try:
            while True:
                data = await tunnel.recv()
                msg_type, fields = data[0], proto.decode(data[1:])
                if msg_type == 1:  # PROTOCOL_VERSION
                    await tunnel.send(data)
                elif msg_type == 4:  # PING
                    self.pings += 1
                    await tunnel.send(b"\x05" + proto.encode([(1, proto.VARINT, fields[1])]))
                elif msg_type == 10:  # CALL_REMOTE
                    self.calls.append(fields)
                    server = proto.encode([(1, proto.LENGTH, "127.0.0.1"), (2, proto.VARINT, self.relay_port)])
                    peer = proto.encode([(3, proto.LENGTH, fields[2]), (4, proto.LENGTH, server), (5, proto.LENGTH, b"tunnel")])
                    reply = proto.encode([(1, proto.VARINT, fields[1]), (2, proto.VARINT, 0), (3, proto.LENGTH, peer)])
                    await tunnel.send(b"\x0b" + reply)
        except asyncio.IncompleteReadError:
            pass
