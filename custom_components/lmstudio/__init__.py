"""The LM Studio integration for Home Assistant.

Manage load/unload of models on a local LM Studio server.
One `switch` per model (ON = loaded, OFF = not-loaded) + a few global
sensors, driven by a DataUpdateCoordinator polling GET /api/v0/models.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .card import async_ship_card
from .client import LMStudioClient, LMStudioConnectionError
from .const import (
    CONF_API_TOKEN,
    CONF_TIMEOUT,
    CONF_URL,
    DEFAULT_API_TOKEN,
    DEFAULT_TIMEOUT,
    DOMAIN,
    SERVICE_LOAD,
    SERVICE_REFRESH,
    SERVICE_UNLOAD,
)
from .coordinator import LMStudioCoordinator

_LOGGER = logging.getLogger(__package__)

PLATFORMS = ["switch", "sensor"]

MODEL_ID_SCHEMA = vol.Schema({
    vol.Required("model"): cv.string,
})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Nothing to do at import time; entries drive the setup."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LM Studio from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    data = entry.data
    url = data[CONF_URL]
    session = async_get_clientsession(hass)

    # Validate the server is reachable before creating the coordinator.
    probe = LMStudioClient(
        session, url,
        timeout=int(data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
        api_token=data.get(CONF_API_TOKEN, DEFAULT_API_TOKEN),
    )
    try:
        info = await probe.server_info()
    except LMStudioConnectionError as err:
        raise ConfigEntryNotReady(
            f"LM Studio server at {url} is not reachable: {err}"
        ) from err
    _LOGGER.info(
        "LM Studio entry '%s' ready (%d models reported)", entry.title, info.get("model_count", -1)
    )

    coordinator = LMStudioCoordinator(hass, entry)
    await coordinator.async_setup()

    # Ship the Lovelace card bundled with the integration (idempotent).
    await _async_sync_card(hass)

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ---------------------------------------------------------------- services
    async def _svc_load(call: ServiceCall) -> None:
        model = call.data["model"]
        if not coordinator.is_known(model):
            raise HomeAssistantError(
                f"Unknown model '{model}'. Known models: {sorted(coordinator.data.keys())}"
            )
        try:
            await coordinator.load_model(model)
        except HomeAssistantError:
            raise
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Failed to load '{model}': {err}") from err

    async def _svc_unload(call: ServiceCall) -> None:
        model = call.data["model"]
        try:
            await coordinator.unload_model(model)
        except HomeAssistantError:
            raise
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Failed to unload '{model}': {err}") from err

    async def _svc_refresh(call: ServiceCall) -> None:
        await coordinator.async_refresh()

    hass.services.async_register(DOMAIN, SERVICE_LOAD, _svc_load, schema=MODEL_ID_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_UNLOAD, _svc_unload, schema=MODEL_ID_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _svc_refresh)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Remove global services once no entry remains.
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_LOAD)
            hass.services.async_remove(DOMAIN, SERVICE_UNLOAD)
            hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update: rebuild the coordinator with new settings."""
    await hass.config_entries.async_reload(entry.entry_id)
