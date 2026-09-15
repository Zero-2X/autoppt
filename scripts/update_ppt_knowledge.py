#!/usr/bin/env python3
"""Append a compact, source-backed learning record after a PPT run.

The script is intentionally conservative: it records what the existing gates
reported and never marks a deck as visually accepted on its own.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "improvement" / "ppt-improvement-ledger.jsonl"
DEFAULT_HANDBOOK = ROOT / "improvement" / "style-handbook.md"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_strings(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_strings(item))
        return out
    return []


def collect(project_dir: Path) -> dict[str, Any]:
    ppt_dir = project_dir / "final" / "ppt"
    audit = read_json(ppt_dir / "ppt_audit.json")
    run_manifest = read_json(ppt_dir / "presentation_run_manifest.json")
    image_manifest = read_json(ppt_dir / "imagegen_manifest.json")
    failures: list[str] = []
    warnings: list[str] = []
    for key in ("issues", "errors", "blockers"):
        failures.extend(_strings(audit.get(key)))
    warnings.extend(_strings(audit.get("warnings")))
    gate_reports: dict[str, Any] = {}
    validation = ppt_dir / "validation"
    if validation.exists():
        for path in sorted(validation.rglob("*.json")):
            report = read_json(path)
            if not report:
                continue
            name = path.stem
            gate_reports[name] = report.get("verdict") or report.get("status") or report.get("gate_status")
            for key in ("issues", "errors", "blockers"):
                failures.extend(_strings(report.get(key)))
            warnings.extend(_strings(report.get("warnings")))
    reconstruction = []
    for path in sorted(ppt_dir.rglob("*reconstruction-report*.json")):
        report = read_json(path)
        if report:
            reconstruction.append({
                "path": str(path),
                "vector_rejections": report.get("vector_rejections") or report.get("rejected_vectors") or [],
                "visual_only": report.get("visual_only") or report.get("visual_only_count"),
            })
    quality = {}
    for candidate in sorted(ppt_dir.rglob("latest-summary.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        quality = read_json(candidate)
        if quality:
            break
    dedup_failures = list(dict.fromkeys(item for item in failures if item))
    dedup_warnings = list(dict.fromkeys(item for item in warnings if item))
    status = str(audit.get("verdict") or run_manifest.get("status") or "unknown")
    profile = str(run_manifest.get("presentation_profile") or audit.get("presentation_profile") or "")
    style = str(run_manifest.get("style_profile") or "")
    rules = [
        "Keep the accepted PPTX immutable; write every iteration to a new round.",
        "Route normal text to native text; accept complex SVG only after PowerPoint visual review.",
        "Keep full-size visual review independent from structural scores; automated gates cannot replace sign-off.",
    ]
    if dedup_failures:
        rules.append("This round has gate failures: repair and record the root cause before the next round; never treat a blocker as completion.")
    if reconstruction:
        rules.append("Every vectorization decision must record source_bbox/layout_bbox, the rejection reason, and any raster fallback.")
    return {
        "schema_version": "ppt-improvement-ledger-v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project": str(project_dir.resolve()),
        "status": status,
        "presentation_profile": profile,
        "style_profile": style,
        "slide_count": audit.get("slide_count") or len(image_manifest.get("slides", [])),
        "failures": dedup_failures,
        "warnings": dedup_warnings,
        "gate_reports": gate_reports,
        "vectorization": reconstruction,
        "quality_iteration": quality.get("status") if isinstance(quality, dict) else None,
        "learned_rules": rules,
        "evidence": {
            "ppt_audit": str(ppt_dir / "ppt_audit.json"),
            "run_manifest": str(ppt_dir / "presentation_run_manifest.json"),
            "validation_dir": str(validation),
        },
    }


def append_markdown(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    failures = record.get("failures") or ["No automated gate failure; full-size slide review is still required."]
    warnings = record.get("warnings") or ["No automated gate warning."]
    lines = [
        f"\n## {record['timestamp']} · {Path(record['project']).name}",
        f"- Status: `{record['status']}`; presentation profile: `{record.get('presentation_profile') or 'unrecorded'}`; style: `{record.get('style_profile') or 'unrecorded'}`",
        f"- Slides: `{record.get('slide_count') or 'unrecorded'}`; quality iteration: `{record.get('quality_iteration') or 'not run'}`",
        "- Failures: " + "; ".join(f"`{item}`" for item in failures),
        "- Warnings: " + "; ".join(f"`{item}`" for item in warnings),
        "- Rules to retain: " + "; ".join(record.get("learned_rules", [])),
        "- Evidence: " + str(record.get("evidence", {})),
    ]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Record PPT run failures and reusable lessons.")
    parser.add_argument("project_dir")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--handbook", default=str(DEFAULT_HANDBOOK))
    args = parser.parse_args()
    project = Path(args.project_dir).expanduser().resolve()
    record = collect(project)
    ledger = Path(args.ledger).expanduser().resolve()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    append_markdown(Path(args.handbook).expanduser().resolve(), record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
