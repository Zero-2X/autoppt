#!/usr/bin/env python3
"""Build a separated editable round from an accepted high-fidelity deck.

This pass is intentionally conservative:

* normal text stays native PowerPoint text;
* brush/stylized titles become bounded movable PNG assets;
* the source page is used only to derive a continuous clean background;
* native frames/connectors are retained, while their measured source pixels are
  removed with local masks;
* every cleanup and fallback is recorded per slide.

The script never overwrites the accepted input deck.  It writes a new round
directory and returns ``blocked`` when any cleanup evidence is inconclusive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def bbox(item: dict[str, Any], *keys: str) -> list[int] | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, list) and len(value) == 4:
            try:
                x, y, w, h = [int(round(float(v))) for v in value]
            except (TypeError, ValueError):
                continue
            if w > 0 and h > 0:
                return [x, y, w, h]
    return None


def clamp_box(box: list[int], width: int, height: int, pad: int = 0) -> list[int]:
    x, y, w, h = box
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(width, x + w + pad)
    y1 = min(height, y + h + pad)
    return [x0, y0, max(1, x1 - x0), max(1, y1 - y0)]


def hex_rgb(value: str) -> np.ndarray:
    text = str(value or "#000000").lstrip("#")
    if len(text) != 6:
        text = "000000"
    return np.asarray([int(text[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.uint8)


def color_mask(crop_rgb: np.ndarray, target_rgb: np.ndarray, threshold: float) -> np.ndarray:
    lab = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    target = cv2.cvtColor(target_rgb.reshape(1, 1, 3), cv2.COLOR_RGB2LAB).reshape(3)
    distance = np.linalg.norm(lab - target, axis=2)
    mask = (distance <= threshold).astype(np.uint8) * 255
    # ImageGen text colors are often slightly wrong in the OCR metadata.  Add
    # a conservative luminance fallback inside the reviewed glyph crop.
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    target_luma = float(cv2.cvtColor(target_rgb.reshape(1, 1, 3), cv2.COLOR_RGB2GRAY)[0, 0])
    if target_luma >= 155:
        mask = cv2.bitwise_or(mask, ((gray >= 170) & (gray - gray.min() >= 18)).astype(np.uint8) * 255)
    elif target_luma <= 125:
        mask = cv2.bitwise_or(mask, (gray <= 145).astype(np.uint8) * 255)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    keep = np.zeros_like(mask)
    minimum = max(2, int(mask.size * 0.00001))
    for index in range(1, n):
        if stats[index, cv2.CC_STAT_AREA] >= minimum:
            keep[labels == index] = 255
    return keep


def text_mask(image_rgb: np.ndarray, item: dict[str, Any], threshold: float = 52.0) -> np.ndarray:
    height, width = image_rgb.shape[:2]
    # Cleanup follows the visible glyph box whenever OCR supplied one.
    # Container/source boxes are alignment regions and must not be used to
    # erase an entire panel.
    source_box = bbox(item, "ocr_bbox", "source_bbox", "bbox")
    if source_box is None:
        return np.zeros((height, width), dtype=np.uint8)
    x, y, w, h = clamp_box(source_box, width, height, pad=2)
    crop = image_rgb[y : y + h, x : x + w]
    raw = color_mask(crop, hex_rgb(item.get("color")), threshold)
    # A one-pixel dilation removes antialiasing remnants without expanding
    # into neighbouring icons or frame strokes.
    raw = cv2.dilate(raw, np.ones((5, 5), np.uint8), iterations=1)
    out = np.zeros((height, width), dtype=np.uint8)
    out[y : y + h, x : x + w] = raw
    return out


def border_mask(shape: dict[str, Any], width: int, height: int, thickness: int = 7) -> np.ndarray:
    source_box = bbox(shape, "source_bbox", "bbox")
    out = np.zeros((height, width), dtype=np.uint8)
    if source_box is None:
        return out
    x, y, w, h = clamp_box(source_box, width, height, pad=0)
    x2, y2 = min(width - 1, x + w - 1), min(height - 1, y + h - 1)
    stype = str(shape.get("type", "")).lower()
    if stype in {"line", "connector"}:
        x1 = int(round(float(shape.get("x1", x))))
        y1 = int(round(float(shape.get("y1", y))))
        x2l = int(round(float(shape.get("x2", x + w))))
        y2l = int(round(float(shape.get("y2", y + h))))
        cv2.line(out, (x1, y1), (x2l, y2l), 255, max(1, thickness), cv2.LINE_AA)
        return out
    if stype in {"oval", "ellipse"}:
        cv2.ellipse(out, ((x + x2) // 2, (y + y2) // 2), ((x2 - x) // 2, (y2 - y) // 2), 0, 0, 360, 255, thickness)
        return out
    # Native rectangles are outline-only in the inherited deck.  Keep the
    # interior (icons and panel artwork) intact.
    cv2.rectangle(out, (x, y), (x2, y2), 255, thickness)
    return out


def local_surface_repair(image_rgb: np.ndarray, mask: np.ndarray, sigma: float = 16.0, padding: int = 3) -> np.ndarray:
    if not np.count_nonzero(mask):
        return image_rgb.copy()
    expanded = cv2.dilate(mask, np.ones((padding * 2 + 1, padding * 2 + 1), np.uint8), iterations=1)
    valid = (expanded == 0).astype(np.float32)
    denominator = cv2.GaussianBlur(valid, (0, 0), sigmaX=sigma, sigmaY=sigma)
    numerator = cv2.GaussianBlur(image_rgb.astype(np.float32) * valid[:, :, None], (0, 0), sigmaX=sigma, sigmaY=sigma)
    surface = numerator / np.maximum(denominator[:, :, None], 1e-4)
    outside = image_rgb[expanded == 0]
    fallback = np.median(outside.reshape(-1, 3), axis=0) if outside.size else np.median(image_rgb.reshape(-1, 3), axis=0)
    surface[denominator < 1e-3] = fallback
    blend = cv2.GaussianBlur((expanded > 0).astype(np.float32), (0, 0), sigmaX=1.5, sigmaY=1.5)
    result = image_rgb.astype(np.float32) * (1.0 - blend[:, :, None]) + surface * blend[:, :, None]
    return np.clip(np.rint(result), 0, 255).astype(np.uint8)


def parse_rgb(value: Any) -> np.ndarray | None:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return None
    try:
        return np.asarray([int(text[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)
    except ValueError:
        return None


def color_support(image_rgb: np.ndarray, mask: np.ndarray, color: Any) -> float:
    rgb = parse_rgb(color)
    selected = image_rgb[mask > 0].astype(np.float32)
    if rgb is None or selected.size == 0:
        return 0.0
    return float(np.mean(np.linalg.norm(selected - rgb, axis=1) <= 48.0))


def color_support_metrics(image_rgb: np.ndarray, mask: np.ndarray, color: Any) -> dict[str, float]:
    support = color_support(image_rgb, mask, color)
    if not np.count_nonzero(mask):
        return {"support": 0.0, "ambient_support": 0.0, "excess_support": 0.0}
    kernel = np.ones((25, 25), np.uint8)
    expanded = cv2.dilate((mask > 0).astype(np.uint8), kernel, iterations=1) > 0
    ring = expanded & ~(mask > 0)
    ambient = color_support(image_rgb, ring.astype(np.uint8) * 255, color)
    return {
        "support": support,
        "ambient_support": ambient,
        "excess_support": max(0.0, support - ambient),
    }


def cleanup_mask_path(out_dir: Path, slide_id: str, item: dict[str, Any], index: int) -> Path:
    stem = str(item.get("name") or item.get("id") or f"shape-{index:03d}")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in stem)
    return out_dir / "assets" / slide_id / "cleanup-masks" / f"{safe}.png"


def write_cleanup_mask(path: Path, mask: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((mask > 0).astype(np.uint8) * 255, mode="L").save(path)


def transparent_crop(image_rgb: np.ndarray, mask: np.ndarray, box: list[int], path: Path) -> None:
    x, y, w, h = clamp_box(box, image_rgb.shape[1], image_rgb.shape[0], pad=3)
    crop = image_rgb[y : y + h, x : x + w]
    alpha = mask[y : y + h, x : x + w]
    rgba = np.dstack([crop, alpha])
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path)


def inherited_asset_mask(
    asset_path: Path,
    asset_box: list[int],
    canvas_size: tuple[int, int],
) -> np.ndarray | None:
    """Recover the reviewed text alpha from a prior visual-locked asset.

    Older accepted rounds store fallback text as RGB PNGs on a clean local
    patch rather than RGBA.  In that case the non-background pixels are
    recovered conservatively from the asset's luminance/color contrast.
    """

    try:
        image = Image.open(asset_path).convert("RGBA")
        rgba = np.asarray(image)
    except (OSError, ValueError):
        return None
    alpha = rgba[:, :, 3]
    if int(alpha.max()) == 0:
        return None
    if int(alpha.min()) == 255:
        rgb = rgba[:, :, :3]
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        # Fallback assets are tightly cropped text patches.  Their near-white
        # or near-paper pixels are background; keep the darker/colored glyphs.
        spread = np.max(rgb, axis=2).astype(np.int16) - np.min(rgb, axis=2).astype(np.int16)
        alpha = ((gray < 220) | (spread > 18)).astype(np.uint8) * 255
    x, y, w, h = [int(v) for v in asset_box]
    canvas_w, canvas_h = canvas_size
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(canvas_w, x + max(1, w))
    y1 = min(canvas_h, y + max(1, h))
    if x1 <= x0 or y1 <= y0:
        return None
    resized = cv2.resize(alpha, (max(1, x1 - x0), max(1, y1 - y0)), interpolation=cv2.INTER_NEAREST)
    out = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    out[y0:y1, x0:x1] = resized
    return cv2.dilate(out, np.ones((3, 3), np.uint8), iterations=1)


def art_text(item: dict[str, Any]) -> bool:
    size = float(item.get("size", 0) or 0)
    confidence = float(item.get("confidence", 1.0) or 0.0)
    # Explicit art/uncertain OCR is kept as a bounded movable image.  A
    # container is not automatically art text: section labels with a tight
    # glyph box can remain native.  Low-confidence/duplicate rows must never
    # become a wide native textbox.
    return bool(item.get("art_text")) or bool(item.get("needs_review")) or bool(
        item.get("duplicate_ocr_text")
    ) or confidence < 0.55 or (
        not item.get("ocr_bbox") and bool(item.get("bold")) and size >= 38
    )


def text_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if not ch.isspace())


def text_width_units(value: Any) -> float:
    """Approximate the PowerPoint width needed by a CJK text run.

    The source analysis stores a glyph-height-like value, while PptxGenJS
    consumes points.  CJK glyphs are close to one em and ASCII is narrower.
    Keeping this estimate in the reconstruction layer prevents a measured
    one-line source label from wrapping after it becomes native text.
    """

    lines = str(value or "").replace("\r", "").split("\n") or [""]
    widest = 0.0
    for line in lines:
        units = 0.0
        for char in line:
            if char.isspace():
                units += 0.35
            elif ord(char) < 128:
                units += 0.58
            else:
                units += 1.0
        widest = max(widest, units)
    return max(1.0, widest)


def fit_native_font_size(row: dict[str, Any]) -> float:
    """Fit a native text row to its measured layout box in PowerPoint points."""

    box = bbox(row, "layout_bbox", "source_bbox", "bbox")
    current = float(row.get("size", row.get("font_size", 18)) or 18)
    if not box:
        return round(current, 1)
    # 1672 px maps to 13.333 in and 941 px maps to 7.5 in in the deck.
    width_pt = float(box[2]) * 13.333333 * 72.0 / 1672.0
    height_pt = float(box[3]) * 7.5 * 72.0 / 941.0
    lines = max(1, str(row.get("text", "")).replace("\r", "").count("\n") + 1)
    width_fit = width_pt / (text_width_units(row.get("text", "")) * 1.08)
    height_fit = height_pt / (lines * 1.18)
    # Never enlarge OCR estimates.  A small floor keeps labels legible while
    # still allowing long standards names to remain single-line.
    return round(max(7.0, min(current, width_fit, height_fit)), 1)


def union_box(first: list[int], second: list[int]) -> list[int]:
    x0 = min(first[0], second[0])
    y0 = min(first[1], second[1])
    x1 = max(first[0] + first[2], second[0] + second[2])
    y1 = max(first[1] + first[3], second[1] + second[3])
    return [x0, y0, max(1, x1 - x0), max(1, y1 - y0)]


def merge_near_duplicate_analysis_texts(
    slide_id: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge OCR rows that are really the two lines of one visible label.

    OCR on the ImageGen pages frequently returns the same two-line label once
    per line (for example ``节省转运等/成本``).  Keeping both rows creates
    the exact overlap seen in S35.  Rows at different horizontal positions
    (repeated labels in a chart) remain independent.
    """

    prepared: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        text = canonical_text(slide_id, row)
        row["text"] = text
        box = bbox(row, "ocr_bbox", "source_bbox", "bbox")
        row["_merge_box"] = box
        prepared.append(row)
    consumed: set[int] = set()
    merged: list[dict[str, Any]] = []
    for index, row in enumerate(prepared):
        if index in consumed:
            continue
        base = dict(row)
        base.pop("_merge_box", None)
        base_box = row.get("_merge_box")
        for other_index in range(index + 1, len(prepared)):
            if other_index in consumed:
                continue
            other = prepared[other_index]
            if text_key(other.get("text")) != text_key(row.get("text")):
                continue
            other_box = other.get("_merge_box")
            if not base_box or not other_box:
                continue
            cx = base_box[0] + base_box[2] / 2.0
            ox = other_box[0] + other_box[2] / 2.0
            y_gap = max(
                0,
                max(base_box[1], other_box[1])
                - min(base_box[1] + base_box[3], other_box[1] + other_box[3]),
            )
            x_gap = abs(cx - ox)
            same_slot = x_gap <= max(base_box[2], other_box[2]) * 0.55 and y_gap <= max(
                base_box[3], other_box[3]
            ) * 1.35
            overlap = (
                min(base_box[0] + base_box[2], other_box[0] + other_box[2])
                - max(base_box[0], other_box[0])
            ) > 0
            if not (same_slot and (overlap or y_gap <= max(base_box[3], other_box[3]))):
                continue
            chosen = base if float(other.get("confidence", 0) or 0) > float(
                base.get("confidence", 0) or 0
            ) else base
            chosen["source_bbox"] = union_box(base_box, other_box)
            chosen["bbox"] = chosen["source_bbox"]
            chosen["ocr_bbox"] = chosen["source_bbox"]
            chosen["merged_from"] = [str(row.get("id")), str(other.get("id"))]
            consumed.add(other_index)
            base_box = chosen["source_bbox"]
            base = chosen
        merged.append(base)
    return merged


