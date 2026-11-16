"""Run the conformance matrix and score every language/category. Also used by the report generator."""

from __future__ import annotations

import tempfile
from pathlib import Path

from llm_localizator.scan import build_scanner
from llm_localizator.scan.base import count_unsupported

from .spec import CATEGORIES, LANGS, REPORTED_ONLY, render


def _norm(text: str) -> str:
    return " ".join(text.split())


def run_language(lang: str) -> dict[str, dict]:
    """``{category: {"intent", "ok", "found", "confidence"}}`` for one language."""
    name, snippets = LANGS[lang]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        src.mkdir()
        (src / name).write_text(render(lang), encoding="utf-8")
        hits = build_scanner("source", root, ["src"]).scan().hardcoded
    out: dict[str, dict] = {}
    for cat in snippets:
        intent, phrase = CATEGORIES[cat]
        matching = [h for h in hits if phrase in _norm(h.text)]
        found = bool(matching)
        out[cat] = {
            "intent": intent,
            "found": found,
            # A call that shows text to a person must be reported at the default (medium+) tier, not buried in low.
            "ok": (found and (cat != "ui_sink" or max(h.confidence for h in matching) != "low"))
            if intent == "ui" else not found,
            "confidence": max((h.confidence for h in matching), key=("low", "medium", "high").index) if matching else "",
        }
    return out


def run_reported_only(lang: str) -> dict:
    """Languages with no scanner: they must be counted as not scanned, never silently skipped."""
    name, body = REPORTED_ONLY[lang]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        src.mkdir()
        (src / name).write_text(body + "\n", encoding="utf-8")
        return count_unsupported(build_scanner("source", root, ["src"]))


def scores() -> dict[str, dict]:
    """Per language: ui recall, rejection of not-ui, and the raw cells."""
    table: dict[str, dict] = {}
    for lang in LANGS:
        cells = run_language(lang)
        ui = [c for c in cells.values() if c["intent"] == "ui"]
        quiet = [c for c in cells.values() if c["intent"] != "ui"]
        table[lang] = {
            "recall": sum(c["ok"] for c in ui) / len(ui) if ui else None,
            "rejection": sum(c["ok"] for c in quiet) / len(quiet) if quiet else None,
            "cells": cells,
        }
    return table
