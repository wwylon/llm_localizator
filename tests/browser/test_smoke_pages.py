"""Broader UI smoke beyond workflow (Wave F). Deselected unless -m browser."""

from __future__ import annotations

import re


def _open(ui, path: str, project: str = "src") -> None:
    ui.page.goto(ui.base + path)
    ui.page.evaluate("p => localStorage.setItem('llm_project', p)", project)
    ui.page.goto(ui.base + path)


def _no_errors(ui) -> None:
    assert not ui.errors, ui.errors


def test_settings_save_round_trip(ui) -> None:
    _open(ui, "/app/settings")
    ui.page.wait_for_selector(".settings-card, #settings-root, .settings-tabs", timeout=15000)
    # Domain / description field if present — otherwise just ensure paint.
    save = ui.page.get_by_role("button", name=re.compile(r"Save", re.I)).first
    if save.count():
        save.click()
        ui.page.get_by_text(re.compile(r"Saved|Save failed", re.I)).first.wait_for(timeout=10000)
    _no_errors(ui)


def test_review_page_loads_and_lists(ui) -> None:
    _open(ui, "/app/review")
    # CSS only: a Playwright ``text=`` engine cannot sit inside a CSS selector list.
    ui.page.wait_for_selector(".rq-title, .rq-list-head", timeout=15000)
    _no_errors(ui)


def test_dashboard_aggregate_with_startup_token(ui) -> None:
    """Startup-token Admin can load /api/dashboard (Wave 3 auth path)."""
    _open(ui, "/app/")
    ui.page.wait_for_selector("#page-body, #dash-title", timeout=15000)
    result = ui.page.evaluate(
        """async () => {
            const r = await fetch('/api/dashboard?project=' + encodeURIComponent(
              localStorage.getItem('llm_project') || 'src'
            ), {
              headers: { 'X-LLM-Token': window.__LLM_TOKEN || '' },
            });
            return { status: r.status, body: await r.json() };
        }"""
    )
    assert result["status"] == 200
    assert result["body"].get("ok") is True
    assert "lite" in result["body"]
    _no_errors(ui)


def test_dashboard_scan_card_without_a_scan(ui) -> None:
    """M6: before the first scan the Hardcoded card says so instead of staying empty."""
    _open(ui, "/app/")
    ui.page.wait_for_selector("#dash-scan .dash-section", timeout=20000)
    text = ui.page.inner_text("#dash-scan")
    assert "No scan yet." in text
    _no_errors(ui)


def test_ops_status_post(ui) -> None:
    _open(ui, "/app/operations")
    ui.page.wait_for_timeout(500)
    result = ui.page.evaluate(
        """async () => {
            const r = await fetch('/api/ops/status', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-LLM-Token': window.__LLM_TOKEN || '',
              },
              body: JSON.stringify({ project: localStorage.getItem('llm_project') || 'src' }),
            });
            return { status: r.status, body: await r.json() };
        }"""
    )
    assert result["status"] == 200
    assert result["body"].get("ok") is True
    _no_errors(ui)


def test_dark_theme_matrix_pages(ui) -> None:
    """Light then dark: key surfaces paint without console errors (Wave F matrix)."""
    pages = ("/app/", "/app/editor", "/app/settings", "/app/review", "/app/operations", "/app/queue")
    _open(ui, "/app/")  # about:blank has no localStorage
    for theme in ("light", "dark"):
        ui.page.evaluate(
            "(t) => { localStorage.setItem('llm_ui_theme', t); "
            "document.documentElement.setAttribute('data-theme', t); }",
            theme,
        )
        for path in pages:
            _open(ui, path)
            ui.page.wait_for_timeout(250)
            attr = ui.page.evaluate("() => document.documentElement.getAttribute('data-theme')")
            assert attr == theme, (path, theme, attr)
            _no_errors(ui)


