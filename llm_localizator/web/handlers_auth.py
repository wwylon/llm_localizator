"""Account and setup POST routes (ADR-39), split out of ``server.do_POST``."""

from __future__ import annotations


class AuthRoutesMixin:
    """Handlers share the ``(url, body, st, actor, project)`` signature."""

    def _post_auth_register(self, url, body, st, actor, project):
        from .auth import SESSION_COOKIE, accounts_for, public_me

        store = accounts_for(self._accounts_cfg())
        result = store.register(
            str(body.get("username") or ""),
            str(body.get("password") or ""),
        )
        if not result.get("ok"):
            return self._send(result, 400)
        user = store.find_by_id(result["user"]["id"])
        cookies = []
        from .auth import Actor

        actor = Actor(kind="anonymous")
        if user is not None:
            token = store.create_session(user)
            cookies.append(
                f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=1209600"
            )
            actor = Actor(kind="user", role=user.role, user=user)
        payload = public_me(actor)
        payload["ok"] = True
        payload["first"] = bool(result.get("first"))
        return self._send(payload, set_cookies=cookies or None)

    def _post_auth_login(self, url, body, st, actor, project):
        from .auth import SESSION_COOKIE, accounts_for, public_me, Actor

        store = accounts_for(self._accounts_cfg())
        if store.is_locked(str(body.get("username") or "")):
            return self._send(
                {"ok": False, "error": "too many failed attempts; try again in a minute"}, 429,
            )
        user = store.authenticate(
            str(body.get("username") or ""),
            str(body.get("password") or ""),
        )
        if user is None:
            return self._send({"ok": False, "error": "invalid credentials"}, 403)
        token = store.create_session(user)
        actor = Actor(kind="user", role=user.role, user=user)
        payload = public_me(actor)
        payload["ok"] = True
        return self._send(
            payload,
            set_cookies=[
                f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=1209600",
            ],
        )

    def _post_auth_logout(self, url, body, st, actor, project):
        from .auth import SESSION_COOKIE, accounts_for

        store = accounts_for(self._accounts_cfg())
        store.drop_session(self._session_token())
        return self._send(
            {"ok": True},
            set_cookies=[
                f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
            ],
        )

    def _post_auth_users(self, url, body, st, actor, project):
        from .auth import accounts_for, require_mutation

        actor = self._actor()
        denied = require_mutation(actor)
        if denied is not None or not actor.is_admin:
            return self._send(
                denied or {"ok": False, "error": "Admin required"}, 403,
            )
        store = accounts_for(self._accounts_cfg())
        return self._send({
            "ok": True,
            "accountProject": self.default_project,
            "users": [u.to_public() for u in store.list_users()],
            "invitePath": store.invite_path(),
        })

    def _post_auth_approve(self, url, body, st, actor, project):
        from .auth import accounts_for, require_mutation

        actor = self._actor()
        denied = require_mutation(actor)
        if denied is not None or not actor.is_admin:
            return self._send(
                denied or {"ok": False, "error": "Admin required"}, 403,
            )
        store = accounts_for(self._accounts_cfg())
        result = store.set_role(
            str(body.get("id") or ""),
            role=str(body.get("role") or ""),
            locales=list(body.get("locales") or []),
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_auth_deny(self, url, body, st, actor, project):
        from .auth import accounts_for, require_mutation

        actor = self._actor()
        denied = require_mutation(actor)
        if denied is not None or not actor.is_admin:
            return self._send(
                denied or {"ok": False, "error": "Admin required"}, 403,
            )
        result = accounts_for(self._accounts_cfg()).deny(
            str(body.get("id") or ""),
        )
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_auth_remove(self, url, body, st, actor, project):
        from .auth import accounts_for, require_mutation

        actor = self._actor()
        denied = require_mutation(actor)
        if denied is not None or not actor.is_admin:
            return self._send(
                denied or {"ok": False, "error": "Admin required"}, 403,
            )
        target_id = str(body.get("id") or "")
        if (
            actor.kind == "user"
            and actor.user is not None
            and actor.user.id == target_id
        ):
            return self._send(
                {"ok": False, "error": "cannot remove yourself"}, 400,
            )
        store = accounts_for(self._accounts_cfg())
        before = store.users_path.read_bytes() if store.users_path.exists() else b""
        result = store.remove(target_id)
        if not result.get("ok"):
            after = store.users_path.read_bytes() if store.users_path.exists() else b""
            if after != before:
                return self._send({"ok": False, "error": "file changed on reject"}, 500)
        return self._send(result, 200 if result.get("ok") else 400)

    def _post_auth_smoke_test(self, url, body, st, actor, project):
        from ..ops.guide import run_smoke_test
        from .auth import require_mutation

        actor = self._actor(st.cfg)
        denied = require_mutation(actor)
        if denied is not None or not actor.is_admin:
            return self._send(
                denied or {"ok": False, "error": "Admin required"}, 403,
            )
        if st.cfg.provider.kind not in ("ollama", "null") and not body.get("confirm"):
            return self._send({
                "ok": False,
                "error": f"'{st.cfg.provider.kind}' is a paid provider; "
                         "confirm to send one short test string",
            }, 400)
        model = str(body.get("model") or "").strip() or None
        ok, message = run_smoke_test(st.cfg, model=model)
        return self._send({"ok": ok, "message": message})

    def _post_auth_setup(self, url, body, st, actor, project):
        from .auth import require_mutation

        actor = self._actor(st.cfg)
        denied = require_mutation(actor)
        if denied is not None or not actor.is_admin:
            return self._send(
                denied or {"ok": False, "error": "Admin required"}, 403,
            )
        return self._post_setup(url, body, st, actor, project)
