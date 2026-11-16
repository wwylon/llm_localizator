"""The ``[qa]`` block: how the QA crawl reaches a consumer's UI (plan Part C, C7; ADR-119).

The crawl itself (Playwright) lives in ``experiments/hardcoded_visible/crawl.py``
(ADR-27). The package only parses and validates where to go and how a page is put
into a locale, so the CLI, ``doctor`` and ``hardcoded-hunt`` share one reading.

```toml
[qa]
start = ["npm", "run", "dev"]   # optional; run in the project root
base_url = "http://127.0.0.1:7474"
pages = ["/", "/#search"]
locale_mode = "query"        # query | path | storage
query_param = "lang"         # query mode
storage_key = "app_lang"     # storage mode
qa_locale = "en-XX"
layout_locales = ["ar", "zh"]
[qa.clicks]
"/" = ["#tab-threads", "#tab-knowledge"]
[qa.wait_for]                 # optional: a selector that means "rendered" (B2, ADR-133)
"/" = "#results li"
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .config import ConfigError

__all__ = ["QaConfig", "parse_qa", "LOCALE_MODES", "QA_KEYS"]

LOCALE_MODES = ("query", "path", "storage")
QA_KEYS = frozenset({
    "start", "base_url", "pages", "locale_mode", "query_param", "storage_key",
    "clicks", "wait_for", "qa_locale", "layout_locales", "ready_timeout",
})


@dataclass
class QaConfig:
    base_url: str
    pages: list[str] = field(default_factory=lambda: ["/"])
    start: list[str] = field(default_factory=list)
    locale_mode: str = "query"
    query_param: str = "lang"
    storage_key: str = ""
    clicks: dict[str, list[str]] = field(default_factory=dict)
    wait_for: dict[str, str] = field(default_factory=dict)
    qa_locale: str = "en-XX"
    layout_locales: list[str] = field(default_factory=list)
    ready_timeout: float = 60.0

    def as_dict(self) -> dict:
        return {
            "base_url": self.base_url, "pages": list(self.pages), "start": list(self.start),
            "locale_mode": self.locale_mode, "query_param": self.query_param,
            "storage_key": self.storage_key,
            "clicks": {k: list(v) for k, v in self.clicks.items()},
            "wait_for": dict(self.wait_for),
            "qa_locale": self.qa_locale, "layout_locales": list(self.layout_locales),
            "ready_timeout": self.ready_timeout,
        }


def _str_list(value, what: str, path: Path) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"{path}: [qa] {what} must be an array of non-empty strings")
    return [v.strip() for v in value]


def parse_qa(raw, path: Path, *, project: str, locales: list[str]) -> QaConfig | None:
    """Validate ``[qa]``; ``None`` when the section is absent."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: [qa] must be a table")
    unknown = set(raw) - QA_KEYS
    if unknown:
        raise ConfigError(f"{path}: unknown [qa] field(s): {', '.join(sorted(unknown))}")
    base_url = str(raw.get("base_url") or "").strip().rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ConfigError(f"{path}: [qa] base_url must be an http(s) URL, got {base_url!r}")
    mode = str(raw.get("locale_mode", "query")).strip()
    if mode not in LOCALE_MODES:
        raise ConfigError(
            f"{path}: [qa] locale_mode must be one of {', '.join(LOCALE_MODES)}, got {mode!r}")
    pages = _str_list(raw.get("pages", ["/"]), "pages", path)
    for page in pages:
        if "://" in page:
            raise ConfigError(f"{path}: [qa] pages are paths under base_url, got {page!r}")
    start = _str_list(raw["start"], "start", path) if raw.get("start") else []
    storage_key = str(raw.get("storage_key") or "").strip()
    if mode == "storage" and not storage_key:
        raise ConfigError(f"{path}: [qa] storage_key is required with locale_mode = \"storage\"")
    clicks_raw = raw.get("clicks", {}) or {}
    if not isinstance(clicks_raw, dict):
        raise ConfigError(f"{path}: [qa] clicks must be a table of page -> selectors")
    clicks: dict[str, list[str]] = {}
    for page, selectors in clicks_raw.items():
        if page not in pages:
            raise ConfigError(f"{path}: [qa.clicks] page {page!r} is not listed in [qa] pages")
        clicks[page] = _str_list(selectors, f"clicks.{page!r}", path)
    wait_raw = raw.get("wait_for", {}) or {}
    if not isinstance(wait_raw, dict):
        raise ConfigError(f"{path}: [qa] wait_for must be a table of page -> selector")
    wait_for: dict[str, str] = {}
    for page, selector in wait_raw.items():
        if page not in pages:
            raise ConfigError(f"{path}: [qa.wait_for] page {page!r} is not listed in [qa] pages")
        if not isinstance(selector, str) or not selector.strip():
            raise ConfigError(f"{path}: [qa.wait_for] {page!r} must be a non-empty selector")
        wait_for[page] = selector.strip()
    if "layout_locales" in raw:
        layout = _str_list(raw["layout_locales"], "layout_locales", path) if raw["layout_locales"] else []
    else:
        layout = [code for code in ("ar", "zh") if code in locales]
    try:
        timeout = float(raw.get("ready_timeout", 60))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{path}: [qa] ready_timeout must be a number of seconds") from exc
    return QaConfig(
        base_url=base_url,
        pages=pages,
        start=start,
        locale_mode=mode,
        query_param=str(raw.get("query_param") or "lang").strip(),
        storage_key=storage_key,
        clicks=clicks,
        wait_for=wait_for,
        qa_locale=str(raw.get("qa_locale") or "en-XX").strip(),
        layout_locales=layout,
        ready_timeout=max(1.0, timeout),
    )
