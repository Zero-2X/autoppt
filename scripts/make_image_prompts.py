from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    run = Path(sys.argv[1])
    brief = json.loads((run / "slide_brief.json").read_text(encoding="utf-8"))
    provenance = json.loads((run / "imagegen_manifest.json").read_text(encoding="utf-8"))
    by_slide = {x["slide_id"]: x for x in provenance["slides"]}
    slides = []
    for item in brief["slides"]:
        record = by_slide.get(item["slide_id"], {})
        prompt = record.get("revised_prompt") or " ".join([item["title"], *item.get("content", []), item.get("visual", "")])
        prompt = "Complete final PPT page image, one complete final presentation page, not a background-only image. " + prompt
        slides.append({
            "slide_id": item["slide_id"],
            "prompt": prompt,
            "expected_output": "complete final PPT page image",
            "acceptance_criteria": ["complete final PPT page image", "one page only", "not a background-only image"],
            "output": f"masters/{item['slide_id']}.png",
            "generation_mode": "direct_final_slide_imagegen",
            "provenance": record.get("id"),
        })
    payload = {
        "schema_version": "imagegen-prompt-pack-v1",
        "generation_mode": "direct_final_slide_imagegen",
        "prompt_policy": {
            "output_mode": "direct_final_slide_imagegen",
            "imagegen_required": True,
            "builtin_imagegen_only": True,
            "external_api_key_allowed": False,
            "external_cli_allowed": False,
            "local_command_allowed": False,
            "mock_formal_output_allowed": False,
            "per_slide_imagegen_required": True,
            "complete_final_page_required": True,
            "no_native_ppt_overlay": True,
            "no_script_generated_slide_content": True,
        },
        "slides": slides,
    }
    (run / "image-prompts.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
