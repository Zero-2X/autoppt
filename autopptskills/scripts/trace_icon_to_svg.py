#!/usr/bin/env python3
"""Trace a small flat raster icon into a bounded-complexity SVG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _entropy(gray: np.ndarray) -> float:
    histogram = cv2.calcHist([gray], [0], None, [64], [0, 256]).ravel()
    probabilities = histogram[histogram > 0] / max(1.0, histogram.sum())
    return float(-(probabilities * np.log2(probabilities)).sum())


def _border_pixels(image: np.ndarray) -> np.ndarray:
    return np.concatenate((image[0], image[-1], image[:, 0], image[:, -1]), axis=0)


def _foreground_mask(image_bgra: np.ndarray, threshold: float | None) -> tuple[np.ndarray, np.ndarray, float]:
    alpha = image_bgra[:, :, 3]
    rgb = cv2.cvtColor(image_bgra[:, :, :3], cv2.COLOR_BGR2RGB)
    if np.count_nonzero(alpha < 250) > alpha.size * 0.02:
        mask = np.where(alpha > 20, 255, 0).astype(np.uint8)
        background = np.array([255.0, 255.0, 255.0], dtype=np.float32)
        return mask, background, float(threshold or 0.0)

    border = _border_pixels(rgb).astype(np.float32)
    background = np.median(border, axis=0)
    distances = np.linalg.norm(rgb.astype(np.float32) - background, axis=2)
    if threshold is None:
        border_distances = np.linalg.norm(border - background, axis=1)
        threshold = max(18.0, float(np.percentile(border_distances, 94)) + 10.0)
    mask = np.where(distances >= threshold, 255, 0).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return mask, background, float(threshold)


def _path_from_contour(contour: np.ndarray, epsilon_ratio: float) -> str | None:
    perimeter = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, max(0.7, epsilon_ratio * perimeter), True)
    points = approx.reshape(-1, 2)
    if len(points) < 3:
        return None
    commands = [f"M {int(points[0][0])} {int(points[0][1])}"]
    commands.extend(f"L {int(point[0])} {int(point[1])}" for point in points[1:])
    commands.append("Z")
    return " ".join(commands)


def _hex(rgb: np.ndarray) -> str:
    values = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    return "#" + "".join(f"{int(value):02X}" for value in values)


def trace_icon(
    image_path: Path,
    output_path: Path,
    bbox: list[int] | None = None,
    max_paths: int = 32,
    max_colors: int = 3,
    min_component_area: int = 8,
    epsilon_ratio: float = 0.012,
    foreground_threshold: float | None = None,
    force: bool = False,
    mask_output: Path | None = None,
) -> dict[str, Any]:
    source = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if source is None:
        raise FileNotFoundError(f"unable to read image: {image_path}")
    if source.ndim == 2:
        source = cv2.cvtColor(source, cv2.COLOR_GRAY2BGRA)
    elif source.shape[2] == 3:
        source = cv2.cvtColor(source, cv2.COLOR_BGR2BGRA)

    source_height, source_width = source.shape[:2]
    used_bbox = [0, 0, source_width, source_height]
    if bbox:
        x, y, width, height = bbox
        x = max(0, min(source_width - 1, int(x)))
        y = max(0, min(source_height - 1, int(y)))
        width = max(1, min(source_width - x, int(width)))
        height = max(1, min(source_height - y, int(height)))
        used_bbox = [x, y, width, height]
        source = source[y:y + height, x:x + width]

    height, width = source.shape[:2]
    mask, background, used_threshold = _foreground_mask(source, foreground_threshold)
    if mask_output is not None:
        mask_output.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(mask_output), mask)
    foreground_pixels = int(np.count_nonzero(mask))
    foreground_ratio = foreground_pixels / float(max(1, mask.size))
    gray = cv2.cvtColor(source[:, :, :3], cv2.COLOR_BGR2GRAY)
    entropy = _entropy(gray)
    edge_density = float(np.count_nonzero(cv2.Canny(gray, 60, 160))) / float(max(1, gray.size))

    rejection_reasons: list[str] = []
    if foreground_ratio < 0.004:
        rejection_reasons.append("foreground-too-small")
    if foreground_ratio > 0.74:
        rejection_reasons.append("foreground-too-large")
    if entropy > 5.65 and edge_density > 0.20:
        rejection_reasons.append("photo-like-complexity")

    pixels_rgb = cv2.cvtColor(source[:, :, :3], cv2.COLOR_BGR2RGB)[mask > 0].astype(np.float32)
    if pixels_rgb.shape[0] == 0:
        pixels_rgb = np.array([[32.0, 32.0, 32.0]], dtype=np.float32)
    sample = pixels_rgb
    if sample.shape[0] > 12000:
        indices = np.linspace(0, sample.shape[0] - 1, 12000).astype(int)
        sample = sample[indices]
    quantized = (sample.astype(np.uint8) // 32).astype(np.uint8)
    palette_count = int(np.unique(quantized, axis=0).shape[0])
    cluster_count = max(1, min(max_colors, palette_count))
    if palette_count > 64 and entropy > 5.2:
        rejection_reasons.append("too-many-colors")

    paths: list[tuple[str, str]] = []
    contour_count = 0
    if not rejection_reasons or force:
        if cluster_count == 1 or pixels_rgb.shape[0] < cluster_count * 8:
            centers = np.array([np.median(pixels_rgb, axis=0)], dtype=np.float32)
            label_map = np.zeros(mask.shape, dtype=np.int32)
            label_map[mask > 0] = 1
        else:
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
            _, labels, centers = cv2.kmeans(sample, cluster_count, None, criteria, 4, cv2.KMEANS_PP_CENTERS)
            full_pixels = cv2.cvtColor(source[:, :, :3], cv2.COLOR_BGR2RGB).astype(np.float32)
            distances = np.linalg.norm(full_pixels[:, :, None, :] - centers[None, None, :, :], axis=3)
            label_map = np.argmin(distances, axis=2).astype(np.int32) + 1
            label_map[mask == 0] = 0

        for cluster_index, center in enumerate(centers, 1):
            if np.linalg.norm(center.astype(np.float32) - background.astype(np.float32)) < max(30.0, used_threshold * 1.35):
                continue
            cluster_mask = np.where(label_map == cluster_index, 255, 0).astype(np.uint8)
            cluster_mask = cv2.morphologyEx(cluster_mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
            contours, hierarchy = cv2.findContours(cluster_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            if hierarchy is None:
                continue
            color = _hex(center)
            cluster_paths: list[str] = []
            for contour in contours:
                if abs(cv2.contourArea(contour)) < min_component_area:
                    continue
                path = _path_from_contour(contour, epsilon_ratio)
                if path:
                    cluster_paths.append(path)
                    contour_count += 1
            if cluster_paths:
                paths.append((" ".join(cluster_paths), color))

    if contour_count > max_paths:
        rejection_reasons.append(f"path-count>{max_paths}")
    if contour_count == 0 and not rejection_reasons:
        rejection_reasons.append("no-vector-paths")
    accepted = (not rejection_reasons or force) and 0 < contour_count <= max_paths
    report = {
        "source": str(image_path.resolve()),
        "source_bbox": used_bbox,
        "output": str(output_path.resolve()),
        "accepted": accepted,
        "forced": force,
        "rejection_reasons": rejection_reasons,
        "width": width,
        "height": height,
        "foreground_ratio": round(foreground_ratio, 5),
        "foreground_threshold": round(used_threshold, 3),
        "background_rgb": [round(float(value), 2) for value in background],
        "entropy": round(entropy, 4),
        "edge_density": round(edge_density, 4),
        "palette_count_quantized": palette_count,
        "color_clusters": cluster_count,
        "path_count": contour_count,
        "svg_path_elements": len(paths),
        "editability_level": "convertible-vector" if accepted else "movable-image",
        "mask_output": str(mask_output.resolve()) if mask_output is not None else None,
    }
    if not accepted:
        return report

    svg_paths = "\n  ".join(
        f'<path d="{path_data}" fill="{color}" fill-rule="evenodd"/>' for path_data, color in paths
    )
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
        f'  {svg_paths}\n'
        '</svg>\n'
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("output")
    parser.add_argument("--bbox", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    parser.add_argument("--max-paths", type=int, default=32)
    parser.add_argument("--max-colors", type=int, default=3)
    parser.add_argument("--min-component-area", type=int, default=8)
    parser.add_argument("--epsilon-ratio", type=float, default=0.012)
    parser.add_argument("--foreground-threshold", type=float)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mask-out")
    parser.add_argument("--report")
    args = parser.parse_args()

    report = trace_icon(
        Path(args.image),
        Path(args.output),
        bbox=args.bbox,
        max_paths=args.max_paths,
        max_colors=args.max_colors,
        min_component_area=args.min_component_area,
        epsilon_ratio=args.epsilon_ratio,
        foreground_threshold=args.foreground_threshold,
        force=args.force,
        mask_output=Path(args.mask_out) if args.mask_out else None,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
