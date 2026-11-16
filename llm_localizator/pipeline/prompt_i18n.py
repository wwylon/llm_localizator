"""Translate the project/model instruction block into the target language (ADR-60).

The text is translated once per (locale, text hash) and cached under
``<state>/prompt-i18n/<locale>.json``. Prompt building only reads the cache
(:func:`cached_translation`); a run fills it first (:func:`ensure_localized`).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..catalog.io import atomic_write_text
from ..core.cldr import language_name
from ..providers import complete_for
from ..providers.base import CompletionRequest, ProviderError

__all__ = ["cached_translation", "ensure_localized"]


def _path(cfg, locale: str) -> Path | None:
    if cfg.state_dir is None:
        return None
    return Path(cfg.state_dir) / "prompt-i18n" / f"{locale}.json"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _load(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def cached_translation(cfg, locale: str, text: str) -> str:
    """Cached translation of ``text`` for ``locale``, or ``""`` when absent."""
    return str(_load(_path(cfg, locale)).get(_digest(text), ""))


def ensure_localized(cfg, provider, locale: str, model: str, *, report=print) -> None:
    """Fill the cache for this locale's instruction block when it is missing."""
    text = cfg.prompt_extras_for(locale, model, raw=True)
    path = _path(cfg, locale)
    if not text or path is None or cached_translation(cfg, locale, text):
        return
    language = language_name(locale)
    prompt = (
        f"Translate these translator instructions from English to {language}. "
        "Keep every {placeholder}, number and proper noun unchanged. "
        "Output ONLY the translated text, one instruction per line, no commentary.\n\n"
        f"{text}"
    )
    try:
        out = complete_for(cfg, provider, locale, CompletionRequest(
            prompt=prompt, model=model, timeout_s=cfg.provider.timeout_single_s,
            options={"target_lang": locale, "locale": locale},
            source_texts=[text], target_locale=locale,
        ))
    except ProviderError as exc:
        report(f"prompt localization skipped for {locale}: {exc}")
        return
    out = (out or "").strip()
    if not out:
        return
    cache = _load(path)
    cache[_digest(text)] = out
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(cache, ensure_ascii=False, indent=2))
