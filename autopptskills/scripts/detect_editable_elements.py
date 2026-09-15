#!/usr/bin/env python3
"""Detect editable text, simple geometry, connectors, and flat icon candidates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe(child) for child in value]
    if isinstance(value, tuple):
        return [_json_safe(child) for child in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _bbox_iou(a: list[int], b: list[int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    return intersection / float(max(1, aw * ah + bw * bh - intersection))


def _bbox_overlap(a: list[int], b: list[int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0.0
    return ((right - left) * (bottom - top)) / float(max(1, aw * ah))


def _dedupe(items: list[dict[str, Any]], threshold: float = 0.82) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda entry: entry["bbox"][2] * entry["bbox"][3], reverse=True):
        if any(_bbox_iou(item["bbox"], prior["bbox"]) >= threshold for prior in kept):
            continue
        kept.append(item)
    return kept


def _hex_color(rgb: np.ndarray, fallback: str = "#111111") -> str:
    if rgb.size != 3 or not np.isfinite(rgb).all():
        return fallback
    values = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    return "#" + "".join(f"{int(value):02X}" for value in values)


def _contrast_color(image_rgb: np.ndarray, bbox: list[int]) -> str:
    x, y, w, h = bbox
    crop = image_rgb[y:y + h, x:x + w]
    if crop.size == 0:
        return "#111111"
    border = np.concatenate((crop[0], crop[-1], crop[:, 0], crop[:, -1]), axis=0)
    background = np.median(border.astype(np.float32), axis=0)
    distances = np.linalg.norm(crop.astype(np.float32) - background, axis=2)
    threshold = max(22.0, float(np.percentile(distances, 72)))
    foreground = crop[distances >= threshold]
    if foreground.shape[0] < 8:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        background_luma = float(np.mean(cv2.cvtColor(border.reshape(-1, 1, 3), cv2.COLOR_RGB2GRAY)))
        foreground = crop[gray < background_luma - 24] if background_luma > 128 else crop[gray > background_luma + 24]
    if foreground.shape[0] < 8:
        return "#111111" if float(np.mean(background)) > 145 else "#FFFFFF"
    return _hex_color(np.median(foreground.astype(np.float32), axis=0))


def _line_color(image_rgb: np.ndarray, bbox: list[int]) -> str:
    x, y, w, h = bbox
    pad = 2
    crop = image_rgb[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
    if crop.size == 0:
        return "#356A61"
    pixels = crop.reshape(-1, 3).astype(np.float32)
    saturation = pixels.max(axis=1) - pixels.min(axis=1)
    selected = pixels[saturation >= np.percentile(saturation, 65)]
    if selected.shape[0] < 8:
        luminance = pixels.mean(axis=1)
        selected = pixels[np.abs(luminance - np.median(luminance)) >= np.percentile(np.abs(luminance - np.median(luminance)), 70)]
    return _hex_color(np.median(selected if selected.shape[0] else pixels, axis=0), "#356A61")


def _font_size_pt(box_height: int, image_height: int) -> float:
    line_box_pt = (box_height / float(image_height)) * 7.5 * 72.0
    return round(max(8.0, min(96.0, line_box_pt * 0.82)), 1)


def _gray_entropy(crop: np.ndarray) -> float:
    if crop.size == 0:
        return 8.0
    histogram = cv2.calcHist([crop], [0], None, [32], [0, 256]).ravel()
    probabilities = histogram[histogram > 0] / max(1.0, histogram.sum())
    return float(-(probabilities * np.log2(probabilities)).sum())


def _flatness_features(crop_rgb: np.ndarray) -> dict[str, float]:
    if crop_rgb.size == 0:
        return {"score": 0.0, "entropy": 8.0, "palette90": 999.0, "edge_density": 1.0}
    small = cv2.resize(crop_rgb, (min(96, crop_rgb.shape[1]), min(96, crop_rgb.shape[0])), interpolation=cv2.INTER_AREA)
    quantized = (small // 32).reshape(-1, 3)
    _, counts = np.unique(quantized, axis=0, return_counts=True)
    counts = np.sort(counts)[::-1]
    palette90 = int(np.searchsorted(np.cumsum(counts), counts.sum() * 0.90) + 1)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    histogram = cv2.calcHist([gray], [0], None, [32], [0, 256]).ravel()
    probabilities = histogram[histogram > 0] / max(1.0, histogram.sum())
    entropy = float(-(probabilities * np.log2(probabilities)).sum())
    edges = cv2.Canny(gray, 60, 160)
    edge_density = float(np.count_nonzero(edges)) / float(edges.size)
    border = np.concatenate((small[0], small[-1], small[:, 0], small[:, -1]), axis=0).astype(np.float32)
    border_std = float(np.mean(np.std(border, axis=0)))
    palette_score = 1.0 - min(1.0, palette90 / 18.0)
    entropy_score = 1.0 - min(1.0, entropy / 5.0)
    edge_score = max(0.0, 1.0 - abs(edge_density - 0.13) / 0.17)
    border_score = 1.0 - min(1.0, border_std / 65.0)
    score = 0.35 * palette_score + 0.25 * entropy_score + 0.22 * edge_score + 0.18 * border_score
    return _json_safe({
        "score": round(float(score), 4),
        "entropy": round(entropy, 4),
        "palette90": float(palette90),
        "edge_density": round(edge_density, 4),
        "border_std": round(border_std, 4),
    })


def _detect_text(image_rgb: np.ndarray, languages: list[str], min_confidence: float) -> tuple[list[dict[str, Any]], str]:
    try:
        import easyocr
    except ImportError as exc:
        raise RuntimeError("EasyOCR is required for automatic text extraction") from exc

    reader = easyocr.Reader(languages, gpu=False, verbose=False)
    raw = reader.readtext(image_rgb, detail=1, paragraph=False, width_ths=0.7, mag_ratio=1.25)
    height, width = image_rgb.shape[:2]
    texts: list[dict[str, Any]] = []
    for index, (points, value, confidence) in enumerate(raw, 1):
        xs = [int(round(float(point[0]))) for point in points]
        ys = [int(round(float(point[1]))) for point in points]
        x1, y1 = max(0, min(xs)), max(0, min(ys))
        x2, y2 = min(width, max(xs)), min(height, max(ys))
        if x2 - x1 < 5 or y2 - y1 < 5 or float(confidence) < min_confidence:
            continue
        bbox = [x1, y1, x2 - x1, y2 - y1]
        center = x1 + (x2 - x1) / 2.0
        align = "center" if (bbox[2] >= width * 0.24 or abs(center - width / 2.0) <= width * 0.055) else "left"
        size = _font_size_pt(bbox[3], height)
        texts.append({
            "id": f"text-{index:03d}",
            "text": str(value).strip(),
            "confidence": round(float(confidence), 4),
            "bbox": bbox,
            "source_bbox": bbox,
            "font": "Microsoft YaHei",
            "size": size,
            "color": _contrast_color(image_rgb, bbox),
            "bold": bool(size >= 22 or bbox[3] >= height * 0.045),
            "align": align,
            "valign": "middle",
            "fit": "shrink",
            "margin_top": 0,
            "margin_right": 0,
            "margin_bottom": 0,
            "margin_left": 0,
            "char_spacing": 0,
            "needs_review": bool(float(confidence) < 0.72),
            "name": f"editable-text-{index:03d}",
        })
    return texts, "EasyOCR"


def _detect_geometry(image_rgb: np.ndarray, texts: list[dict[str, Any]], max_shapes: int, max_lines: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[tuple[int, int]]]:
    height, width = image_rgb.shape[:2]
    area_total = width * height
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(gray, 55, 155)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    rectangles: list[dict[str, Any]] = []
    triangle_centers: list[tuple[int, int]] = []

    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        if perimeter < 30:
            continue
        approx = cv2.approxPolyDP(contour, 0.018 * perimeter, True)
        x, y, w, h = cv2.boundingRect(contour)
        bbox = [int(x), int(y), int(w), int(h)]
        box_area = w * h
        contour_area = abs(float(cv2.contourArea(contour)))
        if len(approx) == 3 and 18 <= contour_area <= area_total * 0.006:
            triangle_centers.append((x + w // 2, y + h // 2))
        area_ratio = box_area / float(area_total)
        if area_ratio < 0.0022 or area_ratio > 0.70:
            continue
        if w < 35 or h < 22 or w / max(1, h) > 24 or h / max(1, w) > 24:
            continue
        rectangularity = contour_area / float(max(1, box_area))
        if len(approx) not in range(4, 11) or rectangularity < 0.48:
            continue
        aspect = max(w / max(1, h), h / max(1, w))
        is_label_or_header = y < height * 0.43 and (aspect >= 2.5 or area_ratio >= 0.006)
        is_panel_or_card = area_ratio >= 0.026
        if not (is_label_or_header or is_panel_or_card):
            continue
        if any(_bbox_iou(bbox, text["bbox"]) > 0.70 for text in texts):
            continue
        rectangles.append({
            "id": "",
            "type": "rounded_rect" if len(approx) > 4 else "rect",
            "bbox": bbox,
            "source_bbox": bbox,
            "fill": None,
            "opacity": 0.0,
            "line": _line_color(image_rgb, bbox),
            "line_width": 1.2,
            "confidence": round(min(0.96, 0.55 + rectangularity * 0.4), 4),
        })

    rectangles = _dedupe(rectangles)[:max_shapes]
    for index, item in enumerate(rectangles, 1):
        item["id"] = f"shape-{index:03d}"
        item["name"] = f"native-{item['type']}-{index:03d}"

    line_edges = edges.copy()
    for text in texts:
        x, y, w, h = text["bbox"]
        cv2.rectangle(line_edges, (max(0, x - 2), max(0, y - 2)), (min(width - 1, x + w + 2), min(height - 1, y + h + 2)), 0, -1)
    for shape in rectangles:
        x, y, w, h = shape["bbox"]
        cv2.rectangle(line_edges, (x, y), (x + w, y + h), 0, max(3, int(round(height / 300))))

    raw_lines = cv2.HoughLinesP(
        line_edges,
        1,
        np.pi / 180,
        threshold=max(26, int(width * 0.018)),
        minLineLength=max(35, int(width * 0.045)),
        maxLineGap=max(8, int(width * 0.008)),
    )
    candidates: list[dict[str, Any]] = []
    if raw_lines is not None:
        for values in raw_lines[:, 0, :]:
            x1, y1, x2, y2 = (int(value) for value in values)
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < width * 0.045:
                continue
            angle = abs(math.degrees(math.atan2(dy, dx))) % 180
            axis_distance = min(angle, abs(angle - 90), abs(angle - 180))
            if axis_distance > 12 and length < width * 0.12:
                continue
            left, top = min(x1, x2), min(y1, y2)
            bbox = [left, top, max(1, abs(dx)), max(1, abs(dy))]
            if any(_bbox_overlap([left, top, max(2, abs(dx)), max(2, abs(dy))], text["bbox"]) > 0.35 for text in texts):
                continue
            pad = max(5, int(round(height / 180)))
            texture = gray[max(0, top - pad):min(height, top + max(2, abs(dy)) + pad), max(0, left - pad):min(width, left + max(2, abs(dx)) + pad)]
            texture_entropy = _gray_entropy(texture)
            texture_edges = cv2.Canny(texture, 60, 160) if texture.size else texture
            texture_edge_density = float(np.count_nonzero(texture_edges)) / float(max(1, texture_edges.size))
            if texture_entropy > 4.6 and texture_edge_density > 0.115:
                continue
            near_border = left <= width * 0.025 or top <= height * 0.025 or left + abs(dx) >= width * 0.975 or top + abs(dy) >= height * 0.975
            proximity = max(18.0, width * 0.018)
            begin_arrow = any(math.hypot(x1 - tx, y1 - ty) <= proximity for tx, ty in triangle_centers)
            end_arrow = any(math.hypot(x2 - tx, y2 - ty) <= proximity for tx, ty in triangle_centers)
            candidates.append({
                "id": "",
                "type": "connector" if begin_arrow or end_arrow else "line",
                "bbox": bbox,
                "source_bbox": bbox,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "line": _line_color(image_rgb, [left, top, max(2, abs(dx)), max(2, abs(dy))]),
                "line_width": 1.2,
                "begin_arrow": "triangle" if begin_arrow else None,
                "end_arrow": "triangle" if end_arrow else None,
                "confidence": 0.68 if begin_arrow or end_arrow else 0.61,
                "length": round(length, 2),
                "angle": round(math.degrees(math.atan2(dy, dx)), 2),
                "texture_entropy": round(texture_entropy, 3),
                "texture_edge_density": round(texture_edge_density, 4),
                "near_border": bool(near_border),
                "rank_score": round((2.0 if begin_arrow or end_arrow else 0.0) + length / width - (0.7 if near_border else 0.0) - texture_entropy * 0.05, 4),
            })

    deduped_lines: list[dict[str, Any]] = []
    for item in sorted(candidates, key=lambda entry: entry["rank_score"], reverse=True):
        mx = (item["x1"] + item["x2"]) / 2.0
        my = (item["y1"] + item["y2"]) / 2.0
        duplicate = False
        for prior in deduped_lines:
            pmx = (prior["x1"] + prior["x2"]) / 2.0
            pmy = (prior["y1"] + prior["y2"]) / 2.0
            if math.hypot(mx - pmx, my - pmy) <= max(8, width * 0.008) and abs(item["angle"] - prior["angle"]) <= 5:
                duplicate = True
                break
        if not duplicate:
            deduped_lines.append(item)
        if len(deduped_lines) >= max_lines:
            break
    for index, item in enumerate(deduped_lines, 1):
        item["id"] = f"line-{index:03d}"
        item["name"] = f"native-{item['type']}-{index:03d}"
    return rectangles, deduped_lines, triangle_centers


def _align_texts_to_containers(texts: list[dict[str, Any]], shapes: list[dict[str, Any]], width: int, height: int) -> None:
    for text in texts:
        x, y, w, h = text["bbox"]
        center_x, center_y = x + w / 2.0, y + h / 2.0
        containers = []
        for shape in shapes:
            sx, sy, sw, sh = shape["bbox"]
            area_ratio = (sw * sh) / float(width * height)
            if area_ratio > 0.065:
                continue
            if sx <= center_x <= sx + sw and sy <= center_y <= sy + sh and w * h < sw * sh * 0.82:
                containers.append(shape)
        if not containers:
            continue
        container = min(containers, key=lambda item: item["bbox"][2] * item["bbox"][3])
        sx, sy, sw, sh = container["bbox"]
        inset_x = max(3, int(round(sw * 0.035)))
        inset_y = max(2, int(round(sh * 0.06)))
        text["ocr_bbox"] = text["bbox"]
        text["bbox"] = [sx + inset_x, sy + inset_y, max(1, sw - 2 * inset_x), max(1, sh - 2 * inset_y)]
        text["source_bbox"] = text["bbox"]
        text["align"] = "center"
        text["valign"] = "middle"
        text["container_shape_id"] = container["id"]


def _detect_icon_candidates(image_rgb: np.ndarray, texts: list[dict[str, Any]], shapes: list[dict[str, Any]], max_icons: int) -> list[dict[str, Any]]:
    height, width = image_rgb.shape[:2]
    area_total = width * height
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 170)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[dict[str, Any]] = []

    circles = cv2.HoughCircles(
        cv2.medianBlur(gray, 5), cv2.HOUGH_GRADIENT, dp=1.25, minDist=max(28, width // 30),
        param1=110, param2=32, minRadius=max(10, height // 80), maxRadius=max(25, height // 9),
    )
    circle_boxes: list[list[int]] = []
    if circles is not None:
        for cx, cy, radius in np.rint(circles[0]).astype(int):
            left = max(0, int(cx - radius - 4))
            top = max(0, int(cy - radius - 4))
            bbox = [left, top, min(width - left, int(2 * radius + 8)), min(height - top, int(2 * radius + 8))]
            if bbox[2] * bbox[3] > area_total * 0.025 or bbox[2] > width * 0.10 or bbox[3] > height * 0.16:
                continue
            ring = np.zeros_like(edges)
            cv2.circle(ring, (int(cx), int(cy)), int(radius), 255, max(2, int(round(radius * 0.08))))
            ring_pixels = np.count_nonzero(ring)
            ring_support = float(np.count_nonzero((edges > 0) & (ring > 0))) / float(max(1, ring_pixels))
            if ring_support >= 0.16:
                circle_boxes.append([int(value) for value in bbox])

    boxes: list[tuple[list[int], bool]] = [(bbox, True) for bbox in circle_boxes]
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        box_area = w * h
        if not (area_total * 0.00035 <= box_area <= area_total * 0.025):
            continue
        if w < 18 or h < 18 or w / max(1, h) > 4.0 or h / max(1, w) > 4.0:
            continue
        boxes.append(([int(x), int(y), int(w), int(h)], False))

    for bbox, is_circle in boxes:
        if bbox[2] > width * 0.10 or bbox[3] > height * 0.16:
            continue
        if any(_bbox_overlap(bbox, text["bbox"]) > 0.15 for text in texts):
            continue
        if any(_bbox_iou(bbox, shape["bbox"]) > 0.72 for shape in shapes):
            continue
        x, y, w, h = bbox
        features = _flatness_features(image_rgb[y:y + h, x:x + w])
        inside_small_container = any(
            _bbox_overlap(bbox, shape["bbox"]) >= 0.92
            and bbox[2] * bbox[3] <= shape["bbox"][2] * shape["bbox"][3] * 0.30
            for shape in shapes
        )
        if not is_circle and not inside_small_container:
            continue
        score = max(features["score"], 0.70 if is_circle and features["score"] >= 0.48 else 0.0)
        if score < (0.66 if is_circle else 0.74):
            continue
        candidates.append({
            "id": "",
            "bbox": bbox,
            "source_bbox": bbox,
            "confidence": round(score, 4),
            "traceable": bool(score >= 0.60),
            "candidate_kind": "circular-flat-icon" if is_circle else "flat-icon",
            "features": features,
        })

    candidates = _dedupe(candidates, 0.65)
    candidates = sorted(candidates, key=lambda entry: entry["confidence"], reverse=True)[:max_icons]
    for index, item in enumerate(candidates, 1):
        item["id"] = f"icon-{index:03d}"
        item["name"] = f"vector-svg::{item['id']}"
    return candidates


def analyze_image(
    image_path: Path,
    languages: list[str] | None = None,
    min_ocr_confidence: float = 0.35,
    max_shapes: int = 80,
    max_lines: int = 32,
    max_icons: int = 24,
) -> dict[str, Any]:
    image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise FileNotFoundError(f"unable to read image: {image_path}")
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    height, width = image_rgb.shape[:2]
    texts, ocr_engine = _detect_text(image_rgb, languages or ["ch_sim", "en"], min_ocr_confidence)
    shapes, lines, _ = _detect_geometry(image_rgb, texts, max_shapes, max_lines)
    _align_texts_to_containers(texts, shapes, width, height)
    icons = _detect_icon_candidates(image_rgb, texts, shapes, max_icons)
    unresolved: list[dict[str, Any]] = []
    for item in texts:
        if item["needs_review"]:
            unresolved.append({"id": item["id"], "kind": "text", "reason": "ocr-needs-review", "confidence": item["confidence"]})
    for item in icons:
        if not item["traceable"]:
            unresolved.append({"id": item["id"], "kind": "icon", "reason": "flatness-below-trace-threshold", "confidence": item["confidence"]})

    native_area = sum(item["bbox"][2] * item["bbox"][3] for item in texts + shapes)
    return _json_safe({
        "source": str(image_path.resolve()),
        "size": {"width": width, "height": height},
        "ocr_engine": ocr_engine,
        "texts": texts,
        "shapes": shapes,
        "lines": lines,
        "icon_candidates": icons,
        "unresolved": unresolved,
        "summary": {
            "text_count": len(texts),
            "shape_count": len(shapes),
            "line_count": len(lines),
            "icon_candidate_count": len(icons),
            "review_text_count": sum(1 for item in texts if item["needs_review"]),
            "rough_native_area_ratio": round(native_area / float(width * height), 4),
        },
    })


def draw_overlay(image_path: Path, analysis: dict[str, Any], output: Path) -> None:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    colors = {"texts": (50, 205, 50), "shapes": (255, 120, 0), "lines": (0, 190, 255), "icon_candidates": (220, 0, 220)}
    for key in ("shapes", "icon_candidates", "texts"):
        for item in analysis[key]:
            x, y, w, h = item["bbox"]
            cv2.rectangle(image, (x, y), (x + w, y + h), colors[key], 2)
            cv2.putText(image, item["id"], (x, max(14, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colors[key], 1, cv2.LINE_AA)
    for item in analysis["lines"]:
        cv2.line(image, (item["x1"], item["y1"]), (item["x2"], item["y2"]), colors["lines"], 2)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), image)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--overlay")
    parser.add_argument("--languages", default="ch_sim,en")
    parser.add_argument("--min-ocr-confidence", type=float, default=0.35)
    parser.add_argument("--max-shapes", type=int, default=80)
    parser.add_argument("--max-lines", type=int, default=32)
    parser.add_argument("--max-icons", type=int, default=24)
    args = parser.parse_args()

    image_path = Path(args.image)
    analysis = analyze_image(
        image_path,
        languages=[value.strip() for value in args.languages.split(",") if value.strip()],
        min_ocr_confidence=args.min_ocr_confidence,
        max_shapes=args.max_shapes,
        max_lines=args.max_lines,
        max_icons=args.max_icons,
    )
    output = Path(args.json_out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.overlay:
        draw_overlay(image_path, analysis, Path(args.overlay))
    print(json.dumps(analysis["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
