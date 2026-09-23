"""Ship the bundled Lovelace custom cards into Home Assistant's ``www/``.

Everything under ``www/`` in the integration package ships with the repo.
At setup we mirror it into ``/homeassistant/www/`` so Lovelace can load any
card via its standard URL (e.g. ``/local/lmstudio-model-card/card.js``) —
the integration now owns the cards end-to-end (install / update / rollback
all stay consistent).

The copy is idempotent and content-aware: a file is written only when the
bundled copy actually differs from the deployed one, so browser caches are
not invalidated on every HA restart.

In addition, the card URL is registered via ``add_extra_js_url`` so the
frontend injects a ``<script>`` tag on **every** Lovelace render, regardless
of whether a Lovelace resource entry exists in storage.  This makes the card
survive the known HA storage-rewrite edge case (see album_slideshow pattern)
where a resource entry can be silently dropped without the card being
unloaded from the browser.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__package__)

#: Base URL (no query) the browser loads to get the card bundle.
CARD_BASE = "/local/lmstudio-model-card/card.js"


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


def _url_base(url: str) -> str:
    """Strip the query string so ``/x.js?v=1`` and ``/x.js`` compare equal."""
    return urlparse(url or "")._replace(query="").geturl()


def _versioned_url(content: bytes) -> str:
    """Append ``?v=<12-hex>`` derived from the file content.

    The value only changes when the file content changes, so browsers are
    forced to re-fetch on a real update (and the Nabu Casa edge cache is
    bypassed) but never thrash on a plain HA restart — the same technique as
    album_slideshow (``?v=1.11.0``) and HACS (``?hacstag=…``).
    """
    return f"{CARD_BASE}?v={hashlib.sha256(content).hexdigest()[:12]}"


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


def _deployed_card_path(hass: HomeAssistant) -> Path | None:
    """Path of the deployed card.js under www/, if present."""
    p = _www_root(hass) / "lmstudio-model-card" / "card.js"
    return p if p.exists() else None


def _versioned_url_for(hass: HomeAssistant) -> str:
    """Versioned URL computed from the deployed file's content on disk."""
    p = _deployed_card_path(hass)
    if p is None:
        return CARD_BASE
    return _versioned_url(p.read_bytes())


async def async_register_card(hass: HomeAssistant) -> bool:
    """Register the card bundle with a versioned URL.

    The versioned URL (``?v=<content-hash>``) is the key difference from the
    album_slideshow/HACS/Bambu cards that work on this box: it forces browsers
    (and the Nabu Casa edge) to fetch the real file instead of serving a stale
    cached copy. A plain un-versioned ``/local/…`` URL is exactly what was
    being served stale before.

    Primary mechanism: ``add_extra_js_url`` — the frontend injects a
    ``<script type="module">`` tag on **every** Lovelace render, independent
    of the ``lovelace_resources`` storage.  This is the durable path (same as
    album_slideshow) and keeps the card available even if a resource entry is
    dropped from storage.

    Secondary mechanism: a Lovelace resource entry (create-or-update by URL
    base) for UI discoverability.  Additive and best-effort — failures are
    non-fatal because ``add_extra_js_url`` already covers the load.

    Returns ``True`` if the card was registered (or already registered).
    """
    ok = False
    vurl = await asyncio.get_running_loop().run_in_executor(
        None, _versioned_url_for, hass
    )
    _LOGGER.info("lmstudio: registering card at %s", vurl)

    # --- primary: add_extra_js_url -------------------------------------
    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, vurl)
        ok = True
        _LOGGER.info("lmstudio: card registered via add_extra_js_url at %s", vurl)
    except Exception:  # noqa: BLE001 - version drift, fall through
        _LOGGER.debug("lmstudio: add_extra_js_url unavailable; will rely on resource only", exc_info=True)

    # --- secondary: lovelace resource entry (create-or-update) ---------
    # hass.data key for Lovelace is "lovelace" (LOVELACE_DATA = HassKey(DOMAIN),
    # stable across versions — same approach as album_slideshow).
    lovelace_data = hass.data.get("lovelace")
    if lovelace_data is None:
        # Lovelace not yet set up (mid-bootstrap). The add_extra_js_url
        # registration is already in place (the durable path); skip resource.
        if ok:
            return True
        _LOGGER.debug("lmstudio: lovelace data not ready; skipping resource entry")
        return ok

    resources = getattr(lovelace_data, "resources", None) or (
        lovelace_data.get("resources") if isinstance(lovelace_data, dict) else None
    )
    if resources is None or not hasattr(resources, "async_create_item"):
        if ok:
            return True
        _LOGGER.debug("lmstudio: resource collection unavailable; relying on add_extra_js_url")
        return ok

    base = _url_base(CARD_BASE)
    try:
        if hasattr(resources, "async_load"):
            try:
                await resources.async_load()
            except Exception:  # noqa: BLE001
                pass
        items = list(resources.async_items()) if hasattr(resources, "async_items") else []
        # Find an existing entry by URL base (ignores the ?v= query) so we
        # update it in place instead of stacking duplicate entries.
        existing_idx = -1
        existing_url = ""
        for i, item in enumerate(items):
            iurl = (
                getattr(item, "url", None)
                or (item.get("url") if isinstance(item, dict) else "")
                or ""
            )
            if _url_base(iurl) == base:
                existing_idx = i
                existing_url = iurl
                break

        if existing_idx == -1:
            # No entry yet → create with the versioned URL.
            # 2026.9.3 RESOURCE_CREATE_FIELDS uses ``res_type`` and ``url``.
            await resources.async_create_item({"url": vurl, "res_type": "module"})
            _LOGGER.info("lmstudio: Lovelace resource created for %s", vurl)
        elif existing_url != vurl:
            # Entry exists with a stale/different URL → update in place.
            if hasattr(resources, "async_update_item"):
                await resources.async_update_item(existing_idx, {"url": vurl, "res_type": "module"})
            elif hasattr(resources, "async_delete_item"):
                await resources.async_delete_item(existing_idx)
                await resources.async_create_item({"url": vurl, "res_type": "module"})
            _LOGGER.info("lmstudio: Lovelace resource updated %s → %s", existing_url, vurl)
        # else: already up to date → do nothing.
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "lmstudio: could not manage Lovelace resource; card still loads via add_extra_js_url"
        )

    return True
