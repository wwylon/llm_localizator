"""Verification workflow: run the engine's stages against a disposable project copy."""

from .runner import PROFILES, StageResult, exit_code_for, run_verify

__all__ = ["PROFILES", "StageResult", "exit_code_for", "run_verify"]
