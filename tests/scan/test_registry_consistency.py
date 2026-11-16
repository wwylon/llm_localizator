"""The language registry and the "not scanned" list never disagree."""

from __future__ import annotations

from llm_localizator.core.languages import source_languages
from llm_localizator.scan.base import UNSUPPORTED_UI_EXTENSIONS


def test_registered_extensions_are_not_reported_as_unscanned() -> None:
    registered = {ext for lang in source_languages() for ext in lang.extensions}
    both = registered & UNSUPPORTED_UI_EXTENSIONS
    assert not both, f"scanned AND reported as not scanned: {sorted(both)}"


def test_every_language_names_a_known_detector() -> None:
    known = {"jsx", "js", "html", "literal", "sfc", "templ", "template", "xmlui", "propdef", "content", "indent", "astro", "mdx"}
    for lang in source_languages():
        assert lang.detector in known, f"{lang.id}: unknown detector {lang.detector!r}"
