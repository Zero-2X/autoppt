from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


def main() -> int:
    src, dst = map(Path, sys.argv[1:])
    deck = json.loads(src.read_text(encoding="utf-8"))
    clean = copy.deepcopy(deck)
    for slide in clean.get("slides", []):
        slide.pop("icons", None)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
