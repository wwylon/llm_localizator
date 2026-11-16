"""Agent-sized report parts (ADR-105)."""

from __future__ import annotations

from llm_localizator.ops.report_split import pack_hits, render_part, write_parts, est_tokens


def _hit(file: str, line: int, text: str = "Hello there", conf: str = "high") -> dict:
    return {
        "file": file, "line": line, "text": text, "reason": "jsx text", "source": "regex",
        "confidence": conf, "existing_key": None, "id": f"{file}:{line}",
    }


def _many(n_files: int, per_file: int) -> list[dict]:
    return [
        _hit(f"pkg{f % 3}/dir{f % 5}/file{f}.tsx", i, f"Some user facing text {f}-{i}")
        for f in range(n_files) for i in range(1, per_file + 1)
    ]


def test_packing_is_deterministic():
    hits = _many(40, 6)
    a = pack_hits(hits, budget_tokens=1200, max_hits=50)
    b = pack_hits(list(reversed(hits)), budget_tokens=1200, max_hits=50)
    assert [(p.id, len(p.hits)) for p in a] == [(p.id, len(p.hits)) for p in b]


def test_no_part_over_budget_and_all_hits_kept():
    hits = _many(60, 8)
    parts = pack_hits(hits, budget_tokens=1500, max_hits=40)
    assert sum(len(p.hits) for p in parts) == len(hits)
    assert all(p.tokens <= 1500 - 600 for p in parts)
    assert all(len(p.hits) <= 40 for p in parts)
    assert len(parts) > 1


def test_small_file_never_split_across_parts():
    hits = _many(30, 5)
    parts = pack_hits(hits, budget_tokens=1000, max_hits=30)
    where: dict[str, set[str]] = {}
    for p in parts:
        for h in p.hits:
            where.setdefault(h["file"], set()).add(p.id)
    assert all(len(ids) == 1 for ids in where.values())


def test_giant_single_file_splits_by_line_range():
    hits = [_hit("big/app.tsx", i, f"Long enough label number {i}") for i in range(1, 400)]
    parts = pack_hits(hits, budget_tokens=900, max_hits=500)
    assert len(parts) > 1
    assert sum(len(p.hits) for p in parts) == 399
    for p in parts:
        lines = [h["line"] for h in p.hits]
        assert lines == sorted(lines)


def test_parts_are_self_contained():
    parts = pack_hits(_many(5, 3), budget_tokens=15000, max_hits=150)
    text = render_part("demo", parts[0], 1, len(parts), "use t()", "node_modules")
    assert "How to route: use t()" in text
    assert "scan-decide" in text
    assert "Skipped while scanning" in text


def test_regeneration_shrinks_and_removes_stale_parts(tmp_path):
    hits = _many(40, 6)
    parts = pack_hits(hits, budget_tokens=1200, max_hits=50)
    idx = write_parts(tmp_path, "demo", parts, "", "")
    first = {e["file"] for e in idx["parts"]}
    assert {p.name for p in tmp_path.glob("part-*.md")} == first
    remaining = [h for h in hits if not h["file"].startswith("pkg0/")]
    parts2 = pack_hits(remaining, budget_tokens=1200, max_hits=50)
    idx2 = write_parts(tmp_path, "demo", parts2, "", "")
    assert idx2["totalHits"] == len(remaining) < idx["totalHits"]
    assert {p.name for p in tmp_path.glob("part-*.md")} == {e["file"] for e in idx2["parts"]}
    assert (tmp_path / "index.md").is_file()


def test_ordering_puts_high_confidence_first():
    hits = [_hit("a/x.tsx", 1, conf="low"), _hit("b/y.tsx", 1, conf="high")]
    parts = pack_hits(hits, budget_tokens=15000, max_hits=1)
    assert parts[0].hits[0]["file"] == "b/y.tsx"


def test_empty_hits_yield_no_parts():
    assert pack_hits([]) == []
    assert est_tokens("") >= 1


def test_backlog_split_by_locale_writes_parts_within_budget(tmp_path):
    import json

    from llm_localizator.ops.agent_backlog import op_agent_backlog
    from llm_localizator.ops.types import AgentBacklogRequest
    from tests.synth.factory import build_project

    proj = build_project(tmp_path)
    cfg = proj.config()
    (tmp_path / "messages" / "pl" / "app.json").write_text("{}", encoding="utf-8")
    out_dir = tmp_path / "parts"
    out = op_agent_backlog(cfg, AgentBacklogRequest(
        locales=["pl"], split="namespace", out_dir=str(out_dir), budget_tokens=500))
    assert out.ok and out.data["parts"]
    index = json.loads((out_dir / "backlog-index.json").read_text(encoding="utf-8"))
    assert index["parts"] and all((out_dir / e["file"]).exists() for e in index["parts"])
    assert sum(e["keys"] for e in index["parts"]) == out.data["count"]
    bad = op_agent_backlog(cfg, AgentBacklogRequest(split="bogus"))
    assert not bad.ok
