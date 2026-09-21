#!/usr/bin/env python3
"""Iterate a reconstructed PPT through independent quality gates.

The iterator is deliberately conservative.  It treats the current deck as an
immutable baseline, writes every candidate into a new round directory, and
only promotes a candidate when the candidate improves the measurable issue
score without a visual regression.  Human visual review and the semantic layer
contract remain independent blockers; this script never fabricates those
approvals.

The repair pass is local and JSON-only: it removes obviously duplicated native
text, restores measured source boxes for co-located OCR rows, drops isolated
single-letter OCR artifacts, and accepts explicit project repair actions.  It
does not redraw images or perform broad inpainting.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
PPT_SCRIPTS = ROOT / "autopptskills" / "scripts"
# The standalone AutoPPT project keeps durable lessons outside the reusable
# skill package so the skill remains portable while every local run can learn.
DEFAULT_LEDGER = ROOT / "improvement" / "ppt-improvement-ledger.jsonl"

VISUAL_METRICS = (
    "mean_abs_diff_0_255",
    "rms_diff_0_255",
    "changed_pixel_fraction_threshold_32",
    "changed_pixel_fraction_threshold_64",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def append_learning_record(path: Path, *, record: dict[str, Any], project_dir: Path, source: str = "quality-iterator") -> None:
    """Write a stable learning record consumed by future PPT runs.

    Keep the original quality-iterator fields, but also preserve failure
    findings, repair actions, vectorization clues and the next priority so the
    ledger is useful as a knowledge base rather than only a score history.
    """
    payload = {
        "schema_version": "ppt-improvement-ledger-v1",
        "timestamp": record.get("timestamp"),
        "project": str(project_dir),
        "iteration_id": record.get("iteration_id"),
        "status": record.get("acceptance_decision"),
        "failures": record.get("unresolved_blockers", []),
        "findings": record.get("findings", {}),
        "repair_actions": record.get("repair_actions", []),
        "vectorization": record.get("vectorization", []),
        "learned_rules": record.get("learned_rules", []),
        "next_priority": record.get("next_priority", ""),
        "evidence": {
            "input_path": record.get("input_path"),
            "output_path": record.get("output_path"),
            "gate_status": record.get("gate_status", {}),
        },
        "source": source,
    }
    append_jsonl(path, payload)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def valid_bbox(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(
        isinstance(v, (int, float)) for v in value
    ) and float(value[2]) > 0 and float(value[3]) > 0


def item_bbox(item: dict[str, Any], prefer_layout: bool = True) -> list[float] | None:
    candidates = (
        item.get("layout_bbox"),
        item.get("source_bbox"),
        [item.get(key) for key in ("x", "y", "w", "h")],
    ) if prefer_layout else (
        item.get("source_bbox"),
        item.get("layout_bbox"),
        [item.get(key) for key in ("x", "y", "w", "h")],
    )
    for candidate in candidates:
        if valid_bbox(candidate):
            return [float(v) for v in candidate]
    return None


def bbox_area(box: list[float] | None) -> float:
    return float(box[2] * box[3]) if box else 0.0


def intersection(left: list[float], right: list[float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[0] + left[2], right[0] + right[2])
    y2 = min(left[1] + left[3], right[1] + right[3])
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def iou(left: list[float], right: list[float]) -> float:
    overlap = intersection(left, right)
    union = bbox_area(left) + bbox_area(right) - overlap
    return overlap / union if union else 0.0


def overlap_fraction(left: list[float], right: list[float]) -> float:
    smaller = min(bbox_area(left), bbox_area(right))
    return intersection(left, right) / smaller if smaller else 0.0


def source_box(item: dict[str, Any]) -> list[float] | None:
    return item_bbox(item, prefer_layout=False)


def set_box(item: dict[str, Any], box: list[float]) -> None:
    clean = [round(float(v), 3) for v in box]
    item["layout_bbox"] = clean
    item["x"], item["y"], item["w"], item["h"] = clean


def union_boxes(boxes: Iterable[list[float]]) -> list[float]:
    values = list(boxes)
    left = min(box[0] for box in values)
    top = min(box[1] for box in values)
    right = max(box[0] + box[2] for box in values)
    bottom = max(box[1] + box[3] for box in values)
    return [left, top, right - left, bottom - top]


def compact_text(value: Any) -> str:
    return re.sub(r"[\\s，。；：、,.!?！？·]+", "", str(value or "")).lower()


def run_command(command: list[str], cwd: Path, *, timeout: int = 180) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + f"\nTimed out after {timeout}s",
        }
    except Exception as exc:  # pragma: no cover - platform launch failure
        return {"command": command, "returncode": None, "stdout": "", "stderr": str(exc)}


def report_status(path: Path, *keys: str) -> str:
    if not path.exists():
        return "blocked"
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return "blocked"
    for key in keys:
        value = payload
        for part in key.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if isinstance(value, str):
            return value
    return "unknown"


def load_visual_metrics(path: Path) -> dict[str, float] | None:
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    result: dict[str, float] = {}
    for key in VISUAL_METRICS:
        try:
            result[key] = float(payload[key])
        except (KeyError, TypeError, ValueError):
            return None
    return result


def load_exact_coverage(path: Path) -> float | None:
    try:
        payload = read_json(path)
        value = payload.get("token_coverage")
        return float(value) if value is not None else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def layout_counts(layout_result: dict[str, Any]) -> dict[str, int]:
    output = "\n".join((layout_result.get("stdout") or "", layout_result.get("stderr") or ""))
    return {
        "warnings": len(re.findall(r"(?im)^warning:", output)),
        "errors": len(re.findall(r"(?im)^error:", output)),
    }


def visual_regressions(current_dir: Path, baseline_dir: Path | None, slide_ids: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    regressions: list[str] = []
    if baseline_dir is None:
        return {"status": "not_required", "slides": rows, "regressions": regressions}
    for slide_id in slide_ids:
        current = load_visual_metrics(current_dir / slide_id / "report.json")
        baseline = load_visual_metrics(baseline_dir / slide_id / "report.json")
        row: dict[str, Any] = {"slide_id": slide_id, "status": "blocked", "metrics": {}}
        if current is None or baseline is None:
            row["reason"] = "current or baseline visual metrics are missing/invalid"
            rows.append(row)
            continue
        slide_regressions = []
        for key in VISUAL_METRICS:
            delta = current[key] - baseline[key]
            row["metrics"][key] = {
                "current": round(current[key], 6),
                "baseline": round(baseline[key], 6),
                "delta": round(delta, 6),
            }
            if delta > 1e-6:
                slide_regressions.append(key)
        row["status"] = "fail" if slide_regressions else "pass"
        row["regressions"] = slide_regressions
        if slide_regressions:
            regressions.append(slide_id)
        rows.append(row)
    statuses = {row.get("status") for row in rows}
    status = "fail" if regressions else ("blocked" if "blocked" in statuses or len(rows) != len(slide_ids) else "pass")
    return {"status": status, "slides": rows, "regressions": regressions}


def collect_findings(deck: dict[str, Any], reports: dict[str, Path] | None = None) -> dict[str, Any]:
    reports = reports or {}
    slides: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []
    for slide in deck.get("slides", []):
        slide_id = str(slide.get("slide_id") or "unnamed")
        texts = list(slide.get("texts") or [])
        slide_findings: list[dict[str, Any]] = []
        for index, item in enumerate(texts):
            box = item_bbox(item)
            if not box:
                continue
            size = float(item.get("size") or item.get("font_size") or 0)
            if size and size < 14 and not item.get("small_text_ok"):
                slide_findings.append({
                    "kind": "small_text",
                    "severity": "advisory",
                    "text_id": item.get("id") or f"text-{index}",
                    "text": item.get("text", ""),
                    "size": size,
                })
            if re.fullmatch(r"[A-Za-z]", str(item.get("text", "")).strip()):
                slide_findings.append({
                    "kind": "suspicious_singleton",
                    "severity": "high",
                    "text_id": item.get("id") or f"text-{index}",
                    "text": item.get("text", ""),
                })
            for other_index in range(index):
                other = texts[other_index]
                other_box = item_bbox(other)
                if not other_box:
                    continue
                overlap = overlap_fraction(box, other_box)
                if overlap < 0.62:
                    continue
                same = compact_text(item.get("text")) == compact_text(other.get("text"))
                slide_findings.append({
                    "kind": "text_overlap",
                    "severity": "high" if same or overlap >= 0.85 else "medium",
                    "text_id": item.get("id") or f"text-{index}",
                    "other_text_id": other.get("id") or f"text-{other_index}",
                    "text": item.get("text", ""),
                    "other_text": other.get("text", ""),
                    "overlap_fraction": round(overlap, 4),
                    "same_text": same,
                })
        # Same text in separated boxes is still useful evidence, but duplicates
        # in the same or almost the same box are almost always an OCR repair.
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in texts:
            key = compact_text(item.get("text"))
            if key:
                groups.setdefault(key, []).append(item)
        for key, group in groups.items():
            if len(group) < 2:
                continue
            for left_index, left in enumerate(group):
                for right in group[left_index + 1 :]:
                    left_box = item_bbox(left)
                    right_box = item_bbox(right)
                    if left_box and right_box and overlap_fraction(left_box, right_box) >= 0.45:
                        slide_findings.append({
                            "kind": "duplicate_text",
                            "severity": "high",
                            "text_ids": [left.get("id"), right.get("id")],
                            "text": left.get("text", ""),
                            "overlap_fraction": round(overlap_fraction(left_box, right_box), 4),
                        })
        row = {"slide_id": slide_id, "findings": slide_findings}
        slides.append(row)
        all_findings.extend({"slide_id": slide_id, **finding} for finding in slide_findings)

    report_findings = {
        "small_text": sum(1 for item in all_findings if item["kind"] == "small_text"),
        "suspicious_singletons": sum(1 for item in all_findings if item["kind"] == "suspicious_singleton"),
        "text_overlaps": sum(1 for item in all_findings if item["kind"] == "text_overlap"),
        "duplicate_texts": sum(1 for item in all_findings if item["kind"] == "duplicate_text"),
        "high_severity": sum(1 for item in all_findings if item["severity"] == "high"),
        "medium_severity": sum(1 for item in all_findings if item["severity"] == "medium"),
        "advisory": sum(1 for item in all_findings if item["severity"] == "advisory"),
    }
    gate_status = {
        name: report_status(path, "verdict", "status") for name, path in reports.items()
    }
    return {"slides": slides, "findings": all_findings, "counts": report_findings, "gates": gate_status}


def _text_by_id(slide: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in slide.get("texts", []) if item.get("id")}


def _remove_text_ids(slide: dict[str, Any], ids: set[str]) -> list[str]:
    before = list(slide.get("texts") or [])
    kept = [item for item in before if str(item.get("id")) not in ids]
    slide["texts"] = kept
    return [str(item.get("id")) for item in before if str(item.get("id")) in ids]


def auto_repair_deck(deck: dict[str, Any], findings: dict[str, Any], explicit_plan: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate = copy.deepcopy(deck)
    actions: list[dict[str, Any]] = []
    use_generic_repair = str((explicit_plan or {}).get("mode") or "conservative") != "explicit-only"
    for slide in candidate.get("slides", []) if use_generic_repair else []:
        slide_id = str(slide.get("slide_id") or "unnamed")
        texts = list(slide.get("texts") or [])
        by_id = _text_by_id(slide)
        remove_ids: set[str] = set()
        # Repair only co-located rows.  A phrase repeated in two genuinely
        # different regions may be intentional and is left alone.
        for index, item in enumerate(texts):
            item_id = str(item.get("id") or f"text-{index}")
            box = item_bbox(item)
            if not box:
                continue
            if re.fullmatch(r"[A-Za-z]", str(item.get("text", "")).strip()):
                neighbours = [other for other in texts if other is not item and item_bbox(other)]
                if any(overlap_fraction(box, item_bbox(other) or box) >= 0.55 for other in neighbours):
                    remove_ids.add(item_id)
                    actions.append({"slide_id": slide_id, "action": "remove_text", "text_id": item_id, "reason": "isolated-single-letter-artifact"})
                    continue
            # If the declared layout frame is much larger than the measured
            # source glyph box, use the measured box as the native frame.  This
            # is the main protection against several OCR rows sharing one
            # container bbox.
            measured = source_box(item)
            if measured and bbox_area(box) > max(1.0, bbox_area(measured) * 2.4):
                set_box(item, measured)
                actions.append({"slide_id": slide_id, "action": "restore_source_bbox", "text_id": item_id, "bbox": measured, "reason": "co-located-ocr-row"})

        # Remove exact duplicates only when their boxes overlap materially.
        for left_index, left in enumerate(texts):
            left_id = str(left.get("id") or f"text-{left_index}")
            if left_id in remove_ids:
                continue
            left_box = item_bbox(left)
            for right_index in range(left_index + 1, len(texts)):
                right = texts[right_index]
                right_id = str(right.get("id") or f"text-{right_index}")
                if right_id in remove_ids:
                    continue
                right_box = item_bbox(right)
                if not left_box or not right_box:
                    continue
                if compact_text(left.get("text")) != compact_text(right.get("text")):
                    continue
                if overlap_fraction(left_box, right_box) < 0.45:
                    continue
                left_score = float(left.get("confidence") or 0) + float(left.get("manifest_match_score") or 0)
                right_score = float(right.get("confidence") or 0) + float(right.get("manifest_match_score") or 0)
                drop = right_id if left_score >= right_score else left_id
                remove_ids.add(drop)
                actions.append({"slide_id": slide_id, "action": "remove_text", "text_id": drop, "reason": "co-located-duplicate-text"})
        if remove_ids:
            _remove_text_ids(slide, remove_ids)

    # Explicit project actions are applied after generic cleanup so that the
    # project can make a reviewed, attributable choice for a known slide.
    for action in (explicit_plan or {}).get("actions", []):
        slide_id = str(action.get("slide_id") or "")
        slide = next((row for row in candidate.get("slides", []) if str(row.get("slide_id")) == slide_id), None)
        if slide is None:
            actions.append({**action, "status": "blocked", "reason": "slide-not-found"})
            continue
        by_id = _text_by_id(slide)
        kind = str(action.get("action") or "")
        if kind == "remove_text":
            removed = _remove_text_ids(slide, {str(action.get("text_id"))})
            actions.append({**action, "status": "applied" if removed else "blocked"})
        elif kind == "replace_text":
            item = by_id.get(str(action.get("text_id")))
            if item is None:
                actions.append({**action, "status": "blocked", "reason": "text-not-found"})
                continue
            before = item.get("text")
            item["text"] = str(action.get("text") or "")
            if action.get("ocr_text") is not None:
                item["ocr_text"] = action["ocr_text"]
            actions.append({**action, "status": "applied", "before": before})
        elif kind == "set_bbox":
            item = by_id.get(str(action.get("text_id")))
            if item is None or not valid_bbox(action.get("bbox")):
                actions.append({**action, "status": "blocked", "reason": "text-or-bbox-not-found"})
                continue
            set_box(item, [float(v) for v in action["bbox"]])
            actions.append({**action, "status": "applied"})
        elif kind == "add_text":
            row = {key: value for key, value in action.items() if key not in {"action", "slide_id"}}
            if not row.get("id"):
                row["id"] = f"quality-added-{len(slide.get('texts') or []) + 1:03d}"
            row.setdefault("name", f"editable-{row['id']}")
            row.setdefault("editability_level", "native")
            row.setdefault("font", "Microsoft YaHei")
            row.setdefault("size", 16.0)
            row.setdefault("color", "#173866")
            row.setdefault("align", "left")
            row.setdefault("valign", "middle")
            row.setdefault("fit", "shrink")
            bbox = row.get("bbox") or row.get("layout_bbox")
            if not valid_bbox(bbox):
                actions.append({**action, "status": "blocked", "reason": "add-text-bbox-missing"})
                continue
            set_box(row, [float(v) for v in bbox])
            row.setdefault("source_bbox", list(row["layout_bbox"]))
            slide.setdefault("texts", []).append(row)
            actions.append({**action, "status": "applied", "id": row["id"]})
        elif kind == "set_background":
            background = str(action.get("background") or "")
            if not background or not Path(background).exists():
                actions.append({**action, "status": "blocked", "reason": "background-not-found"})
                continue
            slide["background"] = str(Path(background).resolve())
            actions.append({**action, "status": "applied"})
        else:
            actions.append({**action, "status": "blocked", "reason": "unsupported-action"})
    return candidate, actions


def resolve_defaults(args: argparse.Namespace) -> tuple[Path, Path, Path, Path, Path, Path]:
    pptx = Path(args.pptx).expanduser().resolve()
    project_dir = Path(args.project_dir).expanduser().resolve() if args.project_dir else pptx.parents[3]
    deck_json = Path(args.deck_json).expanduser().resolve() if args.deck_json else pptx.parent.parent / "reconstruction" / "combined" / "deck.json"
    source_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else project_dir / "final" / "ppt" / "imagegen_workspace"
    iteration_dir = Path(args.iteration_dir).expanduser().resolve() if args.iteration_dir else project_dir / "final" / "ppt" / "reconstruction" / "quality_iterations"
    manifest = Path(args.manifest).expanduser().resolve() if args.manifest else source_dir / "image-prompts.json"
    return pptx, project_dir, deck_json, source_dir, iteration_dir, manifest


def run_round(
    *,
    round_dir: Path,
    deck_json: Path,
    pptx: Path,
    source_dir: Path,
    manifest: Path,
    baseline_visual_dir: Path | None,
    baseline_text_report: Path | None,
    review_template: Path,
) -> dict[str, Any]:
    qa = round_dir / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    deck = read_json(deck_json)
    slide_ids = [str(slide.get("slide_id") or f"S{index:02d}") for index, slide in enumerate(deck.get("slides", []), 1)]
    editability_path = qa / "editability-report.json"
    exact_path = qa / "exact-text-report.json"
    layout_path = qa / "layout-report.json"
    layer_path = qa / "layer-contract-report.json"
    text_fidelity_path = qa / "text-fidelity-report.json"
    visual_dir = qa / "final-visual-gate"
    candidate_pptx = round_dir / "editable.pptx"

    editability_cmd = [sys.executable, str(PPT_SCRIPTS / "pptx_editability_audit.py"), str(candidate_pptx), "--json-out", str(editability_path)]
    editability = run_command(editability_cmd, round_dir)
    exact_cmd = [sys.executable, str(PPT_SCRIPTS / "pptx_exact_text_audit.py"), str(candidate_pptx), str(manifest), "--layout", str(deck_json), "--json-out", str(exact_path)]
    exact = run_command(exact_cmd, round_dir)
    reference = source_dir / "assets" / "slides" / f"{slide_ids[0]}.png"
    layout_cmd = [sys.executable, str(PPT_SCRIPTS / "layout_guard.py"), str(reference), str(deck_json), "--strict"]
    layout = run_command(layout_cmd, round_dir)
    write_json(layout_path, {"command": layout_cmd, **layout})

    compose_cmd = ["node", str(PPT_SCRIPTS / "compose_editable_pptx.mjs"), str(deck_json), str(candidate_pptx), "--report", str(qa / "compose-report.json")]
    # compose is run by the caller before this function.  Keeping the command
    # here makes the evidence self-contained without re-writing the PPTX.
    compose_evidence = {"command": compose_cmd, "returncode": 0, "stdout": "candidate composed before audits", "stderr": ""}
    write_json(qa / "compose-command.json", compose_evidence)

    final_cmd = [sys.executable, str(PPT_SCRIPTS / "final_visual_gate.py"), str(source_dir), str(deck_json), str(candidate_pptx), "--out-dir", str(visual_dir), "--compare-workers", "2"]
    if baseline_visual_dir:
        final_cmd.extend(["--baseline-visual-dir", str(baseline_visual_dir)])
    final = run_command(final_cmd, round_dir, timeout=300)
    layer_cmd = [sys.executable, str(PPT_SCRIPTS / "layer_contract_gate.py"), str(deck_json), "--pptx", str(candidate_pptx), "--review", str(review_template), "--out", str(layer_path)]
    layer = run_command(layer_cmd, round_dir, timeout=300)

    # Per-object fidelity is deliberately independent from the whole-slide
    # metric.  It records source/layout/render bboxes, declared font/size,
    # line count, local crops and local pixel diffs so a wide OCR container or
    # a PowerPoint wrap cannot hide inside an acceptable deck average.
    text_cmd = [
        sys.executable,
        str(PPT_SCRIPTS / "text_fidelity_report.py"),
        "--deck",
        str(deck_json),
        "--pptx",
        str(candidate_pptx),
        "--source-dir",
        str(source_dir),
        "--render-dir",
        str(visual_dir),
        "--out",
        str(text_fidelity_path),
    ]
    if baseline_text_report:
        text_cmd.extend(["--baseline-report", str(baseline_text_report)])
    text_fidelity = run_command(text_cmd, round_dir, timeout=300)

    final_report = visual_dir / "final-visual-gate.json"
    visual_report = read_json(final_report) if final_report.exists() else {}
    metrics = visual_regressions(visual_dir / "visual", baseline_visual_dir, slide_ids)
    report = {
        "round_dir": str(round_dir),
        "pptx": str(candidate_pptx),
        "pptx_sha256": sha256_file(candidate_pptx) if candidate_pptx.exists() else None,
        "deck": str(deck_json),
        "deck_sha256": sha256_file(deck_json),
        "slide_count": len(slide_ids),
        "commands": {"editability": editability, "exact_text": exact, "layout": layout, "final_visual_gate": final, "layer_contract": layer},
        "gate_status": {
            "editability": report_status(editability_path, "verdict", "status"),
            "exact_text": report_status(exact_path, "verdict", "native_verdict"),
            "layout": "pass" if layout.get("returncode") == 0 else "fail",
            "powerpoint_render": visual_report.get("gates", {}).get("powerpoint_render", "blocked"),
            "visual_compare": visual_report.get("gates", {}).get("visual_compare", "blocked"),
            "relative_baseline": metrics["status"],
            "layer_contract": report_status(layer_path, "verdict", "status"),
            "text_fidelity": report_status(text_fidelity_path, "verdict", "status"),
            "human_visual_review": "pending",
        },
        "visual_metrics": metrics,
        "exact_token_coverage": load_exact_coverage(exact_path),
        "layout_counts": layout_counts(layout),
        "final_visual_report": str(final_report),
        "layer_report": str(layer_path),
        "text_fidelity_report": str(text_fidelity_path),
        "text_fidelity_command": text_fidelity,
    }
    if text_fidelity_path.exists():
        try:
            tf = read_json(text_fidelity_path)
            report["text_fidelity_summary"] = tf.get("summary", {})
            report["text_fidelity_relative_baseline"] = tf.get("relative_baseline", {})
        except (OSError, json.JSONDecodeError):
            report["text_fidelity_summary"] = {}
    write_json(qa / "round-report.json", report)
    return report


def issue_score(findings: dict[str, Any], gate_report: dict[str, Any]) -> float:
    counts = findings.get("counts", {})
    score = (
        counts.get("high_severity", 0) * 10
        + counts.get("medium_severity", 0) * 4
        + counts.get("advisory", 0)
    )
    statuses = gate_report.get("gate_status", {})
    score += sum(15 for key in ("layout", "exact_text") if statuses.get(key) not in {"pass", "not_required"})
    score += 10 if statuses.get("relative_baseline") == "fail" else 0
    score += 12 if statuses.get("text_fidelity") not in {"pass", "not_required"} else 0
    tf = gate_report.get("text_fidelity_summary") or {}
    score += float(tf.get("review_items", 0)) * 0.5
    score += float(tf.get("mean_position_delta_px", 0)) / 8.0
    score += float(tf.get("mean_size_delta_px", 0)) / 16.0
    return float(score)


def write_status_markdown(path: Path, summary: dict[str, Any]) -> None:
    rows = summary.get("iterations") or []
    latest = rows[-1] if rows else {}
    lines = [
        "# Presentation quality iteration status",
        "",
        f"- Updated: {datetime.now(timezone.utc).isoformat()}",
        f"- Accepted PPTX: `{summary.get('accepted_pptx', '')}`",
        f"- Accepted deck JSON: `{summary.get('accepted_deck', '')}`",
        f"- Project history: `{summary.get('history', '')}`",
        f"- Global lesson ledger: `{summary.get('global_ledger', '')}`",
        "",
        "## Latest decision",
        "",
        f"- Iteration: `{latest.get('iteration_id', '')}`",
        f"- Decision: `{latest.get('acceptance_decision', '')}`",
        f"- Unresolved blockers: `{', '.join(latest.get('unresolved_blockers', []))}`",
        "",
        "This file is a generated status view. The JSONL ledgers are append-only evidence and should be used for audit history.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pptx", required=True)
    parser.add_argument("--project-dir")
    parser.add_argument("--deck-json")
    parser.add_argument("--source-dir")
    parser.add_argument("--manifest")
    parser.add_argument("--iteration-dir")
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--auto-repair", action="store_true")
    parser.add_argument("--repair-plan", help="Optional JSON with reviewed project actions.")
    parser.add_argument("--preserve-baseline", action="store_true", default=True)
    parser.add_argument("--learn", action="store_true", default=True)
    parser.add_argument("--stop-on-blocker", action="store_true")
    parser.add_argument("--global-ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--promote-accepted-to", default="", help="Optional new PPTX path for the accepted candidate; never overwrites the input baseline.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pptx, project_dir, deck_json, source_dir, iteration_dir, manifest = resolve_defaults(args)
    if not pptx.exists() or not deck_json.exists() or not source_dir.exists():
        missing = [str(path) for path in (pptx, deck_json, source_dir) if not path.exists()]
        raise SystemExit("missing input: " + ", ".join(missing))
    # A round stores the final visual artifacts under ``qa/final-visual-gate``.
    # Older callers placed them directly beside deck.json, so retain that
    # compatibility path while preferring the current durable layout.  This is
    # important when continuing from an already accepted round: candidate
    # acceptance must compare against that round, not silently downgrade to a
    # source-only check.
    baseline_candidates = (
        deck_json.parent / "qa" / "final-visual-gate" / "visual",
        deck_json.parent / "final-visual-gate" / "visual",
    )
    baseline_dir = next((path for path in baseline_candidates if path.exists()), None)
    plan = read_json(Path(args.repair_plan).expanduser().resolve()) if args.repair_plan else None
    iteration_dir.mkdir(parents=True, exist_ok=True)
    history_path = project_dir / "final" / "ppt" / "iteration_history.jsonl"
    global_ledger = Path(args.global_ledger).expanduser().resolve()
    prior_lessons = []
    for row in read_jsonl(global_ledger):
        for rule in row.get("learned_rules", []):
            if rule not in prior_lessons:
                prior_lessons.append(rule)

    baseline_round = iteration_dir / f"iteration-000-baseline-{utc_stamp()}"
    baseline_round.mkdir(parents=True, exist_ok=True)
    baseline_deck = baseline_round / "deck.json"
    baseline_pptx = baseline_round / "editable.pptx"
    shutil.copy2(deck_json, baseline_deck)
    shutil.copy2(pptx, baseline_pptx)
    baseline_review = baseline_round / "qa" / "layer-review.json"
    baseline_review.parent.mkdir(parents=True, exist_ok=True)
    baseline_report = run_round(
        round_dir=baseline_round,
        deck_json=baseline_deck,
        pptx=baseline_pptx,
        source_dir=source_dir,
        manifest=manifest,
        baseline_visual_dir=None,
        baseline_text_report=None,
        review_template=baseline_review,
    )
    baseline_findings = collect_findings(read_json(baseline_deck), {
        "editability": baseline_round / "qa" / "editability-report.json",
        "exact_text": baseline_round / "qa" / "exact-text-report.json",
        "layout": baseline_round / "qa" / "layout-report.json",
        "visual": baseline_round / "qa" / "final-visual-gate" / "final-visual-gate.json",
        "layer": baseline_round / "qa" / "layer-contract-report.json",
    })
    write_json(baseline_round / "qa" / "findings.json", baseline_findings)
    baseline_record = {
        "iteration_id": baseline_round.name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_path": str(pptx),
        "output_path": str(baseline_pptx),
        "input_sha256": sha256_file(pptx),
        "output_sha256": sha256_file(baseline_pptx),
        "slide_count": len(read_json(baseline_deck).get("slides", [])),
        "findings": baseline_findings,
        "repair_actions": [],
        "gate_status": baseline_report.get("gate_status", {}),
        "unresolved_blockers": [key for key, value in baseline_report.get("gate_status", {}).items() if value not in {"pass", "not_required"}],
        "learned_rules": ["Keep visual and human-review gates independent from structural scores.", "Never overwrite an accepted PPTX; preserve rejected candidates."],
        "prior_learned_rules_considered": prior_lessons[-20:],
        "next_priority": "repair co-located duplicate native text without broad background cleanup",
        "acceptance_decision": "baseline-recorded",
    }
    append_jsonl(history_path, baseline_record)
    if args.learn:
        append_learning_record(global_ledger, record=baseline_record, project_dir=project_dir)

    current_deck = read_json(deck_json)
    previous_score = issue_score(baseline_findings, baseline_report)
    accepted_exact_coverage = load_exact_coverage(baseline_round / "qa" / "exact-text-report.json")
    accepted_layout_counts = layout_counts(baseline_report["commands"]["layout"])
    accepted_pptx = pptx
    accepted_deck = deck_json
    # The freshly audited baseline round is the authoritative comparison
    # surface for this continuation.  It is rendered from the exact accepted
    # PPTX supplied by the caller, so it remains valid even when the source
    # round did not retain a visual directory.
    accepted_visual_dir = baseline_round / "qa" / "final-visual-gate" / "visual"
    accepted_text_report = baseline_round / "qa" / "text-fidelity-report.json"
    completed_records = [baseline_record]
    if args.max_iterations <= 0 or not args.auto_repair:
        summary = {
            "status": "completed",
            "accepted_pptx": str(accepted_pptx),
            "accepted_deck": str(accepted_deck),
            "history": str(history_path),
            "global_ledger": str(global_ledger),
            "iterations": completed_records,
        }
        write_json(iteration_dir / "latest-summary.json", summary)
        write_status_markdown(project_dir / "final" / "ppt" / "QUALITY_ITERATION_STATUS.md", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    for index in range(1, args.max_iterations + 1):
        round_dir = iteration_dir / f"iteration-{index:03d}-{utc_stamp()}"
        round_dir.mkdir(parents=True, exist_ok=False)
        findings = collect_findings(current_deck)
        repaired_deck, actions = auto_repair_deck(current_deck, findings, plan)
        candidate_deck = round_dir / "deck.json"
        candidate_pptx = round_dir / "editable.pptx"
        write_json(round_dir / "qa" / "findings-before.json", findings)
        write_json(round_dir / "qa" / "repair-plan.json", {"actions": actions, "mode": "conservative-local-json"})
        write_json(candidate_deck, repaired_deck)
        compose_cmd = ["node", str(PPT_SCRIPTS / "compose_editable_pptx.mjs"), str(candidate_deck), str(candidate_pptx), "--report", str(round_dir / "qa" / "compose-report.json")]
        compose = run_command(compose_cmd, round_dir, timeout=300)
        if compose.get("returncode") != 0 or not candidate_pptx.exists():
            record = {
                "iteration_id": round_dir.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "input_path": str(accepted_pptx),
                "output_path": str(candidate_pptx),
                "input_sha256": sha256_file(accepted_pptx),
                "output_sha256": None,
                "slide_count": len(repaired_deck.get("slides", [])),
                "findings": findings,
                "repair_actions": actions,
                "gate_status": {"compose": "blocked"},
                "unresolved_blockers": ["compose"],
                "learned_rules": ["A candidate without a readable PPTX is retained but never promoted."],
                "next_priority": "fix composition backend/input contract",
                "acceptance_decision": "rejected-compose-blocked",
            }
            write_json(round_dir / "qa" / "round-report.json", record)
            append_jsonl(history_path, record)
            if args.learn:
                append_learning_record(global_ledger, record=record, project_dir=project_dir)
            break
        review = round_dir / "qa" / "layer-review.json"
        report = run_round(round_dir=round_dir, deck_json=candidate_deck, pptx=candidate_pptx, source_dir=source_dir, manifest=manifest, baseline_visual_dir=accepted_visual_dir, baseline_text_report=accepted_text_report, review_template=review)
        after_findings = collect_findings(repaired_deck, {
            "editability": round_dir / "qa" / "editability-report.json",
            "exact_text": round_dir / "qa" / "exact-text-report.json",
            "layout": round_dir / "qa" / "layout-report.json",
            "visual": round_dir / "qa" / "final-visual-gate" / "final-visual-gate.json",
            "layer": round_dir / "qa" / "layer-contract-report.json",
        })
        write_json(round_dir / "qa" / "findings-after.json", after_findings)
        after_score = issue_score(after_findings, report)
        baseline_ok = report.get("gate_status", {}).get("relative_baseline") in {"pass", "not_required"}
        layout_improved = report.get("layout_counts", {}).get("errors", 0) == 0 and report.get("layout_counts", {}).get("warnings", 10**9) <= accepted_layout_counts.get("warnings", 10**9)
        exact_not_worse = (
            accepted_exact_coverage is None
            or report.get("exact_token_coverage") is None
            or report.get("exact_token_coverage") + 1e-9 >= accepted_exact_coverage
        )
        text_relative = report.get("text_fidelity_relative_baseline") or {}
        text_not_worse = text_relative.get("status") in {"pass", "not_required"}
        improved = after_score < previous_score
        accepted = bool(baseline_ok and improved and layout_improved and exact_not_worse and text_not_worse)
        learned = [
            "Prefer local measured source boxes for co-located OCR rows.",
            "Drop isolated single-letter OCR artifacts only when they overlap a valid neighbouring row.",
        ]
        if report.get("gate_status", {}).get("relative_baseline") == "fail":
            learned.append("Reject a candidate when any slide-level visual metric regresses against the accepted baseline.")
        record = {
            "iteration_id": round_dir.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input_path": str(accepted_pptx),
            "output_path": str(candidate_pptx),
            "input_sha256": sha256_file(accepted_pptx),
            "output_sha256": sha256_file(candidate_pptx),
            "slide_count": len(repaired_deck.get("slides", [])),
            "findings": {"before": findings, "after": after_findings, "score_before": previous_score, "score_after": after_score},
            "repair_actions": actions,
            "inherited_slides": [slide_id for slide_id in [str(s.get("slide_id")) for s in current_deck.get("slides", [])] if slide_id not in {str(a.get("slide_id")) for a in actions}],
            "replaced_slides": sorted({str(a.get("slide_id")) for a in actions if a.get("slide_id")}),
            "gate_status": report.get("gate_status", {}),
            "unresolved_blockers": [key for key, value in report.get("gate_status", {}).items() if value not in {"pass", "not_required"}],
            "learned_rules": learned,
            "prior_learned_rules_considered": prior_lessons[-20:],
            "next_priority": "human visual review of all slides and exact-token restoration" if accepted else "stop after rejected visual/layout regression",
            "acceptance_decision": "accepted-candidate" if accepted else "rejected-no-improvement-or-regression",
        }
        append_jsonl(history_path, record)
        if args.learn:
            append_learning_record(global_ledger, record=record, project_dir=project_dir)
        completed_records.append(record)
        if accepted:
            accepted_pptx = candidate_pptx
            accepted_deck = candidate_deck
            accepted_visual_dir = round_dir / "qa" / "final-visual-gate" / "visual"
            accepted_text_report = round_dir / "qa" / "text-fidelity-report.json"
            current_deck = repaired_deck
            previous_score = after_score
            # A subsequent no-op round is useful as a convergence proof, but
            # do not churn indefinitely when no repair action remains.
            if not actions:
                break
        else:
            break

    status = "completed" if completed_records else "blocked"
    summary = {
        "status": status,
        "accepted_pptx": str(accepted_pptx),
        "accepted_deck": str(accepted_deck),
        "history": str(history_path),
        "global_ledger": str(global_ledger),
        "promoted_pptx": None,
        "iterations": completed_records,
    }
    if args.promote_accepted_to and accepted_pptx != pptx and accepted_pptx.exists():
        promoted = Path(args.promote_accepted_to).expanduser().resolve()
        if promoted == pptx:
            raise SystemExit("--promote-accepted-to must not equal the input baseline PPTX")
        promoted.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(accepted_pptx, promoted)
        summary["promoted_pptx"] = str(promoted)
        summary["promoted_pptx_sha256"] = sha256_file(promoted)
    write_json(iteration_dir / "latest-summary.json", summary)
    write_status_markdown(project_dir / "final" / "ppt" / "QUALITY_ITERATION_STATUS.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
