"""SDG encrypted tunnel: framing plus the CurveCP-style handshake.

Every frame on the wire is a 2-byte big-endian length followed by content.
Encrypted packets start with a magic value and a 4-byte command; the
unencrypted forwarding messages used to open a peer tunnel start with a
one-byte message type followed by protobuf.
"""

from __future__ import annotations

import asyncio
import logging
import os

from nacl.bindings import (
    crypto_box,
    crypto_box_afternm,
    crypto_box_beforenm,
    crypto_box_keypair,
    crypto_box_open,
    crypto_box_open_afternm,
)
from nacl.exceptions import CryptoError

from . import proto
from .errors import PeerTimeout, ProtocolError, SDGError

_LOGGER = logging.getLogger(__name__)

PACKET_MAGIC = b"\xf0\x9f\x90\x9f"

CMD_TELL = b"TELL"
CMD_WELC = b"WELC"
CMD_HELO = b"HELO"
CMD_COOK = b"COOK"
CMD_VOCH = b"VOCH"
CMD_REDY = b"REDY"
CMD_MESG = b"MESG"

# Unencrypted forwarding messages
MSG_FORWARD_REMOTE = 0
MSG_FORWARD_HOLD = 1
MSG_FORWARD_REPLY = 2
MSG_FORWARD_ERROR = 3

FORWARD_REMOTE_MAGIC = 0xF09D8C95
FORWARD_REMOTE_SIGNATURE = "Mdg-NaCl/binary"
FORWARD_SERVER_ERROR = 1
FORWARD_PEER_TIMEOUT = 4

PROTOCOL_VERSION_MAJOR = 1
PROTOCOL_VERSION_MINOR = 0

# Empty license key appended to VOCH when talking to the grid itself,
# replicating the original library: length-prefixed "certificate\0" + 128 zeros.
_GRID_CERTIFICATE = b"\x01" + bytes([11]) + b"certificate\x00" + bytes([128]) + bytes(128)

DEFAULT_TIMEOUT = 15


