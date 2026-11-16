"""String-literal lexers for the languages without a framework scanner (split from ``scan/literals.py``, M3).

Each lexer yields ``(line, literal)`` for one file; ``iter_literals`` picks it from the language's quote style.
"""

from __future__ import annotations

from ...core.languages import SourceLanguage
from .cpp import _cpp
from .csharp import _csharp
from .go import _go
from .python import _python
from .script import _script

__all__ = ["iter_literals"]


def iter_literals(text: str, lang: SourceLanguage):
    """Yield ``(line, literal)`` for one source file. Line numbers start at 1."""
    kind = lang.quotes
    if kind == "python":
        yield from _python(text)
    elif kind == "go":
        yield from _go(text)
    elif kind == "cpp":
        yield from _cpp(text)
    elif kind == "csharp":
        yield from _csharp(text)
    elif kind == "script":
        yield from _script(text, lang)
