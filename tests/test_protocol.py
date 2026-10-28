"""Tests for the SDG and dominion protocol layers."""

from __future__ import annotations

import asyncio
import os

from nacl.bindings import crypto_secretbox

from custom_components.devireg import dominion
from custom_components.devireg.api import DeviRegHouse, Room
from custom_components.devireg.dominion import Code, ControlState
from custom_components.devireg.sdg import generate_private_key, proto
from custom_components.devireg.sdg.crypto import xsalsa20_xor

from .fake_sdg import FakeGrid, FakeThermostat


def test_xsalsa20_matches_libsodium() -> None:
    # secretbox = Poly1305 tag + (message XOR keystream[32:]), so prefixing
    # 32 zero bytes exposes keystream bytes 32..63 from libsodium.
    key, nonce = os.urandom(32), os.urandom(24)
    expected = crypto_secretbox(bytes(64), nonce, key)[16:]
    ours = xsalsa20_xor(bytes(96), nonce, key)[32:]
    assert ours == expected


def test_proto_roundtrip() -> None:
    data = proto.encode(
        [
            (1, proto.FIXED32, 0xF09D8C95),
            (2, proto.VARINT, 300),
            (4, proto.LENGTH, b"\x00\x01"),
            (5, proto.LENGTH, "Mdg-NaCl/binary"),
        ]
    )
    assert proto.decode(data) == {1: 0xF09D8C95, 2: 300, 4: b"\x00\x01", 5: b"Mdg-NaCl/binary"}


def _packet(code: int, payload: bytes) -> bytes:
    # Incoming packets have no prefix byte
    msg_class = dominion.CODE_INFO.get(code, (dominion.MsgClass.DOMINION_SCHEDULER,))[0]
    return bytes([msg_class]) + code.to_bytes(2, "little") + bytes([len(payload)]) + payload


def test_dominion_parsing() -> None:
    data = (
        _packet(Code.HEATING_TEMPERATURE_ROOM, (2150).to_bytes(2, "little"))
        + _packet(Code.SYSTEM_HEATING_INFO, b"\x01")
        + _packet(Code.SYSTEM_ROOM_NAME, b"\x07Kitchen" + bytes(25))
    )
    packets = list(dominion.iter_packets(data + b"\x06\x00"))  # truncated tail dropped
    assert [code for _, code, _ in packets] == [
        Code.HEATING_TEMPERATURE_ROOM,
        Code.SYSTEM_HEATING_INFO,
        Code.SYSTEM_ROOM_NAME,
    ]
    assert dominion.decode_value(dominion.DECIMAL, packets[0][2]) == 21.5
    assert dominion.decode_value(dominion.STRING, packets[2][2]) == "Kitchen"


def test_dominion_requests() -> None:
    assert dominion.read_request(Code.HEATING_TEMPERATURE_FLOOR) == bytes([1, 6, 0x72, 0x72, 0])
    assert dominion.write_decimal(Code.SCHEDULER_SETPOINT_MANUAL, 21.5) == bytes(
        [0, 7, 0x94, 0x72, 2]
    ) + (2150).to_bytes(2, "little")


async def test_house_end_to_end(socket_enabled) -> None:
    initial = (
        _packet(Code.HEATING_TEMPERATURE_ROOM, (2150).to_bytes(2, "little"))
        + _packet(Code.HEATING_TEMPERATURE_FLOOR, (2300).to_bytes(2, "little"))
        + _packet(Code.SCHEDULER_CONTROL_INFO, bytes([ControlState.AT_HOME]))
        + _packet(Code.SCHEDULER_SETPOINT_COMFORT, (2200).to_bytes(2, "little"))
        + _packet(Code.SYSTEM_HEATING_INFO, b"\x01")
        # Real thermostats also report codes we only write (seen on hardware)
        + _packet(Code.SCHEDULER_AWAY, bytes(14))
        + _packet(0x1234, b"\x00")
    )
    thermostat = FakeThermostat(initial)
    grid = FakeGrid(thermostat)
    servers = await grid.start()

    house = DeviRegHouse(
        generate_private_key().hex(), [Room(thermostat.peer_id, "Bathroom")], servers
    )
    updated = asyncio.Event()
    house.add_listener(lambda t: updated.set() if t.values else None)
    try:
        await house.start()
        await asyncio.wait_for(updated.wait(), 5)

        t = house.thermostats[thermostat.peer_id]
        assert t.connected
        assert t.get(Code.HEATING_TEMPERATURE_ROOM) == 21.5
        assert t.get(Code.HEATING_TEMPERATURE_FLOOR) == 23.0
        assert t.mode == "schedule"
        assert t.target_temperature == 22.0
        assert grid.calls[0][3] == b"dominion-1.0"
        assert grid.pings >= 1

        await t.set_target_temperature(24)
        await asyncio.wait_for(thermostat.got_data.wait(), 5)
        assert thermostat.received[0] == dominion.write_decimal(
            Code.SCHEDULER_SETPOINT_TEMPORARY, 24
        ) + dominion.write_byte(Code.SCHEDULER_CONTROL_MODE, 6)
    finally:
        await house.stop()
        await grid.stop()
