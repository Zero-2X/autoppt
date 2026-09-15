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
        "保留 accepted PPTX，不覆盖既有基线；每轮输出新 round。",
        "普通文字走 native text；复杂图形只有在 PowerPoint 复核通过后才接受 SVG。",
        "逐页视觉复核独立于结构化分数，不能用自动门禁替代人工 sign-off。",
    ]
    if dedup_failures:
        rules.append("本轮存在 gate failure：先修复并记录根因，再进入下一轮，禁止把 blocker 当作完成。")
    if reconstruction:
        rules.append("矢量化结果必须记录 source_bbox/layout_bbox、拒绝原因和 raster fallback。")
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
    failures = record.get("failures") or ["无自动门禁失败；仍需人工逐页视觉复核"]
    warnings = record.get("warnings") or ["无自动门禁 warning"]
    lines = [
        f"\n## {record['timestamp']} · {Path(record['project']).name}",
        f"- 状态：`{record['status']}`；profile：`{record.get('presentation_profile') or '未记录'}`；style：`{record.get('style_profile') or '未记录'}`",
        f"- 页数：`{record.get('slide_count') or '未记录'}`；质量迭代：`{record.get('quality_iteration') or '未运行'}`",
        "- 失败点：" + "；".join(f"`{item}`" for item in failures),
        "- 警告：" + "；".join(f"`{item}`" for item in warnings),
        "- 本轮必须保留的规则：" + "；".join(record.get("learned_rules", [])),
        "- 验证证据：" + str(record.get("evidence", {})),
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
