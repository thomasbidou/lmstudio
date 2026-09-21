"""DataUpdateCoordinator for the LM Studio integration.

Responsibilities:
  * poll GET /api/v0/models to keep the loaded state of every model fresh;
  * expose load()/unload() actions guarded by the current state (LM Studio's
    load is NOT idempotent);
  * after an action, confirm the state actually flipped (re-read the API).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import LMStudioClient, LMStudioError, ModelInfo
from .const import (
    ACTION_CONFIRM_POLL,
    ACTION_CONFIRM_TIMEOUT,
    CONF_API_TOKEN,
    CONF_CONTEXT_LENGTH,
    CONF_REFRESH,
    CONF_TIMEOUT,
    CONF_URL,
)

_LOGGER = logging.getLogger(__package__)


class LMStudioCoordinator(DataUpdateCoordinator[dict[str, ModelInfo]]):
    """Coordinates model state for one LM Studio server."""

    config_entry: Any  # set by HA

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        self.hass = hass
        self.entry = entry
        data = entry.data
        self._url: str = data[CONF_URL]
        self._timeout: int = int(data.get(CONF_TIMEOUT, 10))
        self._api_token: str = data.get(CONF_API_TOKEN, "")
        self._context_length: int | None = data.get(CONF_CONTEXT_LENGTH) or None
        self._client: LMStudioClient | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"lmstudio:{entry.title}",
            update_interval=timedelta(seconds=int(data.get(CONF_REFRESH, 60))),
        )

    # ------------------------------------------------------------------ setup
    async def async_setup(self) -> None:
        """Create the aiohttp session bound to the HA session manager."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(self.hass)
        self._client = LMStudioClient(
            session, self._url, timeout=self._timeout, api_token=self._api_token
        )
        await self.async_config_entry_first_refresh()

    @property
    def client(self) -> LMStudioClient | None:
        return self._client

    @property
    def context_length(self) -> int | None:
        return self._context_length

    # ------------------------------------------------------------------ poll
    async def _async_update_data(self) -> dict[str, ModelInfo]:
        if self._client is None:
            raise UpdateFailed("Client not initialized")
        try:
            models = await self._client.list_models()
            # Enrich with v1 details (display name, size). Best-effort: if v1
            # is unavailable the v0 list still works.
            try:
                details = await self._client.model_details()
            except LMStudioError:
                details = {}
            for m in models:
                d = details.get(m.id) or details.get(m.id.split("/")[-1])
                if d:
                    m.display_name = d.get("display_name")
                    m.size_bytes = d.get("size_bytes")
        except LMStudioError as err:
            raise UpdateFailed(f"Error communicating with LM Studio: {err}") from err
        return {m.id: m for m in models}

    # ------------------------------------------------------------------ state
    def model_state(self, model_id: str) -> str:
        """'loaded' | 'not-loaded' | 'unknown'."""
        model = self.data.get(model_id) if self.data else None
        return model.state if model else "unknown"

    def is_loaded(self, model_id: str) -> bool:
        return self.model_state(model_id) == "loaded"

    def is_known(self, model_id: str) -> bool:
        return model_id in (self.data or {})

    # ------------------------------------------------------------- actions
    async def load_model(self, model_id: str) -> None:
        """Load a model, guarded on current state. Confirms the flip after."""
        if self.is_loaded(model_id):
            _LOGGER.debug("load_model(%s) skipped: already loaded", model_id)
            return
        if self._client is None:
            raise HomeAssistantError("LM Studio client not initialized")
        try:
            await self._client.load_model(model_id, self._context_length)
        except LMStudioError as err:
            raise HomeAssistantError(f"Failed to load {model_id}: {err}") from err
        await self._async_confirm_state(model_id, want_loaded=True)

    async def unload_model(self, model_id: str) -> None:
        """Unload a model, guarded on current state. Confirms the flip after."""
        if not self.is_loaded(model_id):
            _LOGGER.debug("unload_model(%s) skipped: not loaded", model_id)
            return
        if self._client is None:
            raise HomeAssistantError("LM Studio client not initialized")
        try:
            await self._client.unload_model(model_id)
        except LMStudioError as err:
            raise HomeAssistantError(f"Failed to unload {model_id}: {err}") from err
        await self._async_confirm_state(model_id, want_loaded=False)

    async def _async_confirm_state(self, model_id: str, *, want_loaded: bool) -> None:
        """Poll the API until the model reports the expected state (or timeout).

        A 'successful' POST is not a successful task — the state must be
        re-read and verified to have flipped. We query the client directly
        (bypassing the coordinator interval) and push the fresh state to
        the entities via async_set_updated_data.
        """
        if self._client is None:
            return
        deadline = asyncio.get_running_loop().time() + ACTION_CONFIRM_TIMEOUT
        while True:
            try:
                models = await self._client.list_models()
                fresh = {m.id: m for m in models}
            except LMStudioError:
                pass
            else:
                model = fresh.get(model_id)
                if model is not None and model.is_loaded is want_loaded:
                    await self.async_set_updated_data(fresh)
                    return
            if asyncio.get_running_loop().time() >= deadline:
                _LOGGER.warning(
                    "State of %s not confirmed as %s within %ss",
                    model_id, "loaded" if want_loaded else "not-loaded",
                    ACTION_CONFIRM_TIMEOUT,
                )
                return
            await asyncio.sleep(ACTION_CONFIRM_POLL)