def should_fallback_text(slide_id: str, row: dict[str, Any]) -> bool:
    """Route only visibly unstable native candidates to movable art text."""

    confidence = float(row.get("confidence", 1.0) or 0.0)
    size = float(row.get("size", 0) or 0)
    text = text_key(row.get("text", ""))
    if row.get("art_text") or row.get("needs_review"):
        return True
    if confidence < 0.70:
        return True
    # Large centered labels embedded in brush/medallion artwork are not
    # faithfully reproduced by Microsoft YaHei/Calibri substitutes.
    if row.get("container_shape_id") and size >= 35 and len(text) <= 8:
        return True
    if size >= 40 and len(text) <= 8 and not row.get("ocr_bbox"):
        return True
    return False


def is_garbage_text(item: dict[str, Any]) -> bool:
    value = text_key(item.get("text", ""))
    confidence = float(item.get("confidence", 1.0) or 0.0)
    return bool(value) and len(value) <= 1 and (
        confidence < 0.85 or bool(item.get("needs_review"))
    )


def near_duplicate_text(candidate: dict[str, Any], accepted: dict[str, Any]) -> bool:
    """Suppress sentence/fragment OCR duplicates in the same visual slot."""

    current = text_key(candidate.get("text", ""))
    previous = text_key(accepted.get("text", ""))
    if not current or not previous:
        return False
    if not (current == previous or current in previous or previous in current):
        return False
    current_box = bbox(candidate, "ocr_bbox", "source_bbox", "bbox")
    previous_box = bbox(accepted, "ocr_bbox", "source_bbox", "bbox")
    if not current_box or not previous_box:
        return False
    cx = current_box[0] + current_box[2] / 2.0
    cy = current_box[1] + current_box[3] / 2.0
    px = previous_box[0] + previous_box[2] / 2.0
    py = previous_box[1] + previous_box[3] / 2.0
    x_overlap = max(
        0,
        min(current_box[0] + current_box[2], previous_box[0] + previous_box[2])
        - max(current_box[0], previous_box[0]),
    )
    x_gate = x_overlap >= 0.25 * min(current_box[2], previous_box[2]) or abs(cx - px) <= max(
        current_box[2], previous_box[2]
    )
    y_gate = abs(cy - py) <= 1.65 * max(current_box[3], previous_box[3])
    return bool(x_gate and y_gate)


