#!/usr/bin/env python3
"""Normalize an imagegen layer to the source slide canvas size.

Use this after imagegen when the generated layer is not exactly the same pixel
size as the source slide. The operation is whole-layer normalization only; do
not use it to crop local pieces from the original source image.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def normalize(source: Path, layer: Path, out: Path, mode: str) -> dict:
    with Image.open(source) as src_im:
        target = src_im.size
    im = Image.open(layer).convert("RGBA")
    original = im.size
    tw, th = target
    sw, sh = original

    if mode == "stretch":
        result = im.resize(target, Image.Resampling.LANCZOS)
    else:
        scale_fn = max if mode == "cover" else min
        scale = scale_fn(tw / sw, th / sh)
        nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
        resized = im.resize((nw, nh), Image.Resampling.LANCZOS)
        result = Image.new("RGBA", target, (0, 0, 0, 0))
        left = (tw - nw) // 2
        top = (th - nh) // 2
        if mode == "cover":
            crop_left = max(0, -left)
            crop_top = max(0, -top)
            cropped = resized.crop((crop_left, crop_top, crop_left + tw, crop_top + th))
            result.alpha_composite(cropped, (0, 0))
        else:
            result.alpha_composite(resized, (max(0, left), max(0, top)))

    out.parent.mkdir(parents=True, exist_ok=True)
    result.save(out)
    return {
        "source": str(source),
        "layer": str(layer),
        "out": str(out),
        "mode": mode,
        "original_size": list(original),
        "target_size": list(target),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Original source slide image.")
    parser.add_argument("layer", help="Generated layer image to normalize.")
    parser.add_argument("out", help="Output normalized layer path.")
    parser.add_argument(
        "--mode",
        choices=["stretch", "cover", "contain"],
        default="stretch",
        help="stretch preserves full layer content; cover fills canvas by cropping; contain pads transparent edges.",
    )
    parser.add_argument("--report", help="Optional JSON report path.")
    args = parser.parse_args()

    report = normalize(Path(args.source), Path(args.layer), Path(args.out), args.mode)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
