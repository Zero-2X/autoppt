#!/usr/bin/env python3
"""Create text-cleaned slide backgrounds for editable overlays.

This is a bounded post-imagegen cleanup step. It starts from the verified source
slide image, removes only reviewed native-text regions, and records the mask and
method for every slide. It never redraws the page or invents visual content.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def valid_bbox(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(
        isinstance(v, (int, float)) for v in value
    ) and float(value[2]) > 0 and float(value[3]) > 0


def bbox(item: dict[str, Any]) -> list[int] | None:
    for key in ("source_bbox", "ocr_bbox", "layout_bbox"):
        value = item.get(key)
        if valid_bbox(value):
            return [int(round(float(v))) for v in value]
    return None


def solid_fill_or_inpaint(image: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, str]:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return image, "none"
    # A small rectangle around a text run on a flat card is better restored by
    # a sampled local colour than by Telea, which can leave halo-shaped glyphs.
    border = cv2.dilate(mask, np.ones((9, 9), np.uint8), iterations=1)
    border = cv2.subtract(border, mask)
    pixels = image[border > 0].astype(np.float32)
    if len(pixels) >= 32:
        spread = float(np.mean(np.std(pixels, axis=0)))
        if spread < 18.0:
            colour = np.median(pixels, axis=0).astype(np.uint8)
            restored = image.copy()
            restored[mask > 0] = colour
            return restored, "flat-border-fill"
    return cv2.inpaint(image, mask, 5, cv2.INPAINT_NS), "navier-stokes-inpaint"


def cleanup_slide(source: Path, items: list[dict[str, Any]], output: Path, mask_output: Path) -> dict[str, Any]:
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(source)
    height, width = image.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    rows: list[dict[str, Any]] = []
    for item in items:
        if item.get("keep_in_background") or item.get("background_text") is True:
            continue
        box = bbox(item)
        if not box:
            continue
        x, y, w, h = box
        # Keep the cleanup local: 3 px around the glyph evidence is enough to
        # remove antialiasing while avoiding borders, icons and photographs.
        pad_x = max(3, min(8, int(round(w * 0.025))))
        pad_y = max(3, min(6, int(round(h * 0.10))))
        left = max(0, x - pad_x)
        top = max(0, y - pad_y)
        right = min(width - 1, x + w + pad_x)
        bottom = min(height - 1, y + h + pad_y)
        cv2.rectangle(mask, (left, top), (right, bottom), 255, -1)
        rows.append({"text_id": item.get("id"), "bbox": [left, top, right - left, bottom - top]})
    # A single pass avoids seams where adjacent text boxes touch.
    cleaned, method = solid_fill_or_inpaint(image, mask)
    output.parent.mkdir(parents=True, exist_ok=True)
    mask_output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), cleaned)
    cv2.imwrite(str(mask_output), mask)
    return {
        "source": str(source.resolve()),
        "output": str(output.resolve()),
        "mask": str(mask_output.resolve()),
        "method": method,
        "masked_pixel_ratio": round(float(np.count_nonzero(mask)) / float(mask.size), 6),
        "text_regions": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--slides", nargs="*", default=[])
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    deck = read_json(Path(args.deck).resolve())
    source_dir = Path(args.source_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    wanted = set(args.slides)
    report: dict[str, Any] = {"deck": str(Path(args.deck).resolve()), "slides": []}
    for slide in deck.get("slides", []):
        slide_id = str(slide.get("slide_id") or "")
        if wanted and slide_id not in wanted:
            continue
        source = source_dir / "assets" / "slides" / f"{slide_id}.png"
        output = out_dir / slide_id / "background.png"
        mask = out_dir / slide_id / "text-cleanup-mask.png"
        row = cleanup_slide(source, list(slide.get("texts") or []), output, mask)
        row["slide_id"] = slide_id
        report["slides"].append(row)
    write_json(Path(args.report).resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
