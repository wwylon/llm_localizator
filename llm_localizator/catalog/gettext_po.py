"""gettext ``.po`` catalog adapter.

The most involved adapter, because a ``.po`` file disagrees with our model in
three ways.

**Plurals are indexed, not named.** ``msgid_plural`` plus ``msgstr[0..N]``,
with a ``Plural-Forms`` header giving a C expression from number to slot. Which
CLDR category a slot means is convention; :mod:`llm_localizator.core.plurals`
recovers it from the locale's CLDR category list -- the same source the
validator uses, so the two cannot disagree.

**Keys are the source text.** There is no separate identifier: ``msgid`` is the
English string. Our flat map is therefore keyed by msgid, and ``msgctxt`` (the
disambiguating context) becomes a ``ctxt\\x04msgid`` compound key, which is the
same convention gettext itself uses internally.

**Files carry translator content we must not destroy.** ``#.`` extracted
comments, ``#:`` source references, ``#,`` flags such as ``fuzzy``, and
``#`` translator comments. All are round-tripped: a write merges into the parsed
original rather than regenerating from scratch.

Written by hand rather than via ``polib`` to avoid a runtime dependency for a
format that is, in the end, line-oriented.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from ..core.plurals import (
    gettext_plural_forms,
    PluralSet,
    build_icu_plural,
    fill_catchall_categories,
    gettext_slot_order,
    icu_placeholder_to_printf,
    nplurals_from_header,
    parse_icu_plural,
    printf_placeholder_to_icu,
)
from .base import Catalog, FlatMessages, Message
from .io import atomic_write_text

__all__ = ["GettextPoCatalog", "CONTEXT_SEPARATOR"]

#: gettext's own msgctxt/msgid separator (EOT).
CONTEXT_SEPARATOR = "\x04"

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}
_UNESCAPES = {v: k for k, v in _ESCAPES.items()}
_UNESCAPE_RE = re.compile(r"\\(?:x[0-9a-fA-F]{1,2}|[0-7]{1,3}|[\\ntr\"'abfv])")
_SIMPLE = {"a": "\a", "b": "\b", "f": "\f", "v": "\v", "'": "'"}


def _escape(s: str) -> str:
    return "".join(_ESCAPES.get(ch, ch) for ch in s)


def _unescape(s: str) -> str:
    def one(m: re.Match) -> str:
        tok = m.group(0)
        if tok in _UNESCAPES:
            return _UNESCAPES[tok]
        body = tok[1:]
        if body in _SIMPLE:
            return _SIMPLE[body]
        if body[0] == "x":
            return chr(int(body[1:], 16))
        return chr(int(body, 8))

    return _UNESCAPE_RE.sub(one, s)


@dataclass
class PoEntry:
    msgid: str = ""
    msgid_plural: str | None = None
    msgctxt: str | None = None
    msgstr: str = ""
    msgstr_plural: dict[int, str] = field(default_factory=dict)
    comments: list[str] = field(default_factory=list)      # '#  ' translator
    extracted: list[str] = field(default_factory=list)     # '#. ' from source
    references: list[str] = field(default_factory=list)    # '#: '
    flags: list[str] = field(default_factory=list)         # '#, '
    obsolete: bool = False

    @property
    def key(self) -> str:
        return f"{self.msgctxt}{CONTEXT_SEPARATOR}{self.msgid}" if self.msgctxt else self.msgid


def _copy_po_entry(entry: PoEntry) -> PoEntry:
    """Deep-ish copy so ``save`` never mutates cached entries in place."""
    return PoEntry(
        msgid=entry.msgid,
        msgid_plural=entry.msgid_plural,
        msgctxt=entry.msgctxt,
        msgstr=entry.msgstr,
        msgstr_plural=dict(entry.msgstr_plural),
        comments=list(entry.comments),
        extracted=list(entry.extracted),
        references=list(entry.references),
        flags=list(entry.flags),
        obsolete=entry.obsolete,
    )


def parse_po(text: str) -> list[PoEntry]:
    """Parse a ``.po`` file into entries, preserving everything we do not model."""
    entries: list[PoEntry] = []
    current = PoEntry()
    field_name: str | None = None
    plural_index = 0
    started = False

    def flush() -> None:
        nonlocal current, field_name, started
        if started:
            entries.append(current)
        current, field_name, started = PoEntry(), None, False

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            # A finished field ends the entry. An obsolete ``#~`` block does
            # too: those lines never become msgid/msgstr. A plain comment
            # may still be separated from its msgid by a blank line.
            if field_name is not None or current.obsolete:
                flush()
            continue

        if line.startswith("#"):
            if started and field_name is not None:
                flush()  # a comment after a msgstr starts the next entry
            started = True
            if line.startswith("#."):
                current.extracted.append(line[2:].strip())
            elif line.startswith("#:"):
                current.references.append(line[2:].strip())
            elif line.startswith("#,"):
                current.flags.extend(f.strip() for f in line[2:].split(","))
            elif line.startswith("#~"):
                current.obsolete = True
            else:
                current.comments.append(line[1:].strip())
            continue

        if line.startswith('"') and field_name is not None:
            # Continuation of the previous field.
            chunk = _unescape(line[1:-1] if len(line) >= 2 and line.endswith('"') else line.strip('"'))
            if field_name == "msgid":
                current.msgid += chunk
            elif field_name == "msgid_plural":
                current.msgid_plural = (current.msgid_plural or "") + chunk
            elif field_name == "msgctxt":
                current.msgctxt = (current.msgctxt or "") + chunk
            elif field_name == "msgstr":
                current.msgstr += chunk
            elif field_name == "msgstr_plural":
                current.msgstr_plural[plural_index] = (
                    current.msgstr_plural.get(plural_index, "") + chunk
                )
            continue

        m = re.match(r'^(msgctxt|msgid_plural|msgid|msgstr)(?:\[(\d+)\])?\s+"(.*)"$', line)
        if not m:
            continue
        started = True
        name, index, value = m.group(1), m.group(2), _unescape(m.group(3))

        if name == "msgctxt":
            current.msgctxt, field_name = value, "msgctxt"
        elif name == "msgid":
            current.msgid, field_name = value, "msgid"
        elif name == "msgid_plural":
            current.msgid_plural, field_name = value, "msgid_plural"
        elif index is not None:
            plural_index = int(index)
            current.msgstr_plural[plural_index] = value
            field_name = "msgstr_plural"
        else:
            current.msgstr, field_name = value, "msgstr"

    flush()
    return entries


def _wrap_escaped(text: str, limit: int) -> list[str]:
    """Break *text* after spaces so each piece fits *limit* characters."""
    pieces: list[str] = []
    cur = ""
    for word in re.findall(r"[^ ]* *", text):
        if not word:
            continue
        if cur and len(cur) + len(word) > limit:
            pieces.append(cur)
            cur = ""
        cur += word
    if cur:
        pieces.append(cur)
    return pieces


def _emit_field(name: str, value: str, width: int | None = None) -> list[str]:
    if width:
        segs = value.split("\n")
        parts = [_escape(p) + "\\n" for p in segs[:-1]]
        if segs[-1]:
            parts.append(_escape(segs[-1]))
        if len(parts) == 1 and len(name) + len(parts[0]) + 3 <= width:
            return [f'{name} "{parts[0]}"']
        out = [f'{name} ""']
        for part in parts:
            out += ['"' + w + '"' for w in _wrap_escaped(part, width - 2)]
        return out
    if "\n" not in value:
        return [f'{name} "{_escape(value)}"']

    # Multi-line values conventionally start with an empty first line. Every
    # segment but the last ends in an escaped newline; the last carries one only
    # if the value itself ended in a newline (then the trailing empty segment is
    # dropped, so a header does not emit a stray `""`).
    lines = value.split("\n")
    out = [f'{name} ""']
    for i, part in enumerate(lines):
        if i < len(lines) - 1:
            out.append('"' + _escape(part) + '\\n"')
        elif part:
            out.append('"' + _escape(part) + '"')
    return out


def render_po(entries: list[PoEntry], width: int | None = None) -> str:
    """Render *entries*; ``width`` (e.g. 79) wraps long strings msgmerge-style."""
    out: list[str] = []
    for entry in entries:
        for c in entry.comments:
            out.append(f"# {c}" if c else "#")
        for c in entry.extracted:
            out.append(f"#. {c}")
        for r in entry.references:
            out.append(f"#: {r}")
        if entry.flags:
            out.append("#, " + ", ".join(dict.fromkeys(entry.flags)))
        if entry.msgctxt is not None:
            out += _emit_field("msgctxt", entry.msgctxt, width)
        out += _emit_field("msgid", entry.msgid, width)
        if entry.msgid_plural is not None:
            out += _emit_field("msgid_plural", entry.msgid_plural, width)
            for i in sorted(entry.msgstr_plural):
                out += _emit_field(f"msgstr[{i}]", entry.msgstr_plural[i], width)
        else:
            out += _emit_field("msgstr", entry.msgstr, width)
        out.append("")
    return "\n".join(out)


class GettextPoCatalog(Catalog):
    #: `.po` carries `#.` extracted comments, which are exactly translator notes.
    carries_notes = True

    def __init__(self, root, path_template: str, source_locale: str = "en") -> None:
        super().__init__(root, path_template, source_locale)
        self.multi_namespace = "{namespace}" in path_template

    def namespaces(self) -> list[str]:
        found = set(self.discover_namespaces())
        if "{namespace}" in self.path_template and self.path_template.endswith(".po"):
            base = self.path_for(self.source_locale, "__NS__").parent
            if base.is_dir():
                for pot in base.rglob("*.pot"):
                    rel = pot.relative_to(base).as_posix()
                    if not any(p.startswith(".") for p in rel.split("/")):
                        found.add(rel[: -len(".pot")])
        return sorted(found)

    def path_for(self, locale: str, namespace: str | None = None) -> Path:
        """The source locale reads a sibling ``.pot`` template when it has no ``.po`` (C-045)."""
        path = super().path_for(locale, namespace)
        if locale == self.source_locale and path.suffix == ".po" and not path.exists():
            pot = path.with_suffix(".pot")
            if pot.exists():
                return pot
        return path

    # ---- reading -----------------------------------------------------------

    def _parse_po_file(self, path: Path) -> tuple[list[PoEntry], str | None]:
        entries = parse_po(path.read_text(encoding="utf-8-sig"))
        if path.suffix == ".pot":
            # A template has empty msgstr: its msgid IS the source text.
            for e in entries:
                if e.msgid == "" and not e.msgctxt:
                    continue
                if e.msgid_plural is not None:
                    e.msgstr_plural = {0: e.msgid, 1: e.msgid_plural}
                else:
                    e.msgstr = e.msgid
        header = next(
            (e.msgstr for e in entries if e.msgid == "" and not e.msgctxt),
            None,
        )
        return entries, header

    def _read(self, locale: str, namespace: str | None) -> tuple[list[PoEntry], str | None]:
        path = self.path_for(locale, namespace)
        if not path.exists():
            return [], None
        return self._cached_load(path, self._parse_po_file)

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        entries, header = self._read(locale, namespace)
        order = gettext_slot_order(locale, nplurals_from_header(self._plural_forms(header)))
        # This check is now purely informational: gettext_slot_order no longer
        # produces duplicates (it synthesises other_2, other_3, … for overflow
        # slots), so len(order) == len(set(order)) should always hold here.
        # Keep the guard to surface unexpected regressions.
        if len(order) != len(set(order)):
            path = self.path_for(locale, namespace)
            warnings.warn(
                f"{locale}: gettext_slot_order returned duplicate category names for "
                f"nplurals={len(order)} — plural forms may be lost ({path}). "
                f"This is a bug; please report it.",
                stacklevel=2,
            )
        out: FlatMessages = {}
        for e in entries:
            if e.obsolete or (e.msgid == "" and not e.msgctxt):
                continue  # header and obsolete entries are not translatable content
            if e.msgid_plural is not None:
                if not any(e.msgstr_plural.values()):
                    continue
                branches = {
                    order[i]: printf_placeholder_to_icu(text, "n")
                    for i, text in sorted(e.msgstr_plural.items())
                    if i < len(order) and text
                }
                if branches:
                    # gettext usually declares fewer forms than CLDR requires
                    # (Polish: 3 slots, 4 categories). Without this the message
                    # would be missing a category the validator demands, and
                    # every counted noun would fail through no fault of the
                    # translation.
                    branches = fill_catchall_categories(branches, locale)
                    out[e.key] = build_icu_plural(PluralSet("n", branches))
            elif e.msgstr:
                out[e.key] = e.msgstr
        return out

    def load_entries(self, locale: str, namespace: str | None = None) -> dict[str, Message]:
        entries, _ = self._read(locale, namespace)
        values = self.load(locale, namespace)
        out: dict[str, Message] = {}
        for e in entries:
            if e.obsolete or (e.msgid == "" and not e.msgctxt) or e.key not in values:
                continue
            out[e.key] = Message(
                key=e.key,
                value=values[e.key],
                note="; ".join(e.extracted),
                metadata={"references": e.references, "flags": e.flags,
                          "comments": e.comments},
            )
        return out

    # ---- writing -----------------------------------------------------------

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        if path.suffix == ".pot":
            raise ValueError(f"{path} is a .pot template: it is a read-only source")
        existing, header = self._read(locale, namespace)
        # Fall back to the source catalogue for structure: it is what tells us
        # which entries are plural and what their msgid_plural is.
        template, _ = self._read(self.source_locale, namespace)

        by_key = {e.key: e for e in existing}
        template_by_key = {e.key: e for e in template}
        plural_forms = self._plural_forms(header) or gettext_plural_forms(locale)
        order = gettext_slot_order(locale, nplurals_from_header(plural_forms))

        out: list[PoEntry] = [self._header_entry(existing, locale, plural_forms)]

        for key, value in messages.items():
            cached = by_key.get(key)
            source = template_by_key.get(key)
            if cached is None:
                ctxt, msgid = self._split_key(key)
                entry = PoEntry(msgid=msgid, msgctxt=ctxt)
                if source is not None:
                    entry.msgid_plural = source.msgid_plural
                    entry.extracted = list(source.extracted)
                    entry.references = list(source.references)
            else:
                # Copy before mutate: ``_read`` returns cached entries; a failed
                # write must not leave half-applied msgstr on the live cache.
                entry = _copy_po_entry(cached)

            plural = parse_icu_plural(value)
            if plural is not None:
                if entry.msgid_plural is None:
                    entry.msgid_plural = entry.msgid
                entry.msgstr_plural = {
                    i: icu_placeholder_to_printf(text, plural.variable)
                    for i, text in enumerate(plural.ordered(order))
                }
                entry.msgstr = ""
            else:
                entry.msgstr = value
                entry.msgstr_plural = {}

            # A machine translation is no longer fuzzy.
            entry.flags = [f for f in entry.flags if f != "fuzzy"]
            out.append(entry)

        # Keep obsolete (#~) entries not rewritten; drop live orphans so
        # merge_for_write pruning survives save (Wave 0.3).
        written = set(messages)
        out += [
            _copy_po_entry(e) for e in existing
            if e.key not in written
            and e.obsolete
            and not (e.msgid == "" and not e.msgctxt)
        ]

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            atomic_write_text(path, render_po(out))
        except Exception:
            self._bust_cache(path)
            raise
        self._bust_cache(path)

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _split_key(key: str) -> tuple[str | None, str]:
        if CONTEXT_SEPARATOR in key:
            ctxt, msgid = key.split(CONTEXT_SEPARATOR, 1)
            return ctxt, msgid
        return None, key

    @staticmethod
    def _plural_forms(header: str | None) -> str | None:
        if not header:
            return None
        for line in header.split("\n"):
            if line.lower().startswith("plural-forms:"):
                return line.split(":", 1)[1].strip()
        return None

    def _header_entry(self, existing: list[PoEntry], locale: str,
                      plural_forms: str | None) -> PoEntry:
        header = next((e for e in existing if e.msgid == "" and not e.msgctxt), None)
        if header is not None:
            if plural_forms and "Plural-Forms:" not in header.msgstr:
                header.msgstr = header.msgstr.rstrip("\n") + f"\nPlural-Forms: {plural_forms}\n"
            return header
        lines = [
            "MIME-Version: 1.0",
            "Content-Type: text/plain; charset=UTF-8",
            "Content-Transfer-Encoding: 8bit",
            f"Language: {locale}",
        ]
        if plural_forms:
            lines.append(f"Plural-Forms: {plural_forms}")
        return PoEntry(msgid="", msgstr="\n".join(lines) + "\n")
