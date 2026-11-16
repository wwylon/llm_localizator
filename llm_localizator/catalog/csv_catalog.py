"""CSV catalog adapter.

One CSV file per namespace; the header row names the columns:

    key,en,pl,de,ar
    loginTitle,Sign in,Zaloguj się,Anmelden,تسجيل الدخول
    registerTitle,Create account,...

The ``key`` column is always first. Locale columns may appear in any order.
Missing cells are treated as untranslated (empty string).

Typical path template:

    path = "messages/{namespace}.csv"

For a single-namespace project:

    path = "messages/translations.csv"
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .base import Catalog, FlatMessages
from .io import atomic_write_text

__all__ = ["CsvCatalog"]

_KEY_COL = "key"


class CsvCatalog(Catalog):
    """Translations stored as CSV; one column per locale."""

    def namespaces(self) -> list[str]:
        return self.discover_namespaces()

    # ---- path: no {locale} segment -----------------------------------------

    def path_for(self, locale: str, namespace: str | None = None) -> Path:
        template = self.path_template.replace("{locale}/", "").replace("{locale}", "")
        if namespace is not None and "{namespace}" in template:
            template = template.replace("{namespace}", namespace)
        return self.root / template

    def discover_namespaces(self) -> list[str]:  # type: ignore[override]
        template = self.path_template.replace("{locale}/", "").replace("{locale}", "")
        if "{namespace}" not in template:
            return [""]
        prefix, _, suffix = template.partition("{namespace}")
        base = (self.root / prefix).resolve()
        if not base.is_dir():
            return []
        results = []
        for p in sorted(base.iterdir()):
            tail = suffix.lstrip("/")
            if p.is_file() and tail and p.name.endswith(tail) and p.name != tail:
                results.append(p.name[: -len(tail)])
        return results

    # ---- load ---------------------------------------------------------------

    def load(self, locale: str, namespace: str | None = None) -> FlatMessages:
        path = self.path_for(locale, namespace)
        # Cache the full matrix (all locales), then slice by locale.
        matrix = self._cached_load(path, self._parse_all)
        return {key: row[locale]
                for key, row in matrix.items()  # type: ignore[attr-defined]
                if locale in row and row[locale]}

    @staticmethod
    def _parse_all(path: Path) -> dict:  # type: ignore[return-value]
        """Return {key: {locale: value}} for the whole CSV."""
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or _KEY_COL not in reader.fieldnames:
            return {}
        matrix: dict[str, dict[str, str]] = {}
        for row in reader:
            key = row.get(_KEY_COL, "").strip()
            if not key:
                continue
            matrix[key] = {col: row[col].strip() for col in reader.fieldnames
                           if col != _KEY_COL and row.get(col, "").strip()}
        return matrix  # type: ignore[return-value]

    # ---- save ---------------------------------------------------------------

    def save(self, locale: str, namespace: str | None, messages: FlatMessages) -> None:
        path = self.path_for(locale, namespace)
        # Read existing to preserve other locales
        existing_rows: dict[str, dict[str, str]] = {}
        fieldnames: list[str] = [_KEY_COL]
        if path.exists():
            text = path.read_text(encoding="utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            if reader.fieldnames:
                fieldnames = list(reader.fieldnames)
            for row in reader:
                key = row.get(_KEY_COL, "").strip()
                if key:
                    existing_rows[key] = dict(row)
        # Merge new locale column
        if locale not in fieldnames:
            fieldnames.append(locale)
        # Apply updates
        for key, val in messages.items():
            row = existing_rows.setdefault(key, {_KEY_COL: key})
            row[locale] = val
        # Drop keys absent from the merged write set (orphan prune / merge_for_write).
        keep = set(messages)
        existing_rows = {k: v for k, v in existing_rows.items() if k in keep}
        # Write
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for key in sorted(existing_rows):
            writer.writerow(existing_rows[key])
        atomic_write_text(path, buf.getvalue())
        self._bust_cache(path)

    # ---- locales_present ----------------------------------------------------

    def locales_present(self) -> list[str]:
        found: set[str] = set()
        for ns in self.namespaces():
            path = self.path_for("", ns)
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            if reader.fieldnames:
                for col in reader.fieldnames:
                    if col != _KEY_COL and col != self.source_locale:
                        found.add(col)
        return sorted(found)
