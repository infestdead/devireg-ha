"""Setpoints and other numeric settings for DEVIreg Smart."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviRegConfigEntry
from .api import DeviRegError
from .const import MAX_TEMP, MIN_TEMP, TEMP_STEP
from .coordinator import DeviRegCoordinator
from .dominion import Code
from .entity import DeviRegEntity, all_thermostats


@dataclass(frozen=True, kw_only=True)
class DeviRegNumberDescription(NumberEntityDescription):
    """Describes a numeric thermostat setting."""

    code: Code


def _setpoint(key: str, code: Code) -> DeviRegNumberDescription:
    return DeviRegNumberDescription(
        key=key,
        translation_key=key,
        code=code,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=MIN_TEMP,
        native_max_value=MAX_TEMP,
        native_step=TEMP_STEP,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    )


NUMBERS: tuple[DeviRegNumberDescription, ...] = (
    _setpoint("comfort_temperature", Code.SCHEDULER_SETPOINT_COMFORT),
    _setpoint("economy_temperature", Code.SCHEDULER_SETPOINT_ECONOMY),
    _setpoint("manual_temperature", Code.SCHEDULER_SETPOINT_MANUAL),
    _setpoint("away_temperature", Code.SCHEDULER_SETPOINT_AWAY),
    _setpoint("frost_protection_temperature", Code.SCHEDULER_SETPOINT_FROST_PROTECTION),
    _setpoint("min_floor_temperature", Code.SCHEDULER_SETPOINT_FLOOR_COMFORT),
    _setpoint("max_floor_temperature", Code.SCHEDULER_SETPOINT_MAX_FLOOR),
    _setpoint("low_temperature_warning", Code.HEATING_LOW_TEMPERATURE_WARNING),
    DeviRegNumberDescription(
        key="display_brightness",
        translation_key="display_brightness",
        code=Code.SYSTEM_UI_BRIGTHNESS,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=10,
        native_max_value=100,
        native_step=10,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviRegConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        DeviRegNumber(coordinator, peer_id, description)
        for peer_id in all_thermostats(coordinator)
        for description in NUMBERS
    )


class DeviRegNumber(DeviRegEntity, NumberEntity):
    """A numeric thermostat setting."""

    entity_description: DeviRegNumberDescription

    def __init__(
        self, coordinator: DeviRegCoordinator, peer_id: str, description: DeviRegNumberDescription
    ) -> None:
        super().__init__(coordinator, peer_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        return self.thermostat.get(self.entity_description.code)

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.thermostat.set_value(self.entity_description.code, value)
        except DeviRegError as err:
            raise HomeAssistantError(str(err)) from err
