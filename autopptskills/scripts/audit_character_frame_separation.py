#!/usr/bin/env python3
"""Audit character, frame, and background separation readiness for a deck run.

The audit is deliberately conservative. OCR geometry is treated as evidence,
not as an editable layout decision. In particular, ``ocr_bbox`` is preferred
as the visible-glyph box when a larger container-aligned ``source_bbox`` was
written by an older reconstruction pass.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def bbox_area(value: Any) -> float:
    if not isinstance(value, list) or len(value) != 4:
        return 0.0
    try:
        return max(0.0, float(value[2])) * max(0.0, float(value[3]))
    except (TypeError, ValueError):
        return 0.0


def intersection_ratio(left: list[float], right: list[float]) -> float:
    lx, ly, lw, lh = map(float, left)
    rx, ry, rw, rh = map(float, right)
    x0, y0 = max(lx, rx), max(ly, ry)
    x1, y1 = min(lx + lw, rx + rw), min(ly + lh, ry + rh)
    overlap = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return overlap / max(1.0, min(lw * lh, rw * rh))


def normalized_text(value: str) -> str:
    return "".join(str(value).split()).replace("，", ",").replace("：", ":")


def route_text(item: dict[str, Any]) -> str:
    if bool(item.get("art_text")):
        return "vector-glyph"
    size = float(item.get("size", 0) or 0)
    if size >= 38 and bool(item.get("bold")) and not item.get("container_shape_id"):
        return "vector-glyph-candidate"
    return "native-text"


def audit_slide(
    slide_id: str,
    analysis_path: Path,
    exact_text: list[str],
) -> dict[str, Any]:
    analysis = read_json(analysis_path)
    shapes = analysis.get("shapes", [])
    icons = analysis.get("icon_candidates", [])
    lines = analysis.get("lines", [])
    text_rows: list[dict[str, Any]] = []
    observed = set()
    container_bbox_count = 0
    art_count = 0
    needs_review_count = 0
    for item in analysis.get("texts", []):
        source_bbox = item.get("source_bbox") or item.get("bbox")
        ocr_bbox = item.get("ocr_bbox")
        glyph_bbox = ocr_bbox or source_bbox
        source_area = bbox_area(source_bbox)
        glyph_area = bbox_area(glyph_bbox)
        expansion = source_area / max(1.0, glyph_area)
        container_level = bool(item.get("container_shape_id")) and expansion >= 1.45
        container_level = container_level or expansion >= 2.25
        container_bbox_count += int(container_level)
        art_count += int(bool(item.get("art_text")))
        needs_review_count += int(bool(item.get("needs_review")))
        overlaps = {
            "shape": max(
                [intersection_ratio(glyph_bbox, row.get("source_bbox") or row.get("bbox")) for row in shapes]
                or [0.0]
            ),
            "icon": max(
                [intersection_ratio(glyph_bbox, row.get("source_bbox") or row.get("bbox")) for row in icons]
                or [0.0]
            ),
        }
        text = str(item.get("text", ""))
        observed.add(normalized_text(text))
        route = route_text(item)
        stable_font = route == "native-text"
        text_rows.append(
            {
                "id": item.get("id"),
                "text": text,
                "confidence": item.get("confidence"),
                "source_bbox": source_bbox,
                "ocr_bbox": ocr_bbox,
                "glyph_bbox": glyph_bbox,
                "layout_bbox": item.get("layout_bbox"),
                "container_shape_id": item.get("container_shape_id"),
                "source_to_glyph_area_ratio": round(expansion, 4),
                "container_level_bbox": container_level,
                "art_text": bool(item.get("art_text")),
                "needs_review": bool(item.get("needs_review")),
                "replacement_character_count": text.count("\ufffd"),
                "overlap_with_shape": round(overlaps["shape"], 4),
                "overlap_with_icon": round(overlaps["icon"], 4),
                "font_mapping": "stable-native" if stable_font else "unstable-stylized",
                "route": route,
                "cleanup_mask_status": "missing",
            }
        )

    missing_exact = [
        token for token in exact_text if normalized_text(token) not in observed
    ]
    routed_lines = [row for row in lines if row.get("requires_background_cleanup")]
    failed_line_cleanup = [
        row for row in routed_lines if row.get("cleanup_evidence", {}).get("status") != "pass"
    ]
    return {
        "slide_id": slide_id,
        "analysis": str(analysis_path.resolve()),
        "text_count": len(text_rows),
        "exact_text_count": len(exact_text),
        "exact_text_missing_from_ocr": missing_exact,
        "container_level_text_boxes": container_bbox_count,
        "art_text_count": art_count,
        "needs_review_text_count": needs_review_count,
        "shape_count": len(shapes),
        "line_count": len(lines),
        "routed_line_count": len(routed_lines),
        "failed_line_cleanup_count": len(failed_line_cleanup),
        "icon_candidate_count": len(icons),
        "texts": text_rows,
        "blocking_issues": [
            issue
            for issue, present in (
                ("missing-exact-text-routing", bool(missing_exact)),
                ("container-bbox-used-as-glyph-bbox", container_bbox_count > 0),
                ("text-cleanup-mask-missing", bool(text_rows)),
                ("selected-line-cleanup-not-proven", bool(failed_line_cleanup)),
            )
            if present
        ],
    }


def build_audit(workspace: Path) -> dict[str, Any]:
    scripts = read_json(workspace / "slide-scripts.json")
    if isinstance(scripts, dict):
        scripts = scripts.get("slides", [])
    exact_by_slide = {
        str(item["slide_id"]): list(item.get("exact_text", [])) for item in scripts
    }
    slides = []
    for analysis_path in sorted(
        (workspace / "reconstruction").glob("S??/analysis/analysis.json")
    ):
        slide_id = analysis_path.parents[1].name
        slides.append(
            audit_slide(slide_id, analysis_path, exact_by_slide.get(slide_id, []))
        )
    route_counts: dict[str, int] = {}
    for slide in slides:
        for row in slide["texts"]:
            route_counts[row["route"]] = route_counts.get(row["route"], 0) + 1
    blocking_slides = [row["slide_id"] for row in slides if row["blocking_issues"]]
    return {
        "schema_version": 1,
        "workspace": str(workspace.resolve()),
        "slide_count": len(slides),
        "route_counts": route_counts,
        "totals": {
            "texts": sum(row["text_count"] for row in slides),
            "exact_text_entries": sum(row["exact_text_count"] for row in slides),
            "container_level_text_boxes": sum(row["container_level_text_boxes"] for row in slides),
            "art_texts": sum(row["art_text_count"] for row in slides),
            "shapes": sum(row["shape_count"] for row in slides),
            "lines": sum(row["line_count"] for row in slides),
            "icons": sum(row["icon_candidate_count"] for row in slides),
        },
        "blocking_slide_count": len(blocking_slides),
        "blocking_slides": blocking_slides,
        "verdict": "blocked" if blocking_slides else "pass",
        "slides": slides,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_audit(Path(args.workspace).resolve())
    write_json(Path(args.out).resolve(), report)
    print(json.dumps({
        "slides": report["slide_count"],
        "texts": report["totals"]["texts"],
        "container_level_text_boxes": report["totals"]["container_level_text_boxes"],
        "verdict": report["verdict"],
        "out": str(Path(args.out).resolve()),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
