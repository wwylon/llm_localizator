"""Cloud pre-flight for improve, review and rescore (ADR-35).

``translate`` has its own gate (``ops.translate._cloud_block``). These three
ops call the project provider for every existing translation, so a paid
provider needs the same rule: ``on_request`` sends only a named key list,
``dynamic`` sends when the ceiling fits the remaining budget. The worker path
keeps metering each call; this is the submit-time check only.

When ``take_hold`` is true (inline runs), a successful gate reserves the
quoted ceiling; the caller must ``release_cloud_hold`` in ``finally``.
Enqueue paths should pass ``take_hold=False`` so the worker reserves later.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from ..catalog import build_catalog
from ..catalog.budget import BudgetStore
from ..catalog.cloud_cost import CLOUD_KINDS, paying_cloud_kind, quote_locale
from ..catalog.pricing import PricingError
from ..catalog.state import state_key
from ..projects import ProjectConfig
from .types import OpResult

__all__ = ["cloud_gate", "cloud_session", "paying_locales", "release_cloud_hold"]


def paying_locales(cfg: ProjectConfig, locales: list[str]) -> list[str]:
    """Locales whose calls would spend: locale provider or project default."""
    default_kind = (cfg.provider.kind or "").strip().lower()
    default_pays = (
        default_kind in CLOUD_KINDS
        and bool(getattr(cfg, "allow_cloud", False))
        and float(getattr(cfg, "budget_monthly_usd", 0) or 0) > 0
    )
    return [
        loc for loc in locales
        if paying_cloud_kind(cfg, loc) or default_pays
    ]


def release_cloud_hold(cfg: ProjectConfig, hold_id: str | None) -> None:
    """Drop a budget reservation taken by :func:`cloud_gate`."""
    if not hold_id:
        return
    BudgetStore(cfg.budget_root()).release(hold_id)


@contextmanager
def cloud_session(
    cfg: ProjectConfig,
    command: str,
    *,
    locales: list[str] | None,
    namespaces: list[str] | None = None,
    keys: list[str] | None = None,
    batch_size: int = 5,
    take_hold: bool = True,
    texts_by_locale: dict[str, list[str]] | None = None,
    skip: bool = False,
) -> Iterator[OpResult | None]:
    """Run ``cloud_gate`` and always release the hold.

    Yields a refuse :class:`OpResult` when the run must stop, or ``None`` when
    it may proceed. Pass ``skip=True`` for dry-runs that must not reserve.
    """
    if skip:
        yield None
        return
    blocked, hold_id = cloud_gate(
        cfg, command, locales=locales, namespaces=namespaces, keys=keys,
        batch_size=batch_size, take_hold=take_hold, texts_by_locale=texts_by_locale,
    )
    try:
        yield blocked
    finally:
        release_cloud_hold(cfg, hold_id)


def _existing_texts(
    cfg: ProjectConfig, locale: str, namespaces: list[str] | None,
    keys: list[str] | None,
) -> list[str]:
    catalog = build_catalog(
        cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
    )
    wanted = set(keys) if keys else None
    out: list[str] = []
    for ns in namespaces or cfg.namespaces_for(catalog):
        source = catalog.load(cfg.source_locale, ns)
        target = catalog.load(locale, ns)
        for key, src in source.items():
            text = target.get(key)
            if not text or cfg.is_skipped(ns, key, src):
                continue
            if wanted is not None and key not in wanted and state_key(ns, key) not in wanted:
                continue
            out.extend([src, text])  # the prompt carries both
    return out


def cloud_gate(
    cfg: ProjectConfig,
    command: str,
    *,
    locales: list[str] | None,
    namespaces: list[str] | None = None,
    keys: list[str] | None = None,
    batch_size: int = 5,
    take_hold: bool = True,
    texts_by_locale: dict[str, list[str]] | None = None,
) -> tuple[OpResult | None, str | None]:
    """Return ``(refuse, hold_id)``. ``refuse`` is set when the run must stop.

    On allow, ``hold_id`` is a reservation when ``take_hold`` and the quote is
    positive; release it with :func:`release_cloud_hold`.

    Pass ``texts_by_locale`` for document (or other non-catalogue) runs so the
    quote uses real section text instead of looking up catalogue keys.
    """
    targets = list(locales) if locales else list(cfg.active_targets())
    paying = paying_locales(cfg, targets)
    if not paying:
        return None, None

    def refuse(summary: str, data: dict | None = None) -> tuple[OpResult, None]:
        return OpResult(
            ok=False, exit_code=1, command=command,
            summary=summary, lines=[summary], data=data or {},
        ), None

    mode = getattr(cfg, "budget_mode", "on_request") or "on_request"
    if mode == "on_request" and not keys and texts_by_locale is None:
        return refuse(
            f"cloud mode is on_request: {command} needs a named key list "
            '(--keys namespace.key,...) or set [budget] mode = "dynamic"'
        )
    store = BudgetStore(cfg.budget_root())
    cap = float(getattr(cfg, "budget_monthly_usd", 0) or 0)
    remaining = store.remaining(cap)
    max_usd = 0.0
    try:
        for locale in paying:
            if texts_by_locale is not None:
                texts = list(texts_by_locale.get(locale) or [])
            else:
                texts = _existing_texts(cfg, locale, namespaces, keys)
            if not texts:
                continue
            kind = paying_cloud_kind(cfg, locale) or (cfg.provider.kind or "").strip().lower()
            figures, _, _ = quote_locale(
                cfg, locale, texts, batch_size=batch_size, kind=kind,
            )
            max_usd += figures.max_usd
    except PricingError as exc:
        return refuse(str(exc))
    if max_usd > remaining:
        return refuse(
            f"cloud budget: {command} max_usd {max_usd:.4f} exceeds remaining "
            f"{remaining:.4f}. Not sending.",
            {"max_usd": round(max_usd, 6), "remaining_usd": round(remaining, 6)},
        )
    hold_id = None
    if take_hold and max_usd > 0 and cap > 0:
        hold_id = store.reserve(max_usd, cap_usd=cap)
        if hold_id is None:
            return refuse(
                f"cloud budget: {command} could not reserve {max_usd:.4f} "
                "(remaining raced to below the ceiling). Not sending.",
                {"max_usd": round(max_usd, 6), "remaining_usd": round(store.remaining(cap), 6)},
            )
    return None, hold_id
