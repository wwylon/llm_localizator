"""Config parsing, validation, and three-way discovery (ADR-3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_localizator.projects.config import (
    CONFIG_FILENAME,
    ConfigError,
    discover_config,
    load_config,
)

MINIMAL = """
[project]
name = "demo"

[catalog]
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl"]
"""


def write_config(root: Path, body: str = MINIMAL) -> Path:
    path = root / CONFIG_FILENAME
    path.write_text(body, encoding="utf-8")
    return path


def test_minimal_config_loads(tmp_path: Path) -> None:
    cfg = load_config(write_config(tmp_path))
    assert cfg.name == "demo"
    assert cfg.source_locale == "en"
    assert cfg.targets == ["pl"]
    assert cfg.budget_mode == "on_request"
    assert cfg.budget_output_expansion == 2.0


def test_budget_mode_must_be_known(tmp_path: Path) -> None:
    body = MINIMAL + '\n[budget]\nmode = "estimate"\n'
    with pytest.raises(ConfigError, match="mode"):
        load_config(write_config(tmp_path, body))


def test_paths_resolve_relative_to_the_config_file(tmp_path: Path) -> None:
    write_config(tmp_path, MINIMAL + '\n[prompt]\nglossary = "messages/glossary.json"\n')
    cfg = load_config(tmp_path / CONFIG_FILENAME)
    assert cfg.glossary_path == tmp_path / "messages" / "glossary.json"


def test_vision_model_defaults_to_unset(tmp_path: Path) -> None:
    cfg = load_config(write_config(tmp_path))
    assert cfg.vision_model is None


def test_vision_model_and_improve_multi_sample_round_trip(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        MINIMAL + '\n[quality]\nvision_model = "llava"\nimprove_multi_sample = 3\n',
    )
    cfg = load_config(tmp_path / CONFIG_FILENAME)
    assert cfg.vision_model == "llava"
    assert cfg.improve_multi_sample == 3
    assert cfg.multi_sample == 1  # unaffected -- the two knobs are independent


def test_improve_multi_sample_defaults_to_none(tmp_path: Path) -> None:
    cfg = load_config(write_config(tmp_path))
    assert cfg.improve_multi_sample is None


def test_prompt_family_defaults_to_chat(tmp_path: Path) -> None:
    cfg = load_config(write_config(tmp_path))
    assert cfg.prompt_family == "chat"
    assert cfg.prompt_family_for("pl") == "chat"


def test_prompt_family_and_locale_override(tmp_path: Path) -> None:
    body = (
        MINIMAL
        + '\n[prompt]\nfamily = "mt_chat"\n'
        + '\n[locales.prompt_family]\npl = "chat"\n'
    )
    cfg = load_config(write_config(tmp_path, body))
    assert cfg.prompt_family == "mt_chat"
    assert cfg.prompt_family_for("de") == "mt_chat"
    assert cfg.prompt_family_for("pl") == "chat"


def test_missing_name_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="name is required"):
        load_config(write_config(tmp_path, "[project]\n"))


def test_unknown_catalog_format_is_rejected_with_alternatives(tmp_path: Path) -> None:
    body = MINIMAL.replace('path = "messages', 'format = "sqlite"\npath = "messages')
    with pytest.raises(ConfigError, match="unknown \\[catalog\\] format"):
        load_config(write_config(tmp_path, body))


@pytest.mark.parametrize("fmt", ["json-nested", "json-flat", "yaml", "po", "arb",
                                 "android-xml", "gettext", "i18next", "flutter"])
def test_every_supported_format_is_accepted(tmp_path: Path, fmt: str) -> None:
    body = MINIMAL.replace('path = "messages', f'format = "{fmt}"\npath = "messages')
    assert load_config(write_config(tmp_path, body)).catalog_format == fmt


def test_po_rejects_printf_standard(tmp_path: Path) -> None:
    body = MINIMAL.replace(
        'path = "messages',
        'format = "po"\nstandard = "printf"\npath = "messages',
    )
    with pytest.raises(ConfigError, match="not allowed"):
        load_config(write_config(tmp_path, body))


def test_json_accepts_printf_standard(tmp_path: Path) -> None:
    body = MINIMAL.replace('path = "messages', 'standard = "printf"\npath = "messages')
    assert load_config(write_config(tmp_path, body)).catalog_standard == "printf"


def test_path_without_locale_placeholder_is_rejected(tmp_path: Path) -> None:
    body = '[project]\nname = "d"\n[catalog]\npath = "messages/all.json"\n'
    with pytest.raises(ConfigError, match=r"\{locale\}"):
        load_config(write_config(tmp_path, body))


def test_source_locale_cannot_also_be_a_target(tmp_path: Path) -> None:
    body = MINIMAL.replace('targets = ["pl"]', 'targets = ["en", "pl"]')
    with pytest.raises(ConfigError, match="must not also be a target"):
        load_config(write_config(tmp_path, body))


def test_pivot_referencing_an_unknown_locale_is_rejected(tmp_path: Path) -> None:
    """Catches the silent-degradation case: a pivot whose reference is never translated."""
    body = MINIMAL + '\n[locales.pivots]\n"pt-BR" = "pt-PT"\n'
    with pytest.raises(ConfigError, match="neither a target locale nor the source"):
        load_config(write_config(tmp_path, body))


def test_pivot_to_the_source_locale_is_allowed(tmp_path: Path) -> None:
    body = MINIMAL + '\n[locales.pivots]\n"pl" = "en"\n'
    assert load_config(write_config(tmp_path, body)).pivots == {"pl": "en"}


def test_fallback_cycle_is_rejected(tmp_path: Path) -> None:
    body = MINIMAL.replace('targets = ["pl"]', 'targets = ["pl", "de"]')
    body += '\n[locales.fallbacks]\npl = "de"\nde = "pl"\n'
    with pytest.raises(ConfigError, match="cycle"):
        load_config(write_config(tmp_path, body))


def test_fallback_to_another_target_is_kept(tmp_path: Path) -> None:
    body = MINIMAL.replace('targets = ["pl"]', 'targets = ["pl", "de"]')
    body += '\n[locales.fallbacks]\npl = "de"\n'
    assert load_config(write_config(tmp_path, body)).fallbacks == {"pl": "de"}


def test_frozen_locales_are_excluded_from_active_targets(tmp_path: Path) -> None:
    body = MINIMAL.replace(
        'targets = ["pl"]',
        'targets = ["pl", "ar", "de"]\nfrozen = ["de", "ar"]\n',
    )
    cfg = load_config(write_config(tmp_path, body))
    assert cfg.frozen == ["de", "ar"]
    assert cfg.active_targets() == ["pl"]
    assert cfg.resolve_locales(None) == ["pl"]
    assert cfg.resolve_locales(["de"]) == ["de"]
    assert cfg.is_frozen("de")
    assert not cfg.is_frozen("pl")


def test_frozen_must_be_subset_of_targets(tmp_path: Path) -> None:
    body = MINIMAL + '\nfrozen = ["xx"]\n'
    with pytest.raises(ConfigError, match="subset of targets"):
        load_config(write_config(tmp_path, body))


def test_freezing_every_target_is_rejected(tmp_path: Path) -> None:
    body = MINIMAL.replace('targets = ["pl"]', 'targets = ["pl"]\nfrozen = ["pl"]\n')
    with pytest.raises(ConfigError, match="every target"):
        load_config(write_config(tmp_path, body))


def test_unknown_provider_field_is_rejected(tmp_path: Path) -> None:
    """A typo in a tuning knob should fail loudly, not be silently ignored."""
    body = MINIMAL + '\n[provider]\ntimeout = 60\n'
    with pytest.raises(ConfigError, match="unknown \\[provider\\] field"):
        load_config(write_config(tmp_path, body))


@pytest.mark.parametrize("body, match", [
    (MINIMAL + "\n[quality]\nthreshhold = 0.5\n", r"unknown \[quality\] field"),
    (MINIMAL + "\n[future]\nvalue = true\n", "unknown top-level section"),
])
def test_unknown_config_fields_are_rejected(tmp_path: Path, body: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        load_config(write_config(tmp_path, body))


def test_invalid_toml_is_reported_with_the_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write_config(tmp_path, "[project\nname = broken"))


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no config file"):
        load_config(tmp_path / "absent.toml")


# ---- model resolution ------------------------------------------------------

def test_model_for_uses_the_per_locale_override(tmp_path: Path) -> None:
    body = MINIMAL + '\n[locales.models]\ndefault = "a"\npl = "b"\n'
    cfg = load_config(write_config(tmp_path, body))
    assert cfg.model_for("pl") == "b"
    assert cfg.model_for("de") == "a"


def test_model_for_falls_back_when_nothing_is_configured(tmp_path: Path) -> None:
    assert load_config(write_config(tmp_path)).model_for("pl") == "llama3.2"


def test_model_for_rejects_ambiguous_roster_without_default(tmp_path: Path) -> None:
    body = MINIMAL + '\n[locales.models]\npl = "a"\nde = "b"\n'
    with pytest.raises(ConfigError, match="no default"):
        load_config(write_config(tmp_path, body))


def test_non_string_model_value_fails_load(tmp_path: Path) -> None:
    body = MINIMAL + "\n[locales.models]\npl = 42\n"
    with pytest.raises(ConfigError, match="pl"):
        load_config(write_config(tmp_path, body))


def test_non_string_target_fails_load(tmp_path: Path) -> None:
    body = MINIMAL.replace('targets = ["pl"]', "targets = [1]")
    with pytest.raises(ConfigError, match="targets"):
        load_config(write_config(tmp_path, body))


def test_unknown_model_key_warns_once_and_loads(tmp_path: Path) -> None:
    body = MINIMAL + '\n[locales.models]\ndefault = "a"\nzz = "b"\n'
    with pytest.warns(UserWarning, match="zz"):
        cfg = load_config(write_config(tmp_path, body))
    assert cfg.models["zz"] == "b"
    assert cfg.model_for("pl") == "a"


def test_bad_glossary_json_fails_load_with_the_path(tmp_path: Path) -> None:
    (tmp_path / "glossary.json").write_text("{", encoding="utf-8")
    body = MINIMAL + '\n[prompt]\nglossary = "glossary.json"\n'
    with pytest.raises(ConfigError, match="glossary.json"):
        load_config(write_config(tmp_path, body))


def test_glossary_directory_still_loads(tmp_path: Path) -> None:
    gloss = tmp_path / "glossary"
    gloss.mkdir()
    (gloss / "global.json").write_text(
        '{"doNotTranslate": [], "terms": {}}\n', encoding="utf-8",
    )
    body = MINIMAL + '\n[prompt]\nglossary = "glossary"\n'
    cfg = load_config(write_config(tmp_path, body))
    assert cfg.glossary_path == gloss


def test_locale_roles_override_models_and_judge(tmp_path: Path) -> None:
    body = MINIMAL + """
