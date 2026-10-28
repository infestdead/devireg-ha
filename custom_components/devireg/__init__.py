"""The DEVIreg Smart integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .api import CannotConnect, DeviRegHouse, Room
from .const import CONF_NAME, CONF_PEER_ID, CONF_PRIVATE_KEY, CONF_ROOMS
from .coordinator import DeviRegCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

type DeviRegConfigEntry = ConfigEntry[DeviRegCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: DeviRegConfigEntry) -> bool:
    """Set up a DEVIreg Smart house from a config entry."""
    rooms = [Room(room[CONF_PEER_ID], room[CONF_NAME]) for room in entry.data[CONF_ROOMS]]
    house = DeviRegHouse(entry.data[CONF_PRIVATE_KEY], rooms)
    coordinator = DeviRegCoordinator(hass, entry, house)
    try:
        await coordinator.async_start()
    except CannotConnect as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_stop)

    async def _on_stop(_event: Event) -> None:
        await coordinator.async_stop()

    # Entries are not unloaded on shutdown, so close connections explicitly
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DeviRegConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
