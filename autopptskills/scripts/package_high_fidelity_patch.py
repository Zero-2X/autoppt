#!/usr/bin/env python3
"""Package one reviewed slide as a self-contained merge-compatible patch."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


PIXEL_UNITS = {"pixel", "pixels", "px"}
SKIP_GEOMETRY_CONTAINERS = {
    "cleanup_evidence",
    "derived_transform",
    "source_provenance",
}
X_KEYS = {"x", "w", "x1", "x2"}
Y_KEYS = {"y", "h", "y1", "y2"}
FILE_REFERENCE_KEYS = {
    "background",
    "cleanup_mask",
    "file",
    "frame",
    "input_source_file",
    "mask",
    "original_source_file",
    "override_file",
    "resolved_input_source_file",
    "source_file",
    "source_image",
    "verified_imagegen_master",
}


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def write_json(path: Path, payload: Any) -> None:
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


def resolve_assets_dir(deck: dict[str, Any], deck_path: Path) -> Path:
    raw = Path(str(deck.get("assets_dir") or deck_path.parent))
    return raw.resolve() if raw.is_absolute() else (deck_path.parent / raw).resolve()


def normalized_units(value: Any) -> str:
    units = str(value or "").strip().lower()
    if units not in PIXEL_UNITS:
        raise ValueError(f"only pixel-coordinate decks can be packaged, got {value!r}")
    return "pixels"


def positive_number(value: Any, label: str) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def scaled_number(value: Any, factor: float) -> Any:
    result = float(value) * factor
    if isinstance(value, int):
        return int(round(result))
    return result


def scale_geometry(value: Any, scale_x: float, scale_y: float, *, parent: str = "") -> Any:
    """Scale slide-space geometry while leaving source-provenance geometry intact."""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in SKIP_GEOMETRY_CONTAINERS:
                result[key] = copy.deepcopy(item)
            elif key == "content_source_bbox":
                result[key] = copy.deepcopy(item)
            elif key in X_KEYS and isinstance(item, (int, float)):
                result[key] = scaled_number(item, scale_x)
            elif key in Y_KEYS and isinstance(item, (int, float)):
                result[key] = scaled_number(item, scale_y)
            elif (
                (key == "bbox" or key.endswith("_bbox"))
                and isinstance(item, list)
                and len(item) == 4
                and all(isinstance(number, (int, float)) for number in item)
            ):
                result[key] = [
                    scaled_number(item[0], scale_x),
                    scaled_number(item[1], scale_y),
                    scaled_number(item[2], scale_x),
                    scaled_number(item[3], scale_y),
                ]
            elif key == "points" and isinstance(item, list):
                result[key] = [
                    [scaled_number(point[0], scale_x), scaled_number(point[1], scale_y)]
                    if isinstance(point, list)
                    and len(point) == 2
                    and all(isinstance(number, (int, float)) for number in point)
                    else copy.deepcopy(point)
                    for point in item
                ]
            else:
                result[key] = scale_geometry(item, scale_x, scale_y, parent=key)
        return result
    if isinstance(value, list):
        return [scale_geometry(item, scale_x, scale_y, parent=parent) for item in value]
    return copy.deepcopy(value)


def safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return name or "asset"


def resolve_file_reference(value: str, deck_path: Path, assets_dir: Path) -> Path | None:
    candidate = Path(value).expanduser()
    probes = [candidate] if candidate.is_absolute() else [deck_path.parent / candidate, assets_dir / candidate]
    for probe in probes:
        resolved = probe.resolve()
        if resolved.is_file():
            return resolved
    return None


def resolve_packaged_reference(value: str, output_root: Path) -> Path | None:
    """Resolve a dependency only when it is contained by the package root."""

    if value.startswith(("http://", "https://", "data:", "urn:")):
        return None
    candidate = Path(value).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (output_root / candidate).resolve()
    try:
        resolved.relative_to(output_root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def audit_packaged_file_references(
    value: Any,
    *,
    output_root: Path,
    json_path: str = "$",
) -> list[dict[str, str]]:
    """Find file-bearing deck fields that still depend on paths outside the package."""

    unresolved: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{json_path}.{key}"
            if key in FILE_REFERENCE_KEYS and isinstance(item, str):
                if resolve_packaged_reference(item, output_root) is None:
                    unresolved.append({"json_path": child_path, "value": item})
            unresolved.extend(
                audit_packaged_file_references(
                    item,
                    output_root=output_root,
                    json_path=child_path,
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            unresolved.extend(
                audit_packaged_file_references(
                    item,
                    output_root=output_root,
                    json_path=f"{json_path}[{index}]",
                )
            )
    return unresolved


def package_file_references(
    value: Any,
    *,
    deck_path: Path,
    assets_dir: Path,
    target_dir: Path,
    output_root: Path,
    copied: dict[Path, str],
    records: list[dict[str, Any]],
    rewrites: list[dict[str, str]],
    json_path: str = "$",
) -> Any:
    if isinstance(value, dict):
        result = {
            key: package_file_references(
                item,
                deck_path=deck_path,
                assets_dir=assets_dir,
                target_dir=target_dir,
                output_root=output_root,
                copied=copied,
                records=records,
                rewrites=rewrites,
                json_path=f"{json_path}.{key}",
            )
            for key, item in value.items()
        }
        # Some reviewed provenance stores both an authoring-time relative path
        # and an absolute resolved path. The relative spelling may only be
        # meaningful beside the override file, so it cannot be resolved from
        # the deck directory. Once the resolved sibling has been packaged,
        # point both dependency-bearing fields at the same immutable copy.
        for key, item in list(result.items()):
            if key not in FILE_REFERENCE_KEYS or key.startswith("resolved_"):
                continue
            resolved_key = f"resolved_{key}"
            resolved_item = result.get(resolved_key)
            if not isinstance(item, str) or not isinstance(resolved_item, str):
                continue
            if (
                resolve_packaged_reference(item, output_root) is None
                and resolve_packaged_reference(resolved_item, output_root) is not None
            ):
                result[key] = resolved_item
                rewrites.append(
                    {
                        "json_path": f"{json_path}.{key}",
                        "original": item,
                        "packaged": resolved_item,
                        "resolved_sibling": resolved_key,
                    }
                )
        return result
    if isinstance(value, list):
        return [
            package_file_references(
                item,
                deck_path=deck_path,
                assets_dir=assets_dir,
                target_dir=target_dir,
                output_root=output_root,
                copied=copied,
                records=records,
                rewrites=rewrites,
                json_path=f"{json_path}[{index}]",
            )
            for index, item in enumerate(value)
        ]
    if not isinstance(value, str):
        return copy.deepcopy(value)

    source = resolve_file_reference(value, deck_path, assets_dir)
    if source is None:
        return value
    if source not in copied:
        digest = sha256_file(source)
        filename = f"{len(copied) + 1:03d}-{digest[:12]}-{safe_name(source.name)}"
        destination = target_dir / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        relative = destination.relative_to(output_root).as_posix()
        copied[source] = relative
        records.append(
            {
                "source": str(source),
                "source_sha256": digest,
                "packaged": relative,
                "packaged_sha256": sha256_file(destination),
                "bytes": destination.stat().st_size,
            }
        )
    return copied[source]


def package_patch(
    source_deck_path: Path,
    baseline_deck_path: Path,
    slide_id: str,
    out_dir: Path,
) -> tuple[Path, Path]:
    source_deck_path = source_deck_path.resolve()
    baseline_deck_path = baseline_deck_path.resolve()
    out_dir = out_dir.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"immutable package output already contains files: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    source_deck = read_json(source_deck_path)
    baseline_deck = read_json(baseline_deck_path)
    normalized_units(source_deck.get("units"))
    target_units = normalized_units(baseline_deck.get("units"))

    source_width = positive_number(source_deck.get("ref_width"), "source ref_width")
    source_height = positive_number(source_deck.get("ref_height"), "source ref_height")
    target_width = positive_number(baseline_deck.get("ref_width"), "baseline ref_width")
    target_height = positive_number(baseline_deck.get("ref_height"), "baseline ref_height")
    if abs(source_width / source_height - target_width / target_height) > 1e-6:
        raise ValueError("source and baseline decks disagree on aspect ratio")

    matching = [slide for slide in source_deck.get("slides", []) if str(slide.get("slide_id")) == slide_id]
    if len(matching) != 1:
        raise ValueError(f"expected exactly one {slide_id} slide, found {len(matching)}")

    scale_x = target_width / source_width
    scale_y = target_height / source_height
    scaled_slide = scale_geometry(matching[0], scale_x, scale_y)
    source_assets = resolve_assets_dir(source_deck, source_deck_path)
    packaged_assets = out_dir / "assets" / slide_id / "packaged"
    copied: dict[Path, str] = {}
    records: list[dict[str, Any]] = []
    rewrites: list[dict[str, str]] = []
    packaged_slide = package_file_references(
        scaled_slide,
        deck_path=source_deck_path,
        assets_dir=source_assets,
        target_dir=packaged_assets,
        output_root=out_dir,
        copied=copied,
        records=records,
        rewrites=rewrites,
    )

    packaged_deck = {
        key: copy.deepcopy(value)
        for key, value in baseline_deck.items()
        if key not in {"assets_dir", "slides"}
    }
    packaged_deck.update(
        {
            "units": target_units,
            "ref_width": baseline_deck["ref_width"],
            "ref_height": baseline_deck["ref_height"],
            "slide_width_in": baseline_deck["slide_width_in"],
            "slide_height_in": baseline_deck["slide_height_in"],
            "assets_dir": str(out_dir),
            "slides": [packaged_slide],
        }
    )
    deck_path = out_dir / "deck-high-fidelity.json"
    write_json(deck_path, packaged_deck)

    missing_hash_matches = [
        item for item in records if item["source_sha256"] != item["packaged_sha256"]
    ]
    unresolved_references = audit_packaged_file_references(
        packaged_deck,
        output_root=out_dir,
    )
    report = {
        "schema_version": 1,
        "status": "pass" if not missing_hash_matches and not unresolved_references else "fail",
        "immutable_output": True,
        "slide_id": slide_id,
        "source_deck": str(source_deck_path),
        "source_deck_sha256": sha256_file(source_deck_path),
        "baseline_deck": str(baseline_deck_path),
        "baseline_deck_sha256": sha256_file(baseline_deck_path),
        "output_deck": str(deck_path),
        "output_deck_sha256": sha256_file(deck_path),
        "source_contract": {
            "units": source_deck.get("units"),
            "ref_width": source_deck.get("ref_width"),
            "ref_height": source_deck.get("ref_height"),
            "slide_width_in": source_deck.get("slide_width_in"),
            "slide_height_in": source_deck.get("slide_height_in"),
        },
        "target_contract": {
            "units": target_units,
            "ref_width": baseline_deck.get("ref_width"),
            "ref_height": baseline_deck.get("ref_height"),
            "slide_width_in": baseline_deck.get("slide_width_in"),
            "slide_height_in": baseline_deck.get("slide_height_in"),
        },
        "geometry_scale": {"x": scale_x, "y": scale_y},
        "copied_files": records,
        "copied_file_count": len(records),
        "hash_mismatches": missing_hash_matches,
        "rewritten_dependency_aliases": rewrites,
        "unresolved_file_references": unresolved_references,
    }
    report_path = out_dir / "qa" / "package-report.json"
    write_json(report_path, report)
    if report["status"] != "pass":
        raise RuntimeError("reviewed slide packaging failed")
    return deck_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_deck")
    parser.add_argument("baseline_deck")
    parser.add_argument("--slide", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    deck, report = package_patch(
        Path(args.source_deck),
        Path(args.baseline_deck),
        args.slide,
        Path(args.out_dir),
    )
    print(json.dumps({"deck": str(deck), "report": str(report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
