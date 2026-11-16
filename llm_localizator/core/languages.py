"""Source languages and which message standards a catalogue format may use.

Data only. No I/O. Scanners, config, and the contributor doc read this table.
They do not keep a second copy.

A programming language and a message standard are different facts. A Python
project may store ICU JSON. ``po`` and ``android-xml`` are gettext and Android
on disk and ICU after ``load``, so they may only select ``icu``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "FLEXIBLE_FORMATS",
    "ICU_ONLY_FORMATS",
    "SourceLanguage",
    "StandardInfo",
    "language",
    "language_for_suffix",
    "literal_languages",
    "source_languages",
    "standard_allowed",
    "standard_ids",
]


@dataclass(frozen=True)
class SourceLanguage:
    """One programming language the hardcoded-string scanner understands."""

    id: str
    extensions: tuple[str, ...]
    line_comments: tuple[str, ...]
    block_comment: tuple[str, str] | None
    usual_standards: tuple[str, ...]
    # ``jsx`` / ``js`` / ``html`` stay on the framework scanners. ``literal``
    # is the shared string-literal detector.
    detector: str
    quotes: str


@dataclass(frozen=True)
class StandardInfo:
    """Registry row for a message standard. The parser lives under standards/."""

    id: str
    has_plurals: bool


# Canonical catalogue formats. Aliases are resolved by the catalog package
# before :func:`standard_allowed` is called.
ICU_ONLY_FORMATS = frozenset({"po", "android-xml"})
FLEXIBLE_FORMATS = frozenset({
    "json-nested", "json-flat", "yaml", "arb",
    "multilang-json", "csv", "php-array", "go-i18n",
})

_STANDARDS: tuple[StandardInfo, ...] = (
    StandardInfo("icu", True),
    StandardInfo("printf", False),
    StandardInfo("brace", False),
    StandardInfo("i18next", True),
    StandardInfo("go-template", False),
    StandardInfo("laravel", False),
)

_LANGUAGES: tuple[SourceLanguage, ...] = (
    SourceLanguage(
        "tsx", (".tsx", ".jsx"), ("//",), ("/*", "*/"),
        ("icu", "i18next"), "jsx", "script",
    ),
    SourceLanguage(
        "javascript", (".js", ".mjs", ".cjs"), ("//",), ("/*", "*/"),
        ("icu", "i18next"), "js", "script",
    ),
    SourceLanguage(
        "html", (".html", ".htm"), (), None,
        (), "html", "none",
    ),
    SourceLanguage(
        "typescript", (".ts", ".mts", ".cts"), ("//",), ("/*", "*/"),
        ("icu", "i18next"), "literal", "script",
    ),
    SourceLanguage(
        "go", (".go",), ("//",), ("/*", "*/"),
        ("printf", "go-template", "icu"), "literal", "go",
    ),
    SourceLanguage(
        "cpp", (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h"),
        ("//",), ("/*", "*/"),
        ("printf", "brace", "icu"), "literal", "cpp",
    ),
    SourceLanguage(
        "python", (".py",), ("#",), None,
        ("icu", "printf", "brace"), "literal", "python",
    ),
    SourceLanguage(
        "csharp", (".cs",), ("//",), ("/*", "*/"),
        ("brace",), "literal", "csharp",
    ),
    SourceLanguage(
        "php", (".php",), ("//", "#"), ("/*", "*/"),
        ("printf", "laravel", "icu"), "literal", "script",
    ),
    SourceLanguage(
        "swift", (".swift",), ("//",), ("/*", "*/"),
        ("icu",), "literal", "script",
    ),
    SourceLanguage(
        "objc", (".m", ".mm"), ("//",), ("/*", "*/"),
        ("printf",), "literal", "cpp",
    ),
    SourceLanguage(
        "java", (".java",), ("//",), ("/*", "*/"),
        ("icu", "printf", "brace"), "literal", "script",
    ),
    # V-003: same literal detector as Java/TS; framework-specific scanners can
    # refine later. Extensions must land here so discover/agent-hardcoded see them.
    SourceLanguage(
        "kotlin", (".kt", ".kts"), ("//",), ("/*", "*/"),
        ("icu", "printf", "brace"), "literal", "script",
    ),
    SourceLanguage(
        "dart", (".dart",), ("//",), ("/*", "*/"),
        ("icu", "brace"), "literal", "script",
    ),
    # XML UI definitions: Android layouts (res/layout|menu|navigation|xml), XAML, Qt .ui, iOS storyboards (scan/xmlui.py).
    SourceLanguage(
        "xmlui", (".xml", ".xaml", ".ui", ".storyboard", ".xib", ".fxml"), (), None, ("icu", "printf"), "xmlui", "none",
    ),
    # UI definition files made of property lines: QML, Kivy, Godot scenes (scan/propdef.py).
    SourceLanguage("qml", (".qml",), ("//",), ("/*", "*/"), ("icu",), "propdef", "none"),
    SourceLanguage("kv", (".kv",), ("#",), None, ("icu",), "propdef", "none"),
    SourceLanguage("godot", (".tscn", ".tres"), (";",), None, ("icu",), "propdef", "none"),
    # Freedesktop launcher entries: untranslated ``Name=`` / ``Comment=`` keys (pool E: quemusic).
    SourceLanguage("desktop", (".desktop",), ("#",), None, ("icu",), "propdef", "none"),
    # GDScript: Python-like quoting and ``#`` comments; Godot UI sinks in scan/ecosystems.py (pool E: godotos).
    SourceLanguage("gdscript", (".gd",), ("#",), None, ("icu",), "literal", "python"),
    # Content and manifest files: Markdown pages, TOML menus, extension manifests, Info.plist (scan/content.py).
    SourceLanguage("content", (".md", ".markdown", ".toml", ".json", ".plist"), (), None, ("icu",), "content", "none"),
    # Server-side template engines: HTML with embedded code (scan/templates.py).
    SourceLanguage("erb", (".erb", ".ejs", ".jsp", ".gsp"), (), None, ("icu", "printf"), "template", "none"),
    SourceLanguage("handlebars", (".hbs", ".handlebars", ".mustache"), (), None, ("icu", "brace"), "template", "none"),
    SourceLanguage(
        "jinja", (".twig", ".jinja", ".jinja2", ".j2", ".njk", ".liquid"), (), None, ("icu", "printf", "brace"),
        "template", "none",
    ),
    SourceLanguage("gotmpl", (".gohtml", ".tmpl", ".tpl"), (), None, ("icu", "printf"), "template", "none"),
    SourceLanguage("razor", (".cshtml", ".razor"), (), None, ("icu", "printf"), "template", "none"),
    SourceLanguage("freemarker", (".ftl",), (), None, ("icu", "printf"), "template", "none"),
    # Indentation-based Ruby templates: markup view + Ruby code view (scan/markup_indent.py).
    SourceLanguage("haml", (".haml",), (), None, ("icu", "printf"), "indent", "none"),
    SourceLanguage("slim", (".slim",), (), None, ("icu", "printf"), "indent", "none"),
    # Astro components and MDX pages: TS frontmatter / ESM + JSX, Markdown body (scan/astro_mdx.py).
    SourceLanguage("astro", (".astro",), ("//",), ("/*", "*/"), ("icu", "i18next"), "astro", "script"),
    SourceLanguage("mdx", (".mdx",), (), None, ("icu", "i18next"), "mdx", "none"),
    # Shared literal detector; ecosystem sinks in scan/ecosystems.py.
    SourceLanguage(
        "ruby", (".rb", ".rake"), ("#",), None,
        ("icu", "printf", "brace"), "literal", "script",
    ),
    SourceLanguage(
        "rust", (".rs",), ("//",), ("/*", "*/"),
        ("icu", "printf", "brace"), "literal", "script",
    ),
    SourceLanguage(
        "scala", (".scala", ".sc"), ("//",), ("/*", "*/"),
        ("icu", "printf", "brace"), "literal", "script",
    ),
    SourceLanguage(
        "lua", (".lua",), ("--",), ("--[[", "]]"),
        ("printf",), "literal", "script",
    ),
    SourceLanguage(
        "elixir", (".ex", ".exs"), ("#",), None,
        ("icu", "brace"), "literal", "script",
    ),
    SourceLanguage(
        "svelte", (".svelte",), ("//",), ("/*", "*/"),
        ("icu", "i18next"), "sfc", "script",
    ),
    # Go templ components: only the component bodies are markup (scan/templ.py).
    SourceLanguage(
        "templ", (".templ",), ("//",), ("/*", "*/"),
        ("icu", "printf"), "templ", "script",
    ),
    # Single-file components: markup, script and style are scanned apart (scan/sfc.py).
    SourceLanguage(
        "vue", (".vue",), ("//",), ("/*", "*/"),
        ("icu", "i18next"), "sfc", "script",
    ),
)

_BY_ID = {row.id: row for row in _LANGUAGES}
_BY_SUFFIX: dict[str, SourceLanguage] = {}
for _row in _LANGUAGES:
    for _ext in _row.extensions:
        _BY_SUFFIX[_ext] = _row


def source_languages() -> tuple[SourceLanguage, ...]:
    return _LANGUAGES


def language(language_id: str) -> SourceLanguage:
    try:
        return _BY_ID[language_id]
    except KeyError:
        known = ", ".join(row.id for row in _LANGUAGES)
        raise KeyError(f"unknown source language {language_id!r} (known: {known})") from None


def language_for_suffix(suffix: str) -> SourceLanguage | None:
    return _BY_SUFFIX.get(suffix.lower())


def literal_languages() -> tuple[SourceLanguage, ...]:
    return tuple(row for row in _LANGUAGES if row.detector == "literal")


def standard_ids() -> tuple[str, ...]:
    return tuple(row.id for row in _STANDARDS)


def standard_info(standard_id: str) -> StandardInfo:
    for row in _STANDARDS:
        if row.id == standard_id:
            return row
    known = ", ".join(standard_ids())
    raise KeyError(f"unknown message standard {standard_id!r} (known: {known})")


def standard_allowed(catalog_format: str, standard_id: str) -> bool:
    """Whether *catalog_format* (canonical, not an alias) may select *standard_id*.

    ``po`` and ``android-xml`` already return ICU from ``load``. Any other
    parser would flag healthy strings. JSON, YAML, and ARB may use any
    registered standard. The default is still ``icu``.
    """
    if standard_id not in _BY_STANDARD:
        return False
    if catalog_format in ICU_ONLY_FORMATS:
        return standard_id == "icu"
    if catalog_format in FLEXIBLE_FORMATS:
        return True
    return standard_id == "icu"


_BY_STANDARD = {row.id for row in _STANDARDS}
