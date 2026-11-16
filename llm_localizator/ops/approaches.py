"""How a project can be localized: the options shown when someone starts (ADR-123).

One list, read by ``guide`` (CLI and the web setup card), ``init --approach``,
``llm-localizator approach``, the MCP ``list_approaches`` tool and the help files, so a
human or an agent starting on a project sees the same choices and picks one.

The choice is recorded as ``[translate] approach`` and later guide steps adapt to it
(``agent`` skips the model, ``human`` points at export/import, …). Nothing here calls
a model or the network beyond the local Ollama / taskqueue probes the guide already
uses.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..projects import ProjectConfig
from ..projects.config import APPROACH_IDS
from .types import OpResult

__all__ = ["Approach", "APPROACHES", "by_id", "probe", "recommend", "reason_key", "wiring", "op_approach"]

_CLOUD = frozenset({"anthropic", "openai", "deepseek", "deepl"})


@dataclass(frozen=True)
class Approach:
    id: str
    title: str
    words: str          # who produces the translations
    needs: str
    cost: str
    stamp: str          # provenance written to state (ADR-19 / ADR-48)
    when: str           # when to pick it
    commands: tuple[str, ...] = field(default_factory=tuple)


APPROACHES: tuple[Approach, ...] = (
    Approach(
        "local", "Local model, queued",
        words="Ollama models on this machine, run through taskqueue",
        needs="Ollama (a GPU makes it practical), taskqueue",
        cost="free; slow (minutes to hours)",
        stamp="machine",
        when="Private text, no budget, a GPU available.",
        commands=("llm-localizator translate <project>", "tq status"),
    ),
    Approach(
        "cloud", "Cloud model with a spending cap",
        words="Anthropic, OpenAI or DeepL under [budget] monthly_usd (ADR-35)",
        needs="an API key in the environment and a [budget] ceiling",
        cost="paid; fast",
        stamp="machine",
        when="No GPU, many strings, or a deadline; the text may leave the machine.",
        commands=("llm-localizator estimate-cost <project>", "llm-localizator translate <project>"),
    ),
    Approach(
        "agent", "Your coding agent writes them",
        words="the AI agent in your editor fills the catalogues",
        needs="an agent session (Claude Code or similar)",
        cost="the agent's tokens; no model setup here",
        stamp="agent",
        when="Few strings, an agent already working in the repo, no local model.",
        commands=("llm-localizator agent-backlog <project>", "llm-localizator adopt <project>"),
    ),
    Approach(
        "human", "Human translators",
        words="people, through an exported file or the web editor",
        needs="translators; xlsx / xliff / csv round trip or `llm-localizator web`",
        cost="their time",
        stamp="human",
        when="Legal, marketing or brand text, or a language you cannot check.",
        commands=("llm-localizator export <project> --format xlsx", "llm-localizator import <project> <file>"),
    ),
    Approach(
        "hybrid", "Machine draft, human review",
        words="a draft from local, cloud or agent, then reviewers fix what is risky",
        needs="one of the above plus a reviewer",
        cost="mixed",
        stamp="machine/agent, then human",
        when="Languages you ship to users: drafts are fast, review catches one-word errors.",
        commands=("llm-localizator translate <project>", "llm-localizator web"),
    ),
)
assert tuple(a.id for a in APPROACHES) == APPROACH_IDS


def by_id(approach_id: str) -> Approach | None:
    return next((a for a in APPROACHES if a.id == approach_id), None)


def probe(cfg: ProjectConfig | None, *, ollama_up: bool | None = None, skip: bool = False) -> dict:
    """What this machine and config offer. ``skip`` leaves Ollama unprobed (``None``)."""
    if skip:
        ollama_up = None
    elif ollama_up is None:
        from .guide import DEFAULT_OLLAMA_URL, ollama_state

        url = (cfg.provider.url if cfg and cfg.provider.url else "") or DEFAULT_OLLAMA_URL
        ollama_up = ollama_state(url)[0]
    kind = cfg.provider.kind if cfg else "ollama"
    return {
        "ollama": None if ollama_up is None else bool(ollama_up),
        "taskqueue": shutil.which("tq") is not None,
        "provider": kind,
        "cloud_configured": kind in _CLOUD,
        "budget_usd": float(getattr(cfg, "budget_monthly_usd", 0.0) or 0.0) if cfg else 0.0,
    }


def recommend(probes: dict) -> tuple[str, str]:
    """``(approach id, reason)`` from the probes."""
    if probes.get("cloud_configured"):
        if probes.get("budget_usd", 0) > 0:
            return "cloud", "a cloud provider and a monthly budget are configured"
        return "cloud", "a cloud provider is configured; set [budget] monthly_usd before translating"
    if probes.get("ollama"):
        return "local", "Ollama is running here" + ("" if probes.get("taskqueue") else
                                                    "; install taskqueue to queue long runs")
    if probes.get("ollama") is None and probes.get("provider") == "ollama":
        return "local", "the project is set up for a local Ollama model (not probed)"
    return "agent", "no local model answers here; an agent or a cloud provider can do the work"


_REASON_KEYS = (
    ("a cloud provider and a monthly budget", "guide_approach_reason_cloud_budget"),
    ("a cloud provider is configured", "guide_approach_reason_cloud_nobudget"),
    ("Ollama is running here; install taskqueue", "guide_approach_reason_ollama_notq"),
    ("Ollama is running here", "guide_approach_reason_ollama"),
    ("the project is set up for a local Ollama", "guide_approach_reason_ollama_unprobed"),
    ("no local model answers here", "guide_approach_reason_agent"),
)


def reason_key(reason: str) -> str:
    """Catalogue key for a ``recommend`` reason, so the web page can localise it."""
    return next((k for prefix, k in _REASON_KEYS if reason.startswith(prefix)), "")


def wiring(cfg: ProjectConfig | None) -> dict:
    """How strings reach the app: already wired, shipped runtime, or framework i18n."""
    if cfg is None:
        return {"id": "unknown", "detail": "Create the project first."}
    adapter = (cfg.scan_adapter or "").lower()
    fmt = (cfg.catalog_format or "").lower()
    if getattr(cfg, "web_runtime_path", ""):
        return {"id": "runtime", "detail": "Uses the shipped browser runtime "
                "(`llm-localizator runtime check` keeps it current)."}
    if adapter in ("next-intl",) or fmt in ("po", "android-xml", "xliff", "arb", "ios-strings",
                                             "xcstrings", "resx", "yaml"):
        return {"id": "framework", "detail": f"Framework i18n ({adapter or fmt}): keep using it; "
                "llm-localizator only translates the catalogues."}
    if fmt == "json-flat" and adapter in ("raw-js", "source", ""):
        return {"id": "vanilla", "detail": "Plain JS/HTML with flat JSON catalogues: install the "
                "shipped runtime with `[web] runtime_path` and `llm-localizator runtime install`."}
    return {"id": "catalogue", "detail": f"Catalogues in {fmt}: translate them; wiring is the app's."}


def op_approach(
    cfg: ProjectConfig, *, set_to: str | None = None, ollama_up: bool | None = None,
    skip_probe: bool = False,
) -> OpResult:
    """List the options with a recommendation; ``set_to`` records the choice in the config."""
    probes = probe(cfg, ollama_up=ollama_up, skip=skip_probe)
    rec, reason = recommend(probes)
    current = getattr(cfg, "translate_approach", "") or ""
    lines: list[str] = []
    if set_to is not None:
        if set_to not in APPROACH_IDS:
            return OpResult(ok=False, exit_code=2, command="approach",
                            summary=f"unknown approach {set_to!r} ({'|'.join(APPROACH_IDS)})")
        path = getattr(cfg, "config_path", None)
        if not path:
            return OpResult(ok=False, exit_code=2, command="approach",
                            summary="this project has no config file to write")
        _write_approach(Path(path), set_to)
        lines.append(f"recorded [translate] approach = \"{set_to}\" in {path}")
        current = set_to
    for a in APPROACHES:
        mark = "*" if a.id == current else ("+" if a.id == rec else " ")
        lines.append(f"{mark} {a.id:<7} {a.title}: {a.words}. Needs {a.needs}. Cost: {a.cost}.")
        lines.append(f"          Pick it when: {a.when}")
    lines.append(f"Recommended here: {rec} ({reason}).")
    lines.append(f"App wiring: {wiring(cfg)['detail']}")
    summary = (f"approach {current}" if current else
               f"no approach chosen yet; recommended: {rec}")
    return OpResult(
        ok=True, exit_code=0, command="approach", summary=summary, lines=lines,
        data={"approaches": [asdict(a) for a in APPROACHES], "current": current or None,
              "recommended": rec, "reason": reason, "probes": probes, "wiring": wiring(cfg)},
    )


def _write_approach(path: Path, approach_id: str) -> None:
    import tomlkit

    from ..catalog.io import atomic_write_text

    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    if "translate" not in doc:
        doc["translate"] = tomlkit.table()
    doc["translate"]["approach"] = approach_id
    atomic_write_text(path, tomlkit.dumps(doc))
