"""Documented HTTP API paths for the review server.

``API_ROUTES`` is the source of truth for ``/api-docs``. A hermetic test
fails when ``server.py`` handles an ``/api/`` path that is not listed here,
or the reverse for exact paths.
"""

from __future__ import annotations

# (method, path, one-line purpose). Path templates use {name}.
API_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("GET", "/api/projects", "List registered projects"),
    ("GET", "/api/ui-locales", "UI locale dictionary codes"),
    ("GET", "/api/overview", "Coverage stats and locale cards"),
    ("GET", "/api/overview-lite", "Fast namespaces and scale hints"),
    ("GET", "/api/overview-stats", "Per-locale coverage (async)"),
    ("GET", "/api/dashboard", "Dashboard aggregate: overview-lite, stats and review badge in one call"),
    ("GET", "/api/bootstrap-token", "Startup token for the same-origin shell (loopback only)"),
    ("GET", "/api/collections", "Document collections"),
    ("GET", "/api/collection-files", "Files in a collection"),
    ("GET", "/api/collection-file", "Read a collection file (sections + preview)"),
    ("POST", "/api/collection-file", "Write a collection file or one section"),
    ("GET", "/api/models", "Provider model tags"),
    ("GET", "/api/messages", "Paged message rows"),
    ("GET", "/api/messages/row", "One key with detail"),
    ("GET", "/api/findings", "Validation findings"),
    ("GET", "/api/export", "Export catalogue slice"),
    ("POST", "/api/export", "Export with posted filter"),
    ("GET", "/api/screenshot", "Screenshot for a key"),
    ("GET", "/api/commands", "Ops command manifest"),
    ("GET", "/api/version", "Package version and UI digest"),
    ("GET", "/api/history", "History events for a key"),
    ("GET", "/api/tm/concordance", "TM concordance search"),
    ("GET", "/api/tm/leverage", "TM leverage counts"),
    ("GET", "/api/tm/browse", "Browse TM rows"),
    ("GET", "/api/tm/export", "Export TM"),
    ("GET", "/api/report-parts", "List agent report parts"),
    ("GET", "/api/report-part", "Download one agent report part"),
    ("POST", "/api/tm/import", "Import TMX/JSONL"),
    ("GET", "/api/glossary", "Glossary domain file"),
    ("POST", "/api/glossary", "Save glossary domain file"),
    ("GET", "/api/bundle", "OTA translation bundle"),
    ("GET", "/api/auth/me", "Current session user"),
    ("POST", "/api/auth/register", "Register a local account"),
    ("POST", "/api/auth/login", "Log in"),
    ("POST", "/api/auth/logout", "Log out"),
    ("POST", "/api/auth/users", "List local accounts"),
    ("POST", "/api/auth/users/approve", "Approve a pending user"),
    ("POST", "/api/auth/users/deny", "Deny a pending user"),
    ("POST", "/api/auth/users/remove", "Remove a user"),
    ("POST", "/api/setup", "First-admin setup"),
    ("GET", "/api/setup-state", "Current values that prefill the setup wizard"),
    ("POST", "/api/setup/smoke-test", "Send one short string to the chosen model (Admin)"),
    ("GET", "/api/locales", "Languages the tool has profiles for"),
    ("GET", "/api/settings", "Project settings view"),
    ("POST", "/api/settings", "Save project settings"),
    ("GET", "/api/project-config", "Prompt and glossary config"),
    ("POST", "/api/project-config", "Save project config"),
    ("GET", "/api/model-eval", "Bakeoff report list"),
    ("POST", "/api/model-eval/run", "Enqueue bakeoff via tq"),
    ("POST", "/api/model-eval/apply", "Append apply-notes"),
    ("GET", "/api/workflow", "Named workflow thresholds"),
    ("GET", "/api/workflow/run", "Read a workflow run"),
    ("GET", "/api/workflow/summary", "Workflow applying to each locale + last run"),
    ("POST", "/api/workflow", "Save or run a workflow"),
    ("POST", "/api/workflow/copy", "Copy a workflow into another project"),
    ("POST", "/api/workflow/cancel", "Cancel a waiting workflow run"),
    ("POST", "/api/workflow/resume", "Advance a waiting workflow run"),
    ("GET", "/api/branches", "Tracked branch list"),
    ("GET", "/api/branches/sync", "Sync branch from git status"),
    ("GET", "/api/branches/merge-preview", "Merge conflict preview"),
    ("POST", "/api/branches/track", "Track a git branch"),
    ("POST", "/api/branches/active", "Set active branch state dir"),
    ("POST", "/api/branches/merge", "Merge with explicit picks"),
    ("GET", "/api/branches/diff", "Downloadable branch diff"),
    ("POST", "/api/branches/archive", "Archive a tracked branch"),
    ("POST", "/api/branches/unarchive", "Unarchive a tracked branch"),
    ("POST", "/api/branches/delete", "Forget a branch and its state (confirm)"),
    ("POST", "/api/branches/fetch", "git fetch (network, explicit)"),
    ("GET", "/api/usage", "Stored usage and cost; period=month|last_month|90d|all"),
    ("GET", "/api/usage/export", "Ledger events as CSV for a period"),
    ("GET", "/api/progress", "Progress and ETA"),
    ("GET", "/api/translator-activity", "Per-translator edit activity"),
    ("GET", "/api/metrics", "Edit rate, cycle time and coverage trend; by=user|locale|locale+user with format=csv for the activity report (Admin/Supervisor)"),
    ("GET", "/api/status", "Coverage summary; group_by=screen groups by screen"),
    ("GET", "/api/scan/status", "Hardcoded-string scan cache: age, counts, stale flag"),
    ("GET", "/api/scan/hits", "Hits of the stored hardcoded-string scan with decision ids and status (no scan)"),
    ("GET", "/api/queue", "Blueprint tasks with taskqueue status, engine, model, VRAM and lane (read-only)"),
    ("GET", "/api/analysis", "Pre-run TM analysis"),
    ("GET", "/api/analysis/report", "Pre-translation report: due strings, TM bands, effort, cost"),
    ("GET", "/api/review/tickets", "Review tickets"),
    ("GET", "/api/review/counts", "Review ticket counts (nav badge)"),
    ("POST", "/api/review/tickets", "Open a review ticket"),
    ("POST", "/api/review/tickets/{id}/comment", "Comment on a ticket"),
    ("POST", "/api/review/tickets/{id}/status", "Change ticket status"),
    ("GET", "/api/translator-lookup", "Overlay key lookup"),
    ("GET", "/api/translator-bundle", "Overlay translation bundle"),
    ("GET", "/api/translator-config", "Overlay config"),
    ("POST", "/api/save", "Save a translation"),
    ("POST", "/api/flag", "Flag a key"),
    ("POST", "/api/verify", "Mark verified"),
    ("POST", "/api/context", "Save context note"),
    ("POST", "/api/mark-example", "Mark few-shot example"),
    ("POST", "/api/mark-intentional", "Keep source as-is"),
    ("POST", "/api/add-locale", "Add a target locale"),
    ("POST", "/api/remove-locale", "Remove a target locale"),
    ("GET", "/api/provider-status", "Probe configured LLM providers"),
    ("POST", "/api/web-token", "Regenerate session token"),
    ("POST", "/api/import", "Import translations"),
    ("POST", "/api/push-strings", "Push source strings"),
    ("POST", "/api/preview", "Preview ICU/markdown/HTML with sample values"),
    ("POST", "/api/validate-key", "Live QA for one key"),
    ("POST", "/api/screenshot-upload", "Attach a screenshot"),
    ("POST", "/api/translate-enabled", "Toggle translate for a key"),
    ("POST", "/api/lock", "Lock or unlock a key"),
    ("POST", "/api/revert", "Revert to a history value"),
    ("POST", "/api/retranslate", "Retranslate selected keys"),
    ("POST", "/api/reload", "Reload project from disk"),
    ("POST", "/api/save-ui-locale", "Save a UI chrome string"),
    ("POST", "/api/resolve", "Overlay resolve candidates"),
    ("POST", "/api/ops/{command}", "Run an ops command"),
)

