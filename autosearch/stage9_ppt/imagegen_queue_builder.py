from __future__ import annotations

from pathlib import Path
from typing import Any


def build_generation_queue(stage45_dir: Path, image_prompts: dict[str, Any], *, mock: bool) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for slide in image_prompts.get("slides", []):
        final_path = stage45_dir / slide.get("final_path", f"assets/slides/{slide.get('slide_id')}.png")
        queue.append(
            {
                "slide_id": slide.get("slide_id"),
                "headline": slide.get("headline", ""),
                "final_path": str(final_path),
                "prompt": slide.get("prompt_zh") or slide.get("prompt_en") or "",
                "mock": mock,
                "status": "pending",
            }
        )
    return queue

