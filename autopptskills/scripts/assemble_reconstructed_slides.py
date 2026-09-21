#!/usr/bin/env python3
"""Assemble reviewed one-slide reconstruction decks into one portable deck.

Each input deck is produced by ``reconstruct_imagegen_slide.py``.  This helper
copies only the assets consumed by the final composer, preserves slide order,
adds stable slide IDs, and records source/output hashes.  It never draws slide
content or changes the reconstruction routing.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_asset(deck_path: Path, deck: dict[str, Any], value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        assets_dir = Path(str(deck.get("assets_dir") or deck_path.parent))
        if not assets_dir.is_absolute():
            assets_dir = (deck_path.parent / assets_dir).resolve()
        resolved = (assets_dir / candidate).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def copy_asset(
    source: Path,
    *,
    out_dir: Path,
    slide_id: str,
    role: str,
    ordinal: int,
) -> tuple[str, dict[str, Any]]:
    digest = sha256_file(source)
    suffix = source.suffix.lower() or ".bin"
    filename = f"{role}-{ordinal:03d}-{digest[:12]}{suffix}"
    destination = out_dir / "assets" / slide_id / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    relative = destination.relative_to(out_dir).as_posix()
    return relative, {
        "role": role,
        "source": str(source),
        "source_sha256": digest,
        "packaged": relative,
        "packaged_sha256": sha256_file(destination),
        "bytes": destination.stat().st_size,
    }


def assemble(deck_paths: list[Path], out_dir: Path) -> tuple[Path, Path]:
    out_dir = out_dir.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"immutable output already contains files: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    base_contract: dict[str, Any] | None = None
    slides: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    component_objects: list[dict[str, Any]] = []

    for index, raw_path in enumerate(deck_paths, start=1):
        deck_path = raw_path.resolve()
        deck = load_json(deck_path)
        source_slides = deck.get("slides", [])
        if not isinstance(source_slides, list) or len(source_slides) != 1:
            raise ValueError(f"expected one slide in {deck_path}, found {len(source_slides)}")
        contract = {
            key: deck.get(key)
            for key in ("units", "ref_width", "ref_height", "slide_width_in", "slide_height_in")
        }
        if base_contract is None:
            base_contract = contract
        elif contract != base_contract:
            raise ValueError(f"deck geometry mismatch: {deck_path}")

        slide_id = f"S{index:02d}"
        slide = copy.deepcopy(source_slides[0])
        slide["slide_id"] = slide_id

        background = slide.get("background")
        if background:
            source = resolve_asset(deck_path, deck, str(background))
            packaged, record = copy_asset(
                source,
                out_dir=out_dir,
                slide_id=slide_id,
                role="background",
                ordinal=1,
            )
            slide["background"] = packaged
            records.append({"slide_id": slide_id, **record})

        for ordinal, item in enumerate(slide.get("icons", []), start=1):
            if not isinstance(item, dict) or not item.get("file"):
                continue
            source = resolve_asset(deck_path, deck, str(item["file"]))
            packaged, record = copy_asset(
                source,
                out_dir=out_dir,
                slide_id=slide_id,
                role="icon",
                ordinal=ordinal,
            )
            item["file"] = packaged
            records.append({"slide_id": slide_id, **record})

        manifest_value = deck.get("component_manifest")
        if manifest_value:
            manifest_path = resolve_asset(deck_path, deck, str(manifest_value))
            manifest = load_json(manifest_path)
            objects = manifest.get("objects", [])
            if isinstance(objects, list):
                component_objects.extend(copy.deepcopy(objects))

        slides.append(slide)

    assert base_contract is not None
    component_manifest_path = out_dir / "component_manifest.json"
    write_json(
        component_manifest_path,
        {
            "schema_version": "component-manifest-v1",
            "objects": component_objects,
        },
    )
    final_deck = {
        "title": "轴卫智诊——ImageGen-first 可编辑重构",
        "author": "autopptskills",
        "subject": "verified built-in ImageGen masters with semantic editable reconstruction",
        **base_contract,
        "assets_dir": str(out_dir),
        "component_manifest": component_manifest_path.name,
        "slides": slides,
    }
    deck_path = out_dir / "deck-high-fidelity.json"
    write_json(deck_path, final_deck)

    mismatches = [row for row in records if row["source_sha256"] != row["packaged_sha256"]]
    report = {
        "schema_version": "reconstructed-slide-assembly-v1",
        "verdict": "pass" if not mismatches else "fail",
        "slides": [slide["slide_id"] for slide in slides],
        "slide_count": len(slides),
        "source_decks": [str(path.resolve()) for path in deck_paths],
        "output_deck": str(deck_path),
        "output_deck_sha256": sha256_file(deck_path),
        "component_manifest": str(component_manifest_path),
        "component_objects": len(component_objects),
        "assets": records,
        "hash_mismatches": mismatches,
    }
    report_path = out_dir / "qa" / "assembly-report.json"
    write_json(report_path, report)
    if mismatches:
        raise RuntimeError("packaged asset hash mismatch")
    return deck_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decks", nargs="+")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    deck, report = assemble([Path(value) for value in args.decks], Path(args.out_dir))
    print(json.dumps({"deck": str(deck), "report": str(report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
