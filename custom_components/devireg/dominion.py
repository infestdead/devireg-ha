"""DEVIreg Smart application protocol ("dominion-1.0").

Messages are small typed values: 1 byte class, 2 bytes code (LE), 1 byte
length, payload. Outgoing messages carry an extra leading byte: 0 to write a
value, 1 to request it. Codes come from the openHAB DEVIreg binding.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import IntEnum
from typing import Any


class MsgClass(IntEnum):
    DEVICEGLOBAL = 0
    WIFI = 2
    MDG = 3
    DOMINION_SYSTEM = 5
    DOMINION_HEATING = 6
    DOMINION_SCHEDULER = 7
    DOMINION_LOGS = 8


class Code(IntEnum):
    GLOBAL_SOFTWAREBUILDREVISION = 8
    GLOBAL_SERIALNUMBER = 22
    GLOBAL_HARDWAREREVISION = 34
    GLOBAL_SOFTWAREREVISION = 35
    WIFI_CONNECTED_STRENGTH = 29804
    MDG_CONNECTED_TO_SERVER = 29825
    MDG_CONNECTION_COUNT = 30470
    SYSTEM_RUNTIME_INFO_RELAY_COUNT = 29232
    SYSTEM_RUNTIME_INFO_RELAY_ON_TIME = 29233
    SYSTEM_WIZARD_INFO = 29239
    SYSTEM_HEATING_INFO = 29240
    SYSTEM_ALARM_INFO = 29241
    SYSTEM_WINDOW_OPEN = 29242
    SYSTEM_INFO_FLOOR_SENSOR_CONNECTED = 29243
    SYSTEM_INFO_FORECAST_ENABLED = 29244
    SYSTEM_INFO_BREAKOUT = 29245
    SYSTEM_INFO_WINDOW_OPEN_DETECTION = 29246
    SYSTEM_UI_BRIGTHNESS = 29247
    SYSTEM_ROOM_NAME = 29250
    SYSTEM_HOUSE_NAME = 29251
    SYSTEM_UI_SAFETY_LOCK = 29268
    HEATING_TEMPERATURE_FLOOR = 29298
    HEATING_TEMPERATURE_ROOM = 29299
    HEATING_LOW_TEMPERATURE_WARNING = 29300
    SCHEDULER_CONTROL_INFO = 29328
    SCHEDULER_CONTROL_MODE = 29329
    SCHEDULER_SETPOINT_COMFORT = 29330
    SCHEDULER_SETPOINT_ECONOMY = 29331
    SCHEDULER_SETPOINT_MANUAL = 29332
    SCHEDULER_SETPOINT_AWAY = 29333
    SCHEDULER_SETPOINT_FROST_PROTECTION = 29334
    SCHEDULER_SETPOINT_FLOOR_COMFORT = 29335
    SCHEDULER_SETPOINT_FLOOR_COMFORT_ENABLED = 29336
    SCHEDULER_SETPOINT_MAX_FLOOR = 29337
    SCHEDULER_SETPOINT_TEMPORARY = 29338
    SCHEDULER_AWAY_ISPLANNED = 29339
    SCHEDULER_AWAY = 29340
    LOG_ENERGY_CONSUMPTION_TOTAL = 29377
    LOG_ENERGY_CONSUMPTION_30DAYS = 29378
    LOG_ENERGY_CONSUMPTION_7DAYS = 29379


class ControlState(IntEnum):
    """Value of SCHEDULER_CONTROL_INFO: what the thermostat is doing."""

    CONFIGURING = 0
    MANUAL = 1
    AT_HOME = 2
    AWAY = 3
    VACATION = 4
    FATAL = 5
    PAUSE = 6
    OFF = 7
    AT_HOME_OVERRIDE = 8


class ControlMode(IntEnum):
    """Commands written to SCHEDULER_CONTROL_MODE."""

    WEEKLY_SCHEDULE_ON = 0
    WEEKLY_SCHEDULE_OFF = 1
    OFF_STATE_ON = 2
    OFF_STATE_OFF = 3
    FROST_PROTECTION_ON = 4
    FROST_PROTECTION_OFF = 5
    TEMPORARY_HOME_ON = 6
    TEMPORARY_HOME_OFF = 7


class Alarm(IntEnum):
    """Bits of SYSTEM_ALARM_INFO."""

    DISCONNECTED = 1 << 0
    SHORT_CIRCUITED = 1 << 1
    OVERHEAT = 1 << 2
    UNRECOVERABLE = 1 << 3


# Value types
DECIMAL = "decimal"
BOOL = "bool"
BYTE = "byte"
SHORT = "short"
UINT = "uint"
VERSION = "version"
STRING = "string"
WIZARD = "wizard"

# regulationType values
REGULATION_ROOM = 0
REGULATION_FLOOR = 1
REGULATION_ROOM_AND_FLOOR = 2

# outputPower is stored in units of 25 W; 255 means an external relay
POWER_SCALE = 25
EXTERNAL_RELAY = 255

CODE_INFO: dict[Code, tuple[MsgClass, str]] = {
    Code.GLOBAL_SOFTWAREBUILDREVISION: (MsgClass.DEVICEGLOBAL, SHORT),
    Code.GLOBAL_SERIALNUMBER: (MsgClass.DEVICEGLOBAL, UINT),
    Code.GLOBAL_HARDWAREREVISION: (MsgClass.DEVICEGLOBAL, VERSION),
    Code.GLOBAL_SOFTWAREREVISION: (MsgClass.DEVICEGLOBAL, VERSION),
    Code.WIFI_CONNECTED_STRENGTH: (MsgClass.WIFI, SHORT),
    Code.MDG_CONNECTED_TO_SERVER: (MsgClass.MDG, BOOL),
    Code.MDG_CONNECTION_COUNT: (MsgClass.MDG, BYTE),
    Code.SYSTEM_RUNTIME_INFO_RELAY_COUNT: (MsgClass.DOMINION_SYSTEM, UINT),
    Code.SYSTEM_RUNTIME_INFO_RELAY_ON_TIME: (MsgClass.DOMINION_SYSTEM, UINT),
    Code.SYSTEM_WIZARD_INFO: (MsgClass.DOMINION_SYSTEM, WIZARD),
    Code.SYSTEM_HEATING_INFO: (MsgClass.DOMINION_SYSTEM, BOOL),
    Code.SYSTEM_ALARM_INFO: (MsgClass.DOMINION_SYSTEM, BYTE),
    Code.SYSTEM_WINDOW_OPEN: (MsgClass.DOMINION_SYSTEM, BOOL),
    Code.SYSTEM_INFO_FLOOR_SENSOR_CONNECTED: (MsgClass.DOMINION_SYSTEM, BOOL),
    Code.SYSTEM_INFO_FORECAST_ENABLED: (MsgClass.DOMINION_SYSTEM, BOOL),
    Code.SYSTEM_INFO_BREAKOUT: (MsgClass.DOMINION_SYSTEM, BOOL),
    Code.SYSTEM_INFO_WINDOW_OPEN_DETECTION: (MsgClass.DOMINION_SYSTEM, BOOL),
    Code.SYSTEM_UI_BRIGTHNESS: (MsgClass.DOMINION_SYSTEM, BYTE),
    Code.SYSTEM_ROOM_NAME: (MsgClass.DOMINION_SYSTEM, STRING),
    Code.SYSTEM_HOUSE_NAME: (MsgClass.DOMINION_SYSTEM, STRING),
    Code.SYSTEM_UI_SAFETY_LOCK: (MsgClass.DOMINION_SYSTEM, BOOL),
    Code.HEATING_TEMPERATURE_FLOOR: (MsgClass.DOMINION_HEATING, DECIMAL),
    Code.HEATING_TEMPERATURE_ROOM: (MsgClass.DOMINION_HEATING, DECIMAL),
    Code.HEATING_LOW_TEMPERATURE_WARNING: (MsgClass.DOMINION_HEATING, DECIMAL),
    Code.SCHEDULER_CONTROL_INFO: (MsgClass.DOMINION_SCHEDULER, BYTE),
    Code.SCHEDULER_CONTROL_MODE: (MsgClass.DOMINION_SCHEDULER, BYTE),
    Code.SCHEDULER_SETPOINT_COMFORT: (MsgClass.DOMINION_SCHEDULER, DECIMAL),
    Code.SCHEDULER_SETPOINT_ECONOMY: (MsgClass.DOMINION_SCHEDULER, DECIMAL),
    Code.SCHEDULER_SETPOINT_MANUAL: (MsgClass.DOMINION_SCHEDULER, DECIMAL),
    Code.SCHEDULER_SETPOINT_AWAY: (MsgClass.DOMINION_SCHEDULER, DECIMAL),
    Code.SCHEDULER_SETPOINT_FROST_PROTECTION: (MsgClass.DOMINION_SCHEDULER, DECIMAL),
    Code.SCHEDULER_SETPOINT_FLOOR_COMFORT: (MsgClass.DOMINION_SCHEDULER, DECIMAL),
    Code.SCHEDULER_SETPOINT_FLOOR_COMFORT_ENABLED: (MsgClass.DOMINION_SCHEDULER, BOOL),
    Code.SCHEDULER_SETPOINT_MAX_FLOOR: (MsgClass.DOMINION_SCHEDULER, DECIMAL),
    Code.SCHEDULER_SETPOINT_TEMPORARY: (MsgClass.DOMINION_SCHEDULER, DECIMAL),
    Code.SCHEDULER_AWAY_ISPLANNED: (MsgClass.DOMINION_SCHEDULER, BOOL),
    Code.LOG_ENERGY_CONSUMPTION_TOTAL: (MsgClass.DOMINION_LOGS, UINT),
    Code.LOG_ENERGY_CONSUMPTION_30DAYS: (MsgClass.DOMINION_LOGS, UINT),
    Code.LOG_ENERGY_CONSUMPTION_7DAYS: (MsgClass.DOMINION_LOGS, UINT),
}

HEADER_SIZE = 4


def iter_packets(data: bytes) -> Iterator[tuple[int, int, bytes]]:
    """Split received data into (class, code, payload); many may be merged."""
    pos = 0
    while len(data) - pos >= HEADER_SIZE:
        msg_class = data[pos]
        code = int.from_bytes(data[pos + 1 : pos + 3], "little")
        length = data[pos + 3]
        end = pos + HEADER_SIZE + length
        if end > len(data):
            break  # Malformed tail; drop it
        yield msg_class, code, data[pos + HEADER_SIZE : end]
        pos = end


def decode_value(kind: str, payload: bytes) -> Any:
    """Decode a payload of a known type."""
    if kind == DECIMAL:
        raw = int.from_bytes(payload[:2], "little", signed=True)
        return None if raw == -0x8000 else raw / 100
    if kind == BOOL:
        return payload[0] != 0
    if kind == BYTE:
        return payload[0]
    if kind == SHORT:
        return int.from_bytes(payload[:2], "little", signed=True)
    if kind == UINT:
        return int.from_bytes(payload[:4], "little")
    if kind == VERSION:
        raw = int.from_bytes(payload[:2], "little")
        return f"{raw >> 8}.{raw & 0xFF}"
    if kind == STRING:
        length = payload[0]
        text = payload[1 : 1 + length].split(b"\x00", 1)[0]
        return text.decode(errors="replace")
    if kind == WIZARD:
        # Installer setup, sent as an array: length byte, then sensor type,
        # regulation type, flooring type, room type, output power.
        power = payload[5]
        return {
            "sensor_type": payload[1],
            "regulation_type": payload[2],
            "flooring_type": payload[3],
            "room_type": payload[4],
            "output_power": None if power == EXTERNAL_RELAY else power * POWER_SCALE,
        }
    raise ValueError(kind)


def _header(code: Code, payload: bytes) -> bytes:
    msg_class = CODE_INFO[code][0] if code in CODE_INFO else MsgClass.DOMINION_SCHEDULER
    return bytes([msg_class]) + code.to_bytes(2, "little") + bytes([len(payload)]) + payload


def read_request(code: Code) -> bytes:
    """Ask the thermostat to report a value."""
    return b"\x01" + _header(code, b"")


def write(code: Code, payload: bytes) -> bytes:
    """Set a value on the thermostat."""
    return b"\x00" + _header(code, payload)


def write_decimal(code: Code, value: float) -> bytes:
    return write(code, round(value * 100).to_bytes(2, "little", signed=True))


def write_bool(code: Code, value: bool) -> bytes:
    return write(code, b"\x01" if value else b"\x00")


def write_byte(code: Code, value: int) -> bytes:
    return write(code, bytes([value & 0xFF]))


def write_away_cleared() -> bytes:
    """Clear the vacation period (two 'invalid date' entries)."""
    return write(Code.SCHEDULER_AWAY, bytes(14))
