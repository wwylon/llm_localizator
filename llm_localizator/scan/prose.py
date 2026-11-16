"""Whether a source literal is user-visible prose.

One check for every scanner. A letter is any Unicode letter, not ASCII.
Human languages do not get their own parser.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections import Counter

from ..core.quality import char_script

__all__ = ["grade", "is_prose","is_label_word", "is_lone_word", "is_short_label", "dominant_script", "LabelWordMatcher", "letter_mark_count"]

_CODE_LIKE = re.compile(
    r"^(?:"
    r"[A-Z_]+|"
    r"\w+\(\)|"
    r"https?://|"
    r"/\w|"
    r"[a-z][\w.-]*\.[a-z]{2,4}|"
    r"[\w.-]+\.(?:js|json|css|html|py|yaml|yml|png|svg|tsx|ts)|"
    r"[\w.-]+/[\w.-]+"
    r")$"
)

#: A string that is entirely one brace expression (a JSX expression, not prose).
_SINGLE_BRACE = re.compile(r"^\{[^{}]*\}$")


@functools.lru_cache(maxsize=16384)
def is_prose(text: str) -> bool:
    """True when *text* is plausibly shown to a user, in any writing system. Pure, so cached (M4: P8)."""
    text = unicodedata.normalize("NFC", text).strip()  # decomposed Hangul jamo and accents (macOS) must read as letters
    if not text or "{{" in text or _SINGLE_BRACE.match(text):
        return False
    if text.casefold() == "and/or":
        return True
    if _CODE_LIKE.match(text):
        return False
    letters = [ch for ch in text if unicodedata.category(ch).startswith("L")]
    if not letters:
        return False
    if any(ch.isspace() for ch in text) or text.endswith((".", "!", "?", ":", "…", "。", "！", "？", "：", "؟", "।", "։", "።")):
        return True  # any space (no-break, ideographic) or a sentence mark of any script
    scripts = [name for ch in letters if (name := char_script(ch))]
    if not scripts:
        return False
    top, count = Counter(scripts).most_common(1)[0]
    if top in {"cjk", "thai", "devanagari"} and count >= 2:
        return True
    return any(name != "latin" for name in scripts)


def grade(text: str, sink_strength: str = "shown", *, label=()) -> str | None:
    """The confidence of one literal, by how strongly its sink says it reaches a person (audit D4).

    * ``"shown"``: a sink already shows the text. ``"high"`` when it reads as prose or matches one of the *label*
      checks, else ``"medium"``.
    * ``"none"``: nothing but the text vouches for it. Prose is ``"high"``; a label shape (any *label* check) is
      ``"medium"``; anything else is not text (``None``).
    """
    if is_prose(text):
        return "high"
    matched = any(check(text) for check in label)
    if sink_strength == "shown":
        return "high" if matched else "medium"
    return "medium" if matched else None


def dominant_script(text: str) -> str:
    """The writing system most of the letters belong to (``latin``, ``cyrillic``, ``arabic``, ``cjk`` …), or ``""``."""
    counts = Counter(name for ch in text if unicodedata.category(ch)[0] == "L" and (name := char_script(ch)))
    return counts.most_common(1)[0][0] if counts else ""


def letter_mark_count(text: str) -> int:
    """Letters plus combining marks: Indic vowel signs, Thai tone marks and Arabic diacritics belong to the word."""
    return sum(1 for ch in text if unicodedata.category(ch)[0] in "LM")


def is_label_word(text: str, min_len: int = 3, max_len: int = 24) -> bool:
    """One capitalised word of any cased script: ``Save``, ``Błąd``, ``İptal``, ``Lưu``, ``Über``.

    ASCII-only checks miss every Polish, Czech, Turkish or Vietnamese label that starts or contains an accented
    letter. Caseless scripts need no check: a single word of Arabic or Thai is already prose.
    """
    t = unicodedata.normalize("NFC", text).strip()
    if not t or not (min_len <= len(t) <= max_len) or not t[0].isupper():
        return False
    return all(unicodedata.category(ch)[0] in "LM" or ch in "'’-" for ch in t) and letter_mark_count(t) >= min_len - 1


class LabelWordMatcher:
    """Drop-in for ``re.compile(...).match`` on the old ASCII label patterns."""

    def __init__(self, min_len: int = 3, max_len: int = 24) -> None:
        self.min_len, self.max_len = min_len, max_len

    def match(self, text: str):
        return self if is_label_word(text, self.min_len, self.max_len) else None


_NOT_WORDS = frozenset({"true", "false", "null", "none", "undefined", "default", "submit", "nil", "void"})


def is_short_label(text: str) -> bool:
    """A two-letter word or a short capitalised abbreviation: ``Ad`` (Azerbaijani "name"), ``Ms``, ``PM``, ``IPv4``, ``ID``.

    Too weak on its own (``Id`` is also a field name); only meaningful where the call or the element already says the
    text is shown to a person, like ``is_lone_word``.
    """
    t = unicodedata.normalize("NFC", text).strip()
    if not 2 <= len(t) <= 12 or not (t[0].isupper() or unicodedata.category(t[0]) == "Lo"):
        return False
    if not all(unicodedata.category(c)[0] in "LMN" or c in ".'’-/" for c in t) or letter_mark_count(t) < 2:
        return False
    return not re.search(r"[a-z][A-Z]", t) and t.lower() not in _NOT_WORDS


def is_lone_word(text: str) -> bool:
    """One word of three or more letters and nothing else: not an identifier (no digit, underscore, dot or camelCase).

    Only meaningful where the call already says the text is shown to a person: Spanish, Catalan, Finnish and others
    write month, day and language names in lower case, so ``Toast(…, "nedelja")`` is copy.
    """
    t = unicodedata.normalize("NFC", text).strip()
    if len(t) < 3 or not all(unicodedata.category(c)[0] in "LM" or c in "'’-/" for c in t) or t.startswith("/"):
        return False  # a slash joins two words ("Login/Register")
    return not re.search(r"[a-z][A-Z]", t) and t.lower() not in _NOT_WORDS
