"""Screenshot context wiring: opt-in via ``vision_model``, no-op otherwise."""

from __future__ import annotations

import base64
from pathlib import Path

from llm_localizator.pipeline.translate import run_translation
from llm_localizator.providers import NullProvider

from ..conftest import write_json
from .test_translate import setup_project, tagged

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"


def _write_context(root: Path, *, namespace: str = "app") -> Path:
    context_dir = root / "i18n" / "context"
    (context_dir / "screenshots").mkdir(parents=True)
    (context_dir / "screenshots" / "modal.png").write_bytes(PNG_BYTES)
    write_json(context_dir / f"{namespace}.json", {"greet": {"screen": "modal"}})
    return context_dir


def test_vision_model_unset_never_attaches_image(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(project_root, {"greet": "Hello"})
    context_dir = _write_context(project_root)
    cfg = make_config(project_root, context_dir=context_dir)
    catalog = make_catalog(cfg)
    provider = NullProvider(handler=tagged)

    run_translation(cfg, catalog, provider, report=silent)

    assert all(req.images is None for req in provider.calls)


def test_vision_model_set_attaches_screenshot(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(project_root, {"greet": "Hello"})
    context_dir = _write_context(project_root)
    cfg = make_config(project_root, context_dir=context_dir, vision_model="llava")
    catalog = make_catalog(cfg)
    provider = NullProvider(handler=tagged)

    run_translation(cfg, catalog, provider, report=silent)

    image_calls = [req for req in provider.calls if req.images]
    assert image_calls, "expected at least one request carrying the screenshot"
    assert image_calls[0].images == [base64.b64encode(PNG_BYTES).decode("ascii")]
    assert image_calls[0].model == "llava"


def test_mixed_batch_routes_image_bearing_item_through_singles(
    project_root, make_config, make_catalog, silent
) -> None:
    """A batch with one image item and one plain item must not silently drop
    the screenshot into a combined batch prompt where it would be ignored."""
    setup_project(project_root, {"greet": "Hello", "bye": "Goodbye"})
    context_dir = _write_context(project_root)
    cfg = make_config(project_root, context_dir=context_dir, vision_model="llava")
    catalog = make_catalog(cfg)
    provider = NullProvider(handler=tagged)

    result = run_translation(cfg, catalog, provider, report=silent)

    assert result.written == 2
    # No batch-schema request should have been made for this pair -- both
    # keys were routed through the per-key path once one carried an image.
    # (The risky-key judge, ADR-125, asks for a JSON schema too; it is scoring, not a batch translation.)
    assert all(req.schema is None for req in provider.calls if "quality judge" not in req.prompt)


def test_vision_image_is_attached_on_every_sample(
    project_root, make_config, make_catalog, silent
) -> None:
    setup_project(project_root, {"greet": "Hello"})
    context_dir = _write_context(project_root)
    cfg = make_config(
        project_root, context_dir=context_dir, vision_model="llava", multi_sample=2,
    )
    catalog = make_catalog(cfg)
    provider = NullProvider(handler=tagged)

    run_translation(cfg, catalog, provider, report=silent)

    image_calls = [req for req in provider.calls if req.images]
    assert len(image_calls) >= 2
    assert all(req.images == [base64.b64encode(PNG_BYTES).decode("ascii")] for req in image_calls)


def test_malformed_context_json_fails_before_any_call(
    project_root, make_config, make_catalog, silent
) -> None:
    from llm_localizator.projects.context import ContextError

    setup_project(project_root, {"greet": "Hello"})
    context_dir = project_root / "i18n" / "context"
    context_dir.mkdir(parents=True)
    (context_dir / "app.json").write_text("{", encoding="utf-8")
    cfg = make_config(project_root, context_dir=context_dir)
    catalog = make_catalog(cfg)
    provider = NullProvider(handler=tagged)

    try:
        run_translation(cfg, catalog, provider, report=silent)
    except ContextError as exc:
        assert "app.json" in str(exc)
    else:
        raise AssertionError("expected ContextError")
    assert provider.calls == []
