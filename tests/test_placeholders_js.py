"""placeholders.js tokenizer (C-039), run through node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static" / "placeholders.js"

CASES = {
    "Hi {name}!": [("text", "Hi "), ("brace", "{name}"), ("text", "!")],
    "{n, plural, one {# item} other {# items}}": [("icu", "{n, plural, one {# item} other {# items}}")],
    "%s and %1$d": [("printf", "%s"), ("text", " and "), ("printf", "%1$d")],
    "100%% sure": [("text", "100%% sure")],
    "{{user}}": [("mustache", "{{user}}")],
    "<b>x</b>": [("html", "<b>"), ("text", "x"), ("html", "</b>")],
    "$t(key.a) :count": [("i18n", "$t(key.a)"), ("text", " "), ("named", ":count")],
    "12:30": [("text", "12:30")],
    "{open": [("text", "{open")],
    '<span translate="no">A <b>x</b></span>!': [("dnt", '<span translate="no">A <b>x</b></span>'), ("text", "!")],
}


def test_tokenize_matches_expected() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    script = (
        f"const p=require({json.dumps(str(JS))});"
        f"const c={json.dumps(list(CASES))};"
        "console.log(JSON.stringify(c.map(s=>p.tokenize(s).map(t=>[t.kind,t.text]))));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    got = json.loads(out)
    for (text, want), have in zip(CASES.items(), got):
        assert [list(w) for w in want] == have, text
