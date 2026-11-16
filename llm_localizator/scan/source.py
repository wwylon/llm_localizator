"""Scan every language in the registry.

Framework files keep their call-site parsers. Other languages use the shared
literal detector. A project that is not next-intl does not have to pretend.
"""

from __future__ import annotations

from pathlib import Path

from ..core.languages import language_for_suffix, source_languages
from .base import Scanner, ScanResult, paths_with_suffixes
from .literals import scan_literal_file
from .next_intl import NextIntlScanner
from .raw_js import RawJsScanner

__all__ = ["SourceScanner"]


class SourceScanner(Scanner):
    @property
    def routing_note(self) -> str:
        return (
            "Replace the literal with this file's translation call. "
            "JSX uses t(); HTML and JS use i18n.t() or data-i18n."
        )

    @property
    def file_glob(self) -> str:
        return "**/*"

    def iter_files(self):
        extensions = [ext for lang in source_languages() for ext in lang.extensions]
        if self.content_globs:
            extensions += [".yml", ".yaml"]  # declared YAML text files (``[scan] content_globs``)
        for path in paths_with_suffixes(self, [*extensions, ".txt"], skip_names=("i18n.js",)):
            # A ``.txt`` file is read only inside a ``templates`` folder (Flask/Django e-mail bodies), never elsewhere.
            if path.suffix.lower() != ".txt" or "templates" in (part.lower() for part in path.parts[:-1]):
                yield path

    def _delegate(self, cls):
        """The framework scanner for one file kind (owns its own helpers)."""
        cache = self.__dict__.setdefault("_delegates", {})
        if cls not in cache:
            # M2: a delegate sees the project's [scan] settings, not the constructor defaults.
            delegate = cls(self.root, self.src_dirs, exclude=list(self.exclude), unskip=list(self.unskip))
            delegate.t_functions = self.t_functions
            delegate.content_globs = self.content_globs
            delegate.directive_aliases = self.directive_aliases
            cache[cls] = delegate
        return cache[cls]

    def scan_file(self, path: Path, lines: list[str], result: ScanResult) -> None:
        if path.name.lower().endswith(".blade.php"):
            from .templates import scan_template_file

            scan_template_file(self._delegate(RawJsScanner), path, lines, result)
            return
        if path.suffix.lower() == ".txt":
            from .templates import scan_text_template

            scan_text_template(self, path, lines, result)
            return
        lang = language_for_suffix(path.suffix)
        if lang is None and path.suffix.lower() in (".yml", ".yaml"):
            from .content import scan_content_file

            scan_content_file(self, path, lines, result)
            return
        if lang is None:
            return
        if lang.detector == "jsx":
            self._delegate(NextIntlScanner).scan_file(path, lines, result)
        elif lang.detector in {"js", "html"}:
            self._delegate(RawJsScanner).scan_file(path, lines, result)
        elif lang.detector == "xmlui":
            from .xmlui import scan_xmlui_file

            scan_xmlui_file(self, path, lines, result)
        elif lang.detector == "content":
            from .content import scan_content_file

            scan_content_file(self, path, lines, result)
        elif lang.detector == "propdef":
            from .propdef import scan_propdef_file

            scan_propdef_file(self, path, lines, result)
        elif lang.detector == "template":
            from .templates import scan_template_file

            scan_template_file(self._delegate(RawJsScanner), path, lines, result)
        elif lang.detector in {"astro", "mdx"}:
            from .astro_mdx import scan_astro_file, scan_mdx_file

            scan = scan_astro_file if lang.detector == "astro" else scan_mdx_file
            scan(self, self._delegate(NextIntlScanner), path, lines, result)
        elif lang.detector == "indent":
            from .markup_indent import scan_indent_file

            scan_indent_file(self, self._delegate(RawJsScanner), path, lines, result)
        elif lang.detector == "templ":
            from .templ import scan_templ_file

            scan_templ_file(self._delegate(RawJsScanner), path, lines, result)
        elif lang.detector == "sfc":
            from .sfc import scan_sfc_file

            scan_sfc_file(self._delegate(RawJsScanner), path, lines, result)
        else:
            scan_literal_file(self, path, lines, result)
