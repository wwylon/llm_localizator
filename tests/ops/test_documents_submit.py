"""A queued documents run reads the collection's own tree, not the [documents] default."""

from __future__ import annotations

from llm_localizator.ops import documents as docs_mod
from llm_localizator.ops.types import DocumentsRequest


class _Outcome:
    ok, exit_code, message = True, 0, "queued"


def test_submit_passes_the_collection_dir(tmp_path, make_config, monkeypatch) -> None:
    rules = tmp_path / "arena" / "web" / "rules"
    (rules / "en").mkdir(parents=True)
    (rules / "en" / "euchre.md").write_text("# Euchre\n\nPlay.\n", encoding="utf-8")
    cfg = make_config(tmp_path, targets=["pl"])
    seen = {}
    monkeypatch.setattr(docs_mod, "submit", lambda cfg_, job, ov: seen.update(job=job, ov=ov) or _Outcome())
    result = docs_mod.op_documents(cfg, DocumentsRequest(locales=["pl"], doc_dir=str(rules), submit=True))
    assert result.ok, result.summary
    assert seen["job"] == "documents"
    assert seen["ov"]["--doc-dir"] == rules.as_posix()
    assert seen["ov"]["--locales"] == "pl"


def test_override_values_survive_yaml_quoting() -> None:
    import yaml

    from llm_localizator.projects.taskqueue import _apply_extra_args

    path = "C:" + "\\" + "work" + "\\" + "example-app" + "\\" + 'say "hi"'
    args = _apply_extra_args(["run-documents", "x"], {"--doc-dir": path, "--dry-run": "true"})
    loaded = yaml.safe_load("args: [" + ", ".join(args) + "]")["args"]
    assert loaded == ["run-documents", "x", "--doc-dir", path, "--dry-run"]