def is_title_row(item: dict[str, Any]) -> bool:
    """Large brush title handled once by detect_title_region()."""
    size = float(item.get("size", 0) or 0)
    source_box = bbox(item, "source_bbox", "bbox")
    return bool(source_box and source_box[1] < 220 and size >= 38 and not item.get("ocr_bbox"))


def detect_title_region(image_rgb: np.ndarray) -> tuple[np.ndarray, list[int] | None]:
    """Find a large dark brush title in the upper title band."""
    height, width = image_rgb.shape[:2]
    top = image_rgb[: min(height, 220)]
    hsv = cv2.cvtColor(top, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(top, cv2.COLOR_RGB2GRAY)
    dark = ((gray < 125) & (hsv[:, :, 1] > 35)).astype(np.uint8) * 255
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    keep = np.zeros_like(dark)
    boxes: list[list[int]] = []
    for index in range(1, n):
        x, y, w, h, area = stats[index]
        if area < 30 or h < 18 or w < 8 or h < 0.02 * height:
            continue
        if w > 0.45 * width and h < 18:
            continue
        keep[labels == index] = 255
        boxes.append([int(x), int(y), int(w), int(h)])
    if not boxes:
        return np.zeros((height, width), dtype=np.uint8), None
    x0 = max(0, min(box[0] for box in boxes) - 4)
    y0 = max(0, min(box[1] for box in boxes) - 4)
    x1 = min(width, max(box[0] + box[2] for box in boxes) + 4)
    y1 = min(height, max(box[1] + box[3] for box in boxes) + 4)
    if x1 - x0 < 0.35 * width or y1 - y0 < 35:
        return np.zeros((height, width), dtype=np.uint8), None
    out = np.zeros((height, width), dtype=np.uint8)
    out[:220] = keep
    return out, [x0, y0, x1 - x0, y1 - y0]


def canonical_text(slide_id: str, row: dict[str, Any]) -> str:
    """Apply small, attributable corrections to known OCR fragments."""
    text = str(row.get("text", ""))
    if slide_id == "S09":
        box = bbox(row, "ocr_bbox", "source_bbox", "bbox") or [0, 0, 0, 0]
        x, y, w, h = box
        if "紧急订单" in text and "%" in text:
            return "紧急订单"
        if text == "常规订单":
            return text
        if "差错与审核成本" in text:
            return "审核成本提升"
    if slide_id == "S35" and text_key(text) in {"劈", "助", "力"}:
        return "助\n力"
    return text


def cleanup_status(item: dict[str, Any]) -> str:
    evidence = item.get("cleanup_evidence")
    if isinstance(evidence, dict):
        return str(evidence.get("status", "")).lower()
    return ""


def normalize_native_shape(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    source_box = bbox(row, "source_bbox", "bbox")
    if source_box is None:
        return None
    out = dict(row)
    out["source_bbox"] = source_box
    out["x"], out["y"], out["w"], out["h"] = source_box
    out["editability_level"] = "native"
    out["layer_source"] = source
    out.setdefault("role", "native-frame")
    out.setdefault("name", f"native-{out.get('type', 'shape')}-{out.get('id', source)}")
    role = str(out.get("role", "")).lower()
    shape_type = str(out.get("type", "")).lower()
    if shape_type in {"rect", "rounded_rect"} and any(token in role for token in ("panel", "frame", "card")):
        out.setdefault("frame_id", str(out.get("name") or out.get("id") or source))
    return out


def text_should_use_fallback(
    slide_id: str,
    row: dict[str, Any],
    force_native_text: bool,
    fallback_slides: set[str] | None = None,
) -> bool:
    if force_native_text:
        return False
    return (
        slide_id in {"S03", "S09", "S19", "S33", "S38"}
        or slide_id in (fallback_slides or set())
        or should_fallback_text(slide_id, row)
        or art_text(row)
    )


def title_text_row(slide_id: str, title_text: str, title_box: list[int]) -> dict[str, Any]:
    # ``title_box`` is measured in source pixels while PowerPoint ``size`` is
    # points.  The old height-only formula (h * 0.52) routinely produced
    # 80–90 pt CJK titles that wrapped into a second row.  Fit to the measured
    # width and visible character count first, then cap the result so the
    # native title remains a single line at slide scale.
    text_len = max(1, len("".join(str(title_text).split())))
    width_points = float(title_box[2]) * 0.75
    width_fit = width_points / (text_len * 1.10)
    height_fit = float(title_box[3]) * 0.75 * 0.72
    size = max(30.0, min(56.0, width_fit, height_fit))
    return {
        "id": "title-native",
        "text": title_text,
        "x": title_box[0],
        "y": title_box[1],
        "w": title_box[2],
        "h": title_box[3],
        "source_bbox": title_box,
        "layout_bbox": title_box,
        "font": "STXingkai",
        "size": round(size, 1),
        "color": "#073B16",
        "bold": False,
        "align": "center",
        "valign": "middle",
        "fit": "shrink",
        "margin_top": 0,
        "margin_right": 0,
        "margin_bottom": 0,
        "margin_left": 0,
        "char_spacing": 0,
        "route": "native-text",
        "editability_level": "native",
        "name": f"editable-title::{slide_id}",
    }


REVIEWED_INTENTIONAL_OVERLAPS: dict[str, dict[str, list[str]]] = {
    # These are compact icon+label compositions verified in the full-size
    # PowerPoint comparisons.  Their source/layout bboxes intentionally touch.
    "S04": {
        "editable-text-011": ["vector-svg::icon-013"],
    },
    "S20": {
        "editable-text-020": ["vector-svg::icon-010"],
        "editable-text-018": ["vector-svg::icon-010"],
    },
    "S22": {
        "editable-text-027": ["editable-text-026"],
        "editable-text-026": ["editable-text-027"],
        "editable-text-024": ["vector-svg::icon-015"],
        "editable-text-023": ["vector-svg::icon-014"],
    },
    "S23": {
        "editable-text-003": ["art-text::S23::title"],
        "editable-text-004": ["art-text::S23::title"],
        "editable-text-002": ["art-text::S23::title"],
    },
    "S27": {
        "editable-text-016": ["vector-svg::icon-007"],
    },
}


def apply_reviewed_overlap_allowances(
    slide_id: str,
    texts: list[dict[str, Any]],
    icons: list[dict[str, Any]],
) -> None:
    allowances = REVIEWED_INTENTIONAL_OVERLAPS.get(slide_id, {})
    if not allowances:
        return
    for item in [*texts, *icons]:
        name = str(item.get("name", ""))
        targets = allowances.get(name)
        if targets:
            item["allow_overlap_with"] = sorted(
                {str(value) for value in targets if value}
            )
            item["overlap_review"] = "full-size-PowerPoint-visual-review"


def build_round(
    source_deck: Path,
    source_root: Path,
    out_dir: Path,
    *,
    force_native_text: bool = False,
    native_title_text: bool = False,
    promote_analysis_shapes: bool = False,
    promote_analysis_lines: bool = False,
    stable_native_only: bool = False,
    fallback_slides: set[str] | None = None,
) -> dict[str, Any]:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"round output must be empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    base = read_json(source_deck)
    prompt_manifest = read_json(source_root / "image-prompts.json")
    prompt_by_id = {str(s["slide_id"]): s for s in prompt_manifest.get("slides", [])}
    slides = []
    reports = []
    any_blocked = False
    for slide in base.get("slides", []):
        sid = str(slide["slide_id"])
        source_path = Path(str(slide.get("source_imagegen_master") or source_root / "assets" / "slides" / f"{sid}.png"))
        if not source_path.is_absolute():
            source_path = source_root / source_path
        source_path = source_path.resolve()
        image_rgb = np.asarray(Image.open(source_path).convert("RGB"))
        height, width = image_rgb.shape[:2]
        mask = np.zeros((height, width), dtype=np.uint8)
        native_text_mask = np.zeros((height, width), dtype=np.uint8)
        native_texts = []
        art_assets = []
        text_rows = []
        for index, item in enumerate(slide.get("texts", []), start=1):
            row = dict(item)
            row["source_bbox"] = bbox(item, "source_bbox", "bbox")
            row["layout_bbox"] = bbox(item, "layout_bbox") or row["source_bbox"]
            row["source_bbox"] = row["source_bbox"] or row["layout_bbox"]
            if not row["source_bbox"]:
                row["cleanup_status"] = "fail"
                text_rows.append(row)
                continue
            item_mask = text_mask(image_rgb, row)
            mask = cv2.bitwise_or(mask, item_mask)
            # The five representative pages are intentionally kept on the
            # source-locked raster-text route while their layer contract is
            # repaired.  Their brush labels, metric numerals, and compact
            # panel captions cannot be reproduced faithfully with a generic
            # PowerPoint font without visible drift.
            if text_should_use_fallback(sid, row, force_native_text, fallback_slides):
                asset_path = out_dir / "assets" / sid / "art-text" / f"{row.get('id', f'text-{index:03d}')}.png"
                transparent_crop(image_rgb, item_mask, row["source_bbox"], asset_path)
                art_assets.append({
                    "file": str(asset_path.relative_to(out_dir)).replace("\\", "/"),
                    "x": row["source_bbox"][0] - 3,
                    "y": row["source_bbox"][1] - 3,
                    "w": row["source_bbox"][2] + 6,
                    "h": row["source_bbox"][3] + 6,
                    "source_bbox": row["source_bbox"],
                    "layout_bbox": row.get("layout_bbox"),
                    "role": "art-text-fallback",
                    "editability_level": "movable-image",
                    "name": f"art-text::{sid}::{row.get('id', index)}",
                })
                row["route"] = "movable-image"
                row["fallback_asset"] = str(asset_path.resolve())
            else:
                native_texts.append(row)
                row["route"] = "native-text"
            row["cleanup_status"] = "pass" if np.count_nonzero(item_mask) >= 3 else "fail"
            text_rows.append(row)
        # Promote the complete reviewed OCR inventory, not only the subset
        # that the previous high-fidelity deck happened to keep as native.
        analysis_path = source_root / "reconstruction" / sid / "analysis" / "analysis.json"
        analysis = read_json(analysis_path) if analysis_path.exists() else {}
        analysis_texts = [dict(item) for item in analysis.get("texts", [])]
        if stable_native_only:
            analysis_texts = merge_near_duplicate_analysis_texts(sid, analysis_texts)
        inherited_text_assets = {
            str(icon.get("source_text_id")): dict(icon)
            for icon in slide.get("icons", [])
            if icon.get("source_text_id")
            and str(icon.get("role", "")).lower()
            in {"verified-text-visual-exception", "stylized-art-text"}
            and icon.get("file")
        }
        analysis_texts.sort(
            key=lambda item: (
                len(text_key(item.get("text", ""))),
                float(item.get("confidence", 0.0) or 0.0),
            ),
            reverse=True,
        )
        inherited_by_id = {
            str(item.get("id")): item
            for item in slide.get("texts", [])
            if item.get("id") is not None
        }
        dedupe_text_boxes: list[list[int]] = []
        accepted_text_rows: list[dict[str, Any]] = []
        shape_candidates = []
        seen_shape_keys = set()
        for shape in slide.get("shapes", []):
            normalized = normalize_native_shape(dict(shape), "source-deck")
            if normalized is None:
                continue
            key = tuple(normalized.get("source_bbox", [])) + (str(normalized.get("type", "")),)
            seen_shape_keys.add(key)
            shape_candidates.append(normalized)
        if promote_analysis_shapes:
            for shape in analysis.get("shapes", []):
                normalized = normalize_native_shape(dict(shape), "analysis-shapes")
                if normalized is None:
                    continue
                key = tuple(normalized.get("source_bbox", [])) + (str(normalized.get("type", "")),)
                if key in seen_shape_keys:
                    continue
                confidence = float(normalized.get("confidence", 1.0) or 0.0)
                if confidence < (0.93 if stable_native_only else 0.90):
                    continue
                seen_shape_keys.add(key)
                shape_candidates.append(normalized)
        if promote_analysis_lines:
            for line in analysis.get("lines", []):
                if cleanup_status(line) != "pass":
                    continue
                line_type = str(line.get("type", "")).lower()
                line_role = str(line.get("role", "")).lower()
                line_confidence = float(line.get("confidence", 0.0) or 0.0)
                # Long, low-confidence dividers are often texture edges rather
                # than authored geometry.  Keep explicit connectors, but do
                # not add faint duplicate rules to the visual background.
                if stable_native_only and line_confidence < 0.75:
                    continue
                normalized = normalize_native_shape(dict(line), "analysis-lines")
                if normalized is None:
                    continue
                normalized.setdefault("role", "native-line")
                key = tuple(normalized.get("source_bbox", [])) + (str(normalized.get("type", "")),)
                if key in seen_shape_keys:
                    continue
                seen_shape_keys.add(key)
                shape_candidates.append(normalized)
        shape_rows = []
        visual_only_shapes = []
        shape_cleanup_masks: list[tuple[dict[str, Any], np.ndarray, Path]] = []
        for shape_index, shape in enumerate(shape_candidates, start=1):
            row = dict(shape)
            # Low-confidence approximations are usually duplicate outlines for
            # brush headers, soft panels, or full-page artwork.  They create
            # the visible double-frame defect when the source pixels remain in
            # the continuous background.
            if not promote_analysis_shapes and sid in {"S03", "S09", "S19", "S33", "S38"} and float(
                row.get("confidence", 1.0) or 0.0
            ) < 0.94:
                row["cleanup_status"] = "visual-only-exception"
                row["routing_note"] = "low-confidence-geometry-retained-in-background"
                row["route"] = "visual-only-background"
                visual_only_shapes.append(row)
                continue
            if row.get("fill"):
                row["cleanup_status"] = "visual-only-exception"
                shape_rows.append(row)
                continue
            shape_mask = border_mask(
                row,
                width,
                height,
                thickness=max(5, int(round(float(row.get("line_width", 1.2))) + 4)),
            )
            line_color = row.get("line") or row.get("line_color") or "#000000"
            source_metrics = color_support_metrics(image_rgb, shape_mask, line_color)
            if (
                stable_native_only
                and str(row.get("type", "")).lower() in {"rect", "rounded_rect", "round_rect"}
                and source_metrics["excess_support"] < 0.12
            ):
                row["cleanup_status"] = "visual-only-exception"
                row["routing_note"] = "low-excess-support-frame-retained-in-background"
                row["cleanup_evidence"] = {
                    "status": "not-routed",
                    "method": "local-excess-support-gate",
                    "line_color": line_color,
                    "source_support": round(source_metrics["support"], 6),
                    "source_ambient_support": round(source_metrics["ambient_support"], 6),
                    "source_excess_support": round(source_metrics["excess_support"], 6),
                }
                # The frame remains visually represented by the continuous
                # background. Do not also place a native frame on the slide:
                # that would duplicate the same pixels and falsely inflate
                # native-shape coverage while failing the semantic layer
                # contract. Keep the excluded candidate in the report.
                row["route"] = "visual-only-background"
                visual_only_shapes.append(row)
                continue
            mask = cv2.bitwise_or(mask, shape_mask)
            if np.count_nonzero(shape_mask):
                row["cleanup_status"] = "pass"
                row.setdefault("background_cleanup", "full-frame-directional" if str(row.get("frame_id", "")).strip() else "shape-inpaint")
                row["requires_background_cleanup"] = True
                mask_path = cleanup_mask_path(out_dir, sid, row, shape_index)
                row["cleanup_mask"] = str(mask_path.relative_to(out_dir)).replace("\\", "/")
                shape_cleanup_masks.append((row, shape_mask, mask_path))
            else:
                row["cleanup_status"] = "fail"
            shape_rows.append(row)

        # Rebuild text routing from the analysis inventory.  The inherited
        # deck is used only for measured layout overrides and legacy fallbacks.
        native_texts = []
        art_assets = []
        text_rows = []
        for index, item in enumerate(analysis_texts, start=1):
            row = dict(item)
            item_id = str(row.get("id") or f"text-{index:03d}")
            row["id"] = item_id
            # Titles are extracted once below.  Processing the same analysis
            # row as well produced two overlapping movable title layers.
            if is_title_row(row):
                continue
            source_box = bbox(row, "ocr_bbox", "source_bbox", "bbox")
            if source_box is None:
                continue
            inherited = inherited_by_id.get(item_id, {})
            row["source_bbox"] = source_box
            # A container bbox is not a text frame.  Prefer the tight glyph
            # box whenever OCR supplied one; only non-container text may use a
            # reviewed layout expansion.
            if row.get("container_shape_id"):
                row["layout_bbox"] = source_box
            else:
                row["layout_bbox"] = bbox(inherited, "layout_bbox") or source_box
            row["x"], row["y"], row["w"], row["h"] = row["layout_bbox"]
            row["text"] = canonical_text(sid, row)
            row["source_bbox"] = list(source_box)
            if (
                stable_native_only
                and text_should_use_fallback(sid, row, force_native_text, fallback_slides)
                and item_id not in inherited_text_assets
            ):
                # No reviewed fallback asset exists for this OCR fragment.
                # Leave the source pixels in the continuous background rather
                # than create a new, potentially incomplete crop.
                row["route"] = "visual-only-exception"
                row["cleanup_status"] = "not-routed"
                row["routing_note"] = "no-reviewed-fallback-asset-retained-in-background"
                text_rows.append(row)
                continue
            # A reviewed, uncertain OCR row is safer as a visual exception
            # than as a generic native box.  This is especially important for
            # central medallion text and long labels embedded in title bars.
            if (
                stable_native_only
                and not text_should_use_fallback(sid, row, force_native_text, fallback_slides)
                and (
                    float(row.get("confidence", 1.0) or 0.0) < 0.90
                    or bool(row.get("container_shape_id"))
                    and float(row.get("size", 0) or 0) >= 20
                )
            ):
                row["route"] = "visual-only-exception"
                row["cleanup_status"] = "not-routed"
                row["routing_note"] = "unstable-native-candidate-retained-in-background"
                text_rows.append(row)
                continue
            item_mask = text_mask(image_rgb, row)
            inherited_asset_for_mask = inherited_text_assets.get(item_id)
            if inherited_asset_for_mask:
                inherited_path_for_mask = Path(str(inherited_asset_for_mask.get("file"))).resolve()
                inherited_box_for_mask = bbox(
                    inherited_asset_for_mask,
                    "layout_bbox",
                    "source_bbox",
                )
                if inherited_path_for_mask.exists() and inherited_box_for_mask:
                    alpha_mask = inherited_asset_mask(
                        inherited_path_for_mask,
                        inherited_box_for_mask,
                        (width, height),
                    )
                    if alpha_mask is not None and np.count_nonzero(alpha_mask) >= 3:
                        item_mask = alpha_mask
            mask = cv2.bitwise_or(mask, item_mask)
            if is_garbage_text(row):
                row["route"] = "dropped-residue-cleanup"
                row["cleanup_status"] = "pass" if np.count_nonzero(item_mask) >= 3 else "fail"
                row["routing_note"] = "single-glyph-low-confidence-or-needs-review"
                text_rows.append(row)
                continue
            if any(near_duplicate_text(row, prior) for prior in accepted_text_rows):
                row["route"] = "suppressed-duplicate-cleanup"
                row["cleanup_status"] = "pass" if np.count_nonzero(item_mask) >= 3 else "fail"
                row["routing_note"] = "nearby-containing-ocr-fragment"
                text_rows.append(row)
                continue
            accepted_text_rows.append(row)
            dedupe_text_boxes.append(source_box)
            if text_should_use_fallback(sid, row, force_native_text, fallback_slides):
                inherited_asset = inherited_text_assets.get(item_id)
                inherited_path = (
                    Path(str(inherited_asset.get("file"))).resolve()
                    if inherited_asset
                    else None
                )
                if inherited_path and inherited_path.exists():
                    asset_path = out_dir / "assets" / sid / "verified-text" / inherited_path.name
                    asset_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(inherited_path, asset_path)
                    inherited_box = bbox(inherited_asset, "layout_bbox", "source_bbox")
                    asset_box = inherited_box or source_box
                    # The reviewed asset is already alpha/contrast-cleaned;
                    # use its exact bbox and only the measured mask for
                    # background removal.
                    row["fallback_source"] = "accepted-visual-locked-asset"
                else:
                    asset_path = out_dir / "assets" / sid / "art-text" / f"{item_id}.png"
                    transparent_crop(image_rgb, item_mask, source_box, asset_path)
                    asset_box = [
                        source_box[0] - 3,
                        source_box[1] - 3,
                        source_box[2] + 6,
                        source_box[3] + 6,
                    ]
                    row["fallback_source"] = "source-mask-crop"
                art_assets.append(
                    {
                        "file": str(asset_path.relative_to(out_dir)).replace("\\", "/"),
                        "x": asset_box[0],
                        "y": asset_box[1],
                        "w": asset_box[2],
                        "h": asset_box[3],
                        "source_bbox": source_box,
                        "layout_bbox": asset_box,
                        "role": "art-text-fallback",
                        "editability_level": "movable-image",
                        "name": f"art-text::{sid}::{item_id}",
                        "source_text_id": item_id,
                        "text": str(row.get("text", "")),
                        "fallback_reason": (
                            "explicit-art-text"
                            if row.get("art_text")
                            else "uncertain-or-container-ocr"
                        ),
                    }
                )
                row["route"] = "movable-image"
                row["fallback_asset"] = str(asset_path.resolve())
            else:
                row["route"] = "native-text"
                # Keep the semantic layer contract explicit: rows routed to
                # PowerPoint text are native editable objects, while the
                # art-text branch above is disclosed as movable-image.
                row["editability_level"] = "native"
                if stable_native_only:
                    row["size"] = fit_native_font_size(row)
                native_texts.append(row)
                native_text_mask = cv2.bitwise_or(native_text_mask, item_mask)
            row["cleanup_status"] = "pass" if np.count_nonzero(item_mask) >= 3 else "fail"
            text_rows.append(row)

        title_mask, title_box = detect_title_region(image_rgb)
        title_text = str(prompt_by_id.get(sid, {}).get("headline", "")).strip()
        if title_box and title_text:
            mask = cv2.bitwise_or(mask, title_mask)
            if native_title_text or force_native_text:
                title_row = title_text_row(sid, title_text, title_box)
                native_texts.append(title_row)
                native_text_mask = cv2.bitwise_or(native_text_mask, title_mask)
                text_rows.append({**title_row, "cleanup_status": "pass"})
            else:
                asset_path = out_dir / "assets" / sid / "art-text" / "title.png"
                transparent_crop(image_rgb, title_mask, title_box, asset_path)
                art_assets.append(
                    {
                        "file": str(asset_path.relative_to(out_dir)).replace("\\", "/"),
                        "x": title_box[0],
                        "y": title_box[1],
                        "w": title_box[2],
                        "h": title_box[3],
                        "source_bbox": title_box,
                        "layout_bbox": title_box,
                        "role": "art-text-fallback",
                        "editability_level": "movable-image",
                        "name": f"art-text::{sid}::title",
                        "source_text_id": "title",
                        "text": title_text,
                        "fallback_reason": "brush title detected from source title band",
                    }
                )

        # Remove inherited text pictures that now have a reliable native route.
        analysis_ids = {str(item.get("id")) for item in analysis_texts}
        retained_icons = []
        for icon in slide.get("icons", []):
            source_text_id = str(icon.get("source_text_id", ""))
            role = str(icon.get("role", "")).lower()
            if source_text_id in analysis_ids or "text" in role:
                continue
            retained_icons.append(dict(icon))
        # Use the exact foreground cleanup mask for both text and promoted
        # native geometry so the rendered PowerPoint objects do not sit on top
        # of duplicate pixels baked into the continuous background.
        cleaned = cv2.inpaint(image_rgb, mask, 3, cv2.INPAINT_TELEA)
        # Telea can leave low-opacity brush-text ghosts when the title strokes
        # sit on textured paper. Apply a second, tightly scoped surface repair
        # over native text masks (especially the detected title band) so the
        # original raster glyphs do not remain underneath the editable text.
        cleaned = local_surface_repair(cleaned, native_text_mask, sigma=18.0, padding=3)
        remaining = cv2.bitwise_and(mask, cv2.bitwise_not(native_text_mask))
        cleaned = local_surface_repair(cleaned, remaining, sigma=14.0, padding=2)
        clean_path = out_dir / "assets" / sid / "background.png"
        clean_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(cleaned).save(clean_path)

        for row, shape_mask, mask_path in shape_cleanup_masks:
            write_cleanup_mask(mask_path, shape_mask)
            line_color = row.get("line") or row.get("line_color") or "#000000"
            source_metrics = color_support_metrics(image_rgb, shape_mask, line_color)
            post_metrics = color_support_metrics(cleaned, shape_mask, line_color)
            source_support = source_metrics["support"]
            post_support = post_metrics["support"]
            post_excess = post_metrics["excess_support"]
            row["cleanup_evidence"] = {
                "status": "pass" if post_excess <= 0.12 else "fail",
                "method": "opencv-telea-and-local-surface-native-geometry-cleanup",
                "cleanup_mask": row["cleanup_mask"],
                "mask_bbox": row.get("source_bbox"),
                "line_color": line_color,
                "source_support": round(source_support, 6),
                "source_ambient_support": round(source_metrics["ambient_support"], 6),
                "source_excess_support": round(source_metrics["excess_support"], 6),
                "post_cleanup_support": round(post_support, 6),
                "post_cleanup_frame_support": round(post_support, 6),
                "post_cleanup_ambient_support": round(post_metrics["ambient_support"], 6),
                "post_cleanup_excess_support": round(post_excess, 6),
                "residual_ratio": round(
                    post_excess / max(source_metrics["excess_support"], 1e-6),
                    6,
                ),
            }
            if post_excess > 0.12:
                row["cleanup_status"] = "fail"
        new_slide = dict(slide)
        new_slide["background"] = str(clean_path.relative_to(out_dir)).replace("\\", "/")
        new_slide["assets_dir"] = str(out_dir.resolve())
        new_slide["texts"] = native_texts
        new_slide["icons"] = retained_icons + art_assets
        apply_reviewed_overlap_allowances(sid, new_slide["texts"], new_slide["icons"])
        for icon in new_slide["icons"]:
            if isinstance(icon, dict) and not Path(str(icon.get("file", ""))).is_absolute():
                continue
        new_slide["shapes"] = shape_rows
        slides.append(new_slide)
        failures = [r for r in text_rows + shape_rows if r.get("cleanup_status") == "fail"]
        report = {
            "slide_id": sid,
            "source": str(source_path),
            "background": str(clean_path),
            "source_sha256": sha256_file(source_path),
            "background_sha256": sha256_file(clean_path),
            "mask_pixel_count": int(np.count_nonzero(mask)),
            "texts": text_rows,
            "shapes": shape_rows,
            "visual_only_shape_candidates": visual_only_shapes,
            "art_text_assets": art_assets,
            "routing_options": {
                "force_native_text": force_native_text,
                "native_title_text": native_title_text,
                "promote_analysis_shapes": promote_analysis_shapes,
                "promote_analysis_lines": promote_analysis_lines,
                "stable_native_only": stable_native_only,
                "fallback_slides": sorted(fallback_slides or set()),
            },
            "residual_target_pixels": int(np.count_nonzero(cv2.bitwise_and(mask, cv2.cvtColor(cleaned, cv2.COLOR_RGB2GRAY)))),
            "verdict": "blocked" if failures else "pass",
        }
        reports.append(report)
        any_blocked |= bool(failures)
    deck = dict(base)
    deck["assets_dir"] = str(out_dir.resolve())
    deck["slides"] = slides
    write_json(out_dir / "deck-separated-editable.json", deck)
    write_json(out_dir / "qa" / "separation-report.json", {
        "schema_version": 1,
        "source_deck": str(source_deck.resolve()),
        "slide_count": len(slides),
        "routing_options": {
            "force_native_text": force_native_text,
            "native_title_text": native_title_text,
            "promote_analysis_shapes": promote_analysis_shapes,
            "promote_analysis_lines": promote_analysis_lines,
            "stable_native_only": stable_native_only,
            "fallback_slides": sorted(fallback_slides or set()),
        },
        "slides": reports,
        "blocking_slides": [r["slide_id"] for r in reports if r["verdict"] != "pass"],
        "verdict": "blocked" if any_blocked else "pass",
    })
    return {"slides": len(slides), "blocking_slides": [r["slide_id"] for r in reports if r["verdict"] != "pass"], "verdict": "blocked" if any_blocked else "pass"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_deck")
    parser.add_argument("source_root")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--force-native-text",
        action="store_true",
        help=(
            "Route every detected text row to native PowerPoint text. This is "
            "for max-editability audit rounds; stylized text may need visual "
            "repair after PowerPoint rendering."
        ),
    )
    parser.add_argument(
        "--native-title-text",
        action="store_true",
        help="Rebuild detected brush title bands as editable native text instead of bounded art-text PNGs.",
    )
    parser.add_argument(
        "--promote-analysis-shapes",
        action="store_true",
        help="Promote rectangle/rounded-rectangle candidates from each slide analysis.json into native shapes.",
    )
    parser.add_argument(
        "--promote-analysis-lines",
        action="store_true",
        help="Promote analysis line candidates only when their cleanup evidence already passed.",
    )
    parser.add_argument(
        "--stable-native-only",
        action="store_true",
        help=(
            "Use the visual-first native route: only high-confidence standalone "
            "text and high-excess-support geometry become native; uncertain "
            "embedded rows remain verified movable/background exceptions."
        ),
    )
    parser.add_argument(
        "--fallback-slides",
        default="",
        help="Comma-separated slide IDs routed through the verified visual-text fallback.",
    )
    args = parser.parse_args()
    fallback_slides = {
        value.strip().upper()
        for value in str(args.fallback_slides or "").split(",")
        if value.strip()
    }
    result = build_round(
        Path(args.source_deck).resolve(),
        Path(args.source_root).resolve(),
        Path(args.out_dir).resolve(),
        force_native_text=args.force_native_text,
        native_title_text=args.native_title_text,
        promote_analysis_shapes=args.promote_analysis_shapes,
        promote_analysis_lines=args.promote_analysis_lines,
        stable_native_only=args.stable_native_only,
        fallback_slides=fallback_slides,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
