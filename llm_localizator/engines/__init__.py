"""Engines: one named bundle that sets the provider and model of every pipeline role (ADR-156).

An engine is a TOML file with metadata (``id``, ``name``, ``summary``, ``status``, ``evidence``, ``[requires]``) and a
``[config]`` table shaped like ``.llm-localize.toml``. ``[engine] id = "claude-haiku"`` in a project layers that table
*under* the project's own keys when the config loads: anything the project writes explicitly wins, so per-locale
overrides (a frozen locale kept on a local model) survive an engine switch. ``engine apply`` removes the project keys
that would shadow the engine.

``[config]`` may only set the keys in :data:`ALLOWED`. URLs, model paths, keys, ``[privacy]``, ``[budget]`` and
``[notify]`` stay with the user (ADR-123): a downloaded engine can never turn cloud on, raise a budget or point a
provider at another host.

Built-in engines live in ``engines/builtin/``; engines fetched later (``engine fetch``) go to
``~/.llm_localize/engines/`` and never replace a built-in id.
"""

from __future__ import annotations

import tomllib
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ALLOWED", "STATUSES", "Engine", "EngineError", "all_engines", "get_engine", "parse_engine",
    "layer", "shadowing_keys", "user_engine_dir",
]

STATUSES = ("benchmarked", "waiver", "smoke", "unbenchmarked")

#: ``[config]`` keys an engine may set, as (section path, key).
ALLOWED: frozenset[tuple[tuple[str, ...], str]] = frozenset({
    (("provider",), "kind"),
    (("locales", "models"), "default"),
    (("quality",), "improve_model"),
    (("quality",), "score_model"),
    (("quality",), "score_provider"),
    (("quality",), "judge_model"),
    (("quality",), "documents_model"),
    (("quality",), "threshold"),
    (("translate",), "batch_size"),
    (("translate",), "cloud_batch_size"),
})
_KINDS = frozenset({"ollama", "anthropic", "openai", "deepseek", "deepl", "ctranslate2", "openai_compat"})
_BUILTIN = Path(__file__).resolve().parent / "builtin"


class EngineError(ValueError):
    """An engine file is malformed, unknown, or tries to set a key it may not."""


@dataclass(frozen=True)
class Engine:
    id: str
    name: str
    summary: str
    status: str
    evidence: str
    requires: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    source: str = "builtin"

    @property
    def cloud(self) -> bool:
        return bool(self.requires.get("cloud"))

    @property
    def vram_gib(self) -> float:
        return float(self.requires.get("vram_gib") or 0)

    @property
    def api_key_env(self) -> str:
        return str(self.requires.get("api_key_env") or "")

    def settings(self) -> list[tuple[str, str, object]]:
        """Flat ``(section, key, value)`` rows of what the engine sets, for display."""
        return [(".".join(path), key, value) for path, key, value in _walk(self.config)]

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "summary": self.summary, "status": self.status,
            "evidence": self.evidence, "requires": dict(self.requires), "source": self.source,
            "settings": [{"section": s, "key": k, "value": v} for s, k, v in self.settings()],
        }


def _walk(table: dict, path: tuple[str, ...] = ()):
    for key, value in table.items():
        if isinstance(value, dict):
            yield from _walk(value, (*path, key))
        else:
            yield path, key, value


def parse_engine(text: str, *, source: str = "builtin", expect_id: str | None = None) -> Engine:
    """Parse and validate one engine file."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise EngineError(f"engine {source}: not valid TOML: {exc}") from exc
    engine_id = str(raw.get("id") or "").strip()
    if not engine_id or not all(c.isalnum() or c in "-_." for c in engine_id):
        raise EngineError(f"engine {source}: missing or invalid id {engine_id!r}")
    if expect_id is not None and engine_id != expect_id:
        raise EngineError(f"engine {source}: id {engine_id!r} does not match its file name {expect_id!r}")
    status = str(raw.get("status") or "unbenchmarked")
    if status not in STATUSES:
        raise EngineError(f"engine {engine_id}: status {status!r} is not one of {', '.join(STATUSES)}")
    unknown = set(raw) - {"id", "name", "summary", "status", "evidence", "requires", "config"}
    if unknown:
        raise EngineError(f"engine {engine_id}: unknown field(s) {', '.join(sorted(unknown))}")
    config = raw.get("config") or {}
    if not isinstance(config, dict):
        raise EngineError(f"engine {engine_id}: [config] must be a table")
    for path, key, value in _walk(config):
        if (path, key) not in ALLOWED:
            raise EngineError(
                f"engine {engine_id}: [config.{'.'.join(path)}] {key} is not an engine setting "
                "(engines set providers and models only; privacy, budget, URLs and keys stay with the project)"
            )
        if (path, key) == (("provider",), "kind") and value not in _KINDS:
            raise EngineError(f"engine {engine_id}: provider kind {value!r} is unknown")
    requires = raw.get("requires") or {}
    if not isinstance(requires, dict) or set(requires) - {"cloud", "api_key_env", "vram_gib"}:
        raise EngineError(f"engine {engine_id}: [requires] takes cloud, api_key_env and vram_gib only")
    return Engine(
        id=engine_id, name=str(raw.get("name") or engine_id), summary=str(raw.get("summary") or ""),
        status=status, evidence=str(raw.get("evidence") or ""), requires=dict(requires),
        config=deepcopy(config), source=source,
    )


def user_engine_dir() -> Path:
    from ..projects.registry import registry_home

    return registry_home() / "engines"


def _load_dir(directory: Path, source: str) -> dict[str, Engine]:
    found: dict[str, Engine] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.toml")):
        found[path.stem] = parse_engine(path.read_text(encoding="utf-8"), source=source, expect_id=path.stem)
    return found


def all_engines() -> dict[str, Engine]:
    """Built-in engines plus fetched ones; a fetched file never replaces a built-in id."""
    engines = _load_dir(user_engine_dir(), "fetched")
    engines.update(_load_dir(_BUILTIN, "builtin"))
    return dict(sorted(engines.items()))


def get_engine(engine_id: str) -> Engine:
    engines = all_engines()
    if engine_id not in engines:
        raise EngineError(f"unknown engine {engine_id!r} (known: {', '.join(engines)})")
    return engines[engine_id]


def layer(raw: dict, engine: Engine) -> dict:
    """``raw`` with the engine's ``[config]`` underneath it: the project's explicit keys win."""
    merged = deepcopy(engine.config)

    def merge(base: dict, top: dict) -> dict:
        for key, value in top.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                merge(base[key], value)
            else:
                base[key] = deepcopy(value)
        return base

    return merge(merged, raw)


def shadowing_keys(raw: dict, engine: Engine) -> list[tuple[str, str, object]]:
    """Project keys that would hide the engine's value: ``(section, key, project value)``."""
    rows = []
    for path, key, value in _walk(engine.config):
        table = raw
        for part in path:
            table = table.get(part) if isinstance(table, dict) else None
        if isinstance(table, dict) and key in table and table[key] != value:
            rows.append((".".join(path), key, table[key]))
    return rows
