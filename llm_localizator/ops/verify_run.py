"""``llm-localizator verify`` -- run the verification workflow on a project copy."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from ..verify import exit_code_for, run_verify
from .types import OpResult, VerifyRequest

__all__ = ["op_verify_run"]


def op_verify_run(req: VerifyRequest) -> OpResult:
    try:
        run_dir, results = run_verify(
            Path(req.path or "."), profile=req.profile,
            out=Path(req.out) if req.out else None, resume=req.resume,
            only=req.only, skip=req.skip, locales=req.locales,
        )
    except ValueError as exc:
        return OpResult(ok=False, exit_code=64, command="verify", summary=str(exc), lines=[str(exc)])
    code = exit_code_for(results)
    lines = [
        f"{r.stage} {r.title}: {r.verdict}" + (f" - {r.notes[0].splitlines()[0]}" if r.notes else "")
        for r in results
    ]
    lines.append(f"report: {run_dir / 'VERIFY.md'}")
    return OpResult(
        ok=code == 0, exit_code=code, command="verify",
        summary=f"{sum(r.verdict == 'pass' for r in results)}/{len(results)} stages pass",
        lines=lines,
        data={"runDir": str(run_dir), "stages": [asdict(r) for r in results]},
    )
