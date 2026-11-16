"""Scanner code changed ⇒ ``_SCAN_VERSION`` bumped (M5). Every bump invalidates scan caches, so forgetting one leaves
users with stale cached hits.

After bumping ``_SCAN_VERSION`` in ``llm_localizator/ops/agent_hardcoded.py``, refresh the record:

    .venv/Scripts/python.exe tests/scan/test_scan_version_digest.py --update
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = ROOT / "llm_localizator" / "scan"
RECORD = Path(__file__).with_name("scan_version.json")


def digest() -> str:
    h = hashlib.sha1()
    for path in sorted(SCAN.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        h.update(path.relative_to(SCAN).as_posix().encode("utf-8"))
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def current_version() -> int:
    from llm_localizator.ops.agent_hardcoded import _SCAN_VERSION

    return _SCAN_VERSION


def test_scanner_change_bumps_the_version() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    now = digest()
    if now == record["digest"]:
        return
    assert current_version() != record["version"], (
        "llm_localizator/scan/ changed but _SCAN_VERSION did not: bump it (and add a docs/scanners.md changelog row), "
        "then run: python tests/scan/test_scan_version_digest.py --update"
    )
    raise AssertionError(
        f"_SCAN_VERSION is {current_version()} but the record says {record['version']}: "
        "run python tests/scan/test_scan_version_digest.py --update and commit tests/scan/scan_version.json"
    )


if __name__ == "__main__":
    if "--update" in sys.argv:
        sys.path.insert(0, str(ROOT))
        RECORD.write_text(json.dumps({"version": current_version(), "digest": digest()}, indent=1) + "\n",
                          encoding="utf-8")
        print(f"recorded v{current_version()} {digest()[:12]}")
