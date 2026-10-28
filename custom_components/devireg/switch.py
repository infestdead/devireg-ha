"""Switches for DEVIreg Smart settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviRegConfigEntry
from .api import DeviRegError
from .coordinator import DeviRegCoordinator
from .dominion import Code
from .entity import DeviRegEntity, all_thermostats


@dataclass(frozen=True, kw_only=True)
class DeviRegSwitchDescription(SwitchEntityDescription):
    """Describes a switch backed by one boolean setting."""

    code: Code


SWITCHES: tuple[DeviRegSwitchDescription, ...] = (
    DeviRegSwitchDescription(
        key="window_detection",
        translation_key="window_detection",
        code=Code.SYSTEM_WINDOW_OPEN,
        entity_category=EntityCategory.CONFIG,
    ),
    DeviRegSwitchDescription(
        key="forecast",
        translation_key="forecast",
        code=Code.SYSTEM_INFO_FORECAST_ENABLED,
        entity_category=EntityCategory.CONFIG,
    ),
    DeviRegSwitchDescription(
        key="screen_lock",
        translation_key="screen_lock",
        code=Code.SYSTEM_UI_SAFETY_LOCK,
        entity_category=EntityCategory.CONFIG,
    ),
    DeviRegSwitchDescription(
        key="min_floor_temperature_enabled",
        translation_key="min_floor_temperature_enabled",
        code=Code.SCHEDULER_SETPOINT_FLOOR_COMFORT_ENABLED,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviRegConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        DeviRegSwitch(coordinator, peer_id, description)
        for peer_id in all_thermostats(coordinator)
        for description in SWITCHES
    )


class DeviRegSwitch(DeviRegEntity, SwitchEntity):
    """A thermostat setting that can be turned on or off."""

    entity_description: DeviRegSwitchDescription

    def __init__(
        self, coordinator: DeviRegCoordinator, peer_id: str, description: DeviRegSwitchDescription
    ) -> None:
        super().__init__(coordinator, peer_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.thermostat.get(self.entity_description.code)

    async def _set(self, value: bool) -> None:
        try:
            await self.thermostat.set_value(self.entity_description.code, value)
        except DeviRegError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
