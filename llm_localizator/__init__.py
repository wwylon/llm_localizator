"""llm_localizator -- local-LLM localisation engine.

Translate, validate, and scan message catalogues for any project. The engine
lives here; every project's glossary, context notes, and translation state stay
in that project's own repository.

Importing this package has no side effects: no stdout reconfiguration, no
filesystem access, no network. Terminal setup happens in ``llm_localizator.cli``.
"""

from __future__ import annotations

__version__ = "0.2.0"
