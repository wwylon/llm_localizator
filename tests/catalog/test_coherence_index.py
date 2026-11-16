"""Catalogue coherence index (V30/V31)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.catalog.coherence_index import CoherenceIndex
from llm_localizator.pipeline.context_assembler import assemble_context
from llm_localizator.pipeline.validate import run_validation
from llm_localizator.projects.config import ProjectConfig, ProviderConfig

from ..conftest import write_json


def test_exact_siblings_and_conflicts() -> None:
    idx = CoherenceIndex()
    idx.build([
        ("admin", "a", "Staff", "الموظفون"),
        ("admin", "b", "Staff", "次级人员"),
        ("admin", "c", "Save", "حفظ"),
    ], quality_ok=lambda ns, key: key != "b")
    sibs = idx.exact_siblings("admin", "a", "Staff", quality_only=True)
    assert len(sibs) == 0  # b filtered by quality
    sibs_all = idx.exact_siblings("admin", "a", "Staff", quality_only=False)
    assert len(sibs_all) == 1
    conflicts = idx.exact_conflicts()
    assert len(conflicts) == 1


def test_assemble_context_catalogue_exact() -> None:
    idx = CoherenceIndex()
    idx.build([
        ("admin", "navStaff", "Staff", "الموظفون"),
        ("admin", "otherStaff", "Staff", "الموظفون"),
    ], quality_ok=lambda *_: True)
    pkg = assemble_context(
        source="Staff",
        locale="ar",
        namespace="admin",
        key="navStaff",
        coherence_index=idx,
    )
    assert any(i.kind == "catalogue_exact" for i in pkg.items)
    assert ("Staff", "الموظفون") in pkg.examples


def test_v30_validate(project_root: Path, make_catalog) -> None:
    write_json(
        project_root / "messages" / "en" / "app.json",
        {"a": "Staff", "b": "Staff"},
    )
    write_json(
        project_root / "messages" / "ar" / "app.json",
        {"a": "الموظفون", "b": "次级人员"},
    )
    cfg = ProjectConfig(
        root=project_root,
        name="v30",
        catalog_path="messages/{locale}/{namespace}.json",
        targets=["ar"],
        provider=ProviderConfig(kind="null"),
        state_dir=project_root / ".state",
    )
    report = run_validation(cfg, make_catalog(cfg), locales=["ar"], check_semantic=True)
    v30 = [f for f in report.findings if f.check == "V30"]
    assert len(v30) >= 1


def test_oversized_namespace_still_gets_v30_and_reports_v31_skip(
    project_root: Path, make_catalog, monkeypatch,
) -> None:
    import llm_localizator.pipeline.validate as validate_mod

    monkeypatch.setattr(validate_mod, "SEMANTIC_COHERENCE_MAX_KEYS", 4)
    en = {f"k{i}": f"Distinct text number {i}" for i in range(6)}
    en.update({"a": "Staff", "b": "Staff"})
    ar = {k: v for k, v in en.items()}
    ar.update({"a": "one", "b": "two"})
    write_json(project_root / "messages" / "en" / "app.json", en)
    write_json(project_root / "messages" / "ar" / "app.json", ar)
    cfg = ProjectConfig(
        root=project_root, name="big",
        catalog_path="messages/{locale}/{namespace}.json",
        targets=["ar"], provider=ProviderConfig(kind="null"),
        state_dir=project_root / ".state",
    )
    report = run_validation(cfg, make_catalog(cfg), locales=["ar"], check_semantic=True)
    v30 = [f for f in report.findings if f.check == "V30"]
    assert any("same English source" in f.message for f in v30)  # exact still ran
    skipped = [f for f in report.findings if f.check == "V31" and "skipped" in f.message]
    assert skipped and "V30 (same-source) still ran" in skipped[0].message


def test_oversized_exact_group_is_skipped_and_reported() -> None:
    idx = CoherenceIndex()
    rows = [("n", f"k{i}", "Same", f"t{i}") for i in range(5)]
    rows += [("n", "x", "Other", "a"), ("n", "y", "Other", "b")]
    idx.build(rows)
    pairs = idx.exact_conflicts(max_group=3)
    assert len(pairs) == 1  # only the small group
    assert idx.skipped_groups == [("n.k0", 5)]


def test_vectors_are_cached_per_text(monkeypatch) -> None:
    import llm_localizator.catalog.coherence_index as mod

    calls: list[str] = []
    real = mod.embed
    monkeypatch.setattr(mod, "embed", lambda t: calls.append(t) or real(t))
    idx = CoherenceIndex()
    idx.build([("n", f"k{i}", f"Open the {w} panel", f"t{i}")
               for i, w in enumerate(["red", "blue", "green", "gold"])])
    idx.fuzzy_conflicts(min_overlap=0.0)
    assert len(calls) == len(set(calls)) == 4  # once per text, not per pair