class Tunnel:
    """One encrypted connection, either to the grid or to a peer via a relay."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        public_key: bytes,
        secret_key: bytes,
        *,
        grid: bool,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._pk = public_key
        self._sk = secret_key
        self._grid = grid
        self._nonce = 0
        self._key: bytes | None = None
        self.remote_key: bytes = bytes(32)
        self.session_key: bytes = bytes(32)

    @classmethod
    async def open(
        cls,
        host: str,
        port: int,
        public_key: bytes,
        secret_key: bytes,
        *,
        grid: bool,
        tunnel_id: bytes | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Tunnel:
        """Connect, optionally request forwarding, and run the handshake."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout
        )
        tunnel = cls(reader, writer, public_key, secret_key, grid=grid)
        try:
            async with asyncio.timeout(timeout):
                if tunnel_id is not None:
                    await tunnel._forward(tunnel_id)
                await tunnel._handshake()
        except BaseException:
            tunnel.close()
            raise
        return tunnel

    # Framing

    async def _read_frame(self) -> bytes:
        header = await self._reader.readexactly(2)
        return await self._reader.readexactly(int.from_bytes(header, "big"))

    def _write_frame(self, content: bytes) -> None:
        self._writer.write(len(content).to_bytes(2, "big") + content)

    def _write_packet(self, command: bytes, payload: bytes) -> None:
        self._write_frame(PACKET_MAGIC + command + payload)

    async def _read_packet(self) -> tuple[bytes, bytes]:
        frame = await self._read_frame()
        if len(frame) < 8 or frame[:4] != PACKET_MAGIC:
            raise ProtocolError(f"Invalid packet: {frame[:16].hex()}")
        return frame[4:8], frame[8:]

    async def _expect(self, command: bytes) -> bytes:
        received, payload = await self._read_packet()
        if received != command:
            raise ProtocolError(f"Expected {command!r}, got {received!r}")
        return payload

    def _next_nonce(self, prefix: bytes) -> bytes:
        nonce = prefix + self._nonce.to_bytes(8, "big")
        self._nonce += 1
        return nonce

    # Connection setup

    async def _forward(self, tunnel_id: bytes) -> None:
        """Ask the relay to connect us to the peer, sent before encryption starts."""
        request = proto.encode(
            [
                (1, proto.FIXED32, FORWARD_REMOTE_MAGIC),
                (2, proto.VARINT, PROTOCOL_VERSION_MAJOR),
                (3, proto.VARINT, PROTOCOL_VERSION_MINOR),
                (4, proto.LENGTH, tunnel_id),
                (5, proto.LENGTH, FORWARD_REMOTE_SIGNATURE),
            ]
        )
        self._write_frame(bytes([MSG_FORWARD_REMOTE]) + request)
        await self._writer.drain()

        while True:
            frame = await self._read_frame()
            if not frame:
                continue
            msg_type, body = frame[0], frame[1:]
            if msg_type == MSG_FORWARD_HOLD:
                # Sometimes sent before the reply; meaning unknown, ignored.
                continue
            if msg_type == MSG_FORWARD_REPLY:
                signature = proto.decode(body).get(1, b"").decode()
                if signature != FORWARD_REMOTE_SIGNATURE:
                    raise ProtocolError(f"Wrong forwarding signature {signature}")
                return
            if msg_type == MSG_FORWARD_ERROR:
                code = proto.decode(body).get(1)
                if code == FORWARD_PEER_TIMEOUT:
                    raise PeerTimeout("Peer did not answer (offline or too many connections)")
                raise SDGError(f"Forwarding failed with code {code}")
            raise ProtocolError(f"Unexpected forwarding message {msg_type}")

    async def _handshake(self) -> None:
        self._write_packet(CMD_TELL, b"")
        await self._writer.drain()

        welc = await self._expect(CMD_WELC)
        self.remote_key = welc[:32]
        temp_pk, temp_sk = crypto_box_keypair()

        nonce = self._next_nonce(b"CurveCP-client-H")
        hello = crypto_box(bytes(64), nonce, self.remote_key, temp_sk)
        self._write_packet(CMD_HELO, temp_pk + nonce[16:] + hello)
        await self._writer.drain()

        cook = await self._expect(CMD_COOK)
        try:
            plain = crypto_box_open(
                cook[16:], b"CurveCPK" + cook[:16], self.remote_key, temp_sk
            )
        except CryptoError as err:
            raise ProtocolError("Cannot decrypt COOK") from err
        server_short_pk, cookie = plain[:32], plain[32:128]
        self._key = crypto_box_beforenm(server_short_pk, temp_sk)
        self.session_key = self._key

        vouch_nonce = b"CurveCPV" + os.urandom(16)
        inner = crypto_box(temp_pk, vouch_nonce, self.remote_key, self._sk)
        outer = self._pk + vouch_nonce[8:] + inner
        outer += _GRID_CERTIFICATE if self._grid else b"\x00"
        nonce = self._next_nonce(b"CurveCP-client-I")
        box = crypto_box_afternm(outer, nonce, self._key)
        self._write_packet(CMD_VOCH, cookie + nonce[16:] + box)
        await self._writer.drain()

        redy = await self._expect(CMD_REDY)
        # The payload carries the peer's license certificate, which we ignore.
        self._decrypt(redy, b"CurveCP-server-R")

    def _decrypt(self, payload: bytes, prefix: bytes) -> bytes:
        assert self._key is not None
        try:
            return crypto_box_open_afternm(payload[8:], prefix + payload[:8], self._key)
        except CryptoError as err:
            raise ProtocolError("Decryption failed") from err

    # Data

    async def send(self, data: bytes) -> None:
        """Send one encrypted message."""
        assert self._key is not None
        nonce = self._next_nonce(b"CurveCP-client-M")
        plain = len(data).to_bytes(2, "big") + data
        box = crypto_box_afternm(plain, nonce, self._key)
        self._write_packet(CMD_MESG, nonce[16:] + box)
        await self._writer.drain()

    async def recv(self) -> bytes:
        """Receive the next encrypted message."""
        while True:
            command, payload = await self._read_packet()
            if command == CMD_MESG:
                plain = self._decrypt(payload, b"CurveCP-server-M")
                size = int.from_bytes(plain[:2], "big")
                return plain[2 : 2 + size]
            _LOGGER.debug("Ignoring unexpected packet %r", command)

    def close(self) -> None:
        self._writer.close()

    @property
    def closed(self) -> bool:
        return self._writer.is_closing()
