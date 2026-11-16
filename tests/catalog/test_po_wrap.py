"""Optional msgmerge-style wrapping of PO output."""

from __future__ import annotations

from llm_localizator.catalog.gettext_po import PoEntry, parse_po, render_po


def _entries() -> list[PoEntry]:
    long = "word " * 40 + "end"
    return [
        PoEntry(msgid="short", msgstr="krótki"),
        PoEntry(msgid=long, msgstr=long + "\nsecond line"),
    ]


def test_default_render_is_unwrapped() -> None:
    assert max(len(l) for l in render_po(_entries()).splitlines()) > 150


def test_wrapped_render_respects_width_and_round_trips() -> None:
    out = render_po(_entries(), width=79)
    assert max(len(l) for l in out.splitlines()) <= 79
    assert 'msgid ""' in out and 'msgid "short"' in out
    back = parse_po(out)
    assert [(e.msgid, e.msgstr) for e in back] == [(e.msgid, e.msgstr) for e in _entries()]
