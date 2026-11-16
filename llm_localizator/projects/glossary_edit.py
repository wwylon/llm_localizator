"""Mutate one glossary domain file. Other domain files are not opened for write."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..catalog.io import atomic_write_text
from .context import load_glossary_bundle
from ..catalog.io import read_json

__all__ = ["glossary_payload", "import_glossary_records", "mutate_glossary"]

_DOMAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LOCALE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")
_ACTIONS = frozenset({"add", "edit", "delete"})
_KINDS = frozenset({"term", "dnt"})


def glossary_payload(cfg) -> dict:
    """Bundle the page lists. A missing path is an empty global domain."""
    path = cfg.glossary_path
    if path is None:
        return {"ok": False, "error": "no glossary path configured"}
    path = Path(path)
    return {
        "ok": True,
        "path": str(path),
        "directory": path.is_dir(),
        "sourceLocale": cfg.source_locale,
        "locales": list(cfg.targets),
        "activeLocales": list(cfg.active_targets()),
        "frozenLocales": list(cfg.frozen),
        "domains": load_glossary_bundle(path),
    }


def import_glossary_records(
    path: Path | None,
    records: list,
    *,
    conflict: str = "skip",
    dry_run: bool = False,
) -> dict:
    """Merge parsed rows. ``skip`` keeps the project term. Nothing is written on dry-run."""
    if path is None:
        raise ValueError("no glossary path configured")
    if conflict not in {"skip", "overwrite"}:
        raise ValueError(f"unknown conflict {conflict!r}")
    root = Path(path)
    owners = _owners(root)
    dirty: dict[str, dict] = {}
    skipped = 0
    applied = 0
    for record in records:
        owner = owners.get(record.term)
        if owner is not None and conflict != "overwrite":
            skipped += 1
            continue
        domain = "global" if (root.exists() and root.is_file()) or (not root.exists() and root.suffix == ".json") else (owner or "global")
        if domain not in dirty:
            dirty[domain] = _read_raw(_domain_file(root, domain))
        _apply_record(dirty[domain], record)
        owners[record.term] = domain
        applied += 1
    if not dry_run:
        for domain, data in dirty.items():
            _write_raw(_domain_file(root, domain), data)
    return {"applied": applied, "skipped": skipped, "dry_run": dry_run}


def _owners(root: Path) -> dict[str, str]:
    owners: dict[str, str] = {}
    if not root.exists():
        return owners
    for name, part in load_glossary_bundle(root).items():
        for term in part.get("doNotTranslate") or []:
            owners.setdefault(str(term), name)
        for term in part.get("terms") or {}:
            owners.setdefault(str(term), name)
    return owners


def _apply_record(data: dict, record) -> None:
    terms = data["terms"]
    dnt = data["doNotTranslate"]
    term = record.term
    if getattr(record, "dnt", False):
        terms.pop(term, None)
        if term not in dnt:
            dnt.append(term)
        return
    if term in dnt:
        dnt.remove(term)
    entry: dict = {}
    previous = terms.get(term) if isinstance(terms.get(term), dict) else {}
    new_forms = getattr(record, "forms", None) or {}
    for locale, text in record.translations.items():
        if text:
            entry[locale] = text
            # An import without a forms column must not wipe the forms a project maintains.
            forms = new_forms.get(locale) or previous.get(f"{locale}_forms")
            if forms:
                entry[f"{locale}_forms"] = list(forms)
    for locale, words in record.forbidden.items():
        if words:
            entry[f"{locale}_forbidden"] = list(words)
    notes = getattr(record, "notes", None) or {}
    if isinstance(notes, dict):
        for locale, text in notes.items():
            if text:
                entry[f"{locale}_note"] = str(text)
    elif getattr(record, "note", None):
        entry["note"] = record.note
    terms[term] = entry


def mutate_glossary(
    path: Path | None,
    *,
    domain: str,
    action: str,
    term: str,
    kind: str = "term",
    translations: dict | None = None,
    forbidden: dict | None = None,
    notes: dict | None = None,
    note: str | None = None,
) -> dict:
    """Add, edit, or delete one term in one domain file."""
    if path is None:
        raise ValueError("no glossary path configured")
    if action not in _ACTIONS:
        raise ValueError(f"unknown glossary action {action!r}")
    if kind not in _KINDS:
        raise ValueError(f"unknown glossary kind {kind!r}")
    term = str(term or "").strip()
    if not term or len(term) > 200 or "\n" in term:
        raise ValueError("glossary term must be a single non-empty line")
    domain = str(domain or "global").strip() or "global"
    file_path = _domain_file(Path(path), domain)
    if action == "add":
        _refuse_other_domain(Path(path), domain, term)
    data = _read_raw(file_path)
    terms = data["terms"]
    dnt = data["doNotTranslate"]
    if kind == "dnt":
        _mutate_dnt(dnt, action, term)
    else:
        _mutate_term(
            terms, action, term,
            translations=_string_map(translations),
            forbidden=_forbidden_map(forbidden),
            notes=_string_map(notes) if notes is not None else None,
            note=None if note is None else str(note),
        )
    _write_raw(file_path, data)
    return {"ok": True, "domain": domain, "term": term, "action": action}


def _domain_file(root: Path, domain: str) -> Path:
    if not _DOMAIN.fullmatch(domain):
        raise ValueError(f"invalid glossary domain {domain!r}")
    if root.exists() and root.is_file():
        if domain != "global":
            raise ValueError(f"{root} is a file; domain must be global")
        return root
    if not root.exists() and root.suffix == ".json":
        if domain != "global":
            raise ValueError(f"{root} is a file; domain must be global")
        return root
    return root / f"{domain}.json"


def _refuse_other_domain(root: Path, domain: str, term: str) -> None:
    if not root.exists():
        return
    bundle = load_glossary_bundle(root)
    for name, part in bundle.items():
        if name == domain:
            continue
        if term in part.get("terms", {}) or term in part.get("doNotTranslate", []):
            raise ValueError(f"{term!r} already exists in {name}")


def _read_raw(path: Path) -> dict:
    if not path.exists():
        return {"doNotTranslate": [], "terms": {}}
    try:
        raw = read_json(path)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: glossary file must be a JSON object")
    data = dict(raw)
    dnt = data.get("doNotTranslate", [])
    terms = data.get("terms", {})
    data["doNotTranslate"] = [str(item) for item in dnt if isinstance(item, str) and item] if isinstance(dnt, list) else []
    data["terms"] = dict(terms) if isinstance(terms, dict) else {}
    return data


def _write_raw(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, payload)


def _mutate_dnt(dnt: list, action: str, term: str) -> None:
    present = term in dnt
    if action == "delete":
        if not present:
            raise ValueError(f"{term!r} is not a do-not-translate term")
        dnt.remove(term)
        return
    if present and action == "add":
        raise ValueError(f"{term!r} is already do-not-translate")
    if not present:
        dnt.append(term)


def _mutate_term(
    terms: dict,
    action: str,
    term: str,
    *,
    translations: dict[str, str],
    forbidden: dict[str, list[str]],
    notes: dict[str, str] | None,
    note: str | None,
) -> None:
    current = terms.get(term)
    exists = isinstance(current, dict)
    if action == "delete":
        if not exists:
            raise ValueError(f"{term!r} is not in this domain")
        del terms[term]
        return
    if action == "add" and exists:
        raise ValueError(f"{term!r} is already in this domain")
    if action == "edit" and not exists:
        raise ValueError(f"{term!r} is not in this domain")
    base = dict(current) if exists else {}
    for locale, text in translations.items():
        if text:
            base[locale] = text
        else:
            base.pop(locale, None)
    for locale, words in forbidden.items():
        key = f"{locale}_forbidden"
        if words:
            base[key] = words
        else:
            base.pop(key, None)
    if notes is not None:
        for locale, text in notes.items():
            key = f"{locale}_note"
            if text.strip():
                base[key] = text.strip()
            else:
                base.pop(key, None)
        # Locale notes replace the legacy shared note on write.
        base.pop("note", None)
    elif note is not None:
        if note.strip():
            base["note"] = note.strip()
        else:
            base.pop("note", None)
    terms[term] = base


def _string_map(value: dict | None) -> dict[str, str]:
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("translations must be an object")
    out: dict[str, str] = {}
    for locale, text in value.items():
        name = str(locale)
        if not _LOCALE.fullmatch(name):
            raise ValueError(f"invalid locale {name!r}")
        out[name] = "" if text is None else str(text)
    return out


def _forbidden_map(value: dict | None) -> dict[str, list[str]]:
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("forbidden must be an object")
    out: dict[str, list[str]] = {}
    for locale, words in value.items():
        name = str(locale)
        if not _LOCALE.fullmatch(name):
            raise ValueError(f"invalid locale {name!r}")
        if isinstance(words, str):
            items = [part.strip() for part in words.split(";") if part.strip()]
        elif isinstance(words, list):
            items = [str(part).strip() for part in words if str(part).strip()]
        else:
            raise ValueError(f"forbidden for {name} must be a list")
        out[name] = items
    return out

