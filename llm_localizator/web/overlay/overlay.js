/**
 * llm-localizator translator overlay.
 * Enable translator mode, then hold CTRL to preview English at the cursor;
 * CTRL+click to edit.
 *
 * Boot config (set before loading this script when injecting dynamically):
 *   window.__LLM_OVERLAY_BOOT__ = { mode: "web-ui", project: "...", locale: "pl",
 *                                   api: "http://127.0.0.1:8770", flatNs: "" }
 * Or data-* attributes when loaded via a static <script> tag (data-flat-ns, …).
 *
 * flatNs: catalogue namespace for flat ``data-i18n="key"`` tags. Unset, they
 * are llm-localizator's own web-UI strings (``__web_ui__``); a consumer with a
 * flat catalogue sets it (usually "") so its keys bind to its own catalogue.
 * Cross-origin saves send ``X-LLM-Token``: on the first rejected save the
 * overlay asks for the token printed by ``llm-localizator web`` and keeps it in
 * this tab's sessionStorage only (never in page source).
 */
(function () {
  "use strict";

  const script = document.currentScript;
  const boot = window.__LLM_OVERLAY_BOOT__ || {};
  const mode = boot.mode || (script && script.dataset.mode) || "project";
  const staticProject = boot.project || (script && script.dataset.project) || "";
  const apiBase = boot.api || (script && script.dataset.api) || "";
  const WEB_UI_NS = "__web_ui__";
  const flatNs = "flatNs" in boot ? boot.flatNs
    : (script && script.hasAttribute("data-flat-ns") ? script.dataset.flatNs || "" : null);
  const TOKEN_KEY = "llm_overlay_token";
  const RESOLVE_DEBOUNCE_MS = 150;

  const STORAGE_KEY = "llm_translator_mode";
  let active = localStorage.getItem(STORAGE_KEY) === "1";
  let ctrlDown = false;
  let tipEl = null;
  let chip = null;
  let modalEl = null;
  let hoverEl = null;
  let currentHit = null;
  let lastTipPos = null;
  let resolveGen = 0;
  let resolveTimer = null;
  let bundleLoadPromise = null;
  let lastMouse = { x: 0, y: 0 };
  let tipGen = 0;
  const pendingLookups = new Map();

  const entryIndex = new Map();
  const reverseIndex = new Map();

  function apiUrl(path) {
    return (apiBase || "") + path;
  }

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function storedToken() {
    try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
  }

  async function fetchJson(path, opts) {
    const base = opts || {};
    const write = (base.method || "GET").toUpperCase() !== "GET";
    const send = () => {
      const headers = Object.assign({}, base.headers || {});
      const token = storedToken();
      if (write && token) headers["X-LLM-Token"] = token;
      return fetch(apiUrl(path), Object.assign({}, base, { headers }));
    };
    let r = await send();
    let data = await r.json().catch(() => ({}));
    const authFailure = (r.status === 401 || r.status === 403)
      && !/overlay_edit/.test(String(data.error || ""));
    if (write && authFailure && apiBase && !storedToken()) {
      const token = window.prompt(
        "llm-localizator: paste the web token printed by `llm-localizator web` (kept for this tab only)",
      );
      if (token && token.trim()) {
        try { sessionStorage.setItem(TOKEN_KEY, token.trim()); } catch (e) { /* private mode */ }
        r = await send();
        data = await r.json().catch(() => ({}));
      }
    }
    if (!r.ok) throw new Error(data.error || r.statusText);
    return data;
  }

  function bridge() {
    return window.__LLM_TRANSLATOR__ || {};
  }

  function uiLocale() {
    const b = bridge();
    if (typeof b.locale === "function") return b.locale();
    return boot.locale || (script && script.dataset.locale) || document.documentElement.lang || "en";
  }

  function catalogLocale() {
    const b = bridge();
    if (typeof b.catalogLocale === "function") {
      const loc = b.catalogLocale();
      if (loc) return loc;
    }
    return uiLocale();
  }

  function currentProject() {
    const b = bridge();
    if (typeof b.project === "function") return b.project();
    return staticProject;
  }

  function normalizeText(s) {
    return String(s).normalize("NFC").replace(/\s+/g, " ").trim();
  }

  function indexEntries(entries) {
    (entries || []).forEach((e) => {
      entryIndex.set(e.namespace + "\0" + e.key, e);
    });
  }

  function indexReverseFromBundle(bundle) {
    const byTarget = bundle.byTargetText || {};
    Object.keys(byTarget).forEach((text) => {
      const norm = normalizeText(text);
      if (!norm) return;
      const existing = reverseIndex.get(norm) || [];
      (byTarget[text] || []).forEach((ref) => {
        const dup = existing.some((e) => e.ns === ref.namespace && e.key === ref.key);
        if (!dup) existing.push({ ns: ref.namespace, key: ref.key });
      });
      if (existing.length) reverseIndex.set(norm, existing);
    });
  }

  async function loadWebUiBundle() {
    const uiLoc = uiLocale();
    if (bundleLoadPromise) return bundleLoadPromise;
    bundleLoadPromise = fetchJson(
      "/api/translator-bundle?mode=web-ui&locale=" + encodeURIComponent(uiLoc)
    )
      .then((bundle) => {
        indexEntries(bundle.entries);
        indexReverseFromBundle(bundle);
      })
      .catch((e) => {
        console.warn("llm translator overlay: web-ui bundle load failed", e);
      })
      .finally(() => {
        bundleLoadPromise = null;
      });
    return bundleLoadPromise;
  }

  async function lookupEntryAsync(ns, key) {
    const cacheKey = ns + "\0" + key;
    if (entryIndex.has(cacheKey)) {
      return entryIndex.get(cacheKey);
    }
    if (pendingLookups.has(cacheKey)) {
      return pendingLookups.get(cacheKey);
    }
    const project = currentProject() || staticProject;
    const locale = project ? catalogLocale() : uiLocale();
    const params = new URLSearchParams({
      locale,
      namespace: ns,
      key,
    });
    if (project) params.set("project", project);
    const promise = fetchJson("/api/translator-lookup?" + params)
      .then((entry) => {
        entryIndex.set(cacheKey, entry);
        return entry;
      })
      .catch(() => null)
      .finally(() => {
        pendingLookups.delete(cacheKey);
      });
    pendingLookups.set(cacheKey, promise);
    return promise;
  }

  function formatLabel(ns, key) {
    if (ns === WEB_UI_NS) return key;
    return ns ? ns + "." + key : key;
  }

  function isOverlayNode(el) {
    return el && el.closest && el.closest(".llm-overlay-backdrop, .llm-translator-chip, .llm-tip");
  }

  function isExempt(target) {
    return target && target.closest && (
      target.closest(".llm-translator-chip") ||
      target.closest(".llm-overlay-backdrop")
    );
  }

  function readBindingFromEl(el) {
    if (!el || !el.closest) return null;
    const llm = el.closest("[data-llm-key]");
    if (llm) {
      return { el: llm, ns: llm.dataset.llmNs || "", key: llm.dataset.llmKey || "" };
    }
    const i18nKey = el.closest("[data-i18n-key]");
    if (i18nKey) {
      const v = i18nKey.getAttribute("data-i18n-key") || "";
      const dot = v.indexOf(".");
      const ns = dot >= 0 ? v.slice(0, dot) : "";
      const key = dot >= 0 ? v.slice(dot + 1) : v;
      return { el: i18nKey, ns, key };
    }
    const flat = el.closest("[data-i18n]");
    if (flat && flat.dataset.i18n) {
      return { el: flat, ns: flatNs != null ? flatNs : WEB_UI_NS, key: flat.dataset.i18n };
    }
    return null;
  }

  function rowContextBinding(el) {
    const row = el.closest("tr");
    if (!row) return null;
    const tagged = row.querySelector("[data-llm-key]");
    if (tagged) {
      return {
        el: tagged,
        ns: tagged.dataset.llmNs || "",
        key: tagged.dataset.llmKey || "",
      };
    }
    const ta = row.querySelector("textarea[data-key]");
    if (ta) {
      return { el: ta, ns: ta.dataset.ns || "", key: ta.dataset.key || "" };
    }
    return null;
  }

  function extractText(el) {
    if (!el) return "";
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
      return normalizeText(el.value || "");
    }
    const t = el.innerText || el.textContent || "";
    return normalizeText(t);
  }

  function elementsStackAt(x, y) {
    /* pointer-events:none (if ever re-added) would empty the hit stack — lift lock briefly. */
    const locked = document.body.classList.contains("llm-translate-ctrl");
    if (locked) document.body.classList.remove("llm-translate-ctrl");
    const stack = document.elementsFromPoint(x, y);
    if (locked) document.body.classList.add("llm-translate-ctrl");
    return stack;
  }

  function resolveAtPoint(x, y) {
    const stack = elementsStackAt(x, y);
    let anchorEl = null;

    for (let i = 0; i < stack.length; i++) {
      const el = stack[i];
      if (isOverlayNode(el)) continue;
      const bound = readBindingFromEl(el);
      if (bound && bound.key) return { ...bound, ambiguous: false };
      if (!anchorEl) anchorEl = el;
    }

    if (anchorEl) {
      const row = rowContextBinding(anchorEl);
      if (row && row.key) return { ...row, ambiguous: false };
    }

    for (let i = 0; i < stack.length; i++) {
      const el = stack[i];
      if (isOverlayNode(el)) continue;
      const text = extractText(el);
      if (!text || text.length > 500) continue;
      const cands = reverseIndex.get(text);
      if (cands && cands.length === 1) {
        return { el, ns: cands[0].ns, key: cands[0].key, ambiguous: false };
      }
      if (cands && cands.length > 1) {
        return { el, ns: "", key: "", ambiguous: true, candidates: cands };
      }
      return { el, ns: "", key: "", ambiguous: false, pendingText: text };
    }
    return null;
  }

  function sameHit(a, b) {
    if (!a && !b) return true;
    if (!a || !b) return false;
    return a.el === b.el &&
      a.ns === b.ns &&
      a.key === b.key &&
      !!a.ambiguous === !!b.ambiguous &&
      (a.pendingText || "") === (b.pendingText || "");
  }

  function cancelResolve() {
    clearTimeout(resolveTimer);
    resolveTimer = null;
  }

  function scheduleResolve(hit, x, y) {
    cancelResolve();
    const text = hit.pendingText;
    if (!text) return;
    const gen = ++resolveGen;
    resolveTimer = setTimeout(async () => {
      try {
        const project = currentProject();
        const body = {
          text,
          locale: project ? catalogLocale() : uiLocale(),
          mode: project ? "project" : "web-ui",
        };
        if (project) body.project = project;
        const r = await fetchJson("/api/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (gen !== resolveGen || !ctrlDown) return;
        const cands = (r.candidates || []).map((c) => ({
          ns: c.namespace,
          key: c.key,
        }));
        if (!cands.length) return;
        let resolved;
        if (cands.length === 1) {
          resolved = { el: hit.el, ns: cands[0].ns, key: cands[0].key, ambiguous: false };
        } else {
          resolved = {
            el: hit.el,
            ns: "",
            key: "",
            ambiguous: true,
            candidates: cands.slice(0, 3),
          };
        }
        currentHit = resolved;
        showTipForHit(x, y, resolved);
      } catch (e) {
        /* ignore resolve errors */
      }
    }, RESOLVE_DEBOUNCE_MS);
  }

  function ensureChip() {
    if (chip) return chip;
    chip = document.createElement("button");
    chip.type = "button";
    chip.className = "llm-translator-chip";
    chip.textContent = "Translator mode";
    chip.title = "Turn on, then hold CTRL over text for English · CTRL+click to edit";
    chip.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      setActive(!active);
    });
    document.body.appendChild(chip);
    return chip;
  }

  function setActive(on) {
    active = !!on;
    localStorage.setItem(STORAGE_KEY, active ? "1" : "0");
    document.body.classList.toggle("llm-translator-active", active);
    const c = ensureChip();
    c.classList.toggle("on", active);
    c.textContent = active ? "Translator mode ON" : "Translator mode";
    if (!active) {
      setCtrl(false);
    } else {
      loadWebUiBundle().catch(() => {});
    }
  }

  function refreshHitAt(x, y) {
    if (!ctrlDown || !active) return;
    const hit = resolveAtPoint(x, y);
    if (!hit) {
      cancelResolve();
      currentHit = null;
      clearTip();
      return;
    }
    currentHit = hit;
    showTipForHit(x, y, hit);
  }

  function setCtrl(down) {
    down = !!down && active;
    if (down === ctrlDown) return;
    ctrlDown = down;
    document.body.classList.toggle("llm-translate-ctrl", down);
    if (!down) {
      cancelResolve();
      resolveGen++;
      currentHit = null;
      clearTip();
    } else if (lastMouse.x || lastMouse.y) {
      refreshHitAt(lastMouse.x, lastMouse.y);
    }
  }

  /** Prefer event.ctrlKey — more reliable than keydown alone (esp. after focus changes). */
  function syncCtrlFromEvent(e) {
    setCtrl(active && !!(e.ctrlKey || e.metaKey));
    return ctrlDown;
  }

  function ensureTip() {
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.className = "llm-tip";
      tipEl.style.display = "none";
      document.body.appendChild(tipEl);
    }
    return tipEl;
  }

  function clearTip() {
    if (tipEl) tipEl.style.display = "none";
    if (hoverEl) {
      hoverEl.classList.remove("llm-highlight");
      hoverEl = null;
    }
    lastTipPos = null;
  }

  function setHighlight(el) {
    if (hoverEl && hoverEl !== el) hoverEl.classList.remove("llm-highlight");
    hoverEl = el;
    if (el) el.classList.add("llm-highlight");
  }

  async function showTipForHit(x, y, hit) {
    if (!hit || !hit.el) {
      clearTip();
      return;
    }

    const gen = ++tipGen;
    const tip = ensureTip();

    if (hit.ambiguous && hit.candidates && hit.candidates.length) {
      setHighlight(hit.el);
      const lines = [];
      for (const c of hit.candidates) {
        const entry = await lookupEntryAsync(c.ns, c.key);
        if (gen !== tipGen || !ctrlDown) return;
        const src = entry && entry.source ? entry.source : "?";
        lines.push(esc(formatLabel(c.ns, c.key)) + " — " + esc(src));
      }
      tip.innerHTML =
        '<span class="llm-tip-key">Multiple matches</span>' +
        '<span class="llm-tip-text">' + lines.join("<br>") + "</span>";
      tip.style.display = "block";
      positionTip(tip, x, y);
      return;
    }

    if (hit.pendingText && !hit.key) {
      setHighlight(hit.el);
      tip.innerHTML =
        '<span class="llm-tip-key">' + esc(hit.pendingText.slice(0, 80)) + "</span>" +
        '<span class="llm-tip-text">…</span>';
      tip.style.display = "block";
      positionTip(tip, x, y);
      scheduleResolve(hit, x, y);
      return;
    }

    cancelResolve();
    const entry = hit.key ? await lookupEntryAsync(hit.ns, hit.key) : null;
    if (gen !== tipGen || !ctrlDown) return;
    const source = entry && entry.source;
    setHighlight(hit.el);

    if (!source) {
      tip.innerHTML =
        '<span class="llm-tip-key">' + esc(formatLabel(hit.ns, hit.key)) + "</span>" +
        '<span class="llm-tip-text">(no English found)</span>';
    } else {
      tip.innerHTML =
        '<span class="llm-tip-key">' + esc(formatLabel(hit.ns, hit.key)) + "</span>" +
        '<span class="llm-tip-text">' + esc(source) + "</span>";
    }
    tip.style.display = "block";
    positionTip(tip, x, y);
  }

  function positionTip(tip, x, y) {
    const pad = 14;
    tip.style.left = "0";
    tip.style.top = "0";
    const rect = tip.getBoundingClientRect();
    let left = x + pad;
    let top = y + pad;
    if (left + rect.width > window.innerWidth - 8) left = x - rect.width - pad;
    if (top + rect.height > window.innerHeight - 8) top = y - rect.height - pad;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
    lastTipPos = { x, y };
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function closeModal() {
    if (modalEl) {
      modalEl.remove();
      modalEl = null;
    }
  }

  function isProjectEntry(ns) {
    // "" is a real namespace when the consumer configured flatNs (flat catalogue).
    return ns !== WEB_UI_NS && (Boolean(ns) || flatNs === "");
  }

  async function openModalForHit(hit) {
    const ns = hit.ns || "";
    const key = hit.key;
    if (!key) return;

    let entry = await lookupEntryAsync(ns, key);
    const el = hit.el;
    if (!entry) {
      entry = {
        namespace: ns,
        key,
        source: "",
        target: (el && el.value != null ? el.value : (el && el.textContent || "")).trim(),
      };
    }

    closeModal();
    const projectEntry = isProjectEntry(ns);
    const locale = projectEntry ? catalogLocale() : uiLocale();
    const project = currentProject();

    const backdrop = document.createElement("div");
    backdrop.className = "llm-overlay-backdrop";
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeModal();
    });

    const modal = document.createElement("div");
    modal.className = "llm-overlay-modal";
    const label = formatLabel(ns, key);
    modal.innerHTML =
      "<h3>" + esc(label) + "</h3>" +
      '<label>English</label><div class="llm-readonly" id="llm-m-source"></div>' +
      '<label>Translation (' + esc(locale) + ")</label>" +
      '<textarea id="llm-m-value"></textarea>' +
      '<div class="llm-overlay-errors" id="llm-m-errors"></div>' +
      '<div class="llm-overlay-actions">' +
      '<button type="button" class="llm-primary" id="llm-m-save">Save</button>' +
      '<button type="button" id="llm-m-cancel">Cancel</button>' +
      (projectEntry ? '<button type="button" id="llm-m-flag">Flag</button>' : "") +
      "</div>";

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    modalEl = backdrop;

    const sourceEl = qs("#llm-m-source", modal);
    const valueEl = qs("#llm-m-value", modal);
    const errorsEl = qs("#llm-m-errors", modal);
    sourceEl.textContent = entry.source || "(missing source)";
    valueEl.value = entry.target || "";
    valueEl.focus();

    qs("#llm-m-cancel", modal).addEventListener("click", closeModal);

    async function validate() {
      errorsEl.textContent = "";
      if (!projectEntry) return { ok: true };
      try {
        const r = await fetchJson("/api/validate-key", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project,
            locale,
            namespace: ns,
            key,
            value: valueEl.value,
          }),
        });
        if (!r.ok) {
          const msgs = (r.errors || []).map((e) => e.message).join("; ");
          errorsEl.textContent = msgs || r.error || "validation failed";
        }
        return r;
      } catch (e) {
        errorsEl.textContent = e.message;
        return { ok: false };
      }
    }

    qs("#llm-m-save", modal).addEventListener("click", async () => {
      if (!projectEntry && locale === "en") {
        errorsEl.textContent = "Switch UI language away from English to edit UI strings.";
        return;
      }
      const v = await validate();
      if (!v.ok) return;
      try {
        let result;
        if (projectEntry) {
          result = await fetchJson("/api/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              project,
              locale,
              namespace: ns,
              key,
              value: valueEl.value,
            }),
          });
        } else {
          result = await fetchJson("/api/save-ui-locale", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ locale, key, value: valueEl.value }),
          });
        }
        if (!result.ok) {
          errorsEl.textContent = result.error || "save failed";
          return;
        }
        entry.target = valueEl.value;
        entryIndex.set(ns + "\0" + key, entry);
        const b = bridge();
        if (typeof b.applyTranslation === "function") {
          b.applyTranslation({ namespace: ns, key, value: valueEl.value });
        }
        if (projectEntry && typeof b.onCatalogSaved === "function") {
          b.onCatalogSaved({ namespace: ns, key, value: valueEl.value });
        }
        closeModal();
      } catch (e) {
        errorsEl.textContent = e.message;
      }
    });

    const flagBtn = qs("#llm-m-flag", modal);
    if (flagBtn) {
      flagBtn.addEventListener("click", async () => {
        try {
          await fetchJson("/api/flag", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project, locale, namespace: ns, key }),
          });
          errorsEl.textContent = "Flagged for improve.";
        } catch (e) {
          errorsEl.textContent = e.message;
        }
      });
    }
  }

  function onMouseMove(e) {
    lastMouse = { x: e.clientX, y: e.clientY };
    if (!active) return;
    if (!syncCtrlFromEvent(e)) return;
    const hit = resolveAtPoint(e.clientX, e.clientY);
    if (!hit) {
      cancelResolve();
      currentHit = null;
      clearTip();
      return;
    }
    if (sameHit(currentHit, hit) && lastTipPos) {
      const tip = ensureTip();
      if (tip.style.display === "block") positionTip(tip, e.clientX, e.clientY);
      return;
    }
    currentHit = hit;
    showTipForHit(e.clientX, e.clientY, hit);
  }

  function onMouseUp(e) {
    if (!active || !(e.ctrlKey || e.metaKey)) return;
    if (isExempt(e.target)) return;
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
    if (!currentHit || currentHit.ambiguous || !currentHit.key) return;
    openModalForHit(currentHit);
  }

  function guardInteraction(e) {
    if (!active || !(e.ctrlKey || e.metaKey)) return;
    if (isExempt(e.target)) return;
    if (e.type === "focusin") {
      e.preventDefault();
      if (e.target && e.target.blur) e.target.blur();
      return;
    }
    /* Do not preventDefault on mousedown/mouseup — that suppresses click and our mouseup handler. */
    if (e.type === "mousedown" || e.type === "mouseup") {
      e.stopPropagation();
      return;
    }
    e.preventDefault();
    e.stopPropagation();
  }

  function onKeyDown(e) {
    if ((e.key === "Control" || e.key === "Meta") && active) {
      setCtrl(true);
    }
    if (e.key === "Escape") {
      closeModal();
      setCtrl(false);
    }
  }

  function onKeyUp(e) {
    if (e.key === "Control" || e.key === "Meta") {
      setCtrl(false);
    }
    if (active && !e.ctrlKey && !e.metaKey) setCtrl(false);
  }

  function onBlur() {
    setCtrl(false);
  }

  async function init() {
    ensureChip();
    setActive(active);

    document.addEventListener("mousemove", onMouseMove, true);
    document.addEventListener("mouseup", onMouseUp, true);
    document.addEventListener("click", guardInteraction, true);
    document.addEventListener("mousedown", guardInteraction, true);
    document.addEventListener("dblclick", guardInteraction, true);
    document.addEventListener("contextmenu", guardInteraction, true);
    document.addEventListener("dragstart", guardInteraction, true);
    document.addEventListener("focusin", guardInteraction, true);
    document.addEventListener("wheel", guardInteraction, { capture: true, passive: false });
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("keyup", onKeyUp, true);
    window.addEventListener("blur", onBlur);

    window.LlmTranslatorOverlay = {
      reload: () => {
        entryIndex.clear();
        reverseIndex.clear();
        pendingLookups.clear();
        loadWebUiBundle().catch(() => {});
      },
      setActive,
      tagElement(el, ns, key) {
        el.dataset.llmNs = ns;
        el.dataset.llmKey = key;
      },
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
