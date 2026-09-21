from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_deck_spec(workspace_dir: Path, image_prompts: dict[str, Any]) -> Path:
    slides = []
    for slide in image_prompts.get("slides", []):
        slides.append(
            {
                "slide_id": slide.get("slide_id"),
                "role": slide.get("page_role", ""),
                "layout": "full_slide_image",
                "headline": slide.get("headline", ""),
                "slide_image": slide.get("final_path", f"assets/slides/{slide.get('slide_id')}.png"),
                "imagegen_prompt_ref": slide.get("slide_id"),
                "source_refs": slide.get("source_refs", []),
            }
        )
    deck_spec = {
        "deck": {
            "title": image_prompts.get("deck_title", "Competition deck"),
            "output_mode": "imagegen_full_slide",
            "generation_mode": "direct_final_slide_imagegen",
            "presentation_profile": image_prompts.get("presentation_profile", "innovation_competition_defense"),
            "imagegen_route": image_prompts.get("imagegen_route", "fullpage_imagegen_reconstruct"),
            "slide_contract_schema": image_prompts.get("slide_contract_schema", "slide-ir-v1"),
            "assembly_note": "AutoPPT Workflow adapter; full-slide image assembly.",
        },
        "slides": slides,
    }
    path = workspace_dir / "deck-spec.json"
    write_json(path, deck_spec)
    return path


def build_pptx(workspace_dir: Path, output_path: Path, report_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    builder = root / "autopptskills" / "scripts" / "build_image_deck.py"
    if not builder.exists():
        raise FileNotFoundError(f"bundled PPTX builder not found: {builder}")
    cmd = [
        sys.executable,
        str(builder),
        str(workspace_dir / "deck-spec.json"),
        "--output",
        str(output_path),
        "--report",
        str(report_path),
    ]
    subprocess.run(cmd, check=True)
