"""Translator overlay data: bundles, web-UI strings, resolve, flag."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..catalog import FlagStore
from ..catalog.io import atomic_write_text
from .server import AppState
from ..catalog.io import read_json

__all__ = [
    "WEB_UI_NS",
    "flag_key",
    "resolve_text",
    "save_web_ui_string",
    "translator_bundle",
    "translator_bundle_web_ui",
    "translator_lookup",
    "by_target_index",
    "translator_config",
    "translator_config_web_ui",
    "web_ui_locales_dir",
    "web_ui_overrides_dir",
]

WEB_UI_NS = "__web_ui__"
_LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z][a-z]+)?$")
_WEB_UI_EN: tuple[int, dict[str, str]] | None = None


def web_ui_locales_dir() -> Path:
    return Path(__file__).parent / "locales"


def web_ui_overrides_dir(state_root: Path) -> Path:
    """Per-project overrides for chrome strings (writable; package dir is not)."""
    return Path(state_root) / "web_ui"


def _load_web_ui_en() -> dict[str, str]:
    global _WEB_UI_EN
    path = web_ui_locales_dir() / "en.json"
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = -1
    if _WEB_UI_EN is not None and _WEB_UI_EN[0] == mtime:
        return _WEB_UI_EN[1]
    data = read_json(path)
    parsed = {k: str(v) for k, v in data.items()}
    _WEB_UI_EN = (mtime, parsed)
    return parsed


def _read_locale_json(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data = read_json(path)
    return {k: str(v) for k, v in data.items()}


def _load_web_ui_target(
    locale: str,
    *,
    state_root: Path | None = None,
) -> dict[str, str]:
    if locale == "en":
        return {}
    package = _read_locale_json(web_ui_locales_dir() / f"{locale}.json")
    if state_root is None:
        return package
    overrides = _read_locale_json(web_ui_overrides_dir(state_root) / f"{locale}.json")
    return {**package, **overrides}


def translator_bundle_web_ui(locale: str, *, state_root: Path | None = None) -> dict:
    if not _LOCALE_RE.fullmatch(locale):
        raise ValueError("invalid locale")
    en = _load_web_ui_en()
    target = _load_web_ui_target(locale, state_root=state_root)
    entries: list[dict] = []
    by_target: dict[str, list[dict]] = {}
    for key, src in sorted(en.items()):
        tgt = target.get(key, src) if locale != "en" else src
        entries.append({
            "namespace": WEB_UI_NS,
            "key": key,
            "source": src,
            "target": tgt,
            "note": "",
        })
        if tgt and locale != "en":
            by_target.setdefault(tgt, []).append({"namespace": WEB_UI_NS, "key": key})
    return {
        "mode": "web-ui",
        "sourceLocale": "en",
        "locale": locale,
        "namespace": WEB_UI_NS,
        "entries": entries,
        "byTargetText": by_target,
    }


def translator_bundle(st: AppState, locale: str) -> dict:
    if locale not in st.cfg.targets and locale != st.cfg.source_locale:
        raise ValueError(f"{locale!r} is not a configured target locale")
    by_target = by_target_index(st, locale)
    source_locale = st.cfg.source_locale
    entries: list[dict] = []
    for ns in st.namespaces():
        source = st.catalog.load(source_locale, ns)
        target = st.catalog.load(locale, ns)
        for key, src in sorted(source.items()):
            if st.cfg.is_skipped(ns, key):
                continue
            tgt = target.get(key, "")
            entries.append({
                "namespace": ns,
                "key": key,
                "source": src,
                "target": tgt,
                "note": st.notes.note(ns, key) or "",
            })
    return {
        "mode": "project",
        "sourceLocale": source_locale,
        "locale": locale,
        "entries": entries,
        "byTargetText": by_target,
    }


def by_target_index(st: AppState, locale: str) -> dict[str, list[dict]]:
    """Reverse map target text → [{namespace, key}, …]; cached on AppState."""
    if locale not in st.cfg.targets and locale != st.cfg.source_locale:
        raise ValueError(f"{locale!r} is not a configured target locale")
    if st._resolve_by_target_cache is None:
        st._resolve_by_target_cache = {}
    hit = st._resolve_by_target_cache.get(locale)
    if hit is not None:
        return hit
    source_locale = st.cfg.source_locale
    by_target: dict[str, list[dict]] = {}
    for ns in st.namespaces():
        source = st.catalog.load(source_locale, ns)
        target = st.catalog.load(locale, ns)
        for key in source:
            if st.cfg.is_skipped(ns, key):
                continue
            tgt = target.get(key, "")
            if tgt:
                by_target.setdefault(tgt, []).append({"namespace": ns, "key": key})
    st._resolve_by_target_cache[locale] = by_target
    return by_target


def translator_lookup(
    st: AppState,
    locale: str,
    namespace: str,
    key: str,
) -> dict:
    """Single-key lookup for translator overlay (avoids full-project bundle)."""
    if locale not in st.cfg.targets and locale != st.cfg.source_locale:
        raise ValueError(f"{locale!r} is not a configured target locale")
    source = st.catalog.load(st.cfg.source_locale, namespace)
    if key not in source:
        raise ValueError(f"{key!r} not in namespace {namespace!r}")
    if st.cfg.is_skipped(namespace, key):
        raise ValueError(f"{key!r} is skipped")
    target = st.catalog.load(locale, namespace)
    return {
        "namespace": namespace,
        "key": key,
        "source": source[key],
        "target": target.get(key, ""),
        "note": st.notes.note(namespace, key) or "",
        "sourceLocale": st.cfg.source_locale,
        "locale": locale,
    }


def translator_config(st: AppState) -> dict:
    return {
        "mode": "project",
        "project": st.cfg.name,
        "sourceLocale": st.cfg.source_locale,
        "targets": list(st.cfg.targets),
        "namespaces": st.namespaces(),
    }


def translator_config_web_ui(*, state_root: Path | None = None) -> dict:
    locales_dir = web_ui_locales_dir()
    targets = {f.stem for f in locales_dir.glob("*.json") if f.stem != "en"}
    if state_root is not None:
        overrides = web_ui_overrides_dir(state_root)
        if overrides.is_dir():
            targets.update(f.stem for f in overrides.glob("*.json") if f.stem != "en")
    return {
        "mode": "web-ui",
        "sourceLocale": "en",
        "targets": sorted(targets),
        "namespaces": [WEB_UI_NS],
    }


def save_web_ui_string(
    locale: str,
    key: str,
    value: str,
    *,
    state_root: Path | None = None,
) -> dict:
    if locale == "en":
        return {"ok": False, "error": "English is the source locale; edit en.json in the package"}
    if not _LOCALE_RE.fullmatch(locale):
        return {"ok": False, "error": "invalid locale"}
    en = _load_web_ui_en()
    if key not in en:
        return {"ok": False, "error": f"{key} is not a web UI string key"}
    if state_root is None:
        return {
            "ok": False,
            "error": "state root required to save UI locale overrides",
        }
    out_dir = web_ui_overrides_dir(state_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{locale}.json"
    existing = _read_locale_json(path)
    existing[key] = value
    atomic_write_text(
        path,
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
    )
    return {"ok": True, "value": value, "status": "human"}


def resolve_text(st: AppState | None, locale: str, text: str,
                 *, hint_ns: str = "", hint_key: str = "") -> dict:
    text = text.strip()
    if not text:
        return {"candidates": []}
    if hint_ns and hint_key:
        return {"candidates": [{"namespace": hint_ns, "key": hint_key, "score": 100}]}
    if st is None:
        by_target = translator_bundle_web_ui(locale).get("byTargetText", {})
    else:
        by_target = by_target_index(st, locale)
    exact = by_target.get(text, [])
    if exact:
        return {"candidates": [{**c, "score": 90} for c in exact]}
    candidates: list[dict] = []
    for tgt, refs in by_target.items():
        if tgt and (text in tgt or tgt in text):
            for ref in refs:
                candidates.append({
                    "namespace": ref["namespace"],
                    "key": ref["key"],
                    "score": 50,
                })
    candidates.sort(key=lambda row: row["score"], reverse=True)
    return {"candidates": candidates[:10]}


def flag_key(st: AppState, locale: str, namespace: str, key: str,
             *, reason: str = "flagged from translator overlay") -> dict:
    from ..catalog.mutation_lock import project_mutation_lock

    store = FlagStore(st.cfg.flags_path)
    if not store.path:
        return {"ok": False, "error": "no [state] flags path configured"}
    with project_mutation_lock(st.cfg):
        added = store.append({
            "locale": locale,
            "namespace": namespace,
            "key": key,
            "reason": reason,
        })
    return {"ok": True, "added": added}
