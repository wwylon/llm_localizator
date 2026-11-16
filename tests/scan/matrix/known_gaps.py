"""Cells of the conformance matrix the scanner does not pass yet (baseline 2026-11-10, scanner v24).

Each entry is a strict xfail: once a fix makes the cell pass, the test fails until the entry is deleted,
so this backlog can only shrink. Do not add entries to hide a regression.
"""

KNOWN_GAPS: set[tuple[str, str]] = {

}
