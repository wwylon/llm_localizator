"""PHP adapter refuses to rewrite files holding entries its parser cannot read."""

import pytest

from llm_localizator.catalog.php_array import _unparsed_entries


def test_plain_entries_are_readable():
    text = "<?php\nreturn [\n    'a' => 'x',\n    'n' => [\n        'b' => \"y\",\n    ],\n];\n"
    assert _unparsed_entries(text) == []


def test_multiline_and_call_values_are_flagged():
    text = "<?php\nreturn [\n    'a' => 'x' . 'y',\n    'b' => __('c'),\n    // 'c' => 'skip',\n];\n"
    assert len(_unparsed_entries(text)) == 1  # concatenation is readable; __() is not


def test_save_refuses_lossy_file(tmp_path):
    from llm_localizator.catalog import build_catalog

    path = tmp_path / "en" / "auth.php"
    path.parent.mkdir()
    original = "<?php\nreturn [\n    'a' => 'x',\n    'b' => __('c'),\n];\n"
    path.write_text(original, encoding="utf-8")
    cat = build_catalog("php-array", tmp_path, "{locale}/{namespace}.php")
    with pytest.raises(ValueError, match="cannot read"):
        cat.save("en", "auth", {"a": "x"})
    assert path.read_text(encoding="utf-8") == original


def test_tokenizer_reads_array_syntax_inline_pairs_comments_and_concat():
    from llm_localizator.catalog.php_array import _parse_php

    text = (
        "<?php\n// 'x' => 'no'\nreturn array(\n"
        "  'a' => 'A', \"b\" => \"B\\n\", # note\n"
        "  'n' => ['x' => 'X' . ' more'],\n"
        "  /* 'gone' => 'z' */\n"
        "  'it\\'s' => 'ok',\n);\n"
    )
    assert _parse_php(text) == {"a": "A", "b": "B\n", "n.x": "X more", "it's": "ok"}
