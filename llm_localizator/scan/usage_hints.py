"""Read scan usage artefacts back as per-key "where is this used" hints (C-008).

``llm-localizator scan`` writes ``<scan_out_dir>/<namespace>.json`` as
``{key: [{file, line, component}]}``. The hint is advisory text for the
translator and the prompt; it never enters the state-key hash or the context
fingerprint (ADR-7), and the artefact may be stale (ADR-85).
"""

from __future__ import annotations

import json
from pathlib import Path

MAX_SITES = 3


def load_usage_hints(out_dir: Path | None, namespace: str) -> dict[str, str]:
    """Return ``{key: "used in A, B"}`` for one namespace; empty when absent."""
    if not out_dir or not namespace:
        return {}
    path = Path(out_dir) / f"{namespace}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    hints: dict[str, str] = {}
    for key, sites in data.items():
        if not isinstance(sites, list):
            continue
        names: list[str] = []
        for site in sites:
            if not isinstance(site, dict):
                continue
            name = str(site.get("component") or "").strip()
            if not name:
                name = Path(str(site.get("file") or "")).stem
            if name and name not in names:
                names.append(name)
        if names:
            hints[str(key)] = "used in " + ", ".join(names[:MAX_SITES])
    return hints
