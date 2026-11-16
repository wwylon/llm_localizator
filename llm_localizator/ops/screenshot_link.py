"""``screenshot-link``: attach screenshots to keys, with optional regions (C-012, ADR-102).

Actions: ``list`` (all links, or those of one key), ``link`` and ``unlink``. Links are advisory
metadata in ``<state>/screenshot_links.json``; the image itself stays under the project's
``screenshots/`` context folder and is served by the authenticated ``/api/screenshot`` route.
"""

from __future__ import annotations

from ..catalog.mutation_lock import project_mutation_lock
from ..catalog.screenshot_links import ScreenshotLinks, normalize_region
from ..projects import ProjectConfig
from ..projects.screenshots import SCREENSHOT_EXTS, resolve_screenshot_path
from .types import OpResult, ScreenshotLinkRequest

__all__ = ["op_screenshot_link", "attach_screenshot"]

ACTIONS = ("list", "link", "unlink")


def _fail(summary: str, code: int = 64) -> OpResult:
    return OpResult(ok=False, exit_code=code, command="screenshot-link", summary=summary, lines=[summary])


def _relative_file(cfg: ProjectConfig, file: str) -> str | None:
    """Image path relative to the context folder, or ``None`` when it is not a usable image."""
    name = (file or "").strip().replace("\\", "/")
    if not name or not name.lower().endswith(SCREENSHOT_EXTS):
        return None
    found = resolve_screenshot_path(cfg.context_dir, image=name)
    if found is None:
        return None
    return found.relative_to(cfg.context_dir.resolve()).as_posix()


def attach_screenshot(
    cfg: ProjectConfig, file: str, namespace: str, key: str,
    region: object = None, note: str = "", by: str = "",
) -> dict | None:
    """Link ``file`` to a key; ``None`` when the image or key is unusable. Caller holds the lock."""
    rel = _relative_file(cfg, file)
    if rel is None or not (namespace and key):
        return None
    return ScreenshotLinks(cfg.state_root()).add(rel, namespace, key, normalize_region(region), note, by)


def op_screenshot_link(cfg: ProjectConfig, req: ScreenshotLinkRequest) -> OpResult:
    action = req.action or "list"
    if action not in ACTIONS:
        return _fail(f"unknown screenshot-link action {action!r}")
    store = ScreenshotLinks(cfg.state_root())
    if action == "list":
        rows = store.for_key(req.namespace, req.key) if req.namespace and req.key else store.all()
        lines = [
            f"{r['id']}  {r['namespace']}.{r['key']}  {r['file']}" + ("  region" if r.get("region") else "")
            for r in rows
        ]
        return OpResult(
            ok=True, exit_code=0, command="screenshot-link", summary=f"{len(rows)} link(s)",
            lines=lines, data={"links": rows},
        )
    if action == "unlink":
        if not req.link:
            return _fail("unlink needs a link id")
        with project_mutation_lock(cfg):
            gone = store.remove(req.link)
        if not gone:
            return _fail(f"no link {req.link!r}", 1)
        return OpResult(ok=True, exit_code=0, command="screenshot-link", summary=f"removed {req.link}",
                        lines=[f"removed {req.link}"], data={"removed": req.link})
    if not (req.namespace and req.key):
        return _fail("link needs a namespace and a key")
    if cfg.context_dir is None:
        return _fail("the project has no context_dir, so there is no screenshots folder")
    try:
        with project_mutation_lock(cfg):
            entry = attach_screenshot(cfg, req.file, req.namespace, req.key, req.region, req.note, req.by)
    except ValueError as exc:
        return _fail(str(exc))
    if entry is None:
        return _fail(f"{req.file!r} is not an existing png, jpg or webp under the context folder", 1)
    return OpResult(
        ok=True, exit_code=0, command="screenshot-link", summary=f"linked {entry['file']} to {req.namespace}.{req.key}",
        lines=[entry["id"]], data={"link": entry},
    )
