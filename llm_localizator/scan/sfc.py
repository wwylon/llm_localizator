"""Vue and Svelte single-file components.

A ``.vue`` / ``.svelte`` file holds three languages. Scanning it as one string
soup reports Tailwind classes and SVG paths and misses the plain text between
tags. Here the file is split into a markup view and a script view with the same
line numbers (the other regions are blanked), and each goes to the scanner that
already understands that language. ``<style>`` is never scanned.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ScanResult, relative_posix
from .views import MarkupView, blank, scan_markup_view

__all__ = ["split_sfc", "scan_sfc_file", "scan_markup_view", "blank_markup_comments"]

_BLOCK = re.compile(r"<(script|style|i18n|docs)\b[^>]*>(.*?)</\1\s*>", re.S | re.I)
#: Svelte control flow and directives sit on their own lines: ``{#if x}``, ``{:else}``, ``{@html y}``.
_SVELTE_CTRL = re.compile(r"\{[#/:@][^{}]*\}")
#: A mustache expression inside text: ``{{ n }}`` (Vue) or ``{user.name}`` (Svelte).
_EXPR = re.compile(r"\{\{.*?\}\}|\{[^{}\n]*\}", re.S)


#: ``<!-- … -->`` and Jinja ``{# … #}`` comments: dead markup, never shown.
_MARKUP_COMMENT = re.compile(r"<!--.*?-->|\{#.*?#\}", re.S)


def blank_markup_comments(text: str) -> str:
    return _MARKUP_COMMENT.sub(lambda m: blank(m.group()), text)



def split_sfc(text: str) -> tuple[str, str]:
    """Return ``(markup, script)``: two views of ``text`` with identical line numbering."""
    markup = list(text)
    script = [c if c == "\n" else " " for c in text]
    for m in _BLOCK.finditer(text):
        tag = m.group(1).lower()
        a, b = m.start(), m.end()
        markup[a:b] = blank(text[a:b])
        if tag == "script":
            inner_a, inner_b = m.start(2), m.end(2)
            script[inner_a:inner_b] = text[inner_a:inner_b]
    return "".join(markup), "".join(script)


def _flatten_exprs(markup: str) -> str:
    """Control blocks vanish; inline expressions become a plain-word placeholder."""
    markup = _SVELTE_CTRL.sub(lambda m: blank(m.group()), markup)

    # Every expression becomes the slot word, short ones too (M2: ``{n}`` kept its braces in the text).
    return _EXPR.sub(MarkupView.slot, markup)


_PUG_LANG = re.compile(r"<template[^>]*lang\s*=\s*[\"'](?:pug|jade)[\"']", re.I)
_PUG_PIPE = re.compile(r"(?m)^([ 	]*)\|[ ]?(.*\S.*)$")


def _pug_pipes(markup: str) -> str:
    """Pug ``| plain text`` lines become ``<p>text</p>`` so the HTML rules see the text, not the pipe."""
    if not _PUG_LANG.search(markup):
        return markup
    return _PUG_PIPE.sub(lambda m: f"{m.group(1)}<p>{m.group(2).strip()}</p>", markup)


def scan_sfc_file(raw_scanner, path: Path, lines: list[str], result: ScanResult) -> None:
    rel = relative_posix(path, raw_scanner.root)
    markup, script = split_sfc("\n".join(lines))
    scan_markup_view(raw_scanner, rel, _flatten_exprs(_pug_pipes(markup)), result)
    if script.strip():
        raw_scanner.scan_text(rel, script.split("\n"), False, result)
