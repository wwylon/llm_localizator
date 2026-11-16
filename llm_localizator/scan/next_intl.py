"""next-intl / react-intl scanner for TSX sources.

Two jobs: recover ``t('key')`` call sites as translator context, and flag
user-visible JSX text that never goes through ``t()``.

The hardcoded-string detector is deliberately conservative. A false positive
costs a developer real time chasing a non-bug, so anything ambiguous is left
alone: text with no letters, single words that are probably identifiers,
anything inside a code/pre element, and any line with a real ``t(`` call
(word-boundary; ``setHeight(`` does not count).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.languages import language
from .base import HardcodedString, Scanner, ScanResult, Usage, line_number, relative_posix
from .js_context import context_pass, markup_text_pass, single_word_text
from .patterns import HTML_TEXT, T_PRESENT
from .prose import is_prose
from .usage_calls import routed_re

__all__ = ["NextIntlScanner"]

_T_CALL = re.compile(r"""\bt\(\s*["']([\w./]+)["']\s*(?:,|\))""")
_T_PRESENT = T_PRESENT
_USE_TRANSLATIONS = re.compile(
    r"""(?:useTranslations|getTranslations)\(\s*["']([\w./]+)["']\s*\)"""
)
_COMPONENT = re.compile(r"""(?:function|const)\s+([A-Z]\w+)""")

# JSX text between tags. The prose helper decides; do not require ASCII.
_JSX_TEXT = HTML_TEXT
# Static text fragments in mixed JSX content: } text < and > text {
_JSX_TRAIL = re.compile(r"\}\s*([^<>{}\n]{3,}?)\s*<")
_JSX_LEAD  = re.compile(r">\s*([^<>{}\n]{3,}?)\s*\{")
# Single capitalised word in a widget tag — reliable UI label signal.
_JSX_WIDGET_WORD = re.compile(
    r"<(?:button|a|label|li|option|th|td)\b[^>]*>\s*([A-Z][a-zA-Z]{2,})\s*</"
)
# Attributes that render to the user.
_USER_ATTR = re.compile(
    r"""\b(placeholder|title|alt|aria-label|label)\s*=\s*["']([^"'{}]+?)["']""",
    re.DOTALL,
)

_IGNORE_TAGS = ("<code", "<pre", "<script", "<style", "<svg")

# Lines already routed through a known i18n call or wrapper (not next-intl).
# Covers react-i18next, react-intl, vue-i18n, rails, laravel, django, angular.
_ALREADY_ROUTED = routed_re("next_intl_line")


# TS generics and expressions also sit between ``>``/``}`` and ``<``/``{``:
# ``}: React.ComponentProps<typeof X>``, ``= useState<string>(``, ``): Promise<T> {``.
_CODE_FRAGMENT = re.compile(
    r"^[:=)(,|&?.\]\[]|[=;]|=>|&&|\|\||\)\s*$|\b(?:typeof|keyof|extends|const|let|return|async|await)\b"
    r"|^\w+(?:\.\w+)+$|\w\(|\bReact\."
)


def _looks_like_code(text: str) -> bool:
    if text.endswith(";") and any(ord(ch) > 0x2FF and ch.isalpha() for ch in text):
        text = text[:-1]  # Greek writes its question mark as ';'
    return bool(_CODE_FRAGMENT.search(text))


class NextIntlScanner(Scanner):
    @property
    def routing_note(self) -> str:
        return (
            "Replace the literal with t() using this file's useTranslations or "
            "getTranslations namespace. If the file has none, add one that matches "
            "neighbouring screens."
        )

    @property
    def file_glob(self) -> str:
        ext = language("tsx").extensions[0]
        return f"**/*{ext}"

    def scan_file(self, path: Path, lines: list[str], result: ScanResult) -> None:
        rel = relative_posix(path, self.root)

        namespaces: set[str] = set()
        for line in lines:
            namespaces.update(_USE_TRANSLATIONS.findall(line))

        before = len(result.hardcoded)
        component = "unknown"
        for lineno, line in enumerate(lines, 1):
            match = _COMPONENT.search(line)
            if match:
                component = match.group(1)

            for key in _T_CALL.findall(line):
                namespace, bare = self._split(key, namespaces)
                if namespace is None:
                    continue  # several namespaces in one file and no prefix
                result.usages.append(Usage(namespace, bare, rel, lineno, component))

            self._check_hardcoded(line, rel, lineno, result)

        text = "\n".join(lines)
        self._check_multiline_attrs(text, lines, rel, result)
        context_pass(text, rel, result, first_hit=before)
        markup_text_pass(text, rel, result, first_hit=before)

    @staticmethod
    def _split(key: str, namespaces: set[str]) -> tuple[str | None, str]:
        """Map a t() argument to a stored namespace and a bare key.

        A known namespace wins, including ``admin/users`` written as
        ``admin.users`` in the call. Otherwise a dotted key still splits on
        the first dot, which is what flat catalogues already depend on.
        """
        best: tuple[int, str, str] | None = None
        for ns in namespaces:
            forms = [ns]
            if "/" in ns:
                forms.append(ns.replace("/", "."))
            for form in forms:
                prefix = form + "."
                if key.startswith(prefix) and (best is None or len(form) > best[0]):
                    best = (len(form), ns, key[len(prefix):])
        if best is not None:
            return best[1], best[2]
        if "." in key:
            namespace, bare = key.split(".", 1)
            stored = namespace.replace(".", "/")
            if stored in namespaces:
                return stored, bare
            return namespace, bare
        if len(namespaces) == 1:
            return next(iter(namespaces)), key
        return None, key

    @staticmethod
    def _check_hardcoded(line: str, rel: str, lineno: int, result: ScanResult) -> None:
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "*", "/*")):
            return
        if _T_PRESENT.search(line) or any(tag in line for tag in _IGNORE_TAGS):
            return
        if _ALREADY_ROUTED.search(line):
            return

        for match in _JSX_TEXT.finditer(line):
            text = match.group(1).strip()
            if is_prose(text) and not _looks_like_code(text):
                result.hardcoded.append(HardcodedString(
                    text, rel, lineno, confidence="high",
                ))
            elif single_word_text(text, line, match.start(1)) and not _JSX_WIDGET_WORD.search(line):
                result.hardcoded.append(HardcodedString(
                    text, rel, lineno, "single-word JSX text", confidence="medium",
                ))

        for match in _JSX_WIDGET_WORD.finditer(line):
            text = match.group(1)
            result.hardcoded.append(HardcodedString(
                text, rel, lineno,
                "single-word label in UI widget tag",
                confidence="medium",
            ))

        for match in _JSX_TRAIL.finditer(line):
            text = match.group(1).strip()
            if is_prose(text) and not _looks_like_code(text):
                result.hardcoded.append(HardcodedString(
                    text, rel, lineno,
                    "static text after a JSX expression — wrap in t() with ICU placeholder",
                    confidence="medium",
                ))

        for match in _JSX_LEAD.finditer(line):
            text = match.group(1).strip()
            if is_prose(text) and not _looks_like_code(text):
                result.hardcoded.append(HardcodedString(
                    text, rel, lineno,
                    "static text before a JSX expression — wrap in t() with ICU placeholder",
                    confidence="medium",
                ))

        for attr, value in _USER_ATTR.findall(line):
            if "\n" in value:
                continue
            value = value.strip()
            if len(value) < 3 or not is_prose(value):
                continue
            result.hardcoded.append(HardcodedString(
                value, rel, lineno,
                f"{attr} attribute is user-visible and not routed through t()",
                confidence="high",
            ))

    @staticmethod
    def _check_multiline_attrs(
        text: str, lines: list[str], rel: str, result: ScanResult,
    ) -> None:
        for match in _USER_ATTR.finditer(text):
            value = match.group(2)
            if "\n" not in value and "\n" not in text[match.start():match.end()]:
                continue
            lineno = line_number(text, match.start())
            line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
            if _T_PRESENT.search(line):
                continue
            cleaned = " ".join(value.split())
            if len(cleaned) < 3 or not is_prose(cleaned):
                continue
            result.hardcoded.append(HardcodedString(
                cleaned, rel, lineno,
                f"{match.group(1)} attribute is user-visible and not routed through t()",
                confidence="high",
            ))
