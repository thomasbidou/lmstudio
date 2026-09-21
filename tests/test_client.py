"""Unit tests for the LM Studio client (run with pytest, aiohttp mocked)."""

from __future__ import annotations

import sys
import importlib
import importlib.util
from unittest.mock import AsyncMock, MagicMock

import pytest

PKG_PATH = "/home/thomas/dev/lmstudio-ha/custom_components/lmstudio"
_spec = importlib.machinery.ModuleSpec("lmstudio", loader=None, is_package=True)
_spec.submodule_search_locations = [PKG_PATH]
_pkg = importlib.util.module_from_spec(_spec)
_pkg.__path__ = [PKG_PATH]
sys.modules.setdefault("lmstudio", _pkg)

from lmstudio.client import (  # noqa: E402
    LMStudioActionError,
    LMStudioClient,
    LMStudioConnectionError,
    ModelInfo,
)


def make_client() -> LMStudioClient:
    session = MagicMock()
    return LMStudioClient(session, "http://192.168.1.10:1234/", timeout=5, api_token="")


# ------------------------------------------------------------------ parsing
def test_list_models_parses_v0():
    client = make_client()
    client._get = AsyncMock(return_value={
        "data": [
            {"id": "qwen/qwen3-8b", "state": "loaded", "publisher": "qwen",
             "arch": "qwen35", "quantization": "Q4_K_M", "max_context_length": 32768},
            {"id": "llama-3-8b", "state": "not-loaded"},
        ]
    })
    import asyncio
    models = asyncio.run(client.list_models())
    assert len(models) == 2
    assert models[0].is_loaded is True
    assert models[1].is_loaded is False
    assert models[0].name == "qwen3-8b"
    assert models[0].quantization == "Q4_K_M"


def test_model_info_name_fallback():
    m = ModelInfo(id="foo/bar-baz", state="not-loaded")
    assert m.name == "bar-baz"
    m.display_name = "Bar Baz"
    assert m.name == "Bar Baz"


def test_details_indexed_by_bare_name_and_full_key():
    client = make_client()
    client._get = AsyncMock(return_value={"models": [
        {"key": "qwen/qwen3-8b", "display_name": "Qwen3 8B", "size_bytes": 5000},
    ]})
    import asyncio
    d = asyncio.run(client.model_details())
    assert "qwen/qwen3-8b" in d and "qwen3-8b" in d
    assert d["qwen3-8b"]["size_bytes"] == 5000


