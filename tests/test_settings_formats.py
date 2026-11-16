"""Catalogue format pickers read the adapter registry, not a hardcoded list (plan D4)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.catalog import KNOWN_FORMATS, canonical_formats, resolve_format
from llm_localizator.web.settings import settings_view

STATIC = Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static"


def test_canonical_formats_are_the_registry_without_aliases() -> None:
    formats = canonical_formats()
    assert formats == sorted({resolve_format(f) for f in KNOWN_FORMATS})
    assert {"qt-ts", "chrome-messages", "xliff", "resx"} <= set(formats)
    assert "gettext" not in formats


def test_settings_payload_lists_every_format(tmp_path, make_config) -> None:
    payload = settings_view(make_config(tmp_path), port=8770, coverage={})
    assert payload["catalogFormats"] == canonical_formats()


def test_pickers_use_the_payload() -> None:
    assert "data.catalogFormats" in (STATIC / "settings.js").read_text(encoding="utf-8")
    assert "current.catalogFormats" in (STATIC / "setup.js").read_text(encoding="utf-8")
