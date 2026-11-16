"""Detect catalogue layout and render a starter ``.llm-localize.toml``."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# (format, path template, scan adapter, glob probed inside the parent dir).
# Ordered by specificity: the first template that finds source files wins, so
# framework-specific layouts must precede the generic ones.
KNOWN_LAYOUTS: list[tuple[str, str, str | None, str]] = [
    # JS/TS
    ("json-nested", "apps/web/messages/{locale}/{namespace}.json", "next-intl", "*.json"),
    ("json-nested", "src/messages/{locale}/{namespace}.json", "next-intl", "*.json"),
    ("json-nested", "messages/{locale}/{namespace}.json", "next-intl", "*.json"),
    ("json-flat", "public/locales/{locale}/{namespace}.json", "i18next", "*.json"),
    ("json-flat", "locales/{locale}/{namespace}.json", "i18next", "*.json"),
    ("json-flat", "src/locales/{locale}.json", "i18next", "*.json"),
    # Vue / Rails
    ("yaml", "config/locales/{locale}/{namespace}.yml", None, "*.yml"),
    ("yaml", "src/locales/{locale}.yaml", None, "*.yaml"),
    ("yaml", "locales/{locale}.yml", None, "*.yml"),
    # gettext
    ("po", "locale/{locale}/LC_MESSAGES/{namespace}.po", None, "*.po"),
    ("po", "locales/{locale}/LC_MESSAGES/{namespace}.po", None, "*.po"),
    ("po", "po/{locale}.po", None, "*.po"),
    # Flutter
    ("arb", "lib/l10n/{namespace}_{locale}.arb", None, "*.arb"),
    # Android
    ("android-xml", "app/src/main/res/values-{locale}/{namespace}.xml", None, "*.xml"),
    ("android-xml", "res/values-{locale}/{namespace}.xml", None, "*.xml"),
]


def detect_layout(root: Path, source_locale: str = "en") -> tuple[str, str, str | None] | None:
    """Find the first known catalogue layout that actually has source files."""
    for fmt, template, scanner, glob in KNOWN_LAYOUTS:
        for locale_dir in _probe_locales(fmt, source_locale):
            rel = template.format(locale=locale_dir, namespace="__ns__")
            probe = root / rel
            if probe.parent.is_dir() and any(probe.parent.glob(glob)):
                return fmt, template, scanner
    return _search_layout(root, source_locale)


def _probe_locales(fmt: str, source_locale: str) -> list[str]:
    if fmt == "android-xml":
        return [source_locale, ""]
    return [source_locale]


def survey_layout(
    root: Path, template: str, fmt: str, source_locale: str,
) -> tuple[list[str], list[str]]:
    """Namespaces and sibling locales visible for a detected layout."""
    from ..catalog import build_catalog

    catalog = build_catalog(fmt, root, template, source_locale)
    namespaces = [ns for ns in catalog.namespaces() if ns]
    locales = [loc for loc in catalog.locales_present() if loc != source_locale]
    return namespaces, locales


DEFAULT_MODEL = "llama3.2"
DEFAULT_DOMAIN = "a software application"
DEFAULT_PROVIDER = "ollama"


def _toml_str(value: str) -> str:
    """A TOML basic string. JSON string syntax is a valid subset."""
    return json.dumps(value, ensure_ascii=False)


def layouts_help() -> str:
    """The supported catalogue layouts plus a `--format/--path` example."""
    rows: list[str] = []
    for fmt, template, _scanner, _glob in KNOWN_LAYOUTS:
        row = f"  {fmt:<12} {template}"
        if row not in rows:
            rows.append(row)
    return (
        "Supported layouts:\n" + "\n".join(rows) + "\n"
        "If yours differs, point at it, for example:\n"
        "  llm-localizator init --format json-flat --path 'i18n/{locale}.json'"
    )


def render_init_config(
    name: str,
    source_locale: str,
    fmt: str,
    template: str,
    locales: list[str],
    scanner: str | None,
    *,
    model: str = DEFAULT_MODEL,
    domain: str = DEFAULT_DOMAIN,
    provider: str = DEFAULT_PROVIDER,
) -> str:
    """A commented starter config holding only the essentials.

    Everything else has a default; see docs/configuration.md.
    """
    targets = ", ".join(_toml_str(loc) for loc in locales)
    provider_lines = f"kind = {_toml_str(provider)}\n"
    if provider == "ollama":
        provider_lines += 'url = "http://localhost:11434"   # Ollama runs on your machine\n'
    return (
        "# llm-localizator configuration: only the essentials are set here.\n"
        "# Everything else has a default (docs/configuration.md).\n"
        "# Not sure what to do next? Run: llm-localizator guide\n"
        "\n"
        "[project]\n"
        f"name = {_toml_str(name)}\n"
        f"source_locale = {_toml_str(source_locale)}   # the language your strings are written in\n"
        "# data_home = \"project\"  # keep .llm-state etc. in this repo (default: engine → ~/.llm_localize/data/<name>/)\n"
        "\n"
        "[catalog]\n"
        f"format = {_toml_str(fmt)}\n"
        f"path = {_toml_str(template)}\n"
        'namespaces = "*"   # translate every namespace\n'
        "\n"
        "[locales]\n"
        "# Languages to translate into. Add one later with:\n"
        "#   llm-localizator add-locale --locale pl\n"
        f"targets = [{targets}]\n"
        "\n"
        "[locales.models]\n"
        f"default = {_toml_str(model)}   # the model that translates\n"
        "\n"
        "[provider]\n"
        f"{provider_lines}"
        "\n"
        "[prompt]\n"
        "# One sentence describing the product. It goes into every translation prompt,\n"
        "# and it is the single biggest lever on terminology quality.\n"
        f"domain = {_toml_str(domain)}\n"
        "\n"
        "# Optional: tell the model who the product is for (uncomment to use).\n"
        "# [voice]\n"
        '# description = "A hotel booking app for business travellers."\n'
        '# audience = "Frequent travellers"\n'
        '# tone = "friendly and direct"\n'
    ) + (
        f"\n[scan]\nadapter = {_toml_str(scanner)}\n"
        "\n[apply]\n"
        "# How a scan result you accept reaches the catalogue (llm-localizator scan-decide):\n"
        "#   manual  = recorded only; you run `llm-localizator apply --confirm`\n"
        "#   request = a review ticket is opened; closing it applies the key\n"
        "#   auto    = the key is added and translation queued at once\n"
        'mode = "manual"\n'
        if scanner else ""
    )


_LOCALE_STEM = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,4}){0,2}$")
_SKIP_DIRS = frozenset({
    ".git", "node_modules", "vendor", "dist", "build", "target", "venv", ".venv",
    "__pycache__", "test", "tests", "__tests__", "fixtures", "fixture", "examples",
    "example", "docs", "site-packages", "e2e", "testdata",
})
_WALK_LIMIT = 200_000


def _search_layout(root: Path, source_locale: str) -> tuple[str, str, str | None] | None:
    """Fallback: find a locale-named catalogue anywhere under *root*.

    Handles ``<dir>/<locale>.json`` next to sibling locale files and gettext
    ``<dir>/<locale>/LC_MESSAGES/*.po``. The candidate with the most sibling
    locales wins, then the shallowest path. Never reads outside *root*.
    """
    best: tuple[tuple[int, int, str], tuple[str, str]] | None = None
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in _SKIP_DIRS and not d.startswith("."))
        seen += len(filenames)
        if seen > _WALK_LIMIT:
            break
        here = Path(dirpath)
        rel = here.relative_to(root).as_posix()
        prefix = "" if rel == "." else rel + "/"
        depth = 0 if rel == "." else rel.count("/") + 1
        cand = _json_candidate(here, filenames, source_locale)
        if cand:
            fmt, template, siblings = cand
            key = (-siblings, depth, prefix)
            if best is None or key < best[0]:
                best = (key, (fmt, prefix + template))
        if source_locale in dirnames:
            lc = here / source_locale / "LC_MESSAGES"
            if lc.is_dir() and any(lc.glob("*.po")):
                siblings = sum(1 for d in dirnames if _LOCALE_STEM.match(d))
                key = (-siblings, depth, prefix)
                if best is None or key < best[0]:
                    best = (key, ("po", prefix + "{locale}/LC_MESSAGES/{namespace}.po"))
    if best is None:
        return None
    fmt, template = best[1]
    return fmt, template, None


def _json_candidate(here: Path, filenames: list[str], source_locale: str):
    names = {f for f in filenames if f.endswith(".json")}
    if f"{source_locale}.json" not in names:
        return None
    siblings = sum(1 for f in names if _LOCALE_STEM.match(f[:-5]) and f[:-5] != source_locale)
    if siblings < 1:
        return None
    try:
        data = json.loads((here / f"{source_locale}.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data:
        return None
    nested = any(isinstance(v, dict) for v in data.values())
    return ("json-nested" if nested else "json-flat"), "{locale}.json", siblings