API_PATHS: frozenset[str] = frozenset(path for _, path, _ in API_ROUTES)

# Exact paths the server compares with ``url.path == …`` (no templates).
API_EXACT_PATHS: frozenset[str] = frozenset(
    path for path in API_PATHS if "{" not in path
)

# Sidebar / quick-reference grouping. First matching prefix wins; anything
# unmatched lands in "Other", so a new route never needs a table edit here.
API_GROUP_ORDER: tuple[str, ...] = (
    "Authentication", "Projects", "Strings", "Translation", "Export / Import",
    "Translation memory", "Glossary and config", "Workflows and branches",
    "Reporting", "Review", "Overlay", "OTA delivery", "Other",
)
_GROUP_PREFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Authentication", ("/api/auth/", "/api/setup", "/api/web-token")),
    ("OTA delivery", ("/api/bundle",)),
    ("Export / Import", ("/api/export", "/api/import", "/api/push-strings")),
    ("Translation memory", ("/api/tm/",)),
    ("Glossary and config", ("/api/glossary", "/api/project-config", "/api/settings")),
    ("Workflows and branches", ("/api/workflow", "/api/branches")),
    ("Reporting", ("/api/usage", "/api/progress", "/api/metrics", "/api/status",
                   "/api/scan/", "/api/analysis", "/api/translator-activity",
                   "/api/overview")),
    ("Review", ("/api/review/",)),
    ("Overlay", ("/api/translator-", "/api/resolve")),
    ("Translation", ("/api/ops/", "/api/retranslate", "/api/model", "/api/provider-status",
                     "/api/translate-enabled", "/api/commands")),
    ("Strings", ("/api/messages", "/api/save", "/api/flag", "/api/verify", "/api/context",
                 "/api/mark-", "/api/history", "/api/findings", "/api/lock", "/api/revert",
                 "/api/preview", "/api/validate-key", "/api/screenshot",
                 "/api/collection")),
    ("Projects", ("/api/projects", "/api/locales", "/api/add-locale", "/api/remove-locale",
                  "/api/reload", "/api/ui-locales", "/api/save-ui-locale", "/api/version")),
)


