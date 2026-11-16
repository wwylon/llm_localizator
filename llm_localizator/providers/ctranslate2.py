"""CTranslate2 provider for MADLAD-style encoder–decoder MT (Wave 3b).

Lazy-imports ``ctranslate2`` + ``sentencepiece`` so hermetic CI stays clean.
Install via ``pip install llm_localizator[ctranslate2]`` (or the wheels directly).
"""

from __future__ import annotations

from pathlib import Path

from ..core.locale_code import base_language
from .base import CompletionRequest, Provider, ProviderError

__all__ = ["CTranslate2Provider", "madlad_target_prefix"]


_MADLAD_TAGS = {
    "pt-br": "pt_br",
    "zh-tw": "zh_tw",
    "zh-hant": "zh_Hant",
    "fr-ca": "fr_CA",
}


def madlad_target_prefix(locale: str) -> str:
    """MADLAD ``<2xx>`` target token from a BCP-47 locale.

    Most languages use the ISO 639-1 base (``<2pt>``). A few regions have
    their own published tag (``pt-BR`` → ``<2pt_br>``). Unknown regions stay
    on the base tag rather than guessing a 3-letter code.
    """
    raw = (locale or "en").strip().replace("_", "-")
    key = raw.lower()
    mapped = _MADLAD_TAGS.get(key)
    if mapped:
        return f"<2{mapped}>"
    base = base_language(key)
    if not base.isalpha() or len(base) > 3:
        base = "en"
    return f"<2{base}>"


class CTranslate2Provider(Provider):
    """Offline MT via a converted CTranslate2 model directory.

    ``CompletionRequest.model`` may be a filesystem path; otherwise the
    constructor ``model_path`` is used. Batches use ``source_texts`` when set.
    """

    def __init__(
        self,
        model_path: str = "",
        *,
        device: str = "auto",
        compute_type: str = "default",
        spm_model: str | None = None,
        beam_size: int = 4,
    ) -> None:
        self.model_path = (model_path or "").strip()
        self.device = device
        self.compute_type = compute_type
        self.spm_model = spm_model
        self.beam_size = beam_size
        self._translator = None
        self._spm = None
        self._loaded_path: str | None = None

    @property
    def name(self) -> str:
        return "ctranslate2"

    def health_check(self) -> bool:
        if not self.model_path:
            return False
        return Path(self.model_path).is_dir()

    def stop(self, model: str = "") -> None:
        """Drop the loaded Translator so the next ``ensure_ready`` is a clean load."""
        del model
        self._translator = None
        self._spm = None
        self._loaded_path = None

    def ensure_ready(self, model: str, *, report=None) -> None:
        path = (model or self.model_path or "").strip()
        if path:
            self._load(path)

    def _load(self, model_path: str) -> None:
        if self._translator is not None and self._loaded_path == model_path:
            return
        # Drop the previous load first so peak RSS is ~1× model, not 2×.
        self.stop()
        try:
            import ctranslate2  # type: ignore
            import sentencepiece as spm  # type: ignore
        except ImportError as exc:
            raise ProviderError(
                "ctranslate2 provider requires the optional deps "
                "`ctranslate2` and `sentencepiece` "
                "(pip install 'llm_localizator[ctranslate2]')."
            ) from exc
        path = Path(model_path)
        if not path.is_dir():
            raise ProviderError(f"CTranslate2 model path is not a directory: {model_path}")
        spm_path = self.spm_model or str(path / "sentencepiece.model")
        if not Path(spm_path).is_file():
            # Common CT2 export layout.
            alt = path / "spm.model"
            if alt.is_file():
                spm_path = str(alt)
            else:
                raise ProviderError(
                    f"sentencepiece model not found next to CT2 model ({spm_path})"
                )
        kwargs: dict = {}
        if self.device and self.device != "auto":
            kwargs["device"] = self.device
        if self.compute_type and self.compute_type != "default":
            kwargs["compute_type"] = self.compute_type
        self._translator = ctranslate2.Translator(str(path), **kwargs)
        processor = spm.SentencePieceProcessor()
        processor.Load(spm_path)
        self._spm = processor
        self._loaded_path = model_path

    def complete(self, request: CompletionRequest) -> str:
        model_path = (request.model or self.model_path or "").strip()
        if not model_path:
            raise ProviderError(
                "ctranslate2 requires [provider] model_path or CompletionRequest.model"
            )
        self._load(model_path)
        assert self._translator is not None and self._spm is not None

        locale = request.target_locale or str(request.options.get("locale") or "en")
        prefix = madlad_target_prefix(locale)
        sources = list(request.source_texts or [])
        if not sources:
            # Fall back to last non-empty prompt line (tests / simple callers).
            line = request.prompt.strip().splitlines()[-1] if request.prompt.strip() else ""
            if not line:
                raise ProviderError("ctranslate2: empty source_texts and prompt")
            sources = [line]

        encoded: list[list[str]] = []
        for text in sources:
            pieces = self._spm.EncodeAsPieces(f"{prefix} {text}".strip())
            encoded.append(list(pieces))

        max_chars = max((len(t) for t in sources), default=0)
        max_decoding = max(512, min(2048, max_chars * 3 + 64))
        try:
            results = self._translator.translate_batch(
                encoded,
                beam_size=self.beam_size,
                max_decoding_length=max_decoding,
            )
        except Exception as exc:  # noqa: BLE001 — surface as ProviderError
            raise ProviderError(f"ctranslate2 translate failed: {exc}") from exc

        outs: list[str] = []
        for result in results:
            hyp = result.hypotheses[0] if result.hypotheses else []
            text = self._spm.DecodePieces(hyp).strip()
            if not text:
                raise ProviderError("ctranslate2 returned an empty hypothesis")
            outs.append(text)

        if request.schema is not None:
            import json
            return json.dumps(outs, ensure_ascii=False)
        if len(outs) == 1:
            return outs[0]
        return "\n".join(outs)
