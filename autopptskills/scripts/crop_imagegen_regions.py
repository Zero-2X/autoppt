#!/usr/bin/env python3
"""Crop independently movable assets from an imagegen-produced layer."""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

from PIL import Image


def _filter_alpha_components(image: Image.Image, keep_largest: bool, min_area: int,
                             alpha_threshold: int = 18) -> Image.Image:
    alpha = image.getchannel("A")
    width, height = alpha.size
    values = alpha.tobytes()
    visited = bytearray(width * height)
    components: list[list[int]] = []

    for start, value in enumerate(values):
        if visited[start] or value <= alpha_threshold:
            continue
        visited[start] = 1
        queue = deque([start])
        component: list[int] = []
        while queue:
            current = queue.popleft()
            component.append(current)
            x = current % width
            y = current // width
            for neighbor in (
                current - 1 if x > 0 else -1,
                current + 1 if x + 1 < width else -1,
                current - width if y > 0 else -1,
                current + width if y + 1 < height else -1,
            ):
                if neighbor >= 0 and not visited[neighbor] and values[neighbor] > alpha_threshold:
                    visited[neighbor] = 1
                    queue.append(neighbor)
        components.append(component)

    if not components:
        return image
    if keep_largest:
        kept = [max(components, key=len)]
    else:
        kept = [component for component in components if len(component) >= min_area]
    new_alpha = bytearray(width * height)
    for component in kept:
        for index in component:
            new_alpha[index] = values[index]
    result = image.copy()
    result.putalpha(Image.frombytes("L", (width, height), bytes(new_alpha)))
    return result


def _collect_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _collect_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _collect_strings(child)
    elif isinstance(value, str):
        yield value


def _manifest_contains(manifest: Path, image: Path) -> bool:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    resolved = image.resolve()
    for text in _collect_strings(data):
        try:
            candidate = Path(text)
            if candidate.is_absolute() and candidate.resolve() == resolved:
                return True
        except (OSError, ValueError):
            continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="Transparent/chroma-keyed imagegen layer.")
    parser.add_argument("regions_json", help="JSON containing regions[] with name and bbox [x,y,w,h].")
    parser.add_argument("out_dir")
    parser.add_argument("--manifest", help="Imagegen asset manifest used for provenance verification.")
    parser.add_argument("--padding", type=int, default=0)
    parser.add_argument("--trim-alpha", action="store_true",
                        help="Trim transparent margins after cropping; region-level trim_alpha overrides this default.")
    parser.add_argument("--report", help="Optional JSON report path.")
    args = parser.parse_args()

    image_path = Path(args.image)
    region_path = Path(args.regions_json)
    out_dir = Path(args.out_dir)
    if not image_path.exists():
        parser.error(f"image not found: {image_path}")
    if not region_path.exists():
        parser.error(f"regions JSON not found: {region_path}")
    if args.manifest:
        manifest = Path(args.manifest)
        if not manifest.exists():
            parser.error(f"manifest not found: {manifest}")
        if not _manifest_contains(manifest, image_path):
            parser.error("input image is not referenced by the imagegen manifest")

    spec = json.loads(region_path.read_text(encoding="utf-8"))
    regions = spec.get("regions")
    if not isinstance(regions, list) or not regions:
        parser.error("regions JSON must contain a non-empty regions[] list")

    out_dir.mkdir(parents=True, exist_ok=True)
    source = Image.open(image_path).convert("RGBA")
    width, height = source.size
    report = {
        "source": str(image_path.resolve()),
        "source_size": [width, height],
        "manifest": str(Path(args.manifest).resolve()) if args.manifest else None,
        "regions": [],
    }

    for index, region in enumerate(regions, 1):
        name = str(region.get("name") or f"region-{index:02d}")
        bbox = region.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            parser.error(f"region {name}: bbox must be [x,y,w,h]")
        x, y, w, h = (int(round(float(value))) for value in bbox)
        padding = int(region.get("padding", args.padding))
        left = max(0, x - padding)
        top = max(0, y - padding)
        right = min(width, x + w + padding)
        bottom = min(height, y + h + padding)
        if right <= left or bottom <= top:
            parser.error(f"region {name}: empty bbox after clamping")
        output = out_dir / str(region.get("output") or f"{name}.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        cropped = source.crop((left, top, right, bottom))
        keep_largest = bool(region.get("keep_largest_component", False))
        min_component_area = int(region.get("min_component_area", 0))
        if keep_largest or min_component_area > 0:
            cropped = _filter_alpha_components(cropped, keep_largest, min_component_area)
        trim_alpha = bool(region.get("trim_alpha", args.trim_alpha))
        if trim_alpha:
            alpha_bbox = cropped.getchannel("A").getbbox()
            if alpha_bbox:
                cropped = cropped.crop(alpha_bbox)
        cropped.save(output)
        report["regions"].append(
            {
                "name": name,
                "source_bbox": [left, top, right - left, bottom - top],
                "output": str(output.resolve()),
                "output_size": list(cropped.size),
                "trim_alpha": trim_alpha,
                "keep_largest_component": keep_largest,
                "min_component_area": min_component_area,
                "editability_level": region.get("editability_level", "movable-image"),
            }
        )

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
