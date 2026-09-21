"""Constants for the LM Studio integration."""

DOMAIN = "lmstudio"

CONF_URL = "url"
CONF_TIMEOUT = "timeout"
CONF_REFRESH = "refresh_interval"
CONF_API_TOKEN = "api_token"
CONF_CONTEXT_LENGTH = "context_length"
CONF_LOCAL_MODELS = "local_models"

DEFAULT_URL = "http://127.0.0.1:1234"
DEFAULT_TIMEOUT = 10
DEFAULT_REFRESH = 60
DEFAULT_API_TOKEN = ""
DEFAULT_LOCAL_MODELS = ""

SERVICE_LOAD = "load_model"
SERVICE_UNLOAD = "unload_model"
SERVICE_REFRESH = "refresh"

# How long to wait (seconds) after a load/unload for the state to flip.
ACTION_CONFIRM_TIMEOUT = 90
ACTION_CONFIRM_POLL = 2


def parse_local_models(text: str) -> set[str]:
    """Parse the local-models allowlist field (newline separated) into a set
    of normalized (stripped, lower-cased) model ids. Empty/whitespace-only
    input -> empty set, which means 'no filtering'.

    Lives in const.py as a pure helper so it can be unit-tested without
    pulling in homeassistant.* imports.
    """
    if text is None:
        return set()
    return {item.strip().lower() for item in str(text).splitlines() if item.strip()}


def compute_model_sync(known_ids: set[str], current_ids: set[str]) -> tuple[set[str], set[str]]:
    """Pure diff used to keep the switch set in sync with the server.

    Returns (added, removed):
      * added   -> ids now on the server but not yet represented as a switch;
      * removed -> ids represented as a switch but no longer on the server.
    Both sets are empty when the two collections are equal. Kept pure (no HA
    imports) so the add/remove behaviour is unit-testable.
    """
    known = set(known_ids or ())
    current = set(current_ids or ())
    return current - known, known - current
