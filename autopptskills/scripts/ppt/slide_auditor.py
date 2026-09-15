from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def audit_ppt(
    *,
    image_prompts: dict[str, Any],
    image_dir: Path,
    pptx_path: Path,
    mock: bool,
    asset_manifest_path: Path | None = None,
) -> dict[str, Any]:
    slides = image_prompts.get("slides", [])
    issues: list[str] = []
    slide_results: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}
    manifest_by_slide: dict[str, dict[str, Any]] = {}
    if asset_manifest_path and asset_manifest_path.exists():
        try:
            manifest = json.loads(asset_manifest_path.read_text(encoding="utf-8-sig"))
            manifest_by_slide = {
                str(item.get("slide_id")): item
                for item in manifest.get("slides", [])
                if isinstance(item, dict) and item.get("slide_id")
            }
        except Exception as exc:  # noqa: BLE001 - audit should report malformed evidence, not crash.
            issues.append(f"invalid_asset_manifest:{exc.__class__.__name__}")
    elif not mock:
        issues.append("missing_asset_manifest")

    for slide in slides:
        slide_id = slide.get("slide_id", "")
        expected = image_dir / f"{slide_id}.png"
        exists = expected.exists()
        evidence_refs = slide.get("evidence_refs", [])
        if not exists:
            issues.append(f"missing_image:{slide_id}")
        if not slide.get("prompt_zh") and not slide.get("prompt_en"):
            issues.append(f"missing_prompt:{slide_id}")
        if not evidence_refs:
            issues.append(f"missing_evidence_refs:{slide_id}")
        if evidence_refs and "Evidence anchors:" not in str(slide.get("prompt_zh", "")):
            issues.append(f"missing_evidence_anchor_block:{slide_id}")
        if any("{" in str(item) or "}" in str(item) for item in slide.get("exact_text", [])):
            issues.append(f"unresolved_variable:{slide_id}")
        manifest_record = manifest_by_slide.get(str(slide_id), {})
        generation_status = str(manifest_record.get("status", ""))
        generation_backend = str(manifest_record.get("backend", ""))
        if not mock:
            if not manifest_record:
                issues.append(f"missing_imagegen_manifest_record:{slide_id}")
            elif generation_status != "generated":
                issues.append(f"image_not_freshly_generated:{slide_id}:{generation_status or 'missing_status'}")
            elif generation_backend == "existing":
                issues.append(f"image_reused_existing:{slide_id}")
        slide_results.append(
            {
                "slide_id": slide_id,
                "image_exists": exists,
                "prompt_exists": bool(slide.get("prompt_zh") or slide.get("prompt_en")),
                "evidence_ref_count": len(evidence_refs),
                "headline": slide.get("headline", ""),
                "mock": mock,
                "imagegen_status": generation_status,
                "imagegen_backend": generation_backend,
            }
        )

    if not pptx_path.exists():
        issues.append("missing_final_deck")

    audit = {
        "verdict": "pass" if not issues else "fail",
        "mock_mode": mock,
        "mock_visual_risk": mock,
        "imagegen_generation_verified": (not mock and not any(
            issue.startswith("missing_asset_manifest")
            or issue.startswith("invalid_asset_manifest")
            or issue.startswith("missing_imagegen_manifest_record")
            or issue.startswith("image_not_freshly_generated")
            or issue.startswith("image_reused_existing")
            for issue in issues
        )),
        "asset_manifest": str(asset_manifest_path) if asset_manifest_path else "",
        "slide_count": len(slides),
        "pptx_exists": pptx_path.exists(),
        "issues": issues,
        "warnings": ["mock images prove pipeline structure, not final visual quality"] if mock else [],
        "presentation_gate": {
            "judge_facing": True,
            "slide_count_8_to_12": 8 <= len(slides) <= 12,
            "has_prompt_per_slide": all(bool(s.get("prompt_zh") or s.get("prompt_en")) for s in slides),
            "has_evidence_refs_per_slide": all(bool(s.get("evidence_refs", [])) for s in slides),
            "no_placeholder_detected": not issues,
        },
        "slides": slide_results,
    }
    return audit
