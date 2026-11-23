"""``check --format github`` prints one workflow error annotation per problem."""

from __future__ import annotations

from llm_localizator.cli.cmd_check import github_annotation


def test_annotation_has_a_title_and_escapes_newlines_and_percent() -> None:
    line = github_annotation("pl: 3 key(s) stale\n100% of de missing")
    assert line.startswith("::error title=llm-localizator check::")
    assert "\n" not in line
    assert "%0A" in line and "100%25 of de missing" in line
