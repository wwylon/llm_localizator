"""W-08 — local accounts, role matrix, locale chips, setup, last Admin."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from llm_localizator.ops.dispatch import dispatch_op
from llm_localizator.ops.permissions import deny_message, role_allowed
from llm_localizator.projects.accounts import AccountStore, STATUS_APPROVED
from llm_localizator.projects.config import load_config
from llm_localizator.web import build_state
from llm_localizator.web.auth import Actor, locale_allowed, require_mutation
from llm_localizator.web.server import _Handler
from llm_localizator.web.shell import render_shell

from .conftest import write_json

CONFIG = """
[project]
name = "demo"
source_locale = "en"

[catalog]
format = "json-nested"
path = "messages/{locale}/{namespace}.json"

[locales]
targets = ["pl", "de"]

[provider]
kind = "null"

[state]
dir = "messages/.state"
"""


@pytest.fixture
def auth_server(tmp_path: Path):
    (tmp_path / ".llm-localize.toml").write_text(CONFIG, encoding="utf-8")
    write_json(tmp_path / "messages" / "en" / "app.json", {"greet": "Hello"})
    write_json(tmp_path / "messages" / "pl" / "app.json", {"greet": "Cześć"})
    write_json(tmp_path / "messages" / "de" / "app.json", {"greet": "Hallo"})
    cfg = load_config(tmp_path / ".llm-localize.toml")
    states = {"demo": build_state(cfg)}
    handler = type("Handler", (_Handler,), {
        "states": states,
        "default_project": "demo",
        "session_token": "secret-token",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port, cfg
    server.shutdown()


def _request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = "secret-token",
    session: str | None = None,
    cookies: CookieJar | None = None,
) -> tuple[int, dict, CookieJar]:
    jar = cookies or CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    data = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-LLM-Token"] = token
    if session:
        headers["X-LLM-Session"] = session
    if body is not None or method == "POST":
        data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with opener.open(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return resp.status, payload, jar
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw}
        return exc.code, payload, jar


def test_first_register_is_admin(auth_server) -> None:
    port, cfg = auth_server
    status, payload, jar = _request(port, "/api/auth/register", method="POST", body={
        "username": "owner",
        "password": "password1",
    })
    assert status == 200
    assert payload["ok"] is True
    assert payload["first"] is True
    assert payload["user"]["role"] == "Admin"
    assert payload["user"]["status"] == "approved"
    store = AccountStore(cfg.state_root())
    assert len(store.list_users()) == 1


def test_register_empty_project_uses_default(auth_server) -> None:
    """Auth shell has no project select; clients may POST project=\"\"."""
    port, cfg = auth_server
    status, payload, _jar = _request(port, "/api/auth/register", method="POST", body={
        "username": "owner",
        "password": "password1",
        "project": "",
    })
    assert status == 200, payload
    assert payload["ok"] is True
    assert payload["user"]["role"] == "Admin"


