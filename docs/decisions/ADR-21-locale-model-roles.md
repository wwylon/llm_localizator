# ADR-21: Per-locale model roles (primary / secondary / judge)

``[locales.models]`` remains the shorthand for a single translator tag per
locale. Optional ``[locales.roles.<locale>]`` adds ``primary``, ``secondary``,
``judge``, and ``prefer_secondary``. Resolution: role primary →
``models[locale]`` → ``models.default``; role judge → ``[quality] judge_model``.

When a secondary is configured, translate may generate a second candidate for
high-risk or low-band strings (ICU variables/plurals, expansion-band warnings,
``high_risk_patterns``, LQS/BT retranslate band, or ``prefer_secondary``). Both
candidates are scored with ``score_candidate``; the winner is recorded in state
and history may list ``candidates: [{model, score, provider}]``.

This is Ollama-first (Wave 3a). A future ``ctranslate2`` provider (MADLAD) may
be selected via ``[locales.providers]`` without changing role field names.
Simultaneous multi-model VRAM residency is out of scope — operators run
sequential sweeps / taskqueue jobs.

Rejected: a separate ``models.yaml`` (TOML already owns routing); always
running secondary (cost); making TranslateGemma/MADLAD package defaults before
bakeoff evidence (ADR-12).
