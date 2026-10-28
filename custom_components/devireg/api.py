"""High-level client for a DEVIreg Smart house.

One house shares a single key pair (created when pairing with the app) and
contains one or more thermostats, each reached over its own SDG tunnel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
import time
from typing import Any

from . import dominion
from .dominion import Code, ControlMode, ControlState
from .sdg import Grid, SDGError, generate_private_key
from .sdg.grid import PROTOCOL_DOMINION

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 10
PING_AFTER = 15
STALE_AFTER = 30


class DeviRegError(Exception):
    """Base error for the DEVIreg client."""


class CannotConnect(DeviRegError):
    """The SDG grid could not be reached."""


class InvalidOtp(DeviRegError):
    """The one-time pairing code was rejected or expired."""


# Modes as the DEVIsmart app presents them
MODE_SCHEDULE = "schedule"
MODE_MANUAL = "manual"
MODE_OVERRIDE = "override"
MODE_VACATION = "vacation"
MODE_PAUSE = "pause"
MODE_OFF = "off"

STATE_TO_MODE = {
    ControlState.MANUAL: MODE_MANUAL,
    ControlState.AT_HOME: MODE_SCHEDULE,
    ControlState.AWAY: MODE_SCHEDULE,
    ControlState.VACATION: MODE_VACATION,
    ControlState.PAUSE: MODE_PAUSE,
    ControlState.OFF: MODE_OFF,
    ControlState.AT_HOME_OVERRIDE: MODE_OVERRIDE,
}

# Which setpoint drives the room temperature in each state
STATE_SETPOINT = {
    ControlState.MANUAL: Code.SCHEDULER_SETPOINT_MANUAL,
    ControlState.AT_HOME: Code.SCHEDULER_SETPOINT_COMFORT,
    ControlState.AWAY: Code.SCHEDULER_SETPOINT_ECONOMY,
    ControlState.VACATION: Code.SCHEDULER_SETPOINT_AWAY,
    ControlState.PAUSE: Code.SCHEDULER_SETPOINT_FROST_PROTECTION,
    ControlState.AT_HOME_OVERRIDE: Code.SCHEDULER_SETPOINT_TEMPORARY,
}


@dataclass
class Room:
    """A thermostat as listed in the shared house configuration."""

    peer_id: str
    name: str


@dataclass
class PairingResult:
    """Everything needed to talk to the house later."""

    private_key: str
    house_name: str
    rooms: list[Room]


async def pair(
    otp: str, user_name: str, servers: list[tuple[str, int]] | None = None
) -> PairingResult:
    """Pair with the DEVIsmart app using a 'Share house' one-time code."""
    private_key = generate_private_key()
    grid = Grid(private_key, servers)
    try:
        await grid.connect()
    except (OSError, TimeoutError, SDGError) as err:
        raise CannotConnect(str(err)) from err
    try:
        try:
            phone_id = await grid.pair_remote(otp)
        except ValueError as err:
            raise InvalidOtp(str(err)) from err
        except (TimeoutError, SDGError) as err:
            # A wrong or expired code shows up as a refusal or a timeout
            raise InvalidOtp(str(err)) from err
        try:
            config = await grid.fetch_house_config(phone_id, user_name)
        except (OSError, TimeoutError, SDGError) as err:
            raise CannotConnect(f"Could not receive the house from the app: {err}") from err
    finally:
        await grid.close()

    rooms = [
        Room(peer_id=room["peerId"].strip().lower(), name=room.get("roomName", ""))
        for room in config.get("rooms") or []
        if room.get("peerId")
    ]
    if not rooms:
        raise DeviRegError("The shared house has no DEVIreg Smart thermostats")
    return PairingResult(
        private_key=private_key.hex(),
        house_name=config.get("houseName") or "DEVIreg",
        rooms=rooms,
    )


class Thermostat:
    """Live state of one thermostat, kept up to date over its tunnel."""

    def __init__(self, house: DeviRegHouse, room: Room) -> None:
        self._house = house
        self.peer_id = room.peer_id
        self.name = room.name
        self.values: dict[Code, Any] = {}
        self.connected = False
        self.last_error: str | None = None
        self.messages_received = 0
        self._tunnel = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._last_packet = 0.0

    # Values

    def get(self, code: Code) -> Any:
        return self.values.get(code)

    @property
    def control_state(self) -> ControlState | None:
        value = self.values.get(Code.SCHEDULER_CONTROL_INFO)
        try:
            return ControlState(value) if value is not None else None
        except ValueError:
            return None

    @property
    def mode(self) -> str | None:
        state = self.control_state
        return STATE_TO_MODE.get(state) if state is not None else None

    @property
    def target_temperature(self) -> float | None:
        code = STATE_SETPOINT.get(self.control_state)
        return self.values.get(code) if code else None

    @property
    def heater_power(self) -> int | None:
        """Heater power in W from the installer setup; None for an external relay."""
        wizard = self.values.get(Code.SYSTEM_WIZARD_INFO)
        return wizard["output_power"] if wizard else None

    @property
    def regulated_temperature(self) -> float | None:
        """The reading the thermostat regulates on, as shown on its display."""
        wizard = self.values.get(Code.SYSTEM_WIZARD_INFO)
        room = self.values.get(Code.HEATING_TEMPERATURE_ROOM)
        floor = self.values.get(Code.HEATING_TEMPERATURE_FLOOR)
        if wizard and wizard["regulation_type"] == dominion.REGULATION_FLOOR and floor is not None:
            return floor
        return room if room is not None else floor

    def energy_kwh(self, on_time_code: Code) -> float | None:
        """Energy estimated like the app does: heater on-time times heater power."""
        seconds = self.values.get(on_time_code)
        power = self.heater_power
        if seconds is None or not power:
            return None
        return round(seconds * power / 3_600_000, 3)

    @property
    def firmware(self) -> str | None:
        version = self.values.get(Code.GLOBAL_SOFTWAREREVISION)
        build = self.values.get(Code.GLOBAL_SOFTWAREBUILDREVISION)
        if version is None:
            return None
        return f"{version}.{build & 0xFFFF}" if build is not None else version

    # Connection

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._close()

    def _close(self) -> None:
        if self._tunnel:
            self._tunnel.close()
            self._tunnel = None
        if self.connected:
            self.connected = False
            self._house.notify(self)

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                self.last_error = f"{type(err).__name__}: {err}"
                _LOGGER.warning("Thermostat %s offline: %s", self.name, self.last_error)
            self._close()
            await asyncio.sleep(RECONNECT_DELAY)

    async def _session(self) -> None:
        grid = await self._house.get_grid()
        self._tunnel = await grid.connect_to_peer(bytes.fromhex(self.peer_id), PROTOCOL_DOMINION)
        self._last_packet = time.monotonic()
        self.connected = True
        self.last_error = None
        _LOGGER.info("Connected to thermostat %s", self.name)
        self._house.notify(self)
        first = True
        watchdog = asyncio.get_running_loop().create_task(self._watchdog())
        try:
            while True:
                data = await self._tunnel.recv()
                if first:
                    # The first message carries one garbage byte, a known quirk
                    data, first = data[1:], False
                self._handle(data)
        finally:
            watchdog.cancel()

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(5)
            idle = time.monotonic() - self._last_packet
            if idle > STALE_AFTER and self._tunnel:
                # Closing the tunnel ends the receive loop, which reconnects
                _LOGGER.warning("Thermostat %s silent for %ds, reconnecting", self.name, idle)
                self._tunnel.close()
                return
            if idle > PING_AFTER and self._tunnel:
                await self._tunnel.send(dominion.read_request(Code.HEATING_TEMPERATURE_FLOOR))

    def _handle(self, data: bytes) -> None:
        self._last_packet = time.monotonic()
        self.messages_received += 1
        _LOGGER.debug("Thermostat %s sent %s", self.name, data.hex())
        changed = False
        for _msg_class, code, payload in dominion.iter_packets(data):
            try:
                known = Code(code)
            except ValueError:
                continue
            if known not in dominion.CODE_INFO:
                continue  # Known code we only ever write, such as SCHEDULER_AWAY
            kind = dominion.CODE_INFO[known][1]
            try:
                value = dominion.decode_value(kind, payload)
            except (IndexError, ValueError):
                _LOGGER.debug("Bad payload for %s: %s", known.name, payload.hex())
                continue
            if self.values.get(known) != value:
                self.values[known] = value
                changed = True
        if changed:
            self._house.notify(self)

    # Commands

    async def _send(self, data: bytes) -> None:
        if not self._tunnel or not self.connected:
            raise DeviRegError(f"{self.name} is not connected")
        await self._tunnel.send(data)

    async def set_value(self, code: Code, value: float | bool | int) -> None:
        kind = dominion.CODE_INFO[code][1]
        if kind == dominion.DECIMAL:
            await self._send(dominion.write_decimal(code, float(value)))
        elif kind == dominion.BOOL:
            await self._send(dominion.write_bool(code, bool(value)))
        else:
            await self._send(dominion.write_byte(code, int(value)))

    async def set_target_temperature(self, temperature: float) -> None:
        """Change the setpoint used by the current mode."""
        state = self.control_state
        if state is ControlState.OFF:
            raise DeviRegError("Cannot set a temperature while the thermostat is off")
        if state in (ControlState.AT_HOME, ControlState.AWAY):
            # Changing a schedule setpoint would alter every scheduled day, so
            # do what the app does: hold this temperature until the next period.
            await self._send(
                dominion.write_decimal(Code.SCHEDULER_SETPOINT_TEMPORARY, temperature)
                + dominion.write_byte(Code.SCHEDULER_CONTROL_MODE, ControlMode.TEMPORARY_HOME_ON)
            )
            return
        code = STATE_SETPOINT.get(state, Code.SCHEDULER_SETPOINT_MANUAL)
        await self._send(dominion.write_decimal(code, temperature))

    async def set_mode(self, mode: str) -> None:
        """Switch control mode, cancelling 'special' modes first like the app does."""
        state = self.control_state
        if state in (None, ControlState.CONFIGURING, ControlState.FATAL):
            raise DeviRegError(f"{self.name} cannot change mode right now")
        if STATE_TO_MODE.get(state) == mode:
            return

        out = b""
        if state is ControlState.VACATION:
            out += dominion.write_away_cleared()
            out += dominion.write_bool(Code.SCHEDULER_AWAY_ISPLANNED, False)
        elif state is ControlState.PAUSE:
            out += dominion.write_byte(Code.SCHEDULER_CONTROL_MODE, ControlMode.FROST_PROTECTION_OFF)
        elif state is ControlState.OFF:
            out += dominion.write_byte(Code.SCHEDULER_CONTROL_MODE, ControlMode.OFF_STATE_OFF)
        elif state is ControlState.AT_HOME_OVERRIDE:
            out += dominion.write_byte(Code.SCHEDULER_CONTROL_MODE, ControlMode.TEMPORARY_HOME_OFF)

        if mode == MODE_MANUAL:
            out += dominion.write_byte(Code.SCHEDULER_CONTROL_MODE, ControlMode.WEEKLY_SCHEDULE_OFF)
        elif mode == MODE_SCHEDULE:
            out += dominion.write_byte(Code.SCHEDULER_CONTROL_MODE, ControlMode.WEEKLY_SCHEDULE_ON)
        elif mode == MODE_OVERRIDE:
            out += dominion.write_byte(Code.SCHEDULER_CONTROL_MODE, ControlMode.TEMPORARY_HOME_ON)
        elif mode == MODE_VACATION:
            out += dominion.write_away_cleared()
            out += dominion.write_bool(Code.SCHEDULER_AWAY_ISPLANNED, True)
        elif mode == MODE_PAUSE:
            out += dominion.write_byte(Code.SCHEDULER_CONTROL_MODE, ControlMode.FROST_PROTECTION_ON)
        elif mode == MODE_OFF:
            out += dominion.write_byte(Code.SCHEDULER_CONTROL_MODE, ControlMode.OFF_STATE_ON)
        else:
            raise ValueError(mode)
        await self._send(out)


class DeviRegHouse:
    """A shared house: one grid connection plus a tunnel per thermostat."""

    def __init__(
        self,
        private_key: str,
        rooms: list[Room],
        servers: list[tuple[str, int]] | None = None,
    ) -> None:
        self._private_key = bytes.fromhex(private_key)
        self._servers = servers
        self._grid: Grid | None = None
        self._grid_lock = asyncio.Lock()
        self._listeners: list[Callable[[Thermostat], None]] = []
        self.thermostats = {room.peer_id: Thermostat(self, room) for room in rooms}

    async def start(self) -> None:
        """Connect to the grid, then start every thermostat connection."""
        try:
            await self.get_grid()
        except (OSError, TimeoutError, SDGError) as err:
            raise CannotConnect(str(err)) from err
        for thermostat in self.thermostats.values():
            thermostat.start()

    async def stop(self) -> None:
        await asyncio.gather(*(t.stop() for t in self.thermostats.values()))
        if self._grid:
            await self._grid.close()
            self._grid = None

    async def get_grid(self) -> Grid:
        async with self._grid_lock:
            if self._grid is None or not self._grid.connected:
                grid = Grid(self._private_key, self._servers)
                await grid.connect()
                self._grid = grid
            return self._grid

    @property
    def grid_connected(self) -> bool:
        return self._grid is not None and self._grid.connected

    def add_listener(self, callback: Callable[[Thermostat], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def notify(self, thermostat: Thermostat) -> None:
        for callback in list(self._listeners):
            try:
                callback(thermostat)
            except Exception:
                # A listener bug must never take down the thermostat connection
                _LOGGER.exception("Error in DEVIreg update listener")
