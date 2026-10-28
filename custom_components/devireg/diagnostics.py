"""Diagnostics for DEVIreg Smart."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import DeviRegConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeviRegConfigEntry
) -> dict[str, Any]:
    """Connection state and raw values, without the private key."""
    house = entry.runtime_data.house
    return {
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
    }
