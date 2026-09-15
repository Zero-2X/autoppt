#!/usr/bin/env python3
"""Build a pixel-anchored editable PPT spec from ImageGen masters and Windows OCR boxes."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import itertools
import json
import re
import shutil
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any


REF_W = 1920
REF_H = 1080
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5
NORMALIZE_MAP = str.maketrans({"賦": "赋", "臺": "台", "裏": "里", "與": "与", "為": "为"})
COMPOUND_LAYERS = {"outer", "middle", "inner"}


def load_cv(tools_path: Path):
    sys.path.insert(0, str(tools_path))
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    return cv2, np


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_override_payload(path: Path) -> dict[str, Any]:
    """Load overrides while preserving the origin of portable panel sources."""

    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"override payload must be a JSON object: {path}")
    resolved_path = path.expanduser().resolve()
    for slide_payload in payload.get("slides", {}).values():
        if not isinstance(slide_payload, dict):
            continue
        for entry in slide_payload.get("reviewed_panels", []):
            if not isinstance(entry, dict):
                continue
            entry["_override_file"] = str(resolved_path)
            entry["_override_dir"] = str(resolved_path.parent)
            raw_source = entry.get("content_source_file")
            if raw_source is None:
                continue
            source_path = Path(str(raw_source)).expanduser()
            if not source_path.is_absolute():
                source_path = resolved_path.parent / source_path
            entry["_resolved_content_source_file"] = str(source_path.resolve())
    return payload


def resolve_optional_json_path(
    run_dir: Path,
    raw_path: str,
    *,
    option_name: str,
    explicitly_requested: bool,
) -> Path:
    """Resolve an optional run artifact, failing closed for explicit inputs."""

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (run_dir / path).resolve()
    if explicitly_requested and not path.exists():
        raise FileNotFoundError(f"{option_name} file does not exist: {path}")
    return path


def option_was_explicit(argv: list[str], option_name: str) -> bool:
    return any(
        argument == option_name or argument.startswith(f"{option_name}=")
        for argument in argv
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_override_payloads(*payloads: dict[str, Any]) -> dict[str, Any]:
    """Merge independent visual-review and semantic-completion override files."""
    merged: dict[str, Any] = {"slides": {}}
    for payload in payloads:
        for slide_id, slide_payload in payload.get("slides", {}).items():
            target = merged["slides"].setdefault(slide_id, {})
            source_size = slide_payload.get("source_size")
            if source_size is not None:
                existing_size = target.get("source_size")
                if existing_size is not None and list(existing_size) != list(source_size):
                    raise ValueError(
                        f"override source size mismatch for {slide_id}: "
                        f"{existing_size} != {source_size}"
                    )
                target["source_size"] = source_size
            notes = [
                str(value).strip()
                for value in (target.get("review_note"), slide_payload.get("review_note"))
                if str(value or "").strip()
            ]
            if notes:
                target["review_note"] = " | ".join(dict.fromkeys(notes))
            if "preserve_automatic_match" in slide_payload:
                target["preserve_automatic_match"] = bool(slide_payload["preserve_automatic_match"])
            if "preserve_automatic_reference_indices" in slide_payload:
                target["preserve_automatic_reference_indices"] = [
                    int(value) for value in slide_payload["preserve_automatic_reference_indices"]
                ]
            if "counterfactual_background_cleanup" in slide_payload:
                incoming_cleanup = slide_payload["counterfactual_background_cleanup"]
                existing_cleanup = target.get("counterfactual_background_cleanup")
                if existing_cleanup is not None and existing_cleanup != incoming_cleanup:
                    raise ValueError(
                        f"conflicting counterfactual background cleanup for {slide_id}"
                    )
                target["counterfactual_background_cleanup"] = incoming_cleanup
            target.setdefault("texts", []).extend(slide_payload.get("texts", []))
            target.setdefault("cleanup_regions", []).extend(
                slide_payload.get("cleanup_regions", [])
            )
            target.setdefault("panel_exclusions", []).extend(
                slide_payload.get("panel_exclusions", [])
            )
            target.setdefault("native_shapes", []).extend(
                slide_payload.get("native_shapes", [])
            )
            target.setdefault("reviewed_panels", []).extend(
                slide_payload.get("reviewed_panels", [])
            )
    return merged


def reviewed_shape_compound_layer(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("compound_layer") or entry.get("layer") or "").lower()
    if explicit:
        return explicit
    role = str(entry.get("role", "")).lower()
    return next(
        (layer for layer in COMPOUND_LAYERS if f"compound-{layer}" in role),
        "",
    )


def positive_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, (int, float)) for number in value)
        and value[0] >= 0
        and value[1] >= 0
        and value[2] > 0
        and value[3] > 0
    )


def bbox_within(outer: list[float], inner: list[float], tolerance: float = 0.0) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[0] + inner[2] <= outer[0] + outer[2] + tolerance
        and inner[1] + inner[3] <= outer[1] + outer[3] + tolerance
    )


def bbox_within_canvas(bbox: list[float], width: float, height: float) -> bool:
    return bbox_within([0.0, 0.0, float(width), float(height)], bbox)


def valid_hex_color(value: Any) -> bool:
    return bool(re.fullmatch(r"#?[0-9A-Fa-f]{6}", str(value or "").strip()))


def validate_override_payloads(overrides: dict[str, Any]) -> None:
    """Reject reviewed overrides that can knowingly leave raster/native glyph doubles."""
    for slide_id, slide_payload in overrides.get("slides", {}).items():
        counterfactual = slide_payload.get("counterfactual_background_cleanup")
        if counterfactual is not None:
            if not isinstance(counterfactual, dict):
                raise ValueError(
                    f"{slide_id}: counterfactual_background_cleanup must be an object"
                )
            if bool(counterfactual.get("enabled", True)):
                if not str(counterfactual.get("reason", "")).strip():
                    raise ValueError(
                        f"{slide_id}: counterfactual background cleanup requires an auditable reason"
                    )
                for key, minimum, maximum in (
                    ("padding_px", 0.0, 64.0),
                    ("sigma_px", 1.0, 160.0),
                    ("feather_px", 0.0, 24.0),
                ):
                    value = counterfactual.get(key)
                    if value is None:
                        continue
                    if not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
                        raise ValueError(
                            f"{slide_id}: counterfactual {key} must be between {minimum:g} and {maximum:g}"
                        )
                global_surface = counterfactual.get("global_surface")
                if global_surface is not None:
                    if not isinstance(global_surface, dict):
                        raise ValueError(
                            f"{slide_id}: counterfactual global_surface must be an object"
                        )
                    if bool(global_surface.get("enabled", True)):
                        apply_scope = str(
                            global_surface.get("apply_scope", "semantic-mask")
                        ).strip().lower()
                        if apply_scope not in {"semantic-mask", "full-slide"}:
                            raise ValueError(
                                f"{slide_id}: counterfactual global_surface apply_scope "
                                "must be semantic-mask or full-slide"
                            )
                        for key, minimum, maximum in (
                            ("degree", 1.0, 5.0),
                            ("sample_stride_px", 2.0, 64.0),
                            ("robust_iterations", 1.0, 8.0),
                            ("prefilter_sigma_px", 0.0, 80.0),
                            ("huber_sigma", 1.0, 8.0),
                            ("minimum_scale_0_255", 0.1, 32.0),
                            ("prediction_chunk_rows", 8.0, 512.0),
                            ("fit_exclusion_padding_px", 0.0, 64.0),
                            ("strength", 0.0, 1.0),
                            ("transition_px", 0.0, 64.0),
                        ):
                            value = global_surface.get(key)
                            if value is None:
                                continue
                            if not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
                                raise ValueError(
                                    f"{slide_id}: counterfactual global_surface {key} "
                                    f"must be between {minimum:g} and {maximum:g}"
                                )
        preserved = {
            int(value) for value in slide_payload.get("preserve_automatic_reference_indices", [])
        }
        for entry in slide_payload.get("texts", []):
            reference_index = int(entry["reference_index"])
            cleanup_mode = str(entry.get("cleanup_mode", "inpaint")).lower()
            always_apply = bool(entry.get("always_apply", False))
            replace_match = bool(entry.get("replace_match", False))
            patch_match = bool(entry.get("patch_match", False))
            partial_reference_override = bool(entry.get("partial_reference_override", False))

            if patch_match:
                continue
            if always_apply and cleanup_mode == "none" and not entry.get(
                "allow_raster_text_overlay", False
            ):
                raise ValueError(
                    f"{slide_id}/{entry.get('name', reference_index)} always applies native text "
                    "without removing the source glyphs; choose a cleanup mode or explicitly set "
                    "allow_raster_text_overlay for a measured same-position exception"
                )
            if replace_match and reference_index in preserved and not partial_reference_override:
                raise ValueError(
                    f"{slide_id}/{entry.get('name', reference_index)} replaces reference "
                    f"{reference_index}, but the slide also preserves that automatic reference"
                )
        for entry in slide_payload.get("panel_exclusions", []):
            bbox = entry.get("bbox") or entry.get("source_bbox")
            if (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or any(float(value) <= 0 for value in bbox[2:])
                or any(not isinstance(value, (int, float)) for value in bbox)
            ):
                raise ValueError(
                    f"{slide_id}: panel exclusion requires a positive four-value bbox"
                )
            if not str(entry.get("reason", "")).strip():
                raise ValueError(
                    f"{slide_id}: panel exclusion requires an auditable reason"
                )
        for entry in slide_payload.get("cleanup_regions", []):
            bboxes = entry.get("mask_bboxes") or [entry.get("mask_bbox", entry.get("bbox"))]
            if not bboxes or any(
                not isinstance(bbox, list)
                or len(bbox) != 4
                or any(not isinstance(value, (int, float)) for value in bbox)
                or any(float(value) <= 0 for value in bbox[2:])
                for bbox in bboxes
            ):
                raise ValueError(
                    f"{slide_id}: cleanup region requires positive four-value source bboxes"
                )
            if not str(entry.get("reason", "")).strip():
                raise ValueError(
                    f"{slide_id}: cleanup region requires an auditable reason"
                )
        native_shapes = list(slide_payload.get("native_shapes", []))
        frame_entries: dict[str, list[dict[str, Any]]] = {}
        for entry in native_shapes:
            bbox = entry.get("source_bbox") or entry.get("bbox")
            if (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or any(not isinstance(value, (int, float)) for value in bbox)
                or any(float(value) <= 0 for value in bbox[2:])
            ):
                raise ValueError(
                    f"{slide_id}: reviewed native shape requires a positive four-value source_bbox"
                )
            if not str(entry.get("reason", "")).strip():
                raise ValueError(
                    f"{slide_id}: reviewed native shape requires an auditable reason"
                )
            cleanup_mode = str(entry.get("background_cleanup", "none")).lower()
            if cleanup_mode not in {
                "none",
                "outline-inpaint",
                "outline-directional",
                "full-frame-directional",
            }:
                raise ValueError(
                    f"{slide_id}: unsupported reviewed native-shape background cleanup "
                    f"{cleanup_mode!r}"
                )
            cleanup_delegate = str(entry.get("cleanup_delegated_to", "")).strip()
            if cleanup_mode == "none" and not cleanup_delegate and not bool(
                entry.get("allow_raster_background_frame", False)
            ):
                raise ValueError(
                    f"{slide_id}: reviewed native shape would be synthesized without "
                    "removing the source frame; choose a cleanup mode or explicitly "
                    "record allow_raster_background_frame for a non-Gold exception"
                )
            shape_type = str(entry.get("type", "rounded_rect")).lower()
            if shape_type in {"line", "connector"} and not all(
                key in entry for key in ("x1", "y1", "x2", "y2")
            ):
                raise ValueError(
                    f"{slide_id}: reviewed native line requires x1/y1/x2/y2"
                )
            frame_id = str(entry.get("frame_id", "")).strip()
            if frame_id:
                frame_entries.setdefault(frame_id, []).append(entry)

        reviewed_panels = list(slide_payload.get("reviewed_panels", []))
        reviewed_panel_ids: set[str] = set()
        source_size = slide_payload.get("source_size")
        source_canvas = (
            [float(value) for value in source_size]
            if isinstance(source_size, list)
            and len(source_size) == 2
            and all(isinstance(value, (int, float)) and value > 0 for value in source_size)
            else None
        )
        for panel_index, entry in enumerate(reviewed_panels):
            if not isinstance(entry, dict):
                raise ValueError(f"{slide_id}: reviewed panel must be an object")
            frame_id = str(entry.get("frame_id", "")).strip()
            if not frame_id:
                raise ValueError(f"{slide_id}: reviewed panel requires frame_id")
            if frame_id in reviewed_panel_ids or frame_id in frame_entries:
                raise ValueError(
                    f"{slide_id}: reviewed panel frame_id must be unique: {frame_id}"
                )
            reviewed_panel_ids.add(frame_id)
            frame_bbox = entry.get("frame_bbox")
            content_bbox = entry.get("content_bbox")
            if not positive_bbox(frame_bbox):
                raise ValueError(
                    f"{slide_id}/{frame_id}: reviewed panel requires a positive frame_bbox"
                )
            if not positive_bbox(content_bbox):
                raise ValueError(
                    f"{slide_id}/{frame_id}: reviewed panel requires a positive content_bbox"
                )
            frame_values = [float(value) for value in frame_bbox]
            content_values = [float(value) for value in content_bbox]
            if not bbox_within(frame_values, content_values):
                raise ValueError(
                    f"{slide_id}/{frame_id}: content_bbox must be inside frame_bbox"
                )
            if source_canvas is not None:
                for label, candidate in (
                    ("frame_bbox", frame_values),
                    ("content_bbox", content_values),
                ):
                    if not bbox_within_canvas(candidate, source_canvas[0], source_canvas[1]):
                        raise ValueError(
                            f"{slide_id}/{frame_id}: {label} is outside the source canvas"
                        )
            if not str(entry.get("reason", "")).strip():
                raise ValueError(
                    f"{slide_id}/{frame_id}: reviewed panel requires an auditable reason"
                )
            native_frame = entry.get("native_frame")
            if not isinstance(native_frame, dict):
                raise ValueError(
                    f"{slide_id}/{frame_id}: reviewed panel requires native_frame style"
                )
            shape_type = str(native_frame.get("type", "")).lower()
            if shape_type not in {"rect", "rounded_rect"}:
                raise ValueError(
                    f"{slide_id}/{frame_id}: native_frame type must be rect or rounded_rect"
                )
            for color_key in ("fill", "line"):
                if not valid_hex_color(native_frame.get(color_key)):
                    raise ValueError(
                        f"{slide_id}/{frame_id}: native_frame {color_key} must be a six-digit RGB color"
                    )
            line_width = native_frame.get("line_width")
            if not isinstance(line_width, (int, float)) or float(line_width) <= 0:
                raise ValueError(
                    f"{slide_id}/{frame_id}: native_frame line_width must be positive"
                )
            opacity = native_frame.get("opacity", 1.0)
            if not isinstance(opacity, (int, float)) or not 0.0 <= float(opacity) <= 1.0:
                raise ValueError(
                    f"{slide_id}/{frame_id}: native_frame opacity must be between zero and one"
                )
            raw_source = entry.get("content_source_file")
            source_bbox = entry.get("content_source_bbox")
            if raw_source is None:
                if source_bbox is not None:
                    raise ValueError(
                        f"{slide_id}/{frame_id}: content_source_bbox requires content_source_file"
                    )
                continue
            if not str(raw_source).strip():
                raise ValueError(
                    f"{slide_id}/{frame_id}: content_source_file cannot be empty"
                )
            if source_bbox is not None and not positive_bbox(source_bbox):
                raise ValueError(
                    f"{slide_id}/{frame_id}: content_source_bbox must be a positive bbox"
                )
            resolved_source = entry.get("_resolved_content_source_file")
            if not resolved_source:
                raw_path = Path(str(raw_source)).expanduser()
                if not raw_path.is_absolute():
                    raise ValueError(
                        f"{slide_id}/{frame_id}: relative content_source_file requires "
                        "override JSON origin metadata"
                    )
                resolved_source = str(raw_path.resolve())
                entry["_resolved_content_source_file"] = resolved_source
            resolved_path = Path(str(resolved_source))
            if not resolved_path.exists() or not resolved_path.is_file():
                raise FileNotFoundError(
                    f"{slide_id}/{frame_id}: content_source_file does not exist: {resolved_path}"
                )

        delegated_entries_by_parent: dict[str, list[dict[str, Any]]] = {}
        for entry in native_shapes:
            cleanup_delegate = str(entry.get("cleanup_delegated_to", "")).strip()
            if not cleanup_delegate:
                continue
            name = str(entry.get("name") or entry.get("frame_id") or "reviewed-native-shape")
            frame_id = str(entry.get("frame_id", "")).strip()
            if not frame_id:
                raise ValueError(f"{slide_id}/{name}: delegated cleanup requires frame_id")
            if cleanup_delegate == frame_id:
                raise ValueError(f"{slide_id}/{name}: cleanup delegate cannot reference itself")
            parent_entries = frame_entries.get(cleanup_delegate, [])
            if not parent_entries:
                raise ValueError(
                    f"{slide_id}/{name}: cleanup delegate {cleanup_delegate} does not exist"
                )
            if len(parent_entries) != 1:
                raise ValueError(
                    f"{slide_id}/{name}: cleanup delegate {cleanup_delegate} is not unique"
                )
            parent = parent_entries[0]
            parent_cleanup = str(parent.get("background_cleanup", "none")).lower()
            if parent_cleanup != "full-frame-directional":
                raise ValueError(
                    f"{slide_id}/{name}: cleanup delegate {cleanup_delegate} must use "
                    "full-frame-directional cleanup"
                )
            child_layer = reviewed_shape_compound_layer(entry)
            parent_layer = reviewed_shape_compound_layer(parent)
            if child_layer not in {"middle", "inner"} or parent_layer != "outer":
                raise ValueError(
                    f"{slide_id}/{name}: delegated compound layers require an outer parent "
                    "and a middle or inner child"
                )
            child_z = entry.get("z_order_within_compound")
            parent_z = parent.get("z_order_within_compound")
            if not isinstance(child_z, (int, float)) or not isinstance(
                parent_z, (int, float)
            ):
                raise ValueError(
                    f"{slide_id}/{name}: delegated compound layers require numeric z-order"
                )
            if float(child_z) <= float(parent_z):
                raise ValueError(
                    f"{slide_id}/{name}: z-order must be greater than its cleanup delegate"
                )
            delegated_entries_by_parent.setdefault(cleanup_delegate, []).append(entry)

        layer_rank = {"outer": 0, "middle": 1, "inner": 2}
        for parent_id, children in delegated_entries_by_parent.items():
            members = [frame_entries[parent_id][0], *children]
            layers = [reviewed_shape_compound_layer(member) for member in members]
            if len(layers) != len(set(layers)):
                raise ValueError(
                    f"{slide_id}/{parent_id}: compound cleanup group contains duplicate layers"
                )
            for left, right in itertools.combinations(members, 2):
                left_layer = reviewed_shape_compound_layer(left)
                right_layer = reviewed_shape_compound_layer(right)
                if left_layer == right_layer:
                    continue
                lower, upper = (
                    (left, right)
                    if layer_rank[left_layer] < layer_rank[right_layer]
                    else (right, left)
                )
                if float(lower["z_order_within_compound"]) >= float(
                    upper["z_order_within_compound"]
                ):
                    raise ValueError(
                        f"{slide_id}/{parent_id}: compound layer z-order is not strictly "
                        "increasing from outer to inner"
                    )


def dedupe_text_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove exact duplicate native text caused by overlapping OCR segment paths."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[int, ...]]] = set()
    for item in items:
        text = str(item.get("text", "")).strip()
        bbox = item.get("source_bbox") or item.get("layout_bbox") or []
        try:
            key_bbox = tuple(int(round(float(value))) for value in bbox)
        except (TypeError, ValueError):
            key_bbox = tuple()
        key = (text, key_bbox)
        if text and key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def normalize_text(value: str) -> str:
    value = value.translate(NORMALIZE_MAP)
    return re.sub(r"[^0-9A-Za-z\u3400-\u4dbf\u4e00-\u9fff]+", "", value).lower()


def repair_mojibake(value: str) -> str:
    best = value
    best_score = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", value)) - value.count("�") * 10
    for encoding in ("gbk", "latin1"):
        try:
            candidate = value.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        score = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", candidate)) - candidate.count("�") * 10
        score -= len(re.findall(r"[鑸淮锛绛璇鍥妯]", candidate)) * 0.2
        if score > best_score:
            best = candidate
            best_score = score
    return best


def line_bbox(lines: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    x1 = min(int(line["bbox"]["x"]) for line in lines)
    y1 = min(int(line["bbox"]["y"]) for line in lines)
    x2 = max(int(line["bbox"]["x"] + line["bbox"]["w"]) for line in lines)
    y2 = max(int(line["bbox"]["y"] + line["bbox"]["h"]) for line in lines)
    return x1, y1, x2 - x1, y2 - y1


def candidate_groups(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def related(first: dict[str, Any], second: dict[str, Any]) -> bool:
        a = first["bbox"]
        b = second["bbox"]
        a_cx = a["x"] + a["w"] / 2
        b_cx = b["x"] + b["w"] / 2
        a_cy = a["y"] + a["h"] / 2
        b_cy = b["y"] + b["h"] / 2
        same_row = abs(a_cy - b_cy) <= max(a["h"], b["h"]) * 0.72
        horizontal_gap = max(0.0, max(a["x"], b["x"]) - min(a["x"] + a["w"], b["x"] + b["w"]))
        overlap_x = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
        same_column = overlap_x >= min(a["w"], b["w"]) * 0.22 or abs(a_cx - b_cx) <= max(a["w"], b["w"]) * 0.30
        vertical_gap = max(0.0, max(a["y"], b["y"]) - min(a["y"] + a["h"], b["y"] + b["h"]))
        return (same_row and horizontal_gap <= 470) or (same_column and vertical_gap <= max(a["h"], b["h"]) * 2.5)

    groups = []
    combinations_seen: set[tuple[int, ...]] = set()
    for first_index, first in enumerate(lines):
        nearby = []
        first_box = first["bbox"]
        first_cx = first_box["x"] + first_box["w"] / 2
        first_cy = first_box["y"] + first_box["h"] / 2
        for index in range(first_index + 1, len(lines)):
            box = lines[index]["bbox"]
            center_x = box["x"] + box["w"] / 2
            center_y = box["y"] + box["h"] / 2
            if related(first, lines[index]) or (abs(center_x - first_cx) <= 520 and abs(center_y - first_cy) <= 130):
                distance = abs(center_y - first_cy) * 2.0 + abs(center_x - first_cx) * 0.25
                nearby.append((distance, index))
        neighbor_indices = [index for _, index in sorted(nearby)[:28]]
        for count in (1, 2, 3, 4):
            for tail in itertools.combinations(neighbor_indices, count - 1):
                combination = (first_index, *tail)
                if combination in combinations_seen:
                    continue
                combinations_seen.add(combination)
                if count > 1:
                    connected = {combination[0]}
                    changed = True
                    while changed:
                        changed = False
                        for index in combination:
                            if index in connected:
                                continue
                            if any(related(lines[index], lines[other]) for other in connected):
                                connected.add(index)
                                changed = True
                    if len(connected) != count:
                        continue
                selected = sorted(
                    (lines[index] for index in combination),
                    key=lambda line: (round(float(line["bbox"]["y"]) / 12), float(line["bbox"]["x"])),
                )
                raw_text = " ".join(str(line.get("text", "")) for line in selected)
                groups.append(
                    {
                        "indices": combination,
                        "lines": selected,
                        "text": raw_text,
                        "normalized": normalize_text(raw_text),
                        "bbox": line_bbox(selected),
                    }
                )
    return groups


def numeric_tokens(value: str) -> list[str]:
    compact = value.replace("％", "%").replace("，", ".").replace("．", ".")
    compact = compact.replace("·", ".").replace("•", ".")
    compact = re.sub(r"\s*([.+\-])\s*", r"\1", compact)
    compact = re.sub(r"\s*%\s*", "%", compact)
    tokens = re.findall(r"(?<![A-Za-z])[+-]?\d+(?:\.\d+)?%?", compact)
    return [token.lstrip("+") if token.startswith("+") else token for token in tokens]


def numeric_overlap_score(expected: str, observed: str) -> tuple[float, float]:
    expected_numbers = numeric_tokens(expected)
    if not expected_numbers:
        return 0.0, 1.0
    observed_numbers = numeric_tokens(observed)
    remaining = list(observed_numbers)
    matches = 0
    for token in expected_numbers:
        if token in remaining:
            remaining.remove(token)
            matches += 1
    ratio = matches / len(expected_numbers)
    score = 0.52 * ratio
    if len(expected_numbers) >= 2 and ratio < 0.5:
        score -= 0.85
    elif len(expected_numbers) >= 2 and ratio < 0.75:
        score -= 0.28
    return score, ratio


def compact_ocr_line(line: dict[str, Any], expected: str) -> str:
    value = "".join(str(word.get("text", "")) for word in line.get("words", []))
    value = value.replace("％", "%").replace("，", ".").replace("．", ".")
    value = value.replace("·", ".").replace("•", ".")
    value = value.replace("丨", "I").replace("｜", "I")
    value = value.replace("準確率", "准确率").replace("准確率", "准确率")
    if "F1" in expected:
        value = re.sub(r"F[Il]", "F1", value, flags=re.IGNORECASE)
    if "IDF1" in expected:
        value = re.sub(r"(?:旧|I[D0])F?[Il1]", "IDF1", value, flags=re.IGNORECASE)
    value = re.sub(r"(F1|IDF1|MOTA|NWLT|IDR)(?=[+-]?\d)", r"\1 ", value, flags=re.IGNORECASE)

    expected_numbers = numeric_tokens(expected)
    remaining = list(expected_numbers)
    pattern = re.compile(r"(?<![A-Za-z])[+-]?\d+(?:\.\d+)?%?")

    def replace_number(match: re.Match[str]) -> str:
        token = match.group(0)
        normalized = token.lstrip("+") if token.startswith("+") else token
        if normalized in remaining:
            index = remaining.index(normalized)
            replacement = remaining.pop(index)
            if token.startswith("+") and not replacement.startswith("+"):
                replacement = "+" + replacement
            return replacement
        return token

    return pattern.sub(replace_number, value)


def split_horizontal_word_clusters(line: dict[str, Any]) -> list[list[dict[str, Any]]]:
    words = sorted(line.get("words", []), key=lambda word: float(word["bbox"]["x"]))
    if not words:
        return []
    heights = [max(1.0, float(word["bbox"]["h"])) for word in words]
    gap_threshold = max(18.0, median(heights) * 1.65)
    clusters: list[list[dict[str, Any]]] = [[words[0]]]
    for word in words[1:]:
        previous = clusters[-1][-1]["bbox"]
        current = word["bbox"]
        gap = float(current["x"]) - float(previous["x"] + previous["w"])
        if gap > gap_threshold:
            clusters.append([word])
        else:
            clusters[-1].append(word)
    return clusters


def extend_numeric_words(
    original_words: list[dict[str, Any]], aligned: list[dict[str, Any]], expected: str
) -> list[dict[str, Any]]:
    ordered = sorted(original_words, key=lambda word: float(word["bbox"]["x"]))
    if not ordered or not aligned:
        return aligned or ordered
    aligned_ids = {id(word) for word in aligned}
    indices = [index for index, word in enumerate(ordered) if id(word) in aligned_ids]
    if not indices:
        return aligned
    start = min(indices)
    end = max(indices)
    heights = [max(1.0, float(word["bbox"]["h"])) for word in ordered[start : end + 1]]
    gap_threshold = max(6.0, median(heights) * 0.75)
    while start > 0:
        previous = ordered[start - 1]["bbox"]
        current = ordered[start]["bbox"]
        gap = float(current["x"]) - float(previous["x"] + previous["w"])
        if gap > gap_threshold:
            break
        start -= 1
    while end + 1 < len(ordered):
        current = ordered[end]["bbox"]
        following = ordered[end + 1]["bbox"]
        gap = float(following["x"]) - float(current["x"] + current["w"])
        if gap > gap_threshold:
            following_text = normalize_text(str(ordered[end + 1].get("text", "")))
            expected_text = normalize_text(expected)
            extended_threshold = max(gap_threshold, median(heights) * 2.2)
            if not following_text or following_text not in expected_text or gap > extended_threshold:
                break
        end += 1
    return ordered[start : end + 1]


def compact_numeric_cluster(words: list[dict[str, Any]], expected: str) -> str:
    value = compact_ocr_line({"words": words}, expected)
    value = re.sub(r"(准确率|滞后率)(?=[+-]?\d)", r"\1 ", value)
    value = re.sub(
        r"(%|\d)(?=(?:F1|IDF1|MOTA|NWLT|IDR|准确率|滞后率))",
        r"\1  ",
        value,
        flags=re.IGNORECASE,
    )

    marker_positions = [
        position
        for marker in ("准确率", "滞后率", "IDF1", "MOTA", "NWLT", "IDR", "F1")
        if (position := value.upper().find(marker.upper())) >= 0
    ]
    if marker_positions:
        value = value[min(marker_positions) :]

    numbers = list(re.finditer(r"(?<![A-Za-z])[+-]?\d+(?:\.\d+)?%?", value))
    if not numbers:
        return ""
    value = value[: numbers[-1].end()]
    return value.strip(" ·•、，,;|")


def expected_numeric_chunks(expected: str) -> list[str]:
    return [piece.strip() for piece in re.split(r"\s*·\s*|[，；;]", expected) if piece.strip()]


def trailing_expected_punctuation(expected: str, chunk: str) -> str:
    position = expected.find(chunk)
    if position < 0:
        return ""
    suffix = expected[position + len(chunk) :].lstrip()
    return suffix[0] if suffix and suffix[0] in "，；,;" else ""


def render_expected_numeric_segment(observed: str, chunks: list[str]) -> str:
    combined = "  ".join(chunks).strip()
    observed_normalized = normalize_text(observed)
    markers = (
        "临界滞后率",
        "对应绝对时间",
        "准确率",
        "滞后率",
        "PSNR",
        "SSIM",
        "IDF1",
        "MOTA",
        "NWLT",
        "IDR",
        "F1",
        "E降至",
        "B为",
    )
    marker_candidates = []
    for marker in markers:
        marker_index = combined.upper().find(marker.upper())
        if marker_index >= 0 and normalize_text(marker) in observed_normalized:
            marker_candidates.append((marker_index, marker))
    if marker_candidates:
        marker_index, _ = min(marker_candidates, key=lambda item: item[0])
        return combined[marker_index:].strip()

    number_spans = list(re.finditer(r"(?<![A-Za-z])[+-]?\d+(?:\.\d+)?%?", combined))
    if not number_spans:
        return combined
    start = number_spans[0].start()
    end = number_spans[-1].end()
    suffix = combined[end:]
    unit_match = re.match(r"\s*([㐀-䶿一-鿿]{1,4})", suffix)
    unit = unit_match.group(1) if unit_match else ""
    return (combined[start:end] + unit).strip()


def numeric_ocr_segments(lines: list[dict[str, Any]], expected: str) -> list[dict[str, Any]]:
    raw_segments = []
    for line in sorted(lines, key=lambda item: (float(item["bbox"]["y"]), float(item["bbox"]["x"]))):
        for words in split_horizontal_word_clusters(line):
            raw = "".join(str(word.get("text", "")) for word in words)
            if not numeric_tokens(raw):
                continue
            display_text = compact_numeric_cluster(words, expected)
            if not display_text or not numeric_tokens(display_text):
                continue
            aligned = aligned_words(display_text, {"words": words})
            if aligned:
                words = extend_numeric_words(words, aligned, expected)
                display_text = compact_numeric_cluster(words, expected)
                if not display_text or not numeric_tokens(display_text):
                    continue
            raw_segments.append(
                {
                    "line": line,
                    "words": words,
                    "mask_bbox": bbox_for_words(words),
                    "observed_text": display_text,
                }
            )

    chunks = expected_numeric_chunks(expected)
    chunk_cursor = 0
    segments = []
    for segment in raw_segments:
        # OCR commonly appends a stray axis tick or confidence fragment to a
        # metric line. Once every source-backed numeric chunk has been routed,
        # ignore those surplus detections instead of falling back to the whole
        # expected string and creating an overlapping duplicate text box.
        if chunk_cursor >= len(chunks):
            continue
        observed_count = max(1, len(numeric_tokens(segment["observed_text"])))
        assigned_chunks = []
        assigned_count = 0
        while chunk_cursor < len(chunks) and assigned_count < observed_count:
            chunk = chunks[chunk_cursor]
            chunk_cursor += 1
            chunk_count = len(numeric_tokens(chunk))
            if chunk_count == 0:
                continue
            assigned_chunks.append(chunk)
            assigned_count += chunk_count
        if not assigned_chunks:
            continue
        display_text = render_expected_numeric_segment(segment["observed_text"], assigned_chunks)
        punctuation = trailing_expected_punctuation(expected, assigned_chunks[-1])
        if punctuation and not display_text.endswith(punctuation):
            display_text += punctuation
        segments.append(
            {
                "line": segment["line"],
                "words": segment["words"],
                "mask_bbox": segment["mask_bbox"],
                "text": display_text,
            }
        )
    return segments


def numeric_table_cell_candidates(
    lines: list[dict[str, Any]], source_h: int
) -> list[dict[str, Any]]:
    """Collect small OCR boxes that can be table cells without trusting OCR text."""
    candidates = []
    for line_index, line in enumerate(lines):
        bbox = line.get("bbox", {})
        x = float(bbox.get("x", 0))
        y = float(bbox.get("y", 0))
        w = float(bbox.get("w", 0))
        h = float(bbox.get("h", 0))
        if h < 9 or h > 24 or w < 8 or w > 90:
            continue
        if y < source_h * 0.18 or y > source_h * 0.62:
            continue
        raw = str(line.get("text", ""))
        tokens = numeric_tokens(raw)
        if not tokens:
            continue
        # Long prose lines with an incidental number are not table cells.
        if len(normalize_text(raw)) > 22 and len(tokens) <= 2:
            continue
        candidates.append(
            {
                "line_index": line_index,
                "line": line,
                "bbox": [int(round(x)), int(round(y)), int(round(w)), int(round(h))],
                "tokens": tokens,
                "center_x": x + w / 2.0,
                "center_y": y + h / 2.0,
            }
        )
    return candidates


def cluster_numeric_table_rows(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not candidates:
        return []
    heights = [max(1.0, float(item["bbox"][3])) for item in candidates]
    tolerance = max(10.0, min(16.0, median(heights) * 0.88))
    rows: list[list[dict[str, Any]]] = []
    for candidate in sorted(candidates, key=lambda item: (item["center_y"], item["center_x"])):
        placed = False
        for row in rows:
            center = median(item["center_y"] for item in row)
            if abs(candidate["center_y"] - center) <= tolerance:
                row.append(candidate)
                placed = True
                break
        if not placed:
            rows.append([candidate])
    return [sorted(row, key=lambda item: item["center_x"]) for row in rows]


def cluster_numeric_table_columns(candidates: list[dict[str, Any]]) -> list[float]:
    if not candidates:
        return []
    centers = sorted(float(item["center_x"]) for item in candidates)
    gap_threshold = max(22.0, min(34.0, median([max(1.0, float(item["bbox"][2])) for item in candidates]) * 0.72))
    clusters: list[list[float]] = [[centers[0]]]
    for center in centers[1:]:
        if center - clusters[-1][-1] <= gap_threshold:
            clusters[-1].append(center)
        else:
            clusters.append([center])
    return [float(median(cluster)) for cluster in clusters]


def table_row_key(expected: str) -> str | None:
    match = re.search(r"([PZ])\s*(\d+)", expected, flags=re.IGNORECASE)
    return match.group(1).upper() + match.group(2) if match else None


def is_control_table_reference(expected: str) -> bool:
    return bool(re.search(r"对照|固定|\bB\b", expected, flags=re.IGNORECASE))


def make_numeric_table_text_item(
    match: dict[str, Any],
    expected: str,
    bbox: list[int],
    line: dict[str, Any],
    source: Any,
    np: Any,
    source_w: int,
    source_h: int,
    color: str,
    name: str,
    layout_bbox: list[int] | None = None,
) -> dict[str, Any]:
    item = make_text_item(
        match,
        expected,
        bbox,
        [line],
        source_w,
        source_h,
        color,
        0,
        None,
    )
    item["name"] = name
    item["align"] = "center"
    item["bold"] = True
    item["table_cell"] = True
    item["editability_level"] = "native"
    if layout_bbox:
        layout_x, layout_y, layout_w, layout_h = scaled_bbox(layout_bbox, source_w, source_h)
        item["x"] = layout_x
        item["y"] = layout_y
        item["w"] = layout_w
        item["h"] = layout_h
        item["layout_bbox"] = [layout_x, layout_y, layout_w, layout_h]
    return item


def numeric_table_fallback(
    references: list[dict[str, Any]],
    unmatched: list[dict[str, Any]],
    ocr_lines: list[dict[str, Any]],
    source: Any,
    np: Any,
    cv2: Any,
    source_w: int,
    source_h: int,
    mask: Any,
    text_items: list[dict[str, Any]],
    slide_id: str,
    excluded_reference_indices: set[int] | None = None,
) -> tuple[set[int], list[dict[str, Any]]]:
    """Recover exact numeric cells from a strongly repeated OCR table grid.

    The grid supplies only geometry. Every inserted string still comes from the
    source prompt manifest, so OCR is never allowed to invent a metric.
    """
    excluded_reference_indices = excluded_reference_indices or set()
    entries = [
        item
        for item in unmatched
        if int(item.get("reference_index", -1)) not in excluded_reference_indices
        if len(numeric_tokens(str(item.get("text", "")))) >= 3
    ]
    if len(entries) < 2:
        return set(), []
    metric_counts = [len(numeric_tokens(str(item["text"]))) for item in entries]
    metric_count = max(set(metric_counts), key=metric_counts.count)
    if metric_count < 3:
        return set(), []

    candidates = numeric_table_cell_candidates(ocr_lines, source_h)
    rows = cluster_numeric_table_rows(candidates)
    rows = [row for row in rows if len(row) >= 3]
    if len(rows) < 3:
        return set(), []

    # The first dense row establishes the left edge of the metric grid. This
    # drops row labels such as "Z2" that OCR may report as numeric fragments.
    first_row = min(rows, key=lambda row: median(item["center_y"] for item in row))
    data_start_x = min(item["center_x"] for item in first_row)
    rows = [
        sorted(
            [item for item in row if item["center_x"] >= data_start_x - 24.0],
            key=lambda item: item["center_x"],
        )
        for row in rows
    ]
    rows = [row for row in rows if len(row) >= 3]
    if len(rows) < 3:
        return set(), []

    unique_keys = []
    for item in entries:
        key = table_row_key(str(item["text"]))
        if key and key not in unique_keys:
            unique_keys.append(key)
    target_row_count = max(3, min(4, len(unique_keys) or len(entries)))
    if len(rows) > target_row_count:
        # Prefer the most populated contiguous block with the expected row count.
        best_block = None
        best_score = -1.0
        for start in range(0, len(rows) - target_row_count + 1):
            block = rows[start : start + target_row_count]
            counts = [len(row) for row in block]
            gaps = [
                median(item["center_y"] for item in block[index + 1])
                - median(item["center_y"] for item in block[index])
                for index in range(len(block) - 1)
            ]
            regularity = 1.0 / (1.0 + (max(gaps) - min(gaps) if gaps else 0.0))
            score = sum(counts) + regularity * 25.0
            if score > best_score:
                best_score = score
                best_block = block
        rows = best_block or rows[:target_row_count]

    all_grid_candidates = [item for row in rows for item in row]
    columns = cluster_numeric_table_columns(all_grid_candidates)
    if len(columns) < metric_count * 2:
        return set(), []
    columns = columns[: metric_count * 2 + 1]
    if len(columns) < metric_count * 2:
        return set(), []

    row_centers = [median(item["center_y"] for item in row) for row in rows]
    row_by_key = {}
    for key in unique_keys:
        match = re.search(r"(\d+)$", key)
        if match:
            index = int(match.group(1)) - 1
            if 0 <= index < len(rows):
                row_by_key[key] = index

    cell_widths = [float(item["bbox"][2]) for item in all_grid_candidates]
    cell_heights = [float(item["bbox"][3]) for item in all_grid_candidates]
    default_w = max(18.0, median(cell_widths))
    default_h = max(12.0, median(cell_heights))
    column_tolerance = max(28.0, median([columns[i + 1] - columns[i] for i in range(len(columns) - 1)]) * 0.58)

    by_row_and_column: dict[tuple[int, int], dict[str, Any]] = {}
    for row_index, row in enumerate(rows):
        for candidate in row:
            column_index = min(range(len(columns)), key=lambda index: abs(columns[index] - candidate["center_x"]))
            if abs(columns[column_index] - candidate["center_x"]) <= column_tolerance:
                by_row_and_column[(row_index, column_index)] = candidate

    resolved: set[int] = set()
    report = []
    last_row_key = None
    for unmatched_item in sorted(entries, key=lambda item: int(item["reference_index"])):
        reference_index = int(unmatched_item["reference_index"])
        expected = str(unmatched_item["text"])
        reference = references[reference_index]
        key = table_row_key(expected)
        if key and key in row_by_key:
            row_index = row_by_key[key]
        elif is_control_table_reference(expected) and last_row_key in row_by_key:
            row_index = row_by_key[last_row_key]
        else:
            # Keep unknown rows deterministic and source-order anchored.
            seen_before = [
                table_row_key(str(item["text"]))
                for item in sorted(entries, key=lambda item: int(item["reference_index"]))
                if int(item["reference_index"]) < reference_index and table_row_key(str(item["text"]))
            ]
            row_index = min(len(set(seen_before)), len(rows) - 1)
        if key:
            last_row_key = key

        tokens = numeric_tokens(expected)
        offset = metric_count if is_control_table_reference(expected) else 0
        if row_index >= len(rows) or offset + len(tokens) > len(columns):
            continue
        cell_report = []
        for token_index, token in enumerate(tokens):
            column_index = offset + token_index
            candidate = by_row_and_column.get((row_index, column_index))
            if candidate:
                bbox = list(candidate["bbox"])
                line = candidate["line"]
                words = line.get("words", [])
            else:
                cx = columns[column_index]
                cy = row_centers[row_index]
                bbox = [
                    int(round(cx - default_w / 2.0)),
                    int(round(cy - default_h / 2.0)),
                    int(round(default_w)),
                    int(round(default_h)),
                ]
                words = []
                line = {"text": "", "words": [{"text": token, "bbox": {"x": bbox[0], "y": bbox[1], "w": bbox[2], "h": bbox[3]}}]}
            mask_bbox = tuple(int(value) for value in bbox)
            add_text_mask(mask, [mask_bbox], cv2)
            if words:
                color = color_bucket(
                    foreground_color(
                        source,
                        rectangles_for_words(words),
                        np,
                    )
                )
            else:
                color = color_bucket(foreground_color(source, [mask_bbox], np))
            if color == "FFFFFF":
                color = "0A6F63" if offset == 0 else "1C5AA6"
            left_gap = columns[column_index] - columns[column_index - 1] if column_index > 0 else columns[1] - columns[0]
            right_gap = columns[column_index + 1] - columns[column_index] if column_index + 1 < len(columns) else left_gap
            cell_left = columns[column_index] - left_gap * 0.52
            cell_right = columns[column_index] + right_gap * 0.52
            cell_inset = max(2.0, min(9.0, (cell_right - cell_left) * 0.08))
            cell_layout_w = max(24.0, cell_right - cell_left - cell_inset * 2.0)
            cell_layout_h = max(24.0, default_h * 2.35)
            cell_layout_bbox = [
                int(round(cell_left + cell_inset)),
                int(round(row_centers[row_index] - cell_layout_h / 2.0)),
                int(round(cell_layout_w)),
                int(round(cell_layout_h)),
            ]
            synthetic_match = {
                "reference": reference,
                "reference_index": reference_index,
                "score": 1.0,
                "expected_text": expected,
            }
            text_items.append(
                make_numeric_table_text_item(
                    synthetic_match,
                    token,
                    bbox,
                    line,
                    source,
                    np,
                    source_w,
                    source_h,
                    color,
                    f"hf-table-{slide_id}-{reference_index:03d}-{token_index:02d}",
                    cell_layout_bbox,
                )
            )
            cell_report.append(
                {
                    "token": token,
                    "source_bbox": bbox,
                    "column_index": column_index,
                    "ocr_text": str(line.get("text", "")),
                    "ocr_tokens": numeric_tokens(str(line.get("text", ""))),
                    "inferred_geometry": not bool(candidate),
                }
            )
        if len(cell_report) == len(tokens):
            resolved.add(reference_index)
            report.append(
                {
                    "reference_index": reference_index,
                    "expected_text": expected,
                    "row_index": row_index,
                    "control_columns": bool(offset),
                    "method": "numeric-table-grid-exact-text-fallback",
                    "cells": cell_report,
                }
            )
    return resolved, report


def match_reference_texts(
    references: list[dict[str, Any]], lines: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups = candidate_groups(lines)
    used: set[int] = set()
    matches = []
    unmatched = []
    ordered = list(enumerate(references))

    for ref_index, reference in ordered:
        expected = str(reference.get("text", "")).strip()
        normalized = normalize_text(expected)
        if not normalized:
            unmatched.append({"reference_index": ref_index, "text": expected, "reason": "empty-normalized-text"})
            continue
        best = None
        best_score = -1.0
        for group in groups:
            if any(index in used for index in group["indices"]):
                continue
            observed = group["normalized"]
            if not observed:
                continue
            score = difflib.SequenceMatcher(None, normalized, observed).ratio()
            length_ratio = min(len(normalized), len(observed)) / max(len(normalized), len(observed))
            if length_ratio >= 0.78 and (normalized in observed or observed in normalized):
                score += 0.22
            score += 0.12 * length_ratio
            if length_ratio < 0.68:
                score -= 0.35
            prefix = re.split(r"[：:]", expected, maxsplit=1)[0]
            normalized_prefix = normalize_text(prefix)
            if len(normalized_prefix) >= 2 and prefix != expected:
                score += 0.32 if normalized_prefix in observed else -0.28
            semantic_count = len([piece for piece in re.split(r"\s*[·；;]\s*|\s*[：:]\s*", expected) if piece.strip()])
            if semantic_count > 1:
                score -= abs(len(group["lines"]) - semantic_count) * 0.10
            numeric_score, numeric_ratio = numeric_overlap_score(expected, group["text"])
            score += numeric_score
            if numeric_ratio == 1.0 and len(numeric_tokens(expected)) >= 2:
                score += 0.20
            score -= max(0, len(group["lines"]) - 1) * 0.035
            if not numeric_tokens(expected) and numeric_tokens(group["text"]):
                score -= min(0.36, 0.12 * len(numeric_tokens(group["text"])))
            if "psnr" in normalized or "ssim" in normalized:
                heights = [float(line["bbox"]["h"]) for line in group["lines"]]
                y1 = min(float(line["bbox"]["y"]) for line in group["lines"])
                y2 = max(float(line["bbox"]["y"] + line["bbox"]["h"]) for line in group["lines"])
                if y2 - y1 > max(heights) * 1.75:
                    score -= 0.65
                if group["bbox"][2] > 900:
                    score -= 1.0
            if score > best_score:
                best_score = score
                best = group

        threshold = 0.72 if len(normalized) <= 4 else 0.56 if len(normalized) <= 10 else 0.43
        if best is None or best_score < threshold:
            unmatched.append(
                {
                    "reference_index": ref_index,
                    "text": expected,
                    "reason": "no-confident-ocr-match",
                    "best_score": round(max(best_score, 0.0), 4),
                }
            )
            continue
        used.update(best["indices"])
        matches.append(
            {
                "reference_index": ref_index,
                "reference": reference,
                "expected_text": expected,
                "ocr_text": best["text"],
                "score": round(best_score, 4),
                "line_indices": list(best["indices"]),
                "lines": best["lines"],
                "bbox": list(best["bbox"]),
            }
        )

    matches.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    unmatched.sort(key=lambda item: item["reference_index"])
    return matches, unmatched


def word_rectangles(match: dict[str, Any]) -> list[tuple[int, int, int, int]]:
    return rectangles_for_words([word for line in match["lines"] for word in line.get("words", [])])


def rectangles_for_words(words: list[dict[str, Any]]) -> list[tuple[int, int, int, int]]:
    rectangles = []
    for word in words:
        box = word["bbox"]
        rectangles.append((int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])))
    return rectangles


def cleanup_rectangles_for_visual_row(
    row: dict[str, Any], words: list[dict[str, Any]]
) -> list[tuple[int, int, int, int]]:
    """Use one continuous aligned-word mask for a labelled visual row.

    Labelled metric rows often contain arrows, decimal points, percent signs,
    and antialiased edges that are split into separate OCR words. Masking each
    word independently leaves visible raster residue between those islands.
    Conversely, the complete OCR line bbox can include a nearby icon that was
    misclassified as a leading glyph. The continuous union of the words aligned
    to the exact manifest text clears the inter-word residue without consuming
    that unrelated visual object. Fall back to the OCR line bbox only when no
    usable word geometry exists.
    """

    aligned_bbox = bbox_for_words(words) if words else None
    if aligned_bbox and aligned_bbox[2] > 0 and aligned_bbox[3] > 0:
        return [tuple(aligned_bbox)]
    box = row.get("bbox") or {}
    values = [box.get(key) for key in ("x", "y", "w", "h")]
    if (
        all(isinstance(value, (int, float)) for value in values)
        and values[2] > 0
        and values[3] > 0
    ):
        return [tuple(int(round(float(value))) for value in values)]
    return rectangles_for_words(words)


def bbox_for_words(words: list[dict[str, Any]]) -> list[int]:
    rectangles = rectangles_for_words(words)
    if not rectangles:
        return [0, 0, 1, 1]
    x1 = min(x for x, _, _, _ in rectangles)
    y1 = min(y for _, y, _, _ in rectangles)
    x2 = max(x + w for x, _, w, _ in rectangles)
    y2 = max(y + h for _, y, _, h in rectangles)
    return [x1, y1, x2 - x1, y2 - y1]


def aligned_words(expected: str, line: dict[str, Any]) -> list[dict[str, Any]]:
    words = line.get("words", [])
    observed = ""
    char_to_word = []
    for index, word in enumerate(words):
        normalized = normalize_text(str(word.get("text", "")))
        for char in normalized:
            observed += char
            char_to_word.append(index)
    target = normalize_text(expected)
    if not observed or not target or not char_to_word:
        return words
    matcher = difflib.SequenceMatcher(None, observed, target)
    included: set[int] = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and j2 > j1 and (i2 - i1) <= (j2 - j1) + 2):
            for char_index in range(i1, i2):
                if char_index < len(char_to_word):
                    included.add(char_to_word[char_index])
    if not included:
        return words
    first = min(included)
    last = max(included)

    expected_text = expected.strip()
    while first > 0 and expected_text and is_punctuation_word(words[first - 1]):
        if not is_punctuation_char(expected_text[0]):
            break
        first -= 1
    while last + 1 < len(words) and expected_text and is_punctuation_word(words[last + 1]):
        if not is_punctuation_char(expected_text[-1]):
            break
        last += 1
    return words[first : last + 1]


def is_punctuation_char(value: str) -> bool:
    return bool(value) and (unicodedata.category(value).startswith("P") or value in "·•")


def is_punctuation_word(word: dict[str, Any]) -> bool:
    value = str(word.get("text", "")).strip()
    return bool(value) and all(is_punctuation_char(char) for char in value)


def semantic_word_groups(
    expected: str, lines: list[dict[str, Any]]
) -> list[tuple[str, list[dict[str, Any]]]]:
    segments = semantic_segments(expected)
    if len(segments) < 3:
        return []

    words = sorted(
        (word for line in lines for word in line.get("words", [])),
        key=lambda word: (float(word["bbox"]["x"]), float(word["bbox"]["y"])),
    )
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    cursor = 0
    for segment in segments:
        target = normalize_text(segment)
        best: tuple[float, int, int] | None = None
        max_window = max(3, len(target) + 4)
        for start in range(cursor, len(words)):
            for end in range(start + 1, min(len(words), start + max_window) + 1):
                observed = normalize_text("".join(str(word.get("text", "")) for word in words[start:end]))
                if not observed:
                    continue
                similarity = difflib.SequenceMatcher(None, target, observed).ratio()
                length_ratio = min(len(target), len(observed)) / max(len(target), len(observed))
                score = similarity + 0.18 * length_ratio - 0.02 * max(0, start - cursor)
                if target in observed or observed in target:
                    score += 0.16
                if best is None or score > best[0]:
                    best = (score, start, end)
        if best is None or best[0] < 0.58:
            return []
        _, start, end = best
        selected = aligned_words(segment, {"words": words[start:end]})
        if not selected:
            return []
        groups.append((segment, selected))
        cursor = end
    return groups


def semantic_segments(value: str) -> list[str]:
    pieces = [piece.strip() for piece in re.split(r"\s*[·•→]\s*", value) if piece.strip()]
    if pieces and "：" in pieces[0]:
        prefix, suffix = pieces[0].split("：", 1)
        if prefix.strip() and suffix.strip():
            pieces = [prefix.strip() + "：", suffix.strip(), *pieces[1:]]
    return pieces


def semantic_line_groups(
    expected: str, lines: list[dict[str, Any]]
) -> list[tuple[str, list[dict[str, Any]]]]:
    segments = semantic_segments(expected)
    if len(segments) < 3:
        return []
    used: set[int] = set()
    groups = []
    for segment in segments:
        target = normalize_text(segment)
        best: tuple[float, int] | None = None
        for index, line in enumerate(lines):
            if index in used:
                continue
            observed = normalize_text(str(line.get("text", "")))
            if not observed:
                continue
            similarity = difflib.SequenceMatcher(None, target, observed).ratio()
            length_ratio = min(len(target), len(observed)) / max(len(target), len(observed))
            score = similarity + 0.18 * length_ratio
            if target in observed or observed in target:
                score += 0.18
            if best is None or score > best[0]:
                best = (score, index)
        if best is None or best[0] < 0.58:
            return []
        _, index = best
        words = aligned_words(segment, lines[index])
        if not words:
            return []
        used.add(index)
        groups.append((segment, words))
    return groups


def best_contiguous_word_span(
    expected: str,
    lines: list[dict[str, Any]],
    excluded_line_indices: set[int] | None = None,
    excluded_word_keys: set[tuple[int, int]] | None = None,
) -> dict[str, Any] | None:
    """Find a source-backed OCR word span for one exact semantic fragment.

    The first-pass matcher deliberately claims whole OCR lines. That is safe for
    titles and prose, but it misses short labels embedded in a longer OCR line
    and references split across five or more independent labels. This fallback
    searches only contiguous words and never invents geometry.
    """

    target = normalize_text(expected)
    if not target:
        return None
    excluded_line_indices = excluded_line_indices or set()
    excluded_word_keys = excluded_word_keys or set()
    best: tuple[float, int, list[dict[str, Any]], set[tuple[int, int]]] | None = None
    for line_index, line in enumerate(lines):
        if line_index in excluded_line_indices:
            continue
        sorted_words = sorted(line.get("words", []), key=lambda word: float(word["bbox"]["x"]))
        if not sorted_words:
            continue
        max_window = min(len(sorted_words), max(4, len(target) + 4))
        for start in range(len(sorted_words)):
            for end in range(start + 1, min(len(sorted_words), start + max_window) + 1):
                word_keys = {(line_index, word_index) for word_index in range(start, end)}
                if word_keys & excluded_word_keys:
                    continue
                words = sorted_words[start:end]
                observed = normalize_text("".join(str(word.get("text", "")) for word in words))
                if not observed:
                    continue
                similarity = difflib.SequenceMatcher(None, target, observed).ratio()
                length_ratio = min(len(target), len(observed)) / max(len(target), len(observed))
                score = similarity + 0.22 * length_ratio
                if target in observed or observed in target:
                    score += 0.20
                score -= max(0, len(observed) - len(target)) * 0.015
                candidate = (score, line_index, words, word_keys)
                if best is None or score > best[0]:
                    best = candidate
    if best is None:
        return None
    score, line_index, words, word_keys = best
    threshold = 1.04 if len(target) <= 4 else 0.92
    if score < threshold:
        return None
    return {
        "expected_text": expected,
        "line_index": line_index,
        "line": lines[line_index],
        "words": words,
        "word_keys": word_keys,
        "bbox": bbox_for_words(words),
        "score": round(score, 4),
    }


def recover_unmatched_reference_groups(
    expected: str,
    lines: list[dict[str, Any]],
    excluded_line_indices: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Recover an unmatched exact reference as measured semantic word spans."""

    segments = semantic_segments(expected)
    if not segments:
        return []
    claimed_words: set[tuple[int, int]] = set()
    groups = []
    for segment in segments:
        group = best_contiguous_word_span(
            segment,
            lines,
            excluded_line_indices=excluded_line_indices,
            excluded_word_keys=claimed_words,
        )
        if group is None:
            return []
        claimed_words.update(group["word_keys"])
        groups.append(group)
    return groups


