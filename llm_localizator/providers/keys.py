"""Where a cloud provider's API key comes from: the environment only, never TOML.

Lookup order (first non-empty wins):

1. the variable named by ``api_key_env`` in the provider's config table, when set;
2. ``LLM_LOCALIZATOR_<VENDOR VARIABLE>``, for example ``LLM_LOCALIZATOR_ANTHROPIC_API_KEY``,
   so this tool can use a key (and a spending limit) separate from other software;
3. the vendor's standard variable, for example ``ANTHROPIC_API_KEY``.

Only variable *names* are handled here. A key value is never logged or returned in a message.
"""

from __future__ import annotations

import os

__all__ = ["PREFIX", "candidate_vars", "resolve_api_key", "key_source"]

PREFIX = "LLM_LOCALIZATOR_"


def candidate_vars(vendor_var: str, api_key_env: str | None = None) -> list[str]:
    """Variable names to try, in order, without duplicates."""
    names: list[str] = []
    for name in ((api_key_env or "").strip(), f"{PREFIX}{vendor_var}", vendor_var):
        if name and name not in names:
            names.append(name)
    return names


def resolve_api_key(vendor_var: str, api_key_env: str | None = None) -> str:
    """The key from the first candidate variable that is set, or an empty string."""
    for name in candidate_vars(vendor_var, api_key_env):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def key_source(vendor_var: str, api_key_env: str | None = None) -> str | None:
    """Name (never the value) of the variable that supplies the key, or None when none is set."""
    for name in candidate_vars(vendor_var, api_key_env):
        if (os.environ.get(name) or "").strip():
            return name
    return None
