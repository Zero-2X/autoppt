#!/usr/bin/env python3
"""Fail-closed semantic editability audit for ImageGen-first PPTX decks.

This gate is intentionally independent from exact-text coverage: hidden text
proxies and raster text crops are not evidence of editable wording.
"""
from __future__ import annotations

import argparse, json
from pathlib import Path


def bbox_ok(v):
    return isinstance(v, list) and len(v) == 4 and all(isinstance(x, (int, float)) for x in v) and v[2] > 0 and v[3] > 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("deck")
    ap.add_argument("--out", required=True)
    ap.add_argument("--expected-slides", type=int)
    args = ap.parse_args()
    deck_path = Path(args.deck).resolve()
    deck = json.loads(deck_path.read_text(encoding="utf-8-sig"))
    errors, warnings, slides = [], [], []
    for slide in deck.get("slides", []):
        sid = str(slide.get("slide_id", ""))
        row = {"slide_id": sid, "native_texts": 0, "native_shapes": 0, "raster_text_exceptions": 0, "errors": []}
        for item in slide.get("texts", []):
            name = str(item.get("name", item.get("id", "text")))
            if item.get("audit_proxy") or item.get("role") == "exact-text-audit-proxy":
                row["errors"].append(f"{name}: hidden exact-text proxy is forbidden")
            if item.get("text_raster_fallback") or item.get("role") in {"text-raster-fallback", "stylized-art-text"}:
                row["errors"].append(f"{name}: raster text is not a visible native text layer")
            if str(item.get("editability_level", "")).lower() not in {"native", "native-reviewed"}:
                row["errors"].append(f"{name}: visible text is not native")
            if float(item.get("opacity", 1.0) or 0.0) <= 0:
                row["errors"].append(f"{name}: visible text has zero opacity")
            if not str(item.get("text", "")).strip():
                row["errors"].append(f"{name}: empty visible text")
            if not bbox_ok(item.get("source_bbox")) or not bbox_ok(item.get("layout_bbox") or [item.get(k) for k in ("x", "y", "w", "h")]):
                row["errors"].append(f"{name}: source/layout bbox is invalid")
            else:
                row["native_texts"] += 1
        for item in slide.get("shapes", []):
            name = str(item.get("name", item.get("id", "shape")))
            if str(item.get("editability_level", "")).lower() not in {"native", "native-reviewed"}:
                row["errors"].append(f"{name}: simple geometry is not native")
            else:
                row["native_shapes"] += 1
        for item in slide.get("icons", []):
            role = str(item.get("role", "")).lower()
            if "text" in role or item.get("source_text"):
                row["raster_text_exceptions"] += 1
                if role != "embedded_text_candidate":
                    row["errors"].append(f"{item.get('name', item.get('id', 'asset'))}: raster text exception must be embedded_text_candidate")
        if row["errors"]:
            errors.extend(f"{sid}: {e}" for e in row["errors"])
        slides.append(row)
    report = {
        "policy": "strict-semantic-editability-v1",
        "deck": str(deck_path),
        "slide_count": len(slides),
        "totals": {"native_texts": sum(x["native_texts"] for x in slides), "native_shapes": sum(x["native_shapes"] for x in slides), "raster_text_exceptions": sum(x["raster_text_exceptions"] for x in slides)},
        "errors": errors,
        "warnings": warnings,
        "verdict": "pass" if not errors and slides and (args.expected_slides is None or len(slides) == args.expected_slides) else "fail",
        "slides": slides,
    }
    out = Path(args.out).resolve(); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "native_texts": report["totals"]["native_texts"], "raster_text_exceptions": report["totals"]["raster_text_exceptions"]}, ensure_ascii=False))
    return 0 if report["verdict"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
