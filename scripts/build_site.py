#!/usr/bin/env python3
"""Export the public marketing site as static files (GitHub Pages).

    python scripts/build_site.py                         # -> site/, custom domain
    python scripts/build_site.py --base-path /llm_localizator/ \\
        --site-url https://wwylon.github.io               # project Pages subpath

The pages are the in-app marketing pages rendered in public mode
(``llm_localizator.web.static_site``): base-path links, no loopback links.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_localizator.engines.fetch import build_index  # noqa: E402
from llm_localizator.web.static_site import DEFAULT_SITE_URL, StaticSite, build_site  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="site", help="output directory (default: site)")
    parser.add_argument("--base-path", default="/", help="URL path the site is served under (default: /)")
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL, help=f"public origin (default: {DEFAULT_SITE_URL})")
    args = parser.parse_args(argv)
    site = StaticSite(base_path=args.base_path, site_url=args.site_url)
    written = build_site(Path(args.out), site)
    # `llm-localizator engine fetch` reads <site>/engines/index.json plus the engine files it lists (sha256 pinned).
    index = build_index(out=Path(args.out) / "engines")
    print(f"wrote {len(written)} files and {len(index['engines'])} engines to {args.out} (base path {site.base_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
