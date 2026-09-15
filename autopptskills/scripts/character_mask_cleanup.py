#!/usr/bin/env python3
"""Build tight per-text masks, clean the background, and trace art glyphs.

The script uses the reviewed text color and the visible glyph bbox. It never
erases an entire OCR/container rectangle. Each character route receives an
individual raw mask, a controlled one-pixel dilation mask, cleanup evidence,
and (for stylized text) a bounded SVG contour candidate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_color(value: str) -> np.ndarray:
    text = str(value or "#000000").strip().lstrip("#")
    if len(text) != 6:
        text = "000000"
    return np.asarray([int(text[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.uint8)


def clamp_bbox(value: list[int], width: int, height: int, pad: int = 0) -> list[int]:
    x, y, w, h = [int(round(float(v))) for v in value]
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
    return [x0, y0, max(1, x1 - x0), max(1, y1 - y0)]


def color_mask(crop_rgb: np.ndarray, target_rgb: np.ndarray, threshold: float) -> np.ndarray:
    crop_lab = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    target = cv2.cvtColor(target_rgb.reshape(1, 1, 3), cv2.COLOR_RGB2LAB).reshape(3).astype(np.float32)
    distance = np.linalg.norm(crop_lab - target, axis=2)
    mask = (distance <= threshold).astype(np.uint8) * 255
    # Remove isolated one-pixel noise but retain thin antialiased strokes.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cleaned = np.zeros_like(mask)
    minimum = max(2, int(round(mask.size * 0.00002)))
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= minimum:
            cleaned[labels == label] = 255
    return cleaned


def contours_to_svg(mask: np.ndarray, color: str, path: Path, metadata: dict[str, Any]) -> int:
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    commands: list[str] = []
    accepted = 0
    for contour in contours:
        if abs(cv2.contourArea(contour)) < 2.0:
            continue
        epsilon = 0.35
        points = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        if len(points) < 3:
            continue
        commands.append("M " + " L ".join(f"{int(x)} {int(y)}" for x, y in points) + " Z")
        accepted += 1
    height, width = mask.shape
    payload = json.dumps(metadata, ensure_ascii=False).replace("&", "&amp;").replace("<", "&lt;")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f'<metadata>{payload}</metadata>\n'
        f'<path d="{" ".join(commands)}" fill="{color}" fill-rule="evenodd"/>\n'
        '</svg>\n'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return accepted


def glyph_bbox(item: dict[str, Any]) -> list[int]:
    return list(item.get("ocr_bbox") or item.get("source_bbox") or item.get("bbox"))


def process(source: Path, analysis_path: Path, out_dir: Path, threshold: float, dilation: int) -> dict[str, Any]:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"immutable output already contains files: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    image = np.asarray(Image.open(source).convert("RGB"))
    height, width = image.shape[:2]
    analysis = read_json(analysis_path)
    combined = np.zeros((height, width), dtype=np.uint8)
    rows = []
    for index, item in enumerate(analysis.get("texts", []), start=1):
        item_id = str(item.get("id") or f"text-{index:03d}")
        box = clamp_bbox(glyph_bbox(item), width, height, pad=2)
        x, y, w, h = box
        crop = image[y : y + h, x : x + w]
        raw = color_mask(crop, parse_color(item.get("color", "#000000")), threshold)
        kernel_size = max(1, dilation * 2 + 1)
        dilated = cv2.dilate(raw, np.ones((kernel_size, kernel_size), np.uint8), iterations=1)
        raw_path = out_dir / "character-mask" / f"{item_id}-raw.png"
        dilated_path = out_dir / "character-mask" / f"{item_id}-dilated.png"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(raw_path), raw)
        cv2.imwrite(str(dilated_path), dilated)
        combined[y : y + h, x : x + w] = cv2.bitwise_or(combined[y : y + h, x : x + w], dilated)
        source_support = float(np.count_nonzero(raw)) / max(1, raw.size)
        status = "pass" if np.count_nonzero(raw) >= 3 and source_support <= 0.48 else "fail"
        route = "vector-glyph" if item.get("art_text") or (float(item.get("size", 0) or 0) >= 38 and not item.get("container_shape_id")) else "native-text"
        vector_path = None
        contour_count = 0
        if route == "vector-glyph" and status == "pass":
            vector_path = out_dir / "vector-glyph" / f"{item_id}.svg"
            contour_count = contours_to_svg(
                raw,
                str(item.get("color") or "#000000"),
                vector_path,
                {"text": item.get("text", ""), "source_bbox": box, "route": route},
            )
            if contour_count == 0:
                status = "fail"
        rows.append({
            "id": item_id,
            "text": item.get("text", ""),
            "source_bbox": item.get("source_bbox") or item.get("bbox"),
            "ocr_bbox": item.get("ocr_bbox"),
            "glyph_bbox": box,
            "layout_bbox": item.get("layout_bbox"),
            "route": route,
            "raw_mask": str(raw_path.resolve()),
            "dilated_mask": str(dilated_path.resolve()),
            "masked_pixel_count": int(np.count_nonzero(raw)),
            "mask_area_ratio": round(source_support, 6),
            "vector_glyph": str(vector_path.resolve()) if vector_path else None,
            "vector_contour_count": contour_count,
            "cleanup_status": status,
        })
    combined_path = out_dir / "character-mask-combined.png"
    cv2.imwrite(str(combined_path), combined)
    cleaned_bgr = cv2.inpaint(cv2.cvtColor(image, cv2.COLOR_RGB2BGR), combined, 3, cv2.INPAINT_TELEA)
    cleaned_rgb = cv2.cvtColor(cleaned_bgr, cv2.COLOR_BGR2RGB)
    cleaned_path = out_dir / "clean-background-text-only.png"
    Image.fromarray(cleaned_rgb).save(cleaned_path)
    for row in rows:
        x, y, w, h = row["glyph_bbox"]
        target = parse_color(next(item.get("color", "#000000") for item in analysis["texts"] if item.get("id") == row["id"]))
        before = color_mask(image[y:y+h, x:x+w], target, threshold)
        after = color_mask(cleaned_rgb[y:y+h, x:x+w], target, threshold)
        before_count = max(1, int(np.count_nonzero(before)))
        row["post_cleanup_target_pixel_count"] = int(np.count_nonzero(after))
        row["residual_ratio"] = round(float(np.count_nonzero(after)) / before_count, 6)
        if row["cleanup_status"] == "pass" and row["residual_ratio"] > 0.42:
            row["cleanup_status"] = "fail"
    report = {
        "schema_version": 1,
        "source": str(source.resolve()),
        "analysis": str(analysis_path.resolve()),
        "dimensions": [width, height],
        "method": "tight-reviewed-color-mask-plus-1px-dilation-and-telea",
        "lab_distance_threshold": threshold,
        "dilation_px": dilation,
        "combined_mask": str(combined_path.resolve()),
        "clean_background": str(cleaned_path.resolve()),
        "text_count": len(rows),
        "pass_count": sum(row["cleanup_status"] == "pass" for row in rows),
        "fail_count": sum(row["cleanup_status"] != "pass" for row in rows),
        "verdict": "pass" if all(row["cleanup_status"] == "pass" for row in rows) else "blocked",
        "texts": rows,
    }
    write_json(out_dir / "character-cleanup-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("analysis")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--lab-threshold", type=float, default=36.0)
    parser.add_argument("--dilation", type=int, default=1)
    args = parser.parse_args()
    report = process(
        Path(args.source).resolve(),
        Path(args.analysis).resolve(),
        Path(args.out_dir).resolve(),
        args.lab_threshold,
        args.dilation,
    )
    print(json.dumps({
        "texts": report["text_count"],
        "pass": report["pass_count"],
        "fail": report["fail_count"],
        "verdict": report["verdict"],
        "report": str((Path(args.out_dir).resolve() / "character-cleanup-report.json")),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
