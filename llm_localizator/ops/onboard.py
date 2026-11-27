"""``llm-localizator onboard``: one command from a bare app to a project ready to translate (P5).

It wraps the steps that already exist, so a new consumer does not need hand-written
TOML or a hunt through the docs:
1. ``init`` when there is no config (layout detection, targets, approach), or the
   existing config;
2. frozen layout locales, the approach (ADR-123) and ``[web] runtime_path``
   recorded in ``.llm-localize.toml``;
3. the shipped runtime installed only with ``install_runtime``, since it writes a
   file into the app;
4. taskqueue registration checked. ``~/.taskqueue/projects.yaml`` is never
   edited; onboard prints the exact entry instead;
5. the next commands: ``guide``, ``check-keys``, ``glossary-propose`` and ``cycle``.
"""

from __future__ import annotations

from pathlib import Path

from .types import InitRequest, OpResult

__all__ = ["op_onboard"]


def _set_toml(path: Path, table: str, key: str, value) -> None:
    import tomlkit

    from ..catalog.io import atomic_write_text

    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    if table not in doc:
        doc[table] = tomlkit.table()
    doc[table][key] = value
    atomic_write_text(path, tomlkit.dumps(doc))


def _tq_knows(name: str) -> bool | None:
    """Whether ``~/.taskqueue/projects.yaml`` lists the project; None when unknown."""
    try:
        import yaml

        data = yaml.safe_load((Path.home() / ".taskqueue" / "projects.yaml").read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return None
    if isinstance(data, dict):
        projects = data.get("projects", data)
        return isinstance(projects, dict) and name in projects
    return None


def op_onboard(
    directory: str | None = None, *, targets: list[str] | None = None, frozen: list[str] | None = None,
    approach: str | None = None, runtime_path: str | None = None, install_runtime: bool = False,
    no_register: bool = False,
) -> OpResult:
    from ..projects import load_config
    from ..projects.config import CONFIG_FILENAME
    from ..projects.taskqueue import tq_available
    from .approaches import _write_approach, op_approach
    from .init import op_init

    root = Path(directory or Path.cwd()).resolve()
    path = root / CONFIG_FILENAME
    lines: list[str] = []
    if not path.exists():
        res = op_init(InitRequest(directory=str(root), targets=(targets or []) + (frozen or []) or None,
                                  approach=approach, no_register=no_register))
        lines += res.lines
        if not res.ok:
            return OpResult(ok=False, exit_code=res.exit_code, command="onboard",
                            summary=res.summary, lines=lines)
    elif approach:
        _write_approach(path, approach)
        lines.append(f"approach: {approach}")
    if frozen:
        cfg = load_config(path)
        _set_toml(path, "locales", "targets", list(dict.fromkeys([*cfg.targets, *frozen])))
        _set_toml(path, "locales", "frozen", list(dict.fromkeys(frozen)))
        lines.append(f"frozen layout locales: {', '.join(frozen)}")
    if runtime_path:
        _set_toml(path, "web", "runtime_path", runtime_path)
        lines.append(f"[web] runtime_path = {runtime_path!r}")
    cfg = load_config(path)
    if install_runtime and cfg.web_runtime_path:
        from .web_runtime import op_runtime

        lines.append(op_runtime(cfg, "install").summary)
    choice = op_approach(cfg, skip_probe=True)
    if not cfg.translate_approach:
        lines.append(f"approach not chosen yet: recommended {choice.data['recommended']} "
                     f"({choice.data['reason']}); run `llm-localizator approach {cfg.name} --set <id>`")
    lines.append(f"app wiring: {choice.data['wiring']['detail']}")
    if tq_available():
        known = _tq_knows(cfg.name)
        if known is False:
            lines.append(f"taskqueue does not know {cfg.name!r}; add to ~/.taskqueue/projects.yaml:\n"
                         f"  {cfg.name}:\n    root: {cfg.root}\n    queue_dir: experiments/operator_queue\n"
                         "then `tq restart` when idle, and `llm-localizator init --taskqueue` for blueprints.")
        elif known:
            lines.append(f"taskqueue knows {cfg.name!r}")
    lines += ["", "Next:",
              f"  llm-localizator guide {cfg.name}",
              f"  llm-localizator check-keys {cfg.name}",
              f"  llm-localizator glossary-propose {cfg.name}   # confirm product terms before translating",
              f"  llm-localizator translate {cfg.name} --sample layout   # small layout-check set (zh/ar frozen)",
              f"  llm-localizator cycle {cfg.name}",
              f"  llm-localizator skill install {cfg.name}   # optional: the agent guide as a Claude skill "
              "in this repo (writes .claude/skills/)",
              "",
              "Guides: `llm-localizator help human` (you), `llm-localizator help agent` (your coding agent)."]
    return OpResult(ok=True, exit_code=0, command="onboard", summary=f"{cfg.name} onboarded at {root}",
                    lines=lines, data={"project": cfg.name, "config": str(path),
                                       "approach": cfg.translate_approach or None})
