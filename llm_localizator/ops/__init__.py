"""Shared operations layer for CLI and web."""

from .dispatch import dispatch_op, is_streamable
from .manifest import build_commands_manifest
from .types import OpResult

__all__ = ["OpResult", "dispatch_op", "build_commands_manifest", "is_streamable"]
