"""Config flow for LM Studio: URL + live connectivity test (F5)."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import LMStudioClient, LMStudioConnectionError
from .const import (
    CONF_API_TOKEN,
    CONF_CONTEXT_LENGTH,
    CONF_REFRESH,
    CONF_TIMEOUT,
    CONF_URL,
    DEFAULT_API_TOKEN,
    DEFAULT_REFRESH,
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__package__)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_URL, default=DEFAULT_URL): str,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): int,
    vol.Optional(CONF_REFRESH, default=DEFAULT_REFRESH): int,
    vol.Optional(CONF_API_TOKEN, default=""): str,
    vol.Optional(CONF_CONTEXT_LENGTH): int,
})

STEP_OPTIONS_SCHEMA = vol.Schema({
    vol.Required(CONF_URL): str,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): int,
    vol.Optional(CONF_REFRESH, default=DEFAULT_REFRESH): int,
    vol.Optional(CONF_API_TOKEN): str,
    vol.Optional(CONF_CONTEXT_LENGTH): int,
})


async def _async_test_url(
    hass: HomeAssistant, url: str, timeout: int, api_token: str
) -> int:
    """Probe GET /api/v0/models. Returns model count, raises on failure."""
    session = async_get_clientsession(hass)
    client = LMStudioClient(session, url, timeout=timeout, api_token=api_token)
    info = await client.server_info()
    return int(info.get("model_count", 0))


class LMStudioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LM Studio."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].strip()
            if not url.startswith(("http://", "https://")):
                url = f"http://{url}"
            timeout = int(user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT))
            api_token = user_input.get(CONF_API_TOKEN, "")
            try:
                count = await _async_test_url(self.hass, url, timeout, api_token)
            except LMStudioConnectionError as err:
                errors["base"] = "unreachable"
                _LOGGER.warning("LM Studio config flow: connection test failed: %s", err)
            else:
                data = {
                    CONF_URL: url.rstrip("/"),
                    CONF_TIMEOUT: timeout,
                    CONF_REFRESH: int(user_input.get(CONF_REFRESH, DEFAULT_REFRESH)),
                    CONF_API_TOKEN: api_token,
                }
                context_length = user_input.get(CONF_CONTEXT_LENGTH)
                if context_length:
                    data[CONF_CONTEXT_LENGTH] = int(context_length)
                if count == 0:
                    # Reachable but empty: allow, warn in the entry title.
                    title = "LM Studio"
                else:
                    title = f"LM Studio ({count} models)"
                await self.async_set_unique_id(url.rstrip("/"))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_import(self, import_config: dict) -> FlowResult:
        """Support yaml import (optional)."""
        return await self.async_step_user(import_config)


class LMStudioOptionsFlow(OptionsFlow):
    """Handle options (URL / timeout / refresh / token / context length)."""

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry
        current = dict(entry.data)
        current.setdefault(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        current.setdefault(CONF_REFRESH, DEFAULT_REFRESH)
        current.setdefault(CONF_API_TOKEN, "")

        if user_input is not None:
            url = user_input[CONF_URL].strip()
            if not url.startswith(("http://", "https://")):
                url = f"http://{url}"
            timeout = int(user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT))
            api_token = user_input.get(CONF_API_TOKEN, "")
            try:
                await _async_test_url(self.hass, url, timeout, api_token)
            except LMStudioConnectionError:
                errors["base"] = "unreachable"
            else:
                data = {
                    CONF_URL: url.rstrip("/"),
                    CONF_TIMEOUT: timeout,
                    CONF_REFRESH: int(user_input.get(CONF_REFRESH, DEFAULT_REFRESH)),
                    CONF_API_TOKEN: api_token,
                }
                context_length = user_input.get(CONF_CONTEXT_LENGTH)
                if context_length:
                    data[CONF_CONTEXT_LENGTH] = int(context_length)
                return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="init", data_schema=STEP_OPTIONS_SCHEMA, errors=errors
        )