# ------------------------------------------------------------------ actions
def test_load_posts_id_in_body_with_content_type():
    client = make_client()
    captured = {}

    class FakeResp:
        status = 200

        async def json(self):
            return {"status": "ok"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResp()

    client._session = FakeSession()
    import asyncio
    asyncio.run(client.load_model("qwen/qwen3-8b", context_length=4096))
    assert captured["url"].endswith("/api/v1/models/load")
    assert captured["json"] == {"model": "qwen/qwen3-8b", "context_length": 4096}
    assert captured["headers"]["Content-Type"] == "application/json"
    # id must NOT be in the URL (slash pitfall)
    assert "qwen" not in captured["url"].split("/api/v1")[-1]


def test_unload_posts_instance_id():
    client = make_client()
    captured = {}

    class FakeResp:
        status = 200

        async def json(self):
            return {"status": "ok"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResp()

    client._session = FakeSession()
    import asyncio
    asyncio.run(client.unload_model("qwen/qwen3-8b"))
    assert captured["url"].endswith("/api/v1/models/unload")
    assert captured["json"] == {"instance_id": "qwen/qwen3-8b"}


def test_http_error_raises_action_error():
    import aiohttp

    class FakeResp:
        status = 400

        async def json(self):
            return {"error": "model_load_failed"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            return FakeResp()

    client = make_client()
    client._session = FakeSession()
    import asyncio
    with pytest.raises(LMStudioActionError, match="model_load_failed"):
        asyncio.run(client.load_model("x/y"))


def test_200_with_error_body_raises():
    class FakeResp:
        status = 200

        async def json(self):
            return {"success": False, "error": "insufficient memory"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            return FakeResp()

    client = make_client()
    client._session = FakeSession()
    import asyncio
    with pytest.raises(LMStudioActionError, match="insufficient memory"):
        asyncio.run(client.load_model("x/y"))


def test_connection_error_wrapped():
    import aiohttp

    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            raise aiohttp.ClientError("no route to host")

    client = make_client()
    client._session = FakeSession()
    import asyncio
    with pytest.raises(LMStudioConnectionError):
        asyncio.run(client.list_models())


# ------------------------------------------------------------------ allowlist
def test_parse_local_models_basic():
    from lmstudio.const import parse_local_models
    s = parse_local_models("qwen/qwen3-8b\n  llama-3-8b  \n\nfoo/bar\n")
    assert s == {"qwen/qwen3-8b", "llama-3-8b", "foo/bar"}


def test_parse_local_models_empty_and_none():
    from lmstudio.const import parse_local_models
    assert parse_local_models("") == set()
    assert parse_local_models(None) == set()
    assert parse_local_models("   \n\t\n") == set()


def test_parse_local_models_case_insensitive():
    from lmstudio.const import parse_local_models
    s = parse_local_models("QWEN/QWEN3-8B")
    assert s == {"qwen/qwen3-8b"}


def test_client_load_model_payload_with_params():
    """client.load_model sends ONLY the provided params (typed), never None."""
    from lmstudio.client import LMStudioClient

    sent: dict | None = None

    async def fake_post(path, payload):
        nonlocal sent
        sent = (path, payload)
        return {"status": "loaded"}

    client = LMStudioClient(None, "http://x:1234")
    client._post = fake_post
    import asyncio

    asyncio.run(
        client.load_model(
            "qwen/qwen3-4b",
            8192,
            flash_attention=True,
            eval_batch_size=256,
            num_experts=None,           # omitted -> not sent
            offload_kv_cache_to_gpu=False,
        )
    )
    assert sent is not None
    path, payload = sent
    assert path == "/api/v1/models/load"
    assert payload["model"] == "qwen/qwen3-4b"
    assert payload["context_length"] == 8192
    assert payload["flash_attention"] is True
    assert payload["eval_batch_size"] == 256
    assert "num_experts" not in payload
    assert payload["offload_kv_cache_to_gpu"] is False


def test_client_load_model_defaults_only():
    """client.load_model with no params sends only the model id."""
    from lmstudio.client import LMStudioClient

    sent: dict | None = None

    async def fake_post(path, payload):
        nonlocal sent
        sent = (path, payload)
        return {}

    client = LMStudioClient(None, "http://x:1234")
    client._post = fake_post
    import asyncio

    asyncio.run(client.load_model("qwen/qwen3-4b", None))
    assert sent is not None
    assert sent[1] == {"model": "qwen/qwen3-4b"}


def test_allowlist_filters_models():
    """Simulates the coordinator's _apply_allowlist behaviour end-to-end:
    given a raw model list and an allowlist, only allowed ids survive."""
    from lmstudio.const import parse_local_models

    class _FakeInfo:
        def __init__(self, id_): self.id = id_

    raw = {m.id: _FakeInfo(m.id) for m in [
        _FakeInfo("qwen/qwen3-8b"),
        _FakeInfo("llama-3-8b"),
        _FakeInfo("openai/gpt-oss-120b"),
    ]}
    allowlist = parse_local_models("qwen/qwen3-8b\nllama-3-8b")
    # Empty allowlist = keep all.
    if not allowlist:
        filtered = raw
    else:
        filtered = {mid: info for mid, info in raw.items() if mid.lower() in allowlist}
    assert set(filtered.keys()) == {"qwen/qwen3-8b", "llama-3-8b"}
    # A linked model is correctly dropped.
    assert "openai/gpt-oss-120b" not in filtered


# ------------------------------------------------------------------ dynamic sync
def test_compute_model_sync_add_and_remove():
    """The core of dynamic list behaviour: when a model is deleted on the
    server it must appear in 'removed'; when a new one appears, in 'added'."""
    from lmstudio.const import compute_model_sync

    # known = switches currently in HA; current = what the server reports now.
    known = {"qwen/qwen3-8b", "llama-3-8b", "gemma-7b"}
    current = {"qwen/qwen3-8b", "gemma-7b", "openai/gpt-oss-120b"}

    added, removed = compute_model_sync(known, current)
    assert added == {"openai/gpt-oss-120b"}      # new on server -> create switch
    assert removed == {"llama-3-8b"}             # gone on server -> delete switch


def test_compute_model_sync_no_change():
    from lmstudio.const import compute_model_sync
    added, removed = compute_model_sync({"a", "b"}, {"a", "b"})
    assert added == set()
    assert removed == set()


def test_compute_model_sync_all_removed():
    """Edge case matching the user's report: server now empty of a model that
    HA still shows -> it must be flagged removed."""
    from lmstudio.const import compute_model_sync
    added, removed = compute_model_sync({"qwen/qwen3-8b"}, set())
    assert added == set()
    assert removed == {"qwen/qwen3-8b"}


def test_compute_model_sync_all_added():
    from lmstudio.const import compute_model_sync
    added, removed = compute_model_sync(set(), {"qwen/qwen3-8b"})
    assert added == {"qwen/qwen3-8b"}
    assert removed == set()


def test_no_await_on_sync_ha_methods():
    """Regression: HA's `async_set_updated_data` is a SYNC method (returns None).

    `await`-ing it raises `TypeError: object NoneType can't be awaited` at
    runtime (the model still loads/unloads on the server, then the confirm
    step blows up). This AST scan fails the test if any module awaits a
    known-sync HA helper, catching the bug at import/test time.
    """
    import ast
    import pathlib

    pkg = pathlib.Path(__file__).parent.parent / "custom_components" / "lmstudio"
    # HA helpers that look async by name but are actually plain `def`
    sync_methods = {
        "async_set_updated_data",
        "async_add_listener",
        "async_write_ha_state",
        "async_schedule_ha_state",
    }
    offenders: list[str] = []
    for py in sorted(pkg.glob("*.py")):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Await)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr in sync_methods
            ):
                offenders.append(f"{py.name}:{node.lineno} await {node.value.func.attr}()")
    assert not offenders, "awaited a sync HA helper: " + ", ".join(offenders)
