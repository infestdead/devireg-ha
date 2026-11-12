"""Async Python client for the SecureDeviceGrid (SDG) protocol.

A port of the client side of OpenSDG by Pavel Fedin (Sonic-Amiga):
https://github.com/Sonic-Amiga/opensdg (GPL-3.0). This code is licensed under
GPL-3.0. SecureDeviceGrid is proprietary technology of Trifork; this project is
not affiliated with or endorsed by Danfoss or Trifork.
"""

from .errors import (
    ConnectionClosed,
    ConnectionRefused,
    PairingFailed,
    PeerTimeout,
    ProtocolError,
    SDGError,
)
from .grid import DANFOSS_SERVERS, Grid, generate_private_key, public_key
from .tunnel import Tunnel

__all__ = [
    "DANFOSS_SERVERS",
    "ConnectionClosed",
    "ConnectionRefused",
    "Grid",
    "PairingFailed",
    "PeerTimeout",
    "ProtocolError",
    "SDGError",
    "Tunnel",
    "generate_private_key",
    "public_key",
]