def test_project_switch_cancels_stale_nav(ui) -> None:
    _open(ui, "/app/tm")
    ui.page.wait_for_timeout(300)
    sel = ui.page.locator("#project-select")
    if sel.count() == 0:
        return
    options = sel.locator("option").all_text_contents()
    if len(options) < 2:
        return
    values = sel.locator("option").evaluate_all("els => els.map(e => e.value)")
    sel.select_option(values[1])
    ui.page.wait_for_timeout(400)
    sel.select_option(values[0])
    ui.page.wait_for_timeout(400)
    _no_errors(ui)


def test_settings_engine_card_lists_engines_and_roles(ui) -> None:
    """W2 (ADR-156): the engine card shows each role's model and the engine list; the provider table is back (W1)."""
    _open(ui, "/app/settings")
    ui.page.wait_for_selector(".eng-roles tbody tr", timeout=15000)
    ui.page.wait_for_selector(".eng-list table tbody tr", timeout=15000)
    text = ui.page.inner_text(".eng-list")
    assert "Claude Haiku 5.5" in text and "8 GB" in text
    roles = ui.page.inner_text(".eng-roles")
    assert "Translate" in roles and "Score" in roles
    assert ui.page.locator("tr[data-provider-id]").count() >= 1
    ui.page.screenshot(path=str(ui.dst.root / "engine-card.png"), full_page=True)
    _no_errors(ui)


def test_operations_engine_select_and_cost_modal(ui) -> None:
    """W4: translate gets a run-only engine select; a paid estimate opens an in-page modal, not window.confirm."""
    import json

    seen: dict = {}

    def estimate(route) -> None:
        seen["body"] = json.loads(route.request.post_data or "{}")
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "ok": True, "data": {"local": False, "batch_usd": 0.01, "max_usd": 0.02, "remaining_usd": 4.5,
                                 "keys": 2, "provider": "anthropic", "model": "claude-haiku-5-5"}}))

    ui.page.route("**/api/ops/estimate-cost", estimate)
    ui.page.on("dialog", lambda d: (seen.setdefault("dialog", d.message), d.dismiss()))
    _open(ui, "/app/operations?command=translate")
    ui.page.wait_for_selector(".op-engine-field:not([hidden]) #op-engine", timeout=15000)
    ui.page.select_option("#op-engine", "claude-haiku")
    ui.page.get_by_role("button", name=re.compile(r"Run$")).first.click()
    ui.page.wait_for_selector(".op-cost-modal", timeout=10000)
    text = ui.page.inner_text(".op-cost-modal")
    assert "claude-haiku" in text and "$4.5" in text
    assert seen["body"].get("engine") == "claude-haiku"
    ui.page.locator(".op-cost-modal").get_by_role("button", name="Cancel").click()
    assert ui.page.locator(".op-cost-modal").count() == 0
    assert "dialog" not in seen
    _no_errors(ui)


def test_dashboard_scan_card_has_run_button_and_findings_page_empty_state(ui) -> None:
    """W5: no scan yet means a real empty state with a Run-a-scan button, on the card and on the page."""
    _open(ui, "/app/")
    ui.page.wait_for_selector("#dash-scan .dash-scan-run", timeout=20000)
    _open(ui, "/app/hardcoded")
    ui.page.wait_for_selector(".hc-empty .hc-scan-run", timeout=15000)
    _no_errors(ui)


