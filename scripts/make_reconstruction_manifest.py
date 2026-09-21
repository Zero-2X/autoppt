from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    run = Path(sys.argv[1])
    brief = json.loads((run / "slide_brief.json").read_text(encoding="utf-8"))
    slides = []
    for item in brief["slides"]:
        exact = [item["title"]]
        exact.extend(item.get("content", []))
        exact.extend(item.get("editable", []))
        slides.append({"slide_id": item["slide_id"], "title": item["title"], "exact_text": exact, "content": item.get("content", []), "visual": item.get("visual", "")})
    (run / "reconstruction-manifest.json").write_text(json.dumps({"schema_version": "slide-manifest-v1", "slides": slides}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
