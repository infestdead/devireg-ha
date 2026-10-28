"""Base entity for DEVIreg Smart."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Thermostat
from .const import DOMAIN
from .coordinator import DeviRegCoordinator


class DeviRegEntity(CoordinatorEntity[DeviRegCoordinator]):
    """An entity belonging to one thermostat."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DeviRegCoordinator, peer_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._peer_id = peer_id
        self._attr_unique_id = f"{peer_id}_{key}"
        thermostat = self.thermostat
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, peer_id)},
            name=thermostat.name or "DEVIreg Smart",
            manufacturer="Danfoss",
            model="DEVIreg Smart",
        )

    @property
    def thermostat(self) -> Thermostat:
        return self.coordinator.house.thermostats[self._peer_id]

    @property
    def available(self) -> bool:
        return super().available and self.thermostat.connected and bool(self.thermostat.values)


def all_thermostats(coordinator: DeviRegCoordinator) -> list[str]:
    return list(coordinator.house.thermostats)
