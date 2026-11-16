"""``llm-localizator projects`` — manage the machine-level project registry.

Only the registry is edited; a project's config, catalogues and state are never touched.
"""

from __future__ import annotations

import argparse
import json

from ..projects import ConfigError
from ..projects.registry import (
    list_projects, prune_projects, rename_project, unregister_project,
)

__all__ = ["run"]


def run(args: argparse.Namespace) -> int:
    names = list(args.names)
    try:
        if args.action == "remove":
            if len(names) != 1:
                raise ConfigError("usage: projects remove NAME")
            unregister_project(names[0])
            msg = f"unregistered {names[0]} (project files untouched)"
        elif args.action == "rename":
            if len(names) != 2:
                raise ConfigError("usage: projects rename OLD NEW")
            rename_project(*names)
            msg = f"renamed {names[0]} -> {names[1]}"
        elif args.action == "prune":
            gone = prune_projects()
            msg = f"pruned {len(gone)} missing project(s)" + (": " + ", ".join(gone) if gone else "")
        else:
            rows = list_projects()
            if args.fmt == "json":
                print(json.dumps(rows, indent=2))
            else:
                for r in rows:
                    print(f"{r['name']:<24} {r['root']}" + ("" if r["exists"] else "   [config missing]"))
                if not rows:
                    print("no projects registered")
            return 0
    except ConfigError as exc:
        print(f"error: {exc}")
        return 1
    print(msg)
    return 0
