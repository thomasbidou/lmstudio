"""Constants for the LM Studio integration."""

DOMAIN = "lmstudio"

CONF_URL = "url"
CONF_TIMEOUT = "timeout"
CONF_REFRESH = "refresh_interval"
CONF_API_TOKEN = "api_token"
CONF_CONTEXT_LENGTH = "context_length"

DEFAULT_URL = "http://127.0.0.1:1234"
DEFAULT_TIMEOUT = 10
DEFAULT_REFRESH = 60
DEFAULT_API_TOKEN = ""

SERVICE_LOAD = "load_model"
SERVICE_UNLOAD = "unload_model"
SERVICE_REFRESH = "refresh"

# How long to wait (seconds) after a load/unload for the state to flip.
ACTION_CONFIRM_TIMEOUT = 90
ACTION_CONFIRM_POLL = 2
