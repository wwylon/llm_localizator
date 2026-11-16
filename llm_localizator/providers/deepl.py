"""DeepL translation API backend.

Requires ``DEEPL_AUTH_KEY`` in the environment. Formality maps from the project
``[prompt] register`` setting (informal → prefer_less, formal → prefer_more).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from ..core.locale_code import base_language
from .base import CompletionRequest, Provider, ProviderError
from ._prompt_utils import extract_sources

__all__ = ["DeepLProvider"]

FREE_URL = "https://api-free.deepl.com/v2/translate"
PRO_URL = "https://api.deepl.com/v2/translate"
DEFAULT_TIMEOUT_S = 120

# DeepL target codes (uppercase). Unknown locales fall back to the base tag.
_LOCALE_MAP = {
    "en": "EN",
    "en-gb": "EN-GB",
    "en-us": "EN-US",
    "pl": "PL",
    "de": "DE",
    "ar": "AR",
    "fr": "FR",
    "es": "ES",
    "it": "IT",
    "pt": "PT-PT",
    "pt-br": "PT-BR",
    "nl": "NL",
    "cs": "CS",
    "ru": "RU",
    "tr": "TR",
    "ja": "JA",
    "zh": "ZH",
}


def _target_lang(locale: str) -> str:
    key = (locale or "").strip().lower()
    if key in _LOCALE_MAP:
        return _LOCALE_MAP[key]
    base = base_language(key)
    return _LOCALE_MAP.get(base, base.upper() or "EN")



class DeepLProvider(Provider):
    kind = "deepl"

    def __init__(
        self,
        auth_key: str | None = None,
        *,
        formality: str = "prefer_less",
        use_free: bool | None = None,
        source_locale: str = "en",
    ) -> None:
        self.auth_key = (auth_key or os.environ.get("DEEPL_AUTH_KEY") or "").strip()
        self.formality = formality
        self.source_locale = source_locale or "en"
        if use_free is None:
            # Free keys typically end with :fx
            use_free = self.auth_key.endswith(":fx")
        self.api_url = FREE_URL if use_free else PRO_URL
        self.last_usage: dict | None = None
        self._billed = 0

    def __repr__(self) -> str:
        return f"DeepLProvider(auth_key='***', formality={self.formality!r})"

    def complete(self, request: CompletionRequest) -> str:
        if not self.auth_key:
            raise ProviderError(
                "DeepL auth key missing — set DEEPL_AUTH_KEY in the environment"
            )
        locale = str(
            request.target_locale
            or request.options.get("target_lang")
            or request.options.get("locale")
            or ""
        )
        target = _target_lang(locale) if locale else "EN"
        src_opt = str(
            request.options.get("source_lang")
            or request.options.get("source_locale")
            or self.source_locale
            or "en"
        )
        # DeepL source languages take no region (EN, PT), unlike targets.
        source_lang = (base_language(src_opt.strip().lower()) or "en").upper()
        sources = request.source_texts or extract_sources(request.prompt, request.schema)
        if not sources:
            raise ProviderError("DeepLProvider could not extract source text from prompt")

        self.last_usage = None
        self._billed = 0
        timeout = request.timeout_s or DEFAULT_TIMEOUT_S
        translations = self._translate_many(
            sources, target, source_lang=source_lang, timeout=timeout,
        )
        self.last_usage = {"billed_characters": self._billed}
        if request.schema is not None:
            return json.dumps(translations, ensure_ascii=False)
        return translations[0]

    def _post(self, pairs: list[tuple[str, str]], timeout: float) -> list[dict]:
        from .http_retry import urlopen_json

        req = urllib.request.Request(
            self.api_url,
            data=urllib.parse.urlencode(pairs).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return urlopen_json(req, timeout, "DeepL").get("translations") or []

    def _translate_many(
        self, texts: list[str], target_lang: str, *, source_lang: str = "EN",
        timeout: float = 120, formality: bool = True,
    ) -> list[str]:
        pairs: list[tuple[str, str]] = [
            ("auth_key", self.auth_key),
            ("source_lang", source_lang),
            ("target_lang", target_lang),
        ]
        if formality:
            pairs.append(("formality", self.formality))
        pairs.extend(("text", text) for text in texts)
        try:
            rows = self._post(pairs, timeout)
        except ProviderError as exc:
            detail = getattr(exc, "http_detail", "") or str(exc)
            if (
                formality and getattr(exc, "http_code", None) == 400
                and "formality" in detail.lower()
            ):
                # The target language does not support formality.
                return self._translate_many(
                    texts, target_lang, source_lang=source_lang,
                    timeout=timeout, formality=False,
                )
            # A bad request will not succeed per item and a failed batch may
            # already be billed; never fan out.
            raise
        if len(rows) != len(texts):
            raise ProviderError(
                f"DeepL returned {len(rows)} translation(s) for {len(texts)} source(s)"
            )
        outs: list[str] = []
        for row, text in zip(rows, texts, strict=True):
            out = str(row.get("text", "")).strip()
            if not out:
                raise ProviderError("DeepL returned an empty translation")
            outs.append(out)
            bc = row.get("billed_characters")
            self._billed += int(bc) if bc is not None else len(text)
        return outs

    def health_check(self) -> bool:
        return bool(self.auth_key)
