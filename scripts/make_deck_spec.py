from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    run = Path(sys.argv[1])
    brief = json.loads((run / "slide_brief.json").read_text(encoding="utf-8"))
    prompts = json.loads((run / "image-prompts.json").read_text(encoding="utf-8"))
    prompt_by_id = {item["slide_id"]: item for item in prompts["slides"]}
    spec = {
        "deck": {
            "title": brief["deck_title"],
            "output_mode": "imagegen_full_slide",
            "generation_mode": "direct_final_slide_imagegen",
            "provenance_manifest": "imagegen_manifest.json",
        },
        "slides": [
            {
                "slide_id": slide["slide_id"],
                "layout": "full_slide_image",
                "slide_image": f"masters/{slide['slide_id']}.png",
                "slide_manifest": {**slide, **prompt_by_id.get(slide["slide_id"], {})},
            }
            for slide in brief["slides"]
        ],
    }
    (run / "deck-spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
