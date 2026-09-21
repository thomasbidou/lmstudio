# LM Studio — Home Assistant integration

Manage **load / unload of models** on a local LM Studio server from Home Assistant.
No chat, no inference — just the lifecycle of your models, as first-class entities.

## What you get

| Entity | Meaning |
|--------|---------|
| `switch.<model>` (one per model) | **ON = loaded** on the LM Studio server, OFF = not loaded. Toggle it to load/unload. |
| `sensor.loaded_models` | Number of models currently loaded |
| `sensor.total_models` | Total models available on the server |
| `sensor.server` | `online` when the server responds |

Services (usable in automations):

| Service | Argument | Effect |
|---------|----------|--------|
| `lmstudio.load_model` | `model: "qwen/qwen3-8b"` | Load (only if currently not loaded) |
| `lmstudio.unload_model` | `model: "qwen/qwen3-8b"` | Unload (only if currently loaded) |
| `lmstudio.refresh` | — | Force a state refresh |

## How it talks to LM Studio

Verified against the live API:

- **State**: `GET /api/v0/models` — each entry has a clean `state: loaded | not-loaded`.
- **Load**: `POST /api/v1/models/load` with `{"model": "<id>"}` in the JSON body.
- **Unload**: `POST /api/v1/models/unload` with `{"instance_id": "<id>"}`.

Pitfalls handled in code:

1. `Content-Type: application/json` set on every POST (without it LM Studio
   answers `Unsupported Media Type` and does nothing);
2. **load is not idempotent** — the integration only calls load when the model
   reports `not-loaded` (and vice-versa for unload);
3. Model ids contain a slash (`publisher/name`) which breaks path-style routes —
   ids are always passed in the JSON body, never in the URL;
4. After every action the state is re-read until it confirms the expected
   value (or 90 s timeout, then logged).

## Install (HACS)

1. HACS → Integrations → ⚙ → *Custom repositories* → add `https://github.com/thomasbidou/lmstudio`.
2. HACS → Integrations → **LM Studio** → Install.
3. Restart Home Assistant.

## Configure

Settings → Devices & Services → **Add integration** → *LM Studio* →

- **Server URL** — e.g. `http://192.168.100.72:1234` (tested before saving);
- **Timeout** (default 10 s), **Refresh interval** (default 60 s);
- **API token** (optional), **Context length on load** (optional — passed as
  `context_length` to `/models/load` when set).

Options can be changed later from the entry's *Settings* (re-tested live).

## Example automation

```yaml
alias: "Load small model in the evening"
trigger:
  - platform: time
    at: "18:00:00"
action:
  - service: lmstudio.load_model
    data:
      model: qwen/qwen3-8b
```

## Notes

- One config entry = one LM Studio server. Multiple servers → multiple entries
  (global services act on the last entry — use the switches for per-server control).
- Models downloaded into LM Studio after setup are picked up automatically on
  the next refresh.
- When the server is unreachable, all entities go `unavailable` (HA stays stable,
  the coordinator keeps retrying).
