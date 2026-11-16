"""HTTP tests for the ``/api/workflow*`` endpoints (ADR-62/63)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_localizator.projects import load_config
from llm_localizator.web import build_state
from llm_localizator.web.server import _Handler

from .conftest import write_json

CONFIG = """
[project]
name = "{name}"

[catalog]
path = "messages/{{locale}}/{{namespace}}.json"

[locales]
targets = {targets}

[state]
dir = "messages/.state"
"""


def _make(root: Path, name: str, targets: str):
    root.mkdir(parents=True, exist_ok=True)
    (root / ".llm-localize.toml").write_text(
        CONFIG.format(name=name, targets=targets), encoding="utf-8")
    write_json(root / "messages" / "en" / "app.json", {"greet": "Hello"})
    return load_config(root / ".llm-localize.toml")


@pytest.fixture
def server(tmp_path: Path):
    src = _make(tmp_path / "src", "src", '["pl", "ar"]')
    dst = _make(tmp_path / "dst", "dst", '["pl"]')
    handler = type("Handler", (_Handler,), {
        "states": {"src": build_state(src), "dst": build_state(dst)},
        "default_project": "src",
    })
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], dst
    httpd.shutdown()


def _call(port: int, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _save(port: int, workflows: dict, **extra) -> tuple[int, dict]:
    return _call(port, "/api/workflow", {"workflows": workflows, **extra})


def test_save_script_workflow_and_read_back(server) -> None:
    port, _ = server
    script = [{"type": "translate"}, {"type": "improve", "max_loops": 1}]
    code, res = _save(port, {"default": {"script": script}})
    assert code == 200 and res["ok"], res
    code, view = _call(port, "/api/workflow")
    assert code == 200
    wf = view["workflows"][0]
    assert wf["script"][1] == {"type": "improve", "max_loops": 1}
    assert view["assignments"]["byLocale"] == {"pl": "default", "ar": "default"}


def test_save_rejects_bad_block(server) -> None:
    port, _ = server
    code, res = _save(port, {"default": {"script": [{"type": "nope"}]}})
    assert code == 400 and not res["ok"]


def test_run_and_cancel_unknown_ids_are_404(server) -> None:
    port, _ = server
    assert _call(port, "/api/workflow/run?id=wf_nope")[0] == 404
    assert _call(port, "/api/workflow/cancel", {"id": "wf_nope"})[0] == 404


def test_summary_lists_locales_and_uncovered(server) -> None:
    port, _ = server
    _save(port, {"arabic": {"script": [{"type": "verify"}], "locales": ["ar"]}})
    code, res = _call(port, "/api/workflow/summary")
    assert code == 200
    assert res["locales"]["ar"]["workflow"] == "arabic"
    assert res["locales"]["pl"]["workflow"] is None
    assert res["uncovered"] == ["pl"]


def test_copy_merges_drops_locales_and_refuses_overwrite(server) -> None:
    port, dst = server
    _save(port, {
        "default": {"script": [{"type": "verify"}]},
        "both": {"script": [{"type": "verify"}], "locales": ["pl", "ar"]},
    })
    code, res = _call(port, "/api/workflow/copy", {"name": "both", "toProject": "dst"})
    assert code == 200 and res["droppedLocales"] == ["ar"], res
    back = load_config(dst.config_path)
    assert back.workflows["both"]["locales"] == ["pl"]
    code, res = _call(port, "/api/workflow/copy", {"name": "both", "toProject": "dst"})
    assert code == 400 and "already exists" in res["error"]
    code, res = _call(port, "/api/workflow/copy",
                      {"name": "both", "toProject": "dst", "overwrite": True})
    assert code == 200
    code, res = _call(port, "/api/workflow/copy", {"name": "both", "toProject": "dst",
                                                   "newName": "renamed"})
    assert code == 200 and "renamed" in load_config(dst.config_path).workflows


def test_copy_errors(server) -> None:
    port, _ = server
    _save(port, {"default": {"script": [{"type": "verify"}]}})
    assert _call(port, "/api/workflow/copy", {"name": "zzz", "toProject": "dst"})[0] == 404
    assert _call(port, "/api/workflow/copy", {"name": "default"})[0] == 400
    assert _call(port, "/api/workflow/copy", {"name": "default", "toProject": "ghost"})[0] == 404


def test_summary_reports_overlap_first_alphabetical_wins(server) -> None:
    port, _ = server
    _save(port, {
        "b": {"script": [{"type": "verify"}], "locales": ["ar", "pl"]},
        "a": {"script": [{"type": "verify"}], "locales": ["ar"]},
    })
    code, res = _call(port, "/api/workflow/summary")
    assert code == 200
    assert res["overlaps"]
    assert res["locales"]["ar"]["workflow"] == "a"
    assert res["locales"]["pl"]["workflow"] == "b"


def test_summary_shows_last_run_after_a_run(server) -> None:
    port, _ = server
    _save(port, {"default": {"script": [{"type": "verify"}]}})
    code, res = _call(port, "/api/ops/workflow", {"name": "default"})
    assert code == 200, res
    code, res = _call(port, "/api/workflow/summary")
    last = res["locales"]["pl"]["lastRun"]
    assert last and last["runId"]


def test_copy_keeps_notify_but_not_webhook(server) -> None:
    port, dst = server
    hook = "https://hooks.example.com/abc"
    code, res = _save(port, {"n": {"script": [{"type": "verify"}], "notify": "webhook"}},
                      notifyWebhook=hook)
    assert code == 200, res
    code, res = _call(port, "/api/workflow/copy", {"name": "n", "toProject": "dst"})
    assert code == 200, res
    back = load_config(dst.config_path)
    assert back.workflows["n"]["notify"] == "webhook"
    assert not getattr(back, "notify_webhook", "")


def test_copy_blank_new_name_falls_back_to_source_name(server) -> None:
    port, dst = server
    _save(port, {"keep": {"script": [{"type": "verify"}]}})
    code, res = _call(port, "/api/workflow/copy",
                      {"name": "keep", "toProject": "dst", "newName": ""})
    assert code == 200 and res["name"] == "keep"
    assert "keep" in load_config(dst.config_path).workflows


# --- authorization (accounts enabled) ---------------------------------------

from .test_w08 import _request, auth_server  # noqa: E402,F401  (fixture re-export)
from llm_localizator.projects.accounts import AccountStore  # noqa: E402


def _login(cfg, name: str, role: str, locales: list[str]) -> str:
    store = AccountStore(cfg.state_root())
    store.register(name, "password1")
    user = next(u for u in store.list_users() if u.username == name)
    store.set_role(user.id, role=role, locales=locales)
    return store.create_session(store.find_by_id(user.id))


def test_workflow_writes_need_an_edit_role(auth_server) -> None:
    port, cfg = auth_server
    _request(port, "/api/auth/register", method="POST",
             body={"username": "owner", "password": "password1"})
    admin = _login(cfg, "boss", "Admin", ["pl", "de"])
    translator = _login(cfg, "tr", "Translator", ["pl"])
    wf = {"workflows": {"w": {"script": [{"type": "verify"}]}}}

    code, _, _ = _request(port, "/api/workflow", method="POST", body=wf, session=translator)
    assert code == 403
    code, _, _ = _request(port, "/api/workflow", method="POST", body=wf, token=None)
    assert code == 403  # neither startup token nor session
    code, res, _ = _request(port, "/api/workflow", method="POST", body=wf, session=admin)
    assert code == 200, res

    copy = {"name": "w", "toProject": "demo", "newName": "w2"}
    code, _, _ = _request(port, "/api/workflow/copy", method="POST", body=copy,
                          session=translator)
    assert code == 403
    code, res, _ = _request(port, "/api/workflow/copy", method="POST", body=copy,
                            session=admin)
    assert code == 200, res
    code, res, _ = _request(port, "/api/workflow/copy", method="POST", session=admin,
                            body={"name": "w", "toProject": "ghost"})
    assert code == 404


def test_every_script_the_shell_references_is_served() -> None:
    """Regression: /static/api.js was referenced by the shell but never routed (404)."""
    import re

    from llm_localizator.web import shell
    from llm_localizator.web.server_logic import _SHELL_STATIC, _SHELL_STATIC_DIR

    refs = set(re.findall(r'"(/static/[\w./-]+\.js)"', Path(shell.__file__).read_text(encoding="utf-8")))
    assert refs
    for ref in refs:
        assert ref in _SHELL_STATIC, ref
        assert (_SHELL_STATIC_DIR / _SHELL_STATIC[ref][0]).is_file(), ref


def test_get_run_never_advances_and_resume_is_post_only(server, monkeypatch) -> None:
    port, _ = server
    from llm_localizator.ops import workflow_run

    def boom(*a, **k):
        raise AssertionError("GET must not resume a run")

    monkeypatch.setattr(workflow_run, "resume_run", boom)
    assert _call(port, "/api/workflow/run?id=wf_nope")[0] == 404
    assert _call(port, "/api/workflow/resume", {"id": "wf_nope"})[0] == 404
