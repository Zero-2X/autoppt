#!/usr/bin/env python3
"""Run the technical editable-PPT visual gate and record renderer evidence.

This script creates every-slide comparison artifacts. A gold release still
requires an explicit all-slide visual-review manifest and release_gate.py.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


SCRIPT_DIR = Path(__file__).resolve().parent
VISUAL_METRICS = (
    "mean_abs_diff_0_255",
    "rms_diff_0_255",
    "changed_pixel_fraction_threshold_32",
    "changed_pixel_fraction_threshold_64",
)
EMU_PER_INCH = 914400
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pptx_canvas_contract(pptx: Path, deck: dict[str, Any]) -> dict[str, Any]:
    """Require the authored PPTX canvas to match the deck JSON exactly."""

    result: dict[str, Any] = {
        "status": "fail",
        "pptx": str(pptx),
        "expected_emu": None,
        "actual_emu": None,
        "errors": [],
    }
    try:
        expected = {
            "cx": int(round(float(deck["slide_width_in"]) * EMU_PER_INCH)),
            "cy": int(round(float(deck["slide_height_in"]) * EMU_PER_INCH)),
        }
        result["expected_emu"] = expected
    except (KeyError, TypeError, ValueError) as exc:
        result["errors"].append(f"deck slide-size contract is invalid: {exc}")
        return result
    try:
        with zipfile.ZipFile(pptx) as archive:
            root = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
        node = root.find(f"{{{PRESENTATION_NS}}}sldSz")
        if node is None:
            raise ValueError("ppt/presentation.xml has no p:sldSz")
        actual = {"cx": int(node.attrib["cx"]), "cy": int(node.attrib["cy"])}
        result["actual_emu"] = actual
    except (KeyError, OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        result["errors"].append(f"PPTX slide-size inspection failed: {exc}")
        return result
    if actual != expected:
        result["errors"].append(
            "PPTX slide size differs from the immutable deck contract: "
            f"actual={actual['cx']}x{actual['cy']} expected={expected['cx']}x{expected['cy']}"
        )
        return result
    result["status"] = "pass"
    return result


def _run(command: list[str], *, cwd: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception as exc:  # pragma: no cover - platform launch failure
        return {"command": command, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _source_inventory(source_dir: Path, slide_ids: list[str]) -> dict[str, Any]:
    from PIL import Image

    slides: list[dict[str, Any]] = []
    expected_size: tuple[int, int] | None = None
    errors: list[str] = []
    for slide_id in slide_ids:
        source = source_dir / "assets" / "slides" / f"{slide_id}.png"
        entry: dict[str, Any] = {"slide_id": slide_id, "source": str(source)}
        if not source.exists():
            entry["status"] = "blocked"
            entry["reason"] = "source image is missing"
            errors.append(f"{slide_id}: source not found: {source}")
            slides.append(entry)
            continue
        try:
            with Image.open(source) as image:
                image.load()
                size = (int(image.width), int(image.height))
        except (OSError, ValueError) as exc:
            entry["status"] = "fail"
            entry["reason"] = f"source image decode failed: {exc}"
            errors.append(f"{slide_id}: {entry['reason']}")
            slides.append(entry)
            continue
        entry["size"] = list(size)
        if expected_size is None:
            expected_size = size
        if size != expected_size:
            entry["status"] = "fail"
            entry["reason"] = (
                f"source size {size[0]}x{size[1]} differs from "
                f"deck source size {expected_size[0]}x{expected_size[1]}"
            )
            errors.append(f"{slide_id}: {entry['reason']}")
        else:
            entry["status"] = "pass"
        slides.append(entry)
    return {
        "status": "pass" if not errors and len(slides) == len(slide_ids) else "fail",
        "expected_size": list(expected_size) if expected_size else None,
        "slides": slides,
        "errors": errors,
    }


def _compare_to_baseline(current_report: Path, baseline_report: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "current_report": str(current_report),
        "baseline_report": str(baseline_report),
        "status": "blocked",
        "metrics": {},
        "regressions": [],
    }
    if not current_report.exists() or not baseline_report.exists():
        missing = [str(path) for path in (current_report, baseline_report) if not path.exists()]
        result["reason"] = f"visual report missing: {', '.join(missing)}"
        return result
    try:
        current = json.loads(current_report.read_text(encoding="utf-8"))
        baseline = json.loads(baseline_report.read_text(encoding="utf-8"))
        for key in VISUAL_METRICS:
            current_value = float(current[key])
            baseline_value = float(baseline[key])
            delta = current_value - baseline_value
            result["metrics"][key] = {
                "current": current_value,
                "baseline": baseline_value,
                "delta": round(delta, 6),
            }
            if delta > 1e-6:
                result["regressions"].append(key)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result["reason"] = f"visual report is invalid: {exc}"
        return result
    result["status"] = "fail" if result["regressions"] else "pass"
    return result


def _run_visual_compare(
    index: int,
    slide_id: str,
    source: Path,
    preview: Path,
    compare_dir: Path,
    source_dir: Path,
) -> tuple[int, dict[str, Any]]:
    report_path = compare_dir / "report.json"
    if not source.exists() or not preview.exists():
        missing = [str(path) for path in (source, preview) if not path.exists()]
        return index, {
            "slide_id": slide_id,
            "returncode": None,
            "stdout": "",
            "stderr": f"comparison input missing: {', '.join(missing)}",
            "report": str(report_path),
        }
    compare_command = [
        sys.executable,
        str(SCRIPT_DIR / "visual_compare_qa.py"),
        str(source),
        str(preview),
        "--out-dir",
        str(compare_dir),
    ]
    result = _run(compare_command, cwd=source_dir)
    return index, {"slide_id": slide_id, **result, "report": str(report_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", help="Run directory containing assets/slides/Sxx.png.")
    parser.add_argument("deck_json", help="Final editable deck JSON.")
    parser.add_argument("pptx", help="Final editable PPTX.")
    parser.add_argument("--out-dir", required=True, help="Directory for final gate artifacts.")
    parser.add_argument("--max-background-tiles", type=int, default=0)
    parser.add_argument("--render-timeout-seconds", type=int, default=90)
    parser.add_argument(
        "--compare-workers",
        type=int,
        default=4,
        choices=range(2, 5),
        metavar="{2,3,4}",
        help="Parallel visual-comparison workers; quality checks are unchanged.",
    )
    parser.add_argument(
        "--baseline-visual-dir",
        help="Optional accepted visual-report directory containing Sxx/report.json. "
        "Every current metric must be no worse than the matching baseline.",
    )
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    deck_json = Path(args.deck_json).resolve()
    pptx = Path(args.pptx).resolve()
    out_dir = Path(args.out_dir).resolve()
    preview_dir = out_dir / "preview"
    office_tmp = out_dir / "office_tmp"
    baseline_visual_dir = Path(args.baseline_visual_dir).resolve() if args.baseline_visual_dir else None
    out_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    office_tmp.mkdir(parents=True, exist_ok=True)

    deck = json.loads(deck_json.read_text(encoding="utf-8"))
    slide_ids = [str(slide.get("slide_id") or f"S{index:02d}") for index, slide in enumerate(deck.get("slides", []), 1)]
    pptx_sha256_before_render = _sha256_file(pptx) if pptx.is_file() else None
    canvas_contract = _pptx_canvas_contract(pptx, deck)
    report: dict[str, Any] = {
        "source_dir": str(source_dir),
        "deck_json": str(deck_json),
        "pptx": str(pptx),
        "pptx_sha256": pptx_sha256_before_render,
        "slide_ids": slide_ids,
        "background_policy": "single-continuous-background",
        "max_background_tiles": args.max_background_tiles,
        "render_timeout_seconds": args.render_timeout_seconds,
        "compare_workers": args.compare_workers,
        "system_drive_free_bytes": shutil.disk_usage(os.environ.get("SystemDrive", "C:\\") + "\\").free,
        "layout": [],
        "source_validation": None,
        "canvas_contract": canvas_contract,
        "editability": None,
        "powerpoint": {"status": "not_run", "renderer": "Microsoft PowerPoint", "temp_dir": str(office_tmp)},
        "visual_compare": [],
        "baseline_non_regression": {
            "required": baseline_visual_dir is not None,
            "visual_dir": str(baseline_visual_dir) if baseline_visual_dir else None,
            "metric_policy": "all current metrics must be <= accepted baseline",
            "metrics": list(VISUAL_METRICS),
            "slides": [],
            "status": "not_required" if baseline_visual_dir is None else "blocked",
        },
        "review_policy": "comparison artifacts are diagnostic; explicit all-slide visual review is required for gold release",
        "all_slide_visual_review_required": True,
        "verdict": "blocked",
    }

    source_inventory = _source_inventory(source_dir, slide_ids)
    report["source_validation"] = source_inventory
    layout_reference = next(
        (
            Path(item["source"])
            for item in source_inventory["slides"]
            if item.get("status") == "pass"
        ),
        None,
    )
    if layout_reference is not None:
        command = [
            sys.executable,
            str(SCRIPT_DIR / "layout_guard.py"),
            str(layout_reference),
            str(deck_json),
            "--strict",
        ]
        result = _run(command, cwd=source_dir)
        report["layout"].append(
            {
                "scope": "entire-deck-single-pass",
                "source_reference": str(layout_reference),
                **result,
            }
        )
    else:
        report["layout"].append(
            {
                "scope": "entire-deck-single-pass",
                "source_reference": None,
                "returncode": None,
                "stdout": "",
                "stderr": "no decodable source image is available for layout validation",
            }
        )

    editability_report = out_dir / "editability-report.json"
    editability_command = [
        sys.executable,
        str(SCRIPT_DIR / "pptx_editability_audit.py"),
        str(pptx),
        "--max-background-tile-pictures",
        str(args.max_background_tiles),
        "--max-semantic-full-slide-pictures",
        "0",
        "--min-grade",
        "editable",
        "--json-out",
        str(editability_report),
    ]
    editability = _run(editability_command, cwd=source_dir)
    report["editability"] = {**editability, "report": str(editability_report)}

    render_script = SCRIPT_DIR / "render_pptx_powerpoint.ps1"
    render_command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(render_script),
        "-InputPptx",
        str(pptx),
        "-OutputDirectory",
        str(preview_dir),
    ]
    render_env = os.environ.copy()
    render_env["TEMP"] = str(office_tmp)
    render_env["TMP"] = str(office_tmp)
    try:
        rendered = subprocess.run(
            render_command,
            cwd=str(source_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=render_env,
            timeout=max(1, args.render_timeout_seconds),
        )
        render_result = {
            "command": render_command,
            "returncode": rendered.returncode,
            "stdout": rendered.stdout or "",
            "stderr": rendered.stderr or "",
        }
    except subprocess.TimeoutExpired as exc:
        render_result = {
            "command": render_command,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + f"\nPowerPoint render timed out after {args.render_timeout_seconds}s.",
        }
    except Exception as exc:  # pragma: no cover - platform launch failure
        render_result = {"command": render_command, "returncode": None, "stdout": "", "stderr": str(exc)}
    report["powerpoint"]["command"] = render_result
    if render_result["returncode"] == 0:
        report["powerpoint"]["status"] = "pass"
    else:
        report["powerpoint"]["status"] = "blocked"
        report["powerpoint"]["exact_error"] = render_result["stderr"] or render_result["stdout"]
    pptx_sha256_after_render = _sha256_file(pptx) if pptx.is_file() else None
    report["pptx_sha256_after_render"] = pptx_sha256_after_render
    report["pptx_unchanged_by_render"] = (
        pptx_sha256_before_render is not None
        and pptx_sha256_before_render == pptx_sha256_after_render
    )

    comparisons: list[dict[str, Any] | None] = [None] * len(slide_ids)
    with ThreadPoolExecutor(max_workers=args.compare_workers) as executor:
        futures = [
            executor.submit(
                _run_visual_compare,
                index,
                slide_id,
                source_dir / "assets" / "slides" / f"{slide_id}.png",
                preview_dir / f"slide-{index + 1}.png",
                out_dir / "visual" / slide_id,
                source_dir,
            )
            for index, slide_id in enumerate(slide_ids)
        ]
        for future in as_completed(futures):
            index, result = future.result()
            comparisons[index] = result
    report["visual_compare"] = [item for item in comparisons if item is not None]

    if baseline_visual_dir is not None:
        baseline_rows = []
        for item in report["visual_compare"]:
            slide_id = item["slide_id"]
            assessment = _compare_to_baseline(
                Path(item["report"]),
                baseline_visual_dir / slide_id / "report.json",
            )
            baseline_rows.append({"slide_id": slide_id, **assessment})
        report["baseline_non_regression"]["slides"] = baseline_rows
        statuses = {item["status"] for item in baseline_rows}
        if "fail" in statuses:
            report["baseline_non_regression"]["status"] = "fail"
        elif "blocked" in statuses or len(baseline_rows) != len(slide_ids):
            report["baseline_non_regression"]["status"] = "blocked"
        else:
            report["baseline_non_regression"]["status"] = "pass"

    layout_pass = (
        source_inventory["status"] == "pass"
        and len(report["layout"]) == 1
        and report["layout"][0].get("returncode") == 0
    )
    editability_pass = report["editability"].get("returncode") == 0
    canvas_pass = canvas_contract.get("status") == "pass"
    renderer_immutable_pass = bool(report["pptx_unchanged_by_render"])
    visual_pass = report["powerpoint"]["status"] == "pass" and all(item.get("returncode") == 0 for item in report["visual_compare"]) and len(report["visual_compare"]) == len(slide_ids)
    baseline_status = report["baseline_non_regression"]["status"]
    baseline_pass = baseline_status in {"not_required", "pass"}
    report["gates"] = {
        "layout": "pass" if layout_pass else "fail",
        "canvas_contract": "pass" if canvas_pass else "fail",
        "editability": "pass" if editability_pass else "fail",
        "powerpoint_render": report["powerpoint"]["status"],
        "renderer_immutable": "pass" if renderer_immutable_pass else "fail",
        "visual_compare": "pass" if visual_pass else ("blocked" if report["powerpoint"]["status"] != "pass" else "fail"),
        "relative_baseline": baseline_status,
    }
    report["verdict"] = (
        "pass"
        if layout_pass
        and canvas_pass
        and editability_pass
        and renderer_immutable_pass
        and visual_pass
        and baseline_pass
        else (
            "blocked"
            if report["powerpoint"]["status"] != "pass" or baseline_status == "blocked"
            else "fail"
        )
    )
    report_path = out_dir / "final-visual-gate.json"
    _write_json(report_path, report)
    print(json.dumps({"verdict": report["verdict"], "report": str(report_path)}, ensure_ascii=False))
    return 0 if report["verdict"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
