"""Minimal protobuf (proto2) wire format encoder and decoder.

The grid control messages are small and flat, so a full protobuf runtime is
not needed. Field numbers follow OpenSDG's control_protocol.proto.
"""

from __future__ import annotations

from typing import Any

VARINT = 0
FIXED64 = 1
LENGTH = 2
FIXED32 = 5


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def encode(fields: list[tuple[int, int, Any]]) -> bytes:
    """Encode (field_number, wire_type, value) triples."""
    out = bytearray()
    for number, wire_type, value in fields:
        out += _varint((number << 3) | wire_type)
        if wire_type == VARINT:
            out += _varint(value)
        elif wire_type == FIXED32:
            out += value.to_bytes(4, "little")
        elif wire_type == LENGTH:
            if isinstance(value, str):
                value = value.encode()
            out += _varint(len(value)) + value
        else:
            raise ValueError(f"Unsupported wire type {wire_type}")
    return bytes(out)


def decode(data: bytes) -> dict[int, Any]:
    """Decode a message into {field_number: value}; repeated fields keep the last."""
    fields: dict[int, Any] = {}
    pos = 0

    def read_varint() -> int:
        nonlocal pos
        result = shift = 0
        while True:
            if pos >= len(data):
                raise ValueError("Truncated varint")
            byte = data[pos]
            pos += 1
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result
            shift += 7

    while pos < len(data):
        key = read_varint()
        number, wire_type = key >> 3, key & 7
        if wire_type == VARINT:
            fields[number] = read_varint()
        elif wire_type == FIXED32:
            fields[number] = int.from_bytes(data[pos : pos + 4], "little")
            pos += 4
        elif wire_type == FIXED64:
            fields[number] = int.from_bytes(data[pos : pos + 8], "little")
            pos += 8
        elif wire_type == LENGTH:
            length = read_varint()
            if pos + length > len(data):
                raise ValueError("Truncated field")
            fields[number] = data[pos : pos + length]
            pos += length
        else:
            raise ValueError(f"Unsupported wire type {wire_type}")
    return fields
