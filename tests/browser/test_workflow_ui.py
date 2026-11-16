"""Workflow page and its visibility surfaces, driven in a real browser (ADR-27 amendment)."""

from __future__ import annotations

import re

from llm_localizator.projects import load_config

from ..test_workflow_http import _call  # noqa: F401  (plain HTTP helper, reused below)

WF = "/app/workflow"


def _open(ui, path: str = WF, project: str = "src") -> None:
    ui.page.goto(ui.base + path)
    ui.page.evaluate("p => localStorage.setItem('llm_project', p)", project)
    ui.page.goto(ui.base + path)
    if path == WF:
        ui.page.wait_for_selector(".wf-tab")


def _post(ui, path: str, body: dict) -> dict:
    return ui.page.evaluate(
        """async ([path, body]) => {
            const r = await fetch(path, {method: "POST", body: JSON.stringify(body),
              headers: {"Content-Type": "application/json", "X-LLM-Token": window.__LLM_TOKEN || ""}});
            return await r.json();
        }""", [path, body])


def _save_via_ui(ui) -> None:
    ui.page.get_by_role("button", name=re.compile(r"^Save")).click()
    ui.page.get_by_text("Saved.", exact=True).wait_for()


def _no_errors(ui) -> None:
    assert not ui.errors, ui.errors


def test_project_switch_reloads_locales(ui) -> None:
    _open(ui)
    ui.page.get_by_text("Applies to: pl, ar").first.wait_for()
    ui.page.select_option("#project-select", "dst")
    ui.page.get_by_text("Applies to: pl", exact=True).first.wait_for()
    assert ui.page.locator("text=Applies to: pl, ar").count() == 0
    _no_errors(ui)


def test_webhook_url_only_when_relevant(ui) -> None:
    _open(ui)
    ui.page.wait_for_selector(".wf-tab")
    assert ui.page.get_by_text("Webhook URL").count() == 0
    notify = ui.page.locator("select", has=ui.page.locator("option[value=webhook]")).first
    notify.select_option("webhook")
    ui.page.get_by_text("Webhook URL").first.wait_for()
    notify.select_option("none")
    assert ui.page.get_by_text("Webhook URL").count() == 0
    ui.page.locator(".wf-pal", has_text="Send webhook").click()
    ui.page.get_by_text("Webhook URL").first.wait_for()
    _no_errors(ui)


def test_per_block_loops_persist(ui) -> None:
    _open(ui)
    loops = ui.page.locator(".wf-loops").first
    loops.wait_for()
    loops.fill("1")
    loops.dispatch_event("change")
    _save_via_ui(ui)
    toml = ui.src.config_path.read_text(encoding="utf-8")
    assert "max_loops = 1" in toml
    ui.page.reload()
    assert ui.page.locator(".wf-loops").first.input_value() == "1"
    assert ui.page.get_by_text("Max improve loops").count() == 0  # no Settings-level field
    _no_errors(ui)


def test_duplicate_is_unsaved_until_save(ui) -> None:
    _open(ui)
    ui.page.get_by_role("button", name="Duplicate").click()
    ui.page.locator(".wf-tab", has_text="default-copy").wait_for()
    assert "default-copy" not in ui.src.config_path.read_text(encoding="utf-8")
    _save_via_ui(ui)
    assert "default-copy" in ui.src.config_path.read_text(encoding="utf-8")
    _no_errors(ui)


def test_copy_to_project_drops_missing_locale(ui) -> None:
    _open(ui)
    ui.page.wait_for_selector(".wf-tab")
    # scope the workflow to ar+pl, save, then copy to dst (which only has pl)
    ui.page.locator(".wf-tab", has_text="default").first.click()
    res = _post(ui, "/api/workflow", {"workflows": {"default": {
        "script": [{"type": "verify"}], "locales": ["pl", "ar"]}}})
    assert res["ok"], res
    ui.page.reload()
    ui.page.wait_for_selector(".wf-tab")
    ui.page.get_by_role("button", name="Copy to project…").click()
    modal = ui.page.locator(".br-modal")
    modal.locator("select").select_option("dst")
    modal.get_by_role("button", name="Copy", exact=True).click()
    ui.page.get_by_text("Locales not in the target were dropped: ar").wait_for()
    back = load_config(ui.dst.config_path)
    assert back.workflows["default"]["locales"] == ["pl"]
    _no_errors(ui)


def test_scope_warnings(ui) -> None:
    res = _post_after_open(ui, {"workflows": {
        "arabic": {"script": [{"type": "verify"}], "locales": ["ar"]}}})
    assert res["ok"], res
    ui.page.reload()
    ui.page.locator(".wf-tab-scope", has_text="ar").first.wait_for()
    ui.page.get_by_text("pl", exact=False).first.wait_for()
    assert ui.page.locator(".wf-warn").count() >= 1  # pl has no workflow
    _no_errors(ui)


def _post_after_open(ui, body: dict) -> dict:
    _open(ui)
    ui.page.wait_for_selector(".wf-tab")
    return _post(ui, "/api/workflow", body)


def test_operations_card_and_dashboard_line_and_editor_chip(ui) -> None:
    res = _post_after_open(ui, {"workflows": {
        "default": {"script": [{"type": "verify"}]},
        "arabic": {"script": [{"type": "verify"}], "locales": ["ar"]},
    }})
    assert res["ok"], res

    # The Run-workflow card moved from Operations to the Workflow page (280c4f9); Operations links there.
    ui.page.goto(ui.base + "/app/operations")
    link = ui.page.locator(".op-wf-link")
    link.wait_for()
    assert link.get_attribute("href") == "/app/workflow"

    ui.page.goto(ui.base + "/app")
    ui.page.locator(".locale-workflow").first.wait_for()
    text = " ".join(ui.page.locator(".locale-workflow").all_inner_texts())
    assert "arabic" in text and "default" in text

    ui.page.goto(ui.base + "/app/editor")
    chip = ui.page.locator(".wf-chip")
    chip.wait_for()
    assert chip.inner_text().strip()
    _no_errors(ui)


def test_help_modals_open(ui) -> None:
    _open(ui)
    ui.page.wait_for_selector(".wf-tab")
    triggers = ui.page.locator(".help-trigger")
    assert triggers.count() >= 2
    for i in range(min(3, triggers.count())):
        triggers.nth(i).click()
        body = ui.page.locator(".help-modal-body")
        body.wait_for()
        assert len(body.inner_text().strip()) > 40
        ui.page.locator(".help-close").click()
        body.wait_for(state="detached")
    _no_errors(ui)


def test_new_workflow_offers_server_presets(ui) -> None:
    _open(ui)
    ui.page.get_by_role("button", name=re.compile(r"New workflow")).first.click()
    options = ui.page.locator(".br-modal select option").all_inner_texts()
    assert any("validate" in o.lower() for o in options), options
    ui.page.locator(".br-modal input[type=text]").fill("presetwf")
    ui.page.locator(".br-modal select").select_option("tm_llm_validate")
    ui.page.get_by_role("button", name="Create").click()
    ui.page.get_by_text("Saved.", exact=True).wait_for()
    assert ui.page.locator(".wf-blk-name", has_text="Validate").count() == 1
    _no_errors(ui)
