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

## Lovelace card

The integration ships its own Lovelace card **with the package**
(`lmstudio-model-card`): a scrollable model menu + a single **Load / Unload**
button + a **Chargé / Déchargé** badge + a **Refresh** button. It is copied
into `/homeassistant/www/` automatically at setup — so you never add the
resource manually, and it updates/rolls back with the integration. Add a
`custom: lmstudio-model-card` card to a dashboard and it works out of the box.

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
  `context_length` to `/models/load` when set);
- **Local models only** (optional) — a newline-separated allowlist of model ids
  (`publisher/name`). When non-empty, the integration exposes **only** those
  models: switches, sensors and the Lovelace card ignore everything else. This
  is the intended way to hide models that appear on the server via **LM Link**
  (the HTTP API has no local/linked field — the allowlist is the filter).
  Leave empty to keep every model on the server.

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

- **Dynamic model list** — the list of models mirrors the server at all times:
  a model added to LM Studio gets a switch automatically, and a model **deleted**
  from LM Studio loses its switch (and its card entry) on the next refresh —
  no integration reload needed. The Lovelace card's **Refresh** button forces
  that re-sync immediately (it calls the `lmstudio.refresh` service).
- **Loaded detection** — every switch is ON when its model is loaded on the
  server and OFF when not; the card badge shows **Chargé / Déchargé**.
- **Load / unload** — toggle the switch, or use the services
  `lmstudio.load_model` / `lmstudio.unload_model` in automations.
- **Local models only** (optional) — a newline-separated allowlist of model ids
  to expose only a subset (e.g. to hide models that appear via LM Link). Leave
  empty to keep every model on the server.
- One config entry = one LM Studio server. Multiple servers → multiple entries
  (global services act on the last entry — use the switches for per-server control).
- When the server is unreachable, all entities go `unavailable` (HA stays stable,
  the coordinator keeps retrying).
