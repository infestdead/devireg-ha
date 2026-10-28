"""Crypto primitives used by SDG that PyNaCl does not expose.

Only XSalsa20 stream XOR (libsodium's crypto_stream_xor) is needed, for a
single 32-byte block during pairing, so a pure Python version is fine.
"""

from __future__ import annotations

import struct

_SIGMA = b"expand 32-byte k"
_MASK = 0xFFFFFFFF


def _rotl(value: int, shift: int) -> int:
    return ((value << shift) & _MASK) | (value >> (32 - shift))


def _rounds(x: list[int]) -> list[int]:
    x = list(x)
    for _ in range(10):
        # Column round
        x[4] ^= _rotl((x[0] + x[12]) & _MASK, 7)
        x[8] ^= _rotl((x[4] + x[0]) & _MASK, 9)
        x[12] ^= _rotl((x[8] + x[4]) & _MASK, 13)
        x[0] ^= _rotl((x[12] + x[8]) & _MASK, 18)
        x[9] ^= _rotl((x[5] + x[1]) & _MASK, 7)
        x[13] ^= _rotl((x[9] + x[5]) & _MASK, 9)
        x[1] ^= _rotl((x[13] + x[9]) & _MASK, 13)
        x[5] ^= _rotl((x[1] + x[13]) & _MASK, 18)
        x[14] ^= _rotl((x[10] + x[6]) & _MASK, 7)
        x[2] ^= _rotl((x[14] + x[10]) & _MASK, 9)
        x[6] ^= _rotl((x[2] + x[14]) & _MASK, 13)
        x[10] ^= _rotl((x[6] + x[2]) & _MASK, 18)
        x[3] ^= _rotl((x[15] + x[11]) & _MASK, 7)
        x[7] ^= _rotl((x[3] + x[15]) & _MASK, 9)
        x[11] ^= _rotl((x[7] + x[3]) & _MASK, 13)
        x[15] ^= _rotl((x[11] + x[7]) & _MASK, 18)
        # Row round
        x[1] ^= _rotl((x[0] + x[3]) & _MASK, 7)
        x[2] ^= _rotl((x[1] + x[0]) & _MASK, 9)
        x[3] ^= _rotl((x[2] + x[1]) & _MASK, 13)
        x[0] ^= _rotl((x[3] + x[2]) & _MASK, 18)
        x[6] ^= _rotl((x[5] + x[4]) & _MASK, 7)
        x[7] ^= _rotl((x[6] + x[5]) & _MASK, 9)
        x[4] ^= _rotl((x[7] + x[6]) & _MASK, 13)
        x[5] ^= _rotl((x[4] + x[7]) & _MASK, 18)
        x[11] ^= _rotl((x[10] + x[9]) & _MASK, 7)
        x[8] ^= _rotl((x[11] + x[10]) & _MASK, 9)
        x[9] ^= _rotl((x[8] + x[11]) & _MASK, 13)
        x[10] ^= _rotl((x[9] + x[8]) & _MASK, 18)
        x[12] ^= _rotl((x[15] + x[14]) & _MASK, 7)
        x[13] ^= _rotl((x[12] + x[15]) & _MASK, 9)
        x[14] ^= _rotl((x[13] + x[12]) & _MASK, 13)
        x[15] ^= _rotl((x[14] + x[13]) & _MASK, 18)
    return x


def _state(key: bytes, block16: bytes) -> list[int]:
    k = struct.unpack("<8I", key)
    n = struct.unpack("<4I", block16)
    c = struct.unpack("<4I", _SIGMA)
    return [c[0], *k[:4], c[1], *n, c[2], *k[4:], c[3]]


def _hsalsa20(key: bytes, nonce16: bytes) -> bytes:
    x = _rounds(_state(key, nonce16))
    return struct.pack("<8I", *(x[i] for i in (0, 5, 10, 15, 6, 7, 8, 9)))


def _salsa20_block(key: bytes, nonce8: bytes, counter: int) -> bytes:
    initial = _state(key, nonce8 + counter.to_bytes(8, "little"))
    x = _rounds(initial)
    return struct.pack("<16I", *((a + b) & _MASK for a, b in zip(x, initial, strict=True)))


def xsalsa20_xor(message: bytes, nonce: bytes, key: bytes) -> bytes:
    """Equivalent of libsodium crypto_stream_xor (XSalsa20)."""
    if len(nonce) != 24 or len(key) != 32:
        raise ValueError("XSalsa20 needs a 24-byte nonce and a 32-byte key")
    subkey = _hsalsa20(key, nonce[:16])
    stream = bytearray()
    counter = 0
    while len(stream) < len(message):
        stream += _salsa20_block(subkey, nonce[16:], counter)
        counter += 1
    return bytes(a ^ b for a, b in zip(message, stream, strict=False))
