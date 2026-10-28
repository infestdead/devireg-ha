"""Exceptions raised by the SDG client."""


class SDGError(Exception):
    """Base class for SDG errors."""


class ProtocolError(SDGError):
    """The remote side sent something we did not expect."""


class ConnectionRefused(SDGError):
    """The grid refused to connect us to the requested peer."""


class PeerTimeout(SDGError):
    """The grid could not reach the peer (offline, or too many connections)."""


class PairingFailed(SDGError):
    """Pairing challenge-response verification failed."""
