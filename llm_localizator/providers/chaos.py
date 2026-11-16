"""A provider that fails the way small local models fail (test support, ADR-5 family).

``NullProvider`` answers correctly or not at all. Real models answer wrongly in a handful
of repeatable ways, and a catalogue written from those answers is what the bridge scan
found: Chinese in an Arabic value, an English word in the middle, a sentence cut off at a
comma, the source echoed back. ``ChaosProvider`` reproduces those, seeded, and records which
fault hit which source so a test can ask "which injected defects reached the catalogue?".
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable

from ._prompt_utils import numbered_lines as _numbered_lines
from .base import CompletionRequest, Provider

__all__ = ["ChaosProvider", "FAULTS"]

_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_CJK = "次级人员"  # four Chinese characters, as qwen2.5:7b emitted for Arabic


def _cjk_bleed(source: str, text: str, _rng) -> str:
    return f"{text} {_CJK}"


def _latin_leftover(source: str, text: str, _rng) -> str:
    words = text.split()
    if len(words) < 2:
        return f"Access {text}"
    words.insert(len(words) // 2, "Access")
    return " ".join(words)


def _truncate(source: str, text: str, _rng) -> str:
    """Cut at a comma or apostrophe and leave a backslash, as an escaped-comma CSV import did."""
    for mark in (",", "'", "—", " "):
        cut = text.find(mark, max(1, len(text) // 3))
        if cut > 0:
            return text[:cut] + "\\"
    return text[: max(1, len(text) // 2)] + "\\"


def _echo_source(source: str, _text: str, _rng) -> str:
    return source


def _drop_placeholder(source: str, text: str, _rng) -> str:
    return _PLACEHOLDER.sub("", text, count=1)


def _extra_prose(source: str, text: str, _rng) -> str:
    return f"Here is the translation: {text}"


def _empty(_source: str, _text: str, _rng) -> str:
    return ""


#: Per-string faults. ``json_garbage`` is applied to the whole array instead.
FAULTS: dict[str, Callable[[str, str, random.Random], str]] = {
    "cjk_bleed": _cjk_bleed,
    "latin_leftover": _latin_leftover,
    "truncate": _truncate,
    "echo_source": _echo_source,
    "drop_placeholder": _drop_placeholder,
    "extra_prose": _extra_prose,
    "empty": _empty,
}


class ChaosProvider(Provider):
    """Translate with ``translator`` and corrupt a seeded share of the answers.

    Parameters
    ----------
    translator:
        ``source -> good translation``. Defaults to a ``[xx]`` tag.
    faults:
        ``{fault name: probability}``. One draw per string; the first fault whose
        cumulative probability covers it is applied. ``wrong_term`` uses ``wrong_terms``.
    wrong_terms:
        ``{correct: wrong}`` substitutions for the ``wrong_term`` fault.
    json_garbage:
        Probability that a whole batch answer is wrapped in prose and a code fence.
    """

    def __init__(
        self,
        translator: Callable[[str], str] | None = None,
        *,
        faults: dict[str, float] | None = None,
        wrong_terms: dict[str, str] | None = None,
        json_garbage: float = 0.0,
        seed: int = 0,
    ) -> None:
        unknown = set(faults or {}) - set(FAULTS) - {"wrong_term"}
        if unknown:
            raise ValueError(f"unknown fault(s): {', '.join(sorted(unknown))}")
        if (faults or {}).get("wrong_term") and not wrong_terms:
            raise ValueError("fault 'wrong_term' needs wrong_terms={correct: wrong}")
        self.translator = translator or (lambda source: f"[xx] {source}")
        self.faults = dict(faults or {})
        self.wrong_terms = dict(wrong_terms or {})
        self.json_garbage = json_garbage
        self.rng = random.Random(seed)
        self.calls: list[CompletionRequest] = []
        #: ``(source, fault, output)`` for every string a fault changed.
        self.injected: list[tuple[str, str, str]] = []

    def _apply(self, source: str) -> str:
        good = self.translator(source)
        draw = self.rng.random()
        edge = 0.0
        for name, probability in self.faults.items():
            edge += probability
            if draw >= edge:
                continue
            if name == "wrong_term":
                out = good
                for right, wrong in self.wrong_terms.items():
                    out = out.replace(right, wrong)
            else:
                out = FAULTS[name](source, good, self.rng)
            if out != good:
                self.injected.append((source, name, out))
            return out
        return good

    def complete(self, request: CompletionRequest) -> str:
        self.calls.append(request)
        if "back to English" in request.prompt:
            line = request.prompt.strip().splitlines()[-1]
            return line[5:].strip() if line.startswith("[xx] ") else line.strip()
        if request.schema is not None:
            answers = [self._apply(source) for source in _numbered_lines(request.prompt)]
            body = json.dumps(answers, ensure_ascii=False)
            if self.json_garbage and self.rng.random() < self.json_garbage:
                self.injected.append(("<batch>", "json_garbage", body))
                return f"Sure! Here is the JSON:\n```json\n{body}\n```\nLet me know if you need more."
            return body
        last = request.prompt.strip().splitlines()[-1] if request.prompt.strip() else ""
        return self._apply(last)

    @property
    def call_count(self) -> int:
        return len(self.calls)
