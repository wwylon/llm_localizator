"""write_config_atomically: validated write with a unique temp file (plan-review-7 P6)."""

from __future__ import annotations

from llm_localizator.web.config_write import write_config_atomically

GOOD = '[project]\nname = "demo"\n\n[locales]\ntargets = ["pl"]\n'


def test_valid_config_is_written_and_no_probe_left(tmp_path) -> None:
    path = tmp_path / ".llm-localize.toml"
    path.write_text(GOOD, encoding="utf-8")
    err = write_config_atomically(path, GOOD.replace("pl", "de"))
    assert err is None
    assert '"de"' in path.read_text(encoding="utf-8")
    assert [p.name for p in tmp_path.iterdir()] == [".llm-localize.toml"]


def test_invalid_config_is_refused_and_original_kept(tmp_path) -> None:
    path = tmp_path / ".llm-localize.toml"
    path.write_text(GOOD, encoding="utf-8")
    err = write_config_atomically(path, "[nonsense\n")
    assert err
    assert path.read_text(encoding="utf-8") == GOOD
    assert [p.name for p in tmp_path.iterdir()] == [".llm-localize.toml"]
    assert ".probe" not in err


def test_concurrent_writers_use_distinct_probe_names(tmp_path, monkeypatch) -> None:
    import llm_localizator.web.config_write as mod

    seen: list[str] = []
    real = mod.load_config

    def spy(p):
        seen.append(p.name)
        return real(p)

    monkeypatch.setattr(mod, "load_config", spy)
    path = tmp_path / ".llm-localize.toml"
    path.write_text(GOOD, encoding="utf-8")
    write_config_atomically(path, GOOD)
    write_config_atomically(path, GOOD)
    assert len(set(seen)) == 2
