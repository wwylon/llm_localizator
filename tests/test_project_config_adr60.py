"""ADR-60: prompt text, bridge locale, glossary conflict and identity keys."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_localizator.pipeline.prompt_i18n import cached_translation, ensure_localized
from llm_localizator.pipeline.prompts import _preamble
from llm_localizator.projects.config import ConfigError, load_config
from llm_localizator.projects.context import effective_glossary_for, glossary_conflicts
from llm_localizator.providers.base import ProviderError
from llm_localizator.web.project_config import project_config_view, save_project_config


def _toml(root: Path, *, targets: str = '["pl", "de"]') -> Path:
    path = root / ".llm-localize.toml"
    path.write_text(
        '[project]\nname = "demo"\nsource_locale = "en"\n\n'
        '[catalog]\nformat = "json-nested"\npath = "messages/{locale}/{namespace}.json"\n\n'
        f"[locales]\ntargets = {targets}\n\n"
        '[provider]\nkind = "null"\n\n[prompt]\nfamily = "chat"\n',
        encoding="utf-8",
    )
    (root / "messages" / "en").mkdir(parents=True, exist_ok=True)
    return path


def test_every_key_round_trips(tmp_path) -> None:
    path = _toml(tmp_path)
    result = save_project_config(
        load_config(path),
        display_name="Demo App",
        description="A task queue for developers.",
        audience="Software engineers",
        domain="SaaS / developer tools",
        localize="per-model",
        glossary_conflict="shared",
        locale_notes={"pl": "Use informal tone."},
        models={"llama3.2:latest": {"text": "Be explicit.", "localize": True}},
        bridge={"mode": "custom", "locale": "de", "model": "qwen2.5:7b", "store": True},
        pivots={"pl": "de"},
    )
    assert result["ok"] is True, result
    cfg = load_config(path)
    assert cfg.display_name == "Demo App"
    assert cfg.description == "A task queue for developers."
    assert cfg.audience == "Software engineers"
    assert cfg.domain == "SaaS / developer tools"
    assert cfg.prompt_localize == "per-model"
    assert cfg.glossary_conflict == "shared"
    assert cfg.locale_styles["pl"][1] == "Use informal tone."
    assert cfg.model_prompts["llama3.2:latest"] == ("Be explicit.", True)
    assert (cfg.bridge_mode, cfg.bridge_locale, cfg.bridge_model) == ("custom", "de", "qwen2.5:7b")
    assert cfg.pivots == {"pl": "de"}

    view = project_config_view(cfg)
    assert view["description"] == "A task queue for developers."
    assert view["localeNotes"] == {"pl": "Use informal tone."}
    assert view["models"]["llama3.2:latest"]["localize"] is True
    assert view["bridge"]["locale"] == "de"
    assert view["pivots"] == {"pl": "de"}
    assert view["glossaryConflict"] == "shared"


def test_clearing_removes_keys(tmp_path) -> None:
    path = _toml(tmp_path)
    save_project_config(
        load_config(path), description="x", locale_notes={"pl": "n"},
        bridge={"mode": "custom", "locale": "de"}, pivots={"pl": "de"},
        models={"m": {"text": "t", "localize": False}},
    )
    result = save_project_config(
        load_config(path), description="", locale_notes={}, bridge={"mode": "none"},
        pivots={}, models={},
    )
    assert result["ok"] is True
    cfg = load_config(path)
    assert cfg.description == "" and cfg.locale_styles == {}
    assert cfg.bridge_mode == "none" and cfg.pivots == {} and cfg.model_prompts == {}


@pytest.mark.parametrize(
    "kwargs, needle",
    [
        ({"localize": "sometimes"}, "localize"),
        ({"glossary_conflict": "both"}, "glossary_conflict"),
        ({"description": "x" * 2001}, "2000"),
        ({"audience": "x" * 301}, "300"),
        ({"locale_notes": {"pl": "x" * 501}}, "500"),
        ({"models": {"m": {"text": "x" * 1001}}}, "1000"),
        ({"bridge": {"mode": "custom", "locale": "ja"}}, "target locale"),
        ({"bridge": {"mode": "custom", "locale": "pl", "store": False}}, "store"),
        ({"bridge": {"mode": "custom", "locale": "pl"}, "pivots": {"pl": "de"}}, "pivot"),
    ],
)
def test_invalid_save_rejected_and_file_untouched(tmp_path, kwargs, needle) -> None:
    path = _toml(tmp_path)
    before = path.read_bytes()
    result = save_project_config(load_config(path), **kwargs)
    assert result["ok"] is False
    assert needle in (result.get("error") or "")
    assert path.read_bytes() == before


def test_bridge_store_no_allowed_for_source_locale(tmp_path) -> None:
    path = _toml(tmp_path)
    result = save_project_config(
        load_config(path), bridge={"mode": "custom", "locale": "en", "store": False},
    )
    assert result["ok"] is True
    assert load_config(path).bridge_store is False


def test_bridge_is_default_pivot_and_explicit_pivot_wins(tmp_path) -> None:
    path = _toml(tmp_path, targets='["pl", "de", "fr"]')
    save_project_config(load_config(path), bridge={"mode": "custom", "locale": "de"})
    cfg = load_config(path)
    assert cfg.pivot_for("pl") == "de"
    assert cfg.pivot_for("de") is None  # the bridge locale is translated from the source
    order = cfg.order_locales(["pl", "de", "fr"])
    assert order.index("de") < order.index("pl")
    save_project_config(load_config(path), pivots={"pl": "fr"})
    cfg = load_config(path)
    assert cfg.pivot_for("pl") == "fr"
    assert cfg.pivot_for("fr") == "de"


def test_bridge_model_applies_to_bridge_locale_only(tmp_path) -> None:
    path = _toml(tmp_path)
    save_project_config(
        load_config(path), bridge={"mode": "custom", "locale": "de", "model": "fast:1b"},
    )
    cfg = load_config(path)
    assert cfg.model_for("de") == "fast:1b"
    assert cfg.model_for("pl") != "fast:1b"


def test_preamble_carries_description_audience_and_model_variant(tmp_path) -> None:
    path = _toml(tmp_path)
    save_project_config(
        load_config(path), description="Task queue.", audience="Engineers",
        locale_notes={"pl": "Informal."},
        models={"m1": {"text": "Be explicit.", "localize": False}},
    )
    cfg = load_config(path)
    _, notes = cfg.style_for("pl", "m1")
    text = _preamble("an app", "", "informal", notes, "pl")
    assert "Informal." in text
    assert "Project description: Task queue." in text
    assert "Target audience: Engineers" in text
    assert "Model guidance: Be explicit." in text
    _, other = cfg.style_for("pl", "m2")
    assert "Model guidance" not in _preamble("an app", "", "informal", other, "pl")
    _, de_notes = cfg.style_for("de", "m1")
    assert "Informal." not in _preamble("an app", "", "informal", de_notes, "de")


def test_glossary_conflict_modes(tmp_path) -> None:
    own = tmp_path / "own.json"
    shared = tmp_path / "shared.json"
    own.write_text(json.dumps({"terms": {"Job": {"pl": "Zadanie"}, "Queue": {"pl": "Kolejka"}}}))
    shared.write_text(json.dumps({"terms": {"Job": {"pl": "Praca"}, "Brand": {"pl": "Marka"}}}))
    won = effective_glossary_for(own, shared=[shared])["terms"]
    assert won["Job"] == {"pl": "Zadanie"}
    lost = effective_glossary_for(own, shared=[shared], conflict="shared")["terms"]
    assert lost["Job"] == {"pl": "Praca"} and lost["Queue"] == {"pl": "Kolejka"}
    assert glossary_conflicts(own, [shared]) == ["Job"]


def test_view_lists_conflicts_and_term_counts(tmp_path) -> None:
    path = _toml(tmp_path)
    (tmp_path / "own.json").write_text(json.dumps({"terms": {"Job": {"pl": "a"}}}))
    (tmp_path / "shared.json").write_text(json.dumps({"terms": {"Job": {"pl": "b"}, "X": {}}}))
    save_project_config(
        load_config(path), glossary="own.json", glossary_shared=["shared.json"],
        glossary_conflict="flag",
    )
    view = project_config_view(load_config(path))
    kinds = {row["kind"]: row for row in view["glossaryRows"]}
    assert kinds["own"]["terms"] == 1 and kinds["shared"]["terms"] == 2
    assert view["conflicts"] == ["Job"]


class _Fake:
    def __init__(self, reply: str = "Przetlumaczone", fail: bool = False) -> None:
        self.calls = 0
        self.reply = reply
        self.fail = fail

    def complete(self, request):
        self.calls += 1
        if self.fail:
            raise ProviderError("down")
        return self.reply


def test_prompt_localization_translates_once_and_caches(tmp_path) -> None:
    path = _toml(tmp_path)
    save_project_config(load_config(path), description="Task queue.", localize="target")
    cfg = load_config(path)
    fake = _Fake()
    ensure_localized(cfg, fake, "pl", "m1", report=lambda *_: None)
    ensure_localized(cfg, fake, "pl", "m1", report=lambda *_: None)
    assert fake.calls == 1
    assert cached_translation(cfg, "pl", cfg.prompt_extras_for("pl", "m1", raw=True)) == "Przetlumaczone"
    assert "Przetlumaczone" in cfg.style_for("pl", "m1")[1]
    assert "Task queue." not in cfg.style_for("pl", "m1")[1]


def test_prompt_localization_falls_back_to_source_on_provider_error(tmp_path) -> None:
    path = _toml(tmp_path)
    save_project_config(load_config(path), description="Task queue.", localize="target")
    cfg = load_config(path)
    messages: list[str] = []
    ensure_localized(cfg, _Fake(fail=True), "pl", "m1", report=messages.append)
    assert messages and "skipped" in messages[0]
    assert "Task queue." in cfg.style_for("pl", "m1")[1]


def test_per_model_localization_only_for_flagged_models(tmp_path) -> None:
    path = _toml(tmp_path)
    save_project_config(
        load_config(path), description="Task queue.", localize="per-model",
        models={"m1": {"text": "", "localize": True}},
    )
    cfg = load_config(path)
    assert cfg.localize_prompt_for("m1") is True
    assert cfg.localize_prompt_for("m2") is False
    assert cfg.localize_prompt_for("") is False


def _voice_toml(root: Path, extra: str, prompt: str = "") -> Path:
    path = _toml(root)
    path.write_text(path.read_text(encoding="utf-8") + prompt + extra, encoding="utf-8")
    return path


def test_voice_section_feeds_prompt_fields(tmp_path) -> None:
    path = _voice_toml(
        tmp_path, '\n[voice]\ndescription = "Hotel app."\naudience = "Travellers"\ntone = "friendly"\n',
    )
    cfg = load_config(path)
    assert (cfg.description, cfg.audience, cfg.tone) == ("Hotel app.", "Travellers", "friendly")
    extras = cfg.prompt_extras_for("pl", raw=True)
    assert extras.splitlines() == [
        "Project description: Hotel app.", "Target audience: Travellers", "Tone: friendly",
    ]


def test_no_voice_means_no_tone_line(tmp_path) -> None:
    cfg = load_config(_toml(tmp_path))
    assert cfg.tone == "" and "Tone" not in cfg.prompt_extras_for("pl", raw=True)


def test_voice_conflicts_with_prompt(tmp_path) -> None:
    path = _voice_toml(tmp_path, '\n[voice]\naudience = "A"\n', prompt='audience = "B"\n')
    with pytest.raises(Exception, match="both"):
        load_config(path)


def test_voice_rejects_unknown_and_long(tmp_path) -> None:
    with pytest.raises(Exception, match="voice"):
        load_config(_voice_toml(tmp_path, '\n[voice]\nmood = "x"\n'))
    with pytest.raises(Exception, match="300"):
        load_config(_voice_toml(tmp_path, '\n[voice]\ntone = "' + "x" * 301 + '"\n'))


def test_save_writes_tone_to_voice_and_keeps_prompt_fields(tmp_path) -> None:
    path = _toml(tmp_path)
    assert save_project_config(load_config(path), tone="calm", description="D")["ok"]
    text = path.read_text(encoding="utf-8")
    assert "[voice]" in text and 'tone = "calm"' in text
    cfg = load_config(path)
    assert (cfg.tone, cfg.description) == ("calm", "D")
    assert save_project_config(load_config(path), audience="Pros")["ok"]
    assert load_config(path).audience == "Pros"


def test_style_preset_adds_one_line_and_locale_overrides(tmp_path) -> None:
    path = _voice_toml(
        tmp_path, '\n[prompt.style_presets]\npl = "creative"\n', prompt='style_preset = "fluid"\n',
    )
    cfg = load_config(path)
    assert cfg.prompt_extras_for("de", raw=True).startswith("Style: write natural")
    assert cfg.prompt_extras_for("pl", raw=True).startswith("Style: adapt for impact")


def test_no_preset_means_no_style_line(tmp_path) -> None:
    cfg = load_config(_toml(tmp_path))
    assert "Style:" not in cfg.prompt_extras_for("pl", raw=True)


def test_unknown_preset_is_a_load_error(tmp_path) -> None:
    with pytest.raises(ConfigError):
        load_config(_voice_toml(tmp_path, "", prompt='style_preset = "wild"\n'))
