# The quality loop

How to find translation defects in a real project, turn each into a test, and keep it fixed.

1. **Audit** the real project (read-only):

   ```bash
   python scripts/audit_catalogue.py --project bridge --config path/to/.llm-localize.toml
   ```

   One row per defect class and locale, with who wrote the text (model and channel). Hard classes are
   what a translate or import gate would refuse now; soft classes are advisory. `--json out.json` keeps every
   row.
2. **A new class, or a class you cannot explain?** Add a seeded case to `tests/synth/specs.py` (`DEFECTS`): the
   bad value, its class, the check id that must notice it, whether import must refuse it, who wrote it.
   Run `pytest tests/synth`: it fails. That is the bug report.
3. **Fix** the detector or gate. Prefer one gate that every write path shares (`core/validate.py`,
   `pipeline/candidates.py`) over a check in one caller.
4. **Precision.** A clean project (`build_project(tmp)`) must produce zero findings; if your fix flags gold text,
   fix the check, not the gold.
5. **Ratchet.** `pytest tests/synth` compares `tests/synth/scorecard.json`; numbers may only improve. Update the
   file in the same change when they do:

   ```bash
   python -c "import sys,tempfile,pathlib,json; sys.path.insert(0,'.'); from tests.synth.scorecard import compute,RATCHET_FILE; n=compute(pathlib.Path(tempfile.mkdtemp())); RATCHET_FILE.write_text(json.dumps({k:n[k] for k in ('defects','detected','hard_defects','hard_rejected_on_import','clean_findings')},indent=2)+'\n')"
   ```
6. **Repair** existing data: `llm-localizator bulk-clear <project> --invalid --latin-leftover --dry-run`, read the list,
   then `--confirm`, then `translate`.
7. **Re-audit** and record before and after in your project notes.

`python scripts/audit_catalogue.py --synth --defects` prints the same table for the seeded project, which is how
to check that the audit and the scorecard agree. `ChaosProvider` (`llm_localizator/providers/chaos.py`) is the model
stand-in for lifecycle tests: give it a translator and fault rates and it records what it injected.
