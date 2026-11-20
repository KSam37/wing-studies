"""Check a built site: every media/file path the atlas data references must exist.

    python tools/check_site.py _site
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

EXT = ("webp", "png", "gif", "jpg", "json", "pdf", "csv", "svg")


def refs(o, out):
    if isinstance(o, dict):
        for v in o.values():
            refs(v, out)
    elif isinstance(o, list):
        for v in o:
            refs(v, out)
    elif isinstance(o, str) and "/" in o and o.rsplit(".", 1)[-1].lower() in EXT and " " not in o:
        out.add(o)


def main(site: Path) -> int:
    atlas = site / "atlas"
    html = (atlas / "index.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'id="atlas-data">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
    found: set[str] = set()
    refs({k: v for k, v in data.items() if k != "cols"}, found)
    missing = [r for r in sorted(found)
               if not ((atlas / "media" / r).exists() or (atlas / r).exists())]
    for r in missing:
        print("missing:", r)
    print(f"{len(found)} referenced files, {len(missing)} missing")
    if not (site / "index.html").exists():
        print("missing landing page")
        return 1
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "_site")))
