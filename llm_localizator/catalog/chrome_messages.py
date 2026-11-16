"""Chrome / WebExtension ``_locales/<locale>/messages.json`` adapter (ADR-142).

Each entry is ``{"message": "...", "description": "...", "placeholders": {"name": {"content": "$1"}}}``.
The flat value is the ``message`` with named placeholders written the ICU way: ``$user$`` becomes ``{user}``
(only for names the entry declares; matching is case-insensitive as in Chrome) and ``$$`` becomes ``$``.
``description`` is the translator note. Saving keeps the placeholder blocks, descriptions and key order of
the existing file, copies them from the source file for new keys, and keeps the file's indentation.

Path template: ``_locales/{locale}/messages.json`` (``pt-BR`` is written ``pt_BR``). The extension's default
locale lives in the same layout, so the source locale is just another folder.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .base import Catalog, FlatMessages, Message
from .io import atomic_write_text

__all__ = ["ChromeMessagesCatalog"]

_HOLE = re.compile(r"\$(\w+)\$")


def _to_icu(message: str, placeholders: dict) -> str:
    names = {str(k).lower(): str(k) for k in placeholders}
    out = _HOLE.sub(lambda m: "{" + names[m.group(1).lower()] + "}" if m.group(1).lower() in names else m.group(0), message)
    return out.replace("$$", "$")


def _to_chrome(value: str, placeholders: dict) -> str:
    names = {str(k) for k in placeholders}
    parts = re.split(r"(\{\w+\})", value)
    out = []
    for part in parts:
        if re.fullmatch(r"\{\w+\}", part) and part[1:-1] in names:
            out.append(f"${part[1:-1]}$")
        else:
            out.append(part.replace("$", "$$"))
    return "".join(out)


def _indent_of(text: str):
    m = re.search(r'^\n?([ \t]+)"', text, re.M)
    if not m:
        return 2
    return "\t" if m.group(1).startswith("\t") else len(m.group(1))


class ChromeMessagesCatalog(Catalog):
    carries_notes = True  # "description"
    multi_namespace = False

    def namespaces(self) -> list[str]:
        return [""]

    def format_locale(self, locale: str) -> str:
        return locale.replace("-", "_")

    @staticmethod
    def locale_from_path(fragment: str) -> str:
        return fragment.replace("_", "-")

    def _read(self, path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{path}: messages.json must be an object")
        return data

    def load_entries(self, locale: str, namespace: str | None = None) -> dict[str, Message]:
        path = self.path_for(locale, namespace)
        if not path.exists():
            return {}
        out: dict[str, Message] = {}
        for key, entry in self._read(path).items():
            if not isinstance(entry, dict) or not isinstance(entry.get("message"), str):
                continue
            ph = entry.get("placeholders") if isinstance(entry.get("placeholders"), dict) else {}
            out[key] = Message(key=key, value=_to_icu(entry["message"], ph),
                               note=str(entry.get("description", "")), metadata={"placeholders": ph})
        return out

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        path = self.path_for(locale, namespace)
        if not path.exists():
            return {}
        return self._cached_load(path, lambda p: {k: m.value for k, m in self._entries_from(p).items()})

    def _entries_from(self, path: Path) -> dict[str, Message]:
        out: dict[str, Message] = {}
        for key, entry in self._read(path).items():
            if isinstance(entry, dict) and isinstance(entry.get("message"), str):
                ph = entry.get("placeholders") if isinstance(entry.get("placeholders"), dict) else {}
                out[key] = Message(key=key, value=_to_icu(entry["message"], ph))
        return out

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        indent: int | str = 2
        if path.exists():
            raw = path.read_text(encoding="utf-8-sig")
            existing = self._read(path)
            indent = _indent_of(raw)
        source: dict = {}
        if locale != self.source_locale:
            src = self.path_for(self.source_locale, namespace)
            if src.exists():
                source = self._read(src)
        out: dict = {}
        for key, value in messages.items():
            entry = dict(existing.get(key) or {})
            template = source.get(key) if isinstance(source.get(key), dict) else {}
            if not entry:
                entry = {k: v for k, v in template.items() if k in ("description", "placeholders")}
            ph = entry.get("placeholders") or template.get("placeholders") or {}
            old = entry.get("message")
            unchanged = isinstance(old, str) and _to_icu(old, ph) == value  # keep `$USER$` spelled as the file has it
            entry = {"message": old if unchanged else _to_chrome(value, ph),
                     **{k: v for k, v in entry.items() if k != "message"}}
            if "placeholders" in template and "placeholders" not in entry:
                entry["placeholders"] = template["placeholders"]
            out[key] = entry
        text = json.dumps(out, ensure_ascii=False, indent=indent) + "\n"
        atomic_write_text(path, text)
        self._bust_cache(path)
