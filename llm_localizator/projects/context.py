"""Project-supplied translator guidance: glossary and per-key context notes.

Both are optional. A project with neither still translates and validates; it
just gets less help. Nothing here is required to exist, and a missing file is
never an error. A file that exists but is not JSON is.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..catalog.io import atomic_write_text
from ..catalog.io import read_json, read_json_dict


class ContextError(ValueError):
    """A context file exists but is not a JSON object."""


def context_json_errors(directory: Path | None) -> list[str]:
    """Paths of context files that exist but do not parse as a JSON object."""
    if directory is None or not Path(directory).is_dir():
        return []
    errors: list[str] = []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{path}: context file must be a JSON object")
    return errors


def require_context_json(directory: Path | None) -> None:
    """Fail before a translate/improve run, not on a random key mid-run."""
    errors = context_json_errors(directory)
    if errors:
        raise ContextError("; ".join(errors))


__all__ = [
    "ContextError",
    "context_json_errors",
    "require_context_json",
    "load_glossary",
    "load_glossary_bundle",
    "select_glossary",
    "effective_glossary_for",
    "glossary_conflicts",
    "GlossaryCache",
    "load_examples",
    "append_example",
    "ContextNotes",
    "glossary_prompt_block",
    "write_context_entry",
    "EMPTY_GLOSSARY",
]

EMPTY_GLOSSARY: dict = {"doNotTranslate": [], "terms": {}}
MAX_EXAMPLES_PER_LOCALE = 5


def _normalize_glossary(data: dict) -> dict:
    data = dict(data)
    data.setdefault("doNotTranslate", [])
    data.setdefault("terms", {})
    if not isinstance(data["doNotTranslate"], list):
        data["doNotTranslate"] = []
    if not isinstance(data["terms"], dict):
        data["terms"] = {}
    return data


def load_glossary(path: Path | None) -> dict:
    """Load a glossary file, or return the empty glossary if absent.

    Directory paths are supported via :func:`load_glossary_bundle` +
    :func:`select_glossary` (all domains merged — prefer
    :func:`effective_glossary_for` for domain-aware prompts).
    """
    if path is None or not Path(path).exists():
        return dict(EMPTY_GLOSSARY)
    path = Path(path)
    if path.is_dir():
        return select_glossary(load_glossary_bundle(path), domains=None)
    try:
        data = read_json(path)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: glossary file must be a JSON object")
    return _normalize_glossary(data)


def load_glossary_bundle(path: Path | None) -> dict[str, dict]:
    """Load ``global.json`` + ``<domain>.json`` from a glossary directory.

    Returns ``{domain_name: glossary_dict}`` where ``global`` is always present
    (possibly empty). A single file path yields ``{"global": <file>}``.
    """
    if path is None or not Path(path).exists():
        return {"global": dict(EMPTY_GLOSSARY)}
    path = Path(path)
    if path.is_file():
        return {"global": load_glossary(path)}
    out: dict[str, dict] = {"global": dict(EMPTY_GLOSSARY)}
    for child in sorted(path.glob("*.json")):
        name = child.stem
        try:
            raw = read_json(child)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"{child}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"{child}: glossary file must be a JSON object")
        out[name] = _normalize_glossary(raw)
    return out


def select_glossary(
    bundle: dict[str, dict],
    *,
    domains: list[str] | None = None,
) -> dict:
    """Merge ``global`` with the named domain glossaries (in order)."""
    merged = dict(EMPTY_GLOSSARY)
    merged["doNotTranslate"] = list(bundle.get("global", EMPTY_GLOSSARY).get("doNotTranslate", []))
    merged["terms"] = dict(bundle.get("global", EMPTY_GLOSSARY).get("terms", {}))
    names = domains if domains is not None else [
        n for n in bundle if n != "global"
    ]
    for name in names:
        if name == "global":
            continue
        part = bundle.get(name)
        if not part:
            continue
        for term in part.get("doNotTranslate", []):
            if term not in merged["doNotTranslate"]:
                merged["doNotTranslate"].append(term)
        for term, data in part.get("terms", {}).items():
            merged["terms"][term] = data
    return merged


def _overlay_glossary(base: dict, extra: dict) -> dict:
    """``extra`` wins on the same term. Used so the project glossary overrides shared."""
    merged = {
        "doNotTranslate": list(base.get("doNotTranslate") or []),
        "terms": dict(base.get("terms") or {}),
    }
    for term in extra.get("doNotTranslate") or []:
        if term not in merged["doNotTranslate"]:
            merged["doNotTranslate"].append(term)
    for term, data in (extra.get("terms") or {}).items():
        merged["terms"][term] = data
    return merged


def effective_glossary_for(
    path: Path | None,
    *,
    domains: list[str] | None = None,
    shared: list[Path] | None = None,
    conflict: str = "own",
) -> dict:
    """File or directory glossary, optionally restricted to ``domains``.

    Shared paths are read first. The project file overwrites the same term
    unless ``conflict`` is ``"shared"`` (ADR-60), where shared terms win.
    """
    merged = dict(EMPTY_GLOSSARY)
    for extra in shared or []:
        part = _load_glossary_path(extra, domains)
        merged = _overlay_glossary(merged, part)
    own = _load_glossary_path(path, domains)
    if conflict == "shared":
        shared_terms = set(merged.get("terms") or {})
        own = dict(own)
        own["terms"] = {
            t: d for t, d in (own.get("terms") or {}).items() if t not in shared_terms
        }
    return _overlay_glossary(merged, own)


def glossary_conflicts(
    path: Path | None, shared: list[Path] | None, domains: list[str] | None = None,
) -> list[str]:
    """Terms defined differently in the project glossary and a shared one."""
    own = (_load_glossary_path(path, domains).get("terms") or {})
    out: list[str] = []
    for extra in shared or []:
        for term, data in (_load_glossary_path(extra, domains).get("terms") or {}).items():
            if term in own and own[term] != data and term not in out:
                out.append(term)
    return sorted(out)


def _load_glossary_path(path: Path | None, domains: list[str] | None) -> dict:
    if path is None or not Path(path).exists():
        return dict(EMPTY_GLOSSARY)
    path = Path(path)
    if path.is_file():
        return load_glossary(path)
    bundle = load_glossary_bundle(path)
    if domains is None:
        return select_glossary(bundle, domains=None)
    return select_glossary(bundle, domains=domains)


class GlossaryCache:
    """Memoize :func:`effective_glossary_for` for one validation/import run."""

    __slots__ = ("_path", "_shared", "_cache", "_kind", "_conflict")

    def __init__(
        self, path: Path | None, *, shared: list[Path] | None = None, conflict: str = "own",
    ) -> None:
        self._path = path
        self._conflict = conflict
        self._shared = list(shared or [])
        self._cache: dict[tuple, dict] = {}
        p = Path(path) if path else None
        self._kind = "dir" if p is not None and p.is_dir() else "file"

    def get(self, domains: list[str] | None = None) -> dict:
        key = (
            str(self._path) if self._path else None,
            self._kind,
            tuple(str(p) for p in self._shared),
            tuple(domains or ()),
        )
        hit = self._cache.get(key)
        if hit is None:
            extra = {"conflict": self._conflict} if self._conflict != "own" else {}
            hit = effective_glossary_for(
                self._path, domains=domains, shared=self._shared, **extra,
            )
            self._cache[key] = hit
        return hit


def load_examples(path: Path | None) -> dict[str, list[tuple[str, str]]]:
    """Load few-shot pairs: ``{locale: [[source, target], ...]}``.

    Missing/malformed files yield an empty map. Each locale is capped at
    :data:`MAX_EXAMPLES_PER_LOCALE` pairs (first wins).
    """
    if path is None or not Path(path).exists():
        return {}
    raw = read_json_dict(Path(path))
    if raw is None:
        return {}
    out: dict[str, list[tuple[str, str]]] = {}
    for locale, pairs in raw.items():
        if not isinstance(pairs, list):
            continue
        cleaned: list[tuple[str, str]] = []
        for pair in pairs:
            if (
                isinstance(pair, (list, tuple))
                and len(pair) >= 2
                and isinstance(pair[0], str)
                and isinstance(pair[1], str)
                and pair[0].strip()
                and pair[1].strip()
            ):
                cleaned.append((pair[0], pair[1]))
            if len(cleaned) >= MAX_EXAMPLES_PER_LOCALE:
                break
        if cleaned:
            out[str(locale)] = cleaned
    return out


def append_example(path: Path, locale: str, source: str, target: str) -> bool:
    """Append one few-shot pair for ``locale``. Returns True if written.

    Dedupes exact (source, target) pairs. Caps at :data:`MAX_EXAMPLES_PER_LOCALE`
    by dropping the oldest when full.
    """
    if not source.strip() or not target.strip():
        return False
    path = Path(path)
    data = (read_json_dict(path) if path.exists() else None) or {}
    pairs = list(data.get(locale) or [])
    entry = [source, target]
    if entry in pairs or [source, target] in [[p[0], p[1]] for p in pairs if isinstance(p, list) and len(p) >= 2]:
        return False
    pairs.append(entry)
    if len(pairs) > MAX_EXAMPLES_PER_LOCALE:
        pairs = pairs[-MAX_EXAMPLES_PER_LOCALE:]
    data[locale] = pairs
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return True


def glossary_prompt_block(
    glossary: dict,
    locale: str,
    language: str,
    *,
    sources: list[str] | None = None,
) -> str:
    """Render glossary preamble for one target locale.

    Terms are injected per-string via :func:`glossary_hits` / BatchItem
    annotations. The preamble only lists do-not-translate terms — and when
    *sources* is provided, only those that appear in the batch.
    """
    from ..core.glossary_match import dnt_terms_in_sources

    lines: list[str] = []
    if sources is not None:
        dnt = dnt_terms_in_sources(glossary, sources)
    else:
        dnt = list(glossary.get("doNotTranslate", []))
    if dnt:
        lines.append(f"Never translate these terms, keep verbatim: {', '.join(dnt)}.")
    # Locale term mappings live on individual BatchItem.glossary_note lines so
    # a larger glossary does not bloat every prompt with irrelevant entries.
    _ = (locale, language)  # kept for call-site compatibility / future notes
    if glossary.get("terms"):
        lines.append(
            "Glossary terms override stylistic choices; violations are rejected."
        )
    return "\n".join(lines)


class ContextNotes:
    """Per-namespace translator notes, loaded lazily.

    A ``context/<ns>.json`` value may be a bare string or an object with
    ``note`` / ``screen`` / ``maxChars`` fields. Both forms are accepted.
    """

    def __init__(self, directory: Path | None) -> None:
        self.dir = Path(directory) if directory else None
        self._cache: dict[str, dict] = {}

    def invalidate(self, namespace: str | None = None) -> None:
        if namespace is None:
            self._cache.clear()
        else:
            self._cache.pop(namespace, None)

    def _load(self, namespace: str) -> dict:
        if namespace not in self._cache:
            if self.dir is None:
                self._cache[namespace] = {}
            else:
                # Empty namespace (json-flat) uses _root.json so the path is not ".json".
                name = f"{namespace}.json" if namespace else "_root.json"
                path = self.dir / name
                if not path.is_file():
                    self._cache[namespace] = {}
                    return self._cache[namespace]
                try:
                    data = read_json(path)
                except json.JSONDecodeError as exc:
                    raise ContextError(f"{path}: {exc}") from exc
                except OSError as exc:
                    raise ContextError(f"{path}: {exc}") from exc
                if not isinstance(data, dict):
                    raise ContextError(f"{path}: context file must be a JSON object")
                self._cache[namespace] = data
        return self._cache[namespace]

    def note(self, namespace: str, key: str) -> str:
        val = self._load(namespace).get(key)
        if isinstance(val, str):
            return val
        if isinstance(val, dict):
            n = val.get("note")
            if isinstance(n, str):
                return n.strip()
        return ""

    def tier(self, namespace: str, key: str) -> str | None:
        """Per-key content tier (``human`` / ``review`` / ``auto``), overriding the config globs."""
        val = self._load(namespace).get(key)
        if isinstance(val, dict) and val.get("tier") in ("human", "review", "auto"):
            return val["tier"]
        return None

    def llm_note(self, namespace: str, key: str) -> str:
        val = self._load(namespace).get(key)
        if isinstance(val, dict):
            note = val.get("llmNote")
            if isinstance(note, str):
                return note.strip()
        return ""

    def entry(self, namespace: str, key: str) -> dict | str | None:
        return self._load(namespace).get(key)

    def max_chars(self, namespace: str, key: str) -> int | None:
        val = self._load(namespace).get(key)
        if isinstance(val, dict):
            # ``maxChars`` is canonical; ``max_length`` / ``maxLength`` are accepted aliases.
            for field in ("maxChars", "maxLength", "max_length"):
                mc = val.get(field)
                if isinstance(mc, int) and not isinstance(mc, bool):
                    return mc
        return None

    def preview_values(self, namespace: str, key: str) -> dict[str, object]:
        """ADR-109 sample values kept on the entry (``preview_values``), e.g. ``{"rank": "Ace"}``."""
        val = self._load(namespace).get(key)
        if isinstance(val, dict):
            for field in ("preview_values", "previewValues"):
                raw = val.get(field)
                if isinstance(raw, dict):
                    return {str(k): v for k, v in raw.items()}
        return {}

    def html(self, namespace: str, key: str) -> bool:
        """Whether this string is known to carry HTML that must be preserved."""
        val = self._load(namespace).get(key)
        if isinstance(val, dict):
            flag = val.get("html")
            if isinstance(flag, bool):
                return flag
        return False

    def domain(self, namespace: str, key: str) -> str | None:
        """Optional glossary domain hint on the context entry."""
        val = self._load(namespace).get(key)
        if isinstance(val, dict):
            domain = val.get("domain")
            if isinstance(domain, str) and domain.strip():
                return domain.strip()
        return None

    def screen(self, namespace: str, key: str) -> str | None:
        val = self._load(namespace).get(key)
        if isinstance(val, dict):
            screen = val.get("screen")
            if isinstance(screen, str) and screen.strip():
                return screen.strip()
        return None

    def image(self, namespace: str, key: str) -> str | None:
        """Relative path under ``context_dir`` to a screenshot file, if set."""
        val = self._load(namespace).get(key)
        if isinstance(val, dict):
            image = val.get("image")
            if isinstance(image, str) and image.strip():
                return image.strip()
        return None

    def full_key(self, namespace: str, key: str) -> str | None:
        """Sibling key that holds the unconstrained long form, if declared."""
        val = self._load(namespace).get(key)
        if isinstance(val, dict):
            fk = val.get("fullKey")
            if isinstance(fk, str) and fk.strip():
                return fk.strip()
        return None

    def has_entry(self, namespace: str, key: str) -> bool:
        return key in self._load(namespace)

    def stale_args(self, namespace: str, key: str) -> dict:
        """Keyword arguments for ``needs_translation`` / ``make_entry``.

        A broken context file yields no context rather than an error, so status
        and work selection keep working; ``doctor`` reports the broken file.
        """
        try:
            return {
                "note": self.note(namespace, key),
                "screen": self.screen(namespace, key),
                "max_chars": self.max_chars(namespace, key),
            }
        except ContextError:
            return {}

    def _text_field(self, namespace: str, key: str, field: str) -> str | None:
        val = self._load(namespace).get(key)
        if isinstance(val, dict):
            raw = val.get(field)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return None

    def register(self, namespace: str, key: str) -> str | None:
        """Per-key ``formal`` / ``informal`` override of the locale register."""
        value = self._text_field(namespace, key, "register")
        return value.lower() if value and value.lower() in ("formal", "informal") else None

    def gender(self, namespace: str, key: str) -> str | None:
        """Grammatical gender of the entity a placeholder stands for, e.g. ``feminine``."""
        return self._text_field(namespace, key, "gender")

    def group(self, namespace: str, key: str) -> str | None:
        """Name of the sentence this key is one fragment of."""
        return self._text_field(namespace, key, "group")

    def group_keys(self, namespace: str, group: str) -> list[str]:
        """Every key of the namespace that declares ``group``, in key order."""
        data = self._load(namespace)
        return sorted(k for k, v in data.items() if isinstance(v, dict) and v.get("group") == group)

    def tags(self, namespace: str, key: str) -> list[str]:
        """Free-form labels on a key (C-035). Never part of the staleness hash."""
        val = self._load(namespace).get(key)
        raw = val.get("tags") if isinstance(val, dict) else None
        return normalize_tags(raw)

    def keys_with_tags(self, tags: list[str]) -> list[str]:
        """``namespace.key`` of every key carrying any of ``tags``, sorted."""
        want = set(normalize_tags(tags))
        if not want or self.dir is None or not self.dir.is_dir():
            return []
        out: list[str] = []
        for path in sorted(self.dir.glob("*.json")):
            ns = "" if path.stem == "_root" else path.stem
            for key, val in self._load(ns).items():
                if key.startswith("_") or not isinstance(val, dict):
                    continue
                if want & set(normalize_tags(val.get("tags"))):
                    out.append(f"{ns}.{key}" if ns else key)
        return sorted(out)

    def file_note(self, namespace: str) -> str:
        """Namespace-level translator note stored under the ``_note`` key."""
        val = self._load(namespace).get("_note")
        if isinstance(val, str):
            return val.strip()
        if isinstance(val, dict):
            n = val.get("note")
            if isinstance(n, str):
                return n.strip()
        return ""


_TAG_RE = re.compile(r"[^a-z0-9_-]+")


def normalize_tags(raw) -> list[str]:
    """Lower-case, de-duplicated, at most 12 tags of up to 32 characters."""
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        tag = _TAG_RE.sub("-", str(item).strip().lower()).strip("-")[:32]
        if tag and tag not in out:
            out.append(tag)
    return out[:12]


def _context_path(directory: Path, namespace: str) -> Path:
    name = f"{namespace}.json" if namespace else "_root.json"
    return directory / name


def write_context_entry(
    directory: Path,
    namespace: str,
    key: str,
    patch: dict,
) -> None:
    """Merge ``patch`` into one key's context note object and write the file."""
    directory = Path(directory)
    path = _context_path(directory, namespace)
    data = (read_json_dict(path) if path.exists() else None) or {}
    current = data.get(key)
    if isinstance(current, str):
        merged: dict = {"note": current}
    elif isinstance(current, dict):
        merged = dict(current)
    else:
        merged = {}
    for field, value in patch.items():
        if value is None or value == "" or value == []:
            merged.pop(field, None)
        else:
            merged[field] = value
    if merged:
        data[key] = merged
    else:
        data.pop(key, None)
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
