"""context-propose / context-note (A3, ADR-131)."""

from __future__ import annotations

import json

from llm_localizator.ops.context_notes import frame_note, op_context_note, op_context_propose
from llm_localizator.projects import load_config


def test_frame_note_only_for_function_word_frames() -> None:
    assert "'of'" in frame_note("{rank} of {suit}")
    assert frame_note("worker error: {error}") is None
    assert frame_note("Settings") is None
    assert frame_note("{n, plural, one {# of them} other {# of them}}") is None
    assert frame_note("Image {n} of {total} for the selected folder") is None  # not short


def test_propose_and_write(tmp_path) -> None:
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(json.dumps({"c.name": "{rank} of {suit}", "c.x": "Save"}),
                                                  encoding="utf-8")
    toml = tmp_path / ".llm-localize.toml"
    toml.write_text('[project]\nname = "t"\nsource_locale = "en"\n[catalog]\nformat = "json-flat"\n'
                    'path = "locales/{locale}.json"\n[locales]\ntargets = ["pl"]\n', encoding="utf-8")
    cfg = load_config(toml)
    preview = op_context_propose(cfg)
    assert [r["key"] for r in preview.data["rows"]] == ["c.name"]
    assert not (tmp_path / "locales" / "context").exists()
    assert op_context_propose(cfg, write=True).data["written"]
    notes = json.loads((tmp_path / "locales" / "context" / "_root.json").read_text(encoding="utf-8"))
    assert "of" in notes["c.name"]
    cfg2 = load_config(toml)
    assert cfg2.context_dir is not None
    assert op_context_note(cfg2, key="c.name", note="custom").ok
    assert json.loads((tmp_path / "locales" / "context" / "_root.json").read_text(encoding="utf-8"))["c.name"] == "custom"
    assert op_context_note(cfg2, key="nope", note="x").exit_code == 2


def test_context_note_records_an_approved_translation(tmp_path, make_config) -> None:
    import json as _json

    from llm_localizator.ops.context_notes import op_context_note

    (tmp_path / "locales").mkdir(exist_ok=True)
    (tmp_path / "locales" / "en.json").write_text(_json.dumps({"card.name": "{rank} of {suit}"}),
                                                  encoding="utf-8")
    cfg = make_config(tmp_path, catalog_format="json-flat", catalog_path="locales/{locale}.json",
                      targets=["pl"], context_dir=str(tmp_path / "ctx"))
    assert op_context_note(cfg, key="card.name", note="no preposition").ok
    assert op_context_note(cfg, key="card.name", approved={"pl": "{rank} {suit}"}).ok
    data = _json.loads((tmp_path / "ctx" / "_root.json").read_text(encoding="utf-8"))
    assert data["card.name"] == {"note": "no preposition", "approved": {"pl": "{rank} {suit}"}}
