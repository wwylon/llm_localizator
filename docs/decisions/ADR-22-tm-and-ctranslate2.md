# ADR-22: Translation memory + optional CTranslate2 provider

Exact and near-match TM live under consumer ``[prompt] tm_dir`` (default
``.llm-tm/``). Exact hits reuse prior text with ``trigger=tm-hit`` and stamp the
TM row's provider/model. Near hits only seed few-shot examples — never
auto-accept. Semantic near-match is available via ``tm.near(..., semantic=True)``
or ``[prompt] tm_semantic = true`` (character n-grams by default; optional
``sentence-transformers`` — see ADR-26). V26 is the advisory when live text
diverges from a high-score TM exact for the same source+context.

``provider=ctranslate2`` is an optional MADLAD path (Wave 3b): lazy-import
``ctranslate2`` + ``sentencepiece``, configured via ``[provider] kind`` /
``model_path`` or ``[locales.providers]``. Hermetic CI does not require the
native wheel. NLLB stays out of commercial defaults (CC-BY-NC).

Rejected: always auto-accept near matches; package-default MADLAD without
bakeoff evidence (ADR-12); simultaneous Ollama+CT2 VRAM residency.
