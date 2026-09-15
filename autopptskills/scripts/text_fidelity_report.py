#!/usr/bin/env python3
"""Measure text-object fidelity against source slide images and PowerPoint renders.

This is a diagnostic/release-support tool for editable reconstructions.  It
does not infer that a declared font is visually identical; instead it records
the declared typography, the authored PowerPoint frame extracted from slide
XML, and a spatial local-pixel comparison at the source text region.  The
report is intentionally per-object so a whole-slide mean cannot hide a bad
title wrap or a shifted card label.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import zipfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops, ImageDraw
import numpy as np


NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
EMU_PER_IN = 914400.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compact(value: Any) -> str:
    return re.sub(r"[\s，。；：、,.!?！？·•]+", "", str(value or "")).lower()


def bbox_area(box: list[float] | None) -> float:
    return float(box[2] * box[3]) if box and len(box) == 4 else 0.0


def valid_bbox(box: Any) -> bool:
    return isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box) and box[2] > 0 and box[3] > 0


def item_bbox(item: dict[str, Any]) -> list[float] | None:
    for key in ("source_bbox", "layout_bbox"):
        value = item.get(key)
        if valid_bbox(value):
            return [float(v) for v in value]
    values = [item.get(key) for key in ("x", "y", "w", "h")]
    return [float(v) for v in values] if valid_bbox(values) else None


def slide_id_for(index: int) -> str:
    return f"S{index:02d}"


def extract_text_shapes(pptx: Path, slide_count: int, slide_cx: float, slide_cy: float, ref_w: float, ref_h: float) -> list[list[dict[str, Any]]]:
    """Extract text boxes and run properties from PPTX slide XML."""
    slides: list[list[dict[str, Any]]] = []
    with zipfile.ZipFile(pptx) as archive:
        for index in range(1, slide_count + 1):
            name = f"ppt/slides/slide{index}.xml"
            try:
                root = ET.fromstring(archive.read(name))
            except KeyError:
                slides.append([])
                continue
            rows: list[dict[str, Any]] = []
            for shape in root.findall(".//p:sp", NS):
                tx_body = shape.find("p:txBody", NS)
                if tx_body is None:
                    continue
                texts = [node.text or "" for node in tx_body.findall(".//a:t", NS)]
                text = "".join(texts)
                if not text.strip():
                    continue
                xfrm = shape.find("p:spPr/a:xfrm", NS)
                # Text-box transforms are normally in p:spPr/a:xfrm.
                if xfrm is None:
                    xfrm = shape.find("p:txBody/a:bodyPr/../a:xfrm", NS)
                off = xfrm.find("a:off", NS) if xfrm is not None else None
                ext = xfrm.find("a:ext", NS) if xfrm is not None else None
                if off is None or ext is None:
                    continue
                x_emu, y_emu = float(off.attrib.get("x", 0)), float(off.attrib.get("y", 0))
                w_emu, h_emu = float(ext.attrib.get("cx", 0)), float(ext.attrib.get("cy", 0))
                bbox = [x_emu / slide_cx * ref_w, y_emu / slide_cy * ref_h, w_emu / slide_cx * ref_w, h_emu / slide_cy * ref_h]
                paragraphs = tx_body.findall("a:p", NS)
                line_count = max(1, len(paragraphs))
                ppr = paragraphs[0].find("a:pPr", NS) if paragraphs else None
                alignment = (ppr.attrib.get("algn") if ppr is not None else None) or "left"
                alignment = {"l": "left", "ctr": "center", "r": "right", "just": "justify"}.get(alignment, alignment)
                runs: list[dict[str, Any]] = []
                sizes: list[float] = []
                fonts: list[str] = []
                bold_values: list[bool] = []
                italic_values: list[bool] = []
                for run in tx_body.findall(".//a:r", NS):
                    rpr = run.find("a:rPr", NS)
                    run_text = "".join(node.text or "" for node in run.findall("a:t", NS))
                    if rpr is None:
                        rpr = run.find("a:endParaRPr", NS)
                    size_pt = None
                    font = None
                    bold = False
                    italic = False
                    if rpr is not None:
                        if rpr.attrib.get("sz"):
                            size_pt = float(rpr.attrib["sz"]) / 100.0
                        bold = str(rpr.attrib.get("b", "0")).lower() in {"1", "true"}
                        italic = str(rpr.attrib.get("i", "0")).lower() in {"1", "true"}
                        latin = rpr.find("a:latin", NS)
                        east = rpr.find("a:ea", NS)
                        font_node = latin if latin is not None else east
                        if font_node is not None:
                            font = font_node.attrib.get("typeface")
                    if size_pt is not None:
                        sizes.append(size_pt)
                    if font:
                        fonts.append(font)
                    bold_values.append(bold)
                    italic_values.append(italic)
                    runs.append({"text": run_text, "font_size_pt": size_pt, "font_name": font, "bold": bold, "italic": italic})
                rows.append({
                    "text": text,
                    "compact_text": compact(text),
                    "render_bbox": [round(v, 3) for v in bbox],
                    "font_name": fonts[0] if fonts else None,
                    "font_size_pt": round(sum(sizes) / len(sizes), 3) if sizes else None,
                    "bold": any(bold_values),
                    "italic": any(italic_values),
                    "alignment": alignment,
                    "line_count": line_count,
                    "runs": runs,
                })
            slides.append(rows)
    return slides


def nearest_render_item(item: dict[str, Any], candidates: list[dict[str, Any]], used: set[int]) -> tuple[int | None, dict[str, Any] | None]:
    target = compact(item.get("text"))
    exact = [(idx, row) for idx, row in enumerate(candidates) if idx not in used and row.get("compact_text") == target]
    pool = exact or [(idx, row) for idx, row in enumerate(candidates) if idx not in used]
    if not pool:
        return None, None
    source = item_bbox(item) or [0, 0, 1, 1]
    sx, sy = source[0] + source[2] / 2.0, source[1] + source[3] / 2.0
    def distance(pair: tuple[int, dict[str, Any]]) -> float:
        box = pair[1].get("render_bbox") or [0, 0, 1, 1]
        cx, cy = box[0] + box[2] / 2.0, box[1] + box[3] / 2.0
        return math.hypot(cx - sx, cy - sy)
    idx, row = min(pool, key=distance)
    return idx, row


def _mask_bbox(image: Image.Image, background: Image.Image | None, threshold: int = 18) -> list[int] | None:
    """Find local ink/change bounds. Background subtraction is preferred."""
    arr = np.asarray(image.convert("RGB"), dtype=np.int16)
    if background is not None:
        bg = np.asarray(background.convert("RGB").resize(image.size), dtype=np.int16)
        delta = np.max(np.abs(arr - bg), axis=2)
        mask = delta >= threshold
    else:
        gray = arr.mean(axis=2)
        mask = np.abs(gray - np.median(gray)) >= threshold
    # Remove isolated antialiasing specks while preserving thin CJK strokes.
    ys, xs = np.where(mask)
    if len(xs) < 4:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)]


def crop_metrics(source: Image.Image, render: Image.Image, background: Image.Image | None, box: list[float], ref_size: tuple[int, int], out_dir: Path, stem: str) -> dict[str, Any]:
    pad = max(4, int(round(max(box[2], box[3]) * 0.12)))
    x, y, w, h = box
    sx = source.width / ref_size[0]
    sy = source.height / ref_size[1]
    left = max(0, int(math.floor((x - pad) * sx)))
    top = max(0, int(math.floor((y - pad) * sy)))
    right = min(source.width, int(math.ceil((x + w + pad) * sx)))
    bottom = min(source.height, int(math.ceil((y + h + pad) * sy)))
    src_crop = source.crop((left, top, right, bottom)).convert("RGB")
    bg_crop = background.crop((left, top, right, bottom)).convert("RGB") if background is not None else None
    # Render is compared at the same spatial location, scaled to source crop.
    rx1 = max(0, int(round(left / source.width * render.width)))
    ry1 = max(0, int(round(top / source.height * render.height)))
    rx2 = min(render.width, int(round(right / source.width * render.width)))
    ry2 = min(render.height, int(round(bottom / source.height * render.height)))
    render_crop = render.crop((rx1, ry1, rx2, ry2)).convert("RGB").resize(src_crop.size)
    diff = ImageChops.difference(src_crop, render_crop)
    px = list(diff.convert("L").getdata())
    mean_abs = sum(px) / max(1, len(px))
    rms = math.sqrt(sum(v * v for v in px) / max(1, len(px)))
    src_crop.save(out_dir / f"{stem}-source.png")
    render_crop.save(out_dir / f"{stem}-render.png")
    diff.save(out_dir / f"{stem}-diff.png")
    side = Image.new("RGB", (src_crop.width * 2, src_crop.height), "white")
    side.paste(src_crop, (0, 0))
    side.paste(render_crop, (src_crop.width, 0))
    side.save(out_dir / f"{stem}-side-by-side.png")
    src_ink = _mask_bbox(src_crop, bg_crop)
    ren_ink = _mask_bbox(render_crop, bg_crop)
    def to_ref(local: list[int] | None) -> list[float] | None:
        if not local:
            return None
        return [
            round(left / sx + local[0] / sx, 3),
            round(top / sy + local[1] / sy, 3),
            round((local[2] - local[0]) / sx, 3),
            round((local[3] - local[1]) / sy, 3),
        ]
    return {
        "source_crop": str(out_dir / f"{stem}-source.png"),
        "render_crop": str(out_dir / f"{stem}-render.png"),
        "diff_crop": str(out_dir / f"{stem}-diff.png"),
        "side_by_side": str(out_dir / f"{stem}-side-by-side.png"),
        "mean_abs_diff_0_255": round(mean_abs, 4),
        "rms_diff_0_255": round(rms, 4),
        "crop_size": list(src_crop.size),
        "source_glyph_bbox": to_ref(src_ink),
        "render_glyph_bbox": to_ref(ren_ink),
    }


def compare_decks(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    if not baseline:
        return {"status": "not_required", "regressions": []}
    rows: list[dict[str, Any]] = []
    regressions: list[str] = []
    base_map = {(str(row.get("slide_id")), str(row.get("text_id"))): row for row in baseline.get("items", [])}
    for row in current.get("items", []):
        key = (str(row.get("slide_id")), str(row.get("text_id")))
        prev = base_map.get(key)
        if not prev:
            continue
        cur_diff = float(row.get("local_pixel", {}).get("mean_abs_diff_0_255") or 0)
        prev_diff = float(prev.get("local_pixel", {}).get("mean_abs_diff_0_255") or 0)
        pos = float(row.get("position_delta_px") or 0)
        prev_pos = float(prev.get("position_delta_px") or 0)
        size = float(row.get("size_delta_px") or 0)
        prev_size = float(prev.get("size_delta_px") or 0)
        regressed = cur_diff > prev_diff + 0.25 or pos > prev_pos + 1.0 or size > prev_size + 1.0
        if regressed:
            regressions.append(str(row.get("slide_id")))
        rows.append({"slide_id": row.get("slide_id"), "text_id": row.get("text_id"), "status": "fail" if regressed else "pass", "pixel_delta": round(cur_diff - prev_diff, 4), "position_delta_delta": round(pos - prev_pos, 4), "size_delta_delta": round(size - prev_size, 4)})
    return {"status": "fail" if regressions else "pass", "regressions": sorted(set(regressions)), "items": rows}


def build_report(deck_path: Path, pptx: Path, source_dir: Path, render_dir: Path, out_path: Path, baseline_path: Path | None = None) -> dict[str, Any]:
    deck = read_json(deck_path)
    ref_w = float(deck.get("ref_width") or 1672)
    ref_h = float(deck.get("ref_height") or 941)
    slide_cx = float(deck.get("slide_width_emu") or 12192000)
    slide_cy = float(deck.get("slide_height_emu") or 6858000)
    # 16:9 deck defaults if no EMU fields are stored.
    slide_cx = slide_cx if slide_cx > 0 else 13.333333 * EMU_PER_IN
    slide_cy = slide_cy if slide_cy > 0 else 7.5 * EMU_PER_IN
    slides = deck.get("slides") or []
    xml_slides = extract_text_shapes(pptx, len(slides), slide_cx, slide_cy, ref_w, ref_h)
    crop_dir = out_path.parent / "text-crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    missing = 0
    for index, slide in enumerate(slides, 1):
        sid = str(slide.get("slide_id") or slide_id_for(index))
        source_path = source_dir / "assets" / "slides" / f"{sid}.png"
        background_path = Path(str((slide.get("background") or ""))).expanduser()
        if not background_path.is_absolute():
            background_path = Path(str(deck.get("assets_dir") or "")) / background_path
        preview_path = render_dir / "preview" / f"slide-{index}.png"
        if not source_path.exists() or not preview_path.exists():
            missing += 1
            continue
        source = Image.open(source_path).convert("RGB")
        background = Image.open(background_path).convert("RGB") if background_path.exists() else None
        render = Image.open(preview_path).convert("RGB")
        render_rows = xml_slides[index - 1] if index - 1 < len(xml_slides) else []
        used: set[int] = set()
        for text_index, item in enumerate(slide.get("texts") or [], 1):
            box = item_bbox(item)
            if not box:
                continue
            match_idx, render_row = nearest_render_item(item, render_rows, used)
            if match_idx is not None:
                used.add(match_idx)
            source_box = [float(v) for v in (item.get("source_bbox") or box)]
            layout_box = [float(v) for v in (item.get("layout_bbox") or box)]
            rb = (render_row or {}).get("render_bbox") or layout_box
            # Compare the PowerPoint render frame to the authored frame.  A
            # large layout frame around a small glyph box is reported
            # separately because centered title containers are intentionally
            # wider than their visible glyphs.
            pos_delta = math.hypot((rb[0] - layout_box[0]), (rb[1] - layout_box[1]))
            size_delta = math.hypot((rb[2] - layout_box[2]), (rb[3] - layout_box[3]))
            source_alignment_delta = math.hypot((rb[0] - source_box[0]), (rb[1] - source_box[1]))
            expansion = max(layout_box[2] / max(1.0, source_box[2]), layout_box[3] / max(1.0, source_box[3]))
            stem = f"{sid}-{text_index:03d}"
            local = crop_metrics(source, render, background, source_box, (int(ref_w), int(ref_h)), crop_dir, stem)
            source_glyph = local.get("source_glyph_bbox") or source_box
            render_glyph = local.get("render_glyph_bbox") or rb
            glyph_pos_delta = math.hypot(render_glyph[0] - source_glyph[0], render_glyph[1] - source_glyph[1])
            glyph_size_delta = math.hypot(render_glyph[2] - source_glyph[2], render_glyph[3] - source_glyph[3])
            row = {
                "slide_id": sid,
                "text_id": item.get("id") or f"text-{text_index}",
                "text": item.get("text", ""),
                "source_bbox": [round(v, 3) for v in source_box],
                "layout_bbox": layout_box,
                "render_bbox": rb,
                "source_glyph_bbox": source_glyph,
                "render_glyph_bbox": render_glyph,
                "position_delta_px": round(glyph_pos_delta, 3),
                "size_delta_px": round(glyph_size_delta, 3),
                "source_alignment_delta_px": round(source_alignment_delta, 3),
                "layout_expansion_ratio": round(expansion, 3),
                "font_name": (render_row or {}).get("font_name") or item.get("font"),
                "font_size_pt": (render_row or {}).get("font_size_pt") or item.get("size") or item.get("font_size"),
                "bold": (render_row or {}).get("bold") if render_row else bool(item.get("bold")),
                "italic": (render_row or {}).get("italic") if render_row else bool(item.get("italic")),
                "alignment": (render_row or {}).get("alignment") or item.get("align"),
                "line_count": (render_row or {}).get("line_count") or max(1, str(item.get("text", "")).count("\n") + 1),
                "declared_color": item.get("color"),
                "font_match": "declared-only" if not render_row else bool((render_row.get("font_name") or item.get("font")) == item.get("font")),
                "local_pixel": local,
                "status": "review" if pos_delta > 2 or size_delta > 4 or expansion > 3.0 else "pass",
            }
            items.append(row)
    report = {
        "schema_version": 1,
        "deck": str(deck_path),
        "pptx": str(pptx),
        "source_dir": str(source_dir),
        "render_dir": str(render_dir),
        "reference_size": [int(ref_w), int(ref_h)],
        "slide_count": len(slides),
        "items": items,
        "missing_slide_assets": missing,
        "summary": {
            "text_items": len(items),
            "review_items": sum(1 for row in items if row["status"] == "review"),
            "mean_local_pixel_diff": round(sum(row["local_pixel"]["mean_abs_diff_0_255"] for row in items) / max(1, len(items)), 4),
            "mean_position_delta_px": round(sum(row["position_delta_px"] for row in items) / max(1, len(items)), 4),
            "mean_size_delta_px": round(sum(row["size_delta_px"] for row in items) / max(1, len(items)), 4),
            "mean_layout_expansion_ratio": round(sum(row["layout_expansion_ratio"] for row in items) / max(1, len(items)), 4),
        },
    }
    baseline = read_json(baseline_path) if baseline_path and baseline_path.exists() else None
    report["relative_baseline"] = compare_decks(report, baseline)
    report["verdict"] = "pass" if not missing and report["relative_baseline"]["status"] in {"not_required", "pass"} else "fail"
    write_json(out_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", required=True)
    parser.add_argument("--pptx", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--baseline-report", default="")
    args = parser.parse_args()
    report = build_report(Path(args.deck).resolve(), Path(args.pptx).resolve(), Path(args.source_dir).resolve(), Path(args.render_dir).resolve(), Path(args.out).resolve(), Path(args.baseline_report).resolve() if args.baseline_report else None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("verdict") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
