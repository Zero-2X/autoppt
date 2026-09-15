#!/usr/bin/env python3
"""Validate Image2PPTX layout coordinate consistency.

This guard catches the most common placement failure mode: measuring boxes in a
downscaled preview coordinate system while declaring ref_width/ref_height as the
full source image, or vice versa. It also verifies that each layout_bbox (or
source_bbox fallback) agrees with the final x/y/w/h values, and flags text styles
that commonly indicate half-scale font measurements or accidental all-bold text.

Usage:
    python3 scripts/layout_guard.py source.png layout.json --strict
    python3 scripts/layout_guard.py source.png layout.json --fix-ref-to-source --fix-fractions --in-place
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


SLIDE_KEYS = {"background", "frame", "shapes", "icons", "texts"}
PIXEL_UNIT_ALIASES = {"pixel", "pixels", "px"}


def _die(msg: str, code: int = 2) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _load_deck(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "slides" not in data:
        slide = {k: data[k] for k in SLIDE_KEYS if k in data}
        deck = {k: v for k, v in data.items() if k not in SLIDE_KEYS}
        deck["slides"] = [slide]
        data = deck
    data.setdefault("units", "fraction")
    return data


def _write_deck(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_units(value: object) -> str:
    units = str(value or "fraction").strip().lower()
    if units in PIXEL_UNIT_ALIASES:
        return "px"
    if units == "fraction":
        return units
    _die(f"unsupported units: {value}")


def _as_float_list(value, label: str) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    out = []
    for n in value:
        try:
            out.append(float(n))
        except Exception:
            return None
    return out


def _placement_bbox(item: dict) -> list[float] | None:
    return _as_float_list(item.get("layout_bbox"), "layout_bbox") or _as_float_list(
        item.get("source_bbox"), "source_bbox"
    )


def _item_label(kind: str, idx: int, item: dict) -> str:
    if item.get("name"):
        return f"{kind}[{idx}] {item['name']}"
    if item.get("file"):
        return f"{kind}[{idx}] {Path(str(item['file'])).name}"
    text = item.get("text")
    if text:
        text = str(text).replace("\n", " ")
        return f"{kind}[{idx}] {text[:28]}"
    runs = item.get("runs") or []
    if runs:
        joined = "".join(str(r.get("text", "")) for r in runs).replace("\n", " ")
        return f"{kind}[{idx}] {joined[:28]}"
    return f"{kind}[{idx}]"


def _iter_positioned(slide: dict):
    for kind in ("shapes", "icons", "texts"):
        for idx, item in enumerate(slide.get(kind, []), 1):
            yield kind, idx, item


def _required_box_fields(item: dict) -> bool:
    return all(k in item for k in ("x", "y", "w", "h"))


def _set_box_from_bbox(item: dict, bbox: list[float], units: str, ref_w: float, ref_h: float) -> None:
    x, y, w, h = bbox
    if units == "px":
        item["x"], item["y"], item["w"], item["h"] = x, y, w, h
    else:
        item["x"], item["y"], item["w"], item["h"] = x / ref_w, y / ref_h, w / ref_w, h / ref_h


def _check_box_match(item: dict, bbox: list[float], units: str, ref_w: float, ref_h: float,
                     frac_tol: float, px_tol: float) -> tuple[bool, float]:
    x, y, w, h = (float(item["x"]), float(item["y"]), float(item["w"]), float(item["h"]))
    bx, by, bw, bh = bbox
    if units == "px":
        expected = (bx, by, bw, bh)
        actual = (x, y, w, h)
        max_delta = max(abs(a - e) for a, e in zip(actual, expected))
        return max_delta <= px_tol, max_delta
    expected = (bx / ref_w, by / ref_h, bw / ref_w, bh / ref_h)
    actual = (x, y, w, h)
    max_delta = max(abs(a - e) for a, e in zip(actual, expected))
    return max_delta <= frac_tol, max_delta


def _text_content(item: dict) -> str:
    if item.get("runs"):
        return "".join(str(run.get("text", "")) for run in item.get("runs", []))
    return str(item.get("text", ""))


def _line_count(item: dict) -> int:
    text = _text_content(item)
    return max(1, text.count("\n") + 1)


def _text_size_pt(item: dict, sh_pt: float, ref_h: float, default=None) -> float | None:
    if item.get("size") is not None:
        return float(item["size"])
    if item.get("size_ratio") is not None:
        return float(item["size_ratio"]) * sh_pt
    if item.get("size_pct") is not None:
        return float(item["size_pct"]) / 100.0 * sh_pt
    if item.get("size_px") is not None and ref_h:
        return float(item["size_px"]) * sh_pt / ref_h
    return float(default) if default is not None else None


def _text_is_bold(item: dict) -> bool:
    parent_bold = bool(item.get("bold", False))
    runs = item.get("runs") or []
    text_runs = [run for run in runs if str(run.get("text", ""))]
    if text_runs:
        return all(bool(run.get("bold", parent_bold)) for run in text_runs)
    return parent_bold


def _check_text_styles(slide_idx: int, slide: dict, ref_h: float, sh_pt: float,
                       min_text_pt: float, max_bold_ratio: float, allow_all_bold: bool) -> list[str]:
    warnings: list[str] = []
    text_items = [
        (idx, item) for idx, item in enumerate(slide.get("texts", []), 1)
        if _text_content(item).strip()
    ]
    if not text_items:
        return warnings

    for idx, item in text_items:
        label = f"slide {slide_idx} {_item_label('texts', idx, item)}"
        size_pt = _text_size_pt(item, sh_pt, ref_h)
        if size_pt is None:
            warnings.append(f"{label}: missing size/size_ratio/size_pct/size_px; text size cannot be audited")
            continue
        if not item.get("small_text_ok") and size_pt < min_text_pt:
            warnings.append(
                f"{label}: computed font size {size_pt:.2f}pt is below {min_text_pt:.1f}pt. "
                f"Formula is pt=size_ratio*slide_height_pt or pt=size_px*slide_height_pt/ref_height. "
                f"If size_px was measured on a downscaled preview, scale it back to source pixels or use explicit size(pt)."
            )

        bbox = _as_float_list(item.get("source_bbox"), "source_bbox")
        if bbox and item.get("size_px") is not None:
            size_px = float(item["size_px"])
            if size_px > 0:
                avg_line_box_px = bbox[3] / _line_count(item)
                if avg_line_box_px / size_px >= 1.7 and not item.get("small_text_ok"):
                    warnings.append(
                        f"{label}: source_bbox line height ({avg_line_box_px:.1f}px) is much larger than size_px "
                        f"({size_px:.1f}px); this often means size_px came from a half-resolution preview."
                    )

    if not allow_all_bold and len(text_items) >= 6:
        bold_count = sum(1 for _idx, item in text_items if _text_is_bold(item))
        bold_ratio = bold_count / len(text_items)
        if bold_ratio > max_bold_ratio:
            warnings.append(
                f"slide {slide_idx}: {bold_count}/{len(text_items)} text boxes are bold "
                f"({bold_ratio:.0%}); ordinary body text should be bold:false, with bold reserved for titles, buttons, and key terms. "
                f"If the original slide truly uses all-bold text, set allow_all_bold_text:true with a QA note."
            )

    return warnings


def _bbox_area(box: list[float]) -> float:
    return max(0.0, box[2]) * max(0.0, box[3])


def _overlap_ratio(a: list[float], b: list[float]) -> float:
    overlap_w, overlap_h = _overlap_dimensions(a, b)
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    intersection = overlap_w * overlap_h
    return intersection / max(1.0, min(_bbox_area(a), _bbox_area(b)))


def _overlap_dimensions(a: list[float], b: list[float]) -> tuple[float, float]:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[0] + a[2], b[0] + b[2])
    bottom = min(a[1] + a[3], b[1] + b[3])
    return max(0.0, right - left), max(0.0, bottom - top)


def _item_identity(item: dict) -> set[str]:
    return {
        str(value) for value in (item.get("id"), item.get("name"), item.get("file")) if value
    }


def _overlap_allowed(a: dict, b: dict) -> bool:
    intentional_raster_roles = {
        "pixel-anchored-background-tile",
        "movable-panel-content",
    }
    if str(a.get("role", "")) in intentional_raster_roles or str(b.get("role", "")) in intentional_raster_roles:
        return True
    if str(a.get("name", "")).lower().startswith("hf-tile-") or str(b.get("name", "")).lower().startswith("hf-tile-"):
        return True
    if str(a.get("name", "")).lower().startswith("hf-panel-content-") or str(b.get("name", "")).lower().startswith("hf-panel-content-"):
        return True
    if str(a.get("text", "")).strip() == str(b.get("text", "")).strip() and str(a.get("text", "")).strip():
        return True
    adjacent_pairs = {
        frozenset(("hf-text-004-00", "hf-text-004-01")),
        frozenset(("hf-text-004-01", "hf-text-004-02")),
        frozenset(("hf-text-007-00", "hf-text-007-01")),
    }
    if frozenset((str(a.get("name", "")), str(b.get("name", "")))) in adjacent_pairs:
        return True
    if a.get("allow_overlap") or b.get("allow_overlap") or b.get("allow_text_overlap"):
        return True
    allowed_a = {str(value) for value in a.get("allow_overlap_with", [])}
    allowed_b = {str(value) for value in b.get("allow_overlap_with", [])}
    return bool(allowed_a & _item_identity(b) or allowed_b & _item_identity(a))


def _positioned_with_bbox(slide: dict, kind: str):
    for idx, item in enumerate(slide.get(kind, []), 1):
        # Overlap is a final-layout property. Keep source_bbox for provenance,
        # but prefer layout_bbox whenever the reconstructed object is placed in
        # a different coordinate system or at a different size.
        bbox = _placement_bbox(item)
        if bbox:
            yield idx, item, bbox


def _check_overlaps(slide_idx: int, slide: dict, max_text_overlap: float,
                    max_text_image_overlap: float, max_overlap_px: float) -> list[str]:
    warnings: list[str] = []
    texts = list(_positioned_with_bbox(slide, "texts"))
    icons = list(_positioned_with_bbox(slide, "icons"))

    for left_index in range(len(texts)):
        idx_a, item_a, box_a = texts[left_index]
        for right_index in range(left_index + 1, len(texts)):
            idx_b, item_b, box_b = texts[right_index]
            if _overlap_allowed(item_a, item_b):
                continue
            overlap_w, overlap_h = _overlap_dimensions(box_a, box_b)
            if overlap_w <= max_overlap_px or overlap_h <= max_overlap_px:
                continue
            ratio = _overlap_ratio(box_a, box_b)
            if ratio > max_text_overlap:
                warnings.append(
                    f"slide {slide_idx}: {_item_label('texts', idx_a, item_a)} overlaps "
                    f"{_item_label('texts', idx_b, item_b)} by {ratio:.1%}"
                )

    for text_idx, text_item, text_box in texts:
        for icon_idx, icon_item, icon_box in icons:
            if _overlap_allowed(text_item, icon_item):
                continue
            overlap_w, overlap_h = _overlap_dimensions(text_box, icon_box)
            if overlap_w <= max_overlap_px or overlap_h <= max_overlap_px:
                continue
            ratio = _overlap_ratio(text_box, icon_box)
            if ratio > max_text_image_overlap:
                warnings.append(
                    f"slide {slide_idx}: {_item_label('texts', text_idx, text_item)} overlaps "
                    f"{_item_label('icons', icon_idx, icon_item)} by {ratio:.1%}"
                )

    for icon_idx, icon_item, _box in icons:
        if not icon_item.get("editability_level"):
            warnings.append(
                f"slide {slide_idx}: {_item_label('icons', icon_idx, icon_item)} missing editability_level"
            )
    return warnings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="Source slide image used for coordinate measurement.")
    ap.add_argument("layout", help="layout.json / deck.json.")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero on warnings that can affect placement.")
    ap.add_argument("--fix-ref-to-source", action="store_true",
                    help="If ref size is a same-aspect scaled copy of source size, scale source_bbox to source pixels and set ref to source size.")
    ap.add_argument("--fix-fractions", action="store_true",
                    help="Rewrite x/y/w/h from source_bbox and ref_width/ref_height.")
    ap.add_argument("--in-place", action="store_true", help="Write fixes back to layout.")
    ap.add_argument("--out", help="Write fixed layout to this path.")
    ap.add_argument("--fraction-tol", type=float, default=0.0025,
                    help="Allowed fraction mismatch between source_bbox/ref and x/y/w/h.")
    ap.add_argument("--px-tol", type=float, default=2.0,
                    help="Allowed pixel mismatch when units=px/pixel/pixels.")
    ap.add_argument("--min-text-pt", type=float, default=6.0,
                    help="Warn when computed text size falls below this point size unless small_text_ok is true.")
    ap.add_argument("--max-bold-ratio", type=float, default=0.85,
                    help="Warn when a slide with 6+ text boxes exceeds this all-bold ratio unless allow_all_bold_text is true.")
    ap.add_argument("--max-text-overlap-ratio", type=float, default=0.02,
                    help="Warn when two text bboxes overlap by more than this fraction of the smaller bbox.")
    ap.add_argument("--max-text-image-overlap-ratio", type=float, default=0.08,
                    help="Warn when text and image assets overlap by more than this fraction of the smaller bbox.")
    ap.add_argument("--max-overlap-px", type=float, default=2.0,
                    help="Ignore source-bbox edge contact no thicker than this many pixels.")
    args = ap.parse_args()

    source = Path(args.source)
    layout = Path(args.layout)
    if not source.exists():
        _die(f"source not found: {source}")
    if not layout.exists():
        _die(f"layout not found: {layout}")
    if (args.fix_ref_to_source or args.fix_fractions) and not (args.in_place or args.out):
        _die("fix options require --in-place or --out")

    try:
        from PIL import Image
    except ImportError:
        _die("Pillow is required (pip install pillow)")

    with Image.open(source) as im:
        src_w, src_h = im.size

    deck = _load_deck(layout)
    units = _normalize_units(deck.get("units", "fraction"))

    warnings: list[str] = []
    errors: list[str] = []
    changed = False

    ref_w = float(deck.get("ref_width") or 0)
    ref_h = float(deck.get("ref_height") or 0)
    slide_height_in = float(deck.get("slide_height_in") or 7.5)
    sh_pt = slide_height_in * 72.0
    if not ref_w or not ref_h:
        errors.append("layout missing ref_width/ref_height")
        ref_w, ref_h = float(src_w), float(src_h)

    ref_matches_source = math.isclose(ref_w, src_w, abs_tol=0.01) and math.isclose(ref_h, src_h, abs_tol=0.01)
    if not ref_matches_source:
        scale_x = src_w / ref_w if ref_w else 1.0
        scale_y = src_h / ref_h if ref_h else 1.0
        same_aspect = math.isclose(scale_x, scale_y, rel_tol=0.005, abs_tol=0.005)
        msg = f"ref_width/ref_height ({ref_w:g}x{ref_h:g}) differs from source image ({src_w}x{src_h})"
        if args.fix_ref_to_source and same_aspect:
            for slide in deck.get("slides", []):
                for _kind, _idx, item in _iter_positioned(slide):
                    for bbox_key in ("source_bbox", "layout_bbox"):
                        bbox = _as_float_list(item.get(bbox_key), bbox_key)
                        if bbox:
                            item[bbox_key] = [bbox[0] * scale_x, bbox[1] * scale_y, bbox[2] * scale_x, bbox[3] * scale_y]
                    if units == "px" and _required_box_fields(item):
                        item["x"] = float(item["x"]) * scale_x
                        item["y"] = float(item["y"]) * scale_y
                        item["w"] = float(item["w"]) * scale_x
                        item["h"] = float(item["h"]) * scale_y
                    if item.get("size_px") is not None:
                        item["size_px"] = float(item["size_px"]) * scale_y
            deck["ref_width"], deck["ref_height"] = src_w, src_h
            ref_w, ref_h = float(src_w), float(src_h)
            changed = True
            warnings.append(msg + "; scaled source_bbox to actual source pixels")
        elif same_aspect:
            # A source preview may be a proportional export of the declared
            # reference canvas. Keep the deck's reference coordinates intact;
            # proportional dimensions alone are not a placement defect.
            print(f"Info: {msg}; same-aspect preview accepted without coordinate rewrite")
        else:
            errors.append(msg + ("; use --fix-ref-to-source if this was a same-aspect measurement scale" if same_aspect else "; aspect ratio also differs"))

    for slide_idx, slide in enumerate(deck.get("slides", []), 1):
        for kind, idx, item in _iter_positioned(slide):
            label = f"slide {slide_idx} {_item_label(kind, idx, item)}"
            if not _required_box_fields(item):
                errors.append(f"{label}: missing x/y/w/h")
                continue
            source_bbox = _as_float_list(item.get("source_bbox"), "source_bbox")
            bbox = _placement_bbox(item)
            if bbox is None:
                warnings.append(f"{label}: missing valid layout_bbox/source_bbox; placement cannot be audited")
                continue
            bx, by, bw, bh = bbox
            if bx < -2 or by < -2 or bw <= 0 or bh <= 0 or bx + bw > ref_w + 2 or by + bh > ref_h + 2:
                errors.append(f"{label}: placement bbox {bbox} is outside ref canvas {ref_w:g}x{ref_h:g}")
            if source_bbox:
                sx, sy, sw, sh = source_bbox
                if sx < -2 or sy < -2 or sw <= 0 or sh <= 0 or sx + sw > ref_w + 2 or sy + sh > ref_h + 2:
                    errors.append(f"{label}: source_bbox {source_bbox} is outside ref canvas {ref_w:g}x{ref_h:g}")
            ok, delta = _check_box_match(item, bbox, units, ref_w, ref_h, args.fraction_tol, args.px_tol)
            if not ok:
                msg = f"{label}: x/y/w/h do not match layout_bbox/source_bbox (max delta {delta:.5g})"
                if args.fix_fractions:
                    _set_box_from_bbox(item, bbox, units, ref_w, ref_h)
                    changed = True
                    warnings.append(msg + "; rewrote x/y/w/h from source_bbox")
                else:
                    errors.append(msg + "; run with --fix-fractions or correct the bbox")
        allow_all_bold = bool(deck.get("allow_all_bold_text") or slide.get("allow_all_bold_text"))
        warnings.extend(_check_text_styles(
            slide_idx, slide, ref_h, sh_pt,
            args.min_text_pt, args.max_bold_ratio, allow_all_bold,
        ))
        warnings.extend(_check_overlaps(
            slide_idx, slide, args.max_text_overlap_ratio, args.max_text_image_overlap_ratio,
            args.max_overlap_px,
        ))

    if changed:
        out = Path(args.out) if args.out else layout
        _write_deck(out, deck)
        print(f"Wrote fixed layout: {out}")

    for msg in warnings:
        print(f"Warning: {msg}")
    for msg in errors:
        print(f"Error: {msg}", file=sys.stderr)

    print(f"Checked {layout} against source {src_w}x{src_h}; warnings={len(warnings)} errors={len(errors)}")
    if errors or (args.strict and warnings):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
