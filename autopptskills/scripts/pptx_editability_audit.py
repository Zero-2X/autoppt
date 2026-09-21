#!/usr/bin/env python3
"""Audit editability, Unicode text, and image-layer overuse in a PPTX."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


GRADE_ORDER = {"visual-only": 0, "mixed": 1, "editable": 2}
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def shape_box_fraction(shape, slide_w: int, slide_h: int) -> float:
    try:
        return max(0.0, (int(shape.width) * int(shape.height)) / float(slide_w * slide_h))
    except Exception:
        return 0.0


def _is_background_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in {"imagegen-background", "slide-background", "ambient-background", "paper-texture"}


def _picture_role(name: str) -> str:
    """Classify generated reconstruction pictures by their stable semantic name."""
    lowered = name.lower()
    if lowered.startswith("hf-tile-"):
        return "pixel-anchored-background-tile"
    if lowered.startswith("hf-panel-content-"):
        return "movable-panel-content"
    return "semantic-raster"


def visible_text_reasons(shape, slide_w: int, slide_h: int) -> list[str]:
    """Reject proxy text; presence in slide XML is not visible editability."""
    reasons = []
    if (shape.left < 0 or shape.top < 0 or shape.left + shape.width > slide_w + 12700
            or shape.top + shape.height > slide_h + 12700):
        reasons.append("outside-slide")
    if shape.width <= 0 or shape.height <= 0:
        reasons.append("empty-frame")
    if "proxy" in shape.name.lower():
        reasons.append("proxy-object")
    for p in shape.text_frame.paragraphs:
        for run in p.runs:
            if not run.text.strip():
                continue
            if run.font.size is not None and run.font.size.pt < 5:
                reasons.append("tiny-text")
            if any(int(a.get("val", "100000")) == 0 for a in run._r.xpath(".//a:alpha")):
                reasons.append("transparent-text")
    return sorted(set(reasons))


def _xml_text_evidence(path: Path) -> dict:
    xml_text = ""
    with zipfile.ZipFile(path) as zf:
        slide_names = sorted(
            name for name in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        )
        for name in slide_names:
            xml_text += zf.read(name).decode("utf-8", errors="replace")
        media = [name for name in zf.namelist() if name.startswith("ppt/media/")]
    return {
        "slide_xml_count": len(slide_names),
        "xml_has_cjk": bool(CJK_RE.search(xml_text)),
        "xml_cjk_character_count": len(CJK_RE.findall(xml_text)),
        "replacement_character_count": xml_text.count("\ufffd"),
        "media_count": len(media),
        "svg_media_count": sum(1 for name in media if name.lower().endswith(".svg")),
    }


def audit(path: Path, full_slide_threshold: float) -> dict:
    prs = Presentation(path)
    slide_w = int(prs.slide_width)
    slide_h = int(prs.slide_height)
    slides = []
    totals = {
        "slides": len(prs.slides),
        "pictures": 0,
        "background_pictures": 0,
        "background_tile_pictures": 0,
        "semantic_pictures": 0,
        "complex_raster_pictures": 0,
        "convertible_vectors": 0,
        "movable_pictures": 0,
        "native_vector_shapes": 0,
        "full_slide_pictures": 0,
        "semantic_full_slide_pictures": 0,
        "text_boxes": 0,
        "invalid_text_objects": 0,
        "native_shapes": 0,
        "connectors": 0,
        "text_items": 0,
        "cjk_characters": 0,
        "picture_area_ratio_sum": 0.0,
        "background_tile_area_ratio_sum": 0.0,
        "complex_raster_area_ratio_sum": 0.0,
        "semantic_picture_area_ratio_sum": 0.0,
        "native_shape_area_ratio_sum": 0.0,
        "text_area_ratio_sum": 0.0,
    }

    for slide_index, slide in enumerate(prs.slides, 1):
        item = {
            "slide": slide_index,
            "pictures": 0,
            "background_pictures": 0,
            "background_tile_pictures": 0,
            "semantic_pictures": 0,
            "complex_raster_pictures": 0,
            "convertible_vectors": 0,
            "movable_pictures": 0,
            "native_vector_shapes": 0,
            "full_slide_pictures": 0,
            "semantic_full_slide_pictures": 0,
            "text_boxes": 0,
            "invalid_text_objects": 0,
            "native_shapes": 0,
            "connectors": 0,
            "picture_area_ratio_sum": 0.0,
            "background_tile_area_ratio_sum": 0.0,
            "complex_raster_area_ratio_sum": 0.0,
            "semantic_picture_area_ratio_sum": 0.0,
            "native_shape_area_ratio_sum": 0.0,
            "text_area_ratio_sum": 0.0,
            "texts": [],
            "objects": [],
        }
        for shape_index, shape in enumerate(slide.shapes, 1):
            shape_type = shape.shape_type
            name = str(getattr(shape, "name", "") or f"shape-{shape_index}")
            text = getattr(shape, "text", "") if getattr(shape, "has_text_frame", False) else ""
            area = shape_box_fraction(shape, slide_w, slide_h)
            object_info = {
                "name": name,
                "shape_type": str(shape_type),
                "area_ratio": round(area, 6),
                "has_text": bool(text.strip()),
            }

            if shape_type == MSO_SHAPE_TYPE.PICTURE:
                item["pictures"] += 1
                totals["pictures"] += 1
                item["picture_area_ratio_sum"] += area
                totals["picture_area_ratio_sum"] += area
                is_full = area >= full_slide_threshold
                picture_role = _picture_role(name)
                is_background_tile = picture_role == "pixel-anchored-background-tile"
                # Position in z-order cannot prove that an image is non-semantic.
                # Named backgrounds still require the separate layer review.
                is_background = _is_background_name(name) or is_background_tile
                is_vector = name.lower().startswith("vector-svg::")
                if is_background:
                    item["background_pictures"] += 1
                    totals["background_pictures"] += 1
                    if is_background_tile:
                        item["background_tile_pictures"] += 1
                        totals["background_tile_pictures"] += 1
                        item["background_tile_area_ratio_sum"] += area
                        totals["background_tile_area_ratio_sum"] += area
                elif is_vector:
                    item["convertible_vectors"] += 1
                    totals["convertible_vectors"] += 1
                else:
                    item["semantic_pictures"] += 1
                    totals["semantic_pictures"] += 1
                    item["movable_pictures"] += 1
                    totals["movable_pictures"] += 1
                    item["semantic_picture_area_ratio_sum"] += area
                    totals["semantic_picture_area_ratio_sum"] += area
                    if picture_role == "movable-panel-content":
                        item["complex_raster_pictures"] += 1
                        totals["complex_raster_pictures"] += 1
                        item["complex_raster_area_ratio_sum"] += area
                        totals["complex_raster_area_ratio_sum"] += area
                if is_full:
                    item["full_slide_pictures"] += 1
                    totals["full_slide_pictures"] += 1
                    if not is_background:
                        item["semantic_full_slide_pictures"] += 1
                        totals["semantic_full_slide_pictures"] += 1
            elif shape_type == MSO_SHAPE_TYPE.LINE or "connector" in name.lower():
                item["connectors"] += 1
                totals["connectors"] += 1
            elif shape_type == MSO_SHAPE_TYPE.TEXT_BOX or text.strip():
                invalid = visible_text_reasons(shape, slide_w, slide_h)
                if invalid:
                    item["invalid_text_objects"] += 1
                    totals["invalid_text_objects"] += 1
                    object_info["visibility_errors"] = invalid
                    item["objects"].append(object_info)
                    continue
                item["text_boxes"] += 1
                totals["text_boxes"] += 1
                item["text_area_ratio_sum"] += area
                totals["text_area_ratio_sum"] += area
            else:
                item["native_shapes"] += 1
                totals["native_shapes"] += 1
                if name.lower().startswith("native-vector::"):
                    item["native_vector_shapes"] += 1
                    totals["native_vector_shapes"] += 1
                item["native_shape_area_ratio_sum"] += area
                totals["native_shape_area_ratio_sum"] += area

            if text.strip():
                item["texts"].append(text)
                totals["text_items"] += 1
                totals["cjk_characters"] += len(CJK_RE.findall(text))
            item["objects"].append(object_info)

        for key in (
            "picture_area_ratio_sum",
            "background_tile_area_ratio_sum",
            "complex_raster_area_ratio_sum",
            "semantic_picture_area_ratio_sum",
            "native_shape_area_ratio_sum",
            "text_area_ratio_sum",
        ):
            item[key] = round(item[key], 4)
        slides.append(item)

    native_count = totals["text_boxes"] + totals["native_shapes"] + totals["connectors"]
    semantic_object_count = native_count + totals["convertible_vectors"] + totals["semantic_pictures"]
    raw_native_object_ratio = native_count / max(1, semantic_object_count)
    # A bounded panel crop is movable and crop-able in PowerPoint, but its
    # internal pixels are not path-editable. Give it limited editability credit
    # while keeping the raw native ratio visible in the report.
    editable_equivalent = (
        native_count
        + totals["convertible_vectors"] * 0.8
        + totals["complex_raster_pictures"] * 0.35
    )
    object_editability = editable_equivalent / max(1, semantic_object_count)
    semantic_picture_pressure = min(1.0, totals["complex_raster_area_ratio_sum"] / max(1, totals["slides"]))
    text_signal = 1.0 if totals["text_boxes"] > 0 else 0.0
    score = round(100 * (0.60 * object_editability + 0.25 * (1 - semantic_picture_pressure) + 0.15 * text_signal), 1)

    picture_area = max(1e-9, totals["picture_area_ratio_sum"])
    # Every visible semantic text object in this deck is native PowerPoint text.
    # Keep this as a hard, machine-checkable signal: the release gate must not
    # infer editability from a few proxy boxes or from an object-count ratio.
    visible_text_objects = totals["text_boxes"] + totals["invalid_text_objects"]
    native_text_coverage = (
        totals["text_boxes"] / max(1, visible_text_objects)
        if visible_text_objects
        else 0.0
    )
    native_shape_coverage = (
        (totals["native_shapes"] + totals["connectors"])
        / max(1, totals["native_shapes"] + totals["connectors"] + totals["convertible_vectors"])
    )
    complex_raster_exception_ratio = totals["complex_raster_area_ratio_sum"] / picture_area
    full_slide_raster_shortcut = totals["semantic_full_slide_pictures"] > 0

    if totals["semantic_full_slide_pictures"] > 0 or native_count == 0:
        grade = "visual-only"
    elif score >= 65 and semantic_picture_pressure <= 0.45 and totals["text_boxes"] > 0 and (totals["native_shapes"] + totals["connectors"]) > 0:
        grade = "editable"
    else:
        grade = "mixed"

    for key in (
        "picture_area_ratio_sum",
        "background_tile_area_ratio_sum",
        "complex_raster_area_ratio_sum",
        "semantic_picture_area_ratio_sum",
        "native_shape_area_ratio_sum",
        "text_area_ratio_sum",
    ):
        totals[key] = round(totals[key], 4)

    return {
        "pptx": str(path),
        "totals": totals,
        "editability": {
            "score": score,
            "grade": grade,
            "native_object_ratio": round(raw_native_object_ratio, 4),
            "tier_adjusted_object_ratio": round(object_editability, 4),
            "semantic_picture_pressure": round(semantic_picture_pressure, 4),
            "native_text_coverage": round(native_text_coverage, 4),
            "visible_text_objects": visible_text_objects,
            "coverage_requires": "all visible semantic text must be native and in-bounds",
            "native_shape_coverage": round(native_shape_coverage, 4),
            "complex_raster_exception_ratio": round(complex_raster_exception_ratio, 4),
            "full_slide_raster_shortcut": full_slide_raster_shortcut,
            "level_notes": {
                "native": "PowerPoint text, shapes, and connectors",
                "convertible-vector": "SVG/EMF requires separate manifest evidence",
                "pixel-anchored-background-tile": "high-fidelity background tile; excluded from semantic raster pressure",
                "movable-panel-content": "bounded complex raster exception; movable but not path-editable",
                "movable-image": "separate semantic pictures",
                "visual-only": "semantic full-slide pictures",
            },
        },
        "unicode": _xml_text_evidence(path),
        "slides": slides,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx")
    parser.add_argument("--min-text-boxes", type=int, default=0)
    parser.add_argument("--min-native-shapes", type=int, default=0)
    parser.add_argument("--min-convertible-vectors", type=int, default=0)
    parser.add_argument("--max-full-slide-pictures", type=int, default=999)
    parser.add_argument("--max-background-tile-pictures", type=int, default=0)
    parser.add_argument("--max-semantic-full-slide-pictures", type=int, default=0)
    parser.add_argument("--full-slide-threshold", type=float, default=0.90)
    parser.add_argument("--min-grade", choices=GRADE_ORDER, default="visual-only")
    parser.add_argument("--json-out", help="Optional JSON report path.")
    args = parser.parse_args()

    report = audit(Path(args.pptx), args.full_slide_threshold)
    failures = []
    totals = report["totals"]
    if totals["invalid_text_objects"]:
        failures.append("invalid_text_objects>0")
    if totals["text_boxes"] < args.min_text_boxes:
        failures.append(f"text_boxes<{args.min_text_boxes}")
    if totals["native_shapes"] + totals["connectors"] < args.min_native_shapes:
        failures.append(f"native_shapes<{args.min_native_shapes}")
    if totals["convertible_vectors"] < args.min_convertible_vectors:
        failures.append(f"convertible_vectors<{args.min_convertible_vectors}")
    if totals["full_slide_pictures"] > args.max_full_slide_pictures:
        failures.append(f"full_slide_pictures>{args.max_full_slide_pictures}")
    if totals["background_tile_pictures"] > args.max_background_tile_pictures:
        failures.append(f"background_tile_pictures>{args.max_background_tile_pictures}")
    if totals["semantic_full_slide_pictures"] > args.max_semantic_full_slide_pictures:
        failures.append(f"semantic_full_slide_pictures>{args.max_semantic_full_slide_pictures}")
    if GRADE_ORDER[report["editability"]["grade"]] < GRADE_ORDER[args.min_grade]:
        failures.append(f"grade<{args.min_grade}")
    if report["unicode"]["replacement_character_count"]:
        failures.append("unicode_replacement_characters>0")
    report["failures"] = failures
    report["verdict"] = "pass" if not failures else "fail"

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