[locales.models]
default = "fallback"

[locales.roles.pl]
primary = "primary-tag"
secondary = "secondary-tag"
judge = "judge-tag"
prefer_secondary = true

[quality]
judge_model = "global-judge"
high_risk_patterns = ["\\\\baccount\\\\b"]
"""
    cfg = load_config(write_config(tmp_path, body))
    assert cfg.model_for("pl") == "primary-tag"
    assert cfg.secondary_model_for("pl") == "secondary-tag"
    assert cfg.judge_model_for("pl") == "judge-tag"
    assert cfg.judge_model_for("de") == "global-judge"
    assert cfg.role_for("pl").prefer_secondary is True
    assert cfg.high_risk_patterns == [r"\baccount\b"]


def test_locale_role_for_unknown_target_is_rejected(tmp_path: Path) -> None:
    body = MINIMAL + '\n[locales.roles.de]\nprimary = "x"\n'
    with pytest.raises(ConfigError, match="must be target locales"):
        load_config(write_config(tmp_path, body))


def test_apply_model_override_clears_secondary(tmp_path: Path) -> None:
    body = MINIMAL + """
[locales.roles.pl]
primary = "a"
secondary = "b"
"""
    cfg = load_config(write_config(tmp_path, body))
    cfg.apply_model_override("forced")
    assert cfg.model_for("pl") == "forced"
    assert cfg.secondary_model_for("pl") is None


# ---- discovery -------------------------------------------------------------

def test_discovery_finds_the_config_in_the_current_directory(tmp_path: Path) -> None:
    write_config(tmp_path)
    assert discover_config(tmp_path) == tmp_path / CONFIG_FILENAME


def test_discovery_walks_upward(tmp_path: Path) -> None:
    """The no-registry path: this is what makes CI and fresh clones work."""
    write_config(tmp_path)
    deep = tmp_path / "apps" / "web" / "features"
    deep.mkdir(parents=True)
    assert discover_config(deep) == tmp_path / CONFIG_FILENAME


def test_discovery_failure_names_the_remedy(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="llm-localizator init"):
        discover_config(tmp_path)


def test_locale_style_table(tmp_path: Path) -> None:
    body = MINIMAL + """
