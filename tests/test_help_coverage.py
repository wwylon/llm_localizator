"""Every "?" mounted by a page has a HELP entry, and every entry is reachable."""

from __future__ import annotations

import json
import re
from pathlib import Path

from llm_localizator.web import shell

STATIC = Path(shell.__file__).parent / "static"
HELP_DIR = Path(shell.__file__).parent / "locales" / "help"
HELP_EN = json.loads((HELP_DIR / "en.json").read_text(encoding="utf-8"))
DEFINED = set(HELP_EN)

# Pages whose "?" keys are built from a prefix plus a dynamic suffix.
PREFIX_MOUNTS = {
    "analysis:": {"general", "breakdown", "repetitions", "providers", "queue"},
    "tm:": {"concordance", "leverage", "browse"},
    "project-config:": {"prompt", "bridge", "glossary", "identity"},
}


def _js_texts() -> list[str]:
    return [
        js.read_text(encoding="utf-8")
        for js in STATIC.glob("*.js")
        if js.name != "help.js"
    ]


def _called_keys() -> set[str]:
    """Keys passed to a help call (the call may span lines, as in settings cards)."""
    pattern = re.compile(
        r'(?:helpBtn|showHelp|help|card|section)\([^)]*?"([a-z-]+:[a-z-]+)"', re.S
    )
    keys: set[str] = set()
    for text in _js_texts():
        keys.update(pattern.findall(text))
    return keys


def _mounted_keys() -> set[str]:
    """Any literal naming a defined key counts as a mount."""
    keys: set[str] = set()
    for text in _js_texts():
        keys.update(k for k in DEFINED if f'"{k}"' in text)
    for prefix, topics in PREFIX_MOUNTS.items():
        keys.update(prefix + topic for topic in topics)
    # operations.js mounts "operations:" + <command name> for every command
    keys.update(k for k in DEFINED if k.startswith("operations:"))
    return keys


def test_every_mounted_key_is_defined() -> None:
    missing = sorted(k for k in _called_keys() if k not in DEFINED)
    assert not missing, f"help keys mounted but not defined: {missing}"


def test_every_defined_key_is_mounted() -> None:
    orphan = sorted(DEFINED - _mounted_keys())
    assert not orphan, f"help keys defined but never mounted: {orphan}"


def test_entries_are_detailed() -> None:
    assert len(HELP_EN) == len(DEFINED)
    for key, entry in HELP_EN.items():
        title = entry.get("title") or ""
        body = entry.get("body") or ""
        assert len(title) > 4, key
        assert len(body) >= 450, f"{key} help text is too thin ({len(body)} chars)"


def test_help_locale_parity() -> None:
    en_keys = set(HELP_EN)
    for path in HELP_DIR.glob("*.json"):
        if path.name == "en.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data) == en_keys, f"{path.name} key set differs from en"


def test_content_pages_defer_help_js() -> None:
    """Wave 3: help.js is idle-deferred via ``__LLM_ENSURE_HELP``, not in PAGE_SCRIPTS."""
    # Auth / guided-setup shells skip the idle help deferral (no "?" mounts).
    skip = {"login", "register", "pending", "setup"}
    from llm_localizator.web.shell import ROUTES, _PAGE_SCRIPTS

    for route in ROUTES:
        if route.id in skip:
            continue
        scripts = _PAGE_SCRIPTS.get(route.id, ())
        assert "/static/help.js" not in scripts, route.id


def test_help_js_loads_locale_json() -> None:
    text = (STATIC / "help.js").read_text(encoding="utf-8")
    assert "/locales/help/" in text
    assert "loadHelp" in text
    assert '"branches:general"' not in text
