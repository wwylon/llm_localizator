"""Help topics per programming ecosystem and per human language (ADR-139).

``llm-localizator help human|agent --code kotlin`` and ``--lang ar`` print a page for one reader.

* ``--code NAME``: a hand-written file ``help/code/NAME.md`` with ``## For people`` and ``## For agents``
  sections, plus a ``code-facts`` block rendered from code (scanner tier, UI sinks, routed calls, catalogue
  formats) so the numbers cannot drift.
* ``--lang CODE``: rendered from the language profile (``core/locales/<code>.py``) so plural forms, typography
  and grammar rules are always current, then the practice text of its writing-system group
  (``help/lang/groups/<group>.md``) and, when it exists, hand-written extras (``help/lang/<code>.md``).

Pure: no I/O beyond reading the packaged files.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

__all__ = [
    "CODE_TOPICS", "READERS", "SCRIPT_GROUPS", "code_topic_names", "code_text", "lang_topic_names", "lang_text",
    "render_code_facts", "section",
]

HELP_DIR = Path(__file__).resolve().parent
READERS = ("human", "agent")
_SECTION = {"human": "## For people", "agent": "## For agents"}

#: topic -> (title, scanner language ids, catalogue formats from docs/catalog-adapters.md, ecosystem sink key)
CODE_TOPICS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], str | None]] = {
    "js-ts": ("JavaScript and TypeScript (React, Vue, Svelte, Next.js, Node)",
              ("javascript", "typescript", "tsx", "vue", "svelte", "html"), ("json-nested", "json-flat"), None),
    "python": ("Python (Django, Flask, FastAPI)", ("python",), ("po", "json-flat", "yaml"), None),
    "android": ("Android (Kotlin and Java)", ("kotlin", "java", "xmlui"), ("android-xml",), "kotlin"),
    "swift": ("iOS and macOS (Swift, Objective-C)", ("swift", "objc", "xmlui"), ("xcstrings", "ios-strings", "ios-stringsdict"), "swift"),
    "java": ("Java (Spring, Swing, JavaFX)", ("java", "erb"), ("properties",), "java"),
    "csharp": (".NET (WinForms, WPF, MAUI, Blazor, ASP.NET)", ("csharp", "razor", "xmlui"), ("resx",), "csharp"),
    "dart": ("Dart and Flutter", ("dart",), ("arb",), "dart"),
    "php": ("PHP (Laravel, Symfony, WordPress)", ("php",), ("php-array", "po"), "php"),
    "ruby": ("Ruby and Rails", ("ruby", "erb"), ("yaml",), "ruby"),
    "go": ("Go (html/template, templ, go-i18n)", ("go", "gotmpl", "templ"), ("go-i18n", "json-flat"), "go"),
    "rust": ("Rust (CLI, Tauri, Yew, Leptos)", ("rust",), ("po",), "rust"),
    "cpp-qt": ("C and C++ (Qt, wxWidgets, GTK)", ("cpp", "xmlui"), ("po", "xliff"), "cpp"),
    "templates": ("Template engines (Jinja, ERB, Handlebars, Razor, Freemarker)",
                  ("jinja", "erb", "handlebars", "gotmpl", "razor", "freemarker"), ("po", "json-flat"), None),
}

#: Profile script -> group page. Unknown scripts fall back to ``other``.
SCRIPT_GROUPS = {
    "latin": "latin", "cyrillic": "cyrillic-greek", "greek": "cyrillic-greek", "arabic": "rtl", "hebrew": "rtl",
    "thaana": "rtl", "devanagari": "indic", "bengali": "indic", "tamil": "indic", "thai": "southeast-asian",
    "lao": "southeast-asian", "khmer": "southeast-asian", "myanmar": "southeast-asian", "cjk": "cjk",
    "hangul": "cjk", "georgian": "caucasus-ethiopic", "armenian": "caucasus-ethiopic", "ethiopic": "caucasus-ethiopic",
}


def section(text: str, reader: str) -> str:
    """The part of a two-reader file that *reader* should see (the text before the first section is shared)."""
    h, a = text.find(_SECTION["human"]), text.find(_SECTION["agent"])
    if h < 0 or a < h:
        return text  # not a two-reader file
    return text[:h] + (text[h:a] if reader == "human" else text[a:])


def code_topic_names() -> list[str]:
    return sorted(CODE_TOPICS)


def render_code_facts(name: str) -> str:
    from ..scan.ecosystems import SINK_LABELS
    from ..scan.tiers import tier_for
    from ..scan.usage_calls import ROUTED_CALLS

    title, ids, formats, sink_key = CODE_TOPICS[name]
    rows = ["| Scanner language | Tier |", "|---|---|"] + [f"| `{i}` | {tier_for(i)} |" for i in ids]
    out = ["\n".join(rows), ""]
    sinks = list(SINK_LABELS.get(sink_key or "", ()))
    if sinks:
        out.append("Calls that show text to a person (a literal given to one is reported at medium or high confidence): "
                   + ", ".join(f"`{s}`" for s in sinks) + ".")
        out.append("")
    if name in {"js-ts", "python", "templates"}:
        out.append("Calls recognised as already translated: " + ", ".join(f"`{c}`" for c in sorted(ROUTED_CALLS)) + ".")
        out.append("")
    out.append("Catalogue formats (`[catalog] format`): " + ", ".join(f"`{f}`" for f in formats) + ".")
    return "\n".join(out) + "\n"


_BLOCK = re.compile(r"(<!-- generated:code-facts -->\n)(.*?)(<!-- /generated:code-facts -->)", re.S)


def regenerate_code(name: str, text: str) -> str:
    return _BLOCK.sub(lambda m: m.group(1) + render_code_facts(name) + m.group(3), text)


def code_text(name: str, reader: str) -> str:
    if name not in CODE_TOPICS:
        raise ValueError(f"unknown code topic {name!r} ({', '.join(code_topic_names())})")
    path = HELP_DIR / "code" / f"{name}.md"
    text = section(path.read_text(encoding="utf-8"), reader)
    return re.sub(r"<!-- /?generated:code-facts -->\n", "", text)


def lang_topic_names() -> list[str]:
    from ..core.locales import all_profiles

    profiles = all_profiles()
    items = profiles.values() if isinstance(profiles, dict) else profiles
    return sorted({p.code for p in items})


def _group_text(group: str, reader: str) -> str:
    path = HELP_DIR / "lang" / "groups" / f"{group}.md"
    return section(path.read_text(encoding="utf-8"), reader) if path.exists() else ""


#: Languages without a profile module yet: their writing-system group (the profile would say ``latin``).
UNPROFILED_GROUPS = {
    "bn": "indic", "ta": "indic", "te": "indic", "gu": "indic", "kn": "indic", "ml": "indic", "pa": "indic", "or": "indic",
    "si": "indic", "km": "southeast-asian", "lo": "southeast-asian", "my": "southeast-asian",
    "ka": "caucasus-ethiopic", "hy": "caucasus-ethiopic", "am": "caucasus-ethiopic",
}


def lang_text(code: str, reader: str) -> str:
    from ..core.locales import profile

    p = profile(code)
    has_profile = p.code.lower() == code.lower() or p.code.lower() == code.lower().split("-")[0]
    group = SCRIPT_GROUPS.get(p.script, "other") if has_profile else UNPROFILED_GROUPS.get(code.lower().split("-")[0], "latin")
    if not has_profile:
        p = replace(p, name=code, code=code)
    lines = [f"# {p.name} ({p.code}): localization notes", "",
             *(["No language profile exists for this code yet: the table below shows defaults, not facts. "
                "See docs/adding-a-language.md.", ""] if not has_profile else []),
             f"Writing system: {p.script}, {'right-to-left' if p.direction == 'rtl' else 'left-to-right'}; "
             + ("words are separated by spaces." if p.segmented else "no spaces between words: never split text on spaces."), ""]
    rows = ["| Fact | Value |", "|---|---|", f"| plural categories | {', '.join(p.plural_categories)} |"]
    if p.plural_example:
        rows.append(f"| plural example | `{p.plural_example}` |")
    if p.gettext_plural_forms and reader == "agent":
        rows.append(f"| gettext Plural-Forms | `{p.gettext_plural_forms}` |")
    if p.expansion_band:
        lo, hi = p.expansion_band
        rows.append(f"| length vs English | {lo:.2f} to {hi:.2f} times |")
    if p.decimal_mark:
        rows.append(f"| decimal mark | `{p.decimal_mark}` |")
    rows.append(f"| nouns keep a capital | {'yes' if p.capitalizes_nouns else 'no'} |")
    rows.append(f"| words inflect around glossary terms | {'yes' if p.inflects else 'no'} |")
    lines += rows + [""]
    if p.typography_prompt:
        lines += ["## Typography", "", p.typography_prompt, ""]
        if reader == "agent" and p.typography_checks:
            lines += ["Checked by V34:", ""]
            lines += [f"- `{c.id}`: {c.message}. Good: `{c.good}`. Bad: `{c.bad}`." for c in p.typography_checks]
            lines.append("")
    if p.grammar_prompt:
        lines += ["## Grammar", "", p.grammar_prompt, ""]
        if reader == "agent" and p.grammar_examples:
            lines += [f"- `{s}` -> `{t}`" for s, t in p.grammar_examples] + [""]
    if p.informal_prompt or p.formal_prompt:
        lines += ["## Formality", "",
                  "This language has a formal and an informal register. Set the `register` option (`informal` or `formal`, see docs/configuration.md) once and keep it.", ""]
    group_text = _group_text(group, reader)
    if group_text:
        lines += [group_text.rstrip(), ""]
    extra = HELP_DIR / "lang" / f"{p.code.lower()}.md"
    if extra.exists():
        lines += [section(extra.read_text(encoding="utf-8"), reader).rstrip(), ""]
    return "\n".join(lines)