[prompt]
register = "informal"

[prompt.styles.de]
register = "formal"
notes = "Use Sie."
"""
    cfg = load_config(write_config(tmp_path, body))
    register, notes = cfg.style_for("de")
    assert register == "formal"
    assert notes.startswith("Use Sie.")  # the locale's register wording follows the notes
    assert cfg.style_for("pl")[0] == "informal"


def test_locale_style_register_must_be_known(tmp_path: Path) -> None:
    body = MINIMAL + '\n[prompt.styles.de]\nregister = "slang"\n'
    with pytest.raises(ConfigError, match="register"):
        load_config(write_config(tmp_path, body))


def test_quality_thresholds_override_the_global_cut(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        MINIMAL + "\n[quality]\nthreshold = 0.55\n\n[quality.thresholds]\npl = 0.7\n",
    )
    cfg = load_config(tmp_path / CONFIG_FILENAME)
    assert cfg.quality_threshold_for("pl") == 0.7
    assert cfg.quality_threshold_for("de") == 0.55  # no override: the global cut


def test_quality_thresholds_reject_non_targets_and_bad_numbers(tmp_path: Path) -> None:
    import pytest

    from llm_localizator.projects.config import ConfigError

    for body, message in (
        ("[quality.thresholds]\nfr = 0.5\n", "target locales"),
        ("[quality.thresholds]\npl = 1.5\n", "outside 0..1"),
        ('[quality.thresholds]\npl = "high"\n', "must be a number"),
    ):
        write_config(tmp_path, MINIMAL + "\n" + body)
        with pytest.raises(ConfigError, match=message):
            load_config(tmp_path / CONFIG_FILENAME)


@pytest.mark.parametrize("line, field", [
    ('t_functions = "tr"', "t_functions"),
    ('exclude = "build"', "exclude"),
    ('directive_aliases = "false"', "directive_aliases"),
])
def test_scan_settings_reject_wrong_types(tmp_path: Path, line: str, field: str) -> None:
    """A bare string must not become a list of characters, nor "false" become True (M0, audit ops #6)."""
    with pytest.raises(ConfigError, match=field):
        load_config(write_config(tmp_path, MINIMAL + "\n[scan]\n" + line + "\n"))


def test_scan_lists_still_load(tmp_path: Path) -> None:
    cfg = load_config(write_config(tmp_path, MINIMAL + '\n[scan]\nt_functions = ["tr", "myT"]\ndirective_aliases = false\n'))
    assert cfg.scan_t_functions == ["tr", "myT"] and cfg.scan_directive_aliases is False
