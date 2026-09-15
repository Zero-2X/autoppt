from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def repo_root(start: Path) -> Path:
    for path in [start.resolve(), *start.resolve().parents]:
        if (path / ".git").exists():
            return path
    return start.resolve()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_deck_spec(stage45_dir: Path, image_prompts: dict[str, Any]) -> Path:
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
            "assembly_note": "AutoSearch Stage9 adapter; full-slide image assembly.",
        },
        "slides": slides,
    }
    path = stage45_dir / "deck-spec.json"
    write_json(path, deck_spec)
    return path


def build_pptx_with_stage45_builder(stage45_dir: Path, output_path: Path, report_path: Path) -> None:
    skill_scripts = Path(__file__).resolve().parents[1]
    root = repo_root(Path(__file__))
    candidates = [
        skill_scripts / "build_competition_ppt.py",
        root / "research-workflow-pipeline" / "scripts" / "build_competition_ppt.py",
    ]
    builder = next((path for path in candidates if path.exists()), candidates[0])
    cmd = [
        sys.executable,
        str(builder),
        str(stage45_dir / "deck-spec.json"),
        "--output",
        str(output_path),
        "--report",
        str(report_path),
    ]
    subprocess.run(cmd, check=True)
