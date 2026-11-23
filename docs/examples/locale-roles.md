# Example locale roles (not package defaults)

Routing examples inspired by the external architecture note. **Do not** copy
untested locales into production until the
[model evaluation procedure](../model-evaluation.md) and your own
bakeoff report support the swap.

**Consumer matrix 2026-08-29 (pl × 76):** Winner `aya-expanse:8b` (chat 0.936 /
mt_chat 0.940). Applied in a consumer: `pl = "aya-expanse:8b"`. Keep `family = chat`.
TG / llama3.2 are not primaries. Optional secondary: `qwen2.5:7b`.

```toml
[prompt]
family = "chat"   # mt_chat did not beat chat enough to flip (aya +0.004 only)

[locales.models]
pl = "aya-expanse:8b"

# Optional roles after more locale matrices:
[locales.roles.pl]
primary = "aya-expanse:8b"
secondary = "qwen2.5:7b"
# judge = "qwen2.5:14b"   # pull first
```

```toml
# Tier-1 example (other locales — bakeoff first)
[locales.roles.de]
primary = "aya-expanse:8b"
secondary = "qwen2.5:7b"

# Tier-2 / low-resource — MADLAD secondary via CT2 when installed
[locales.roles.sk]
primary = "qwen2.5:7b"
secondary = "madlad400-3b-ct2"
judge = "qwen2.5:14b"

[locales.providers]
sk = "ctranslate2"   # only if secondary is CT2; else keep ollama

[provider]
# When kind is ctranslate2 for a locale via providers map, model_path is the
# converted CT2 directory (sentencepiece.model beside model.bin).
# model_path = "D:/models/madlad400-3b-ct2"
```

Corpus: `llm_localizator/pipeline/bakeoff_corpus.json`.
Runner: `llm-localizator bakeoff --matrix …` ([model-evaluation.md](../model-evaluation.md)).
