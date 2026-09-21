"""Thin async client for the LM Studio local server.

Two API families, NOT interchangeable (verified against a live server):
  * state (loaded / not-loaded)  -> GET  /api/v0/models   (clean per-model `state` flag)
  * actions (load / unload)      -> POST /api/v1/models/load | /api/v1/models/unload
                                    with the model id in the JSON BODY (ids contain '/',
                                    which breaks path-style routes).

Every POST must carry `Content-Type: application/json` or LM Studio answers
`Unsupported Media Type` and silently does nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import DEFAULT_TIMEOUT

_LOGGER = logging.getLogger(__package__)


class LMStudioError(Exception):
    """Base error for LM Studio client problems."""


class LMStudioConnectionError(LMStudioError):
    """The server could not be reached."""


class LMStudioActionError(LMStudioError):
    """A load/unload action was rejected by the server."""


@dataclass
class ModelInfo:
    """A single model as reported by GET /api/v0/models.

    Note: v0 carries `quantization`, `arch`, `publisher`, `max_context_length`
    but NO size and NO displayName — size/display come from v1 if wanted.
    """

    id: str
    state: str  # "loaded" | "not-loaded"
    publisher: str = ""
    arch: str = ""
    quantization: str = ""
    max_context_length: int | None = None
    size_bytes: int | None = None
    display_name: str | None = None

    @property
    def is_loaded(self) -> bool:
        return self.state == "loaded"

    @property
    def name(self) -> str:
        if self.display_name:
            return self.display_name
        return self.id.split("/")[-1]

    @property
    def slug(self) -> str:
        return self.id.replace("/", "_")


class LMStudioClient:
    """Async client for one LM Studio server."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        api_token: str = "",
    ) -> None:
        self._session = session
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._api_token = api_token

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        return headers

    @staticmethod
    def _error_from_payload(payload: Any) -> LMStudioActionError:
        detail = ""
        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                if key in payload:
                    detail = str(payload[key])
                    break
            if not detail:
                detail = str(payload)
        elif isinstance(payload, (list, str)):
            detail = str(payload)
        return LMStudioActionError(f"LM Studio rejected the action: {detail}" if detail else "LM Studio rejected the action (no detail)")

    async def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with self._session.get(
                url, headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise LMStudioConnectionError(f"Cannot reach LM Studio at {url}: {err}") from err
        except ValueError as err:  # invalid JSON
            raise LMStudioConnectionError(f"LM Studio at {url} returned invalid JSON") from err

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        headers = self._headers()
        # Mandatory on every POST: without it LM Studio returns
        # "Unsupported Media Type" and the action silently does nothing.
        headers["Content-Type"] = "application/json"
        try:
            async with self._session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                try:
                    body = await resp.json()
                except ValueError:
                    body = await resp.text()
                if resp.status >= 400:
                    raise self._error_from_payload(body)
                # LM Studio sometimes signals failure with HTTP 200 + an error body.
                if isinstance(body, dict) and (body.get("error") or body.get("success") is False):
                    raise self._error_from_payload(body)
                return body
        except aiohttp.ClientError as err:
            raise LMStudioConnectionError(f"Cannot reach LM Studio at {url}: {err}") from err

    async def list_models(self) -> list[ModelInfo]:
        """GET /api/v0/models — the clean source of truth for loaded state."""
        data = await self._get("/api/v0/models")
        entries = data.get("data", []) if isinstance(data, dict) else []
        out: list[ModelInfo] = []
        for m in entries:
            if not m.get("id"):
                continue
            out.append(
                ModelInfo(
                    id=str(m["id"]),
                    state=str(m.get("state", "not-loaded")),
                    publisher=str(m.get("publisher", "")),
                    arch=str(m.get("arch", "")),
                    quantization=str(m.get("quantization", "")),
                    max_context_length=m.get("max_context_length"),
                )
            )
        return out

    async def model_details(self) -> dict[str, dict[str, Any]]:
        """GET /api/v1/models — richer per-model data (display_name, size_bytes).

        NOTE on keys: v1 `key` is the BARE model name (no publisher prefix),
        while v0 `id` is `publisher/name`. We therefore index details by the
        last path segment of the id; callers try the full id first, then the
        bare name. v1 duplicates entries per quantization variant — first one
        wins.
        """
        data = await self._get("/api/v1/models")
        models = data.get("models", []) if isinstance(data, dict) else []
        out: dict[str, dict[str, Any]] = {}
        for m in models:
            key = m.get("key")
            if not key:
                continue
            bare = key.split("/")[-1]
            entry = {
                "display_name": m.get("display_name") or bare,
                "size_bytes": m.get("size_bytes"),
                "quantization": m.get("selected_variant") or m.get("quantization"),
                "architecture": m.get("architecture"),
            }
            out.setdefault(bare, entry)
            out.setdefault(key, entry)
        return out

    async def load_model(
        self,
        model_id: str,
        context_length: int | None = None,
        *,
        flash_attention: bool | None = None,
        eval_batch_size: int | None = None,
        num_experts: int | None = None,
        offload_kv_cache_to_gpu: bool | None = None,
    ) -> None:
        """POST /api/v1/models/load with the id in the JSON body.

        NOTE: load is NOT idempotent — the caller must only invoke this for a
        model whose state is "not-loaded" (see coordinator guard).

        Parameters (all optional; omitted fields are NOT sent, so the server
        applies its own defaults):
          * context_length        — int, max tokens considered by the model
          * flash_attention       — bool, llama.cpp engine only
          * eval_batch_size       — int,  llama.cpp engine only
          * num_experts           — int,  MoE models + llama.cpp only
          * offload_kv_cache_to_gpu — bool, llama.cpp engine only
        """
        payload: dict[str, Any] = {"model": model_id}
        if context_length is not None:
            payload["context_length"] = int(context_length)
        if flash_attention is not None:
            payload["flash_attention"] = bool(flash_attention)
        if eval_batch_size is not None:
            payload["eval_batch_size"] = int(eval_batch_size)
        if num_experts is not None:
            payload["num_experts"] = int(num_experts)
        if offload_kv_cache_to_gpu is not None:
            payload["offload_kv_cache_to_gpu"] = bool(offload_kv_cache_to_gpu)
        _LOGGER.debug("Loading model %s (payload=%s)", model_id, payload)
        await self._post("/api/v1/models/load", payload)

    async def unload_model(self, model_id: str) -> None:
        """POST /api/v1/models/unload with the id in the JSON body.

        NOTE: only invoke for a model whose state is "loaded".
        """
        await self._post("/api/v1/models/unload", {"instance_id": model_id})

    async def server_info(self) -> dict[str, Any]:
        """Lightweight probe used by the config flow to validate the URL."""
        data = await self._get("/api/v0/models")
        entries = data.get("data", []) if isinstance(data, dict) else []
        return {"model_count": len(entries)}
