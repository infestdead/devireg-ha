"""Climate entity for DEVIreg Smart."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    PRESET_AWAY,
    PRESET_HOME,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviRegConfigEntry
from .api import (
    MODE_MANUAL,
    MODE_OFF,
    MODE_OVERRIDE,
    MODE_PAUSE,
    MODE_SCHEDULE,
    MODE_VACATION,
    DeviRegError,
)
from .const import MAX_TEMP, MIN_TEMP, TEMP_STEP
from .coordinator import DeviRegCoordinator
from .dominion import Code
from .entity import DeviRegEntity, all_thermostats

PRESET_FROST_PROTECTION = "frost_protection"

# Presets are the app's "special" modes; schedule and manual are HVAC modes
PRESET_TO_MODE = {
    PRESET_HOME: MODE_OVERRIDE,
    PRESET_AWAY: MODE_VACATION,
    PRESET_FROST_PROTECTION: MODE_PAUSE,
}
MODE_TO_PRESET = {mode: preset for preset, mode in PRESET_TO_MODE.items()}

HVAC_TO_MODE = {
    HVACMode.AUTO: MODE_SCHEDULE,
    HVACMode.HEAT: MODE_MANUAL,
    HVACMode.OFF: MODE_OFF,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviRegConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one climate entity per thermostat."""
    coordinator = entry.runtime_data
    async_add_entities(DeviRegClimate(coordinator, peer_id) for peer_id in all_thermostats(coordinator))


class DeviRegClimate(DeviRegEntity, ClimateEntity):
    """A DEVIreg Smart floor heating thermostat."""

    _attr_name = None
    _attr_translation_key = "thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = list(HVAC_TO_MODE)
    _attr_preset_modes = [PRESET_NONE, *PRESET_TO_MODE]
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: DeviRegCoordinator, peer_id: str) -> None:
        super().__init__(coordinator, peer_id, "climate")

    @property
    def current_temperature(self) -> float | None:
        return self.thermostat.regulated_temperature

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "floor_temperature": self.thermostat.get(Code.HEATING_TEMPERATURE_FLOOR),
            "room_temperature": self.thermostat.get(Code.HEATING_TEMPERATURE_ROOM),
        }

    @property
    def target_temperature(self) -> float | None:
        return self.thermostat.target_temperature

    @property
    def hvac_mode(self) -> HVACMode | None:
        mode = self.thermostat.mode
        if mode is None:
            return None
        if mode == MODE_OFF:
            return HVACMode.OFF
        if mode == MODE_MANUAL:
            return HVACMode.HEAT
        # Schedule and its temporary overrides (vacation, pause, home) follow the plan
        return HVACMode.AUTO

    @property
    def hvac_action(self) -> HVACAction | None:
        if self.thermostat.mode == MODE_OFF:
            return HVACAction.OFF
        heating = self.thermostat.get(Code.SYSTEM_HEATING_INFO)
        if heating is None:
            return None
        return HVACAction.HEATING if heating else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        return MODE_TO_PRESET.get(self.thermostat.mode, PRESET_NONE)

    async def _call(self, coro) -> None:
        try:
            await coro
        except DeviRegError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self._call(self.thermostat.set_target_temperature(temperature))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._call(self.thermostat.set_mode(HVAC_TO_MODE[hvac_mode]))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._call(
            self.thermostat.set_mode(PRESET_TO_MODE.get(preset_mode, MODE_SCHEDULE))
        )
