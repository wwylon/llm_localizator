"""V32: sentence punctuation after a URL or email is not part of the literal."""

from __future__ import annotations

from llm_localizator.core.validate import check_literal_presence


def test_url_followed_by_period_is_not_required_with_the_period() -> None:
    assert check_literal_presence("See https://x.example.com/a.", "Zobacz https://x.example.com/a") is None


def test_url_in_parentheses_and_with_comma() -> None:
    assert check_literal_presence("(https://x.example.com/a), ok", "https://x.example.com/a - ok") is None


def test_email_followed_by_period() -> None:
    assert check_literal_presence("Write to me@x.org.", "Napisz: me@x.org") is None


def test_missing_url_still_reported() -> None:
    msg = check_literal_presence("See https://x.example.com/a.", "Zobacz stronę")
    assert msg and "https://x.example.com/a" in msg
    assert "a." not in msg.split(": ", 1)[1]


def test_snake_case_identifier_kept_verbatim() -> None:
    assert check_literal_presence("use max_items here", "uzyj max_items tutaj") is None
    assert check_literal_presence("use max_items here", "uzyj max items tutaj")


def test_char_script_cached_results_unchanged() -> None:
    from llm_localizator.core.scripts import char_script

    assert char_script("a") == char_script("a")
    assert char_script("Ж") == "cyrillic"
    assert char_script("1") is None
