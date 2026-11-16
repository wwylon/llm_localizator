"""Message-file adapters and translation state."""

from __future__ import annotations

from pathlib import Path

from .android_xml import AndroidXmlCatalog, android_qualifier, locale_from_qualifier
from .arb import ArbCatalog
from .base import Catalog, FlatMessages, Message
from .csv_catalog import CsvCatalog
from .gettext_po import GettextPoCatalog
from .go_i18n import GoI18nCatalog
from .ios_strings import IosStringsCatalog
from .ios_stringsdict import IosStringsdictCatalog
from .xcstrings import XcstringsCatalog
from .json_flat import JsonFlatCatalog
from .json_nested import JsonNestedCatalog, flatten_messages, unflatten_messages
from .multilang_json import MultilangJsonCatalog
from .php_array import PhpArrayCatalog
from .properties import PropertiesCatalog
from .resx import ResxCatalog
from .chrome_messages import ChromeMessagesCatalog
from .qt_ts import QtTsCatalog
from .xliff import XliffCatalog
from .yaml_nested import YamlNestedCatalog
from .state import (
    LEGACY_TIMESTAMPS,
    StateStore,
    is_structurally_stale,
    make_entry,
    needs_translation,
    now_iso,
    parse_translated_at,
    state_key,
)
from .history import HistoryEvent, HistoryStore, make_history_event
from .flags import FlagStore
from .provenance import (
    PROVIDER_CLOUD,
    PROVIDER_LOCAL,
    PROVIDERS,
    infer_provider,
    normalize_provider,
    provider_of,
)
from .scores import ScoreStore
from .tm import TranslationMemory, TMEntry, context_hash

__all__ = [
    "KNOWN_FORMATS",
    "catalog_for",
    "PROVIDER_CLOUD",
    "PROVIDER_LOCAL",
    "PROVIDERS",
    "AndroidXmlCatalog",
    "ArbCatalog",
    "Catalog",
    "CsvCatalog",
    "FlatMessages",
    "FlagStore",
    "GettextPoCatalog",
    "GoI18nCatalog",
    "HistoryEvent",
    "HistoryStore",
    "IosStringsCatalog",
    "JsonFlatCatalog",
    "JsonNestedCatalog",
    "LEGACY_TIMESTAMPS",
    "Message",
    "MultilangJsonCatalog",
    "PhpArrayCatalog",
    "PropertiesCatalog",
    "ResxCatalog",
    "ScoreStore",
    "StateStore",
    "TMEntry",
    "TranslationMemory",
    "YamlNestedCatalog",
    "android_qualifier",
    "build_catalog",
    "context_hash",
    "flatten_messages",
    "infer_provider",
    "is_structurally_stale",
    "make_entry",
    "make_history_event",
    "needs_translation",
    "normalize_provider",
    "now_iso",
    "parse_translated_at",
    "provider_of",
    "resolve_format",
    "canonical_formats",
    "state_key",
    "unflatten_messages",
]

_ADAPTERS: dict[str, type[Catalog]] = {
    "json-nested": JsonNestedCatalog,       # next-intl, react-intl
    "json-flat": JsonFlatCatalog,           # i18next, hand-rolled catalogues
    "yaml": YamlNestedCatalog,             # vue-i18n, Rails
    "po": GettextPoCatalog,                # gettext: Python, PHP, C, Go
    "arb": ArbCatalog,                     # Flutter
    "android-xml": AndroidXmlCatalog,      # Android strings.xml
    "multilang-json": MultilangJsonCatalog, # single file, all locales inline
    "csv": CsvCatalog,                     # spreadsheet / CSV export
    "php-array": PhpArrayCatalog,          # Laravel / Symfony PHP arrays
    "go-i18n": GoI18nCatalog,             # go-i18n v2 JSON
    "ios-strings": IosStringsCatalog,      # Apple Localizable.strings
    "ios-stringsdict": IosStringsdictCatalog,  # Apple .stringsdict plurals
    "xcstrings": XcstringsCatalog,         # Apple string catalog, all locales in one file
    "properties": PropertiesCatalog,       # Java / Spring .properties
    "resx": ResxCatalog,                   # .NET .resx resources
    "chrome-messages": ChromeMessagesCatalog,  # WebExtension _locales/<locale>/messages.json
    "qt-ts": QtTsCatalog,                  # Qt Linguist .ts, one file per locale
    "xliff": XliffCatalog,                 # XLIFF 1.2 / 2.0, one .xlf per locale
}

#: Aliases, so a config may name the framework rather than the file format.
_ALIASES: dict[str, str] = {
    "next-intl": "json-nested",
    "react-intl": "json-nested",
    "i18next": "json-flat",
    "vue-i18n": "yaml",
    "rails": "yaml",
    "gettext": "po",
    "flutter": "arb",
    "android": "android-xml",
    "yml": "yaml",
    "glossary": "multilang-json",
    "laravel": "php-array",
    "laravel-array": "php-array",
    "spring": "properties",
    "dotnet": "resx",
    "xlf": "xliff",
    "webextension": "chrome-messages",
    "chrome": "chrome-messages",
    "qt": "qt-ts",
    "linguist": "qt-ts",
    "apple": "ios-strings",
    "xcode": "ios-strings",
}

#: Every name accepted by :func:`build_catalog`, for error messages and docs.
KNOWN_FORMATS: list[str] = sorted({*_ADAPTERS, *_ALIASES})


def canonical_formats() -> list[str]:
    """Adapter ids without aliases, for pickers (web settings and setup)."""
    return sorted(_ADAPTERS)


def resolve_format(fmt: str) -> str:
    """Canonical format name. ``gettext`` becomes ``po``."""
    return _ALIASES.get(fmt, fmt)


def catalog_for(cfg) -> Catalog:
    """The project's message catalogue (M3: one call instead of four config fields at 50+ sites)."""
    return build_catalog(cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale)


def build_catalog(
    fmt: str, root: Path, path_template: str, source_locale: str = "en"
) -> Catalog:
    """Instantiate the catalog adapter named by ``fmt``.

    Accepts either a format name (``po``) or a framework alias (``gettext``).
    """
    resolved = _ALIASES.get(fmt, fmt)
    try:
        cls = _ADAPTERS[resolved]
    except KeyError:
        known = ", ".join(KNOWN_FORMATS)
        raise ValueError(f"unknown catalog format {fmt!r} (known: {known})") from None
    return cls(root, path_template, source_locale)
