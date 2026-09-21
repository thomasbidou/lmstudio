"""Ship the bundled Lovelace custom card into Home Assistant's ``www/``.

The card (``www/lmstudio-model-card/card.js``) ships inside the integration
package, versioned with the repo.  At setup we copy it into
``/homeassistant/www/`` so Lovelace can load it via the standard
``/local/lmstudio-model-card/card.js`` URL — the integration now owns the
card end-to-end (install / update / rollback all stay consistent).

The copy is idempotent and content-aware: it only writes when the bundled
card actually differs from the deployed one, so browser caches are not
invalidated on every HA restart.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__package__)

#: card path relative to the integration package root
CARD_REL = Path("www") / "lmstudio-model-card" / "card.js"


def _bundled_card() -> Path:
    """Absolute path to the bundled card.js inside the package."""
    return Path(__file__).resolve().parent / CARD_REL


def _target_path(hass: HomeAssistant) -> Path:
    """Absolute path where the card should live under HA's www dir."""
    return Path(hass.config.path("www")) / "lmstudio-model-card" / "card.js"


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _same_content(a: Path, b: Path) -> bool:
    """True if both files exist and have identical content."""
    if not a.exists() or not b.exists():
        return False
    try:
        return _digest(a) == _digest(b)
    except OSError:
        return False


def _copy_sync(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


async def async_ship_card(hass: HomeAssistant) -> Path | None:
    """Ensure the bundled card is present in ``www/``.

    Returns the target path when it was (re)written, or ``None`` when the
    card was already up-to-date (or could not be found).
    """
    bundled = _bundled_card()
    if not bundled.exists():
        _LOGGER.debug(
            "lmstudio: bundled card not found at %s — skipping ship", bundled
        )
        return None

    target = _target_path(hass)
    if _same_content(bundled, target):
        return None

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _copy_sync, bundled, target)
    _LOGGER.info("lmstudio: shipped Lovelace card to %s", target)
    return target
