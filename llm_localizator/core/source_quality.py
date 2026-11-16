"""Deterministic source-authoring checks. No I/O and no project layout."""

from __future__ import annotations

import re

__all__ = [
    "duplicate_source_findings",
    "placeholder_without_note",
    "raw_html_in_plain",
    "pseudo_text",
    "source_style_findings",
]

_HTML_TAG = re.compile(r"</?[A-Za-z][^>\n]*>")
_SLOT = re.compile("\uE000(\\d+)\uE001")

_PSEUDO_MAP = str.maketrans({
    "a": "á", "b": "ƀ", "c": "ç", "d": "ð", "e": "é",
    "f": "ƒ", "g": "ĝ", "h": "ĥ", "i": "í", "j": "ĵ",
    "k": "ķ", "l": "ľ", "m": "ɱ", "n": "ñ", "o": "ó",
    "p": "þ", "q": "ǫ", "r": "ŕ", "s": "š", "t": "ť",
    "u": "ú", "v": "ṽ", "w": "ŵ", "x": "ẋ", "y": "ý", "z": "ž",
    "A": "Á", "B": "Ɓ", "C": "Ç", "D": "Ð", "E": "É",
    "F": "Ƒ", "G": "Ĝ", "H": "Ĥ", "I": "Í", "J": "Ĵ",
    "K": "Ķ", "L": "Ľ", "M": "Ɱ", "N": "Ñ", "O": "Ó",
    "P": "Þ", "Q": "Ǫ", "R": "Ŕ", "S": "Š", "T": "Ť",
    "U": "Ú", "V": "Ṽ", "W": "Ŵ", "X": "Ẋ", "Y": "Ý", "Z": "Ž",
})


