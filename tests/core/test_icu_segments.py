"""ICU segment splitting and decomposition routing."""

from __future__ import annotations

from llm_localizator.core.icu import (
    is_bare_placeholder_span,
    needs_icu_decomposition,
    split_top_level_segments,
)

SOURCE = (
    "{players, plural, one {# player} other {# players}} online · "
    "{tables, plural, one {# table} other {# tables}}"
)


def test_livestats_needs_decomposition() -> None:
    assert needs_icu_decomposition(SOURCE)


def test_livestats_splits_three_segments() -> None:
    segs = split_top_level_segments(SOURCE)
    assert segs == [
        ("icu", "{players, plural, one {# player} other {# players}}"),
        ("text", " online · "),
        ("icu", "{tables, plural, one {# table} other {# tables}}"),
    ]


def test_simple_bare_placeholder_does_not_decompose() -> None:
    assert not needs_icu_decomposition("{players} players")


def test_single_plural_decomposes() -> None:
    assert needs_icu_decomposition("{n, plural, one {# item} other {# items}}")


def test_bare_placeholder_span_detection() -> None:
    assert is_bare_placeholder_span("{ns}")
    assert is_bare_placeholder_span("{round}")
    assert not is_bare_placeholder_span("{n, plural, one {# item} other {# items}}")


def test_mixed_string_splits_bare_and_plural() -> None:
    src = "Session total: NS {ns} · EW {ew} ({boards, plural, one {# board} other {# boards}})"
    segs = split_top_level_segments(src)
    assert ("icu", "{ns}") in segs
    assert ("icu", "{ew}") in segs
    assert any(s[1].startswith("{boards, plural") for s in segs if s[0] == "icu")

