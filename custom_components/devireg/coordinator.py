"""Push-based coordinator for a DEVIreg Smart house."""

from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import DeviRegHouse, Thermostat
from .const import DOMAIN
from .dominion import Code

_LOGGER = logging.getLogger(__name__)


class DeviRegCoordinator(DataUpdateCoordinator[dict[str, Thermostat]]):
    """Holds the thermostats of one house; they push their own updates."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, house: DeviRegHouse) -> None:
        # No update_interval: thermostats push changes over the grid.
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN)
        self.house = house
        self._remove_listener: Callable[[], None] | None = None
        self._device_info: dict[str, tuple] = {}

    async def async_start(self) -> None:
        """Connect and start receiving pushed updates."""
        self._remove_listener = self.house.add_listener(self._handle_update)
        await self.house.start()
        self.async_set_updated_data(self.house.thermostats)

    async def async_stop(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        await self.house.stop()

    def _handle_update(self, thermostat: Thermostat) -> None:
        self._update_device(thermostat)
        self.async_set_updated_data(self.house.thermostats)

    def _update_device(self, thermostat: Thermostat) -> None:
        """Firmware and serial arrive after connecting; keep the registry current."""
        serial = thermostat.get(Code.GLOBAL_SERIALNUMBER)
        info = (
            thermostat.firmware,
            thermostat.get(Code.GLOBAL_HARDWAREREVISION),
            str(serial) if serial is not None else None,
        )
        if self._device_info.get(thermostat.peer_id) == info:
            return
        # get_or_create updates the existing device in place
        dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            identifiers={(DOMAIN, thermostat.peer_id)},
            sw_version=info[0],
            hw_version=info[1],
            serial_number=info[2],
        )
        self._device_info[thermostat.peer_id] = info
