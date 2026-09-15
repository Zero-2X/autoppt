#!/usr/bin/env python3
"""Build the stable semantic bridge between a slide master and editable PPTX.

This is the only img2pptx-derived layer that the MVP needs.  OCR/vision is
allowed to propose geometry, while slide/content manifests remain the source
of truth for text.  The output is deliberately representation-agnostic so the
Composer can route each object to native PowerPoint, SVG, or a bounded asset.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


RENDER_TYPES = {
    "native_text", "native_shape", "native_connector", "native_table",
    "native_chart", "svg_group", "raster_asset",
}


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", str(value or "")).lower()


def _bbox(item: dict[str, Any], width: float, height: float) -> list[float]:
    raw = item.get("bbox") or item.get("source_bbox") or [0, 0, 0, 0]
    x, y, w, h = [float(v) for v in (list(raw) + [0, 0, 0, 0])[:4]]
    return [round(x / max(1.0, width), 6), round(y / max(1.0, height), 6),
            round(w / max(1.0, width), 6), round(h / max(1.0, height), 6)]


def _content_index(slide_manifest: dict[str, Any] | None, slide_id: str) -> list[tuple[str, str]]:
    """Collect exact source strings without imposing a particular manifest shape."""
    if not isinstance(slide_manifest, dict):
        return []
    slides = slide_manifest.get("slides") or [slide_manifest]
    selected = next((s for s in slides if str(s.get("slide_id", "")) == slide_id), None)
    if not isinstance(selected, dict):
        selected = slide_manifest
    out: list[tuple[str, str]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            cid = value.get("content_id") or value.get("id")
            for key in ("text", "value", "title", "body", "label", "content"):
                if cid and isinstance(value.get(key), str) and value[key].strip():
                    out.append((str(cid), value[key].strip()))
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key in {"title", "subtitle", "body", "text", "label", "footnote", "equation", "value"} and isinstance(child, str) and child.strip():
                    out.append((child_path, child.strip()))
                elif key not in {"content"}:
                    walk(child, child_path)
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                walk(child, f"{path}[{idx}]")
        elif isinstance(value, str) and value.strip() and path.split(".")[-1] in {
            "title", "subtitle", "body", "label", "footnote", "equation"
        }:
            out.append((path, value.strip()))

    walk(selected, slide_id)
    seen: set[tuple[str, str]] = set()
    return [item for item in out if not (item in seen or seen.add(item))]


def _match_content(text: str, candidates: list[tuple[str, str]], fallback: str) -> str:
    ntext = _norm(text)
    if ntext:
        for cid, value in candidates:
            nvalue = _norm(value)
            if nvalue and (ntext == nvalue or ntext in nvalue or nvalue in ntext):
                return cid
    return fallback


def _style(item: dict[str, Any]) -> dict[str, Any]:
    keys = ("font", "size", "font_size", "bold", "italic", "color", "fill",
            "line", "line_width", "align", "valign", "opacity")
    return {key: item[key] for key in keys if key in item}


def build_component_manifest(
    analysis: dict[str, Any],
    *,
    slide_id: str,
    slide_manifest: dict[str, Any] | None = None,
    source_image: str | None = None,
) -> dict[str, Any]:
    width = float((analysis.get("size") or {}).get("width") or 1)
    height = float((analysis.get("size") or {}).get("height") or 1)
    candidates = _content_index(slide_manifest, slide_id)
    objects: list[dict[str, Any]] = []

    def add(item: dict[str, Any], semantic_type: str, render_type: str, index: int, *, content_id: str = "") -> None:
        raw_id = str(item.get("id") or f"component-{index:03d}")
        bbox = _bbox(item, width, height)
        objects.append({
            "id": f"{slide_id}::{raw_id}",
            "semantic_type": semantic_type,
            "parent_id": None,
            "bbox": bbox,
            "source_bbox": item.get("source_bbox") or item.get("bbox"),
            "z_index": index,
            "content_id": content_id or None,
            "render_type": render_type if render_type in RENDER_TYPES else "raster_asset",
            "style": _style(item),
            "editable": render_type in {"native_text", "native_shape", "native_connector", "native_table", "native_chart"},
            "confidence": round(float(item.get("confidence", item.get("score", 1.0)) or 0.0), 4),
            "provenance": {
                "slide_id": slide_id,
                "source_image": source_image,
                "source_component_id": raw_id,
                "content_source": "slide_manifest" if content_id else "visual_analysis",
            },
        })

    for index, item in enumerate(analysis.get("texts", []), 1):
        bbox = item.get("bbox") or [0, 0, 0, 0]
        semantic = "title" if float(bbox[1]) < height * 0.18 else "body_text"
        cid = _match_content(str(item.get("text", "")), candidates, f"{slide_id}.text[{index - 1}]")
        add(item, semantic, "native_text", index, content_id=cid)
    offset = len(objects)
    for index, item in enumerate(analysis.get("shapes", []), 1):
        add(item, "card" if item.get("type") in {"rounded_rect", "rect", "rectangle"} else "simple_shape", "native_shape", offset + index)
    offset = len(objects)
    for index, item in enumerate(analysis.get("lines", []), 1):
        add(item, "connector", "native_connector", offset + index)
    offset = len(objects)
    for index, item in enumerate(analysis.get("icon_candidates", []), 1):
        accepted = bool(item.get("accepted") or item.get("traceable", True))
        add(item, "icon", "svg_group" if accepted else "raster_asset", offset + index)

    objects.sort(key=lambda obj: obj["z_index"])
    counts = {render: sum(1 for obj in objects if obj["render_type"] == render) for render in sorted(RENDER_TYPES)}
    return {
        "schema_version": "component-manifest-v1",
        "route": "fullpage_imagegen_reconstruct",
        "slide_id": slide_id,
        "coordinate_system": {"type": "normalized", "reference_width": int(width), "reference_height": int(height)},
        "source_imagegen_master": source_image,
        "content_authority": "slide_manifest > reviewed_source_text > OCR_geometry",
        "objects": objects,
        "routing_summary": counts,
        "qa": {"text_objects_require_exact_content_match": True, "semantic_full_slide_shortcut": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis_json")
    parser.add_argument("out_json")
    parser.add_argument("--slide-id", required=True)
    parser.add_argument("--slide-manifest")
    parser.add_argument("--source-image")
    args = parser.parse_args()
    analysis = json.loads(Path(args.analysis_json).read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.slide_manifest).read_text(encoding="utf-8")) if args.slide_manifest else None
    result = build_component_manifest(analysis, slide_id=args.slide_id, slide_manifest=manifest, source_image=args.source_image)
    path = Path(args.out_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(path), "objects": len(result["objects"]), "routing_summary": result["routing_summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
