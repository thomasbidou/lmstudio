"""Ship the bundled Lovelace custom cards into Home Assistant's ``www/``.

Everything under ``www/`` in the integration package ships with the repo.
At setup we mirror it into ``/homeassistant/www/`` so Lovelace can load any
card via its standard URL (e.g. ``/local/lmstudio-model-card/card.js``) —
the integration now owns the cards end-to-end (install / update / rollback
all stay consistent).

The copy is idempotent and content-aware: a file is written only when the
bundled copy actually differs from the deployed one, so browser caches are
not invalidated on every HA restart.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__package__)


def _bundled_dir() -> Path:
    """Absolute path to the bundled www/ directory inside the package."""
    return Path(__file__).resolve().parent / "www"


def _www_root(hass: HomeAssistant) -> Path:
    """Absolute path to Home Assistant's user www directory."""
    return Path(hass.config.path("www"))


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


async def async_ship_card(hass: HomeAssistant) -> list[Path]:
    """Ensure every bundled card file is present under ``www/``.

    Returns the list of files that were (re)written (empty when everything
    was already up-to-date, or when no bundled www/ directory exists).
    """
    bundled = _bundled_dir()
    if not bundled.is_dir():
        _LOGGER.debug("lmstudio: no bundled www/ directory — skipping ship")
        return []

    # Collect the files to ship (skip anything HA-internal; only real cards).
    sources = sorted(p for p in bundled.rglob("*") if p.is_file())
    if not sources:
        return []

    root = _www_root(hass)
    written: list[Path] = []
    for src in sources:
        dst = root / src.relative_to(bundled)
        if _same_content(src, dst):
            continue
        written.append(dst)

    if not written:
        return []

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _copy_many, sources, root, bundled, written)
    _LOGGER.info(
        "lmstudio: shipped %d Lovelace card file(s) to %s", len(written), root
    )
    return written


def _copy_many(
    sources: list[Path], root: Path, bundled: Path, written: list[Path]
) -> None:
    """Copy each source that was flagged as needing a refresh."""
    to_copy = set(written)
    for src in sources:
        dst = root / src.relative_to(bundled)
        if dst in to_copy:
            _copy_sync(src, dst)
