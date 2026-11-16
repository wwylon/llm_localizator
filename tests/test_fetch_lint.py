"""Static gate: page scripts should prefer LLMApi over raw fetch (Wave F).

Raw ``fetch(`` is still allowed in ``api.js`` (the client) and a short allowlist
of bootstrap/shell modules. New page code should use ``LLMApi.apiGet/apiPost``.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "llm_localizator" / "web" / "static"

# Modules that own transport or must run before LLMApi is defined.
_ALLOW_RAW_FETCH = frozenset({
    "api.js",
    "shell.js",
    "request-health.js",
    "ops.js",  # legacy ops drawer; prefer operations.js + LLMApi going forward
})


def test_page_scripts_limit_raw_fetch() -> None:
    offenders: list[str] = []
    for path in sorted(ROOT.glob("*.js")):
        if path.name in _ALLOW_RAW_FETCH:
            continue
        text = path.read_text(encoding="utf-8")
        # Count fetch( that are not commented; crude but catches new call sites.
        n = text.count("fetch(")
        # Migration leftovers are OK while pages move onto LLMApi; flag when a
        # page still has a large raw-fetch surface (editor is the known heavy
        # holdout — Wave B1 continues there).
        limit = 20 if path.name == "editor.js" else 12
        if n > limit:
            offenders.append(f"{path.name}: {n} fetch(")
    assert not offenders, "route high-fetch pages through LLMApi:\n" + "\n".join(offenders)


def test_api_js_exports_core_helpers() -> None:
    text = (ROOT / "api.js").read_text(encoding="utf-8")
    for name in ("apiGet", "apiPost", "apiBlob", "apiStream", "requestScope", "authHeaders"):
        assert name in text
