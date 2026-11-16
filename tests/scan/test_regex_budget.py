"""Every compiled pattern in ``llm_localizator/scan`` stays fast on adversarial input (M2).

Catastrophic backtracking (nested or overlapping quantifiers) grows exponentially with the number of repeated
tokens. At ~22 tokens an exponential pattern takes seconds, a linear one microseconds, so a generous budget
separates them without depending on machine load.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import time

import pytest

import llm_localizator.scan as scan_pkg

_BUDGET_S = 0.5
_N = 22
_ADVERSARIAL = [
    " ".join(["123"] * _N) + " x!",
    "1" * 2000 + "!",
    " " * 2000 + "x!",
    "a" * 2000 + "!",
    "-".join(["AB"] * _N) + "!",
    ",".join(["ab"] * _N) + " !",
    "M" + " 1" * (_N * 3) + " x!",
    ".".join(["a"] * _N) + "(",
    "a1" * 200 + "!",
    "{{" + " a" * _N,
    "<" + "a " * _N,
    "\\" * 200 + "!",
    "__" * 200 + "!",
    "(" * 60 + "a",
    "'" + "a'" * 60,
    '"' + "a\\\"" * 60,
    "Ab" * 200 + "!",
    "1px " * _N + "x",
    "$ " + "a " * _N + "|",
    "a: " * _N + "!",
]


def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    found = []
    prefix = scan_pkg.__name__ + "."
    for info in pkgutil.walk_packages(scan_pkg.__path__, prefix):  # subpackages too (scan/lexers, M3)
        module = importlib.import_module(info.name)
        for name, value in vars(module).items():
            if isinstance(value, re.Pattern) and isinstance(value.pattern, str):
                found.append((f"{info.name.removeprefix(prefix)}.{name}", value))
    return found


#: Patterns only ever used anchored (``.match``) or on a short window: an unanchored search is not their workload.
_ANCHORED_USE = {"js_tokenizer._NAME_BEFORE", "markup_text._CLOSING_TAG"}


@pytest.mark.parametrize(("name", "pattern"), _patterns(), ids=lambda v: v if isinstance(v, str) else "")
def test_pattern_is_not_catastrophic(name: str, pattern: re.Pattern[str]) -> None:
    run = pattern.match if name in _ANCHORED_USE else pattern.search
    for text in _ADVERSARIAL:
        start = time.perf_counter()
        run(text)
        elapsed = time.perf_counter() - start
        assert elapsed < _BUDGET_S, f"{name} took {elapsed:.2f}s on {text[:40]!r}…"
