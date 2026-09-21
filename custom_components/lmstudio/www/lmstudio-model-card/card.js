/*
 * LM Studio Model Picker — carte Lovelace maison
 * Un menu défilant pour choisir le modèle + un bouton Loader/Unloader.
 * Détecte automatiquement les switch de l'intégration "lmstudio"
 * (attribut "lmstudio_state"), ou prend la liste "entities" du config.
 */
(() => {
  "use strict";
  if (customElements.get("lmstudio-model-card")) return;

  const style = new CSSStyleSheet();
  style.replaceSync(`
    :host {
      display: block;
      padding: 16px;
      background: var(--card-background-color, #fff);
      border-radius: var(--card-border-radius, 12px);
      color: var(--primary-text-color, #111);
    }
    .title { font-size: 1.15em; font-weight: 600; margin-bottom: 12px; }
    .sel {
      width: 100%;
      box-sizing: border-box;
      padding: 10px;
      font-size: 1em;
      border-radius: 8px;
      border: 1px solid var(--divider-color, rgba(0,0,0,.12));
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #111);
      margin-bottom: 12px;
    }
    .row { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
    .badge { font-size: .85em; font-weight: 600; padding: 3px 12px; border-radius: 999px; flex: 0 0 auto; }
    .badge.on { background: rgba(76,175,80,.18); color: #43a047; }
    .badge.off { background: rgba(140,140,140,.18); color: #888; }
    .mid {
      font-size: .8em;
      color: var(--secondary-text-color, #666);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .btn {
      width: 100%;
      padding: 13px;
      font-size: 1.05em;
      font-weight: 600;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      background: var(--primary-color, #03a9f4);
      color: var(--primary-button-text-color, #fff);
    }
    .btn:disabled { opacity: .55; cursor: wait; }
    .refresh {
      width: 100%;
      margin-top: 8px;
      padding: 9px;
      font-size: .9em;
      font-weight: 600;
      border: 1px solid var(--divider-color, rgba(0,0,0,.12));
      border-radius: 8px;
      cursor: pointer;
      background: transparent;
      color: var(--secondary-text-color, #666);
    }
    .refresh:disabled { opacity: .55; cursor: wait; }
    .empty { padding: 20px; text-align: center; color: var(--secondary-text-color, #666); }
    .err { margin-top: 10px; font-size: .85em; color: #e53935; }
  `);

  class LMStudioModelCard extends HTMLElement {
    constructor() {
      super();
      const root = this.attachShadow({ mode: "open" });
      root.adoptedStyleSheets = [style];
    }

    setConfig(cfg) {
      this._config = cfg || { type: "custom:lmstudio-model-card" };
      this._selected = null;
      this._built = false;
      this._render();
    }
    getConfig() {
      return this._config;
    }
    set config(cfg) {
      this.setConfig(cfg);
    }
    get config() {
      return this._config;
    }

    set hass(h) {
      this._hass = h;
      if (this._config) this._render();
    }
    get hass() {
      return this._hass;
    }

    _models() {
      const hass = this._hass;
      if (!hass) return [];
      let ids = (this._config && this._config.entities) || [];
      if (!ids.length) {
        ids = Object.keys(hass.states).filter(
          (id) =>
            id.startsWith("switch.") &&
            hass.states[id].attributes.lmstudio_state !== undefined
        );
      }
      return ids
        .filter((id) => hass.states[id])
        .sort((a, b) =>
          (hass.states[a].attributes.friendly_name || a).localeCompare(
            hass.states[b].attributes.friendly_name || b
          )
        );
    }

    _render() {
      if (!this._hass) return;
      if (this._built) {
        this._update();
        return;
      }
      this._build();
    }

    _build() {
      const root = this.shadowRoot;
      root.innerHTML = "";
      this._built = true;

      const title = document.createElement("div");
      title.className = "title";
      title.textContent = (this._config && this._config.title) || "Modèles LM Studio";
      root.appendChild(title);

      const sel = document.createElement("select");
      sel.className = "sel";
      sel.addEventListener("change", () => {
        this._selected = sel.value;
        this._error = null;
        this._update();
      });
      this._sel = sel;
      root.appendChild(sel);

      const row = document.createElement("div");
      row.className = "row";
      const badge = document.createElement("span");
      badge.className = "badge";
      row.appendChild(badge);
      const mid = document.createElement("span");
      mid.className = "mid";
      row.appendChild(mid);
      this._badge = badge;
      this._mid = mid;
      root.appendChild(row);

      const btn = document.createElement("button");
      btn.className = "btn";
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        const on =
          this._hass.states[this._selected].state === "on";
        btn.disabled = true;
        btn.textContent = "…";
        try {
          await this.hass.callService(
            "switch",
            on ? "turn_off" : "turn_on",
            { entity_id: this._selected }
          );
        } catch (err) {
          this._error = String((err && err.message) || err);
          this._update();
          setTimeout(() => {
            this._error = null;
            this._update();
          }, 5000);
        }
      });
      this._btn = btn;
      root.appendChild(btn);

      const refresh = document.createElement("button");
      refresh.className = "refresh";
      refresh.textContent = "↻ Actualiser la liste";
      refresh.addEventListener("click", async (ev) => {
        ev.preventDefault();
        refresh.disabled = true;
        refresh.textContent = "…";
        try {
          // Force the integration to re-read the server. The coordinator then
          // reconciles the switch set (adds new / removes gone models) and the
          // card list below updates on the next hass state change.
          await this.hass.callService("lmstudio", "refresh", {});
        } catch (err) {
          this._error = String((err && err.message) || err);
          this._update();
          setTimeout(() => {
            this._error = null;
            this._update();
          }, 5000);
        } finally {
          refresh.disabled = false;
          refresh.textContent = "↻ Actualiser la liste";
        }
      });
      this._refreshBtn = refresh;
      root.appendChild(refresh);

      const err = document.createElement("div");
      err.className = "err";
      this._errEl = err;
      root.appendChild(err);

      this._update();
    }

    _update() {
      const hass = this._hass;
      const models = this._models();

      // Liste des modèles — ne toucher au <select> que si nécessaire
      // (nombre différent OU au moins un id différent : gère aussi le cas où
      // un modèle est remplacé par un autre, même cardinalité).
      const currentOptions = Array.from(this._sel.options).map((o) => o.value);
      const needRebuild =
        models.length !== currentOptions.length ||
        models.some((m) => !currentOptions.includes(m));
      if (needRebuild) {
        this._sel.innerHTML = "";
        for (const id of models) {
          const o = document.createElement("option");
          o.value = id;
          o.textContent = hass.states[id].attributes.friendly_name || id;
          this._sel.appendChild(o);
        }
      }
      if (!this._selected || !models.includes(this._selected)) {
        this._selected = models[0] || null;
      }
      if (this._selected && this._sel.value !== this._selected) {
        this._sel.value = this._selected;
      }

      if (!this._selected) {
        this._badge.className = "badge off";
        this._badge.textContent = "Aucun modèle";
        this._mid.textContent = "";
        this._btn.disabled = true;
        this._btn.textContent = "Loader";
        return;
      }

      const state = hass.states[this._selected];
      const on = state && state.state === "on";
      this._badge.className = "badge " + (on ? "on" : "off");
      this._badge.textContent = on ? "Chargé" : "Déchargé";

      let midText = (state.attributes.model_id || this._selected) + "";
      if (state.attributes.quantization)
        midText += " · " + state.attributes.quantization;
      this._mid.textContent = midText;

      this._btn.disabled = false;
      this._btn.textContent = on ? "Unloader" : "Loader";

      this._errEl.textContent = this._error || "";
    }

    getCardSize() {
      return 6;
    }

    static getConfigElement() {
      return document.createElement("lmstudio-model-card-editor");
    }
  }

  class LMStudioModelCardEditor extends HTMLElement {
    constructor() {
      super();
      const root = this.attachShadow({ mode: "open" });
      root.adoptedStyleSheets = [style];
    }
    setConfig(cfg) {
      this._config = cfg || { type: "custom:lmstudio-model-card" };
      this._render();
    }
    get config() {
      return this._config;
    }
    _fire() {
      this.dispatchEvent(
        new CustomEvent("config-changed", { detail: { config: this._config } })
      );
    }
    _render() {
      const root = this.shadowRoot;
      root.innerHTML = "";
      const wrap = document.createElement("div");
      const label = document.createElement("div");
      label.className = "mid";
      label.textContent = "Titre (optionnel)";
      wrap.appendChild(label);
      const input = document.createElement("input");
      input.value = this._config.title || "";
      input.placeholder = "Modèles LM Studio";
      input.style.cssText =
        "width:100%;box-sizing:border-box;padding:8px 10px;font-size:1em;border-radius:8px;border:1px solid rgba(128,128,128,.4);margin-bottom:8px;";
      input.addEventListener("input", () => {
        this._config = { ...this._config, title: input.value };
        this._fire();
      });
      wrap.appendChild(input);
      const help = document.createElement("div");
      help.className = "mid";
      help.textContent =
        "Optionnel : \"entities\" (liste de switch) pour forcer la liste. Par défaut, tous les switch de l'intégration LM Studio sont détectés.";
      wrap.appendChild(help);
      root.appendChild(wrap);
    }
  }

  customElements.define("lmstudio-model-card", LMStudioModelCard);
  customElements.define("lmstudio-model-card-editor", LMStudioModelCardEditor);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "lmstudio-model-card",
    name: "LM Studio Model Picker",
  });
})();
