"""Diagnostics for DEVIreg Smart."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import DeviRegConfigEntry

# Free-text names and the serial identify the household or the device
TO_REDACT = {
    "name",
    "GLOBAL_SERIALNUMBER",
    "SYSTEM_HOUSE_NAME",
    "SYSTEM_ROOM_NAME",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeviRegConfigEntry
) -> dict[str, Any]:
    """Connection state and raw values, without the private key or personal data."""
    house = entry.runtime_data.house
    return async_redact_data({
        "grid_connected": house.grid_connected,
        "thermostats": [
            {
                "name": t.name,
                "peer_id": f"{t.peer_id[:8]}…",
                "connected": t.connected,
                "last_error": t.last_error,
                "messages_received": t.messages_received,
                "values": {code.name: value for code, value in t.values.items()},
            }
            for t in house.thermostats.values()
        ],
    }, TO_REDACT)
