#!/usr/bin/env python3
"""Create a new reconstruction round by replacing only reviewed slides."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def resolve_assets_dir(deck: dict[str, Any], deck_path: Path) -> Path:
    raw = Path(str(deck.get("assets_dir") or deck_path.parent))
    return raw.resolve() if raw.is_absolute() else (deck_path.parent / raw).resolve()


def merge_round(
    baseline_deck_path: Path,
    patch_deck_path: Path,
    out_dir: Path,
    selected_slide_ids: list[str],
    report_path: Path | None = None,
) -> tuple[Path, Path]:
    baseline_deck_path = baseline_deck_path.resolve()
    patch_deck_path = patch_deck_path.resolve()
    out_dir = out_dir.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"output round already contains files: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = load_json(baseline_deck_path)
    patch = load_json(patch_deck_path)
    baseline_slides = {str(slide["slide_id"]): slide for slide in baseline.get("slides", [])}
    patch_slides = {str(slide["slide_id"]): slide for slide in patch.get("slides", [])}
    selected = list(dict.fromkeys(selected_slide_ids))
    missing = [slide_id for slide_id in selected if slide_id not in baseline_slides or slide_id not in patch_slides]
    if missing:
        raise ValueError(f"selected slides missing from baseline or patch deck: {missing}")

    for key in ("units", "ref_width", "ref_height", "slide_width_in", "slide_height_in"):
        if baseline.get(key) != patch.get(key):
            raise ValueError(f"baseline and patch deck disagree on {key}")

    baseline_assets = resolve_assets_dir(baseline, baseline_deck_path) / "assets"
    patch_assets = resolve_assets_dir(patch, patch_deck_path) / "assets"
    target_assets = out_dir / "assets"
    if not baseline_assets.is_dir() or not patch_assets.is_dir():
        raise FileNotFoundError("both deck rounds must contain an assets directory")
    shutil.copytree(baseline_assets, target_assets, dirs_exist_ok=False)

    for slide_id in selected:
        source = patch_assets / slide_id
        target = target_assets / slide_id
        if not source.is_dir():
            raise FileNotFoundError(source)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

    merged = dict(baseline)
    merged["assets_dir"] = str(out_dir)
    merged["slides"] = [
        patch_slides.get(str(slide["slide_id"]), slide)
        if str(slide["slide_id"]) in selected
        else slide
        for slide in baseline.get("slides", [])
    ]
    output_deck = out_dir / "deck-high-fidelity.json"
    output_deck.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    asset_checks = []
    for slide_id in baseline_slides:
        expected_root = patch_assets / slide_id if slide_id in selected else baseline_assets / slide_id
        actual_root = target_assets / slide_id
        if expected_root.is_dir() and actual_root.is_dir():
            expected_hash = sha256_tree(expected_root)
            actual_hash = sha256_tree(actual_root)
            asset_checks.append(
                {
                    "slide_id": slide_id,
                    "source": "patch" if slide_id in selected else "baseline",
                    "expected_sha256": expected_hash,
                    "actual_sha256": actual_hash,
                    "match": expected_hash == actual_hash,
                }
            )

    report_path = (report_path or out_dir / "qa" / "baseline-merge-report.json").resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "baseline_deck": str(baseline_deck_path),
        "baseline_deck_sha256": sha256_file(baseline_deck_path),
        "patch_deck": str(patch_deck_path),
        "patch_deck_sha256": sha256_file(patch_deck_path),
        "output_deck": str(output_deck),
        "output_deck_sha256": sha256_file(output_deck),
        "selected_slides": selected,
        "unchanged_slides": [slide_id for slide_id in baseline_slides if slide_id not in selected],
        "asset_checks": asset_checks,
        "verdict": "pass" if asset_checks and all(item["match"] for item in asset_checks) else "fail",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["verdict"] != "pass":
        raise RuntimeError("baseline round merge asset verification failed")
    return output_deck, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_deck")
    parser.add_argument("patch_deck")
    parser.add_argument("--slides", required=True, help="Comma-separated reviewed slide IDs")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()
    slides = [value.strip() for value in args.slides.split(",") if value.strip()]
    if not slides:
        raise ValueError("--slides must contain at least one slide ID")
    output, report = merge_round(
        Path(args.baseline_deck),
        Path(args.patch_deck),
        Path(args.out_dir),
        slides,
        Path(args.report) if args.report else None,
    )
    print(json.dumps({"deck": str(output), "report": str(report), "slides": slides}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
