"""ICU plural parse/build, including selectordinal."""

from llm_localizator.core.plurals import PluralSet, build_icu_plural, parse_icu_plural


def test_plural_round_trip_keeps_keyword() -> None:
    text = "{n, plural, one {# file} other {# files}}"
    parsed = parse_icu_plural(text)
    assert parsed is not None
    assert parsed.keyword == "plural"
    assert parse_icu_plural(build_icu_plural(parsed)) == parsed


def test_selectordinal_round_trip_does_not_become_plural() -> None:
    text = "Take the {n, selectordinal, one {#st} two {#nd} few {#rd} other {#th}} turn"
    parsed = parse_icu_plural(text)
    assert parsed is not None
    assert parsed.keyword == "selectordinal"
    rebuilt = build_icu_plural(parsed)
    assert "selectordinal" in rebuilt
    assert ", plural," not in rebuilt
    assert parse_icu_plural(rebuilt) == parsed


def test_select_is_not_a_plural_set() -> None:
    text = "{gender, select, male {he} female {she} other {they}}"
    assert parse_icu_plural(text) is None


def test_unknown_keyword_is_rejected() -> None:
    try:
        PluralSet("n", {"other": "x"}, keyword="select")
    except ValueError as exc:
        assert "selectordinal" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cldr_corrections() -> None:
    from llm_localizator.core.plural import plural_category as pc

    assert pc("sr", 5) == "other" and pc("sr", 3) == "few" and pc("bs", 21) == "one"
    assert pc("sl", 1.5) == "few"
    assert pc("fr", 0) == "one" and pc("fr", 1.5) == "one" and pc("fr", 2) == "other"
    assert pc("pt-BR", 0) == "one" and pc("pt-PT", 0) == "other"
    assert pc("hi", 0) == "one" and pc("hi", 0.5) == "one" and pc("hi", 2) == "other"
