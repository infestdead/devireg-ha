"""Binary sensors for DEVIreg Smart."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviRegConfigEntry
from .api import Thermostat
from .coordinator import DeviRegCoordinator
from .dominion import Alarm, Code
from .entity import DeviRegEntity, all_thermostats


@dataclass(frozen=True, kw_only=True)
class DeviRegBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor."""

    value_fn: Callable[[Thermostat], bool | None]


def _alarm(key: str, bit: Alarm) -> DeviRegBinarySensorDescription:
    def value(thermostat: Thermostat) -> bool | None:
        alarms = thermostat.get(Code.SYSTEM_ALARM_INFO)
        return None if alarms is None else bool(alarms & bit)

    return DeviRegBinarySensorDescription(
        key=key,
        translation_key=key,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=value,
    )


BINARY_SENSORS: tuple[DeviRegBinarySensorDescription, ...] = (
    DeviRegBinarySensorDescription(
        key="heating",
        translation_key="heating",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda t: t.get(Code.SYSTEM_HEATING_INFO),
    ),
    DeviRegBinarySensorDescription(
        key="window_open",
        translation_key="window_open",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda t: t.get(Code.SYSTEM_INFO_WINDOW_OPEN_DETECTION),
    ),
    _alarm("sensor_disconnected", Alarm.DISCONNECTED),
    _alarm("sensor_short_circuit", Alarm.SHORT_CIRCUITED),
    _alarm("overheat", Alarm.OVERHEAT),
    _alarm("unrecoverable_error", Alarm.UNRECOVERABLE),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviRegConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        DeviRegBinarySensor(coordinator, peer_id, description)
        for peer_id in all_thermostats(coordinator)
        for description in BINARY_SENSORS
    )


class DeviRegBinarySensor(DeviRegEntity, BinarySensorEntity):
    """An on/off state reported by the thermostat."""

    entity_description: DeviRegBinarySensorDescription

    def __init__(
        self,
        coordinator: DeviRegCoordinator,
        peer_id: str,
        description: DeviRegBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, peer_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.thermostat)
