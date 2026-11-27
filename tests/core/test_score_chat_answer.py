"""Scores must not rate a chat answer or leaked prompt text as a good translation.

aya-expanse:8b answered "The translation of "Trigger" into Polish is "Wyzwalacz"." while
the Ollama provider dropped the system prompt, and the scorer gave it 1.0.
"""
import pytest

from llm_localizator.core.quality import score_translation
from llm_localizator.core.validate import check_chat_answer
from llm_localizator.pipeline.judge import quality_from_judge

LEAKS = [
    ("Trigger", 'The translated string "Trigger" from English to Polish is "Wyzwalacz".'),
    ("Test set", 'The translation of "Test set" into Polish is **zestaw testowy**.'),
    ("Locale", "اللغة (اترك فارغًا لاستخدام اللغة الافتراضية للمشروع)"),
    ("Key:", "Gdy jest włączone, tekst instrukcji projektu jest tłumaczony na język docelowy."),
]


@pytest.mark.parametrize("src,out", LEAKS)
def test_heuristic_score_fails_leaks(src: str, out: str) -> None:
    q = score_translation(src, out, "pl" if out.isascii() or "ł" in out else "ar",
                          back_translated=src)
    assert q.score == 0.0, q.signals


@pytest.mark.parametrize("src,out", LEAKS[:2])
def test_judge_score_fails_leaks(src: str, out: str) -> None:
    q = quality_from_judge(source=src, translated=out, locale="pl", glossary={},
                           judgment={"accuracy": 5, "fluency": 5})
    assert q.score == 0.0 and q.scorer == "lqs"


@pytest.mark.parametrize("src,out", [
    ("Trigger", "Wyzwalacz"),
    ("Translate this key", "Przetłumacz ten klucz"),
    ("The translation of this key is stale", "Tłumaczenie tego klucza jest nieaktualne"),
    ("Save changes to disk", "Änderungen auf die Festplatte speichern"),
])
def test_real_translations_pass(src: str, out: str) -> None:
    assert check_chat_answer(src, out) is None
    assert score_translation(src, out, "pl" if "ä" not in out else "de").score > 0