def duplicate_source_findings(
    rows: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """One finding per repeated source, attached to the first key.

    Each item is ``(namespace, key, source)``. The message names every key
    in the group. Empty sources are ignored.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for namespace, key, source in rows:
        if not isinstance(source, str) or not source:
            continue
        groups.setdefault(source, []).append((namespace, key))
    findings: list[tuple[str, str, str]] = []
    for keys in groups.values():
        unique = sorted(set(keys))
        if len(unique) < 2:
            continue
        first_ns, first_key = unique[0]
        named = [
            f"{ns}.{key}" if ns else key for ns, key in unique
        ]
        findings.append((
            first_ns,
            first_key,
            "duplicate source text on " + " and ".join(named),
        ))
    return findings


# Deliberately narrow: "Log in", "Sort by" and "Email:" are ordinary UI labels, not fragments.
_FRAGMENT_TAIL = re.compile(r"(?:,|\b(?:and|or|of|to|the|a|an))\s*$", re.IGNORECASE)
_FRAGMENT_HEAD = re.compile(r"^(?:and|or|of)\s", re.IGNORECASE)
_SERIAL = re.compile(r"\b[^,.;:!?]+, [^,.;:!?]+, (?:and|or) ")
_NO_SERIAL = re.compile(r"\b[^,.;:!?]+, [^,.;:!?]+[^,] (?:and|or) ")
_MAX_STYLE_WORDS = 8
_MIN_STYLE_SAMPLE = 8
_MINORITY = 0.25


def _is_prose_line(text: str) -> bool:
    return bool(text) and "\n" not in text and "<" not in text and len(text.split()) <= _MAX_STYLE_WORDS


def _minority(flags: dict[tuple[str, str], bool]) -> list[tuple[str, str]]:
    """Keys of the rarer style, when both styles occur and one is clearly the exception."""
    yes = [k for k, v in flags.items() if v]
    no = [k for k, v in flags.items() if not v]
    if not yes or not no or len(flags) < _MIN_STYLE_SAMPLE:
        return []
    small = yes if len(yes) <= len(no) else no
    return small if len(small) / len(flags) <= _MINORITY else []


def source_style_findings(
    rows: list[tuple[str, str, str]],
) -> list[tuple[str, str, str, str]]:
    """Authoring problems in the source catalogue that make translation harder.

    Each item of ``rows`` is ``(namespace, key, source)``; each finding is
    ``(namespace, key, code, message)``.

    * V35: a string that reads as one piece of a longer sentence (ends in a
      conjunction, comma or colon, or starts with a preposition). Translators
      cannot reorder pieces.
    * V36: short strings end with a full stop in some places and not in others.
    * V37: lists are written with the serial comma in some places and without in others.
    """
    findings: list[tuple[str, str, str, str]] = []
    period: dict[tuple[str, str], bool] = {}
    serial: dict[tuple[str, str], bool] = {}
    for ns, key, source in rows:
        if not isinstance(source, str):
            continue
        text = source.strip()
        if not text:
            continue
        padded = source != source.strip(" \t")
        if len(text.split()) >= 2 and (padded or _FRAGMENT_TAIL.search(text) or _FRAGMENT_HEAD.match(text)):
            findings.append((
                ns, key, "V35",
                "reads as a fragment of a longer sentence; make it a whole sentence "
                "with placeholders so it can be translated in one piece",
            ))
        if _is_prose_line(text) and len(text.split()) >= 2 and not text.endswith(("..", "\u2026")):
            body = text[:-1] if text.endswith(".") else text
            if body and body[-1].isalnum():
                period[(ns, key)] = text.endswith(".")
        if _SERIAL.search(text):
            serial[(ns, key)] = True
        elif _NO_SERIAL.search(text):
            serial[(ns, key)] = False
    for ns, key in _minority(period):
        has = period[(ns, key)]
        findings.append((
            ns, key, "V36",
            "ends with a full stop but most short strings do not" if has
            else "has no final full stop but most short strings have one",
        ))
    for ns, key in _minority(serial):
        has = serial[(ns, key)]
        findings.append((
            ns, key, "V37",
            "list uses the serial comma but most lists do not" if has
            else "list has no serial comma but most lists have one",
        ))
    return findings


def placeholder_without_note(
    source: str,
    *,
    has_placeholder: bool,
    has_note: bool,
) -> str | None:
    """A placeholder with no context note. A plain sentence stays silent."""
    if source and has_placeholder and not has_note:
        return "placeholder with no context note"
    return None


def raw_html_in_plain(source: str, *, marked_html: bool) -> str | None:
    """An HTML tag in a message the context note does not mark as HTML."""
    if marked_html or not source:
        return None
    if _HTML_TAG.search(source):
        return "raw HTML in a plain message"
    return None


_ICU_COMPLEX = re.compile(r"\s*[\w-]+\s*,\s*(?:plural|select|selectordinal)\s*,")
_ICU_SELECTOR = re.compile(r"\s*(?:offset\s*:\s*\d+\s*)?(=?[\w-]+)\s*")


def _matching_brace(text: str, open_at: int) -> int:
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _pseudo_icu(text: str, xform) -> str:
    """Apply *xform* to the message text only; keep ICU syntax intact.

    ``{name}`` / ``{n, number}`` stay as they are; ``{n, plural|select, sel {...}}``
    keeps its header and selectors while each branch body is transformed
    recursively (``#`` survives because *xform* leaves non-letters alone).
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        brace = text.find("{", i)
        if brace < 0:
            out.append(xform(text[i:]))
            break
        out.append(xform(text[i:brace]))
        close = _matching_brace(text, brace)
        if close < 0:
            out.append(xform(text[brace:]))
            break
        inner = text[brace + 1:close]
        head = _ICU_COMPLEX.match(inner)
        if not head:
            out.append(text[brace:close + 1])  # simple placeholder
        else:
            out.append("{" + inner[: head.end()])
            rest = inner[head.end():]
            k = 0
            while k < len(rest):
                sel = _ICU_SELECTOR.match(rest, k)
                if not sel or sel.end() >= len(rest) or rest[sel.end()] != "{":
                    out.append(rest[k:])  # not well-formed: keep the remainder as-is
                    break
                out.append(rest[k:sel.end()])
                body_end = _matching_brace(rest, sel.end())
                if body_end < 0:
                    out.append(rest[sel.end():])
                    break
                out.append("{" + _pseudo_icu(rest[sel.end() + 1:body_end], xform) + "}")
                k = body_end + 1
            out.append("}")
        i = close + 1
    return "".join(out)


def pseudo_text(
    value: str,
    tokens: set[str] | None = None,
    *,
    length_factor: float = 1.4,
    style: str = "accents",
) -> str:
    """Transform catalogue text for visual leftover hunting.

    * ``accents`` (default, en-XA): accent letters and pad — length stress.
    * ``xxxx`` (en-XX): same-length run of ``X``, placeholders/tags preserved —
      remaining readable Latin on the page is hardcoded or missing a key.
    """
    slots: list[str] = []

    def stash(piece: str) -> str:
        slots.append(piece)
        return f"\uE000{len(slots) - 1}\uE001"

    masked = _HTML_TAG.sub(lambda match: stash(match.group(0)), value or "")
    # ICU structure ({name}, {n, plural, one {...}}) is handled by _pseudo_icu.
    # Only placeholder *syntax* tokens (printf %s, {{x}}, :name) are masked here:
    # a bare argument name such as "version" must not protect the same word in
    # the prose ("Current version: {version}"), nor the "n" inside "one".
    for token in sorted(tokens or (), key=len, reverse=True):
        if token and not re.fullmatch(r"\w+", token) and token in masked:
            masked = masked.replace(token, stash(token))

    def restore(match: re.Match[str]) -> str:
        return slots[int(match.group(1))]

    kind = (style or "accents").strip().lower()
    if kind in ("xxxx", "x", "marker"):
        def xform(segment: str) -> str:
            out: list[str] = []
            i = 0
            n = len(segment)
            while i < n:
                if segment[i] == "\uE000":
                    j = segment.find("\uE001", i)
                    if j < 0:
                        out.append(segment[i:])
                        break
                    out.append(segment[i : j + 1])
                    i = j + 1
                    continue
                out.append("X" if segment[i].isalpha() else segment[i])
                i += 1
            return "".join(out)

        return _SLOT.sub(restore, _pseudo_icu(masked, xform))

    accented = _pseudo_icu(masked, lambda segment: segment.translate(_PSEUDO_MAP))
    restored = _SLOT.sub(restore, accented)
    target = int(len(restored) * length_factor)
    pad = target - len(restored) - 2
    return "⟦" + restored + ("~" * pad if pad > 0 else "") + "⟧"
