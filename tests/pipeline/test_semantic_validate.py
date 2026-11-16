from llm_localizator.core.validate import check_fullkey_coherence, validate_translation_detailed
from llm_localizator.pipeline.validate import run_validation

from ..conftest import write_json
from ..pipeline.test_translate import setup_project


def test_fullkey_coherence_warns_on_divergence() -> None:
    msg = check_fullkey_coherence("Short", "Completely different long text")
    assert msg is not None
    ok, failures = validate_translation_detailed(
        "Hello", "Short", "pl", {},
        fullkey_sibling="A much longer greeting for the user",
    )
    assert ok
    assert any(f.id == "V24" for f in failures)


def test_run_validation_semantic_flag(project_root, make_config, make_catalog) -> None:
    setup_project(project_root, {"short": "Hi", "long": "Hello there"}, existing={"short": "Hi"})
    ctx = project_root / "context"
    ctx.mkdir()
    (ctx / "app.json").write_text(
        '{"short": {"fullKey": "long", "maxChars": 2}}',
        encoding="utf-8",
    )
    cfg = make_config(project_root, context_dir=project_root / "context")
    catalog = make_catalog(cfg)
    write_json(project_root / "messages" / "pl" / "app.json", {
        "short": "XX",
        "long": "Witaj",
    })
    report = run_validation(cfg, catalog, locales=["pl"], check_semantic=True)
    ids = {f.check for f in report.findings}
    assert "V22" in ids or "V24" in ids


def test_v38_stays_off_unless_requested(project_root, make_config, make_catalog) -> None:
    setup_project(
        project_root,
        {"total": "Total 1,234.56"},
        existing={"total": "Summe 1,234.56"},
    )
    cfg = make_config(project_root, targets=["de"])
    catalog = make_catalog(cfg)
    write_json(project_root / "messages" / "de" / "app.json", {
        "total": "Summe 1,234.56",
    })
    quiet = run_validation(cfg, catalog, locales=["de"])
    assert "V38" not in {f.check for f in quiet.findings}
    loud = run_validation(cfg, catalog, locales=["de"], check_numbers=True)
    assert "V38" in {f.check for f in loud.findings}
