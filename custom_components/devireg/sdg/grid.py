"""Grid connection: the control channel used to reach peers and to pair."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from hashlib import sha512
import json
import logging
import os
import random
import time
from typing import Any

from nacl.bindings import crypto_scalarmult, crypto_scalarmult_base

from . import proto
from .crypto import xsalsa20_xor
from .errors import ConnectionRefused, PairingFailed, ProtocolError, SDGError
from .tunnel import DEFAULT_TIMEOUT, PROTOCOL_VERSION_MAJOR, PROTOCOL_VERSION_MINOR, Tunnel

_LOGGER = logging.getLogger(__name__)

DANFOSS_SERVERS: list[tuple[str, int]] = [
    ("77.66.11.90", 443),
    ("77.66.11.92", 443),
    ("5.179.92.180", 443),
    ("5.179.92.182", 443),
]

MSG_PROTOCOL_VERSION = 1
MSG_PING = 4
MSG_PONG = 5
MSG_CALL_REMOTE = 10
MSG_REMOTE_REPLY = 11
MSG_INCOMING_CALL = 12
MSG_INCOMING_CALL_REPLY = 13
MSG_PAIR_REMOTE = 32
MSG_PAIR_REMOTE_REPLY = 33

MSG_PAIRING_CHALLENGE = 3
MSG_PAIRING_RESPONSE = 4
MSG_PAIRING_RESULT = 5

PROTOCOL_VERSION_MAGIC = 0xF09D8CA8
PING_INTERVAL = 30
MIN_OTP_LENGTH = 7

PROTOCOL_DOMINION = "dominion-1.0"
PROTOCOL_CONFIGURATION = "dominion-configuration-1.0"


def generate_private_key() -> bytes:
    """Create a new long-term Curve25519 secret key."""
    return os.urandom(32)


def public_key(private_key: bytes) -> bytes:
    """Our peer ID is the public key matching the private key."""
    return crypto_scalarmult_base(private_key)


def pairing_response(
    otp: str, my_key: bytes, peer_key: bytes, session_key: bytes, challenge: bytes
) -> tuple[bytes, bytes]:
    """Answer MSG_PAIRING_CHALLENGE; returns (response, expected result)."""
    if len(challenge) < 97:
        raise ProtocolError("Short pairing challenge")
    x, nonce, y = challenge[1:33], challenge[33:65], challenge[65:97]

    digest = sha512(otp.encode() + my_key + peer_key).digest()
    key = sha512(digest + nonce).digest()
    unmasked = xsalsa20_xor(y, nonce[:24], key[:32])
    p1 = crypto_scalarmult(unmasked, crypto_scalarmult_base(session_key))

    rnd = os.urandom(32)
    response_x = crypto_scalarmult(rnd, p1)
    shared = crypto_scalarmult(rnd, x)
    response_y = sha512(sha512(x).digest() + shared).digest()[:32]
    expected = sha512(sha512(response_x).digest() + shared).digest()[:32]
    return bytes([MSG_PAIRING_RESPONSE]) + response_x + response_y, expected


class Grid:
    """Connection to the Danfoss SecureDeviceGrid."""

    def __init__(
        self,
        private_key: bytes,
        servers: list[tuple[str, int]] | None = None,
        on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        self._sk = private_key
        self._pk = public_key(private_key)
        self._servers = servers or DANFOSS_SERVERS
        self._on_disconnect = on_disconnect
        self._tunnel: Tunnel | None = None
        self._tasks: list[asyncio.Task] = []
        self._requests: dict[int, asyncio.Future[dict[int, Any]]] = {}
        self._request_id = 0
        self._ping_seq = 0
        self._ping_delay: int | None = None
        self._last_ping = 0.0
        self._connected: asyncio.Future[None] | None = None

    @property
    def peer_id(self) -> bytes:
        return self._pk

    @property
    def connected(self) -> bool:
        return self._tunnel is not None and not self._tunnel.closed

    async def connect(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Connect to one of the grid servers, trying them in random order."""
        servers = list(self._servers)
        random.shuffle(servers)
        last_error: Exception | None = None
        for host, port in servers:
            try:
                self._tunnel = await Tunnel.open(
                    host, port, self._pk, self._sk, grid=True, timeout=timeout
                )
                break
            except (OSError, TimeoutError, SDGError) as err:
                _LOGGER.debug("Grid server %s:%s failed: %s", host, port, err)
                last_error = err
        else:
            raise SDGError(f"No grid server reachable: {last_error}")

        loop = asyncio.get_running_loop()
        self._connected = loop.create_future()
        self._tasks = [loop.create_task(self._reader())]
        version = proto.encode(
            [
                (1, proto.FIXED32, PROTOCOL_VERSION_MAGIC),
                (2, proto.VARINT, PROTOCOL_VERSION_MAJOR),
                (3, proto.VARINT, PROTOCOL_VERSION_MINOR),
            ]
        )
        try:
            await self._send(MSG_PROTOCOL_VERSION, version)
            # Connected once the first PING (sent after version exchange) is answered
            await asyncio.wait_for(asyncio.shield(self._connected), timeout)
        except BaseException:
            await self.close()
            raise
        self._tasks.append(loop.create_task(self._pinger()))

    async def close(self) -> None:
        for task in self._tasks:
            if task is not asyncio.current_task():
                task.cancel()
        self._tasks = []
        if self._tunnel:
            self._tunnel.close()
            self._tunnel = None
        for future in self._requests.values():
            if not future.done():
                future.set_exception(SDGError("Grid connection closed"))
        self._requests.clear()

    async def _send(self, msg_type: int, body: bytes) -> None:
        if not self._tunnel:
            raise SDGError("Grid is not connected")
        await self._tunnel.send(bytes([msg_type]) + body)

    async def _ping(self) -> None:
        fields = [(1, proto.VARINT, self._ping_seq)]
        if self._ping_delay is not None:
            fields.append((2, proto.VARINT, self._ping_delay))
        self._ping_seq += 1
        self._last_ping = time.monotonic()
        await self._send(MSG_PING, proto.encode(fields))

    async def _pinger(self) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await self._ping()

    async def _reader(self) -> None:
        assert self._tunnel
        try:
            while True:
                await self._handle(await self._tunnel.recv())
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Grid connection lost: %s", err)
            if self._connected and not self._connected.done():
                self._connected.set_exception(SDGError(f"Grid handshake failed: {err}"))
            await self.close()
            if self._on_disconnect:
                self._on_disconnect()

    async def _handle(self, data: bytes) -> None:
        if not data:
            return
        msg_type, body = data[0], data[1:]
        if msg_type == MSG_PROTOCOL_VERSION:
            fields = proto.decode(body)
            if fields.get(1) != PROTOCOL_VERSION_MAGIC or (
                fields.get(2),
                fields.get(3),
            ) != (PROTOCOL_VERSION_MAJOR, PROTOCOL_VERSION_MINOR):
                raise ProtocolError(f"Unsupported grid protocol {fields}")
            await self._ping()
        elif msg_type == MSG_PONG:
            if proto.decode(body).get(1) == self._ping_seq - 1:
                self._ping_delay = int((time.monotonic() - self._last_ping) * 1000)
            if self._connected and not self._connected.done():
                self._connected.set_result(None)
        elif msg_type in (MSG_REMOTE_REPLY, MSG_PAIR_REMOTE_REPLY):
            fields = proto.decode(body)
            future = self._requests.pop(fields.get(1, -1), None)
            if future and not future.done():
                future.set_result(fields)
        elif msg_type == MSG_INCOMING_CALL:
            # We are a client only, so reject incoming calls.
            call_id = proto.decode(body).get(1, 0)
            reply = proto.encode([(1, proto.VARINT, call_id), (2, proto.VARINT, 0)])
            await self._send(MSG_INCOMING_CALL_REPLY, reply)
        else:
            _LOGGER.debug("Unhandled grid message %s: %s", msg_type, body.hex())

    async def _request(
        self, msg_type: int, fields: list[tuple[int, int, Any]], timeout: float
    ) -> tuple[str, int, bytes]:
        """Send a call/pair request; return the relay (host, port, tunnel id)."""
        request_id = self._request_id
        self._request_id += 1
        future = asyncio.get_running_loop().create_future()
        self._requests[request_id] = future
        await self._send(
            msg_type, proto.encode([(1, proto.VARINT, request_id), *fields])
        )
        try:
            reply = await asyncio.wait_for(future, timeout)
        finally:
            self._requests.pop(request_id, None)

        if reply.get(2, 0) != 0 or 3 not in reply:
            raise ConnectionRefused(f"Grid refused the connection (code {reply.get(2)})")
        peer = proto.decode(reply[3])
        server = proto.decode(peer[4])
        return server[1].decode(), server[2], peer[5]

    async def connect_to_peer(
        self, peer_id: bytes, protocol: str, timeout: float = DEFAULT_TIMEOUT
    ) -> Tunnel:
        """Open a tunnel to a peer (thermostat or phone)."""
        host, port, tunnel_id = await self._request(
            MSG_CALL_REMOTE,
            [(2, proto.LENGTH, peer_id.hex()), (3, proto.LENGTH, protocol)],
            timeout,
        )
        return await Tunnel.open(
            host, port, self._pk, self._sk, grid=False, tunnel_id=tunnel_id, timeout=timeout
        )

    async def pair_remote(self, otp: str, timeout: float = 60) -> bytes:
        """Pair with the phone that generated the OTP; returns the phone's peer ID."""
        digits = "".join(c for c in otp if c.isdigit())
        if not MIN_OTP_LENGTH <= len(digits) < 32:
            raise ValueError("OTP has the wrong length")

        # Only part of the OTP goes to the server; the rest is proven in the
        # challenge-response below.
        host, port, tunnel_id = await self._request(
            MSG_PAIR_REMOTE, [(2, proto.LENGTH, digits[:-3])], DEFAULT_TIMEOUT
        )
        tunnel = await Tunnel.open(
            host, port, self._pk, self._sk, grid=False, tunnel_id=tunnel_id
        )
        try:
            async with asyncio.timeout(timeout):
                expected: bytes | None = None
                while True:
                    data = await tunnel.recv()
                    if not data:
                        continue
                    if data[0] == MSG_PAIRING_CHALLENGE:
                        response, expected = pairing_response(
                            digits, self._pk, tunnel.remote_key, tunnel.session_key, data
                        )
                        await tunnel.send(response)
                    elif data[0] == MSG_PAIRING_RESULT:
                        if expected is None or data[1:33] != expected:
                            raise PairingFailed("Pairing verification failed")
                        return tunnel.remote_key
        finally:
            tunnel.close()

    async def fetch_house_config(
        self, phone_id: bytes, user_name: str, timeout: float = 60
    ) -> dict[str, Any]:
        """Ask the paired phone to share its house configuration."""
        tunnel = await self.connect_to_peer(phone_id, PROTOCOL_CONFIGURATION)
        try:
            async with asyncio.timeout(timeout):
                request = {
                    "phoneName": user_name,
                    "phonePublicKey": self._pk.hex(),
                    "chunkedMessage": True,
                }
                await tunnel.send(json.dumps(request).encode())

                data = await tunnel.recv()
                total = len(data)
                # Chunked mode: first packet starts with int 0 and the total
                # length (little-endian), so it cannot be mistaken for JSON.
                if len(data) > 8 and data[:4] == bytes(4):
                    total = int.from_bytes(data[4:8], "little")
                    data = data[8:]
                while len(data) < total:
                    data += await tunnel.recv()
                return json.loads(data[:total].decode())
        finally:
            tunnel.close()