def api_group(path: str) -> str:
    """Group name for ``path`` (first prefix match, else ``Other``)."""
    for group, prefixes in _GROUP_PREFIXES:
        if path.startswith(prefixes):
            return group
    return "Other"


def api_anchor(method: str, path: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in path.strip("/")).strip("-")
    return f"{method.lower()}-{slug}"


# Worked examples for the endpoints integrators call most. Samples are
# abbreviated to fields the handlers really read or return.
API_DETAILS: dict[tuple[str, str], dict] = {
    ("GET", "/api/messages"): {
        "params": (
            ("project", "Project name (default: the server's default project)"),
            ("locales", "Comma-separated target locales: de,pl"),
            ("namespace", "__all__ or one namespace"),
            ("only", "Status filter: all, missing, stale, …"),
            ("q", "Text search"),
            ("limit", "Page size. Default 100"),
            ("offset", "Pagination offset"),
            ("sort / dir", "Sort column and asc|desc"),
            ("include", "findings to attach validation findings"),
        ),
        "request": "GET /api/messages?project=bridge&locales=de,pl&only=missing&limit=50",
        "response": '{\n  "locales": ["de", "pl"],\n  "namespace": "__all__",\n'
                    '  "rows": [ … ],\n'
                    '  "counts": { "total": 608, "offset": 0, "limit": 50 },\n'
                    '  "qualityThreshold": 0.8\n}',
    },
    ("POST", "/api/save"): {
        "request": '{\n  "project": "bridge",\n  "locale": "de",\n  "namespace": "common",\n'
                   '  "key": "save",\n  "value": "Änderungen speichern",\n'
                   '  "provider": "agent",   // optional\n  "model": "…"           // optional\n}',
        "response": '// Success\n{ "ok": true, … }\n\n// Rejected by validation\n{ "ok": false, "error": "…" }',
        "note": "Runs the same validation rules as the editor. Provider "
                "<code>agent</code> keeps agent edits distinguishable from human edits "
                "in history (ADR-19).",
    },
    ("POST", "/api/push-strings"): {
        "request": '{\n  "project": "bridge",\n  "namespace": "onboarding",\n'
                   '  "strings": {\n    "step1.title": "Welcome aboard!",\n'
                   '    "step2.title": "Connect your repo"\n  },\n  "dry_run": false\n}',
        "response": '{\n  "ok": true,\n  "added": 2,\n  "updated": 0,\n'
                    '  "skipped": 0,\n  "stale_marked": 0\n}',
        "note": "New strings are written into the source catalogue; changed values "
                "mark existing translations stale. Needs a token. Use from CI after "
                "extracting strings.",
    },
    ("GET", "/api/bundle"): {
        "params": (
            ("project", "Project name"),
            ("locale", "One locale (required): de"),
            ("namespace", "Optional namespace filter"),
        ),
        "request": "const res = await fetch(\n  'http://127.0.0.1:8770/api/bundle?project=bridge&locale=de',\n"
                   "  { headers: { 'If-None-Match': etag } }\n);\nif (res.status === 304) return; // cached\n"
                   "const { messages, etag } = await res.json();",
        "response": '{\n  "ok": true,\n  "locale": "de",\n  "etag": "a3f9e1b2…",\n'
                    '  "generated_at": "2026-10-19T08:00:00Z",\n'
                    '  "messages": { "common": { "save": "Änderungen speichern" } }\n}',
        "note": "Read-only and CORS-checked against allowed origins. Send "
                "<code>If-None-Match</code> with the ETag for a 304 instead of the full bundle.",
    },
    ("POST", "/api/ops/{command}"): {
        "request": "POST /api/ops/translate\n"
                   '{ "project": "bridge", "locales": ["de", "pl"], "dry_run": false }',
        "response": "// Same result shape as the CLI command (see docs/cli.md)",
        "note": "Any command listed by the commands endpoint runs through the same "
                "operation layer as the CLI.",
    },
}
