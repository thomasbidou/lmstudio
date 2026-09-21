"""Global sensors: loaded count, total count, server online."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription

from .const import DOMAIN
from .coordinator import LMStudioCoordinator

LOADED_COUNT = SensorEntityDescription(
    key="loaded_count",
    name="Loaded models",
    icon="mdi:memory",
)

TOTAL_COUNT = SensorEntityDescription(
    key="total_count",
    name="Total models",
    icon="mdi:database",
)

SERVER_ONLINE = SensorEntityDescription(
    key="server_online",
    name="Server",
    icon="mdi:server-network",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: LMStudioCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        GlobalSensor(coordinator, LOADED_COUNT),
        GlobalSensor(coordinator, TOTAL_COUNT),
        GlobalSensor(coordinator, SERVER_ONLINE),
    ])


class GlobalSensor(CoordinatorEntity[LMStudioCoordinator], SensorEntity):
    def __init__(self, coordinator: LMStudioCoordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.name}_{description.key}"

    @property
    def state(self) -> str | int | None:
        if not self.coordinator.last_update_success:
            return None
        data = self.coordinator.data or {}
        if self.entity_description.key == "loaded_count":
            return sum(1 for m in data.values() if m.is_loaded)
        if self.entity_description.key == "total_count":
            return len(data)
        return "online" if data is not None else "offline"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
