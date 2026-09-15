#!/usr/bin/env python3
"""Validate component-manifest-v1 structure and content provenance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


RENDER_TYPES = {"native_text", "native_shape", "native_connector", "native_table", "native_chart", "svg_group", "raster_asset"}


def validate(payload: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("schema_version") != "component-manifest-v1":
        errors.append("schema_version must be component-manifest-v1")
    objects = payload.get("objects") or []
    seen: set[str] = set()
    z_values: list[int] = []
    for index, obj in enumerate(objects):
        prefix = f"objects[{index}]"
        for key in ("id", "semantic_type", "render_type", "editable", "confidence", "provenance"):
            if key not in obj:
                errors.append(f"{prefix}: missing {key}")
        oid = str(obj.get("id", ""))
        if oid in seen:
            errors.append(f"{prefix}: duplicate id {oid}")
        seen.add(oid)
        if obj.get("render_type") not in RENDER_TYPES:
            errors.append(f"{prefix}: unsupported render_type {obj.get('render_type')}")
        if obj.get("render_type") == "native_text" and not obj.get("content_id"):
            warnings.append(f"{prefix}: native_text has no content_id; exact text QA cannot trace it")
        bbox = obj.get("bbox")
        if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4 or any(float(v) < 0 or float(v) > 1 for v in bbox)):
            errors.append(f"{prefix}: bbox must be normalized 0..1 [x,y,w,h]")
        z_values.append(int(obj.get("z_index", 0)))
    if z_values != sorted(z_values):
        warnings.append("objects are not ordered by z_index; Composer should sort before emitting PPTX")
    if payload.get("qa", {}).get("semantic_full_slide_shortcut"):
        errors.append("semantic_full_slide_shortcut must be false")
    return {"schema_version": "component-manifest-qa-v1", "verdict": "fail" if errors else ("warn" if warnings else "pass"), "errors": errors, "warnings": warnings, "object_count": len(objects)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--json-out")
    args = parser.parse_args()
    payload = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    report = validate(payload)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["verdict"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
