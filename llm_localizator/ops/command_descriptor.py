"""Typed command surface (Deep health Wave 3).

One descriptor per operator command. Drift tests keep path keys, submit,
stream, and read-only sets in sync with this table so those lists are not
hand-maintained three times over.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CommandDescriptor",
    "COMMANDS",
    "by_name",
    "read_only_ops",
    "submit_ops",
    "streamable_ops",
]


@dataclass(frozen=True)
class CommandDescriptor:
    name: str
    group: str
    read_only: bool = False
    llm: bool = False
    stream: bool = False
    submit: bool = False
    web_only: bool = False
    path_keys: tuple[str, ...] = ()
    locale_keys: tuple[str, ...] = ("locales", "locale")


COMMANDS: tuple[CommandDescriptor, ...] = (
    CommandDescriptor("status", "inspect", read_only=True),
    CommandDescriptor("validate", "inspect", read_only=True),
    CommandDescriptor("export", "export", read_only=True),
    CommandDescriptor("import", "export"),
    CommandDescriptor("translate", "translate", llm=True, stream=True, submit=True),
    CommandDescriptor("improve", "translate", llm=True, stream=True, submit=True),
    CommandDescriptor("review", "review", llm=True, stream=True, submit=True),
    CommandDescriptor("rescore", "translate", llm=True, stream=True, submit=True),
    CommandDescriptor("documents", "translate", llm=True, stream=True, submit=True, path_keys=("doc_dir",)),
    CommandDescriptor("verify", "inspect", read_only=True, path_keys=("path", "out", "resume")),
    CommandDescriptor("guide", "inspect", read_only=True, path_keys=("directory",)),
    CommandDescriptor("bakeoff", "admin", llm=True, stream=True, submit=True, path_keys=("out", "corpus")),
    CommandDescriptor("scan-decide", "review", web_only=True),
    # list/show/recommend read; apply writes [engine] id (Admin, like other config writes) (ADR-156).
    CommandDescriptor("engine", "admin"),
    # Rewrites existing blueprints only (W3); Admin like init --taskqueue.
    CommandDescriptor("queue-engine", "admin"),
    # Lists the options; set_to writes [translate] approach (Admin, the dashboard getting-started button) (W6).
    CommandDescriptor("approach", "admin"),
    # Ops previously only in allowlists / hand sets — keep path_keys aligned.
    CommandDescriptor("estimate-cost", "inspect", read_only=True),
    CommandDescriptor("agent-backlog", "inspect", path_keys=("out_dir",)),  # writes report parts (M3)
    CommandDescriptor("agent-hardcoded", "inspect", read_only=True, submit=True, path_keys=("out_dir",)),
    CommandDescriptor("term-report", "inspect", read_only=True),
    CommandDescriptor("release-diff", "inspect", read_only=True),
    CommandDescriptor("concordance", "inspect", read_only=True),
    CommandDescriptor("analytics", "inspect", read_only=True),
    CommandDescriptor("metrics", "inspect", read_only=True),
    CommandDescriptor("hard-keys", "inspect", read_only=True),
    CommandDescriptor("explain-scan", "inspect", read_only=True),
    CommandDescriptor("doctor", "inspect", read_only=True),
    CommandDescriptor("tm-export", "export", path_keys=("path", "out")),  # may write a file (M3)
    CommandDescriptor("tm-import", "export", path_keys=("path", "file")),
    CommandDescriptor("glossary-export", "export", path_keys=("file", "out")),  # may write a file (M3)
    CommandDescriptor("glossary-import", "export", path_keys=("file",)),
    CommandDescriptor("glossary-propose", "export", path_keys=("out",)),
    CommandDescriptor("impact", "inspect", read_only=True),
    CommandDescriptor("scan", "inspect", read_only=True, path_keys=("out_dir",)),
    CommandDescriptor("discover", "inspect", read_only=True),
    CommandDescriptor("source-review-queue", "inspect", read_only=True),
    CommandDescriptor("suggest", "inspect", read_only=True),
    CommandDescriptor("org", "inspect", read_only=True),
    CommandDescriptor("source-diff", "inspect", read_only=True),
    CommandDescriptor("patch", "review", path_keys=("out_dir",)),
    CommandDescriptor("ingest-visual", "review", path_keys=("file", "path")),
)


def by_name() -> dict[str, CommandDescriptor]:
    return {c.name: c for c in COMMANDS}


def _underscore(name: str) -> str:
    return name.replace("-", "_")


def read_only_ops() -> frozenset[str]:
    """Dispatch names (underscore form) that never write."""
    return frozenset(_underscore(c.name) for c in COMMANDS if c.read_only)


def submit_ops() -> frozenset[str]:
    """CLI/web names that may set ``body['submit']`` (hyphen form)."""
    return frozenset(c.name for c in COMMANDS if c.submit)


def streamable_ops() -> frozenset[str]:
    """Dispatch stream ids: base underscore names plus ``run_*`` aliases."""
    out: set[str] = set()
    for c in COMMANDS:
        if not c.stream:
            continue
        base = _underscore(c.name)
        out.add(base)
        out.add(f"run_{base}")
    return frozenset(out)
