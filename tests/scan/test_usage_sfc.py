"""Key usage in Vue/Svelte/i18n.__ call styles (so ``check-keys`` does not call used keys unused)."""

from __future__ import annotations

import pytest

from llm_localizator.scan.usage_calls import KeyUsage, collect_key_usage

CASES = [
    ("<p>{{ $t('ok') }}</p>", "ok"),
    ("<p>{{ $t('home.title') }}</p>", "home.title"),
    ("const m = this.$t('a.b')", "a.b"),
    ("<p>{$_('words.kick')}</p>", "words.kick"),
    ("<p>{$format('words.kick')}</p>", "words.kick"),
]


@pytest.mark.parametrize(("src", "key"), CASES)
def test_call_styles_register_key_usage(src: str, key: str) -> None:
    usage = KeyUsage()
    collect_key_usage(src, "x.vue", usage)
    assert key in usage.keys
