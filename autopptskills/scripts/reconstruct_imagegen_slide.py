#!/usr/bin/env python3
"""Reconstruct one imagegen full-slide master into a mixed editable PPTX."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from detect_editable_elements import analyze_image, draw_overlay
from trace_icon_to_svg import trace_icon
from component_manifest import build_component_manifest
from component_manifest_qa import validate as validate_component_manifest


SCRIPT_DIR = Path(__file__).resolve().parent


def _collect_strings(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from _collect_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _collect_strings(child)
    elif isinstance(value, str):
        yield value


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _builtin_provenance_record(record: dict[str, Any]) -> bool:
    imagegen_id = str(
        record.get("id")
        or record.get("imagegen_id")
        or record.get("generation_id")
        or ""
    ).strip().lower()
    backend = str(record.get("backend") or record.get("imagegen_backend") or "").strip().lower()
    provenance = str(record.get("provenance_kind") or record.get("provenance") or "").strip().lower()
    generation_mode = str(record.get("generation_mode") or "").strip()
    status = str(record.get("status") or record.get("provenance_status") or "").strip().lower()
    # The Codex desktop host currently records completed built-in calls with
    # ``exec-...`` item ids rather than the older ``ig_...`` ids.  Accept the
    # host id only when the independent backend/provenance fields still prove
    # this was a built-in direct final-slide generation.
    host_generation_id = imagegen_id.startswith("exec-")
    strong_generation_id = imagegen_id.startswith("ig_")
    return (
        (strong_generation_id or host_generation_id)
        and generation_mode == "direct_final_slide_imagegen"
        and status in {"generated", "completed"}
        and (
            backend in {"builtin", "builtin_image_gen"}
            or provenance in {"builtin-imagegen", "builtin_image_gen", "image_generation_call"}
            or provenance.startswith("builtin-")
        )
    )


def _manifest_candidates(manifest_path: Path, source: Path) -> list[Path]:
    """Find the prompt pack plus adjacent built-in provenance sidecars."""
    stage_dir = manifest_path.parent
    if manifest_path.name.lower() in {"asset-manifest.json", "imagegen_manifest.json"}:
        stage_dir = manifest_path.parent.parent
    stem = source.stem
    candidates = [
        manifest_path,
        stage_dir / "references" / "asset-manifest.json",
        stage_dir / "builtin-imagegen-handoff.json",
        stage_dir / "assets" / "generated" / f"{stem}-pipeline.json",
        stage_dir / "assets" / "slides" / f"{stem}.imagegen_manifest.json",
        stage_dir / "assets" / "slides" / f"{stem}.image_generation_metadata.json",
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        key = str(resolved).lower()
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _verify_imagegen_manifest(manifest_path: Path | None, source: Path) -> tuple[bool, str | None]:
    if manifest_path is None:
        return False, "imagegen manifest was not supplied"
    if not manifest_path.exists():
        return False, f"imagegen manifest not found: {manifest_path}"
    try:
        source_digest = _sha256_file(source)
    except OSError as exc:
        return False, f"source image could not be hashed: {exc.__class__.__name__}"
    candidates = _manifest_candidates(manifest_path.resolve(), source.resolve())
    loaded: list[tuple[Path, Any]] = []
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            loaded.append((candidate, json.loads(candidate.read_text(encoding="utf-8-sig"))))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    if not loaded:
        return False, f"imagegen manifest could not be read: {manifest_path}"
    normalized_source = source.resolve()
    source_name = source.name.lower()
    source_stem = source.stem.lower()
    source_referenced = False
    strong_match = False
    for _path, data in loaded:
        for value in _collect_strings(data):
            normalized = value.replace("\\", "/").lower()
            if source_name in normalized or normalized.endswith(f"/{source_stem}.png"):
                source_referenced = True
            try:
                candidate = Path(value)
                if candidate.is_absolute() and candidate.resolve() == normalized_source:
                    source_referenced = True
            except (OSError, ValueError):
                pass
        for record in _iter_dicts(data):
            if not _builtin_provenance_record(record):
                continue
            record_digest = str(
                record.get("sha256")
                or record.get("image_sha256")
                or record.get("output_sha256")
                or ""
            ).strip().lower()
            output_text = " ".join(_collect_strings(record)).replace("\\", "/").lower()
            if record_digest and record_digest == source_digest:
                strong_match = True
            elif source_name in output_text or output_text.endswith(f"/{source_stem}.png"):
                strong_match = True
    if not source_referenced:
        return False, f"source image {source.name} is not referenced by the imagegen manifest"
    if not strong_match:
        return False, (
            f"source image {source.name} lacks matching strong ig_ Codex built-in "
            "image_gen provenance"
        )
    return True, None


def _manifest_exact_text(manifest_path: Path | None, slide_stem: str) -> list[str]:
    if manifest_path is None or not manifest_path.exists():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    slides = data.get("slides", []) if isinstance(data, dict) else []
    selected = next((item for item in slides if str(item.get("slide_id", "")).lower() == slide_stem.lower()), None)
    if not selected:
        return []
    candidates: list[str] = []
    for value in selected.get("exact_text", []):
        text = str(value).strip()
        if not text:
            continue
        candidates.append(text)
        fragments = [
            fragment.strip()
            for fragment in re.split(r"[、，,；;|]", text)
            if len(_normalized_text(fragment.strip())) >= 4
        ]
        if len(fragments) > 1:
            candidates.extend(fragments)
    return list(dict.fromkeys(candidates))


def _slide_manifest_exact_text(manifest: dict[str, Any] | None, slide_id: str) -> list[str]:
    """Collect reviewed text from Slide Manifest without OCR-ing it again."""
    if not isinstance(manifest, dict):
        return []
    slides = manifest.get("slides") or [manifest]
    selected = next((item for item in slides if str(item.get("slide_id", "")) == slide_id), None)
    if not isinstance(selected, dict):
        selected = manifest
    out: list[str] = []
    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str) and value.strip() and key in {"title", "subtitle", "body", "text", "label", "footnote", "equation", "value"}:
            out.append(value.strip())
    walk(selected)
    return list(dict.fromkeys(out))


def _normalized_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", value).lower()


def _reconcile_ocr_with_manifest(analysis: dict[str, Any], candidates: list[str]) -> None:
    normalized_candidates = [(candidate, _normalized_text(candidate)) for candidate in candidates]
    for item in analysis["texts"]:
        if item.get("corrected_from_imagegen_manifest") and item.get("ocr_text"):
            item["text"] = item["ocr_text"]
            item.pop("corrected_from_imagegen_manifest", None)
            item.pop("manifest_match_score", None)
        source = _normalized_text(str(item.get("text", "")))
        if not source:
            continue
        best_text = None
        best_score = 0.0
        for candidate, normalized in normalized_candidates:
            if not normalized:
                continue
            score = difflib.SequenceMatcher(None, source, normalized).ratio()
            if source in normalized or normalized in source:
                score = max(score, min(len(source), len(normalized)) / max(len(source), len(normalized)))
            if score > best_score:
                best_score = score
                best_text = candidate
        if best_text is not None and best_score >= 0.58:
            item["ocr_text"] = item["text"]
            item["text"] = best_text
            item["manifest_match_score"] = round(best_score, 4)
            item["corrected_from_imagegen_manifest"] = True
            if best_score >= 0.72:
                item["needs_review"] = False
    analysis["unresolved"] = [
        item for item in analysis.get("unresolved", [])
        if not (
            item.get("kind") == "text"
            and any(text["id"] == item.get("id") and not text.get("needs_review", False) for text in analysis["texts"])
        )
    ]
    normalized_groups: dict[str, list[dict[str, Any]]] = {}
    for item in analysis["texts"]:
        normalized = _normalized_text(str(item.get("text", "")))
        if normalized:
            normalized_groups.setdefault(normalized, []).append(item)
    for group in normalized_groups.values():
        if len(group) < 2:
            continue
        for item in group:
            if not item.get("corrected_from_imagegen_manifest"):
                item["needs_review"] = True
                item["duplicate_ocr_text"] = True
                analysis["unresolved"].append({
                    "id": item["id"],
                    "kind": "text",
                    "reason": "duplicate-ocr-text-needs-review",
                    "confidence": item.get("confidence"),
                })


def _select_texts(analysis: dict[str, Any], height: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    embedded: list[dict[str, Any]] = []
    for item in analysis["texts"]:
        size = float(item.get("size", 0.0))
        confidence = float(item.get("confidence", 0.0))
        _, y, _, box_height = item["bbox"]
        color = str(item.get("color", "#111111")).lstrip("#")
        try:
            red, green, blue = (int(color[index:index + 2], 16) for index in (0, 2, 4))
        except (TypeError, ValueError):
            red, green, blue = (17, 17, 17)
        plain_dark_title = max(red, green, blue) <= 72 and max(red, green, blue) - min(red, green, blue) <= 45
        stylized_title = box_height >= height * 0.10 and not plain_dark_title
        manifest_matched = bool(item.get("corrected_from_imagegen_manifest"))
        is_large_normal_text = size >= 16.0 and confidence >= 0.75
        is_bottom_summary = y >= height * 0.77 and size >= 16.0 and confidence >= 0.60
        is_prominent = box_height >= height * 0.045 and confidence >= 0.72
        # A vertical band is not evidence of a photograph. Only an explicitly
        # reviewed asset region may retain embedded text as a raster exception.
        inside_photo_body = bool(item.get("reviewed_embedded_text"))
        # Reviewed source/slide-manifest text may explicitly opt into native
        # reconstruction even when OCR classifies it as stylized art text or
        # low-confidence.  This is the safe escape hatch for titles and
        # labels that must remain editable in the final PPTX; the exact string
        # still comes from the manifest, never from OCR.
        force_native = bool(item.get("force_native"))
        if force_native or (not stylized_title and not inside_photo_body and (manifest_matched or is_large_normal_text or is_bottom_summary or is_prominent)):
            selected.append(item)
        else:
            if stylized_title:
                item["art_text"] = True
            embedded.append(item)
    return selected, embedded


def _apply_overrides(analysis: dict[str, Any], override_path: Path | None) -> dict[str, Any]:
    if override_path is None:
        return analysis
    overrides = json.loads(override_path.read_text(encoding="utf-8"))
    slide_key = str(analysis.get("slide_id") or "")

    def scoped(name: str, default: Any) -> Any:
        value = overrides.get(name, default)
        if isinstance(value, dict):
            if slide_key in value:
                return value[slide_key]
            # List-valued override fields may be keyed by slide ID.  A slide
            # without an entry gets an empty list; extending the analysis with
            # the mapping itself would otherwise append strings such as S06.
            if isinstance(default, list):
                return default
        return value

    drop_ids = set(str(value) for value in scoped("drop_ids", []))
    replacements = {str(key): str(value) for key, value in scoped("replace_text", {}).items()}
    text_updates = overrides.get("text_updates", {})
    # Deck-level reviewed overrides may be keyed by slide_id.  Accepting that
    # form keeps one provenance file for the whole deck while preserving the
    # existing single-slide override contract.
    if isinstance(text_updates, dict) and text_updates and all(isinstance(value, dict) for value in text_updates.values()):
        nested = text_updates.get(slide_key)
        if isinstance(nested, dict):
            text_updates = nested
        elif any(str(key).startswith("text-") for key in text_updates):
            text_updates = text_updates
        else:
            text_updates = {}

    analysis["texts"] = [item for item in analysis["texts"] if item["id"] not in drop_ids]
    analysis["shapes"] = [item for item in analysis["shapes"] if item["id"] not in drop_ids]
    analysis["lines"] = [item for item in analysis["lines"] if item["id"] not in drop_ids]
    analysis["icon_candidates"] = [item for item in analysis["icon_candidates"] if item["id"] not in drop_ids]
    for item in analysis["texts"]:
        if item["id"] in replacements:
            item["text"] = replacements[item["id"]]
            item["needs_review"] = False
            item["corrected_by_override"] = True
        if item["id"] in text_updates:
            item.update(text_updates[item["id"]])
    reviewed_ids = {
        item_id for item_id, update in text_updates.items()
        if update.get("needs_review") is False
    }
    analysis["unresolved"] = [
        item for item in analysis.get("unresolved", [])
        if not (item.get("kind") == "text" and item.get("id") in reviewed_ids)
    ]
    analysis["texts"].extend(scoped("add_texts", []))
    analysis["shapes"].extend(scoped("add_shapes", []))
    analysis["lines"].extend(scoped("add_lines", []))
    analysis["icon_candidates"].extend(scoped("add_icon_candidates", []))
    analysis["override_file"] = str(override_path.resolve())
    return analysis


def _apply_visual_first_text_only(analysis: dict[str, Any]) -> dict[str, Any]:
    """Keep ImageGen artwork intact and route only reviewed text to native PPT.

    This conservative post-ImageGen mode is for pages where automatic contour
    and frame promotion creates visible duplicate strokes.  It does not draw a
    replacement page: the verified ImageGen master remains the visual source,
    while selected text is removed locally and rebuilt as native text.
    """
    analysis["shapes"] = []
    analysis["lines"] = []
    analysis["icon_candidates"] = []
    analysis["visual_first_text_only"] = True
    return analysis


def _object_foreground_mask(image: np.ndarray, bbox: list[int]) -> tuple[np.ndarray, list[int]]:
    height, width = image.shape[:2]
    x, y, w, h = bbox
    pad = max(4, int(round(h * 0.12)))
    left, top = max(0, x - pad), max(0, y - pad)
    right, bottom = min(width, x + w + pad), min(height, y + h + pad)
    crop = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2RGB)
    border = np.concatenate((crop[0], crop[-1], crop[:, 0], crop[:, -1]), axis=0).astype(np.float32)
    background = np.median(border, axis=0)
    distances = np.linalg.norm(crop.astype(np.float32) - background, axis=2)
    border_distances = np.linalg.norm(border - background, axis=1)
    threshold = max(12.0, float(np.percentile(border_distances, 90)) + 6.0)
    local = np.where(distances >= threshold, 255, 0).astype(np.uint8)
    inner = np.zeros_like(local)
    inner[y - top:y - top + h, x - left:x - left + w] = 255
    local = cv2.bitwise_and(local, inner)
    local = cv2.morphologyEx(local, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    dilation = max(3, min(9, int(round(h * 0.045)) | 1))
    local = cv2.dilate(local, np.ones((dilation, dilation), np.uint8), iterations=1)
    ratio = float(np.count_nonzero(local)) / float(max(1, w * h))
    if ratio < 0.01 or ratio > 0.68:
        local[:] = 0
        cv2.rectangle(local, (x - left, y - top), (x - left + w, y - top + h), 255, -1)
    return local, [left, top, right - left, bottom - top]


def _reviewed_text_mask(image: np.ndarray, bbox: list[int]) -> tuple[np.ndarray, list[int]]:
    """Mask only bright glyph pixels for an explicitly reviewed native text item.

    The generic foreground detector is intentionally conservative for unknown
    OCR regions and falls back to the full box when a region is dense. That is
    the wrong behavior for reviewed labels: it erases the card/panel behind the
    text and leaves a large Telea blur. Use a luminance/value mask with a small
    interior margin so frames and panel fills remain part of the background.
    """
    height, width = image.shape[:2]
    x, y, w, h = [int(value) for value in bbox]
    left, top = max(0, x), max(0, y)
    right, bottom = min(width, x + w), min(height, y + h)
    crop = image[top:bottom, left:right]
    if crop.size == 0:
        return np.zeros((0, 0), dtype=np.uint8), [left, top, 0, 0]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    margin_x = max(2, int(round(crop.shape[1] * 0.025)))
    margin_y = max(2, int(round(crop.shape[0] * 0.10)))
    # For reviewed source text, the bbox is already a semantic text region.
    # Remove the complete local region so antialiased shadows and colored
    # glyph halos cannot remain behind the visible native text. The region is
    # deliberately limited to the text bbox, preserving surrounding artwork
    # and connector geometry.
    mask = np.zeros_like(gray, dtype=np.uint8)
    inset = max(1, int(round(min(crop.shape[:2]) * 0.02)))
    mask[inset:max(inset + 1, crop.shape[0] - inset), inset:max(inset + 1, crop.shape[1] - inset)] = 255
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    return mask, [left, top, right - left, bottom - top]


def _sample_text_color_runs(image: np.ndarray, item: dict[str, Any]) -> list[dict[str, Any]] | None:
    text = str(item.get("text", ""))
    if len(text) < 3:
        return None
    x, y, width, height = item.get("ocr_bbox", item["bbox"])
    pad = max(4, int(round(height * 0.12)))
    left, top = max(0, x - pad), max(0, y - pad)
    right, bottom = min(image.shape[1], x + width + pad), min(image.shape[0], y + height + pad)
    crop = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2RGB)
    border = np.concatenate((crop[0], crop[-1], crop[:, 0], crop[:, -1]), axis=0).astype(np.float32)
    background = np.median(border, axis=0)
    colors: list[np.ndarray | None] = []
    for index in range(len(text)):
        start = x + int(round(width * index / len(text)))
        end = x + int(round(width * (index + 1) / len(text)))
        segment = cv2.cvtColor(image[y:y + height, max(x, start):max(start + 1, end)], cv2.COLOR_BGR2RGB)
        pixels = segment.reshape(-1, 3).astype(np.float32)
        distances = np.linalg.norm(pixels - background, axis=1)
        foreground = pixels[distances >= max(18.0, float(np.percentile(distances, 72)))]
        colors.append(np.median(foreground, axis=0) if foreground.shape[0] >= 4 else None)
    fallback_hex = str(item.get("color", "#111111")).lstrip("#")
    try:
        fallback = np.array([int(fallback_hex[index:index + 2], 16) for index in (0, 2, 4)], dtype=np.float32)
    except ValueError:
        fallback = np.array([17.0, 17.0, 17.0], dtype=np.float32)
    numeric = np.array([color if color is not None else fallback for color in colors], dtype=np.float32)
    if len(numeric) < 4:
        return None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 25, 1.0)
    _, labels, centers = cv2.kmeans(numeric, 2, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
    if float(np.linalg.norm(centers[0] - centers[1])) < 68.0:
        return None
    label_values = labels.ravel().tolist()
    transitions = sum(1 for index in range(1, len(label_values)) if label_values[index] != label_values[index - 1])
    if transitions > 4:
        return None
    runs: list[dict[str, Any]] = []
    start = 0
    for index in range(1, len(text) + 1):
        if index < len(text) and label_values[index] == label_values[start]:
            continue
        center = centers[label_values[start]]
        color = "#" + "".join(f"{int(np.clip(round(value), 0, 255)):02X}" for value in center)
        runs.append({"text": text[start:index], "color": color, "bold": bool(item.get("bold"))})
        start = index
    return runs if len(runs) >= 2 else None


def _composition_text_item(
    item: dict[str, Any],
    slide_width_px: int,
    slide_height_px: int,
    source_image: np.ndarray,
) -> dict[str, Any]:
    text_item = dict(item)
    x, y, width, height = item["bbox"]
    source_bbox = item.get("ocr_bbox") or item.get("source_bbox") or item["bbox"]
    if width >= slide_width_px * 0.24:
        expansion = 0.16
    elif y >= slide_height_px * 0.76:
        expansion = 0.34
    else:
        expansion = 0.28
    extra = int(round(width * expansion))
    if item.get("align") == "left":
        new_x = x
        new_right = min(slide_width_px, x + width + extra)
    else:
        new_x = max(0, x - extra // 2)
        new_right = min(slide_width_px, x + width + extra - extra // 2)
    layout_bbox = [new_x, y, max(1, new_right - new_x), height]
    text_item.update({"x": layout_bbox[0], "y": layout_bbox[1], "w": layout_bbox[2], "h": layout_bbox[3]})
    text_item["source_bbox"] = list(source_bbox)
    text_item["layout_bbox"] = layout_bbox
    text_length = len(_normalized_text(str(item.get("text", ""))))
    font_size = float(item.get("size", 18.0))
    if item.get("native_rebuild"):
        # Reviewed bboxes are measured in source-image pixels. Convert them
        # to PowerPoint points before PptxGenJS renders the text.
        font_size *= (13.333333 * 72.0 / float(max(1, slide_width_px)))
    if text_length >= 10 and not item.get("native_rebuild"):
        font_size *= 0.90
    if y >= slide_height_px * 0.76 and text_length >= 5:
        font_size *= 0.88
    text_item["size"] = round(max(8.0, font_size), 1)
    text_item["fit"] = "shrink"
    # Native text reconstruction should use one stable PowerPoint color unless
    # the reviewed item explicitly keeps the source's raster typography.  The
    # previous round sampled background pixels into per-character runs while
    # the text itself was transparent, which made the apparent text remain
    # baked into the full-slide image.  A reviewed native item now becomes a
    # genuinely visible text box with deterministic styling.
    if item.get("preserve_raster", True):
        runs = _sample_text_color_runs(source_image, item)
        if runs:
            text_item["runs"] = runs
    else:
        text_item.pop("runs", None)
    return text_item


def _bbox_overlap_ratio(a: list[float], b: list[float]) -> float:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[0] + a[2], b[0] + b[2])
    bottom = min(a[1] + a[3], b[1] + b[3])
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    return overlap / max(1.0, min(a[2] * a[3], b[2] * b[3]))


def _mark_intentional_source_overlaps(texts: list[dict[str, Any]], icons: list[dict[str, Any]]) -> None:
    for text_item in texts:
        text_bbox = text_item.get("source_bbox")
        if not text_bbox:
            continue
        for icon_item in icons:
            icon_bbox = icon_item.get("source_bbox")
            if not icon_bbox or _bbox_overlap_ratio(text_bbox, icon_bbox) <= 0.08:
                continue
            text_item.setdefault("allow_overlap_with", []).append(icon_item["id"])
            icon_item.setdefault("allow_overlap_with", []).append(text_item["id"])


def _line_color_support(image: np.ndarray, mask: np.ndarray, line_color: Any) -> float:
    color = str(line_color or "").strip().lstrip("#")
    if len(color) == 3:
        color = "".join(character * 2 for character in color)
    if len(color) != 6 or not np.count_nonzero(mask):
        return 0.0
    try:
        red, green, blue = (int(color[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return 0.0
    target_bgr = np.asarray([blue, green, red], dtype=np.float32)
    selected = image[mask > 0].astype(np.float32)
    return float(np.mean(np.linalg.norm(selected - target_bgr, axis=1) <= 48.0))


def _native_line_cleanup_mask(
    canvas_shape: tuple[int, int],
    item: dict[str, Any],
    stroke: int,
) -> np.ndarray:
    height, width = canvas_shape
    mask = np.zeros((height, width), dtype=np.uint8)
    start = (
        int(np.clip(item["x1"], 0, width - 1)),
        int(np.clip(item["y1"], 0, height - 1)),
    )
    end = (
        int(np.clip(item["x2"], 0, width - 1)),
        int(np.clip(item["y2"], 0, height - 1)),
    )
    cleanup_width = max(3, stroke + 2)
    cv2.line(mask, start, end, 255, cleanup_width, cv2.LINE_AA)
    arrow_radius = max(5, cleanup_width * 2)
    if item.get("begin_arrow"):
        cv2.circle(mask, start, arrow_radius, 255, -1, cv2.LINE_AA)
    if item.get("end_arrow"):
        cv2.circle(mask, end, arrow_radius, 255, -1, cv2.LINE_AA)
    return cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)


def _inpaint_background(
    source: Path,
    analysis: dict[str, Any],
    accepted_icon_masks: dict[str, Path],
    output: Path,
    mask_output: Path,
    line_mask_dir: Path | None = None,
) -> dict[str, Any]:
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"unable to read image: {source}")
    height, width = image.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    text_padding = max(3, int(round(height / 260)))
    stroke = max(3, int(round(height / 260)))
    line_cleanup: list[tuple[dict[str, Any], np.ndarray, Path | None]] = []

    for item in analysis["texts"]:
        if item.get("native_rebuild"):
            local_mask, local_bbox = _reviewed_text_mask(image, item.get("ocr_bbox", item["bbox"]))
        else:
            local_mask, local_bbox = _object_foreground_mask(image, item.get("ocr_bbox", item["bbox"]))
        left, top, local_width, local_height = local_bbox
        mask[top:top + local_height, left:left + local_width] = cv2.bitwise_or(
            mask[top:top + local_height, left:left + local_width], local_mask
        )
    for item in analysis["shapes"]:
        if float(item.get("confidence", 0.0)) < 0.78:
            continue
        x, y, w, h = item["bbox"]
        cv2.rectangle(mask, (x, y), (min(width - 1, x + w), min(height - 1, y + h)), 255, stroke)
    for item in analysis["lines"]:
        local_mask = _native_line_cleanup_mask((height, width), item, stroke)
        mask = cv2.bitwise_or(mask, local_mask)
        cleanup_path = line_mask_dir / f"{item['id']}.png" if line_mask_dir else None
        line_cleanup.append((item, local_mask, cleanup_path))
    for item in analysis["icon_candidates"]:
        icon_mask_path = accepted_icon_masks.get(item["id"])
        if icon_mask_path is None:
            continue
        x, y, w, h = item["bbox"]
        local_mask = cv2.imread(str(icon_mask_path), cv2.IMREAD_GRAYSCALE)
        if local_mask is None:
            continue
        right, bottom = min(width, x + w), min(height, y + h)
        target_width, target_height = max(0, right - x), max(0, bottom - y)
        if target_width == 0 or target_height == 0:
            continue
        if local_mask.shape[1] != target_width or local_mask.shape[0] != target_height:
            local_mask = cv2.resize(local_mask, (target_width, target_height), interpolation=cv2.INTER_NEAREST)
        mask[y:bottom, x:right] = cv2.bitwise_or(mask[y:bottom, x:right], local_mask)

    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    has_reviewed_text = any(item.get("native_rebuild") for item in analysis.get("texts", []))
    # Large reviewed text regions need a wider local reconstruction radius;
    # the legacy radius leaves dark glyph shadows/halos in the background.
    inpaint_radius = max(3, int(round(height / 220)))
    if has_reviewed_text:
        inpaint_radius = max(inpaint_radius, 14)
    cleaned = cv2.inpaint(image, mask, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_TELEA)
    output.parent.mkdir(parents=True, exist_ok=True)
    mask_output.parent.mkdir(parents=True, exist_ok=True)
    if line_mask_dir:
        line_mask_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), cleaned)
    cv2.imwrite(str(mask_output), mask)
    line_cleanup_evidence: list[dict[str, Any]] = []
    for item, local_mask, cleanup_path in line_cleanup:
        if cleanup_path is not None:
            cv2.imwrite(str(cleanup_path), local_mask)
        source_support = _line_color_support(image, local_mask, item.get("line"))
        post_cleanup_support = _line_color_support(cleaned, local_mask, item.get("line"))
        residual_ratio = (
            post_cleanup_support / source_support if source_support > 0.01 else 1.0
        )
        status = (
            "pass"
            if source_support > 0.01
            and post_cleanup_support <= 0.12
            and residual_ratio <= 0.35
            else "fail"
        )
        evidence = {
            "status": status,
            "method": "opencv-telea-native-line-cleanup",
            "cleanup_mask": str(cleanup_path.resolve()) if cleanup_path else None,
            "line_color": item.get("line"),
            "source_support": round(source_support, 6),
            "post_cleanup_support": round(post_cleanup_support, 6),
            "residual_ratio": round(residual_ratio, 6),
        }
        item["editability_level"] = "native"
        item["role"] = "connector" if item.get("type") == "connector" else "divider"
        item["background_cleanup"] = "line-inpaint"
        item["requires_background_cleanup"] = True
        if cleanup_path is not None:
            item["cleanup_mask"] = str(cleanup_path.resolve())
        item["cleanup_evidence"] = evidence
        line_cleanup_evidence.append({"id": item.get("id"), **evidence})
    return {
        "masked_pixel_ratio": round(float(np.count_nonzero(mask)) / float(mask.size), 5),
        "method": "opencv-telea-post-imagegen-decomposition",
        "line_cleanup": line_cleanup_evidence,
        "line_cleanup_failures": sum(
            1 for item in line_cleanup_evidence if item.get("status") != "pass"
        ),
    }


def _node_executable() -> str:
    candidate = shutil.which("node")
    if candidate:
        return candidate
    bundled = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
    if bundled.exists():
        return str(bundled)
    raise RuntimeError("Node.js is unavailable")


def _node_modules() -> Path:
    configured = os.environ.get("NODE_PATH")
    if configured:
        first = Path(configured.split(os.pathsep)[0])
        if first.exists():
            return first
    bundled = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "node_modules"
    if bundled.exists():
        return bundled
    raise RuntimeError("bundled Node.js modules are unavailable")


def _compose(deck_path: Path, output_path: Path, report_path: Path) -> None:
    environment = os.environ.copy()
    environment["NODE_PATH"] = str(_node_modules())
    command = [
        _node_executable(),
        str(SCRIPT_DIR / "compose_editable_pptx.mjs"),
        str(deck_path),
        str(output_path),
        "--report",
        str(report_path),
    ]
    subprocess.run(command, check=True, env=environment)


def _powerpoint_convert(input_path: Path, output_path: Path, report_path: Path) -> None:
    script = SCRIPT_DIR / "convert_svg_to_shapes.ps1"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-InputPptx",
        str(input_path),
        "-OutputPptx",
        str(output_path),
        "-ReportPath",
        str(report_path),
    ]
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("run_dir")
    parser.add_argument("--imagegen-manifest")
    parser.add_argument("--slide-manifest", help="Reviewed content manifest; text remains the source of truth.")
    parser.add_argument("--slide-id", help="Select one slide from a multi-slide Slide Manifest.")
    parser.add_argument("--allow-unverified-imagegen", action="store_true")
    parser.add_argument("--overrides")
    parser.add_argument("--analysis-json", help="Reuse a reviewed analysis JSON and skip OCR/detection.")
    parser.add_argument("--languages", default="ch_sim,en")
    parser.add_argument("--min-ocr-confidence", type=float, default=0.35)
    parser.add_argument("--max-shapes", type=int, default=64)
    parser.add_argument("--max-lines", type=int, default=32)
    parser.add_argument("--max-icons", type=int, default=16)
    parser.add_argument("--max-svg-paths", type=int, default=28)
    parser.add_argument("--no-compose", action="store_true")
    parser.add_argument("--convert-svg-to-shapes", action="store_true")
    parser.add_argument(
        "--visual-first-text-only",
        action="store_true",
        help="Preserve ImageGen geometry/artwork in the continuous background and rebuild only reviewed text.",
    )
    parser.add_argument("--force-16x9", action="store_true")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    run_dir = Path(args.run_dir).resolve()
    if not source.exists():
        parser.error(f"source image not found: {source}")
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ("source", "analysis", "assets", "assets/icons", "out", "qa"):
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    source_copy = run_dir / "source" / source.name
    if source_copy.resolve() != source:
        shutil.copy2(source, source_copy)

    manifest_path = Path(args.imagegen_manifest).resolve() if args.imagegen_manifest else None
    slide_manifest_path = Path(args.slide_manifest).resolve() if args.slide_manifest else None
    slide_manifest = None
    if slide_manifest_path:
        if not slide_manifest_path.exists():
            parser.error(f"slide manifest not found: {slide_manifest_path}")
        slide_manifest = json.loads(slide_manifest_path.read_text(encoding="utf-8"))
    provenance_verified, provenance_warning = _verify_imagegen_manifest(manifest_path, source)
    if not provenance_verified and not args.allow_unverified_imagegen:
        parser.error(f"imagegen-first gate failed: {provenance_warning}; pass --allow-unverified-imagegen only for analysis drafts")

    if args.analysis_json:
        analysis = json.loads(Path(args.analysis_json).resolve().read_text(encoding="utf-8"))
        analysis["source"] = str(source_copy.resolve())
    else:
        analysis = analyze_image(
            source_copy,
            languages=[value.strip() for value in args.languages.split(",") if value.strip()],
            min_ocr_confidence=args.min_ocr_confidence,
            max_shapes=args.max_shapes,
            max_lines=args.max_lines,
            max_icons=args.max_icons,
        )
    selected_slide_id = str(args.slide_id or (slide_manifest or {}).get("slide_id") or source.stem)
    analysis["slide_id"] = selected_slide_id
    manifest_text = _manifest_exact_text(manifest_path, selected_slide_id)
    manifest_text.extend(_slide_manifest_exact_text(slide_manifest, selected_slide_id))
    _reconcile_ocr_with_manifest(analysis, list(dict.fromkeys(manifest_text)))
    analysis = _apply_overrides(analysis, Path(args.overrides).resolve() if args.overrides else None)
    if args.visual_first_text_only:
        analysis = _apply_visual_first_text_only(analysis)
    width = int(analysis["size"]["width"])
    height = int(analysis["size"]["height"])
    selected_texts, embedded_texts = _select_texts(analysis, height)
    selected_lines = [
        item for item in analysis["lines"]
        if item.get("type") == "connector"
        or (float(item.get("rank_score", 0.0)) >= 0.12 and float(item.get("length", 0.0)) >= width * 0.14)
    ][:16]
    analysis_path = run_dir / "analysis" / "analysis.json"
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Stable semantic bridge for the hybrid Composer.  This is intentionally
    # emitted alongside the legacy deck.json rather than replacing it, so old
    # runs remain reproducible while new runs gain content provenance and
    # explicit Object Router decisions.
    slide_id = selected_slide_id
    component_manifest = build_component_manifest(
        analysis,
        slide_id=slide_id,
        slide_manifest=slide_manifest,
        source_image=str(source_copy.resolve()),
    )
    component_manifest_path = run_dir / "component_manifest.json"
    component_manifest_path.write_text(
        json.dumps(component_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    draw_overlay(source_copy, analysis, run_dir / "analysis" / "detection-overlay.png")

    icon_assets: list[dict[str, Any]] = []
    trace_reports: list[dict[str, Any]] = []
    accepted_icon_ids: set[str] = set()
    accepted_icon_masks: dict[str, Path] = {}
    for item in analysis["icon_candidates"]:
        if not item.get("traceable", True):
            continue
        svg_path = run_dir / "assets" / "icons" / f"{item['id']}.svg"
        icon_mask_path = run_dir / "analysis" / "icon-masks" / f"{item['id']}.png"
        report = trace_icon(
            source_copy,
            svg_path,
            bbox=item["bbox"],
            max_paths=args.max_svg_paths,
            mask_output=icon_mask_path,
        )
        report["id"] = item["id"]
        item["accepted"] = bool(report.get("accepted"))
        trace_reports.append(report)
        analysis["unresolved"] = [
            unresolved for unresolved in analysis.get("unresolved", [])
            if not (unresolved.get("kind") == "icon" and unresolved.get("id") == item["id"])
        ]
        if not report["accepted"]:
            analysis["unresolved"].append({
                "id": item["id"],
                "kind": "icon",
                "reason": ",".join(report["rejection_reasons"]) or "trace-rejected",
            })
            continue
        accepted_icon_ids.add(item["id"])
        accepted_icon_masks[item["id"]] = icon_mask_path
        x, y, icon_width, icon_height = report["source_bbox"]
        icon_assets.append({
            "id": item["id"],
            "file": str(svg_path.relative_to(run_dir)).replace("\\", "/"),
            "asset_type": "svg",
            "editability_level": "convertible-vector",
            "convert_to_shape": True,
            "name": f"vector-svg::{item['id']}",
            "component_id": f"{slide_id}::{item['id']}",
            "x": x,
            "y": y,
            "w": icon_width,
            "h": icon_height,
            "source_bbox": [x, y, icon_width, icon_height],
        })

    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Refresh after icon tracing so rejected vectors are routed to raster_asset
    # instead of being advertised as editable SVG groups.
    component_manifest = build_component_manifest(
        analysis,
        slide_id=slide_id,
        slide_manifest=slide_manifest,
        source_image=str(source_copy.resolve()),
    )
    component_manifest_path.write_text(
        json.dumps(component_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    background_path = run_dir / "assets" / "background.png"
    render_analysis = dict(analysis)
    render_analysis["texts"] = selected_texts
    render_analysis["lines"] = selected_lines
    inpaint_report = _inpaint_background(
        source_copy,
        render_analysis,
        accepted_icon_masks,
        background_path,
        run_dir / "analysis" / "reconstruction-mask.png",
        run_dir / "analysis" / "line-cleanup-masks",
    )
    for item in selected_lines:
        if item.get("cleanup_evidence", {}).get("status") == "pass":
            continue
        analysis.setdefault("unresolved", []).append({
            "id": item.get("id"),
            "kind": "native-line-cleanup",
            "reason": "background line cleanup evidence did not meet the Gold threshold",
        })

    slide_width = 13.333333
    slide_height = 7.5 if args.force_16x9 else round(slide_width / (width / float(height)), 6)
    shapes: list[dict[str, Any]] = []
    for item in analysis["shapes"]:
        shape = dict(item)
        shape["component_id"] = f"{slide_id}::{item.get('id')}"
        shape.update({"x": item["bbox"][0], "y": item["bbox"][1], "w": item["bbox"][2], "h": item["bbox"][3]})
        shapes.append(shape)
    for item in selected_lines:
        line = dict(item)
        line["component_id"] = f"{slide_id}::{item.get('id')}"
        line.update({"x": item["bbox"][0], "y": item["bbox"][1], "w": item["bbox"][2], "h": item["bbox"][3]})
        shapes.append(line)
    texts: list[dict[str, Any]] = []
    source_image = cv2.imread(str(source_copy), cv2.IMREAD_COLOR)
    for item in selected_texts:
        text_item = _composition_text_item(item, width, height, source_image)
        text_item["component_id"] = f"{slide_id}::{item.get('id')}"
        texts.append(text_item)
    _mark_intentional_source_overlaps(texts, icon_assets)

    text_items_with_content = [item for item in texts if str(item.get("text", "")).strip() or item.get("runs")]
    bold_count = sum(1 for item in text_items_with_content if bool(item.get("bold")))
    allow_all_bold = len(text_items_with_content) >= 6 and bold_count / len(text_items_with_content) > 0.85
    slide_qa_note = None
    if allow_all_bold:
        slide_qa_note = "Bold text ratio preserved from the reviewed imagegen source analysis."

    deck = {
        "title": f"Editable reconstruction - {source.stem}",
        "author": "autopptskills",
        "units": "pixel",
        "ref_width": width,
        "ref_height": height,
        "slide_width_in": slide_width,
        "slide_height_in": slide_height,
        "assets_dir": str(run_dir),
        "component_manifest": "component_manifest.json",
        "slides": [{
            "source_imagegen_master": str(source_copy.relative_to(run_dir)).replace("\\", "/"),
            "background": str(background_path.relative_to(run_dir)).replace("\\", "/"),
            "allow_all_bold_text": allow_all_bold,
            "qa_note": slide_qa_note,
            "shapes": shapes,
            "icons": icon_assets,
            "texts": texts,
        }],
    }
    deck_path = run_dir / "deck.json"
    deck_path.write_text(json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    assets_manifest = {
        "policy": "imagegen-full-slide-first-then-semantic-reconstruction",
        "imagegen_required": True,
        "provenance_verified": provenance_verified,
        "provenance_warning": provenance_warning,
        "imagegen_manifest": str(manifest_path) if manifest_path else None,
        "slide_manifest": str(slide_manifest_path) if slide_manifest_path else None,
        "component_manifest": str(component_manifest_path.resolve()),
        "master": {
            "path": str(source_copy.resolve()),
            "original_path": str(source),
            "provenance_type": "imagegen-full-slide-master",
        },
        "derived_assets": [
            {
                "path": str(background_path.resolve()),
                "role": "clean-background",
                "derivation": "post-imagegen semantic removal and inpainting",
                "editability_level": "background-picture",
            },
            *[
                {
                    "path": str((run_dir / item["file"]).resolve()),
                    "role": "flat-icon-vector",
                    "source_bbox": item["source_bbox"],
                    "editability_level": "convertible-vector",
                }
                for item in icon_assets
            ],
        ],
        "semantic_cleanup": {
            "combined_mask": str((run_dir / "analysis" / "reconstruction-mask.png").resolve()),
            "native_lines": [
                {
                    "id": item.get("id"),
                    "type": item.get("type"),
                    "source_bbox": item.get("source_bbox") or item.get("bbox"),
                    "cleanup_mask": item.get("cleanup_mask"),
                    "cleanup_evidence": item.get("cleanup_evidence"),
                }
                for item in selected_lines
            ],
        },
    }
    (run_dir / "imagegen-assets-manifest.json").write_text(
        json.dumps(assets_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    unique_unresolved: list[dict[str, Any]] = []
    unresolved_keys: set[tuple[str, str, str]] = set()
    for item in analysis["unresolved"]:
        if item.get("kind") == "text" and not any(text["id"] == item.get("id") for text in selected_texts):
            continue
        key = (str(item.get("id", "")), str(item.get("kind", "")), str(item.get("reason", "")))
        if key not in unresolved_keys:
            unresolved_keys.add(key)
            unique_unresolved.append(item)
    analysis["unresolved"] = unique_unresolved
    has_text_review = any(item.get("kind") == "text" for item in unique_unresolved)
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    reconstruction_report = {
        "source": str(source),
        "run_dir": str(run_dir),
        "provenance_verified": provenance_verified,
        "counts": {
            "editable_texts": len(texts),
            "native_shapes": len(analysis["shapes"]),
            "native_connectors": len(selected_lines),
            "convertible_vectors": len(icon_assets),
            "unresolved": len(unique_unresolved),
            "unselected_line_candidates": max(0, len(analysis["lines"]) - len(selected_lines)),
            "embedded_text_candidates": len(embedded_texts),
            "component_manifest_objects": len(component_manifest.get("objects", [])),
        },
        "component_manifest": str(component_manifest_path.resolve()),
        "component_manifest_qa": validate_component_manifest(component_manifest),
        "inpaint": inpaint_report,
        "trace_reports": trace_reports,
        "unresolved": unique_unresolved,
        "embedded_text_candidates": [
            {"id": item["id"], "text": item.get("text", ""), "reason": "retained-in-complex-raster"}
            for item in embedded_texts
        ],
        "claim": (
            "automatic-draft-needs-text-review"
            if has_text_review
            else ("automatic-mixed-pass-with-unresolved-assets" if unique_unresolved else "automatic-structural-pass")
        ),
    }
    component_manifest_qa = validate_component_manifest(component_manifest)
    (run_dir / "qa" / "component-manifest-qa.json").write_text(
        json.dumps(component_manifest_qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_path = run_dir / "qa" / "reconstruction-report.json"
    report_path.write_text(json.dumps(reconstruction_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.no_compose:
        editable_pptx = run_dir / "out" / "editable.pptx"
        _compose(deck_path, editable_pptx, run_dir / "qa" / "compose-report.json")
        if args.convert_svg_to_shapes:
            postprocessed_pptx = run_dir / "out" / "editable-vector-postprocessed.pptx"
            _powerpoint_convert(editable_pptx, postprocessed_pptx, run_dir / "qa" / "svg-conversion-report.json")

    print(json.dumps(reconstruction_report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"subprocess failed with exit code {exc.returncode}: {exc.cmd}", file=sys.stderr)
        raise
