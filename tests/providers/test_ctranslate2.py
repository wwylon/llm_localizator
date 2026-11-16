"""CTranslate2 provider (Wave 3b) — hermetic, no native wheel required."""

from __future__ import annotations

import pytest

from llm_localizator.providers.base import CompletionRequest, ProviderError
from llm_localizator.providers.ctranslate2 import CTranslate2Provider, madlad_target_prefix
from llm_localizator.providers import build_provider
from llm_localizator.projects.config import ProviderConfig


def test_madlad_target_prefix() -> None:
    assert madlad_target_prefix("pl") == "<2pl>"
    assert madlad_target_prefix("pt-BR") == "<2pt_br>"
    assert madlad_target_prefix("zh-TW") == "<2zh_tw>"
    assert madlad_target_prefix("fr-CA") == "<2fr_CA>"
    assert madlad_target_prefix("pt") == "<2pt>"
    assert madlad_target_prefix("EN") == "<2en>"


def test_build_provider_ctranslate2() -> None:
    p = build_provider(ProviderConfig(kind="ctranslate2", model_path="/models/madlad"))
    assert isinstance(p, CTranslate2Provider)
    assert p.model_path == "/models/madlad"


def test_ctranslate2_complete_with_stub(tmp_path) -> None:
    class FakeSpm:
        def EncodeAsPieces(self, text: str) -> list[str]:
            return text.split()

        def DecodePieces(self, pieces: list[str]) -> str:
            return " ".join(pieces)

    class FakeResult:
        hypotheses = [["Witaj", "świecie"]]

    class FakeTranslator:
        def translate_batch(self, encoded, **kwargs):
            assert encoded
            assert encoded[0][0].startswith("<2")
            return [FakeResult()]

    provider = CTranslate2Provider(model_path=str(tmp_path))
    provider._translator = FakeTranslator()
    provider._spm = FakeSpm()
    provider._loaded_path = str(tmp_path)

    out = provider.complete(CompletionRequest(
        prompt="ignored",
        model=str(tmp_path),
        source_texts=["Hello world"],
        target_locale="pl",
    ))
    assert out == "Witaj świecie"


def test_ctranslate2_empty_hypothesis_is_provider_error(tmp_path) -> None:
    class FakeSpm:
        def EncodeAsPieces(self, text: str) -> list[str]:
            return text.split()

        def DecodePieces(self, pieces: list[str]) -> str:
            return " ".join(pieces)

    class FakeResult:
        hypotheses = [[]]

    class FakeTranslator:
        def translate_batch(self, encoded, **kwargs):
            return [FakeResult()]

    provider = CTranslate2Provider(model_path=str(tmp_path))
    provider._translator = FakeTranslator()
    provider._spm = FakeSpm()
    provider._loaded_path = str(tmp_path)

    with pytest.raises(ProviderError, match="empty hypothesis"):
        provider.complete(CompletionRequest(
            prompt="ignored",
            model=str(tmp_path),
            source_texts=["Hello"],
            target_locale="pl",
        ))