def test_users_list_ignores_catalogue_project_switch(tmp_path: Path) -> None:
    """Pending Approvals stay on the default store when the switcher is elsewhere."""
    from llm_localizator.web import build_state

    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    for root, name in ((root_a, "alpha"), (root_b, "beta")):
        root.mkdir()
        (root / ".llm-localize.toml").write_text(
            CONFIG.replace('name = "demo"', f'name = "{name}"'),
            encoding="utf-8",
        )
        write_json(root / "messages" / "en" / "app.json", {"greet": "Hello"})
        write_json(root / "messages" / "pl" / "app.json", {"greet": "Hi"})
        write_json(root / "messages" / "de" / "app.json", {"greet": "Hi"})
    cfg_a = load_config(root_a / ".llm-localize.toml")
    cfg_b = load_config(root_b / ".llm-localize.toml")
    handler = type("Handler", (_Handler,), {
        "states": {"alpha": build_state(cfg_a), "beta": build_state(cfg_b)},
        "default_project": "alpha",
        "session_token": "secret-token",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _request(port, "/api/auth/register", method="POST", body={
            "username": "owner", "password": "password1",
        })
        _request(port, "/api/auth/register", method="POST", body={
            "username": "pending.user", "password": "password1",
        })
        status, payload, _ = _request(
            port, "/api/auth/users", method="POST",
            body={"project": "beta"},
        )
        assert status == 200, payload
        assert payload.get("accountProject") == "alpha"
        names = {u["username"]: u["status"] for u in payload["users"]}
        assert names.get("pending.user") == "pending"
        assert names.get("owner") == "approved"
        assert not (cfg_b.state_root() / "users.json").exists()
    finally:
        server.shutdown()


def test_pending_user_can_get_pending_cannot_save(auth_server) -> None:
    port, cfg = auth_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    status, payload, jar = _request(port, "/api/auth/register", method="POST", body={
        "username": "newbie", "password": "password1",
    })
    assert status == 200
    assert payload["user"]["status"] == "pending"
    # Session cookie from register; prefer session over token for actor.
    session = None
    for cookie in jar:
        if cookie.name == "llm_session":
            session = cookie.value
            break
    assert session
    # HTML shell for /pending (not JSON).
    req = urllib.request.Request(f"http://127.0.0.1:{port}/pending")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "Pending" in html or 'data-page="pending"' in html

    save_status, save_payload, _ = _request(
        port, "/api/save", method="POST",
        token="secret-token",
        session=session,
        body={
            "project": "demo",
            "locale": "pl",
            "namespace": "app",
            "key": "greet",
            "value": "Hej",
        },
    )
    assert save_status == 403
    assert "pending" in (save_payload.get("error") or "").lower()


def test_translator_translate_same_denial_cli_and_web(auth_server) -> None:
    port, cfg = auth_server
    msg = deny_message("Translator", "translate")
    cli = dispatch_op(cfg, "translate", {"dry_run": True}, actor_role="Translator")
    assert cli["ok"] is False
    assert cli["exit_code"] == 77
    assert cli["error"] == msg
    assert not role_allowed("Translator", "translate", cfg=cfg)

    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    store.register("tr", "password1")
    users = store.list_users()
    tr = next(u for u in users if u.username == "tr")
    store.set_role(tr.id, role="Translator", locales=["pl"])
    user = store.find_by_id(tr.id)
    assert user is not None
    session = store.create_session(user)

    status, payload, _ = _request(
        port, "/api/ops/translate", method="POST",
        token="secret-token",
        session=session,
        body={"dry_run": True},
    )
    assert status == 403
    assert payload["error"] == msg
    assert payload.get("exit_code") == 77


def test_other_locale_save_refused(auth_server) -> None:
    port, cfg = auth_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    store.register("tr", "password1")
    tr = next(u for u in store.list_users() if u.username == "tr")
    store.set_role(tr.id, role="Translator", locales=["pl"])
    session = store.create_session(store.find_by_id(tr.id))

    status, payload, _ = _request(
        port, "/api/save", method="POST",
        token="secret-token",
        session=session,
        body={
            "locale": "de",
            "namespace": "app",
            "key": "greet",
            "value": "Hallo!",
        },
    )
    assert status == 403
    assert "not allowed" in (payload.get("error") or "")

    ok_status, ok_payload, _ = _request(
        port, "/api/save", method="POST",
        token="secret-token",
        session=session,
        body={
            "locale": "pl",
            "namespace": "app",
            "key": "greet",
            "value": "Hej",
        },
    )
    assert ok_status == 200
    assert ok_payload.get("ok") is True


def test_setup_load_config_succeeds(auth_server) -> None:
    port, cfg = auth_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    status, payload, _ = _request(port, "/api/setup", method="POST", body={
        "source_locale": "en",
        "targets": ["pl", "de", "fr"],
        "model": "testmodel",
        "catalog_format": "json-nested",
        "catalog_path": "messages/{locale}/{namespace}.json",
    })
    assert status == 200, payload
    assert payload["ok"] is True
    reloaded = load_config(cfg.config_path)
    assert reloaded.targets == ["pl", "de", "fr"]
    assert reloaded.models.get("default") == "testmodel"


def test_translator_cannot_post_admin_config(auth_server) -> None:
    """Settings / project-config / web-token / add-locale are Admin-only."""
    port, cfg = auth_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    store.register("tr", "password1")
    tr = next(u for u in store.list_users() if u.username == "tr")
    store.set_role(tr.id, role="Translator", locales=["pl"])
    session = store.create_session(store.find_by_id(tr.id))

    for path, body in (
        ("/api/settings", {"frozen": []}),
        ("/api/project-config", {"family": "chat"}),
        ("/api/web-token", {}),
        ("/api/add-locale", {"locale": "fr"}),
        ("/api/remove-locale", {"locale": "de"}),
        ("/api/model-eval/apply", {"report": "missing.md"}),
    ):
        status, payload, _ = _request(
            port, path, method="POST",
            token="secret-token",
            session=session,
            body=body,
        )
        assert status == 403, path
        assert "Admin" in (payload.get("error") or ""), path


def test_admin_can_post_settings(auth_server) -> None:
    port, cfg = auth_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    admin = store.list_users()[0]
    session = store.create_session(admin)
    status, payload, _ = _request(
        port, "/api/settings", method="POST",
        token="secret-token",
        session=session,
        body={"frozen": ["de"]},
    )
    assert status == 200, payload
    assert payload.get("ok") is True


def test_admin_remove_locale_and_provider_status(auth_server) -> None:
    port, cfg = auth_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    admin = store.list_users()[0]
    session = store.create_session(admin)

    status, payload, _ = _request(
        port, "/api/remove-locale", method="POST",
        token="secret-token",
        session=session,
        body={"locale": "de"},
    )
    assert status == 200, payload
    assert payload.get("ok") is True
    reloaded = load_config(cfg.config_path)
    assert "de" not in reloaded.targets
    assert "pl" in reloaded.targets

    status, payload, _ = _request(
        port, "/api/provider-status",
        token="secret-token",
        session=session,
    )
    assert status == 200, payload
    assert payload.get("ok") is True
    assert isinstance(payload.get("statuses"), dict)


def test_cannot_remove_last_admin(auth_server) -> None:
    port, cfg = auth_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    admin = store.list_users()[0]
    before = store.users_path.read_bytes()
    result = store.remove(admin.id)
    assert result["ok"] is False
    assert "last Admin" in result["error"]
    assert store.users_path.read_bytes() == before
    assert any(
        u.role == "Admin" and u.status == STATUS_APPROVED
        for u in store.list_users()
    )

    status, payload, _ = _request(
        port, "/api/auth/users/remove", method="POST",
        body={"id": admin.id},
    )
    assert status == 400
    assert "last Admin" in payload["error"]


def test_admin_cannot_remove_self(auth_server) -> None:
    port, cfg = auth_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    owner = store.list_users()[0]
    store.register("other", "password1")
    other = next(u for u in store.list_users() if u.username == "other")
    store.set_role(other.id, role="Admin", locales=[])
    session = store.create_session(store.find_by_id(owner.id))

    status, payload, _ = _request(
        port, "/api/auth/users/remove", method="POST",
        token="secret-token",
        session=session,
        body={"id": owner.id},
    )
    assert status == 400
    assert "yourself" in payload["error"]
    assert store.find_by_id(owner.id) is not None


def test_approve_can_reduce_locales(auth_server) -> None:
    port, cfg = auth_server
    _request(port, "/api/auth/register", method="POST", body={
        "username": "owner", "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    store.register("tr", "password1")
    tr = next(u for u in store.list_users() if u.username == "tr")
    admin_session = store.create_session(store.list_users()[0])

    status, payload, _ = _request(
        port, "/api/auth/users/approve", method="POST",
        token="secret-token",
        session=admin_session,
        body={"id": tr.id, "role": "Translator", "locales": ["pl", "de"]},
    )
    assert status == 200 and payload.get("ok") is True
    assert payload["user"]["locales"] == ["pl", "de"]
    # Server wrote via its own AccountStore; re-read from disk.
    refreshed = AccountStore(cfg.state_root())
    assert refreshed.find_by_id(tr.id).locales == ["pl", "de"]

    status, payload, _ = _request(
        port, "/api/auth/users/approve", method="POST",
        token="secret-token",
        session=admin_session,
        body={"id": tr.id, "role": "Translator", "locales": ["pl"]},
    )
    assert status == 200 and payload.get("ok") is True
    assert payload["user"]["locales"] == ["pl"]
    refreshed = AccountStore(cfg.state_root())
    assert refreshed.find_by_id(tr.id).locales == ["pl"]

def test_token_snippet_attaches_on_get() -> None:
    from llm_localizator.web.shell import token_snippet

    snippet = token_snippet("secret-token")
    # Token is fetched from /api/bootstrap-token — not inlined into HTML.
    assert "secret-token" not in snippet
    assert "/api/bootstrap-token" in snippet
    assert "X-LLM-Token" in snippet
    # Locale-gated GETs need the token; do not gate on method !== GET.
    assert "method!=='GET'" not in snippet
    assert "method!==\"GET\"" not in snippet


def test_auth_pages_render() -> None:
    for route in ("login", "register", "pending", "setup", "users", "activity"):
        html = render_shell(route)
        assert f'data-page="{route}"' in html
    users = render_shell("users")
    assert "Users &amp; roles" in users or "Users & roles" in users
    assert 'id="invite-open"' in users
    assert "Manage who can access the workspace" in users
    activity = render_shell("activity")
    assert "Team activity" in activity
    from llm_localizator.web.server import _SHELL_STATIC

    assert "/static/auth.js" in _SHELL_STATIC
    assert "/static/setup.js" in _SHELL_STATIC
    assert "/static/users.js" in _SHELL_STATIC
    assert "/static/translator-activity.js" in _SHELL_STATIC

def test_locale_allowed_helpers() -> None:
    from llm_localizator.projects.accounts import UserRecord

    tr = UserRecord(
        id="1", username="t", password_hash="x",
        status=STATUS_APPROVED, role="Translator", locales=["pl"],
    )
    actor = Actor(kind="user", role="Translator", user=tr)
    assert locale_allowed(actor, "pl")
    assert not locale_allowed(actor, "de")
    assert require_mutation(Actor(kind="anonymous")) is not None

    admin = UserRecord(
        id="2", username="a", password_hash="x",
        status=STATUS_APPROVED, role="Admin", locales=[],
    )
    admin_actor = Actor(kind="user", role="Admin", user=admin)
    assert locale_allowed(admin_actor, "pl")
    admin.locales = ["de"]
    assert locale_allowed(admin_actor, "pl")
    empty = UserRecord(
        id="3", username="e", password_hash="x",
        status=STATUS_APPROVED, role="Translator", locales=[],
    )
    assert not locale_allowed(Actor(kind="user", role="Translator", user=empty), "pl")
    assert not locale_allowed(Actor(kind="anonymous"), "pl")


def _session_value(jar: CookieJar) -> str | None:
    for cookie in jar:
        if cookie.name == "llm_session":
            return cookie.value
    return None


def test_admin_can_read_locale_outside_assigned_chips(auth_server) -> None:
    port, cfg = auth_server
    status, payload, jar = _request(port, "/api/auth/register", method="POST", body={
        "username": "owner",
        "password": "password1",
    })
    assert status == 200, payload
    session = _session_value(jar)
    assert session
    store = AccountStore(cfg.state_root())
    owner = store.find_by_username("owner")
    assert owner is not None
    assert owner.locales == []

    status, payload, _ = _request(
        port,
        "/api/messages?project=demo&locales=pl&namespace=app",
        token=None,
        session=session,
    )
    assert status == 200, payload
    assert payload.get("ok") is not False
    assert payload["rows"]
    assert payload["rows"][0]["values"]["pl"] == "Cześć"

    assert store.set_role(owner.id, role="Admin", locales=["de"])["ok"]
    status, payload, _ = _request(
        port,
        "/api/messages?project=demo&locales=pl&namespace=app",
        token=None,
        session=session,
    )
    assert status == 200, payload
    assert payload.get("rows")

    _request(port, "/api/auth/register", method="POST", body={
        "username": "tr",
        "password": "password1",
    })
    store = AccountStore(cfg.state_root())
    translator = store.find_by_username("tr")
    assert translator is not None
    assert store.set_role(translator.id, role="Translator", locales=[])["ok"]
    status, _login, tr_jar = _request(port, "/api/auth/login", method="POST", body={
        "username": "tr",
        "password": "password1",
    })
    assert status == 200
    tr_session = _session_value(tr_jar)
    status, payload, _ = _request(
        port,
        "/api/messages?project=demo&locales=pl&namespace=app",
        token=None,
        session=tr_session,
    )
    assert status == 403
    assert "not allowed" in (payload.get("error") or "")

    status, payload, _ = _request(
        port,
        "/api/messages?project=demo&locales=pl&namespace=app",
        token=None,
    )
    # No session, no token: /api/messages is an "auth" GET (get_policy.py), so anonymous is 401, not 403.
    assert status == 401, payload


def test_settings_permission_rows_match_operations() -> None:
    from llm_localizator.ops.permissions import OPERATIONS
    from llm_localizator.web.settings import settings_view
    from llm_localizator.projects.config import load_config
    from pathlib import Path
    import tempfile

    html = render_shell("settings")
    assert 'data-tab="permissions"' in html
    assert "System settings" in html

    # Matrix metadata comes from the API payload, not server HTML.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".llm-localize.toml").write_text(
            "[project]\nname = \"demo\"\nsource_locale = \"en\"\n\n"
            "[catalog]\nformat = \"json-nested\"\n"
            "path = \"messages/{locale}/{namespace}.json\"\n\n"
            "[locales]\ntargets = [\"de\"]\n\n"
            "[provider]\nkind = \"ollama\"\n",
            encoding="utf-8",
        )
        cfg = load_config(root / ".llm-localize.toml")
        view = settings_view(cfg, port=8770)
        assert view["permissionMeta"]["operations"] == list(OPERATIONS)
        assert "term-report" in view["permissionMeta"]["operations"]
        assert "release-freeze" in view["permissionMeta"]["operations"]
        assert "release-diff" in view["permissionMeta"]["operations"]
        assert view["permissionMeta"]["defaults"]["translate"][2] is False


def test_translator_cannot_switch_project(tmp_path: Path) -> None:
    """Translator on the default project must not mutate another catalogue."""
    root_a = tmp_path / "alpha"
    root_b = tmp_path / "beta"
    for root, name in ((root_a, "alpha"), (root_b, "beta")):
        root.mkdir()
        (root / ".llm-localize.toml").write_text(
            CONFIG.replace('name = "demo"', f'name = "{name}"'),
            encoding="utf-8",
        )
        write_json(root / "messages" / "en" / "app.json", {"greet": "Hello"})
        write_json(root / "messages" / "pl" / "app.json", {"greet": "Hi"})
        write_json(root / "messages" / "de" / "app.json", {"greet": "Hi"})
    cfg_a = load_config(root_a / ".llm-localize.toml")
    cfg_b = load_config(root_b / ".llm-localize.toml")
    handler = type("Handler", (_Handler,), {
        "states": {"alpha": build_state(cfg_a), "beta": build_state(cfg_b)},
        "default_project": "alpha",
        "session_token": "secret-token",
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _request(port, "/api/auth/register", method="POST", body={
            "username": "owner", "password": "password1",
        })
        store = AccountStore(cfg_a.state_root())
        store.register("tr", "password1")
        tr = next(u for u in store.list_users() if u.username == "tr")
        store.set_role(tr.id, role="Translator", locales=["pl"])
        session = store.create_session(store.find_by_id(tr.id))

        status, payload, _ = _request(
            port, "/api/save", method="POST",
            token="secret-token",
            session=session,
            body={
                "project": "beta",
                "locale": "pl",
                "namespace": "app",
                "key": "greet",
                "value": "Hacked",
            },
        )
        assert status == 403, payload
        assert "not allowed" in payload.get("error", "")
        pl_path = root_b / "messages" / "pl" / "app.json"
        assert json.loads(pl_path.read_text(encoding="utf-8"))["greet"] == "Hi"
    finally:
        server.shutdown()
