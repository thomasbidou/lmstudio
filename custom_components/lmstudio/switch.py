"""One switch per LM Studio model: ON = loaded, OFF = not-loaded.

The list of models is DYNAMIC and mirrors the server:
  * a model added to LM Studio  -> a switch is created;
  * a model removed from LM Studio -> its switch is deleted.
No integration reload is needed in either case. A coordinator listener
performs the add/remove diff after every successful refresh (and after a
manual `lmstudio.refresh`, which the Lovelace card's Refresh button calls).
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import ModelInfo
from .const import DOMAIN, compute_model_sync
from .coordinator import LMStudioCoordinator

_LOGGER = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create one switch per model and keep the set in sync with the server."""
    coordinator: LMStudioCoordinator = hass.data[DOMAIN][entry.entry_id]

    # model_id -> live switch entity. Single source of truth for which switches
    # currently exist, used to diff against the server on every refresh.
    switches: dict[str, ModelSwitch] = {}

    # Initial batch.
    initial_data = coordinator.data or {}
    for mid, model in initial_data.items():
        switches[mid] = ModelSwitch(coordinator, model)
    async_add_entities(list(switches.values()))

    # Reconcile the live switch set with coordinator.data after each refresh.
    # NOTE: the coordinator invokes this callback SYNCHRONOUSLY (HA's
    # ``async_update_listeners`` is a ``@callback`` and calls ``update_callback()``
    # without awaiting), so the listener itself must be a plain function.
    # Async work (entity removal) is scheduled onto the event loop instead.
    def _handle_update() -> None:
        data = coordinator.data or {}
        current_ids = set(data)
        added, removed = compute_model_sync(set(switches), current_ids)

        if added:
            new_entities = {mid: ModelSwitch(coordinator, data[mid]) for mid in added}
            switches.update(new_entities)
            async_add_entities(list(new_entities.values()))
            _LOGGER.info("LM Studio: added model(s): %s", ", ".join(sorted(added)))

        if removed:
            _LOGGER.info("LM Studio: removed model(s): %s", ", ".join(sorted(removed)))
            for mid in removed:
                # async_remove() deletes the entity + its registry entry, so the
                # model disappears from HA (and from the Lovelace card) cleanly.
                entity = switches.pop(mid)
                hass.async_create_task(entity.async_remove(), f"lmstudio-remove-{mid}")

    coordinator.async_add_listener(_handle_update)


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