def labelled_numeric_visual_rows(
    expected: str, lines: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Use exact manifest wording for a labelled metric when OCR covers its rows.

    Numeric-only reconstruction is retained for sparse tables and detached
    cells. A compact colon-labelled metric, however, must preserve its visible
    label, units, and suffixes as native text instead of keeping those semantics
    in the raster background.
    """

    if not re.search(r"[：:]", expected) or len(numeric_tokens(expected)) < 2:
        return []
    rows = cluster_visual_rows(lines)
    if not rows or len(rows) > 4:
        return []
    observed = " ".join(str(row.get("text", "")) for row in rows)
    _, numeric_ratio = numeric_overlap_score(expected, observed)
    target = normalize_text(expected)
    observed_normalized = normalize_text(observed)
    similarity = difflib.SequenceMatcher(None, target, observed_normalized).ratio()
    prefix = re.split(r"[：:]", expected, maxsplit=1)[0]
    prefix_normalized = normalize_text(prefix)
    prefix_present = bool(prefix_normalized) and any(
        difflib.SequenceMatcher(
            None,
            prefix_normalized,
            normalize_text(str(row.get("text", ""))),
        ).ratio()
        >= 0.62
        or prefix_normalized in normalize_text(str(row.get("text", "")))
        for row in rows
    )
    if numeric_ratio < 0.75 or not prefix_present or similarity < 0.48:
        return []
    return rows


def foreground_color(image, rectangles, np) -> str:
    height, width = image.shape[:2]
    colors = []
    for x, y, w, h in rectangles:
        if w <= 0 or h <= 0:
            continue
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(width, x + w)
        y2 = min(height, y + h)
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        pad = max(2, int(round(h * 0.18)))
        rx1 = max(0, x1 - pad)
        ry1 = max(0, y1 - pad)
        rx2 = min(width, x2 + pad)
        ry2 = min(height, y2 + pad)
        ring = image[ry1:ry2, rx1:rx2].reshape(-1, 3)
        if ring.size == 0:
            continue
        background = np.median(ring, axis=0)
        pixels = crop.reshape(-1, 3).astype(np.float32)
        distance = np.linalg.norm(pixels - background.astype(np.float32), axis=1)
        if len(distance) < 4:
            continue
        cutoff = np.quantile(distance, 0.76)
        foreground = pixels[distance >= cutoff]
        if foreground.size:
            colors.append(np.median(foreground, axis=0))
    if not colors:
        return "FFFFFF"
    bgr = np.median(np.vstack(colors), axis=0)
    b, g, r = [int(max(0, min(255, round(value)))) for value in bgr]
    return f"{r:02X}{g:02X}{b:02X}"


def color_bucket(hex_color: str) -> str:
    hex_color = str(hex_color).lstrip("#").upper()
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    # Dark academic text colors are already measured from the accepted
    # ImageGen master. Replacing a sampled navy/teal/red with a brighter theme
    # swatch creates a large, systematic PowerPoint pixel regression even when
    # the text geometry is correct. Preserve those measurements; the legacy
    # buckets below are only useful for ambiguous bright highlight pixels.
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if luminance <= 165:
        return hex_color
    if r > 220 and g > 190 and b < 225 and r - b > 20:
        return "FBE2A2"
    if r > 150 and g >= r * 0.38 and g < 190 and b < 100:
        return "F28C28"
    if r > 175 and g < 130 and b < 130:
        return "D32F2F"
    if b > max(r, g) + 25 and b > 70:
        return "1C5AA6"
    if (
        r < 80
        and g >= 35
        and b >= 30
        and max(g, b) < 150
        and g >= r + 25
        and b >= r + 20
    ):
        return "0A6F63"
    if r < 100 and g > 130 and b > 130:
        return "00A9C6"
    if r < 100 and g > 120 and b < 150:
        return "0A8F72"
    if r > 185 and g > 185 and b > 185:
        return "FFFFFF"
    if max(r, g, b) < 165 and max(r, g, b) - min(r, g, b) < 22:
        return "081A2A"
    if r < 105 and g < 120 and b < 135:
        return "081A2A"
    return hex_color


def _rgb_from_hex(hex_color: str) -> tuple[int, int, int]:
    value = str(hex_color).lstrip("#").upper()
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )


def _color_distance(first: str, second: str) -> float:
    first_rgb = _rgb_from_hex(first)
    second_rgb = _rgb_from_hex(second)
    return sum((a - b) ** 2 for a, b in zip(first_rgb, second_rgb)) ** 0.5


def _weighted_median_color(colors: list[str], weights: list[int]) -> str:
    if not colors:
        return "FFFFFF"

    rgb_values = [_rgb_from_hex(color) for color in colors]
    safe_weights = [max(1, int(weight)) for weight in weights]

    def weighted_median(channel: int) -> int:
        ordered = sorted(
            (rgb[channel], weight)
            for rgb, weight in zip(rgb_values, safe_weights)
        )
        threshold = sum(weight for _, weight in ordered) / 2.0
        cumulative = 0
        for value, weight in ordered:
            cumulative += weight
            if cumulative >= threshold:
                return int(value)
        return int(ordered[-1][0])

    r, g, b = (weighted_median(channel) for channel in range(3))
    return f"{r:02X}{g:02X}{b:02X}"


def color_runs_for_line(
    expected: str,
    line: dict[str, Any],
    image,
    np,
    words: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]] | None, str]:
    words = line.get("words", []) if words is None else words
    if not words:
        return None, "FFFFFF"
    colors = []
    weights = []
    for word in words:
        box = word["bbox"]
        color = color_bucket(
            foreground_color(
                image,
                [(int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"]))],
                np,
            )
        )
        colors.append(color)
        weights.append(max(1, len(normalize_text(str(word.get("text", ""))))))
    representative = _weighted_median_color(colors, weights)
    near_color_distance = 28.0
    if all(
        _color_distance(color, representative) <= near_color_distance
        for color in colors
    ):
        return None, representative

    normalized_colors = [
        representative
        if _color_distance(color, representative) <= near_color_distance
        else color
        for color in colors
    ]

    total_weight = sum(weights)
    raw_segments = []
    start = 0
    cumulative = 0
    for index, (color, weight) in enumerate(zip(normalized_colors, weights)):
        cumulative += weight
        end = len(expected) if index == len(colors) - 1 else round(len(expected) * cumulative / total_weight)
        raw_segments.append((expected[start:end], color))
        start = end

    merged = []
    for text, color in raw_segments:
        if not text:
            continue
        if merged and _color_distance(merged[-1][1], color) <= near_color_distance:
            merged[-1] = (merged[-1][0] + text, color)
        else:
            merged.append((text, color))
    if len(merged) <= 1:
        return None, merged[0][1] if merged else colors[0]
    return ([{"text": text, "color": color} for text, color in merged], merged[0][1])


def add_text_mask(mask, rectangles, cv2) -> None:
    for x, y, w, h in rectangles:
        pad_x = max(2, int(round(h * 0.10)))
        pad_y = max(1, int(round(h * 0.08)))
        cv2.rectangle(
            mask,
            (max(0, x - pad_x), max(0, y - pad_y)),
            (min(mask.shape[1] - 1, x + w + pad_x), min(mask.shape[0] - 1, y + h + pad_y)),
            255,
            -1,
        )


def scaled_bbox(bbox: list[int], source_w: int, source_h: int) -> list[int]:
    x, y, w, h = bbox
    return [
        int(round(x * REF_W / source_w)),
        int(round(y * REF_H / source_h)),
        int(round(w * REF_W / source_w)),
        int(round(h * REF_H / source_h)),
    ]


def split_semantic_segments(value: str) -> list[str]:
    pieces = [piece.strip() for piece in re.split(r"\s*[·；;]\s*|\s*[：:]\s*", value) if piece.strip()]
    if len(pieces) <= 1:
        pieces = [piece.strip() for piece in re.split(r"(?<=[，,。])", value) if piece.strip()]
    return pieces


def normalize_partition_punctuation(parts: list[str]) -> list[str]:
    normalized = [part.strip() for part in parts]
    leading_punctuation = "，。；：、！？,.;:!?"
    for index in range(1, len(normalized)):
        moved = ""
        while normalized[index] and normalized[index][0] in leading_punctuation:
            moved += normalized[index][0]
            normalized[index] = normalized[index][1:].lstrip()
        if moved:
            normalized[index - 1] = normalized[index - 1].rstrip() + moved
    return normalized


def finalize_partition(parts: list[str], lines: list[dict[str, Any]]) -> list[str]:
    normalized = normalize_partition_punctuation(parts)
    for index in range(min(len(normalized) - 1, len(lines) - 1)):
        observed = str(lines[index].get("text", "")).strip()
        if observed.endswith("+") and normalized[index + 1].lstrip().startswith("+"):
            normalized[index] = normalized[index].rstrip() + " +"
            normalized[index + 1] = normalized[index + 1].lstrip()[1:].lstrip()
    return normalized


def partition_expected(value: str, lines: list[dict[str, Any]]) -> list[str]:
    if len(lines) <= 1:
        return [value]

    observed_rows = [normalize_text(str(line.get("text", ""))) for line in lines]

    def score_part(part: str, observed: str) -> float:
        normalized = normalize_text(part)
        if not normalized or not observed:
            return -1.0
        similarity = difflib.SequenceMatcher(None, normalized, observed).ratio()
        length_ratio = min(len(normalized), len(observed)) / max(len(normalized), len(observed))
        score = similarity + 0.18 * length_ratio
        if normalized in observed or observed in normalized:
            score += 0.16
        return score

    if len(value) <= 220 and len(lines) <= 4:
        @lru_cache(maxsize=None)
        def search(line_index: int, start: int) -> tuple[float, tuple[str, ...]]:
            remaining = len(lines) - line_index
            if remaining == 1:
                final = value[start:].strip()
                return score_part(final, observed_rows[line_index]), (final,)

            best_score = -1e9
            best_parts: tuple[str, ...] = ()
            max_end = len(value) - remaining + 1
            for end in range(start + 1, max_end + 1):
                part = value[start:end].strip()
                normalized_length = len(normalize_text(part))
                observed_length = max(1, len(observed_rows[line_index]))
                if normalized_length < max(1, round(observed_length * 0.45)):
                    continue
                if normalized_length > round(observed_length * 1.9) + 3:
                    continue
                tail_score, tail_parts = search(line_index + 1, end)
                total_score = score_part(part, observed_rows[line_index]) + tail_score
                if total_score > best_score:
                    best_score = total_score
                    best_parts = (part, *tail_parts)
            return best_score, best_parts

        _, aligned_parts = search(0, 0)
        if len(aligned_parts) == len(lines) and all(aligned_parts):
            return finalize_partition(list(aligned_parts), lines)

    segments = split_semantic_segments(value)
    if len(segments) >= len(lines):
        normalized_lines = [normalize_text(str(line.get("text", ""))) for line in lines]
        best_score = -1.0
        best_partition = None

        def search(start: int, line_index: int, current: list[str], score: float) -> None:
            nonlocal best_score, best_partition
            remaining_lines = len(lines) - line_index
            if remaining_lines == 1:
                if start >= len(segments):
                    return
                text = " · ".join(segments[start:])
                final_score = score + difflib.SequenceMatcher(None, normalize_text(text), normalized_lines[line_index]).ratio()
                if final_score > best_score:
                    best_score = final_score
                    best_partition = [*current, text]
                return
            max_end = len(segments) - remaining_lines + 1
            for end in range(start + 1, max_end + 1):
                text = " · ".join(segments[start:end])
                line_score = difflib.SequenceMatcher(None, normalize_text(text), normalized_lines[line_index]).ratio()
                search(end, line_index + 1, [*current, text], score + line_score)

        search(0, 0, [], 0.0)
        if best_partition:
            return finalize_partition(best_partition, lines)

    normalized_lengths = [max(1, len(normalize_text(str(line.get("text", ""))))) for line in lines]
    total = sum(normalized_lengths)
    parts = []
    start = 0
    for index, line_length in enumerate(normalized_lengths):
        if index == len(lines) - 1:
            parts.append(value[start:].strip())
            break
        target = start + round((len(value) - start) * line_length / max(1, total - sum(normalized_lengths[:index])))
        candidates = [position + 1 for position, char in enumerate(value) if char in "，,。；;· " and position + 1 > start]
        if candidates:
            target = min(candidates, key=lambda position: abs(position - target))
        parts.append(value[start:target].strip())
        start = target
    return finalize_partition(parts, lines)


def filter_composition_lines(expected: str, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(lines) <= 1:
        return lines
    target = normalize_text(expected)
    filtered = []
    for line in lines:
        observed = normalize_text(str(line.get("text", "")))
        if not observed:
            continue
        similarity = difflib.SequenceMatcher(None, target, observed).ratio()
        if len(observed) <= 4 and observed not in target and similarity < 0.50:
            continue
        filtered.append(line)
    return filtered or lines


def cluster_visual_rows(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for line in sorted(lines, key=lambda item: (item["bbox"]["y"], item["bbox"]["x"])):
        box = line["bbox"]
        center = box["y"] + box["h"] / 2
        placed = False
        for row in rows:
            row_center = median(item["bbox"]["y"] + item["bbox"]["h"] / 2 for item in row)
            row_height = max(item["bbox"]["h"] for item in row)
            if abs(center - row_center) <= max(row_height, box["h"]) * 0.72:
                row.append(line)
                placed = True
                break
        if not placed:
            rows.append([line])

    result = []
    for row in rows:
        ordered = sorted(row, key=lambda item: item["bbox"]["x"])
        result.append(
            {
                "text": "".join(str(item.get("text", "")) for item in ordered),
                "bbox": dict(zip(("x", "y", "w", "h"), line_bbox(ordered))),
                "words": [word for item in ordered for word in item.get("words", [])],
            }
        )
    return result


def dominant_single_line(expected: str, lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = normalize_text(expected)
    if not target:
        return None
    best: tuple[float, float, dict[str, Any]] | None = None
    for line in lines:
        observed = normalize_text(str(line.get("text", "")))
        if not observed:
            continue
        similarity = difflib.SequenceMatcher(None, target, observed).ratio()
        coverage = min(len(target), len(observed)) / max(len(target), len(observed))
        candidate = (similarity, coverage, line)
        if best is None or (similarity + coverage) > (best[0] + best[1]):
            best = candidate
    if best and best[0] >= 0.82 and best[1] >= 0.78:
        return best[2]
    return None


def make_text_item(
    match: dict[str, Any],
    expected: str,
    bbox: list[int],
    lines: list[dict[str, Any]],
    source_w: int,
    source_h: int,
    color: str,
    suffix: int,
    runs: list[dict[str, Any]] | None = None,
    layout_mode: str = "standard",
) -> dict[str, Any]:
    reference = match["reference"]
    x, y, w, h = scaled_bbox(bbox, source_w, source_h)
    line_heights = []
    for line in lines:
        for word in line.get("words", []):
            line_heights.append(float(word["bbox"]["h"]) * REF_H / source_h)
    glyph_height = median(line_heights) if line_heights else h
    size = max(8.0, min(72.0, glyph_height * 0.46))
    compact_layout = layout_mode == "compact"
    if layout_mode not in {"standard", "compact"}:
        raise ValueError(f"unsupported text layout mode: {layout_mode!r}")
    pad = 0 if compact_layout else max(2, int(round(glyph_height * 0.10)))
    layout_x = x if compact_layout else max(0, x - pad)
    layout_y = y if compact_layout else max(0, y - pad)
    layout_w = (
        w
        if compact_layout
        else min(REF_W - layout_x, max(w + pad * 2, int(round(w * 1.12))))
    )
    short_range = bool(
        re.fullmatch(r"[+-]?\d+(?:\.\d+)?~[+-]?\d+(?:\.\d+)?[㐀-䶿一-鿿]{0,2}", expected.strip())
    )
    if short_range and not compact_layout:
        desired_width = min(REF_W, max(layout_w, int(round(w * 1.35))))
        center_x = x + w / 2
        layout_x = max(0, int(round(center_x - desired_width / 2)))
        layout_w = min(REF_W - layout_x, desired_width)
    if layout_y < 140 and size >= 24 and not compact_layout:
        layout_w = REF_W - layout_x - 18
    if "\n" not in expected:
        width_units = 0.0
        for char in expected:
            if "\u3400" <= char <= "\u9fff":
                width_units += 2.0
            elif char.isspace():
                width_units += 0.55
            else:
                width_units += 1.1
        if width_units > 0:
            size = max(8.0, min(size, layout_w / width_units * 0.94))
    item = {
        "name": f"hf-text-{match['reference_index']:03d}-{suffix:02d}",
        "text": expected,
        "x": layout_x,
        "y": layout_y,
        "w": layout_w,
        "h": min(REF_H - layout_y, h + pad * 2),
        "source_bbox": [x, y, w, h],
        "layout_bbox": [layout_x, layout_y, layout_w, h + pad * 2],
        "font": "Microsoft YaHei",
        "size": round(size, 2),
        "color": color,
        "bold": bool(reference.get("bold", size >= 20)),
        "align": "center" if short_range else "left",
        "valign": "middle",
        "fit": "shrink",
        "margin_top": 0,
        "margin_right": 0,
        "margin_bottom": 0,
        "margin_left": 0,
        "char_spacing": 0,
        "line_spacing_multiple": 1.0,
        "editability_level": "native",
        "match_score": match["score"],
        "layout_mode": layout_mode,
    }
    if runs:
        item["runs"] = [
            {
                "text": run["text"],
                "color": run["color"],
                "bold": bool(reference.get("bold", size >= 20)),
            }
            for run in runs
        ]
    return item


def make_reviewed_text_item(
    entry: dict[str, Any],
    source_w: int,
    source_h: int,
) -> dict[str, Any]:
    source_bbox = [int(value) for value in entry["source_bbox"]]
    layout_source_bbox = [int(value) for value in entry.get("layout_bbox", source_bbox)]
    x, y, w, h = scaled_bbox(source_bbox, source_w, source_h)
    layout_x, layout_y, layout_w, layout_h = scaled_bbox(layout_source_bbox, source_w, source_h)
    inferred_size = max(8.0, min(72.0, h * 0.46))
    item = {
        "name": str(entry.get("name", "hf-reviewed-text")),
        "text": str(entry["text"]),
        "x": layout_x,
        "y": layout_y,
        "w": layout_w,
        "h": layout_h,
        "source_bbox": [x, y, w, h],
        "layout_bbox": [layout_x, layout_y, layout_w, layout_h],
        "font": str(entry.get("font", "Microsoft YaHei")),
        "size": round(float(entry.get("size", inferred_size)), 2),
        "color": str(entry.get("color", "FFFFFF")).lstrip("#").upper(),
        "bold": bool(entry.get("bold", True)),
        "align": str(entry.get("align", "left")),
        "valign": str(entry.get("valign", "middle")),
        "fit": str(entry.get("fit", "shrink")),
        "margin_top": 0,
        "margin_right": 0,
        "margin_bottom": 0,
        "margin_left": 0,
        "char_spacing": float(entry.get("char_spacing", 0)),
        "line_spacing_multiple": float(entry.get("line_spacing_multiple", 1.0)),
        "editability_level": "native-reviewed",
        "match_score": 1.0,
        "reviewed_override": True,
    }
    if entry.get("runs"):
        item["runs"] = [
            {
                "text": str(run.get("text", "")),
                "color": str(run.get("color", entry.get("color", "FFFFFF"))).lstrip("#").upper(),
                "bold": bool(run.get("bold", entry.get("bold", True))),
                "break_line": bool(run.get("break_line", False)),
                "size": round(float(run.get("size", entry.get("size", inferred_size))), 2),
                "char_spacing": float(
                    run.get("char_spacing", entry.get("char_spacing", 0))
                ),
            }
            for run in entry["runs"]
        ]
    return item


def make_reviewed_text_mask(entry: dict[str, Any], mask, cv2) -> None:
    mask_bboxes = entry.get("mask_bboxes") or [entry.get("mask_bbox", entry.get("source_bbox"))]
    mask_bboxes = [bbox for bbox in mask_bboxes if bbox]
    if not mask_bboxes:
        return
    for mask_bbox in mask_bboxes:
        x, y, w, h = [int(value) for value in mask_bbox]
        # Reviewed boxes are measured against the source raster. Keep cleanup
        # padding explicit: a large visual-object box must never become a large
        # inpaint region merely because it is used as a text anchor.
        pad_x = int(entry.get("mask_pad_x", max(1, round(h * 0.04))))
        pad_y = int(entry.get("mask_pad_y", max(1, round(h * 0.04))))
        cv2.rectangle(
            mask,
            (max(0, x - pad_x), max(0, y - pad_y)),
            (min(mask.shape[1] - 1, x + w + pad_x), min(mask.shape[0] - 1, y + h + pad_y)),
            255,
            -1,
        )


def make_reviewed_native_shape(
    entry: dict[str, Any],
    source_w: int,
    source_h: int,
) -> dict[str, Any]:
    """Scale one visually reviewed simple frame or divider into deck coordinates."""

    raw_source_bbox = entry.get("source_bbox") or entry.get("bbox")
    source_bbox = [int(round(float(value))) for value in raw_source_bbox]
    layout_source_bbox = [
        int(round(float(value)))
        for value in entry.get("layout_bbox", source_bbox)
    ]
    source_x, source_y, source_width, source_height = scaled_bbox(
        source_bbox, source_w, source_h
    )
    x, y, width, height = scaled_bbox(layout_source_bbox, source_w, source_h)
    item: dict[str, Any] = {
        "name": str(entry.get("name", "hf-reviewed-native-shape")),
        "frame_id": str(entry.get("frame_id", "")).strip(),
        "type": str(entry.get("type", "rounded_rect")),
        "x": x,
        "y": y,
        "w": width,
        "h": height,
        "source_bbox": [source_x, source_y, source_width, source_height],
        "layout_bbox": [x, y, width, height],
        "frame_bbox": [x, y, width, height],
        "line": str(entry.get("line", "2D9CC4")).lstrip("#").upper(),
        "line_width": float(entry.get("line_width", 1.0)),
        "line_width_px": float(
            entry.get("line_width_px", entry.get("cleanup_width_px", 4.0))
        ),
        "corner_radius_px": float(
            entry.get("corner_radius_px", max(4.0, min(width, height) * 0.06))
        ),
        "line_opacity": float(entry.get("line_opacity", 1.0)),
        "role": str(entry.get("role", "reviewed-native-frame")),
        "editability_level": "native-reviewed",
        "reviewed_override": True,
        "review_reason": str(entry.get("reason", "")).strip(),
    }
    item["line_color"] = item["line"]
    cleanup_mode = str(entry.get("background_cleanup", "none")).lower()
    item["background_cleanup"] = cleanup_mode
    item["requires_background_cleanup"] = bool(
        entry.get("requires_background_cleanup", cleanup_mode != "none")
    )
    compound_layer = reviewed_shape_compound_layer(entry)
    if compound_layer:
        item["compound_layer"] = compound_layer
    for key in (
        "cleanup_delegated_to",
        "z_order_within_compound",
        "allow_raster_background_frame",
        "compound_id",
        "compound_parent_frame_id",
        "outer_frame_id",
        "layer",
    ):
        if key in entry:
            item[key] = entry[key]
    for key in ("dash", "begin_arrow", "end_arrow"):
        if entry.get(key) is not None:
            item[key] = entry[key]
    if entry.get("fill") is not None:
        item["fill"] = str(entry["fill"]).lstrip("#").upper()
        item["opacity"] = float(entry.get("opacity", 1.0))
    if item["type"] in {"line", "connector"}:
        scale_x = REF_W / source_w
        scale_y = REF_H / source_h
        item.update(
            {
                "x1": int(round(float(entry["x1"]) * scale_x)),
                "y1": int(round(float(entry["y1"]) * scale_y)),
                "x2": int(round(float(entry["x2"]) * scale_x)),
                "y2": int(round(float(entry["y2"]) * scale_y)),
            }
        )
    return item


def make_reviewed_panel_frame(
    entry: dict[str, Any],
    source_w: int,
    source_h: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Translate one reviewed semantic panel into a directly cleaned native frame."""

    style = dict(entry["native_frame"])
    line_width = float(style["line_width"])
    source_entry: dict[str, Any] = {
        **style,
        "name": str(
            entry.get("name")
            or f"hf-reviewed-panel-frame-{str(entry['frame_id']).strip()}"
        ),
        "frame_id": str(entry["frame_id"]).strip(),
        "source_bbox": [int(round(float(value))) for value in entry["frame_bbox"]],
        "layout_bbox": [int(round(float(value))) for value in entry["frame_bbox"]],
        "line_width_px": float(
            style.get("line_width_px", max(1.0, line_width / 0.65))
        ),
        "cleanup_width_px": float(
            style.get(
                "cleanup_width_px",
                style.get("line_width_px", max(1.0, line_width / 0.65)),
            )
        ),
        "background_cleanup": "full-frame-directional",
        "requires_background_cleanup": True,
        "background_cleanup_scope": "full-semantic-panel",
        "role": "reviewed-semantic-frame",
        "reason": str(entry["reason"]).strip(),
        "reviewed_panel": True,
    }
    shape = make_reviewed_native_shape(source_entry, source_w, source_h)
    shape.update(
        {
            "reviewed_panel": True,
            "background_cleanup_scope": "full-semantic-panel",
            "content_bbox": list(scaled_bbox(entry["content_bbox"], source_w, source_h)),
        }
    )
    return source_entry, shape


def _rounded_rect_mask(width: int, height: int, radius: int, cv2, np) -> Any:
    """Return a filled, antialias-safe rounded-rectangle mask."""

    width = max(1, int(width))
    height = max(1, int(height))
    radius = max(0, min(int(radius), width // 2, height // 2))
    result = np.zeros((height, width), dtype=np.uint8)
    if radius <= 1:
        cv2.rectangle(result, (0, 0), (width - 1, height - 1), 255, -1)
        return result
    cv2.rectangle(result, (radius, 0), (width - radius - 1, height - 1), 255, -1)
    cv2.rectangle(result, (0, radius), (width - 1, height - radius - 1), 255, -1)
    for center in (
        (radius, radius),
        (width - radius - 1, radius),
        (radius, height - radius - 1),
        (width - radius - 1, height - radius - 1),
    ):
        cv2.circle(result, center, radius, 255, -1)
    return result


def _rounded_rect_outline_mask(
    width: int,
    height: int,
    radius: int,
    thickness: int,
    cv2,
    np,
    *,
    antialias_pad: int = 2,
) -> Any:
    """Return a rounded outline mask that covers outer AA pixels and shadows."""

    thickness = max(1, int(thickness))
    outer = _rounded_rect_mask(width, height, radius, cv2, np)
    inset = min(max(1, thickness + antialias_pad), max(1, min(width, height) // 3))
    inner_width = width - 2 * inset
    inner_height = height - 2 * inset
    if inner_width <= 1 or inner_height <= 1:
        return outer
    inner = _rounded_rect_mask(
        inner_width,
        inner_height,
        max(0, radius - inset),
        cv2,
        np,
    )
    outer[inset : inset + inner_height, inset : inset + inner_width][inner > 0] = 0
    return outer


def add_reviewed_native_shape_mask(entry: dict[str, Any], mask, cv2) -> bool:
    """Remove only a reviewed simple outline before restoring it as a native shape."""

    cleanup_mode = str(entry.get("background_cleanup", "none")).lower()
    if cleanup_mode not in {
        "outline-inpaint",
        "outline-directional",
        "full-frame-directional",
    }:
        return False
    shape_type = str(entry.get("type", "rounded_rect")).lower()
    antialias_pad = max(2, int(round(float(entry.get("antialias_pad_px", 2)))))
    thickness = max(
        1,
        int(
            round(
                float(
                    entry.get(
                        "cleanup_width_px",
                        entry.get("line_width_px", 4),
                    )
                )
            )
        ),
    )
    if shape_type in {"line", "connector"}:
        start = (
            int(round(float(entry["x1"]))),
            int(round(float(entry["y1"]))),
        )
        end = (
            int(round(float(entry["x2"]))),
            int(round(float(entry["y2"]))),
        )
        cv2.line(
            mask,
            start,
            end,
            255,
            thickness + antialias_pad * 2,
            cv2.LINE_AA,
        )
        arrow_radius = max(5, (thickness + antialias_pad * 2) * 2)
        if entry.get("begin_arrow"):
            cv2.circle(mask, start, arrow_radius, 255, -1, cv2.LINE_AA)
        if entry.get("end_arrow"):
            cv2.circle(mask, end, arrow_radius, 255, -1, cv2.LINE_AA)
        return True

    bbox = entry.get("source_bbox") or entry.get("bbox")
    x, y, width, height = [int(round(float(value))) for value in bbox]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(mask.shape[1] - 1, x + width)
    y2 = min(mask.shape[0] - 1, y + height)
    if x1 >= x2 or y1 >= y2:
        return False
    import numpy as np  # local import keeps the helper testable without global CV imports

    local_width = x2 - x1 + 1
    local_height = y2 - y1 + 1
    radius = int(
        round(
            float(
                entry.get(
                    "corner_radius_px",
                    max(4, min(local_width, local_height) * 0.06),
                )
            )
        )
    )
    if shape_type in {"oval", "ellipse"}:
        local_mask = np.zeros((local_height, local_width), dtype=np.uint8)
        center = ((local_width - 1) // 2, (local_height - 1) // 2)
        axes = (
            max(1, (local_width - 1) // 2),
            max(1, (local_height - 1) // 2),
        )
        ellipse_thickness = (
            -1
            if cleanup_mode == "full-frame-directional"
            else max(1, thickness + antialias_pad * 2)
        )
        cv2.ellipse(
            local_mask,
            center,
            axes,
            0,
            0,
            360,
            255,
            ellipse_thickness,
            cv2.LINE_AA,
        )
    elif shape_type in {"right_arrow", "left_arrow", "up_arrow", "down_arrow"}:
        shaft = 0.38
        neck = 0.62
        if shape_type in {"right_arrow", "left_arrow"}:
            points = np.asarray(
                [
                    [0, int(round(local_height * (0.5 - shaft / 2)))],
                    [int(round(local_width * neck)), int(round(local_height * (0.5 - shaft / 2)))],
                    [int(round(local_width * neck)), 0],
                    [local_width - 1, (local_height - 1) // 2],
                    [int(round(local_width * neck)), local_height - 1],
                    [int(round(local_width * neck)), int(round(local_height * (0.5 + shaft / 2)))],
                    [0, int(round(local_height * (0.5 + shaft / 2)))],
                ],
                dtype=np.int32,
            )
            if shape_type == "left_arrow":
                points[:, 0] = local_width - 1 - points[:, 0]
        else:
            points = np.asarray(
                [
                    [int(round(local_width * (0.5 - shaft / 2))), local_height - 1],
                    [int(round(local_width * (0.5 - shaft / 2))), int(round(local_height * (1 - neck)))],
                    [0, int(round(local_height * (1 - neck)))],
                    [(local_width - 1) // 2, 0],
                    [local_width - 1, int(round(local_height * (1 - neck)))],
                    [int(round(local_width * (0.5 + shaft / 2))), int(round(local_height * (1 - neck)))],
                    [int(round(local_width * (0.5 + shaft / 2))), local_height - 1],
                ],
                dtype=np.int32,
            )
            if shape_type == "down_arrow":
                points[:, 1] = local_height - 1 - points[:, 1]
        local_mask = np.zeros((local_height, local_width), dtype=np.uint8)
        if cleanup_mode == "full-frame-directional":
            # Reviewed arrow bboxes are intentionally tight and contain no
            # neighboring semantic object. Clearing the complete measured
            # footprint avoids leaving source-specific shaft/head pixels when
            # the ImageGen arrow proportions differ from PowerPoint's preset.
            cv2.rectangle(
                local_mask,
                (0, 0),
                (local_width - 1, local_height - 1),
                255,
                -1,
            )
        else:
            cv2.polylines(
                local_mask,
                [points],
                True,
                255,
                max(1, thickness + antialias_pad * 2),
                cv2.LINE_AA,
            )
    elif cleanup_mode == "full-frame-directional":
        local_mask = _rounded_rect_mask(local_width, local_height, radius, cv2, np)
    else:
        local_mask = _rounded_rect_outline_mask(
            local_width,
            local_height,
            radius,
            thickness,
            cv2,
            np,
            antialias_pad=antialias_pad,
        )
    mask[y1 : y2 + 1, x1 : x2 + 1] = cv2.bitwise_or(
        mask[y1 : y2 + 1, x1 : x2 + 1],
        local_mask,
    )
    return True


def hex_to_bgr(value: str) -> tuple[int, int, int]:
    value = str(value).lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected six-digit RGB color, got {value!r}")
    r, g, b = (int(value[offset : offset + 2], 16) for offset in (0, 2, 4))
    return b, g, r


REVIEWED_REGION_FILL_MODES = frozenset(
    {
        "solid-fill",
        "border-median-fill",
        "mask-inpaint",
        "local-median-fill",
        "edge-sample-fill",
    }
)

CLEANUP_MODE_ALIASES = {
    "solid": "solid-fill",
    "sampled-fill": "edge-sample-fill",
    "sampled_fill": "edge-sample-fill",
}


def classify_cleanup_mode(value: Any, *, allow_none: bool = False) -> tuple[str, str]:
    """Return one canonical cleanup mode and its execution route.

    The reconstruction previously maintained a narrow allow-list in the main
    loop that disagreed with ``fill_reviewed_region``. Keeping the canonical
    modes here makes reviewed text cleanup and standalone cleanup regions use
    the same contract while preserving the legacy aliases found in old ledgers.
    """

    mode = str(value if value is not None else "inpaint").strip().lower()
    mode = CLEANUP_MODE_ALIASES.get(mode, mode)
    if mode == "inpaint":
        return mode, "mask"
    if mode in REVIEWED_REGION_FILL_MODES:
        return mode, "reviewed-fill"
    if allow_none and mode == "none":
        return mode, "none"
    raise ValueError(f"unsupported reviewed cleanup mode: {mode}")


def fill_reviewed_region(image, entry: dict[str, Any], cv2, np) -> None:
    """Remove a reviewed source glyph without smearing nearby artwork."""
    if entry.get("mask_bboxes"):
        for mask_bbox in entry["mask_bboxes"]:
            child = {**entry, "mask_bbox": mask_bbox}
            child.pop("mask_bboxes", None)
            fill_reviewed_region(image, child, cv2, np)
        return
    bbox = entry.get("mask_bbox", entry.get("source_bbox"))
    if not bbox:
        return
    x, y, w, h = [int(value) for value in bbox]
    pad_x = int(entry.get("mask_pad_x", max(1, round(h * 0.04))))
    pad_y = int(entry.get("mask_pad_y", max(1, round(h * 0.04))))
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(image.shape[1], x + w + pad_x + 1)
    y2 = min(image.shape[0], y + h + pad_y + 1)
    if x1 >= x2 or y1 >= y2:
        return

    mode, route = classify_cleanup_mode(entry.get("cleanup_mode", "inpaint"))
    if route == "mask":
        return
    if mode == "solid-fill":
        color = hex_to_bgr(str(entry.get("fill_color", "F4F7F5")))
        image[y1:y2, x1:x2] = np.asarray(color, dtype=np.uint8)
        return
    if mode == "border-median-fill":
        region = image[y1:y2, x1:x2]
        ring = max(1, min(8, int(round(min(region.shape[:2]) * 0.08))))
        samples = np.concatenate(
            [
                region[:ring].reshape(-1, 3),
                region[-ring:].reshape(-1, 3),
                region[:, :ring].reshape(-1, 3),
                region[:, -ring:].reshape(-1, 3),
            ],
            axis=0,
        )
        replacement = np.median(samples, axis=0).astype(np.uint8)
        region[:] = replacement
        return
    if mode == "mask-inpaint":
        local_mask = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
        cv2.rectangle(
            local_mask,
            (0, 0),
            (local_mask.shape[1] - 1, local_mask.shape[0] - 1),
            255,
            -1,
        )
        repaired = cv2.inpaint(image[y1:y2, x1:x2], local_mask, 3, cv2.INPAINT_TELEA)
        image[y1:y2, x1:x2] = repaired
        return
    if mode == "local-median-fill":
        region = image[y1:y2, x1:x2]
        radius = max(2, int(entry.get("median_radius", 4)))
        surround = image[
            max(0, y1 - radius) : min(image.shape[0], y2 + radius),
            max(0, x1 - radius) : min(image.shape[1], x2 + radius),
        ]
        replacement = np.median(surround.reshape(-1, 3), axis=0).astype(np.uint8)
        region[:] = replacement
        return
    if mode == "edge-sample-fill":
        region = image[y1:y2, x1:x2]
        ring = max(1, int(entry.get("sample_ring", 4)))
        samples = []
        if y1 - ring >= 0:
            samples.append(image[y1 - ring : y1, x1:x2])
        if y2 + ring <= image.shape[0]:
            samples.append(image[y2 : y2 + ring, x1:x2])
        if x1 - ring >= 0:
            samples.append(image[y1:y2, x1 - ring : x1])
        if x2 + ring <= image.shape[1]:
            samples.append(image[y1:y2, x2 : x2 + ring])
        if samples:
            replacement = np.median(
                np.concatenate([sample.reshape(-1, 3) for sample in samples], axis=0), axis=0
            ).astype(np.uint8)
            region[:] = replacement
        return
    raise AssertionError(f"unrouted reviewed cleanup mode: {mode}")


def create_tiles(image, slide_dir: Path, rows: int, cols: int, cv2) -> list[dict[str, Any]]:
    slide_dir.mkdir(parents=True, exist_ok=True)
    icons = []
    for row in range(rows):
        y1 = round(row * REF_H / rows)
        y2 = round((row + 1) * REF_H / rows)
        for col in range(cols):
            x1 = round(col * REF_W / cols)
            x2 = round((col + 1) * REF_W / cols)
            tile_path = slide_dir / f"tile-r{row}-c{col}.png"
            cv2.imwrite(str(tile_path), image[y1:y2, x1:x2])
            icons.append(
                {
                    "name": f"hf-tile-r{row}-c{col}",
                    "file": str(tile_path.resolve()),
                    "x": x1,
                    "y": y1,
                    "w": x2 - x1,
                    "h": y2 - y1,
                    "source_bbox": [x1, y1, x2 - x1, y2 - y1],
                    "editability_level": "movable-image",
                    "role": "pixel-anchored-background-tile",
                }
            )
    return icons


def bgr_to_hex(color) -> str:
    b, g, r = [int(max(0, min(255, round(float(value))))) for value in color]
    return f"{r:02X}{g:02X}{b:02X}"


def edge_support(image, mask, cv2, np) -> float:
    """Measure the share of cleanup-mask pixels carrying a visible edge."""

    if image.size == 0 or mask.size == 0 or not np.count_nonzero(mask):
        return 0.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    return float(np.count_nonzero((edges > 0) & (mask > 0)) / np.count_nonzero(mask))


def reviewed_shape_cleanup_assessment(
    *,
    shape_type: str,
    cleanup_applied: bool,
    source_color_support: float,
    post_color_support: float,
    source_edge_support: float,
    post_edge_support: float,
    mean_abs_cleanup_delta: float,
    semantic_content_coverage: float,
) -> dict[str, Any]:
    """Avoid treating unrelated photograph edges as duplicate reviewed lines."""

    line_like = str(shape_type).lower() in {"line", "connector", "oval", "ellipse"}
    source_support = max(source_color_support, source_edge_support)
    if line_like:
        post_cleanup_support = post_color_support
        residual_ratio = (
            post_color_support / source_color_support
            if source_color_support > 0.01
            else 0.0
        )
        cleanup_signal = (
            source_edge_support >= 0.02 and mean_abs_cleanup_delta >= 8.0
        )
        ratio_ok = source_color_support <= 0.01 or residual_ratio <= 0.35
        support_mode = "line-color-removal-plus-reviewed-mask-change"
    else:
        post_cleanup_support = max(post_color_support, post_edge_support)
        residual_ratio = (
            post_cleanup_support / source_support if source_support > 0.01 else 0.0
        )
        cleanup_signal = source_support >= 0.02
        ratio_ok = residual_ratio <= 0.35
        support_mode = "color-or-edge-residual"

    status = (
        "pass"
        if cleanup_applied
        and cleanup_signal
        and post_cleanup_support <= 0.12
        and ratio_ok
        and semantic_content_coverage >= 0.98
        else "fail"
    )
    return {
        "status": status,
        "support_mode": support_mode,
        "source_support": source_support,
        "post_cleanup_support": post_cleanup_support,
        "residual_ratio": residual_ratio,
    }


def box_iou(first: list[int], second: list[int]) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - intersection
    return intersection / max(1, union)


def panel_matches_exclusion(panel: dict[str, Any], exclusion: dict[str, Any]) -> bool:
    """Match a reviewed false-positive panel by measured normalized bbox.

    Panel candidates are detected after the source image is normalized to the
    1920x1080 reconstruction canvas. A bbox match is deliberately explicit and
    local: reviewers may use either a high IoU threshold or a small coordinate
    tolerance, but never a broad region that could hide neighboring cards.
    """
    target = exclusion.get("bbox") or exclusion.get("source_bbox")
    if not isinstance(target, list) or len(target) != 4:
        return False
    try:
        target_box = [int(round(float(value))) for value in target]
        actual_box = [int(round(float(value))) for value in panel["bbox"]]
        min_iou = float(exclusion.get("min_iou", 0.86))
        max_delta = float(exclusion.get("max_delta", 10.0))
    except (KeyError, TypeError, ValueError):
        return False
    if min_iou < 0.0 or min_iou > 1.0 or max_delta < 0.0:
        return False
    coordinate_delta = max(abs(actual - expected) for actual, expected in zip(actual_box, target_box))
    return box_iou(actual_box, target_box) >= min_iou or coordinate_delta <= max_delta


def _box_overlap_over_smaller(first: list[int], second: list[int]) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    return intersection / max(1, min(aw * ah, bw * bh))


def suppress_reviewed_panel_candidates(
    candidates: list[dict[str, Any]],
    reviewed_frames: list[dict[str, Any]],
    *,
    min_overlap: float = 0.80,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove automatic frames already owned by an explicit reviewed panel."""

    if not reviewed_frames:
        return list(candidates), []
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_bbox = [int(round(float(value))) for value in candidate["bbox"]]
        match: tuple[dict[str, Any], str, float] | None = None
        for reviewed in reviewed_frames:
            reviewed_bbox_raw = reviewed.get("frame_bbox") or reviewed.get("source_bbox")
            if not positive_bbox(reviewed_bbox_raw):
                continue
            reviewed_bbox = [int(round(float(value))) for value in reviewed_bbox_raw]
            overlap = _box_overlap_over_smaller(candidate_bbox, reviewed_bbox)
            if bbox_within(
                [float(value) for value in reviewed_bbox],
                [float(value) for value in candidate_bbox],
                tolerance=4.0,
            ):
                reason = "contained-by-reviewed-panel"
            elif overlap >= min_overlap:
                reason = "high-overlap-with-reviewed-panel"
            else:
                continue
            if match is None or overlap > match[2]:
                match = (reviewed, reason, overlap)
        if match is None:
            kept.append(candidate)
            continue
        reviewed, reason, overlap = match
        suppressed.append(
            {
                **candidate,
                "suppressed_by_frame_id": str(reviewed.get("frame_id", "")).strip(),
                "suppression_reason": reason,
                "reviewed_frame_bbox": reviewed.get("frame_bbox")
                or reviewed.get("source_bbox"),
                "overlap_over_smaller": round(float(overlap), 6),
            }
        )
    return kept, suppressed


def _frame_boundary_support(edges, bbox: list[int], np) -> float:
    x, y, width, height = bbox
    pad = max(3, int(round(min(width, height) * 0.025)))
    corner = max(pad * 2, int(round(min(width, height) * 0.10)))
    regions = [
        edges[max(0, y - pad) : min(edges.shape[0], y + pad + 1), x + corner : x + width - corner],
        edges[max(0, y + height - pad - 1) : min(edges.shape[0], y + height + pad), x + corner : x + width - corner],
        edges[y + corner : y + height - corner, max(0, x - pad) : min(edges.shape[1], x + pad + 1)],
        edges[y + corner : y + height - corner, max(0, x + width - pad - 1) : min(edges.shape[1], x + width + pad)],
    ]
    supports = []
    for index, region in enumerate(regions):
        if region.size == 0:
            continue
        supports.append(
            float(np.mean(np.any(region > 0, axis=0 if index < 2 else 1)))
        )
    return float(np.mean(supports)) if supports else 0.0


def _sample_panel_line_color(image, bbox: list[int], fill, np) -> tuple[list[float], float]:
    """Sample the repeated stroke on the inside of a candidate frame boundary.

    A wide two-sided band allowed sparse black glyphs or the white page outside
    a light card to dominate the sampled color. Quantising the inside-boundary
    pixels makes the repeated frame stroke win over isolated content noise.
    """

    x, y, width, height = bbox
    band = max(3, min(8, int(round(min(width, height) * 0.025))))
    corner = max(band * 2, int(round(min(width, height) * 0.12)))
    left = max(0, x)
    top = max(0, y)
    right = min(image.shape[1], x + width)
    bottom = min(image.shape[0], y + height)
    horizontal_start = min(right, left + corner)
    horizontal_stop = max(horizontal_start, right - corner)
    vertical_start = min(bottom, top + corner)
    vertical_stop = max(vertical_start, bottom - corner)
    regions = [
        image[top : min(bottom, top + band), horizontal_start:horizontal_stop],
        image[max(top, bottom - band) : bottom, horizontal_start:horizontal_stop],
        image[vertical_start:vertical_stop, left : min(right, left + band)],
        image[vertical_start:vertical_stop, max(left, right - band) : right],
    ]
    pixels = [region.reshape(-1, 3) for region in regions if region.size]
    if not pixels:
        return [float(value) for value in fill], 0.0
    pixels_array = np.concatenate(pixels, axis=0).astype(np.float32)
    fill_array = np.array(fill, dtype=np.float32)
    distances = np.linalg.norm(pixels_array - fill_array, axis=1)
    threshold = max(6.0, float(np.percentile(distances, 70)))
    selected = pixels_array[distances >= threshold]
    if selected.shape[0] < 8:
        selected = pixels_array[distances >= max(4.0, float(np.percentile(distances, 55)))]
    if selected.shape[0] < 8:
        return [float(value) for value in fill], threshold

    quantization = 12.0
    buckets = np.rint(selected / quantization).astype(np.int16)
    unique, counts = np.unique(buckets, axis=0, return_counts=True)
    line = None
    for bucket_index in np.argsort(counts)[::-1]:
        bucket = unique[bucket_index]
        cluster = selected[np.all(buckets == bucket, axis=1)]
        candidate = np.median(cluster, axis=0)
        if float(np.linalg.norm(candidate - fill_array)) >= 5.0:
            line = candidate
            break
    if line is None:
        line = np.median(selected, axis=0)
    return [float(value) for value in line], threshold


def _cluster_line_width(
    cluster: list[dict[str, Any]], chosen: dict[str, Any]
) -> tuple[int, bool]:
    _, _, width, height = chosen["bbox"]
    estimates = []
    for candidate in cluster:
        if candidate is chosen:
            continue
        _, _, other_width, other_height = candidate["bbox"]
        delta_x = abs(other_width - width) / 2.0
        delta_y = abs(other_height - height) / 2.0
        if (
            1.0 <= delta_x <= 10.0
            and 1.0 <= delta_y <= 10.0
            and abs(delta_x - delta_y) <= 4.5
        ):
            estimates.append((delta_x + delta_y) / 2.0)
    if estimates:
        return max(1, int(round(min(estimates)))), True
    return max(2, min(6, int(round(min(width, height) * 0.014)))), False


def _profiled_frame_side(
    line_mask,
    bbox: list[int],
    side: str,
    np,
    *,
    search_px: int,
) -> dict[str, Any] | None:
    """Measure one long straight frame side while ignoring corner/content noise."""

    x, y, width, height = bbox
    guard = max(18, int(round(min(width, height) * 0.22)))
    if side in {"top", "bottom"}:
        start = max(0, x + guard)
        stop = min(line_mask.shape[1], x + width - guard)
        if stop - start < 24:
            return None
        profile = line_mask[:, start:stop].sum(axis=1)
        guess = y if side == "top" else y + height - 1
        span = stop - start
    else:
        start = max(0, y + guard)
        stop = min(line_mask.shape[0], y + height - guard)
        if stop - start < 24:
            return None
        profile = line_mask[start:stop, :].sum(axis=0)
        guess = x if side == "left" else x + width - 1
        span = stop - start

    lower = max(0, int(round(guess - search_px)))
    upper = min(profile.shape[0], int(round(guess + search_px + 1)))
    local = profile[lower:upper]
    if local.size == 0 or float(local.max()) < max(8.0, span * 0.24):
        return None

    peak = int(np.argmax(local)) + lower
    peak_support = float(profile[peak])
    threshold = max(2.0, peak_support * 0.34)
    run_start = peak
    run_stop = peak
    while run_start > 0 and float(profile[run_start - 1]) >= threshold:
        run_start -= 1
    while run_stop + 1 < profile.shape[0] and float(profile[run_stop + 1]) >= threshold:
        run_stop += 1
    weights = profile[run_start : run_stop + 1].astype(np.float64)
    coordinates = np.arange(run_start, run_stop + 1, dtype=np.float64)
    center = (
        float(np.average(coordinates, weights=weights))
        if float(weights.sum()) > 0
        else float(peak)
    )
    return {
        "center": center,
        "run": [int(run_start), int(run_stop)],
        "width_px": int(run_stop - run_start + 1),
        "support": float(peak_support / max(1, span)),
    }


def _longest_component(values) -> tuple[int, int] | None:
    if values.size == 0:
        return None
    components: list[tuple[int, int]] = []
    start = int(values[0])
    previous = start
    for raw_value in values[1:]:
        value = int(raw_value)
        if value > previous + 1:
            components.append((start, previous))
            start = value
        previous = value
    components.append((start, previous))
    return max(components, key=lambda item: item[1] - item[0])


def _measure_frame_corner_radius(
    line_mask,
    sides: dict[str, dict[str, Any]],
    np,
) -> int | None:
    left = int(round(sides["left"]["center"]))
    right = int(round(sides["right"]["center"]))
    top = int(round(sides["top"]["center"]))
    bottom = int(round(sides["bottom"]["center"]))
    if right <= left or bottom <= top:
        return None

    top_start, top_stop = sides["top"]["run"]
    left_start, left_stop = sides["left"]["run"]
    top_origin = max(0, left - 4)
    left_origin = max(0, top - 4)
    top_values = np.where(
        line_mask[
            max(0, top_start) : min(line_mask.shape[0], top_stop + 1),
            top_origin : min(line_mask.shape[1], right + 5),
        ].any(axis=0)
    )[0] + top_origin
    left_values = np.where(
        line_mask[
            left_origin : min(line_mask.shape[0], bottom + 5),
            max(0, left_start) : min(line_mask.shape[1], left_stop + 1),
        ].any(axis=1)
    )[0] + left_origin
    top_component = _longest_component(top_values)
    left_component = _longest_component(left_values)
    radii = []
    if top_component is not None:
        radii.extend([top_component[0] - left, right - top_component[1]])
    if left_component is not None:
        radii.extend([left_component[0] - top, bottom - left_component[1]])
    maximum = max(3, int(round(min(right - left, bottom - top) * 0.18)))
    valid = [value for value in radii if 2 <= value <= maximum]
    if not valid:
        return None
    return max(2, int(round(float(np.median(valid)))))


def _refine_panel_geometry(
    image,
    bbox: list[int],
    fill,
    line_bgr,
    line_width_hint: int,
    np,
) -> tuple[list[int], int, int, dict[str, Any]]:
    """Refine contour boxes from the center lines of the four frame sides."""

    x, y, width, height = bbox
    line = np.array(line_bgr, dtype=np.float32)
    fill_array = np.array(fill, dtype=np.float32)
    separation = float(np.linalg.norm(line - fill_array))
    tolerance = max(10.0, min(52.0, separation * 0.22 + 3.0))
    distances = np.linalg.norm(image.astype(np.float32) - line, axis=2)
    line_mask = distances <= tolerance
    bounded_line_width_hint = max(
        1,
        min(
            int(line_width_hint),
            max(8, min(14, int(round(min(width, height) * 0.045)))),
        ),
    )
    search_px = max(
        12,
        int(round(min(width, height) * 0.10)),
        bounded_line_width_hint * 4,
    )
    search_px = min(search_px, max(18, int(round(min(width, height) * 0.16))))
    sides = {
        side: _profiled_frame_side(
            line_mask,
            bbox,
            side,
            np,
            search_px=search_px,
        )
        for side in ("top", "bottom", "left", "right")
    }
    fallback_radius = max(
        bounded_line_width_hint * 2,
        int(round(min(width, height) * 0.04)),
    )
    if any(value is None for value in sides.values()):
        return bbox, int(line_width_hint), fallback_radius, {
            "status": "fallback",
            "reason": "insufficient-straight-side-support",
        }

    measured_sides = {key: value for key, value in sides.items() if value is not None}
    left = float(measured_sides["left"]["center"])
    right = float(measured_sides["right"]["center"])
    top = float(measured_sides["top"]["center"])
    bottom = float(measured_sides["bottom"]["center"])
    if right - left < 40 or bottom - top < 28:
        return bbox, int(line_width_hint), fallback_radius, {
            "status": "fallback",
            "reason": "invalid-refined-frame-extent",
        }

    refined_bbox = [
        int(round(left)),
        int(round(top)),
        max(1, int(round(right - left))),
        max(1, int(round(bottom - top))),
    ]
    measured_width = max(
        1,
        int(
            float(
                np.median(
                    [item["width_px"] for item in measured_sides.values()]
                )
            )
        ),
    )
    radius = _measure_frame_corner_radius(line_mask, measured_sides, np)
    if radius is None:
        radius = max(
            measured_width * 2,
            int(round(min(refined_bbox[2], refined_bbox[3]) * 0.04)),
        )
    return refined_bbox, measured_width, int(radius), {
        "status": "pass",
        "input_bbox": [int(value) for value in bbox],
        "refined_bbox": refined_bbox,
        "line_width_px": measured_width,
        "corner_radius_px": int(radius),
        "side_support": {
            key: round(float(value["support"]), 6)
            for key, value in measured_sides.items()
        },
    }


def panel_geometry_rejection_reason(
    bbox: list[int],
    line_width_px: int,
    corner_radius_px: int,
    fill,
    line_bgr,
    geometry_evidence: dict[str, Any],
    np,
) -> str | None:
    """Reject geometry that cannot plausibly be a presentation frame stroke."""

    _, _, width, height = bbox
    minimum_extent = max(1, min(width, height))
    maximum_line_width = max(6, min(14, int(round(minimum_extent * 0.045))))
    if int(line_width_px) > maximum_line_width:
        return (
            f"implausible-line-width:{int(line_width_px)}px>"
            f"{maximum_line_width}px-for-{minimum_extent}px-min-extent"
        )
    if int(corner_radius_px) > int(round(minimum_extent * 0.48)):
        return "implausible-corner-radius"
    separation = float(
        np.linalg.norm(
            np.asarray(line_bgr, dtype=np.float32)
            - np.asarray(fill, dtype=np.float32)
        )
    )
    if separation < 5.0:
        return "insufficient-line-fill-separation"
    if geometry_evidence.get("status") == "pass":
        supports = [
            float(value)
            for value in geometry_evidence.get("side_support", {}).values()
        ]
        if supports and sum(value >= 0.30 for value in supports) < 3:
            return "insufficient-three-side-frame-support"
    return None


def detect_flat_panels(image, cv2, np) -> list[dict[str, Any]]:
    """Detect frame geometry before considering interior content complexity.

    The former detector rejected tall or content-rich cards before measuring their
    borders. This border-first route uses rectangular contour support for frame
    existence, then records interior flatness only as a downstream routing hint.
    """

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raw_edges = cv2.Canny(gray, 40, 120)
    edges = cv2.morphologyEx(raw_edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    raw_candidates = []
    for contour in contours:
        x, y, panel_width, panel_height = cv2.boundingRect(contour)
        contour_area = abs(float(cv2.contourArea(contour)))
        box_area = float(max(1, panel_width * panel_height))
        rectangularity = contour_area / box_area
        slide_ratio = box_area / float(width * height)
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, max(0.8, 0.018 * perimeter), True)
        if panel_width < 110 or panel_height < 34 or panel_height > height * 0.56:
            continue
        if y > height * 0.90:
            continue
        if panel_width > width * 0.995 and panel_height > height * 0.45:
            continue
        if not 0.003 <= slide_ratio <= 0.24 or rectangularity < 0.82:
            continue
        if not 4 <= len(approx) <= 10:
            continue
        bbox = [int(x), int(y), int(panel_width), int(panel_height)]
        boundary_support = _frame_boundary_support(raw_edges, bbox, np)
        if boundary_support < 0.58:
            continue
        raw_candidates.append(
            {
                "bbox": bbox,
                "area_ratio": float(rectangularity),
                "slide_ratio": float(slide_ratio),
                "approx_vertices": int(len(approx)),
                "boundary_support": float(boundary_support),
            }
        )

    clusters: list[list[dict[str, Any]]] = []
    for candidate in sorted(
        raw_candidates,
        key=lambda item: item["bbox"][2] * item["bbox"][3],
        reverse=True,
    ):
        cluster = next(
            (
                group
                for group in clusters
                if any(
                    box_iou(candidate["bbox"], prior["bbox"]) >= 0.72
                    or _box_overlap_over_smaller(candidate["bbox"], prior["bbox"]) >= 0.88
                    for prior in group
                )
            ),
            None,
        )
        if cluster is None:
            clusters.append([candidate])
        else:
            cluster.append(candidate)

    candidates = []
    for cluster in clusters:
        best_rectangularity = max(item["area_ratio"] for item in cluster)
        geometry_candidates = [
            item
            for item in cluster
            if item["area_ratio"] >= best_rectangularity - 0.025
            and item["approx_vertices"] <= 6
        ]
        if not geometry_candidates:
            geometry_candidates = cluster
        chosen = max(
            geometry_candidates,
            key=lambda item: (
                item["bbox"][2] * item["bbox"][3],
                item["boundary_support"],
            ),
        )
        x, y, panel_width, panel_height = chosen["bbox"]
        line_width_px, has_parallel_outline = _cluster_line_width(cluster, chosen)
        if not has_parallel_outline:
            expansion = line_width_px
            x = max(0, x - expansion)
            y = max(0, y - expansion)
            panel_width = min(width - x, panel_width + expansion * 2)
            panel_height = min(height - y, panel_height + expansion * 2)
        provisional_bbox = [int(x), int(y), int(panel_width), int(panel_height)]
        inset = max(8, min(20, int(round(min(panel_width, panel_height) * 0.08))))
        interior = image[
            y + inset : y + panel_height - inset,
            x + inset : x + panel_width - inset,
        ]
        if interior.size == 0:
            continue
        pixels = interior.reshape(-1, 3).astype(np.float32)
        fill = np.median(pixels, axis=0)
        distances = np.linalg.norm(pixels - fill, axis=1)
        near_fill_ratio = float(np.mean(distances < 20.0))
        distance_q75 = float(np.percentile(distances, 75))
        line_bgr, line_threshold = _sample_panel_line_color(
            image, provisional_bbox, fill, np
        )
        frame_bbox, line_width_px, corner_radius_px, geometry_evidence = (
            _refine_panel_geometry(
                image,
                provisional_bbox,
                fill,
                line_bgr,
                line_width_px,
                np,
            )
        )
        x, y, panel_width, panel_height = frame_bbox
        inset = max(8, min(20, int(round(min(panel_width, panel_height) * 0.08))))
        interior = image[
            y + inset : y + panel_height - inset,
            x + inset : x + panel_width - inset,
        ]
        if interior.size == 0:
            continue
        pixels = interior.reshape(-1, 3).astype(np.float32)
        fill = np.median(pixels, axis=0)
        distances = np.linalg.norm(pixels - fill, axis=1)
        near_fill_ratio = float(np.mean(distances < 20.0))
        distance_q75 = float(np.percentile(distances, 75))
        line_bgr, line_threshold = _sample_panel_line_color(
            image, frame_bbox, fill, np
        )
        rejection_reason = panel_geometry_rejection_reason(
            frame_bbox,
            line_width_px,
            corner_radius_px,
            fill,
            line_bgr,
            geometry_evidence,
            np,
        )
        if rejection_reason is not None:
            continue
        fill_mode = (
            "native-flat"
            if near_fill_ratio >= 0.68 and distance_q75 <= 28.0
            else "native-fill-plus-bounded-content"
        )
        detection_confidence = min(
            0.995,
            0.55
            + min(0.25, chosen["area_ratio"] * 0.20)
            + min(0.18, chosen["boundary_support"] * 0.18),
        )
        candidates.append(
            {
                "bbox": frame_bbox,
                "frame_bbox": frame_bbox,
                "fill_bgr": [float(value) for value in fill],
                "fill": bgr_to_hex(fill),
                "line_bgr": line_bgr,
                "line_color": bgr_to_hex(line_bgr),
                "line_width_px": int(line_width_px),
                "corner_radius_px": int(corner_radius_px),
                "cleanup_padding_px": int(max(8, line_width_px + 5)),
                "fill_mode": fill_mode,
                "area_ratio": round(chosen["area_ratio"], 4),
                "slide_ratio": round(chosen["slide_ratio"], 5),
                "boundary_support": round(chosen["boundary_support"], 4),
                "near_fill_ratio": round(near_fill_ratio, 4),
                "distance_q75": round(distance_q75, 3),
                "line_sample_threshold": round(line_threshold, 3),
                "geometry_evidence": geometry_evidence,
                "detection_confidence": round(detection_confidence, 4),
                "candidate_cluster_size": len(cluster),
            }
        )

    ordered = sorted(candidates, key=lambda item: (item["bbox"][1], item["bbox"][0]))
    for index, candidate in enumerate(ordered, 1):
        candidate["frame_id"] = f"frame-{index:03d}"
    return ordered


def make_panel_overlay(image, panel: dict[str, Any], cv2, np) -> tuple[Any, list[int], Any]:
    """Extract non-frame panel pixels plus shadow as a bounded transparent asset."""

    x, y, width, height = panel["bbox"]
    pad = int(panel.get("cleanup_padding_px", 4))
    fill = np.array(panel["fill_bgr"], dtype=np.float32)
    # A semantic icon may straddle a card border. Detect that case before the
    # crop is fixed, otherwise the fidelity layer retains only a narrow icon
    # sliver and PowerPoint exposes a seam where the native frame passes under
    # the rest of the icon.
    panel_crop = image[y : y + height, x : x + width]
    panel_distance = np.linalg.norm(panel_crop.astype(np.float32) - fill, axis=2)
    panel_interior_probe = _rounded_rect_mask(
        width,
        height,
        int(panel["corner_radius_px"]),
        cv2,
        np,
    )
    panel_frame_probe = _rounded_rect_outline_mask(
        width,
        height,
        int(panel["corner_radius_px"]),
        int(panel["line_width_px"]),
        cv2,
        np,
        antialias_pad=2,
    )
    probe_guard_px = max(2, int(round(float(panel["line_width_px"]) * 0.75)))
    panel_frame_probe = cv2.dilate(
        panel_frame_probe,
        np.ones((probe_guard_px * 2 + 1, probe_guard_px * 2 + 1), np.uint8),
        iterations=1,
    )
    semantic_probe = (
        (panel_distance > 42.0)
        & (panel_interior_probe > 0)
        & (panel_frame_probe == 0)
    )
    edge_band_px = min(
        max(8, int(panel["line_width_px"]) * 3),
        max(1, min(width, height) // 3),
    )
    edge_probe = np.zeros((height, width), dtype=bool)
    edge_probe[:edge_band_px, :] = True
    edge_probe[-edge_band_px:, :] = True
    edge_probe[:, :edge_band_px] = True
    edge_probe[:, -edge_band_px:] = True
    semantic_crosses_frame = bool(np.any(semantic_probe & edge_probe))
    if semantic_crosses_frame:
        pad = max(
            pad,
            int(panel.get("semantic_overlap_padding_px", min(width, height) * 0.65)),
        )
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(image.shape[1], x + width + pad)
    bottom = min(image.shape[0], y + height + pad)
    crop = image[top:bottom, left:right].copy()
    distance = np.linalg.norm(crop.astype(np.float32) - fill, axis=2)
    # Preserve the exact ImageGen panel surface in a bounded layer. The native
    # fill remains editable underneath, while this fidelity layer carries only
    # the non-frame interior plus any measured outer shadow/content.
    alpha = np.clip((distance - 1.5) * (255.0 / 4.0), 0, 255).astype(np.uint8)
    frame_left = x - left
    frame_top = y - top
    frame_mask = _rounded_rect_outline_mask(
        width,
        height,
        int(panel["corner_radius_px"]),
        int(panel["line_width_px"]),
        cv2,
        np,
        antialias_pad=2,
    )
    bleed_guard_px = max(2, int(round(float(panel["line_width_px"]) * 0.75)))
    overlay_frame_mask = cv2.dilate(
        frame_mask,
        np.ones((bleed_guard_px * 2 + 1, bleed_guard_px * 2 + 1), np.uint8),
        iterations=1,
    )
    frame_alpha = alpha[
        frame_top : frame_top + height,
        frame_left : frame_left + width,
    ]
    local_distance = distance[
        frame_top : frame_top + height,
        frame_left : frame_left + width,
    ]
    panel_interior_mask = _rounded_rect_mask(
        width,
        height,
        int(panel["corner_radius_px"]),
        cv2,
        np,
    )
    semantic_seed = (
        (local_distance > 42.0)
        & (panel_interior_mask > 0)
        & (overlay_frame_mask == 0)
    ).astype(np.uint8) * 255
    semantic_bridge_px = max(
        5,
        int(panel["line_width_px"]) + bleed_guard_px + 3,
    )
    if semantic_crosses_frame:
        semantic_bridge_px = max(semantic_bridge_px, pad)
    crop_semantic_seed = np.zeros_like(alpha)
    crop_semantic_seed[
        frame_top : frame_top + height,
        frame_left : frame_left + width,
    ] = semantic_seed
    crop_semantic_bridge = cv2.dilate(
        crop_semantic_seed,
        np.ones((semantic_bridge_px * 2 + 1, semantic_bridge_px * 2 + 1), np.uint8),
        iterations=1,
    )
    crop_crossing_keep = (crop_semantic_bridge > 0) & (distance > 24.0)
    crossing_semantic_keep = crop_crossing_keep[
        frame_top : frame_top + height,
        frame_left : frame_left + width,
    ]
    # Do not carry the flat panel surface in the fidelity overlay. The native
    # PowerPoint shape below owns the editable fill; this PNG should contain
    # only bounded semantic content/shadow that the native frame cannot
    # reproduce. Keeping the whole interior opaque would visually hide the
    # native fill and effectively fuse the panel surface back into a raster.
    frame_alpha[overlay_frame_mask > 0] = 0
    frame_alpha[crossing_semantic_keep] = 255
    local_panel_mask = np.zeros_like(alpha)
    local_panel_mask[
        frame_top : frame_top + height,
        frame_left : frame_left + width,
    ] = panel_interior_mask
    # Keep only low-contrast shadow outside the frame. Connected arrows and
    # connector stubs are already present in the clean background and would be
    # duplicated if the bounded panel layer carried them again.
    alpha[
        (local_panel_mask == 0)
        & (distance > 42.0)
        & (~crop_crossing_keep)
    ] = 0
    if str(panel.get("fill_mode", "")).strip() == "native-flat":
        alpha[(local_panel_mask == 0) & (~crop_crossing_keep)] = 0
    else:
        shadow_keep_px = max(4, min(12, int(panel.get("cleanup_padding_px", 4))))
        shadow_context = cv2.dilate(
            local_panel_mask,
            np.ones((shadow_keep_px * 2 + 1, shadow_keep_px * 2 + 1), np.uint8),
            iterations=1,
        ) > 0
        alpha[
            (local_panel_mask == 0)
            & (~crop_crossing_keep)
            & (~shadow_context)
        ] = 0
    alpha[crop_crossing_keep] = 255
    alpha[alpha < 18] = 0
    # The editable native shape owns the flat panel surface. Retain only
    # semantic pixels selected above; otherwise even subtle ImageGen texture
    # differences make the entire panel an opaque raster and defeat the layer
    # separation contract.
    alpha[(local_panel_mask > 0) & (~crop_crossing_keep)] = 0
    # PowerPoint may interpolate RGB values from fully transparent pixels.
    # Neutralizing those pixels prevents a removed dark border from returning
    # as a faint halo after the PNG is scaled on the slide.
    crop[alpha == 0] = np.clip(fill, 0, 255).astype(np.uint8)
    nonzero_rows, nonzero_columns = np.nonzero(alpha)
    if nonzero_rows.size and nonzero_columns.size:
        trim_pad = 2
        trim_left = max(0, int(nonzero_columns.min()) - trim_pad)
        trim_top = max(0, int(nonzero_rows.min()) - trim_pad)
        trim_right = min(alpha.shape[1], int(nonzero_columns.max()) + trim_pad + 1)
        trim_bottom = min(alpha.shape[0], int(nonzero_rows.max()) + trim_pad + 1)
        crop = crop[trim_top:trim_bottom, trim_left:trim_right]
        alpha = alpha[trim_top:trim_bottom, trim_left:trim_right]
        left += trim_left
        top += trim_top
        right = left + (trim_right - trim_left)
        bottom = top + (trim_bottom - trim_top)
    overlay = np.dstack((crop, alpha))
    return overlay, [left, top, right - left, bottom - top], frame_mask


def build_reviewed_panel_content_asset(
    entry: dict[str, Any],
    shape: dict[str, Any],
    master_image,
    master_path: Path,
    slide_dir: Path,
    panel_index: int,
    cv2,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a bounded panel-content asset with auditable source provenance."""

    panel_dir = slide_dir / "reviewed-panels"
    source_dir = panel_dir / "sources"
    panel_dir.mkdir(parents=True, exist_ok=True)
    raw_source = entry.get("content_source_file")
    if raw_source is None:
        source_pixels = master_image
        source_file = master_path.resolve()
        source_bbox = [int(round(float(value))) for value in entry["content_bbox"]]
        source_kind = "verified-imagegen-master-crop"
        source_evidence_file = source_file
        resolution_strategy = "current-run-imagegen-master"
    else:
        resolved_source = Path(str(entry["_resolved_content_source_file"])).resolve()
        source_pixels = cv2.imread(str(resolved_source), cv2.IMREAD_UNCHANGED)
        if source_pixels is None:
            raise ValueError(
                f"{entry['frame_id']}: content_source_file is not a decodable image: "
                f"{resolved_source}"
            )
        source_height, source_width = source_pixels.shape[:2]
        source_bbox = [
            int(round(float(value)))
            for value in entry.get(
                "content_source_bbox", [0, 0, source_width, source_height]
            )
        ]
        source_kind = "external-source-crop"
        source_dir.mkdir(parents=True, exist_ok=True)
        suffix = resolved_source.suffix or ".bin"
        source_evidence_file = (
            source_dir / f"reviewed-panel-{panel_index:03d}-source{suffix.lower()}"
        ).resolve()
        shutil.copy2(resolved_source, source_evidence_file)
        source_file = resolved_source
        resolution_strategy = (
            "absolute-input-path-copied-into-run"
            if Path(str(raw_source)).expanduser().is_absolute()
            else "relative-to-override-json-directory-copied-into-run"
        )

    source_height, source_width = source_pixels.shape[:2]
    if not positive_bbox(source_bbox) or not bbox_within_canvas(
        [float(value) for value in source_bbox], source_width, source_height
    ):
        raise ValueError(
            f"{entry['frame_id']}: content source bbox is outside the source image "
            f"{source_width}x{source_height}"
        )
    source_x, source_y, source_w, source_h = source_bbox
    crop = source_pixels[
        source_y : source_y + source_h,
        source_x : source_x + source_w,
    ].copy()
    if crop.size == 0:
        raise ValueError(f"{entry['frame_id']}: reviewed panel content crop is empty")

    asset_path = (panel_dir / f"reviewed-panel-{panel_index:03d}-content.png").resolve()
    if not cv2.imwrite(str(asset_path), crop):
        raise OSError(f"failed to write reviewed panel asset: {asset_path}")

    target_bbox = [int(round(float(value))) for value in shape["content_bbox"]]
    frame_bbox = [int(round(float(value))) for value in shape["frame_bbox"]]
    provenance = {
        "kind": source_kind,
        "source_file": str(source_evidence_file),
        "source_sha256": sha256_file(source_evidence_file),
        "source_dimensions": [int(source_width), int(source_height)],
        "source_bbox": source_bbox,
        "resolution_strategy": resolution_strategy,
    }
    if raw_source is not None:
        provenance.update(
            {
                "input_source_file": str(raw_source),
                "resolved_input_source_file": str(source_file),
                "override_file": str(entry.get("_override_file", "")),
            }
        )
    else:
        provenance.update(
            {
                "slide_id": str(entry.get("slide_id", "")),
                "verified_imagegen_master": True,
            }
        )
    asset = {
        "name": f"hf-reviewed-panel-content-{panel_index:03d}",
        "file": str(asset_path),
        "x": target_bbox[0],
        "y": target_bbox[1],
        "w": target_bbox[2],
        "h": target_bbox[3],
        "source_bbox": target_bbox,
        "layout_bbox": target_bbox,
        "content_bbox": target_bbox,
        "content_source_bbox": source_bbox,
        "frame_bbox": frame_bbox,
        "frame_id": str(entry["frame_id"]).strip(),
        "cleanup_mask": shape.get("cleanup_mask", ""),
        "mask_bbox": shape.get("mask_bbox", frame_bbox),
        "cleanup_evidence": shape.get("cleanup_evidence", {}),
        "background_cleanup_scope": "full-semantic-panel",
        "source_provenance": provenance,
        "asset_sha256": sha256_file(asset_path),
        "editability_level": "movable-image",
        "role": "movable-panel-content",
        "reviewed_panel": True,
        "review_reason": str(entry["reason"]).strip(),
    }
    report = {
        "frame_id": asset["frame_id"],
        "frame_bbox": frame_bbox,
        "content_bbox": target_bbox,
        "content_asset": str(asset_path),
        "content_asset_sha256": asset["asset_sha256"],
        "source_provenance": provenance,
        "reason": asset["review_reason"],
        "route": "reviewed-native-frame-plus-bounded-content",
    }
    return asset, report


def contour_path(contour, cv2, epsilon_ratio: float = 0.012) -> str | None:
    perimeter = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, max(0.8, epsilon_ratio * perimeter), True)
    points = approx.reshape(-1, 2)
    if len(points) < 3:
        return None
    commands = [f"M {int(points[0][0])} {int(points[0][1])}"]
    commands.extend(f"L {int(point[0])} {int(point[1])}" for point in points[1:])
    commands.append("Z")
    return " ".join(commands)


def extract_gap_native_objects(
    image, panels: list[dict[str, Any]], cv2, np
) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    height, width = image.shape[:2]
    panel_rows: list[list[dict[str, Any]]] = []
    for panel in sorted(panels, key=lambda item: (item["bbox"][1], item["bbox"][0])):
        x, y, w, h = panel["bbox"]
        if y < height * 0.48 or h < 70 or w > width * 0.35:
            continue
        placed = False
        for row in panel_rows:
            _, row_y, _, row_h = row[0]["bbox"]
            if abs(y - row_y) <= max(h, row_h) * 0.18 and abs(h - row_h) <= max(h, row_h) * 0.24:
                row.append(panel)
                placed = True
                break
        if not placed:
            panel_rows.append([panel])

    base = image.copy()
    removal_mask = np.zeros((height, width), dtype=np.uint8)
    native_shapes = []
    native_texts = []
    reports = []
    object_index = 0

    for row in panel_rows:
        ordered = sorted(row, key=lambda item: item["bbox"][0])
        if len(ordered) < 2:
            continue
        for left, right in zip(ordered, ordered[1:]):
            lx, ly, lw, lh = left["bbox"]
            rx, ry, rw, rh = right["bbox"]
            gap = rx - (lx + lw)
            if gap < 18 or gap > 240:
                continue
            x1 = max(0, lx + lw - 18)
            x2 = min(width, rx + 18)
            y1 = max(0, min(ly, ry) - 18)
            y2 = min(height, max(ly + lh, ry + rh) + 18)
            crop = image[y1:y2, x1:x2]
            b, g, r = cv2.split(crop)
            red_mask = ((r > 112) & (r > g * 1.75) & (r > b * 1.55)).astype(np.uint8) * 255
            red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            red_contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            red_candidates = []
            for contour in red_contours:
                area = abs(float(cv2.contourArea(contour)))
                cx, cy, cw, ch = cv2.boundingRect(contour)
                if 650 <= area <= 3200 and 0.72 <= cw / max(1, ch) <= 1.28 and 28 <= cw <= 72:
                    red_candidates.append((area, cx, cy, cw, ch))
            if not red_candidates:
                continue
            _, cx, cy, cw, ch = max(red_candidates)

            light_mask = (
                (b > 88)
                & (g > 72)
                & (r > 44)
                & ((b.astype(np.int16) - r.astype(np.int16)) > 22)
            ).astype(np.uint8) * 255
            light_mask[: min(light_mask.shape[0], cy + ch - 4), :] = 0
            light_mask[min(light_mask.shape[0], cy + ch + 58) :, :] = 0
            light_mask = cv2.morphologyEx(light_mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            light_mask = cv2.morphologyEx(light_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            light_contours, _ = cv2.findContours(light_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            arrow_candidates = []
            for contour in light_contours:
                area = abs(float(cv2.contourArea(contour)))
                ax, ay, aw, ah = cv2.boundingRect(contour)
                if area >= 220 and aw / max(1, ah) >= 1.45 and aw >= 38:
                    arrow_candidates.append((area, ax, ay, aw, ah))
            if not arrow_candidates:
                continue
            _, ax, ay, aw, ah = max(arrow_candidates)

            native_shapes.append(
                {
                    "name": f"hf-native-question-circle-{object_index:03d}",
                    "type": "oval",
                    "x": x1 + cx,
                    "y": y1 + cy,
                    "w": cw,
                    "h": ch,
                    "source_bbox": [x1 + cx, y1 + cy, cw, ch],
                    "fill": "A0241C",
                    "opacity": 1.0,
                    "line": "F2F0F1",
                    "line_width": 1.4,
                    "editability_level": "native",
                    "role": "native-gap-question-circle",
                }
            )
            native_shapes.append(
                {
                    "name": f"hf-native-arrow-{object_index:03d}",
                    "type": "right_arrow",
                    "x": x1 + ax,
                    "y": y1 + ay,
                    "w": aw,
                    "h": ah,
                    "source_bbox": [x1 + ax, y1 + ay, aw, ah],
                    "fill": "7FA4BA",
                    "opacity": 1.0,
                    "line": "7FA4BA",
                    "line_width": 0.2,
                    "editability_level": "native",
                    "role": "native-gap-arrow",
                }
            )
            question_size = max(14.0, min(24.0, ch * 0.42))
            native_texts.append(
                {
                    "name": f"hf-native-question-mark-{object_index:03d}",
                    "text": "?",
                    "x": x1 + cx,
                    "y": y1 + cy - 1,
                    "w": cw,
                    "h": ch + 2,
                    "source_bbox": [x1 + cx, y1 + cy, cw, ch],
                    "layout_bbox": [x1 + cx, y1 + cy - 1, cw, ch + 2],
                    "font": "Arial",
                    "size": round(question_size, 2),
                    "color": "FFFFFF",
                    "bold": True,
                    "align": "center",
                    "valign": "middle",
                    "fit": "shrink",
                    "margin_top": 0,
                    "margin_right": 0,
                    "margin_bottom": 0,
                    "margin_left": 0,
                    "editability_level": "native",
                }
            )
            reports.append(
                {
                    "bbox": [x1, y1, x2 - x1, y2 - y1],
                    "circle_bbox": [x1 + cx, y1 + cy, cw, ch],
                    "arrow_bbox": [x1 + ax, y1 + ay, aw, ah],
                    "method": "native oval + native question text + native right arrow",
                }
            )
            combined_mask = cv2.bitwise_or(red_mask, light_mask)
            white_mask = ((b > 175) & (g > 175) & (r > 175)).astype(np.uint8) * 255
            white_focus = np.zeros_like(white_mask)
            white_focus[max(0, cy - 4) : min(white_mask.shape[0], cy + ch + 4), max(0, cx - 4) : min(white_mask.shape[1], cx + cw + 4)] = 255
            combined_mask = cv2.bitwise_or(combined_mask, cv2.bitwise_and(white_mask, white_focus))
            expanded = cv2.dilate(combined_mask, np.ones((3, 3), np.uint8), iterations=1)
            removal_mask[y1:y2, x1:x2] = cv2.bitwise_or(removal_mask[y1:y2, x1:x2], expanded)
            object_index += 1

    if np.count_nonzero(removal_mask):
        base = cv2.inpaint(base, removal_mask, 3, cv2.INPAINT_TELEA)
    return base, native_shapes, native_texts, reports


def _directional_repair_patch(
    region,
    cleanup_mask,
    np,
    *,
    direction: str = "both",
) -> Any:
    """Fill a removed object from clean opposite edges instead of Telea synthesis.

    Horizontal arrows/lines must sample above and below their footprint; using
    their left/right endpoints would pull adjacent panel or node colors across
    the cleared gap. Vertical objects use the symmetric left/right route.
    """

    if direction not in {"both", "horizontal", "vertical", "solid"}:
        raise ValueError(f"unsupported directional repair axis: {direction}")

    repaired = region.astype(np.float32).copy()
    mask_bool = cleanup_mask > 0
    horizontal = np.zeros_like(repaired)
    vertical = np.zeros_like(repaired)
    horizontal_valid = np.zeros(mask_bool.shape, dtype=bool)
    vertical_valid = np.zeros(mask_bool.shape, dtype=bool)

    for row in range(region.shape[0]):
        columns = np.flatnonzero(mask_bool[row])
        if columns.size == 0:
            continue
        start = int(columns[0])
        end = int(columns[-1])
        left_pixels = region[row, max(0, start - 4) : start]
        right_pixels = region[row, end + 1 : min(region.shape[1], end + 5)]
        if left_pixels.size:
            left_color = np.median(left_pixels.reshape(-1, 3), axis=0)
        elif right_pixels.size:
            left_color = np.median(right_pixels.reshape(-1, 3), axis=0)
        else:
            continue
        if right_pixels.size:
            right_color = np.median(right_pixels.reshape(-1, 3), axis=0)
        else:
            right_color = left_color
        sample_count = end - start + 1
        weights = np.linspace(0.0, 1.0, sample_count, dtype=np.float32)[:, None]
        horizontal[row, start : end + 1] = (
            left_color[None, :] * (1.0 - weights) + right_color[None, :] * weights
        )
        horizontal_valid[row, start : end + 1] = True

    for column in range(region.shape[1]):
        rows = np.flatnonzero(mask_bool[:, column])
        if rows.size == 0:
            continue
        start = int(rows[0])
        end = int(rows[-1])
        top_pixels = region[max(0, start - 4) : start, column]
        bottom_pixels = region[end + 1 : min(region.shape[0], end + 5), column]
        if top_pixels.size:
            top_color = np.median(top_pixels.reshape(-1, 3), axis=0)
        elif bottom_pixels.size:
            top_color = np.median(bottom_pixels.reshape(-1, 3), axis=0)
        else:
            continue
        if bottom_pixels.size:
            bottom_color = np.median(bottom_pixels.reshape(-1, 3), axis=0)
        else:
            bottom_color = top_color
        sample_count = end - start + 1
        weights = np.linspace(0.0, 1.0, sample_count, dtype=np.float32)[:, None]
        vertical[start : end + 1, column] = (
            top_color[None, :] * (1.0 - weights) + bottom_color[None, :] * weights
        )
        vertical_valid[start : end + 1, column] = True

    outside = region[~mask_bool]
    fallback = (
        np.median(outside.reshape(-1, 3), axis=0)
        if outside.size
        else np.median(region.reshape(-1, 3), axis=0)
    )
    if direction == "solid":
        repaired[mask_bool] = fallback
    elif direction == "both":
        both = mask_bool & horizontal_valid & vertical_valid
        only_horizontal = mask_bool & horizontal_valid & ~vertical_valid
        only_vertical = mask_bool & vertical_valid & ~horizontal_valid
        unresolved = mask_bool & ~horizontal_valid & ~vertical_valid
        repaired[both] = (horizontal[both] + vertical[both]) / 2.0
        repaired[only_horizontal] = horizontal[only_horizontal]
        repaired[only_vertical] = vertical[only_vertical]
        repaired[unresolved] = fallback
    else:
        preferred, preferred_valid = (
            (horizontal, horizontal_valid)
            if direction == "horizontal"
            else (vertical, vertical_valid)
        )
        alternate, alternate_valid = (
            (vertical, vertical_valid)
            if direction == "horizontal"
            else (horizontal, horizontal_valid)
        )
        preferred_pixels = mask_bool & preferred_valid
        alternate_pixels = mask_bool & ~preferred_valid & alternate_valid
        unresolved = mask_bool & ~preferred_valid & ~alternate_valid
        repaired[preferred_pixels] = preferred[preferred_pixels]
        repaired[alternate_pixels] = alternate[alternate_pixels]
        repaired[unresolved] = fallback
    return np.clip(np.rint(repaired), 0, 255).astype(np.uint8)


def reviewed_shape_repair_direction(
    shape: dict[str, Any], cleanup_mode: str
) -> str:
    """Choose the cleanup sampling axis perpendicular to a simple shape.

    Full-frame cleanup of a wide bar must not sample its left/right endpoints:
    those pixels commonly contain the chart axis, bar shadow, or a neighbouring
    segment and can create a bar-shaped gradient in the supposedly clean
    background.  The symmetric rule applies to tall bars.  Callers may record
    an explicit reviewed direction when the measured page requires it.
    """

    allowed = {"both", "horizontal", "vertical", "solid"}
    explicit = str(shape.get("repair_direction", "")).strip().lower()
    if explicit:
        if explicit not in allowed:
            raise ValueError(f"unsupported reviewed repair direction: {explicit}")
        return explicit

    shape_type = str(shape.get("type", "")).lower()
    if shape_type in {"right_arrow", "left_arrow"}:
        return "vertical"
    if shape_type in {"up_arrow", "down_arrow"}:
        return "horizontal"
    if shape_type in {"oval", "ellipse"} and cleanup_mode == "full-frame-directional":
        return "solid"
    if shape_type in {"line", "connector"}:
        delta_x = abs(float(shape.get("x2", 0)) - float(shape.get("x1", 0)))
        delta_y = abs(float(shape.get("y2", 0)) - float(shape.get("y1", 0)))
        if delta_x >= delta_y * 1.5:
            return "vertical"
        if delta_y >= delta_x * 1.5:
            return "horizontal"
        return "both"
    if shape_type in {"rect", "rounded_rect"} and cleanup_mode == "full-frame-directional":
        bbox = shape.get("source_bbox") or shape.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            width = float(bbox[2])
            height = float(bbox[3])
            if width >= height * 1.5:
                return "vertical"
            if height >= width * 1.5:
                return "horizontal"
    return "both"


def _polynomial_surface_terms(x_values, y_values, degree: int, np):
    """Return total-degree polynomial terms in a stable order."""

    return np.column_stack(
        [
            (x_values ** x_power) * (y_values ** y_power)
            for total_degree in range(degree + 1)
            for x_power in range(total_degree + 1)
            for y_power in [total_degree - x_power]
        ]
    )


def _fit_robust_polynomial_background_surface(
    image,
    valid_mask,
    config: dict[str, Any],
    cv2,
    np,
) -> tuple[Any, dict[str, Any]]:
    """Fit an opt-in low-frequency RGB background surface.

    The fit excludes reviewed semantic bboxes and iteratively down-weights
    remaining foreground outliers. Coordinates are normalized to [-1, 1] so
    the least-squares system is stable across slide sizes.
    """

    height, width = image.shape[:2]
    degree = int(config.get("degree", 3))
    sample_stride = int(config.get("sample_stride_px", 8))
    robust_iterations = int(config.get("robust_iterations", 3))
    prefilter_sigma = float(config.get("prefilter_sigma_px", 8.0))
    huber_sigma = float(config.get("huber_sigma", 2.5))
    minimum_scale = float(config.get("minimum_scale_0_255", 1.0))

    if not 1 <= degree <= 5:
        raise ValueError("global polynomial surface degree must be between 1 and 5")
    if not 2 <= sample_stride <= 64:
        raise ValueError("global polynomial sample_stride_px must be between 2 and 64")
    if not 1 <= robust_iterations <= 8:
        raise ValueError("global polynomial robust_iterations must be between 1 and 8")
    if not 0.0 <= prefilter_sigma <= 80.0:
        raise ValueError("global polynomial prefilter_sigma_px must be between 0 and 80")
    if not 1.0 <= huber_sigma <= 8.0:
        raise ValueError("global polynomial huber_sigma must be between 1 and 8")
    if not 0.1 <= minimum_scale <= 32.0:
        raise ValueError("global polynomial minimum_scale_0_255 must be between 0.1 and 32")

    fit_image = image
    if prefilter_sigma:
        fit_image = cv2.GaussianBlur(
            image,
            (0, 0),
            sigmaX=prefilter_sigma,
            sigmaY=prefilter_sigma,
        )

    rows = np.arange(0, height, sample_stride, dtype=np.int32)
    columns = np.arange(0, width, sample_stride, dtype=np.int32)
    grid_x, grid_y = np.meshgrid(columns, rows)
    sample_valid = valid_mask[grid_y, grid_x] > 0
    sample_x = grid_x[sample_valid].astype(np.float64)
    sample_y = grid_y[sample_valid].astype(np.float64)
    samples = fit_image[grid_y[sample_valid], grid_x[sample_valid]].astype(np.float64)

    normalized_x = sample_x / max(width - 1, 1) * 2.0 - 1.0
    normalized_y = sample_y / max(height - 1, 1) * 2.0 - 1.0
    design = _polynomial_surface_terms(normalized_x, normalized_y, degree, np)
    term_count = int(design.shape[1])
    if len(samples) < term_count * 4:
        raise ValueError(
            "global polynomial surface has insufficient clean samples: "
            f"{len(samples)} for {term_count} terms"
        )

    weights = np.ones(len(samples), dtype=np.float64)
    coefficients = None
    robust_scale = minimum_scale
    for _ in range(robust_iterations):
        square_root_weights = np.sqrt(weights)[:, None]
        coefficients, *_ = np.linalg.lstsq(
            design * square_root_weights,
            samples * square_root_weights,
            rcond=None,
        )
        residual_rgb = samples - design @ coefficients
        residual = np.sqrt(np.mean(residual_rgb * residual_rgb, axis=1))
        residual_median = float(np.median(residual))
        median_absolute_deviation = float(
            np.median(np.abs(residual - residual_median))
        )
        robust_scale = max(minimum_scale, 1.4826 * median_absolute_deviation)
        cutoff = max(minimum_scale, huber_sigma * robust_scale)
        weights = np.minimum(1.0, cutoff / np.maximum(residual, 1e-6))

    if coefficients is None:
        raise AssertionError("global polynomial fit did not produce coefficients")

    surface = np.empty((height, width, 3), dtype=np.float32)
    x_axis = np.arange(width, dtype=np.float64) / max(width - 1, 1) * 2.0 - 1.0
    chunk_rows = int(config.get("prediction_chunk_rows", 64))
    if not 8 <= chunk_rows <= 512:
        raise ValueError("global polynomial prediction_chunk_rows must be between 8 and 512")
    for start in range(0, height, chunk_rows):
        end = min(height, start + chunk_rows)
        y_axis = (
            np.arange(start, end, dtype=np.float64) / max(height - 1, 1) * 2.0
            - 1.0
        )
        prediction_x, prediction_y = np.meshgrid(x_axis, y_axis)
        prediction_design = _polynomial_surface_terms(
            prediction_x.reshape(-1),
            prediction_y.reshape(-1),
            degree,
            np,
        )
        surface[start:end] = (prediction_design @ coefficients).reshape(
            end - start,
            width,
            3,
        )

    surface = np.clip(np.rint(surface), 0, 255).astype(np.uint8)
    fitted_samples = design @ coefficients
    sample_mae = float(np.mean(np.abs(samples - fitted_samples)))
    return surface, {
        "status": "pass",
        "method": "robust-total-degree-polynomial",
        "degree": degree,
        "term_count": term_count,
        "sample_stride_px": sample_stride,
        "sample_count": int(len(samples)),
        "robust_iterations": robust_iterations,
        "prefilter_sigma_px": prefilter_sigma,
        "huber_sigma": huber_sigma,
        "robust_scale_0_255": round(float(robust_scale), 6),
        "sample_mean_abs_error_0_255": round(sample_mae, 6),
    }


def counterfactual_surface_repair(
    image,
    shapes: list[dict[str, Any]],
    texts: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    config: dict[str, Any],
    cv2,
    np,
) -> tuple[Any, Any, dict[str, Any]]:
    """Remove object-shaped cleanup footprints from a completed clean background.

    The ordinary cleanup pass removes source colors and edges.  This second,
    explicitly reviewed pass answers the stronger counterfactual question:
    what remains when the routed foreground object is moved away?  It masks the
    complete semantic bboxes and estimates the low-frequency background from
    surrounding unmasked pixels with normalized Gaussian convolution.
    """

    height, width = image.shape[:2]
    semantic_mask = np.zeros((height, width), dtype=np.uint8)
    routed: list[dict[str, Any]] = []

    def add_item(item: dict[str, Any], kind: str) -> None:
        role = str(item.get("role", "")).lower()
        if kind == "asset" and role in {
            "pixel-anchored-background-tile",
            "background-tile",
            "background_tile",
        }:
            return
        candidates = (
            ("frame_bbox", "source_bbox", "layout_bbox")
            if kind == "shape"
            else ("source_bbox", "layout_bbox")
            if kind == "text"
            else ("content_bbox", "source_bbox", "layout_bbox", "frame_bbox")
        )
        bbox = next((item.get(key) for key in candidates if positive_bbox(item.get(key))), None)
        if bbox is None:
            return
        x, y, item_width, item_height = [int(round(float(value))) for value in bbox]
        left = max(0, min(width, x))
        top = max(0, min(height, y))
        right = max(left, min(width, x + item_width))
        bottom = max(top, min(height, y + item_height))
        if right <= left or bottom <= top:
            return
        cv2.rectangle(
            semantic_mask,
            (left, top),
            (right - 1, bottom - 1),
            255,
            -1,
        )
        routed.append(
            {
                "kind": kind,
                "name": str(item.get("name", "")),
                "bbox": [left, top, right - left, bottom - top],
            }
        )

    for shape in shapes:
        add_item(shape, "shape")
    for text_item in texts:
        add_item(text_item, "text")
    for asset in assets:
        add_item(asset, "asset")

    if not routed or not np.count_nonzero(semantic_mask):
        raise ValueError("counterfactual background cleanup found no routed semantic objects")

    padding = int(round(float(config.get("padding_px", 8))))
    sigma = float(config.get("sigma_px", 34.0))
    feather = float(config.get("feather_px", 3.0))
    expanded = semantic_mask
    if padding:
        kernel_size = padding * 2 + 1
        expanded = cv2.dilate(
            semantic_mask,
            np.ones((kernel_size, kernel_size), np.uint8),
            iterations=1,
        )

    valid = (expanded == 0).astype(np.float32)
    denominator = cv2.GaussianBlur(valid, (0, 0), sigmaX=sigma, sigmaY=sigma)
    numerator = cv2.GaussianBlur(
        image.astype(np.float32) * valid[:, :, None],
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
    )
    safe_denominator = np.maximum(denominator[:, :, None], 1e-4)
    surface = numerator / safe_denominator
    fallback_pixels = image[expanded == 0]
    fallback = (
        np.median(fallback_pixels.reshape(-1, 3), axis=0)
        if fallback_pixels.size
        else np.median(image.reshape(-1, 3), axis=0)
    )
    unsupported = denominator < 1e-3
    surface[unsupported] = fallback
    alpha = (expanded > 0).astype(np.float32)
    if feather:
        alpha = cv2.GaussianBlur(alpha, (0, 0), sigmaX=feather, sigmaY=feather)
    repaired = (
        image.astype(np.float32) * (1.0 - alpha[:, :, None])
        + surface * alpha[:, :, None]
    )
    repaired = np.clip(np.rint(repaired), 0, 255).astype(np.uint8)
    effective_mask = expanded
    global_surface_report = None
    global_surface_config = config.get("global_surface")
    if isinstance(global_surface_config, dict) and bool(
        global_surface_config.get("enabled", True)
    ):
        fit_valid = (expanded == 0).astype(np.uint8) * 255
        fit_exclusion_padding = int(
            round(float(global_surface_config.get("fit_exclusion_padding_px", 0)))
        )
        if fit_exclusion_padding:
            fit_valid = cv2.erode(
                fit_valid,
                np.ones(
                    (fit_exclusion_padding * 2 + 1, fit_exclusion_padding * 2 + 1),
                    np.uint8,
                ),
                iterations=1,
            )
        global_surface, global_surface_report = (
            _fit_robust_polynomial_background_surface(
                repaired,
                fit_valid,
                global_surface_config,
                cv2,
                np,
            )
        )
        apply_scope = str(
            global_surface_config.get("apply_scope", "semantic-mask")
        ).strip().lower()
        if apply_scope not in {"semantic-mask", "full-slide"}:
            raise ValueError(
                "global polynomial apply_scope must be semantic-mask or full-slide"
            )
        strength = float(global_surface_config.get("strength", 1.0))
        if not 0.0 <= strength <= 1.0:
            raise ValueError("global polynomial strength must be between 0 and 1")
        if apply_scope == "full-slide":
            apply_alpha = np.ones((height, width), dtype=np.float32)
            effective_mask = np.full((height, width), 255, dtype=np.uint8)
        else:
            apply_alpha = (expanded > 0).astype(np.float32)
            effective_mask = expanded
        transition = float(global_surface_config.get("transition_px", 0.0))
        if not 0.0 <= transition <= 64.0:
            raise ValueError("global polynomial transition_px must be between 0 and 64")
        if transition:
            apply_alpha = cv2.GaussianBlur(
                apply_alpha,
                (0, 0),
                sigmaX=transition,
                sigmaY=transition,
            )
        apply_alpha = np.clip(apply_alpha * strength, 0.0, 1.0)
        before_global = repaired
        repaired = (
            before_global.astype(np.float32) * (1.0 - apply_alpha[:, :, None])
            + global_surface.astype(np.float32) * apply_alpha[:, :, None]
        )
        repaired = np.clip(np.rint(repaired), 0, 255).astype(np.uint8)
        global_delta = np.abs(
            repaired.astype(np.int16) - before_global.astype(np.int16)
        )
        global_surface_report.update(
            {
                "apply_scope": apply_scope,
                "strength": strength,
                "transition_px": transition,
                "fit_exclusion_padding_px": fit_exclusion_padding,
                "fit_valid_area_ratio": round(float(np.mean(fit_valid > 0)), 6),
                "apply_area_ratio": round(float(np.mean(apply_alpha > 0)), 6),
                "mean_abs_delta_0_255": round(float(np.mean(global_delta)), 6),
            }
        )

    total_changed = np.abs(repaired.astype(np.int16) - image.astype(np.int16))
    report = {
        "status": "pass",
        "method": (
            "normalized-gaussian-plus-robust-polynomial-surface"
            if global_surface_report is not None
            else "normalized-gaussian-counterfactual-surface"
        ),
        "reason": str(config.get("reason", "")).strip(),
        "object_count": len(routed),
        "objects": routed,
        "padding_px": padding,
        "sigma_px": sigma,
        "feather_px": feather,
        "semantic_mask_area_ratio": round(float(np.mean(expanded > 0)), 6),
        "mask_area_ratio": round(float(np.mean(effective_mask > 0)), 6),
        "mean_abs_delta_0_255": round(float(np.mean(total_changed)), 6),
    }
    if global_surface_report is not None:
        report["global_surface"] = global_surface_report
    return repaired, effective_mask, report


def _frame_color_support(region, frame_mask, line_bgr, np) -> float:
    selected = region[frame_mask > 0].astype(np.float32)
    if selected.size == 0:
        return 0.0
    distances = np.linalg.norm(selected - np.array(line_bgr, dtype=np.float32), axis=1)
    return float(np.mean(distances <= 48.0))


def panel_native_shape_type(panel: dict[str, Any]) -> str:
    """Use aspect ratio only for layout, never to erase a measured card border."""

    return "rect" if int(round(float(panel.get("corner_radius_px", 0)))) <= 1 else "rounded_rect"


def extract_native_panels(
    image, slide_dir: Path, cv2, np, panels: list[dict[str, Any]] | None = None
) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    panels = detect_flat_panels(image, cv2, np) if panels is None else panels
    if not panels:
        return image, [], [], []

    base = image.copy()
    shapes = []
    overlays = []
    reports = []
    panel_dir = slide_dir / "panels"
    panel_dir.mkdir(parents=True, exist_ok=True)

    for index, panel in enumerate(panels):
        x, y, width, height = panel["bbox"]
        frame_id = str(panel.get("frame_id") or f"frame-{index + 1:03d}")
        overlay, content_bbox, frame_mask = make_panel_overlay(image, panel, cv2, np)
        overlay_left, overlay_top, overlay_width, overlay_height = content_bbox
        cleanup_pad = int(panel.get("cleanup_padding_px", 4))
        left = max(0, x - cleanup_pad)
        top = max(0, y - cleanup_pad)
        right = min(image.shape[1], x + width + cleanup_pad)
        bottom = min(image.shape[0], y + height + cleanup_pad)
        cleanup_bbox = [left, top, right - left, bottom - top]
        crop_width = cleanup_bbox[2]
        crop_height = cleanup_bbox[3]
        overlay_path = panel_dir / f"panel-{index:03d}-content.png"
        cleanup_mask_path = panel_dir / f"panel-{index:03d}-cleanup-mask.png"

        local_cleanup_mask = np.zeros((crop_height, crop_width), dtype=np.uint8)
        frame_left = x - left
        frame_top = y - top
        full_frame_mask = _rounded_rect_mask(
            width,
            height,
            int(panel["corner_radius_px"]),
            cv2,
            np,
        )
        local_cleanup_mask[
            frame_top : frame_top + height,
            frame_left : frame_left + width,
        ] = full_frame_mask
        shadow_expansion = max(4, int(panel.get("cleanup_padding_px", 8)) - 2)
        local_cleanup_mask = cv2.dilate(
            local_cleanup_mask,
            np.ones((shadow_expansion * 2 + 1, shadow_expansion * 2 + 1), np.uint8),
            iterations=1,
        )

        local_frame_mask = np.zeros_like(local_cleanup_mask)
        local_frame_mask[
            frame_top : frame_top + height,
            frame_left : frame_left + width,
        ] = frame_mask
        source_region = image[top : top + crop_height, left : left + crop_width]
        outside_pixels = source_region[local_cleanup_mask == 0]
        outside_spread = float("inf")
        if outside_pixels.size:
            outside_pixels_float = outside_pixels.reshape(-1, 3).astype(np.float32)
            outside_median = np.median(outside_pixels_float, axis=0)
            outside_spread = float(
                np.percentile(
                    np.linalg.norm(outside_pixels_float - outside_median, axis=1),
                    75,
                )
            )
        repair_direction = "solid" if outside_spread <= 18.0 else "both"
        repaired_region = _directional_repair_patch(
            source_region,
            local_cleanup_mask,
            np,
            direction=repair_direction,
        )
        source_color_support = _frame_color_support(
            source_region,
            local_frame_mask,
            panel["line_bgr"],
            np,
        )
        post_color_support = _frame_color_support(
            repaired_region,
            local_frame_mask,
            panel["line_bgr"],
            np,
        )
        source_edge_support = edge_support(source_region, local_frame_mask, cv2, np)
        post_edge_support = edge_support(repaired_region, local_frame_mask, cv2, np)
        source_support = max(source_color_support, source_edge_support)
        post_cleanup_support = max(post_color_support, post_edge_support)
        residual_ratio = (
            post_cleanup_support / source_support if source_support > 0.01 else 0.0
        )
        cleanup_status = (
            "pass"
            if source_support >= 0.12 and residual_ratio <= 0.25
            else "fail"
        )
        cv2.imwrite(str(cleanup_mask_path), local_cleanup_mask)
        cleanup_evidence = {
            "status": cleanup_status,
            "method": "rounded-frame-directional-edge-interpolation",
            "repair_direction": repair_direction,
            "outside_color_spread_q75": round(outside_spread, 6),
            "cleanup_mask": str(cleanup_mask_path.resolve()),
            "mask_bbox": cleanup_bbox,
            "cleanup_width_px": int(panel["line_width_px"]),
            "line_color": panel["line_color"],
            "corner_radius_px": int(panel["corner_radius_px"]),
            "source_color_support": round(source_color_support, 6),
            "post_cleanup_color_support": round(post_color_support, 6),
            "source_edge_support": round(source_edge_support, 6),
            "post_cleanup_edge_support": round(post_edge_support, 6),
            "source_support": round(source_support, 6),
            "post_cleanup_support": round(post_cleanup_support, 6),
            "source_frame_support": round(source_support, 6),
            "post_cleanup_frame_support": round(post_cleanup_support, 6),
            "residual_ratio": round(residual_ratio, 6),
        }
        if cleanup_status != "pass":
            reports.append(
                {
                    **panel,
                    "frame_id": frame_id,
                    "route": "unresolved-raster-background",
                    "cleanup_evidence": cleanup_evidence,
                    "reason": "frame cleanup evidence did not meet the Gold threshold",
                }
            )
            continue

        base[top : top + crop_height, left : left + crop_width] = repaired_region
        has_bounded_content = bool(np.count_nonzero(overlay[:, :, 3]))
        if has_bounded_content:
            cv2.imwrite(str(overlay_path), overlay)
            overlays.append(
                {
                    "name": f"hf-panel-content-{index:03d}",
                    "file": str(overlay_path.resolve()),
                    "x": overlay_left,
                    "y": overlay_top,
                    "w": overlay_width,
                    "h": overlay_height,
                    "source_bbox": content_bbox,
                    "content_bbox": content_bbox,
                    "frame_bbox": [x, y, width, height],
                    "frame_id": frame_id,
                    "cleanup_mask": str(cleanup_mask_path.resolve()),
                    "mask_bbox": cleanup_bbox,
                    "line_color": panel["line_color"],
                    "line_width_px": int(panel["line_width_px"]),
                    "corner_radius_px": int(panel["corner_radius_px"]),
                    "cleanup_evidence": cleanup_evidence,
                    "editability_level": "movable-image",
                    "role": "movable-panel-content",
                }
            )

        line_width_pt = max(0.2, float(panel["line_width_px"]) * 0.65)
        corner_adjustment = round(
            min(
                0.45,
                max(
                    0.0,
                    2.0
                    * float(panel["corner_radius_px"])
                    / max(1, min(width, height)),
                ),
            ),
            4,
        )
        shape = {
            "name": f"hf-native-panel-{index:03d}__ca_{corner_adjustment:.4f}",
            "type": panel_native_shape_type(panel),
            "x": x,
            "y": y,
            "w": width,
            "h": height,
            "source_bbox": [x, y, width, height],
            "frame_bbox": [x, y, width, height],
            "frame_id": frame_id,
            "fill": panel["fill"],
            "opacity": 1.0,
            "line": panel["line_color"],
            "line_color": panel["line_color"],
            "line_width": round(line_width_pt, 3),
            "line_width_px": int(panel["line_width_px"]),
            "corner_radius_px": int(panel["corner_radius_px"]),
            "corner_adjustment": corner_adjustment,
            "cleanup_mask": str(cleanup_mask_path.resolve()),
            "mask_bbox": cleanup_bbox,
            "cleanup_evidence": cleanup_evidence,
            "detection_confidence": panel["detection_confidence"],
            "fill_mode": panel["fill_mode"],
            "editability_level": "native",
            "role": "measured-semantic-frame",
        }
        shapes.append(shape)
        reports.append(
            {
                **panel,
                "frame_id": frame_id,
                "route": (
                    "native-frame-plus-bounded-content"
                    if has_bounded_content
                    else "native-frame-only"
                ),
                "overlay": str(overlay_path.resolve()) if has_bounded_content else None,
                "shape": shape["name"],
                "cleanup_evidence": cleanup_evidence,
            }
        )
    return base, shapes, overlays, reports


def parse_slide_ids(value: str, available: list[str]) -> list[str]:
    if not value.strip():
        return available
    requested = [item.strip().upper() for item in value.split(",") if item.strip()]
    missing = [item for item in requested if item not in available]
    if missing:
        raise ValueError(f"Unknown slide IDs: {', '.join(missing)}")
    return requested


def build_source_notes(slide: dict[str, Any], source_metadata: dict[str, Any]) -> str:
    """Build portable per-slide source notes when an outline has no authored notes."""
    existing = str(slide.get("notes", "")).strip()
    if existing:
        return existing

    document = str(source_metadata.get("document", "")).strip()
    document_name = Path(document).name if document else "source document"
    source_sha256 = str(source_metadata.get("source_sha256", "")).strip()
    speaker_refs = [
        str(value).strip()
        for value in slide.get("speaker_note_source_refs", [])
        if str(value).strip()
    ]
    evidence_refs = [
        str(value).strip()
        for value in slide.get("evidence_refs", [])
        if str(value).strip()
    ]
    media_refs = []
    for item in slide.get("recommended_media", []):
        if not isinstance(item, dict):
            continue
        value = item.get("media_id") or item.get("source_ref") or item.get("path")
        if value and str(value).strip() and str(value).strip() not in media_refs:
            media_refs.append(str(value).strip())

    lines = ["[Sources]"]
    source_line = f"- {document_name}"
    if source_sha256:
        source_line += f" | SHA256 {source_sha256}"
    lines.append(source_line)
    if speaker_refs:
        lines.append(f"- Thesis refs: {', '.join(speaker_refs)}")
    if evidence_refs:
        lines.append(f"- Evidence refs: {', '.join(evidence_refs)}")
    if media_refs:
        lines.append(f"- Media refs: {', '.join(media_refs)}")
    claim_boundary = str(slide.get("claim_boundary", "")).strip()
    if claim_boundary:
        lines.append(f"- Claim boundary: {claim_boundary}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--reference-deck", default="editable/deck-editable.json")
    parser.add_argument("--prompt-manifest", default="image-prompts.json")
    parser.add_argument("--ocr-dir", default="high_fidelity/ocr")
    parser.add_argument("--reviewed-overrides", default="high_fidelity/reviewed-overrides.json")
    parser.add_argument(
        "--semantic-overrides",
        default="high_fidelity/semantic-completion-overrides.json",
        help="Source-semantic text promoted from bounded raster regions into native PowerPoint text.",
    )
    parser.add_argument("--out-dir", default="high_fidelity/round1")
    parser.add_argument(
        "--deck-title",
        default="",
        help="Optional title for deck-high-fidelity.json; otherwise infer it from the current manifests.",
    )
    parser.add_argument("--slides", default="", help="Comma-separated slide IDs; default all.")
    parser.add_argument(
        "--background-mode",
        choices=("single", "tiled"),
        default="single",
        help="Use one continuous full-slide background by default; tiled is a legacy compatibility mode.",
    )
    parser.add_argument("--tile-rows", type=int, default=3)
    parser.add_argument("--tile-cols", type=int, default=4)
    parser.add_argument("--tools-path", default=".ppt_tools")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_deck = load_json((run_dir / args.reference_deck).resolve())
    prompt_manifest = load_json((run_dir / args.prompt_manifest).resolve())
    evidence_registry_path = run_dir / str(
        reference_deck.get("evidence_registry_ref", "evidence-registry.json")
    )
    evidence_registry = (
        load_json(evidence_registry_path.resolve()) if evidence_registry_path.exists() else {}
    )
    source_metadata = evidence_registry.get("source", {}) if isinstance(evidence_registry, dict) else {}
    out_dir = (run_dir / args.out_dir).resolve()
    ocr_dir = (run_dir / args.ocr_dir).resolve()
    reviewed_overrides_path = resolve_optional_json_path(
        run_dir,
        args.reviewed_overrides,
        option_name="--reviewed-overrides",
        explicitly_requested=option_was_explicit(sys.argv[1:], "--reviewed-overrides"),
    )
    reviewed_overrides = (
        load_override_payload(reviewed_overrides_path)
        if reviewed_overrides_path.exists()
        else {}
    )
    semantic_overrides_path = resolve_optional_json_path(
        run_dir,
        args.semantic_overrides,
        option_name="--semantic-overrides",
        explicitly_requested=option_was_explicit(sys.argv[1:], "--semantic-overrides"),
    )
    semantic_overrides = (
        load_override_payload(semantic_overrides_path)
        if semantic_overrides_path.exists()
        else {}
    )
    overrides = merge_override_payloads(reviewed_overrides, semantic_overrides)
    validate_override_payloads(overrides)
    tools_path = Path(args.tools_path).expanduser().resolve()
    cv2, np = load_cv(tools_path)

    reference_by_id = {slide["slide_id"]: slide for slide in reference_deck["slides"]}
    prompt_by_id = {slide["slide_id"]: slide for slide in prompt_manifest.get("slides", [])}
    available = list(reference_by_id)
    selected = parse_slide_ids(args.slides, available)
    deck_slides = []
    qa_slides = []

    for slide_id in selected:
        source_path = run_dir / "assets" / "slides" / f"{slide_id}.png"
        ocr_path = ocr_dir / f"{slide_id}.json"
        source = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
        if source is None:
            raise FileNotFoundError(source_path)
        ocr = load_json(ocr_path)
        source_h, source_w = source.shape[:2]
        slide_asset_dir = out_dir / "assets" / slide_id
        slide_asset_dir.mkdir(parents=True, exist_ok=True)
        references = [
            {"text": repair_mojibake(str(text)), "bold": True}
            for text in prompt_by_id.get(slide_id, {}).get("exact_text", [])
            if str(text).strip()
        ]
        slide_override = overrides.get("slides", {}).get(slide_id, {})
        override_entries = slide_override.get("texts", [])
        preserve_automatic_reference_indices = {
            int(value) for value in slide_override.get("preserve_automatic_reference_indices", [])
        }
        replace_reference_indices = {
            int(entry["reference_index"])
            for entry in override_entries
            if entry.get("replace_match", False)
            and not entry.get("partial_reference_override", False)
            and int(entry["reference_index"]) not in preserve_automatic_reference_indices
        } if not slide_override.get("preserve_automatic_match", False) else set()
        ocr_lines = sorted(
            ocr.get("lines", []),
            key=lambda line: (round(float(line["bbox"]["y"]) / 12), float(line["bbox"]["x"])),
        )
        matches, unmatched = match_reference_texts(references, ocr_lines)

        mask = np.zeros((source_h, source_w), dtype=np.uint8)
        reviewed_cleanup_entries: list[dict[str, Any]] = []
        text_items = []
        match_report = []
        numeric_fallback_reference_indices, numeric_fallback_report = numeric_table_fallback(
            references,
            unmatched,
            ocr_lines,
            source,
            np,
            cv2,
            source_w,
            source_h,
            mask,
            text_items,
            slide_id,
            replace_reference_indices,
        )
        used_match_line_indices = {
            int(line_index)
            for match in matches
            for line_index in match.get("line_indices", [])
        }
        semantic_recovery_reference_indices: set[int] = set()
        semantic_recovery_report = []
        for unmatched_entry in unmatched:
            reference_index = int(unmatched_entry["reference_index"])
            if (
                reference_index in numeric_fallback_reference_indices
                or reference_index in replace_reference_indices
            ):
                continue
            expected = str(references[reference_index]["text"])
            recovered_groups = recover_unmatched_reference_groups(
                expected,
                ocr_lines,
                excluded_line_indices=used_match_line_indices,
            )
            if not recovered_groups:
                continue
            recovery_match = {
                "reference_index": reference_index,
                "reference": references[reference_index],
                "expected_text": expected,
                "score": min(float(group["score"]) for group in recovered_groups),
            }
            recovered_items = []
            for suffix, group in enumerate(recovered_groups):
                words = group["words"]
                expected_part = str(group["expected_text"])
                row = {
                    "text": "".join(str(word.get("text", "")) for word in words),
                    "words": words,
                }
                runs, color = color_runs_for_line(expected_part, row, source, np, words)
                add_text_mask(mask, rectangles_for_words(words), cv2)
                text_items.append(
                    make_text_item(
                        recovery_match,
                        expected_part,
                        bbox_for_words(words),
                        [row],
                        source_w,
                        source_h,
                        color,
                        suffix,
                        runs,
                        "compact",
                    )
                )
                recovered_items.append(
                    {
                        "text": expected_part,
                        "source_bbox": group["bbox"],
                        "score": group["score"],
                    }
                )
            semantic_recovery_reference_indices.add(reference_index)
            semantic_recovery_report.append(
                {
                    "reference_index": reference_index,
                    "expected_text": expected,
                    "method": "contiguous-ocr-word-span-exact-text-recovery",
                    "items": recovered_items,
                }
            )
        cleanup_region_report = []
        for cleanup_index, entry in enumerate(slide_override.get("cleanup_regions", [])):
            cleanup_entry = {
                **entry,
                "source_bbox": entry.get("source_bbox")
                or entry.get("mask_bbox")
                or entry.get("bbox"),
            }
            try:
                cleanup_mode, cleanup_route = classify_cleanup_mode(
                    cleanup_entry.get("cleanup_mode", "inpaint")
                )
            except ValueError as exc:
                raise ValueError(
                    f"unsupported cleanup mode for {slide_id}/cleanup-{cleanup_index:03d}: "
                    f"{cleanup_entry.get('cleanup_mode', 'inpaint')!r}"
                ) from exc
            cleanup_entry["cleanup_mode"] = cleanup_mode
            if cleanup_route == "mask":
                make_reviewed_text_mask(cleanup_entry, mask, cv2)
            elif cleanup_route == "reviewed-fill":
                reviewed_cleanup_entries.append(cleanup_entry)
            else:
                raise AssertionError(f"unrouted cleanup action: {cleanup_route}")
            cleanup_region_report.append(
                {
                    "name": str(cleanup_entry.get("name", f"cleanup-{cleanup_index:03d}")),
                    "mask_bboxes": cleanup_entry.get("mask_bboxes")
                    or [cleanup_entry["source_bbox"]],
                    "cleanup_mode": cleanup_mode,
                    "reason": str(cleanup_entry.get("reason", "")).strip(),
                }
            )
        reviewed_native_shapes = []
        reviewed_native_shape_actions = []
        reviewed_native_shape_report = []
        reviewed_panel_actions = []
        reviewed_panel_report = []
        for shape_index, entry in enumerate(slide_override.get("native_shapes", [])):
            frame_id = str(entry.get("frame_id") or f"frame-{slide_id}-reviewed-{shape_index + 1:03d}")
            reviewed_entry = {**entry, "frame_id": frame_id}
            shape = make_reviewed_native_shape(reviewed_entry, source_w, source_h)
            shape_mask = np.zeros((source_h, source_w), dtype=np.uint8)
            cleanup_applied = add_reviewed_native_shape_mask(reviewed_entry, shape_mask, cv2)
            cleanup_mode = str(reviewed_entry.get("background_cleanup", "none")).lower()
            if cleanup_applied and cleanup_mode == "outline-inpaint":
                mask[:] = cv2.bitwise_or(mask, shape_mask)
            reviewed_native_shapes.append(shape)
            reviewed_native_shape_actions.append(
                {
                    "entry": reviewed_entry,
                    "shape": shape,
                    "mask": shape_mask,
                    "cleanup_applied": cleanup_applied,
                    "cleanup_mode": cleanup_mode,
                }
            )
            reviewed_shape_record = {
                "name": shape["name"],
                "frame_id": frame_id,
                "type": shape["type"],
                "source_bbox": [
                    int(round(float(value)))
                    for value in (entry.get("source_bbox") or entry.get("bbox"))
                ],
                "layout_bbox": shape["layout_bbox"],
                "background_cleanup": cleanup_mode,
                "cleanup_applied": cleanup_applied,
                "reason": str(entry.get("reason", "")).strip(),
            }
            for key in (
                "cleanup_delegated_to",
                "compound_layer",
                "z_order_within_compound",
            ):
                if key in shape:
                    reviewed_shape_record[key] = shape[key]
            reviewed_native_shape_report.append(reviewed_shape_record)
        for panel_index, entry in enumerate(slide_override.get("reviewed_panels", []), 1):
            for label in ("frame_bbox", "content_bbox"):
                candidate = [float(value) for value in entry[label]]
                if not bbox_within_canvas(candidate, source_w, source_h):
                    raise ValueError(
                        f"{slide_id}/{entry['frame_id']}: {label} is outside the "
                        f"source image {source_w}x{source_h}"
                    )
            reviewed_entry = {**entry, "slide_id": slide_id}
            frame_entry, shape = make_reviewed_panel_frame(
                reviewed_entry, source_w, source_h
            )
            shape_mask = np.zeros((source_h, source_w), dtype=np.uint8)
            if not add_reviewed_native_shape_mask(frame_entry, shape_mask, cv2):
                raise ValueError(
                    f"{slide_id}/{entry['frame_id']}: reviewed panel cleanup mask is empty"
                )
            content_x, content_y, content_w, content_h = [
                int(round(float(value))) for value in entry["content_bbox"]
            ]
            cv2.rectangle(
                shape_mask,
                (content_x, content_y),
                (content_x + content_w - 1, content_y + content_h - 1),
                255,
                -1,
            )
            cleanup_guard_px = max(
                2,
                int(round(float(frame_entry.get("cleanup_width_px", 2.0)))) + 2,
            )
            shape_mask = cv2.dilate(
                shape_mask,
                np.ones(
                    (cleanup_guard_px * 2 + 1, cleanup_guard_px * 2 + 1),
                    np.uint8,
                ),
                iterations=1,
            )
            evidence_mask = np.zeros((source_h, source_w), dtype=np.uint8)
            add_reviewed_native_shape_mask(
                {**frame_entry, "background_cleanup": "outline-directional"},
                evidence_mask,
                cv2,
            )
            action = {
                "entry": frame_entry,
                "panel_entry": reviewed_entry,
                "shape": shape,
                "mask": shape_mask,
                "evidence_mask": evidence_mask,
                "cleanup_applied": True,
                "cleanup_mode": "full-frame-directional",
                "reviewed_panel": True,
                "panel_index": panel_index,
            }
            reviewed_native_shapes.append(shape)
            reviewed_native_shape_actions.append(action)
            reviewed_panel_actions.append(action)
            reviewed_shape_record = {
                "name": shape["name"],
                "frame_id": shape["frame_id"],
                "type": shape["type"],
                "source_bbox": shape["source_bbox"],
                "layout_bbox": shape["layout_bbox"],
                "content_bbox": shape["content_bbox"],
                "background_cleanup": shape["background_cleanup"],
                "background_cleanup_scope": "full-semantic-panel",
                "cleanup_applied": True,
                "reviewed_panel": True,
                "reason": str(entry["reason"]).strip(),
            }
            reviewed_native_shape_report.append(reviewed_shape_record)
            action["report_index"] = len(reviewed_native_shape_report) - 1
        for match in matches:
            if int(match["reference_index"]) in replace_reference_indices:
                continue
            text_start = len(text_items)
            has_multi_number_reference = len(numeric_tokens(match["expected_text"])) >= 2
            composition_lines = (
                match["lines"] if has_multi_number_reference else filter_composition_lines(match["expected_text"], match["lines"])
            )
            dominant_line = dominant_single_line(match["expected_text"], composition_lines)
            if dominant_line is not None:
                composition_lines = [dominant_line]
            visual_rows = cluster_visual_rows(composition_lines)
            semantic_parts = semantic_segments(match["expected_text"])
            semantic_source_lines = (
                ocr_lines
                if len(semantic_parts) >= 6 or "→" in match["expected_text"]
                else composition_lines
            )
            matched_semantic_exact_groups = (
                recover_unmatched_reference_groups(
                    match["expected_text"],
                    ocr_lines,
                    excluded_line_indices=(
                        used_match_line_indices - {int(value) for value in match.get("line_indices", [])}
                    ),
                )
                if len(semantic_parts) >= 3
                else []
            )
            semantic_groups = (
                []
                if dominant_line is not None
                else semantic_word_groups(match["expected_text"], composition_lines)
            )
            if (
                dominant_line is None
                and not semantic_groups
                and semantic_source_lines is ocr_lines
            ):
                semantic_groups = semantic_word_groups(match["expected_text"], semantic_source_lines)
            if dominant_line is None and not semantic_groups and semantic_source_lines is ocr_lines:
                semantic_groups = semantic_line_groups(match["expected_text"], semantic_source_lines)
            numeric_segments = (
                numeric_ocr_segments(composition_lines, match["expected_text"])
                if has_multi_number_reference
                else []
            )
            labelled_numeric_rows = (
                [dominant_line]
                if has_multi_number_reference and dominant_line is not None
                else labelled_numeric_visual_rows(match["expected_text"], composition_lines)
                if has_multi_number_reference
                else []
            )
            if labelled_numeric_rows:
                expected_parts = partition_expected(match["expected_text"], labelled_numeric_rows)
                row_colors = []
                for suffix, (row, expected_part) in enumerate(zip(labelled_numeric_rows, expected_parts)):
                    words = aligned_words(expected_part, row) or list(row.get("words", []))
                    rectangles = cleanup_rectangles_for_visual_row(row, words)
                    runs, color = color_runs_for_line(expected_part, row, source, np, words)
                    row_colors.append(color)
                    add_text_mask(mask, rectangles, cv2)
                    text_items.append(
                        make_text_item(
                            match,
                            expected_part,
                            bbox_for_words(words),
                            [row],
                            source_w,
                            source_h,
                            color,
                            suffix,
                            runs,
                            "compact",
                        )
                    )
                color = row_colors[0] if row_colors else "FFFFFF"
            elif matched_semantic_exact_groups:
                group_colors = []
                for suffix, group in enumerate(matched_semantic_exact_groups):
                    words = group["words"]
                    expected_part = str(group["expected_text"])
                    row = {
                        "text": "".join(str(word.get("text", "")) for word in words),
                        "words": words,
                    }
                    runs, color = color_runs_for_line(expected_part, row, source, np, words)
                    group_colors.append(color)
                    add_text_mask(mask, rectangles_for_words(words), cv2)
                    text_items.append(
                        make_text_item(
                            match,
                            expected_part,
                            bbox_for_words(words),
                            [row],
                            source_w,
                            source_h,
                            color,
                            suffix,
                            runs,
                            "compact",
                        )
                    )
                color = group_colors[0] if group_colors else "FFFFFF"
            elif numeric_segments:
                segment_colors = []
                for suffix, segment in enumerate(numeric_segments):
                    words = segment["words"]
                    display_text = segment["text"]
                    rectangles = [tuple(int(value) for value in segment["mask_bbox"])]
                    row = {"text": "".join(str(word.get("text", "")) for word in words), "words": words}
                    runs, color = color_runs_for_line(display_text, row, source, np, words)
                    segment_colors.append(color)
                    add_text_mask(mask, rectangles, cv2)
                    text_items.append(
                        make_text_item(
                            match,
                            display_text,
                            bbox_for_words(words),
                            [row],
                            source_w,
                            source_h,
                            color,
                            suffix,
                            runs,
                            "compact",
                        )
                    )
                color = segment_colors[0] if segment_colors else "FFFFFF"
            elif semantic_groups:
                group_colors = []
                for suffix, (expected_part, words) in enumerate(semantic_groups):
                    rectangles = rectangles_for_words(words)
                    row = {"text": "".join(str(word.get("text", "")) for word in words), "words": words}
                    runs, color = color_runs_for_line(expected_part, row, source, np, words)
                    group_colors.append(color)
                    add_text_mask(mask, rectangles, cv2)
                    text_items.append(
                        make_text_item(
                            match,
                            expected_part,
                            bbox_for_words(words),
                            [row],
                            source_w,
                            source_h,
                            color,
                            suffix,
                            runs,
                            "compact",
                        )
                    )
                color = group_colors[0] if group_colors else "FFFFFF"
            elif dominant_line is None and len(visual_rows) == 1 and len(match["lines"]) > 1:
                expected_parts = partition_expected(match["expected_text"], match["lines"])
                for suffix, (line, expected_part) in enumerate(zip(match["lines"], expected_parts)):
                    observed = normalize_text(str(line.get("text", "")))
                    if re.fullmatch(r"[0-9]+", observed):
                        expected_part = re.sub(r"^(PSNR|SSIM)\s*", "", expected_part, flags=re.IGNORECASE)
                    words = aligned_words(expected_part, line)
                    rectangles = rectangles_for_words(words)
                    runs, color = color_runs_for_line(expected_part, line, source, np, words)
                    add_text_mask(mask, rectangles, cv2)
                    bbox = bbox_for_words(words)
                    text_items.append(
                        make_text_item(
                            match,
                            expected_part,
                            bbox,
                            [line],
                            source_w,
                            source_h,
                            color,
                            suffix,
                            runs,
                        )
                    )
            elif len(visual_rows) > 1:
                expected_parts = partition_expected(match["expected_text"], visual_rows)
                row_colors = []
                for suffix, (row, expected_part) in enumerate(zip(visual_rows, expected_parts)):
                    words = aligned_words(expected_part, row)
                    rectangles = rectangles_for_words(words)
                    runs, color = color_runs_for_line(expected_part, row, source, np, words)
                    row_colors.append(color)
                    add_text_mask(mask, rectangles, cv2)
                    text_items.append(
                        make_text_item(
                            match,
                            expected_part,
                            bbox_for_words(words),
                            [row],
                            source_w,
                            source_h,
                            color,
                            suffix,
                            runs,
                        )
                    )
                color = row_colors[0] if row_colors else "FFFFFF"
            else:
                line = visual_rows[0] if visual_rows else composition_lines[0]
                words = aligned_words(match["expected_text"], line)
                rectangles = (
                    [tuple(bbox_for_words(words))]
                    if dominant_line is not None
                    else rectangles_for_words(words)
                )
                runs, color = color_runs_for_line(match["expected_text"], line, source, np, words)
                add_text_mask(mask, rectangles, cv2)
                text_items.append(
                    make_text_item(
                        match,
                        match["expected_text"],
                        bbox_for_words(words),
                        [line],
                        source_w,
                        source_h,
                        color,
                        0,
                        runs,
                    )
                )
            match_report.append(
                {
                    "reference_index": match["reference_index"],
                    "expected_text": match["expected_text"],
                    "ocr_text": match["ocr_text"],
                    "score": match["score"],
                    "source_bbox": match["bbox"],
                    "color": color,
                    "native_texts": [item["text"] for item in text_items[text_start:]],
                }
            )
            for patch_entry in (
                entry
                for entry in override_entries
                if entry.get("patch_match", False)
                and int(entry["reference_index"]) == int(match["reference_index"])
            ):
                target_suffix = int(patch_entry.get("target_suffix", 0))
                target_index = text_start + target_suffix
                if target_index >= len(text_items):
                    raise ValueError(
                        f"match patch target out of range for {slide_id} "
                        f"reference {match['reference_index']} suffix {target_suffix}"
                    )
                text_items[target_index] = make_reviewed_text_item(
                    patch_entry, source_w, source_h
                )

        expected_source_size = slide_override.get("source_size")
        if expected_source_size and [source_w, source_h] != [int(value) for value in expected_source_size]:
            raise ValueError(
                f"reviewed override source size mismatch for {slide_id}: "
                f"expected {expected_source_size}, got {[source_w, source_h]}"
            )
        automatically_resolved_reference_indices = (
            set(numeric_fallback_reference_indices) | semantic_recovery_reference_indices
        )
        if automatically_resolved_reference_indices:
            unmatched = [
                item
                for item in unmatched
                if int(item["reference_index"]) not in automatically_resolved_reference_indices
            ]
        unmatched_indices = {int(item["reference_index"]) for item in unmatched}
        resolved_reference_indices: set[int] = set(automatically_resolved_reference_indices)
        override_report = []
        for entry in slide_override.get("texts", []):
            if entry.get("patch_match", False):
                override_report.append(
                    {
                        "reference_index": int(entry["reference_index"]),
                        "text": str(entry["text"]),
                        "source_bbox": [int(value) for value in entry["source_bbox"]],
                        "layout_bbox": [
                            int(value) for value in entry.get("layout_bbox", entry["source_bbox"])
                        ],
                        "method": "reviewed-native-match-patch",
                    }
                )
                continue
            reference_index = int(entry["reference_index"])
            if (
                reference_index not in unmatched_indices
                and not entry.get("always_apply", False)
                and not entry.get("replace_match", False)
            ):
                continue
            try:
                cleanup_mode, cleanup_route = classify_cleanup_mode(
                    entry.get("cleanup_mode", "inpaint"), allow_none=True
                )
            except ValueError as exc:
                raise ValueError(
                    f"unsupported cleanup mode for {slide_id}/text-{reference_index}: "
                    f"{entry.get('cleanup_mode', 'inpaint')!r}"
                ) from exc
            if cleanup_route == "none":
                pass
            elif cleanup_route == "reviewed-fill":
                reviewed_cleanup_entries.append({**entry, "cleanup_mode": cleanup_mode})
            elif cleanup_route == "mask":
                make_reviewed_text_mask(entry, mask, cv2)
            else:
                raise AssertionError(f"unrouted cleanup action: {cleanup_route}")
            text_items.append(make_reviewed_text_item(entry, source_w, source_h))
            resolved_reference_indices.add(reference_index)
            override_report.append(
                {
                    "reference_index": reference_index,
                    "text": str(entry["text"]),
                    "source_bbox": [int(value) for value in entry["source_bbox"]],
                    "layout_bbox": [int(value) for value in entry.get("layout_bbox", entry["source_bbox"])],
                    "method": "reviewed-measured-override",
                }
            )
        if resolved_reference_indices:
            unmatched = [
                item for item in unmatched if int(item["reference_index"]) not in resolved_reference_indices
            ]

        clean = cv2.inpaint(source, mask, 3, cv2.INPAINT_TELEA)
        for entry in reviewed_cleanup_entries:
            fill_reviewed_region(clean, entry, cv2, np)

        for action in reviewed_native_shape_actions:
            if action["cleanup_mode"] not in {
                "outline-directional",
                "full-frame-directional",
            }:
                continue
            shape_mask = action["mask"]
            rows, columns = np.nonzero(shape_mask)
            if not len(rows) or not len(columns):
                continue
            pad = max(4, int(round(float(action["shape"].get("line_width_px", 4)))) + 3)
            x1 = max(0, int(columns.min()) - pad)
            y1 = max(0, int(rows.min()) - pad)
            x2 = min(source_w, int(columns.max()) + pad + 1)
            y2 = min(source_h, int(rows.max()) + pad + 1)
            repair_direction = reviewed_shape_repair_direction(
                action["shape"], action["cleanup_mode"]
            )
            clean[y1:y2, x1:x2] = _directional_repair_patch(
                clean[y1:y2, x1:x2],
                shape_mask[y1:y2, x1:x2],
                np,
                direction=repair_direction,
            )

        normalized_source = cv2.resize(
            source, (REF_W, REF_H), interpolation=cv2.INTER_LANCZOS4
        )
        normalized = cv2.resize(clean, (REF_W, REF_H), interpolation=cv2.INTER_LANCZOS4)
        text_clean_path = slide_asset_dir / "text-clean-master.png"
        clean_path = slide_asset_dir / "clean-master.png"
        reviewed_mask_dir = slide_asset_dir / "reviewed-frame-cleanup"
        reviewed_mask_dir.mkdir(parents=True, exist_ok=True)

        for action_index, action in enumerate(reviewed_native_shape_actions):
            shape = action["shape"]
            shape_type = str(shape.get("type", "")).lower()
            normalized_mask = cv2.resize(
                action["mask"],
                (REF_W, REF_H),
                interpolation=cv2.INTER_NEAREST,
            )
            normalized_evidence_mask = cv2.resize(
                action.get("evidence_mask", action["mask"]),
                (REF_W, REF_H),
                interpolation=cv2.INTER_NEAREST,
            )
            cleanup_mask_path = reviewed_mask_dir / f"{shape['frame_id']}.png"
            cleanup_mask = ""
            if action["cleanup_applied"] and np.count_nonzero(normalized_mask):
                cv2.imwrite(str(cleanup_mask_path), normalized_mask)
                cleanup_mask = str(cleanup_mask_path.resolve())

            try:
                line_bgr = hex_to_bgr(shape.get("line_color", shape.get("line", "2D9CC4")))
            except ValueError:
                line_bgr = hex_to_bgr("2D9CC4")
            source_color_support = _frame_color_support(
                normalized_source, normalized_evidence_mask, line_bgr, np
            )
            post_color_support = _frame_color_support(
                normalized, normalized_evidence_mask, line_bgr, np
            )
            source_edge_support = edge_support(
                normalized_source, normalized_evidence_mask, cv2, np
            )
            post_edge_support = edge_support(
                normalized, normalized_evidence_mask, cv2, np
            )
            selected_mask = normalized_evidence_mask > 0
            mean_abs_cleanup_delta = (
                float(
                    np.mean(
                        np.abs(
                            normalized_source[selected_mask].astype(np.float32)
                            - normalized[selected_mask].astype(np.float32)
                        )
                    )
                )
                if np.count_nonzero(selected_mask)
                else 0.0
            )
            cleanup_delegate = str(shape.get("cleanup_delegated_to", "")).strip()
            semantic_content_coverage = 1.0
            if action.get("reviewed_panel"):
                content_left, content_top, content_width, content_height = [
                    int(round(float(value))) for value in shape["content_bbox"]
                ]
                content_region = normalized_mask[
                    content_top : content_top + content_height,
                    content_left : content_left + content_width,
                ]
                semantic_content_coverage = (
                    float(np.mean(content_region > 0)) if content_region.size else 0.0
                )
            if cleanup_delegate and not action["cleanup_applied"]:
                cleanup_status = "delegated"
                assessment = {
                    "support_mode": "delegated",
                    "source_support": 0.0,
                    "post_cleanup_support": 0.0,
                    "residual_ratio": 0.0,
                }
            else:
                assessment = reviewed_shape_cleanup_assessment(
                    shape_type=shape_type,
                    cleanup_applied=action["cleanup_applied"],
                    source_color_support=source_color_support,
                    post_color_support=post_color_support,
                    source_edge_support=source_edge_support,
                    post_edge_support=post_edge_support,
                    mean_abs_cleanup_delta=mean_abs_cleanup_delta,
                    semantic_content_coverage=semantic_content_coverage,
                )
                cleanup_status = assessment["status"]
            source_support = float(assessment["source_support"])
            post_cleanup_support = float(assessment["post_cleanup_support"])
            residual_ratio = float(assessment["residual_ratio"])
            cleanup_evidence = {
                "status": cleanup_status,
                "method": (
                    "delegated"
                    if cleanup_delegate
                    else "reviewed-panel-full-region-directional"
                    if action.get("reviewed_panel")
                    else action["cleanup_mode"]
                ),
                "cleanup_mask": cleanup_mask,
                "mask_bbox": shape["frame_bbox"],
                "cleanup_width_px": shape["line_width_px"],
                "source_support": round(source_support, 6),
                "post_cleanup_support": round(post_cleanup_support, 6),
                "source_frame_support": round(source_support, 6),
                "post_cleanup_frame_support": round(post_cleanup_support, 6),
                "residual_ratio": round(residual_ratio, 6),
                "support_mode": assessment["support_mode"],
                "source_color_support": round(source_color_support, 6),
                "post_cleanup_color_support": round(post_color_support, 6),
                "source_edge_support": round(source_edge_support, 6),
                "post_cleanup_edge_support": round(post_edge_support, 6),
                "mean_abs_cleanup_delta_0_255": round(mean_abs_cleanup_delta, 6),
            }
            if action.get("reviewed_panel"):
                cleanup_evidence.update(
                    {
                        "background_cleanup_scope": "full-semantic-panel",
                        "content_bbox": shape["content_bbox"],
                        "semantic_content_coverage": round(
                            semantic_content_coverage, 6
                        ),
                    }
                )
            if cleanup_delegate:
                cleanup_evidence["cleanup_delegated_to"] = cleanup_delegate
            shape["cleanup_mask"] = cleanup_mask
            shape["mask_bbox"] = shape["frame_bbox"]
            shape["cleanup_evidence"] = cleanup_evidence
            reviewed_native_shape_report[action_index]["cleanup_evidence"] = cleanup_evidence

        reviewed_panel_overlays = []
        for action in reviewed_panel_actions:
            asset, report = build_reviewed_panel_content_asset(
                action["panel_entry"],
                action["shape"],
                source,
                source_path,
                slide_asset_dir,
                int(action["panel_index"]),
                cv2,
            )
            report["cleanup_evidence"] = action["shape"].get("cleanup_evidence", {})
            reviewed_panel_overlays.append(asset)
            reviewed_panel_report.append(report)

        cv2.imwrite(str(text_clean_path), normalized)
        detected_panel_candidates = detect_flat_panels(normalized, cv2, np)
        reserved_frame_ids = {
            str(shape.get("frame_id", "")).strip()
            for shape in reviewed_native_shapes
            if str(shape.get("frame_id", "")).strip()
        }
        for panel_index, panel in enumerate(detected_panel_candidates, 1):
            frame_id = f"frame-{slide_id}-{panel_index:03d}"
            if frame_id in reserved_frame_ids:
                frame_id = f"frame-{slide_id}-auto-{panel_index:03d}"
            panel["frame_id"] = frame_id
        detected_with_indices = [
            {**panel, "detection_index": detection_index}
            for detection_index, panel in enumerate(detected_panel_candidates)
        ]
        unsuppressed_candidates, suppressed_panel_candidates = (
            suppress_reviewed_panel_candidates(
                detected_with_indices,
                [action["shape"] for action in reviewed_panel_actions],
            )
        )
        panel_exclusions = list(slide_override.get("panel_exclusions", []))
        panel_candidates = []
        excluded_panels = []
        for candidate in unsuppressed_candidates:
            matching_exclusion = next(
                (
                    entry
                    for entry in panel_exclusions
                    if panel_matches_exclusion(candidate, entry)
                ),
                None,
            )
            if matching_exclusion is None:
                panel_candidates.append(candidate)
                continue
            excluded_panels.append(
                {
                    **candidate,
                    "reason": str(matching_exclusion.get("reason", "")).strip(),
                    "reviewed_bbox": matching_exclusion.get("bbox")
                    or matching_exclusion.get("source_bbox"),
                }
            )
        geometry_clean, gap_shapes, gap_texts, gap_report = extract_gap_native_objects(
            normalized, panel_candidates, cv2, np
        )
        background, panel_shapes, panel_overlays, panel_report = extract_native_panels(
            geometry_clean, slide_asset_dir, cv2, np, panel_candidates
        )
        shapes = list(panel_shapes)
        shapes.extend(gap_shapes)
        shapes.extend(reviewed_native_shapes)
        text_items.extend(gap_texts)
        semantic_assets = [*panel_overlays, *reviewed_panel_overlays]
        counterfactual_cleanup_report: dict[str, Any] | None = None
        counterfactual_config = slide_override.get("counterfactual_background_cleanup")
        if isinstance(counterfactual_config, dict) and bool(
            counterfactual_config.get("enabled", True)
        ):
            background, counterfactual_mask, counterfactual_cleanup_report = (
                counterfactual_surface_repair(
                    background,
                    shapes,
                    text_items,
                    semantic_assets,
                    counterfactual_config,
                    cv2,
                    np,
                )
            )
            counterfactual_mask_path = (
                slide_asset_dir / "counterfactual-background-cleanup-mask.png"
            )
            if not cv2.imwrite(str(counterfactual_mask_path), counterfactual_mask):
                raise OSError(
                    f"failed to write counterfactual cleanup mask: {counterfactual_mask_path}"
                )
            counterfactual_cleanup_report["cleanup_mask"] = str(
                counterfactual_mask_path.resolve()
            )
        cv2.imwrite(str(clean_path), background)
        if args.background_mode == "tiled":
            background_tiles = create_tiles(background, slide_asset_dir / "tiles", args.tile_rows, args.tile_cols, cv2)
            background_asset = None
            icons = [*background_tiles, *semantic_assets]
        else:
            background_tiles = []
            background_asset = str(clean_path.relative_to(out_dir)).replace("\\", "/")
            icons = semantic_assets
        text_items = dedupe_text_items(text_items)
        deck_slide = {
            "slide_id": slide_id,
            "background": background_asset,
            "icons": icons,
            "texts": text_items,
            "shapes": shapes,
            "notes": build_source_notes(reference_by_id[slide_id], source_metadata),
            "allow_all_bold_text": True,
            "qa_note": (
                "Continuous full-slide background; bold weight follows the ImageGen master."
                if args.background_mode == "single"
                else "Legacy tiled background compatibility mode; bold weight follows the ImageGen master."
            ),
        }
        if counterfactual_cleanup_report is not None:
            deck_slide["counterfactual_background_cleanup"] = (
                counterfactual_cleanup_report
            )
        deck_slides.append(deck_slide)
        qa_slides.append(
            {
                "slide_id": slide_id,
                "source": str(source_path.resolve()),
                "ocr_lines": len(ocr.get("lines", [])),
                "reference_texts": len(references),
                "matched_reference_texts": len(
                    {int(match["reference_index"]) for match in matches} | resolved_reference_indices
                ),
                "ocr_matched_reference_texts": len(matches),
                "reviewed_override_reference_texts": len({int(item["reference_index"]) for item in override_report}),
                "numeric_table_fallback_reference_texts": len(numeric_fallback_reference_indices),
                "unmatched_reference_texts": unmatched,
                "matches": match_report,
                "numeric_table_fallbacks": numeric_fallback_report,
                "semantic_exact_text_recoveries": semantic_recovery_report,
                "reviewed_overrides": override_report,
                "reviewed_cleanup_regions": cleanup_region_report,
                "reviewed_native_shapes": reviewed_native_shape_report,
                "reviewed_panels": reviewed_panel_report,
                "counterfactual_background_cleanup": counterfactual_cleanup_report,
                "detected_panels": len(detected_panel_candidates),
                "suppressed_panels": len(suppressed_panel_candidates),
                "reviewed_panel_candidate_suppressions": suppressed_panel_candidates,
                "excluded_panels": len(excluded_panels),
                "reviewed_panel_exclusions": excluded_panels,
                "text_clean_master": str(text_clean_path.resolve()),
                "clean_master": str(clean_path.resolve()),
                "background_tiles": len(background_tiles),
                "native_panels": len(panel_shapes),
                "panel_overlays": len(panel_overlays),
                "panel_cleanup_failures": sum(
                    1
                    for item in panel_report
                    if item.get("cleanup_evidence", {}).get("status") != "pass"
                ),
                "native_gap_shapes": len(gap_shapes),
                "native_gap_texts": len(gap_texts),
                "panels": panel_report,
                "gap_native_objects": gap_report,
            }
        )

    deck_title = (
        args.deck_title.strip()
        or str(prompt_manifest.get("deck_title", "")).strip()
        or str(prompt_manifest.get("deck", {}).get("title", "")).strip()
        or str(reference_deck.get("title", "")).strip()
        or "ImageGen高保真可编辑重构"
    )
    deck = {
        "title": deck_title,
        "subject": "pixel-anchored ImageGen-to-editable reconstruction",
        "units": "pixels",
        "ref_width": REF_W,
        "ref_height": REF_H,
        "slide_width_in": SLIDE_W_IN,
        "slide_height_in": SLIDE_H_IN,
        "assets_dir": str(out_dir.resolve()),
        "slides": deck_slides,
    }
    write_json(out_dir / "deck-high-fidelity.json", deck)
    write_json(
        out_dir / "qa" / "reconstruction-analysis.json",
        {
            "method": "ImageGen pixel anchor + OCR text mask + OpenCV inpaint + native text/panels + movable complex assets + reviewed semantic panels/exclusions/native frames",
            "selected_slides": selected,
            "background_mode": args.background_mode,
            "tile_grid": [args.tile_rows, args.tile_cols] if args.background_mode == "tiled" else None,
            "reviewed_overrides": str(reviewed_overrides_path) if reviewed_overrides_path.exists() else None,
            "semantic_overrides": str(semantic_overrides_path) if semantic_overrides_path.exists() else None,
            "slides": qa_slides,
        },
    )
    print(json.dumps({"deck": str(out_dir / "deck-high-fidelity.json"), "slides": selected}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
