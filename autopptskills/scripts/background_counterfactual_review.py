#!/usr/bin/env python3
"""Generate foreground-hidden background views for mandatory manual review.

The script never decides whether a background is semantically clean. It creates
hash-bound normal, global-stretch, signed high-pass, and enlarged grid crops so
the reviewer can detect text, frames, arrows, nodes, asset silhouettes, and
structured repair ghosts that are easy to miss in the ordinary image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, ImageOps


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def signed_highpass(image: Image.Image, *, gain: float, blur_radius: float) -> Image.Image:
    rgb = image.convert("RGB")
    source = np.asarray(rgb, dtype=np.int16)
    blurred = np.asarray(rgb.filter(ImageFilter.GaussianBlur(blur_radius)), dtype=np.int16)
    amplified = np.clip(128.0 + (source - blurred) * gain, 0, 255).astype(np.uint8)
    return Image.fromarray(amplified, mode="RGB")


def save_image(path: Path, image: Image.Image) -> dict[str, Any]:
    image.save(path)
    return {
        "file": path.name,
        "sha256": sha256_file(path),
        "dimensions": [image.width, image.height],
    }


def generate_review_views(
    image_path: Path,
    out_dir: Path,
    *,
    gain: float = 16.0,
    blur_radius: float = 8.0,
    grid_cols: int = 2,
    grid_rows: int = 2,
    crop_scale: int = 2,
) -> Path:
    image_path = image_path.resolve()
    out_dir = out_dir.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"counterfactual review output already contains files: {out_dir}")
    if gain <= 0 or blur_radius <= 0:
        raise ValueError("gain and blur radius must be positive")
    if grid_cols <= 0 or grid_rows <= 0 or crop_scale <= 0:
        raise ValueError("grid dimensions and crop scale must be positive")
    out_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(image_path) as opened:
        opened.load()
        normal = opened.convert("RGB")
    stretch = ImageOps.autocontrast(normal)
    highpass = signed_highpass(normal, gain=gain, blur_radius=blur_radius)

    evidence: list[dict[str, Any]] = []
    evidence.append(save_image(out_dir / "background-normal.png", normal))
    evidence.append(save_image(out_dir / "background-global-contrast-stretch.png", stretch))
    evidence.append(
        save_image(
            out_dir / f"background-highpass-gain{gain:g}.png",
            highpass,
        )
    )

    crops: list[dict[str, Any]] = []
    resampling = Image.Resampling.NEAREST
    for row in range(grid_rows):
        y0 = round(row * normal.height / grid_rows)
        y1 = round((row + 1) * normal.height / grid_rows)
        for col in range(grid_cols):
            x0 = round(col * normal.width / grid_cols)
            x1 = round((col + 1) * normal.width / grid_cols)
            bbox = (x0, y0, x1, y1)
            prefix = f"crop-r{row + 1:02d}-c{col + 1:02d}"
            row_evidence = []
            for label, source in (
                ("normal", normal),
                ("stretch", stretch),
                (f"highpass-gain{gain:g}", highpass),
            ):
                crop = source.crop(bbox).resize(
                    ((x1 - x0) * crop_scale, (y1 - y0) * crop_scale),
                    resampling,
                )
                row_evidence.append(save_image(out_dir / f"{prefix}-{label}-{crop_scale}x.png", crop))
            crops.append(
                {
                    "row": row + 1,
                    "column": col + 1,
                    "bbox": [x0, y0, x1 - x0, y1 - y0],
                    "scale": crop_scale,
                    "evidence": row_evidence,
                }
            )

    report = {
        "schema_version": 1,
        "input": os.path.relpath(image_path, out_dir).replace("\\", "/"),
        "input_sha256": sha256_file(image_path),
        "input_dimensions": [normal.width, normal.height],
        "review_scope": "foreground-hidden continuous-background counterfactual inspection",
        "highpass": {
            "method": "signed RGB difference from Gaussian low-pass on neutral gray",
            "gain": gain,
            "blur_radius": blur_radius,
        },
        "global_evidence": evidence,
        "grid": {"columns": grid_cols, "rows": grid_rows, "crops": crops},
        "manual_review": {
            "status": "pending",
            "required_checks": [
                "no semantic text or glyph residue",
                "no card, frame, divider, arrow, connector, or node footprint",
                "no bounded-asset silhouette that should be independently movable",
                "no structured inpainting rectangle, seam, or repeated interpolation pattern",
                "all retained marks are explicitly identified as non-semantic background design",
            ],
            "notes": "",
        },
        "verdict": "pending",
    }
    report_path = out_dir / "background-counterfactual-evidence.json"
    write_json(report_path, report)
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--gain", type=float, default=16.0)
    parser.add_argument("--blur-radius", type=float, default=8.0)
    parser.add_argument("--grid-cols", type=int, default=2)
    parser.add_argument("--grid-rows", type=int, default=2)
    parser.add_argument("--crop-scale", type=int, default=2)
    args = parser.parse_args()
    report = generate_review_views(
        Path(args.image),
        Path(args.out_dir),
        gain=args.gain,
        blur_radius=args.blur_radius,
        grid_cols=args.grid_cols,
        grid_rows=args.grid_rows,
        crop_scale=args.crop_scale,
    )
    print(json.dumps({"report": str(report), "verdict": "pending"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
