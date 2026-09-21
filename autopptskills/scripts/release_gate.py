#!/usr/bin/env python3
"""Aggregate immutable evidence for a gold-standard editable PPTX release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PASS = "pass"
FAIL = "fail"
BLOCKED = "blocked"
NOT_APPLICABLE = "not_applicable"
SLIDE_XML_RE = re.compile(r"^ppt/slides/slide\d+\.xml$")
BASE_REVIEW_CHECKS = (
    "text_residue",
    "wrapping_and_spacing",
    "color_and_emphasis",
    "icons_and_vectors",
    "crop_overlap_and_hierarchy",
)
DESIGN_REVIEW_CHECKS = (
    "spectacle_control",
    "design_completion",
    "information_density",
    "restrained_style",
    "master_visual_fidelity",
)
INSTITUTIONAL_REVIEW_CHECKS = ("institutional_identity_absence",)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def same_path(reported: Any, actual: Path) -> bool:
    if not reported:
        return False
    try:
        return Path(str(reported)).resolve() == actual.resolve()
    except OSError:
        return False


def resolve_report_path(value: Any, report_path: Path) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else (report_path.parent / path).resolve()


def archive_gate(pptx: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(pptx) as archive:
            bad_entry = archive.testzip()
            names = {entry.filename for entry in archive.infolist()}
            slide_count = sum(1 for name in names if SLIDE_XML_RE.match(name))
    except (OSError, zipfile.BadZipFile) as exc:
        return {"status": FAIL, "error": str(exc), "slide_count": 0}

    missing = [
        name
        for name in ("[Content_Types].xml", "ppt/presentation.xml")
        if name not in names
    ]
    status = PASS if bad_entry is None and not missing and slide_count > 0 else FAIL
    return {
        "status": status,
        "entries": len(names),
        "slide_count": slide_count,
        "bad_entry": bad_entry,
        "missing_required_parts": missing,
    }


def load_gate_report(path: Path, *, missing_status: str = BLOCKED) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not path.exists():
        return None, {"status": missing_status, "report": str(path), "error": "report not found"}
    try:
        return read_json(path), {"status": PASS, "report": str(path)}
    except (OSError, json.JSONDecodeError) as exc:
        return None, {"status": FAIL, "report": str(path), "error": str(exc)}


def imagegen_gate(path: Path, expected_slides: int) -> dict[str, Any]:
    payload, gate = load_gate_report(path)
    if payload is None:
        return gate
    reported_slides = payload.get("slides_verified")
    errors = []
    if payload.get("verdict") != PASS:
        errors.append(f"verdict={payload.get('verdict')!r}")
    if reported_slides is None:
        errors.append("slides_verified is missing")
    else:
        try:
            if int(reported_slides) != expected_slides:
                errors.append(
                    f"slides_verified={reported_slides}, expected={expected_slides}"
                )
        except (TypeError, ValueError):
            errors.append(f"slides_verified is not an integer: {reported_slides!r}")
    if payload.get("slides_expected") is not None:
        try:
            if int(payload["slides_expected"]) != expected_slides:
                errors.append("ImageGen report expected slide count mismatch")
        except (TypeError, ValueError):
            errors.append("slides_expected is not an integer")
    if payload.get("manifest_full_slide_contracts") is not None:
        try:
            if int(payload["manifest_full_slide_contracts"]) != expected_slides:
                errors.append("full-slide prompt contract count mismatch")
        except (TypeError, ValueError):
            errors.append("manifest_full_slide_contracts is not an integer")
    if payload.get("require_strong_ig_id") is True:
        try:
            if int(payload.get("strong_ig_id_slides", -1)) != expected_slides:
                errors.append("strong ImageGen ID coverage is incomplete")
        except (TypeError, ValueError):
            errors.append("strong_ig_id_slides is not an integer")
    if payload.get("errors"):
        errors.append("ImageGen-first report still contains errors")
    reported_official_source = payload.get("official_source_inspired") is True
    official_source_contract = payload.get("official_source_contract", {})
    if not isinstance(official_source_contract, dict):
        errors.append("official_source_contract is not an object")
        official_source_contract = {}
    contract_requires_official_source = official_source_contract.get("required") is True
    official_source_inspired = reported_official_source or contract_requires_official_source
    if reported_official_source != contract_requires_official_source:
        errors.append("official-source ImageGen report flags are inconsistent")
    if official_source_inspired and official_source_contract.get("status") != PASS:
        errors.append("official-source ImageGen contract did not pass")
    return {
        "status": PASS if not errors else FAIL,
        "report": str(path),
        "slides_verified": reported_slides,
        "official_source_inspired": official_source_inspired,
        "official_source_contract": official_source_contract,
        "errors": errors,
    }


def technical_gate(path: Path, pptx: Path, expected_slides: int) -> dict[str, Any]:
    payload, gate = load_gate_report(path)
    if payload is None:
        return gate

    errors: list[str] = []
    expected_gates = ("layout", "editability", "powerpoint_render", "visual_compare")
    if payload.get("verdict") != PASS:
        errors.append(f"verdict={payload.get('verdict')!r}")
    for name in expected_gates:
        if payload.get("gates", {}).get(name) != PASS:
            errors.append(f"gate {name}={payload.get('gates', {}).get(name)!r}")
    if not same_path(payload.get("pptx"), pptx):
        errors.append("technical report targets a different PPTX")
    reported_pptx_hash = payload.get("pptx_sha256")
    if reported_pptx_hash is not None and reported_pptx_hash != sha256_file(pptx):
        errors.append("technical report PPTX hash does not match the final PPTX")
    for current_only_gate in ("canvas_contract", "renderer_immutable"):
        if current_only_gate in payload.get("gates", {}) and payload["gates"].get(current_only_gate) != PASS:
            errors.append(
                f"gate {current_only_gate}={payload.get('gates', {}).get(current_only_gate)!r}"
            )
    if len(payload.get("slide_ids", [])) != expected_slides:
        errors.append("technical report slide count mismatch")
    powerpoint = payload.get("powerpoint", {})
    if powerpoint.get("status") != PASS or powerpoint.get("renderer") != "Microsoft PowerPoint":
        errors.append("exact final PPTX was not passed by Microsoft PowerPoint")

    editability_report_path = resolve_report_path(
        payload.get("editability", {}).get("report"), path
    )
    editability_summary: dict[str, Any] = {}
    if editability_report_path is None or not editability_report_path.exists():
        errors.append("editability report referenced by technical gate is missing")
    else:
        try:
            editability = read_json(editability_report_path)
            totals = editability.get("totals", {})
            metrics = editability.get("editability", {})
            unicode_info = editability.get("unicode", {})
            editability_summary = {
                "report": str(editability_report_path),
                "pptx": editability.get("pptx"),
                "grade": metrics.get("grade"),
                "score": metrics.get("score"),
                "native_text_coverage": metrics.get("native_text_coverage"),
                "native_shape_coverage": metrics.get("native_shape_coverage"),
                "background_tile_pictures": totals.get("background_tile_pictures"),
                "semantic_full_slide_pictures": totals.get("semantic_full_slide_pictures"),
                "replacement_character_count": unicode_info.get("replacement_character_count"),
            }
            if editability.get("verdict") != PASS:
                errors.append("editability report verdict is not pass")
            if not same_path(editability.get("pptx"), pptx):
                errors.append("editability report targets a different PPTX")
            if totals.get("slides") != expected_slides:
                errors.append("editability report slide count mismatch")
            if metrics.get("grade") != "editable":
                errors.append("editability grade is not editable")
            if metrics.get("native_text_coverage") != 1.0:
                errors.append("native text coverage is not 100%")
            # Imported SVGs are intentionally reported as ``convertible-vector``
            # rather than falsely promoted to native PowerPoint paths.  Their
            # visual/editability decision is enforced by the separate
            # icon-decisions gate.  Therefore native-shape coverage may be below
            # 100% only when the complete shortfall is represented by explicit
            # convertible-vector objects and there is no semantic full-slide
            # raster shortcut.
            native_shape_coverage = metrics.get("native_shape_coverage")
            convertible_vectors = int(totals.get("convertible_vectors", 0) or 0)
            semantic_full_slide_pictures = int(totals.get("semantic_full_slide_pictures", 0) or 0)
            if native_shape_coverage != 1.0:
                if convertible_vectors <= 0 or semantic_full_slide_pictures != 0:
                    errors.append("native shape coverage is not 100%")
            if totals.get("background_tile_pictures") != 0:
                errors.append("background tiles are present")
            if totals.get("semantic_full_slide_pictures") != 0:
                errors.append("semantic full-slide pictures are present")
            if unicode_info.get("replacement_character_count") != 0:
                errors.append("replacement characters are present")
            if unicode_info.get("slide_xml_count") != expected_slides:
                errors.append("editability Unicode slide count mismatch")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"editability report unreadable: {exc}")

    return {
        "status": PASS if not errors else FAIL,
        "report": str(path),
        "editability": editability_summary,
        "errors": errors,
    }


def exact_text_gate(path: Path, pptx: Path, expected_slides: int) -> dict[str, Any]:
    payload, gate = load_gate_report(path)
    if payload is None:
        return gate
    errors = []
    if payload.get("verdict") != PASS:
        errors.append(f"verdict={payload.get('verdict')!r}")
    if float(payload.get("token_coverage", 0.0)) < 1.0:
        errors.append("token coverage is below 100%")
    if int(payload.get("missing_tokens", 0)) != 0:
        errors.append("missing exact-text tokens remain")
    if int(payload.get("slides", 0)) != expected_slides:
        errors.append("exact-text report slide count mismatch")
    if not same_path(payload.get("pptx"), pptx):
        errors.append("exact-text report targets a different PPTX")
    return {
        "status": PASS if not errors else FAIL,
        "report": str(path),
        "token_coverage": payload.get("token_coverage"),
        "matched_tokens": payload.get("matched_tokens"),
        "tokens": payload.get("tokens"),
        "errors": errors,
    }


def overflow_gate(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": BLOCKED, "report": str(path), "error": "overflow report not found"}
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        return {"status": FAIL, "report": str(path), "error": str(exc)}

    status = FAIL
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
            status = PASS if payload.get("status", payload.get("verdict")) == PASS else FAIL
        except json.JSONDecodeError:
            status = FAIL
    elif "Test passed. No overflow detected." in text:
        status = PASS
    return {"status": status, "report": str(path)}


def review_checks(
    require_design_quality: bool = False,
    require_institutional_identity_absence: bool = False,
) -> tuple[str, ...]:
    checks = BASE_REVIEW_CHECKS
    if require_design_quality:
        checks += DESIGN_REVIEW_CHECKS
    if require_institutional_identity_absence:
        checks += INSTITUTIONAL_REVIEW_CHECKS
    return checks


def review_template(
    pptx: Path,
    pptx_hash: str,
    slide_ids: list[str],
    *,
    require_design_quality: bool = False,
    require_institutional_identity_absence: bool = False,
) -> dict[str, Any]:
    checks = review_checks(require_design_quality, require_institutional_identity_absence)
    return {
        "schema_version": 3 if require_institutional_identity_absence else (2 if require_design_quality else 1),
        "pptx": str(pptx),
        "pptx_sha256": pptx_hash,
        "review_scope": "all_slides_full_size_and_montage",
        "design_quality_required": require_design_quality,
        "institutional_identity_review_required": require_institutional_identity_absence,
        "slides": [
            {
                "slide_id": slide_id,
                "status": "pending",
                "checks": {name: "pending" for name in checks},
                "notes": "",
            }
            for slide_id in slide_ids
        ],
        "verdict": "pending",
    }


def visual_review_gate(
    path: Path,
    pptx: Path,
    pptx_hash: str,
    slide_ids: list[str],
    *,
    require_design_quality: bool = False,
    require_institutional_identity_absence: bool = False,
) -> dict[str, Any]:
    required_checks = review_checks(require_design_quality, require_institutional_identity_absence)
    if not path.exists():
        write_json(
            path,
            review_template(
                pptx,
                pptx_hash,
                slide_ids,
                require_design_quality=require_design_quality,
                require_institutional_identity_absence=require_institutional_identity_absence,
            ),
        )
        return {
            "status": BLOCKED,
            "report": str(path),
            "error": "pending visual-review template created",
        }
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": FAIL, "report": str(path), "error": str(exc)}

    errors = []
    if payload.get("verdict") != PASS:
        errors.append(f"verdict={payload.get('verdict')!r}")
    if payload.get("review_scope") != "all_slides_full_size_and_montage":
        errors.append("visual review scope is not all slides at full size and montage")
    if require_institutional_identity_absence and payload.get("institutional_identity_review_required") is not True:
        errors.append("visual review does not declare the required institutional identity review")
    if payload.get("pptx_sha256") != pptx_hash:
        errors.append("visual review hash does not match the final PPTX")
    if not same_path(payload.get("pptx"), pptx):
        errors.append("visual review targets a different PPTX")
    slide_rows = list(payload.get("slides", []))
    rows = {str(item.get("slide_id")): item for item in slide_rows}
    if len(slide_rows) != len(slide_ids) or len(rows) != len(slide_ids):
        errors.append("visual review contains missing or duplicate slide rows")
    if set(rows) != set(slide_ids):
        errors.append("visual review slide coverage mismatch")
    for slide_id in slide_ids:
        row = rows.get(slide_id, {})
        if row.get("status") != PASS:
            errors.append(f"{slide_id} review status is not pass")
            continue
        checks = row.get("checks", {})
        missing_checks = [name for name in required_checks if checks.get(name) != PASS]
        if missing_checks:
            errors.append(f"{slide_id} pending checks: {', '.join(missing_checks)}")
    return {
        "status": PASS if not errors else BLOCKED,
        "report": str(path),
        "reviewed_slides": sum(1 for row in rows.values() if row.get("status") == PASS),
        "required_checks": list(required_checks),
        "institutional_identity_review_required": require_institutional_identity_absence,
        "errors": errors,
    }


def icon_decision_gate(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": NOT_APPLICABLE, "reason": "no icon/vector candidates reported"}
    payload, gate = load_gate_report(path)
    if payload is None:
        return gate
    errors = []
    mappings = list(payload.get("mappings", []))

    def valid_bbox(value: Any) -> bool:
        return (
            isinstance(value, list)
            and len(value) == 4
            and all(isinstance(number, (int, float)) for number in value)
            and value[2] > 0
            and value[3] > 0
        )

    def review_passed(item: dict[str, Any]) -> bool:
        value = (
            item.get("powerpoint_visual_review")
            or item.get("powerpoint_review")
            or item.get("visual_review_status")
            or item.get("vector_visual_review")
        )
        if isinstance(value, dict):
            value = value.get("status", value.get("verdict"))
        return str(value).lower() == PASS

    for item in mappings:
        item_id = str(item.get("id", "unnamed"))
        accepted_as = str(item.get("accepted_as", "")).lower()
        vector_accepted = item.get("vector_accepted") is True or accepted_as in {
            "vector",
            "convertible-vector",
            "native-vector",
        }
        source_bbox = item.get("source_bbox")
        final_bbox = (
            item.get("layout_bbox")
            or item.get("deck_bbox")
            or item.get("final_bbox")
        )
        if not valid_bbox(source_bbox):
            errors.append(f"{item_id}: source_bbox is missing or invalid")
        if not valid_bbox(final_bbox):
            errors.append(f"{item_id}: final layout bbox is missing or invalid")
        if vector_accepted:
            asset_value = (
                item.get("final_asset")
                or item.get("asset")
                or item.get("vector_candidate")
            )
            asset = resolve_report_path(asset_value, path)
            if asset is None or not asset.exists():
                errors.append(f"{item_id}: accepted vector asset missing")
            if not review_passed(item):
                errors.append(
                    f"{item_id}: accepted vector lacks PowerPoint visual pass"
                )
            continue
        reason = str(
            item.get("vector_rejection_reason")
            or item.get("rejection_reason")
            or ""
        ).strip()
        asset_value = item.get("fallback_asset") or item.get("asset")
        asset = resolve_report_path(asset_value, path)
        if not reason:
            errors.append(f"{item_id}: missing vector rejection reason")
        if asset is None or not asset.exists():
            errors.append(f"{item_id}: fallback asset missing")
    return {
        "status": PASS if not errors else FAIL,
        "report": str(path),
        "items": len(mappings),
        "errors": errors,
    }


def layer_contract_gate(
    path: Path | None,
    pptx: Path,
    pptx_hash: str,
    expected_slides: int,
    *,
    required: bool,
) -> dict[str, Any]:
    if path is None:
        if required:
            return {
                "status": BLOCKED,
                "error": "layer-contract report is required for this release",
            }
        return {
            "status": NOT_APPLICABLE,
            "reason": "legacy release did not request the semantic layer-contract gate",
        }
    payload, gate = load_gate_report(path)
    if payload is None:
        return gate

    errors: list[str] = []
    totals = payload.get("totals", {})
    if payload.get("verdict") != PASS:
        errors.append(f"verdict={payload.get('verdict')!r}")
    if not same_path(payload.get("pptx"), pptx):
        errors.append("layer-contract report targets a different PPTX")
    if payload.get("pptx_sha256") != pptx_hash:
        errors.append("layer-contract PPTX hash mismatch")
    try:
        if int(payload.get("slide_count", 0)) != expected_slides:
            errors.append("layer-contract slide count mismatch")
    except (TypeError, ValueError):
        errors.append("layer-contract slide count is not an integer")
    if payload.get("strict") is not True:
        errors.append("layer-contract report is not strict")
    if totals.get("backgrounds") != expected_slides:
        errors.append("single continuous background coverage is incomplete")
    if totals.get("background_tiles") != 0:
        errors.append("layer-contract report contains background tiles")
    if payload.get("structural", {}).get("status") != PASS:
        errors.append("semantic layer structure did not pass")
    if payload.get("review", {}).get("status") != PASS:
        errors.append("per-slide background/frame separation review did not pass")
    return {
        "status": PASS if not errors else FAIL,
        "report": str(path),
        "totals": totals,
        "errors": errors,
    }


def overall_verdict(gates: dict[str, dict[str, Any]]) -> str:
    required = [gate for gate in gates.values() if gate.get("status") != NOT_APPLICABLE]
    if any(gate.get("status") == FAIL for gate in required):
        return FAIL
    if any(gate.get("status") == BLOCKED for gate in required):
        return BLOCKED
    if any(gate.get("status") != PASS for gate in required):
        return FAIL
    return PASS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx")
    parser.add_argument("--imagegen-first-report", required=True)
    parser.add_argument("--technical-gate-report", required=True)
    parser.add_argument("--exact-text-report", required=True)
    parser.add_argument("--overflow-report", required=True)
    parser.add_argument("--visual-review", required=True)
    parser.add_argument("--icon-decisions")
    parser.add_argument("--layer-contract-report")
    parser.add_argument(
        "--require-layer-contract",
        action="store_true",
        help="Require the strict continuous-background and semantic-layer report for a vNext gold release.",
    )
    parser.add_argument(
        "--require-design-quality",
        action="store_true",
        help="Require spectacle-control and design-completion checks in the all-slide visual review.",
    )
    parser.add_argument("--out", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pptx = Path(args.pptx).resolve()
    out = Path(args.out).resolve()
    if not pptx.exists():
        report = {
            "policy": "gold-standard-editable-pptx-release",
            "pptx": str(pptx),
            "verdict": BLOCKED,
            "gates": {"archive": {"status": BLOCKED, "error": "PPTX not found"}},
        }
        write_json(out, report)
        print(json.dumps({"verdict": BLOCKED, "report": str(out)}, ensure_ascii=False))
        return 2

    pptx_hash = sha256_file(pptx)
    archive = archive_gate(pptx)
    slide_count = int(archive.get("slide_count", 0))
    slide_ids = [f"S{index:02d}" for index in range(1, slide_count + 1)]
    imagegen = imagegen_gate(
        Path(args.imagegen_first_report).resolve(), slide_count
    )
    require_institutional_identity_absence = imagegen.get("official_source_inspired") is True
    gates = {
        "archive": archive,
        "imagegen_first": imagegen,
        "technical": technical_gate(
            Path(args.technical_gate_report).resolve(), pptx, slide_count
        ),
        "exact_text": exact_text_gate(
            Path(args.exact_text_report).resolve(), pptx, slide_count
        ),
        "overflow": overflow_gate(Path(args.overflow_report).resolve()),
        "visual_review": visual_review_gate(
            Path(args.visual_review).resolve(),
            pptx,
            pptx_hash,
            slide_ids,
            require_design_quality=args.require_design_quality,
            require_institutional_identity_absence=require_institutional_identity_absence,
        ),
        "layer_contract": layer_contract_gate(
            Path(args.layer_contract_report).resolve()
            if args.layer_contract_report
            else None,
            pptx,
            pptx_hash,
            slide_count,
            required=args.require_layer_contract,
        ),
        "icon_decisions": icon_decision_gate(
            Path(args.icon_decisions).resolve() if args.icon_decisions else None
        ),
    }
    verdict = overall_verdict(gates)
    report = {
        "policy": "gold-standard-editable-pptx-release",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pptx": str(pptx),
        "pptx_sha256": pptx_hash,
        "slide_count": slide_count,
        "gates": gates,
        "verdict": verdict,
    }
    write_json(out, report)
    print(json.dumps({"verdict": verdict, "report": str(out)}, ensure_ascii=False))
    return 0 if verdict == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
