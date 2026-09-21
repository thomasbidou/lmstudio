"""One switch per LM Studio model: ON = loaded, OFF = not-loaded."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import ModelInfo
from .const import DOMAIN
from .coordinator import LMStudioCoordinator

_LOGGER = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create one switch per model known to the server."""
    coordinator: LMStudioCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_ids: set[str] = set((coordinator.data or {}).keys())
    async_add_entities([
        ModelSwitch(coordinator, model)
        for model in (coordinator.data or {}).values()
    ])

    # Pick up models downloaded into LM Studio after setup.
    async def _on_update() -> None:
        data = coordinator.data or {}
        new = [mid for mid in data if mid not in known_ids]
        if new:
            _LOGGER.info("New models detected on LM Studio: %s", new)
            known_ids.update(new)
            async_add_entities([ModelSwitch(coordinator, data[mid]) for mid in new])

    coordinator.async_add_listener(_on_update)


class ModelSwitch(CoordinatorEntity[LMStudioCoordinator]):
    """Represents one model; ON means the model is loaded on the server."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LMStudioCoordinator, model: ModelInfo) -> None:
        super().__init__(coordinator)
        self._model_id = model.id
        self._attr_unique_id = self._model_id
        self._attr_name = model.name

    @property
    def state(self) -> str | None:
        if not self.coordinator.last_update_success:
            return None
        model = self.coordinator.data.get(self._model_id)
        if model is None:
            return "off"
        return "on" if model.is_loaded else "off"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        attrs: dict[str, object] = {
            "model_id": self._model_id,
            "lmstudio_state": "unknown",
        }
        model = self.coordinator.data.get(self._model_id) if self.coordinator.data else None
        if model is not None:
            attrs["lmstudio_state"] = model.state
            if model.size_bytes is not None:
                attrs["size_bytes"] = model.size_bytes
            if model.quantization:
                attrs["quantization"] = model.quantization
            if model.arch:
                attrs["architecture"] = model.arch
        return attrs

    async def async_turn_on(self, **kwargs: object) -> None:
        try:
            await self.coordinator.load_model(self._model_id)
        except HomeAssistantError as err:
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        try:
            await self.coordinator.unload_model(self._model_id)
        except HomeAssistantError as err:
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()
