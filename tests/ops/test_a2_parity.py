"""Wave A2: queued review namespaces, confirm policy, document texts."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.documents import document_source_texts, documents_dir


def test_inline_translate_requires_explicit_confirm(tmp_path, make_config, monkeypatch) -> None:
    monkeypatch.setattr("llm_localizator.projects.taskqueue.tq_available", lambda: False)
    cfg = make_config(tmp_path)
    out = dispatch_op(cfg, "translate", {"dry_run": False, "inline": True}, actor_role="Admin")
    assert out["ok"] is False
    assert "confirm" in (out.get("error") or "").lower()


def test_inline_translate_accepts_confirm(tmp_path, make_config, monkeypatch) -> None:
    monkeypatch.setattr("llm_localizator.projects.taskqueue.tq_available", lambda: False)
    cfg = make_config(tmp_path)
    out = dispatch_op(
        cfg, "translate",
        {"dry_run": True, "confirm": True, "inline": True},
        actor_role="Admin",
    )
    assert out["ok"] is True


def test_document_source_texts_reads_markdown(tmp_path, make_config) -> None:
    cfg = make_config(tmp_path)
    root = documents_dir(cfg)
    src = root / "en"
    src.mkdir(parents=True)
    (src / "terms.md").write_text("# Terms\n\nHello world.\n", encoding="utf-8")
    texts = document_source_texts(cfg, root, ["terms"])
    assert texts and "Hello world" in texts[0]


def test_queued_review_forwards_namespace(monkeypatch, tmp_path, make_config) -> None:
    from llm_localizator.ops import review as review_mod

    cfg = make_config(tmp_path)
    captured: dict = {}

    class Outcome:
        ok = True
        exit_code = 0
        message = "queued"
        task_ids = ["t1"]

    def fake_submit(project, job, overrides):
        captured["overrides"] = dict(overrides)
        return Outcome()

    monkeypatch.setattr(review_mod, "tq_available", lambda: True)
    monkeypatch.setattr(review_mod, "should_enqueue", lambda **kw: True)
    monkeypatch.setattr(review_mod, "submit", fake_submit)
    monkeypatch.setattr(review_mod, "cloud_gate", lambda *a, **k: (None, None))

    from llm_localizator.ops.types import ReviewRequest

    result = review_mod.op_review(
        cfg,
        ReviewRequest(locales=["pl"], namespace="app", submit=True, dry_run=False),
    )
    assert result.ok
    assert captured["overrides"].get("--namespace") == "app"