def test_findings_page_filters_explains_and_decides(ui) -> None:
    """W5: stored hits grouped by file, tier filter, explain drill-down and accept via scan-decide."""
    import json

    state = ui.src.state_root()
    state.mkdir(parents=True, exist_ok=True)
    (ui.src.root / "app.js").write_text('const a = "Save changes";\nconst b = "Cancel";\n', encoding="utf-8")
    (state / "scan_cache.json").write_text(json.dumps({"key": "k", "filesScanned": 1, "hits": [
        {"file": "app.js", "line": 1, "text": "Save changes", "confidence": "high"},
        {"file": "app.js", "line": 2, "text": "Cancel", "confidence": "low"},
    ]}), encoding="utf-8")
    # The fixture project has no scan adapter, so scan-decide cannot rebuild the live hits: stub it and check the body.
    sent: dict = {}

    def decide(route) -> None:
        sent.update(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": True, "summary": "accepted 1 hit(s)", "data": {"applied": 0}}))

    ui.page.route("**/api/ops/scan-decide", decide)
    _open(ui, "/app/hardcoded")
    ui.page.wait_for_selector(".hc-file .hc-row", timeout=15000)
    assert ui.page.locator(".hc-row").count() == 1  # high tier first
    ui.page.click(".hc-filter [data-tier='all']")
    assert ui.page.locator(".hc-row").count() == 2
    ui.page.locator(".hc-explain-btn").first.click()
    ui.page.wait_for_selector(".hc-explain-out", timeout=15000)
    assert ui.page.inner_text(".hc-explain-out").strip()
    ui.page.locator(".hc-row").first.get_by_role("button", name="Accept").click()
    ui.page.wait_for_function("document.querySelectorAll('.hc-row').length === 1", timeout=10000)
    assert sent["action"] == "accept" and len(sent["ids"]) == 1
    # Without a scan adapter explain-scan answers 400 with its reason, which the drill-down shows; that is expected.
    ui.errors[:] = [e for e in ui.errors if "explain-scan" not in e and "status of 400" not in e]
    _no_errors(ui)


def test_setup_wizard_starts_with_engine_step(ui) -> None:
    """W6: the first wizard step lists the engines from the engine op with a Use button; Next still moves on."""
    _open(ui, "/setup")
    ui.page.wait_for_selector(".setup-engine-table tbody tr", timeout=15000)
    assert ui.page.locator(".wizard-step").first.inner_text().strip() == "Engine"
    assert ui.page.locator(".setup-engine-table tr[data-engine='claude-haiku']").count() == 1
    # Unbenchmarked engines need an explicit tick before Use (ADR-12).
    row = ui.page.locator(".setup-engine-table tr[data-engine='local-16gb']")
    if row.count():
        assert row.get_by_role("button").is_disabled()
    ui.page.get_by_role("button", name="Next").click()
    ui.page.wait_for_selector(".wizard-step.is-current:nth-child(2)", timeout=5000)
    _no_errors(ui)


def test_dashboard_approach_step_records_choice(ui) -> None:
    """W6: the getting-started approach step has a real button (approach op) instead of only the CLI hint."""
    _open(ui, "/app/")
    ui.page.wait_for_selector(".dash-approach-use", timeout=20000)
    ui.page.select_option(".dash-approach-select", "agent")
    ui.page.click(".dash-approach-use")
    # The op probes the machine (Ollama), then the server reloads the config and the guide marks the step done.
    ui.page.wait_for_function("() => !document.querySelector('.dash-approach-use')", timeout=30000)
    assert 'approach = "agent"' in (ui.src.root / ".llm-localize.toml").read_text(encoding="utf-8")
    _no_errors(ui)


def test_queue_page_lists_blueprints_with_daemon_banner(ui, monkeypatch, tmp_path) -> None:
    """W3: blueprint tasks with lane and status; no daemon/DB means a banner and never a start button."""
    from llm_localizator.projects.taskqueue import blueprint_filename, generate_blueprint

    monkeypatch.setenv("TQDAEMON_HOME", str(tmp_path / "no-tq"))
    out = ui.src.root / "experiments" / "operator_queue"
    out.mkdir(parents=True, exist_ok=True)
    (out / blueprint_filename("sync")).write_text(generate_blueprint(ui.src, "sync"), encoding="utf-8")
    _open(ui, "/app/queue")
    ui.page.wait_for_selector(".q-table tbody tr", timeout=15000)
    assert "localize_sync" in ui.page.inner_text(".q-table")
    assert ui.page.locator(".q-banner").count() == 1
    assert ui.page.get_by_role("button", name=re.compile(r"start", re.I)).count() == 0
    ui.page.wait_for_selector(".q-switch:not([hidden]) .q-engine-select option", state="attached", timeout=15000)
    _no_errors(ui)
