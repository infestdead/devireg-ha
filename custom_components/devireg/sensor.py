"""Sensors for DEVIreg Smart."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviRegConfigEntry
from .api import Thermostat
from .coordinator import DeviRegCoordinator
from .dominion import Code
from .entity import DeviRegEntity, all_thermostats


@dataclass(frozen=True, kw_only=True)
class DeviRegSensorDescription(SensorEntityDescription):
    """Describes a sensor backed by one thermostat value."""

    code: Code | None = None
    value_fn: Callable[[Thermostat], float | int | None] | None = None


def _temperature(key: str, code: Code) -> DeviRegSensorDescription:
    return DeviRegSensorDescription(
        key=key,
        translation_key=key,
        code=code,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    )


def _on_time(key: str, code: Code, state_class: SensorStateClass) -> DeviRegSensorDescription:
    return DeviRegSensorDescription(
        key=key,
        translation_key=key,
        code=code,
        device_class=SensorDeviceClass.DURATION,
        state_class=state_class,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
    )


def _energy(key: str, code: Code, state_class: SensorStateClass | None) -> DeviRegSensorDescription:
    return DeviRegSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENERGY,
        state_class=state_class,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda t: t.energy_kwh(code),
    )


SENSORS: tuple[DeviRegSensorDescription, ...] = (
    _temperature("room_temperature", Code.HEATING_TEMPERATURE_ROOM),
    _temperature("floor_temperature", Code.HEATING_TEMPERATURE_FLOOR),
    _on_time("heating_time_7_days", Code.LOG_ENERGY_CONSUMPTION_7DAYS, SensorStateClass.MEASUREMENT),
    _on_time("heating_time_30_days", Code.LOG_ENERGY_CONSUMPTION_30DAYS, SensorStateClass.MEASUREMENT),
    _on_time("heating_time_total", Code.SYSTEM_RUNTIME_INFO_RELAY_ON_TIME, SensorStateClass.TOTAL_INCREASING),
    # The thermostat does not meter energy; like the app, estimate it from
    # heater on-time and the installed heater power.
    _energy("energy_7_days", Code.LOG_ENERGY_CONSUMPTION_7DAYS, None),
    _energy("energy_30_days", Code.LOG_ENERGY_CONSUMPTION_30DAYS, None),
    _energy("energy_total", Code.SYSTEM_RUNTIME_INFO_RELAY_ON_TIME, SensorStateClass.TOTAL_INCREASING),
    DeviRegSensorDescription(
        key="heater_power",
        translation_key="heater_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.heater_power,
    ),
    DeviRegSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        code=Code.WIFI_CONNECTED_STRENGTH,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    DeviRegSensorDescription(
        key="relay_switch_count",
        translation_key="relay_switch_count",
        code=Code.SYSTEM_RUNTIME_INFO_RELAY_COUNT,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviRegConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        DeviRegSensor(coordinator, peer_id, description)
        for peer_id in all_thermostats(coordinator)
        for description in SENSORS
    )


class DeviRegSensor(DeviRegEntity, SensorEntity):
    """A value reported by the thermostat."""

    entity_description: DeviRegSensorDescription

    def __init__(
        self, coordinator: DeviRegCoordinator, peer_id: str, description: DeviRegSensorDescription
    ) -> None:
        super().__init__(coordinator, peer_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        description = self.entity_description
        if description.value_fn:
            return description.value_fn(self.thermostat)
        return self.thermostat.get(description.code)
