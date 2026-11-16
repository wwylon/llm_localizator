"""Resolve optional screenshot files under a project's context directory."""

from __future__ import annotations

from pathlib import Path

from .paths import is_under_root

__all__ = ["resolve_screenshot_path", "SCREENSHOT_EXTS"]

SCREENSHOT_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def resolve_screenshot_path(
    context_dir: Path | None,
    *,
    screen: str | None = None,
    image: str | None = None,
    locale: str | None = None,
) -> Path | None:
    """Return an existing image file, or ``None``.

    ``screen`` is the logical UI screen id (groups keys for translation).
    ``image`` is an explicit path relative to ``context_dir`` (from context JSON).
    ``locale`` opts into ``screenshots/{locale}__{screen}.ext`` before the
    generic ``screenshots/{screen}.ext`` (multi-locale browse capture).

    When only ``screen`` is set, looks under ``screenshots/<screen>.<ext>``.
    """
    if not context_dir:
        return None
    root = Path(context_dir).resolve()
    candidates: list[Path] = []
    if image and image.strip():
        raw_image = image.strip().replace("\\", "/")
        if not raw_image.startswith("/") and ".." not in Path(raw_image).parts:
            candidates.append(root / raw_image)
    if screen and screen.strip():
        sid = screen.strip()
        if locale and str(locale).strip():
            loc = str(locale).strip()
            for ext in SCREENSHOT_EXTS:
                candidates.append(root / "screenshots" / f"{loc}__{sid}{ext}")
        for ext in SCREENSHOT_EXTS:
            candidates.append(root / "screenshots" / f"{sid}{ext}")
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not is_under_root(resolved, root):
            continue
        if resolved.is_file():
            return resolved
    return None
