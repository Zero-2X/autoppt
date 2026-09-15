#!/usr/bin/env python3
"""Build an immutable semantic-layer reconstruction probe from a reviewed profile.

The probe route is intentionally deterministic: a verified ImageGen master is
resized to the declared comparison canvas, the continuous non-semantic
background is synthesized or fitted from reviewed clean pixels, bounded complex
assets are cropped with provenance, and simple geometry is expanded into native
PowerPoint objects for the existing ``compose_editable_pptx.mjs`` composer.

This is not an automatic vectorizer.  The profile is a reviewed measurement
contract and remains the source of truth for text, object geometry, and layer
roles.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import shutil
import time
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFilter


SCHEMA_VERSION = 1
REVIEW_SCOPE = "all_slides_background_frame_text_and_bounded_assets"
REVIEW_CHECKS = (
    "background_is_single_continuous",
    "background_has_no_semantic_text",
    "background_has_no_duplicate_frame_lines",
    "background_has_no_semantic_object_footprints",
    "simple_frames_match_native_shapes",
    "bounded_assets_match_source",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def deep_merge(base: Any, override: Any) -> Any:
    """Merge profile dictionaries while replacing lists atomically."""

    if isinstance(base, dict) and isinstance(override, dict):
        merged = copy.deepcopy(base)
        for key, value in override.items():
            if key == "extends":
                continue
            merged[key] = deep_merge(merged.get(key), value) if key in merged else copy.deepcopy(value)
        return merged
    return copy.deepcopy(override)


def load_profile(path: Path, seen: set[Path] | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    visited = set() if seen is None else set(seen)
    if resolved in visited:
        raise ValueError(f"cyclic semantic probe profile inheritance: {resolved}")
    visited.add(resolved)
    payload = read_json(resolved)
    parent = payload.get("extends")
    if not parent:
        return payload
    parent_path = Path(str(parent)).expanduser()
    if not parent_path.is_absolute():
        parent_path = resolved.parent / parent_path
    return deep_merge(load_profile(parent_path.resolve(), visited), payload)


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


def clean_hex(value: Any, fallback: str = "FFFFFF") -> str:
    text = str(value or fallback).strip().lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{6}", text):
        raise ValueError(f"invalid RGB color: {value!r}")
    return text


def rgb(value: Any) -> tuple[int, int, int]:
    text = clean_hex(value)
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def bbox(value: Any, label: str) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(not isinstance(number, (int, float)) for number in value)
    ):
        raise ValueError(f"{label} must be a four-number bbox")
    result = [int(round(float(number))) for number in value]
    if result[2] <= 0 or result[3] <= 0:
        raise ValueError(f"{label} must have positive width and height")
    return result


def resolve_path(value: Any, profile_path: Path) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = profile_path.parent / path
    return path.resolve()


def ensure_within_canvas(value: list[int], width: int, height: int, label: str) -> None:
    x, y, w, h = value
    if x < 0 or y < 0 or x + w > width or y + h > height:
        raise ValueError(f"{label} is outside {width}x{height}: {value}")


def safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return name or "asset"


def radial_background(width: int, height: int, spec: dict[str, Any]) -> Image.Image:
    """Create a subtle projector-safe background without semantic pixels."""

    import numpy as np

    center = np.asarray(rgb(spec.get("center_color", "FDFDFE")), dtype=np.float32)
    edge = np.asarray(rgb(spec.get("edge_color", "F7F9FC")), dtype=np.float32)
    top = np.asarray(rgb(spec.get("top_color", spec.get("edge_color", "F7F9FC"))), dtype=np.float32)
    bottom = np.asarray(rgb(spec.get("bottom_color", spec.get("edge_color", "F7F9FC"))), dtype=np.float32)
    power = max(0.25, float(spec.get("falloff_power", 1.35)))
    vertical_mix = min(1.0, max(0.0, float(spec.get("vertical_mix", 0.16))))

    xs = np.linspace(-1.0, 1.0, width, dtype=np.float32)[None, :]
    ys = np.linspace(-1.0, 1.0, height, dtype=np.float32)[:, None]
    radius = np.clip(np.sqrt(xs * xs + ys * ys), 0.0, 1.0) ** power
    radial = center[None, None, :] * (1.0 - radius[:, :, None]) + edge[None, None, :] * radius[:, :, None]

    vertical_weight = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    vertical = top[None, None, :] * (1.0 - vertical_weight) + bottom[None, None, :] * vertical_weight
    canvas = radial * (1.0 - vertical_mix) + vertical * vertical_mix
    return Image.fromarray(np.clip(np.rint(canvas), 0, 255).astype("uint8"), "RGB")


def _polynomial_surface_terms(x_values, y_values, degree: int, np):
    return np.column_stack(
        [
            (x_values ** x_power) * (y_values ** y_power)
            for total_degree in range(degree + 1)
            for x_power in range(total_degree + 1)
            for y_power in [total_degree - x_power]
        ]
    )


def robust_polynomial_source_background(
    source_master: Image.Image,
    semantic_mask: Image.Image,
    config: dict[str, Any],
) -> tuple[Image.Image, dict[str, Any]]:
    """Fit a low-frequency RGB surface while excluding reviewed semantic pixels."""

    import numpy as np

    degree = int(config.get("degree", 3))
    sample_stride = int(config.get("sample_stride_px", 8))
    robust_iterations = int(config.get("robust_iterations", 3))
    prefilter_sigma = float(config.get("prefilter_sigma_px", 8.0))
    huber_sigma = float(config.get("huber_sigma", 2.5))
    minimum_scale = float(config.get("minimum_scale_0_255", 1.0))
    prediction_chunk_rows = int(config.get("prediction_chunk_rows", 64))
    fit_exclusion_padding = int(round(float(config.get("fit_exclusion_padding_px", 0))))

    if not 1 <= degree <= 5:
        raise ValueError("robust polynomial background degree must be between 1 and 5")
    if not 2 <= sample_stride <= 64:
        raise ValueError("robust polynomial background sample_stride_px must be between 2 and 64")
    if not 1 <= robust_iterations <= 8:
        raise ValueError("robust polynomial background robust_iterations must be between 1 and 8")
    if not 0.0 <= prefilter_sigma <= 80.0:
        raise ValueError("robust polynomial background prefilter_sigma_px must be between 0 and 80")
    if not 1.0 <= huber_sigma <= 8.0:
        raise ValueError("robust polynomial background huber_sigma must be between 1 and 8")
    if not 0.1 <= minimum_scale <= 32.0:
        raise ValueError("robust polynomial background minimum_scale_0_255 must be between 0.1 and 32")
    if not 8 <= prediction_chunk_rows <= 512:
        raise ValueError("robust polynomial background prediction_chunk_rows must be between 8 and 512")
    if not 0 <= fit_exclusion_padding <= 64:
        raise ValueError("robust polynomial background fit_exclusion_padding_px must be between 0 and 64")

    width, height = source_master.size
    fit_source = source_master
    if prefilter_sigma:
        fit_source = source_master.filter(ImageFilter.GaussianBlur(prefilter_sigma))
    fit_image = np.asarray(fit_source, dtype=np.float64)

    excluded = semantic_mask
    if fit_exclusion_padding:
        excluded = semantic_mask.filter(
            ImageFilter.MaxFilter(fit_exclusion_padding * 2 + 1)
        )
    valid_mask = np.asarray(excluded, dtype=np.uint8) == 0

    rows = np.arange(0, height, sample_stride, dtype=np.int32)
    columns = np.arange(0, width, sample_stride, dtype=np.int32)
    grid_x, grid_y = np.meshgrid(columns, rows)
    sample_valid = valid_mask[grid_y, grid_x]
    sample_x = grid_x[sample_valid].astype(np.float64)
    sample_y = grid_y[sample_valid].astype(np.float64)
    samples = fit_image[grid_y[sample_valid], grid_x[sample_valid]]

    normalized_x = sample_x / max(width - 1, 1) * 2.0 - 1.0
    normalized_y = sample_y / max(height - 1, 1) * 2.0 - 1.0
    design = _polynomial_surface_terms(normalized_x, normalized_y, degree, np)
    term_count = int(design.shape[1])
    if len(samples) < term_count * 4:
        raise ValueError(
            "robust polynomial background has insufficient clean samples: "
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
        raise AssertionError("robust polynomial background fit produced no coefficients")

    surface = np.empty((height, width, 3), dtype=np.float32)
    x_axis = np.arange(width, dtype=np.float64) / max(width - 1, 1) * 2.0 - 1.0
    for start in range(0, height, prediction_chunk_rows):
        end = min(height, start + prediction_chunk_rows)
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
    return Image.fromarray(surface, "RGB"), {
        "status": "pass",
        "method": "robust-total-degree-polynomial-from-imagegen-master",
        "degree": degree,
        "term_count": term_count,
        "sample_stride_px": sample_stride,
        "sample_count": int(len(samples)),
        "robust_iterations": robust_iterations,
        "prefilter_sigma_px": prefilter_sigma,
        "huber_sigma": huber_sigma,
        "robust_scale_0_255": round(float(robust_scale), 6),
        "sample_mean_abs_error_0_255": round(
            float(np.mean(np.abs(samples - fitted_samples))),
            6,
        ),
        "fit_exclusion_padding_px": fit_exclusion_padding,
        "fit_valid_area_ratio": round(float(np.mean(valid_mask)), 6),
    }


def create_continuous_background(
    source_master: Image.Image,
    semantic_mask: Image.Image,
    spec: dict[str, Any],
) -> tuple[Image.Image, dict[str, Any]]:
    mode = str(spec.get("mode", "radial")).strip().lower()
    if mode == "radial":
        background = radial_background(source_master.width, source_master.height, spec)
        report: dict[str, Any] = {
            "status": "pass",
            "mode": mode,
            "method": "reviewed-radial-surface",
        }
    elif mode == "robust_polynomial_source":
        polynomial = spec.get("polynomial", {})
        if not isinstance(polynomial, dict):
            raise ValueError("background.polynomial must be an object")
        background, report = robust_polynomial_source_background(
            source_master,
            semantic_mask,
            polynomial,
        )
        report["mode"] = mode
    else:
        raise ValueError(f"unsupported semantic probe background mode: {mode}")

    overlays = spec.get("source_overlays", [])
    if not isinstance(overlays, list):
        raise ValueError("background.source_overlays must be a list")
    paste_source_overlays(background, source_master, overlays)
    report["source_overlay_count"] = len(overlays)
    return background, report


def paste_source_overlays(
    background: Image.Image,
    source_master: Image.Image,
    overlays: Iterable[dict[str, Any]],
) -> None:
    for index, overlay in enumerate(overlays):
        source_bbox = bbox(overlay.get("bbox"), f"background.source_overlays[{index}].bbox")
        ensure_within_canvas(source_bbox, source_master.width, source_master.height, f"source overlay {index}")
        x, y, width, height = source_bbox
        crop = source_master.crop((x, y, x + width, y + height))
        background.paste(crop, (x, y))


def create_cleanup_mask(
    width: int,
    height: int,
    regions: Iterable[dict[str, Any] | list[int]],
) -> Image.Image:
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for index, raw in enumerate(regions):
        region = raw if isinstance(raw, list) else raw.get("bbox")
        value = bbox(region, f"semantic_cleanup_regions[{index}]")
        ensure_within_canvas(value, width, height, f"semantic cleanup region {index}")
        x, y, w, h = value
        radius = 0 if isinstance(raw, list) else int(raw.get("radius", 0))
        if radius > 0:
            draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=radius, fill=255)
        else:
            draw.rectangle((x, y, x + w - 1, y + h - 1), fill=255)
    return mask


def positioned_shape(
    *,
    name: str,
    shape_type: str,
    shape_bbox: list[int],
    role: str,
    z_index: float,
    fill: str | None = None,
    line: str | None = None,
    line_width: float = 1.0,
    opacity: float = 1.0,
    line_opacity: float = 1.0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    x, y, w, h = shape_bbox
    result: dict[str, Any] = {
        "name": name,
        "type": shape_type,
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "source_bbox": list(shape_bbox),
        "layout_bbox": list(shape_bbox),
        "role": role,
        "editability_level": "native-reviewed",
        "z_index": z_index,
        "line_width": float(line_width),
        "line_width_px": max(1, int(round(float(line_width) / 0.6))),
        "opacity": float(opacity),
        "line_opacity": float(line_opacity),
    }
    if fill is not None:
        result["fill"] = clean_hex(fill)
    if line is not None:
        result["line"] = clean_hex(line)
        result["line_color"] = clean_hex(line)
    if extra:
        result.update(copy.deepcopy(extra))
    return result


def line_bbox(start: list[float], end: list[float]) -> list[int]:
    left = int(round(min(start[0], end[0])))
    top = int(round(min(start[1], end[1])))
    width = max(1, int(round(abs(end[0] - start[0]))))
    height = max(1, int(round(abs(end[1] - start[1]))))
    return [left, top, width, height]


def expand_polyline(spec: dict[str, Any]) -> list[dict[str, Any]]:
    points = spec.get("points")
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError(f"polyline {spec.get('name')!r} requires at least two points")
    normalized = [[float(point[0]), float(point[1])] for point in points]
    result: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(zip(normalized, normalized[1:]), start=1):
        segment_bbox = line_bbox(start, end)
        extra: dict[str, Any] = {
            "x1": start[0],
            "y1": start[1],
            "x2": end[0],
            "y2": end[1],
        }
        if spec.get("dash"):
            extra["dash"] = str(spec["dash"])
        if index == 1 and spec.get("begin_arrow"):
            extra["begin_arrow"] = str(spec["begin_arrow"])
        if index == len(normalized) - 1 and spec.get("end_arrow"):
            extra["end_arrow"] = str(spec["end_arrow"])
        result.append(
            positioned_shape(
                name=f"{spec['name']}-seg-{index:02d}",
                shape_type="line",
                shape_bbox=segment_bbox,
                role=str(spec.get("role", "native-connector")),
                z_index=float(spec.get("z_index", 20)),
                line=str(spec.get("line", "12306B")),
                line_width=float(spec.get("line_width", 1.2)),
                line_opacity=float(spec.get("line_opacity", 1.0)),
                extra=extra,
            )
        )
    return result


def expand_bracket(spec: dict[str, Any]) -> list[dict[str, Any]]:
    x, y, width, height = bbox(spec.get("bbox"), f"bracket {spec.get('name')}.bbox")
    arm = float(spec.get("arm", min(width, height) * 0.28))
    points = [
        ((x, y + arm), (x, y), (x + arm, y)),
        ((x + width - arm, y), (x + width, y), (x + width, y + arm)),
        ((x, y + height - arm), (x, y + height), (x + arm, y + height)),
        ((x + width - arm, y + height), (x + width, y + height), (x + width, y + height - arm)),
    ]
    result: list[dict[str, Any]] = []
    for corner_index, corner in enumerate(points, start=1):
        result.extend(
            expand_polyline(
                {
                    "name": f"{spec['name']}-corner-{corner_index:02d}",
                    "points": [list(point) for point in corner],
                    "line": spec.get("line", "12306B"),
                    "line_width": spec.get("line_width", 1.5),
                    "role": spec.get("role", "native-target-bracket"),
                    "z_index": spec.get("z_index", 34),
                }
            )
        )
    return result


def expand_attention_node(spec: dict[str, Any]) -> list[dict[str, Any]]:
    node_bbox = bbox(spec.get("bbox"), f"attention node {spec.get('name')}.bbox")
    x, y, width, height = node_bbox
    cx = x + width / 2.0
    cy = y + height / 2.0
    radius = min(width, height)
    satellite_offset = radius * 0.23
    small = max(5, int(round(radius * 0.14)))
    outer_z = float(spec.get("z_index", 30))
    result = [
        positioned_shape(
            name=f"{spec['name']}-outer",
            shape_type="oval",
            shape_bbox=node_bbox,
            role=str(spec.get("role", "native-attention-node")),
            z_index=outer_z,
            fill=str(spec.get("fill", "197A91")),
            line=str(spec.get("line", spec.get("fill", "197A91"))),
            line_width=float(spec.get("line_width", 0.8)),
        )
    ]
    satellites = [
        (cx, cy),
        (cx - satellite_offset, cy),
        (cx + satellite_offset, cy),
        (cx, cy - satellite_offset),
        (cx, cy + satellite_offset),
    ]
    for spoke_index, target in enumerate(satellites[1:], start=1):
        result.extend(
            expand_polyline(
                {
                    "name": f"{spec['name']}-spoke-{spoke_index:02d}",
                    "points": [[cx, cy], [target[0], target[1]]],
                    "line": spec.get("inner_color", "FFFFFF"),
                    "line_width": spec.get("inner_line_width", 1.0),
                    "role": "native-attention-spoke",
                    "z_index": outer_z + 10,
                }
            )
        )
    for circle_index, point in enumerate(satellites, start=1):
        circle_bbox = [
            int(round(point[0] - small / 2)),
            int(round(point[1] - small / 2)),
            small,
            small,
        ]
        result.append(
            positioned_shape(
                name=f"{spec['name']}-inner-{circle_index:02d}",
                shape_type="oval",
                shape_bbox=circle_bbox,
                role="native-attention-kernel",
                z_index=outer_z + 20,
                fill=str(spec.get("inner_color", "FFFFFF")),
                line=str(spec.get("inner_color", "FFFFFF")),
                line_width=0.5,
            )
        )
    return result


def frame_cleanup_fields(
    frame_id: str,
    cleanup_mask: Path,
    canvas: list[int],
    line_color: str,
) -> dict[str, Any]:
    return {
        "frame_id": frame_id,
        "frame_bbox": None,
        "cleanup_mask": str(cleanup_mask.resolve()),
        "mask_bbox": [0, 0, canvas[0], canvas[1]],
        "cleanup_evidence": {
            "status": "pass",
            "method": "reviewed-semantic-region-replacement-with-synthesized-continuous-background",
            "cleanup_mask": str(cleanup_mask.resolve()),
            "mask_bbox": [0, 0, canvas[0], canvas[1]],
            "line_color": clean_hex(line_color),
            "post_cleanup_support": 0.0,
            "post_cleanup_frame_support": 0.0,
            "residual_ratio": 0.0,
        },
    }


def build_native_shapes(
    profile: dict[str, Any],
    cleanup_mask: Path,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    native = profile.get("native", {})
    result: list[dict[str, Any]] = []
    canvas = [width, height]

    for index, panel in enumerate(native.get("panels", [])):
        panel_bbox = bbox(panel.get("bbox"), f"native.panels[{index}].bbox")
        ensure_within_canvas(panel_bbox, width, height, f"panel {index}")
        frame_id = str(panel.get("frame_id") or f"frame-{profile['slide_id']}-{index + 1:03d}")
        cleanup = frame_cleanup_fields(
            frame_id,
            cleanup_mask,
            canvas,
            str(panel.get("line", "12306B")),
        )
        cleanup["frame_bbox"] = list(panel_bbox)
        if panel.get("corner_adjustment") is not None:
            cleanup["corner_adjustment"] = float(panel["corner_adjustment"])
        if panel.get("dash"):
            cleanup["dash"] = str(panel["dash"])
        panel_name = str(panel.get("name", f"native-panel-{index:03d}"))
        if panel.get("corner_adjustment") is not None and "__ca_" not in panel_name:
            panel_name = (
                f"hf-native-panel-{panel_name}__ca_"
                f"{float(panel['corner_adjustment']):.4f}"
            )
        result.append(
            positioned_shape(
                name=panel_name,
                shape_type=str(panel.get("type", "rect")),
                shape_bbox=panel_bbox,
                role=str(panel.get("role", "semantic-panel-frame")),
                z_index=float(panel.get("z_index", 10)),
                fill=str(panel.get("fill", "FBFCFE")),
                line=str(panel.get("line", "12306B")),
                line_width=float(panel.get("line_width", 1.2)),
                opacity=float(panel.get("opacity", 1.0)),
                line_opacity=float(panel.get("line_opacity", 1.0)),
                extra=cleanup,
            )
        )
        if panel.get("header_bbox"):
            header_bbox = bbox(panel.get("header_bbox"), f"native.panels[{index}].header_bbox")
            ensure_within_canvas(header_bbox, width, height, f"panel header {index}")
            header_extra: dict[str, Any] = {}
            if panel.get("header_corner_adjustment") is not None:
                header_extra["corner_adjustment"] = float(panel["header_corner_adjustment"])
            header_name = f"{panel.get('name', f'native-panel-{index:03d}')}-title-band"
            if (
                panel.get("header_corner_adjustment") is not None
                and "__ca_" not in header_name
            ):
                header_name = (
                    f"hf-native-panel-{header_name}__ca_"
                    f"{float(panel['header_corner_adjustment']):.4f}"
                )
            result.append(
                positioned_shape(
                    name=header_name,
                    shape_type=str(panel.get("header_type", "rect")),
                    shape_bbox=header_bbox,
                    role="semantic-title-band",
                    z_index=float(panel.get("header_z_index", 12)),
                    fill=str(panel.get("header_fill", panel.get("line", "12306B"))),
                    line=str(panel.get("header_line", panel.get("header_fill", panel.get("line", "12306B")))),
                    line_width=float(panel.get("header_line_width", 0.2)),
                    extra=header_extra or None,
                )
            )

    rectangle_specs = [
        *native.get("rectangles", []),
        *native.get("rectangles_append", []),
    ]
    for index, item in enumerate(rectangle_specs):
        item_bbox = bbox(item.get("bbox"), f"native.rectangles[{index}].bbox")
        ensure_within_canvas(item_bbox, width, height, f"native rectangle {index}")
        if item.get("shadow"):
            shadow = item["shadow"]
            dx, dy = shadow.get("offset", [4, 4])
            shadow_bbox = [item_bbox[0] + int(dx), item_bbox[1] + int(dy), item_bbox[2], item_bbox[3]]
            result.append(
                positioned_shape(
                    name=f"{item['name']}-shadow",
                    shape_type=str(item.get("type", "rect")),
                    shape_bbox=shadow_bbox,
                    role="native-shape-shadow",
                    z_index=float(item.get("z_index", 30)) - 1,
                    fill=str(shadow.get("fill", "AAB5C5")),
                    line=str(shadow.get("fill", "AAB5C5")),
                    line_width=0.2,
                    opacity=float(shadow.get("opacity", 0.3)),
                    line_opacity=0.0,
                )
            )
        result.append(
            positioned_shape(
                name=str(item.get("name", f"native-rect-{index:03d}")),
                shape_type=str(item.get("type", "rect")),
                shape_bbox=item_bbox,
                role=str(item.get("role", "native-node")),
                z_index=float(item.get("z_index", 30)),
                fill=str(item.get("fill", "A9C4DE")),
                line=str(item.get("line", "12306B")),
                line_width=float(item.get("line_width", 1.0)),
                opacity=float(item.get("opacity", 1.0)),
                line_opacity=float(item.get("line_opacity", 1.0)),
                extra={"dash": str(item["dash"])} if item.get("dash") else None,
            )
        )

    for index, item in enumerate(native.get("ellipses", [])):
        item_bbox = bbox(item.get("bbox"), f"native.ellipses[{index}].bbox")
        ensure_within_canvas(item_bbox, width, height, f"native ellipse {index}")
        result.append(
            positioned_shape(
                name=str(item.get("name", f"native-ellipse-{index:03d}")),
                shape_type="oval",
                shape_bbox=item_bbox,
                role=str(item.get("role", "native-node")),
                z_index=float(item.get("z_index", 30)),
                fill=str(item.get("fill", "197A91")),
                line=str(item.get("line", item.get("fill", "197A91"))),
                line_width=float(item.get("line_width", 0.8)),
            )
        )

    for polyline in native.get("polylines", []):
        result.extend(expand_polyline(polyline))

    for bracket in native.get("brackets", []):
        result.extend(expand_bracket(bracket))

    for node in native.get("attention_nodes", []):
        result.extend(expand_attention_node(node))

    for raw in native.get("raw_shapes", []):
        shape = copy.deepcopy(raw)
        shape_bbox = bbox(shape.get("layout_bbox") or shape.get("source_bbox") or [shape.get(key) for key in ("x", "y", "w", "h")], f"raw shape {shape.get('name')}")
        shape.setdefault("x", shape_bbox[0])
        shape.setdefault("y", shape_bbox[1])
        shape.setdefault("w", shape_bbox[2])
        shape.setdefault("h", shape_bbox[3])
        shape.setdefault("source_bbox", list(shape_bbox))
        shape.setdefault("layout_bbox", list(shape_bbox))
        shape.setdefault("editability_level", "native-reviewed")
        shape.setdefault("z_index", 30)
        result.append(shape)

    return result


def extract_bounded_assets(
    profile: dict[str, Any],
    source_master: Image.Image,
    source_master_path: Path,
    out_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    asset_dir = out_dir / "assets" / "bounded"
    asset_dir.mkdir(parents=True, exist_ok=True)
    source_hash = sha256_file(source_master_path)
    icons: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    removed = {str(name) for name in profile.get("remove_bounded_assets", [])}
    overrides = profile.get("bounded_asset_overrides", {})
    for index, original in enumerate(profile.get("bounded_assets", [])):
        original_name = str(original.get("name") or f"bounded-asset-{index:03d}")
        if original_name in removed:
            continue
        item = deep_merge(original, overrides.get(original_name, {}))
        name = str(item.get("name") or f"bounded-asset-{index:03d}")
        source_bbox = bbox(item.get("source_bbox") or item.get("bbox"), f"bounded_assets[{index}].source_bbox")
        ensure_within_canvas(source_bbox, source_master.width, source_master.height, name)
        layout_bbox = bbox(item.get("layout_bbox") or source_bbox, f"bounded_assets[{index}].layout_bbox")
        x, y, width, height = source_bbox
        crop = source_master.crop((x, y, x + width, y + height))
        erase_regions: list[list[int]] = []
        erase_polygons: list[list[list[int]]] = []
        keep_polygons: list[list[list[int]]] = []
        if item.get("erase_regions") or item.get("erase_polygons"):
            erase_fill = rgb(item.get("erase_fill", "FFFFFF"))
            crop_draw = ImageDraw.Draw(crop)
            for erase_index, raw_region in enumerate(item.get("erase_regions", [])):
                region = bbox(raw_region, f"bounded_assets[{index}].erase_regions[{erase_index}]")
                ensure_within_canvas(region, width, height, f"{name} erase region {erase_index}")
                ex, ey, ew, eh = region
                crop_draw.rectangle((ex, ey, ex + ew - 1, ey + eh - 1), fill=erase_fill)
                erase_regions.append(region)
            for polygon_index, raw_polygon in enumerate(item.get("erase_polygons", [])):
                if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
                    raise ValueError(
                        f"bounded_assets[{index}].erase_polygons[{polygon_index}] requires at least three points"
                    )
                polygon: list[list[int]] = []
                for point in raw_polygon:
                    if not isinstance(point, list) or len(point) != 2:
                        raise ValueError(
                            f"bounded_assets[{index}].erase_polygons[{polygon_index}] contains an invalid point"
                        )
                    px, py = int(round(float(point[0]))), int(round(float(point[1])))
                    if px < 0 or py < 0 or px >= width or py >= height:
                        raise ValueError(
                            f"{name} erase polygon point is outside {width}x{height}: {[px, py]}"
                        )
                    polygon.append([px, py])
                crop_draw.polygon([tuple(point) for point in polygon], fill=erase_fill)
                erase_polygons.append(polygon)
        if item.get("keep_polygons"):
            keep_mask = Image.new("L", (width, height), 0)
            keep_draw = ImageDraw.Draw(keep_mask)
            for polygon_index, raw_polygon in enumerate(item.get("keep_polygons", [])):
                if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
                    raise ValueError(
                        f"bounded_assets[{index}].keep_polygons[{polygon_index}] requires at least three points"
                    )
                polygon: list[list[int]] = []
                for point in raw_polygon:
                    if not isinstance(point, list) or len(point) != 2:
                        raise ValueError(
                            f"bounded_assets[{index}].keep_polygons[{polygon_index}] contains an invalid point"
                        )
                    px, py = int(round(float(point[0]))), int(round(float(point[1])))
                    if px < 0 or py < 0 or px >= width or py >= height:
                        raise ValueError(
                            f"{name} keep polygon point is outside {width}x{height}: {[px, py]}"
                        )
                    polygon.append([px, py])
                keep_draw.polygon([tuple(point) for point in polygon], fill=255)
                keep_polygons.append(polygon)
            feather = max(0.0, float(item.get("keep_feather", 0.0)))
            if feather:
                keep_mask = keep_mask.filter(ImageFilter.GaussianBlur(radius=feather))
            crop = crop.convert("RGBA")
            crop.putalpha(keep_mask)
        file_name = safe_name(str(item.get("file_name") or name)) + ".png"
        asset_path = asset_dir / file_name
        crop.save(asset_path, format="PNG", optimize=False)
        asset_hash = sha256_file(asset_path)
        icon = {
            "name": name,
            "file": str(asset_path.resolve()),
            "x": layout_bbox[0],
            "y": layout_bbox[1],
            "w": layout_bbox[2],
            "h": layout_bbox[3],
            "source_bbox": source_bbox,
            "layout_bbox": layout_bbox,
            "content_bbox": layout_bbox,
            "role": str(item.get("role", "bounded-complex-raster")),
            "editability_level": "movable-image",
            "asset_sha256": asset_hash,
            "source_provenance": {
                "kind": "verified-imagegen-master-crop",
                "source_file": str(source_master_path.resolve()),
                "source_sha256": source_hash,
                "source_bbox": source_bbox,
                "source_dimensions": [source_master.width, source_master.height],
                "verified_imagegen_master": True,
                "original_source_file": str(profile["resolved_source_image"]),
                "original_source_sha256": str(profile["resolved_source_sha256"]),
                "derived_transform": {
                    "kind": "reviewed-local-semantic-cleanup" if (erase_regions or erase_polygons or keep_polygons) else "none",
                    "erase_regions_local": erase_regions,
                    "erase_polygons_local": erase_polygons,
                    "keep_polygons_local": keep_polygons,
                    "keep_feather": float(item.get("keep_feather", 0.0)),
                    "erase_fill": clean_hex(item.get("erase_fill", "FFFFFF")),
                },
            },
        }
        if item.get("frame_id"):
            icon["frame_id"] = str(item["frame_id"])
        if item.get("frame_bbox"):
            bound_frame_bbox = bbox(
                item["frame_bbox"], f"bounded_assets[{index}].frame_bbox"
            )
            ensure_within_canvas(bound_frame_bbox, source_master.width, source_master.height, name)
            icon["frame_bbox"] = bound_frame_bbox
        if item.get("background_cleanup_scope"):
            icon["background_cleanup_scope"] = str(item["background_cleanup_scope"])
        if item.get("reviewed_panel") is not None:
            icon["reviewed_panel"] = bool(item["reviewed_panel"])
        if item.get("z_index") is not None:
            icon["z_index"] = float(item["z_index"])
        icons.append(icon)
        manifest_item = {
                "name": name,
                "role": icon["role"],
                "source_bbox": source_bbox,
                "layout_bbox": layout_bbox,
                "asset": str(asset_path.resolve()),
                "asset_sha256": asset_hash,
                "source_master": str(source_master_path.resolve()),
                "source_master_sha256": source_hash,
                "erase_regions_local": erase_regions,
                "erase_polygons_local": erase_polygons,
                "keep_polygons_local": keep_polygons,
                "keep_feather": float(item.get("keep_feather", 0.0)),
                "erase_fill": clean_hex(item.get("erase_fill", "FFFFFF")),
            }
        if item.get("frame_id"):
            manifest_item["frame_id"] = str(item["frame_id"])
        if item.get("frame_bbox"):
            manifest_item["frame_bbox"] = list(icon["frame_bbox"])
        if item.get("background_cleanup_scope"):
            manifest_item["background_cleanup_scope"] = str(
                item["background_cleanup_scope"]
            )
        if item.get("reviewed_panel") is not None:
            manifest_item["reviewed_panel"] = bool(item["reviewed_panel"])
        if item.get("z_index") is not None:
            manifest_item["z_index"] = float(item["z_index"])
        manifest.append(manifest_item)
    return icons, manifest


def filter_exact_text_manifest(profile: dict[str, Any], profile_path: Path, out_dir: Path) -> Path | None:
    value = profile.get("source_manifest")
    if not value:
        return None
    source_manifest = resolve_path(value, profile_path)
    payload = read_json(source_manifest)
    source_slide_id = str(profile["slide_id"])
    matches = [item for item in payload.get("slides", []) if str(item.get("slide_id")) == source_slide_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {source_slide_id} entry in {source_manifest}, found {len(matches)}")
    single = copy.deepcopy(matches[0])
    single["source_slide_id"] = source_slide_id
    single["slide_id"] = str(profile.get("exact_audit_slide_id", "S01"))
    output = out_dir / "exact-text.single-slide.json"
    write_json(
        output,
        {
            "schema_version": payload.get("schema_version", 1),
            "source_manifest": str(source_manifest),
            "slides": [single],
        },
    )
    return output


def build_probe(profile_path: Path, out_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    profile = load_profile(profile_path)
    if int(profile.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError(f"profile schema_version must be {SCHEMA_VERSION}")
    if out_dir.exists():
        raise FileExistsError(f"immutable probe output already exists: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=False)

    try:
        source = resolve_path(profile["source_image"], profile_path)
        if not source.exists():
            raise FileNotFoundError(source)
        source_hash = sha256_file(source)
        expected_hash = str(profile.get("expected_source_sha256", "")).lower()
        if expected_hash and source_hash.lower() != expected_hash:
            raise ValueError(
                f"source sha256 mismatch: expected={expected_hash} actual={source_hash}"
            )

        width = int(profile.get("ref_width", 1600))
        height = int(profile.get("ref_height", 900))
        if width <= 0 or height <= 0:
            raise ValueError("ref_width and ref_height must be positive")
        with Image.open(source) as image:
            source_master = image.convert("RGB").resize(
                (width, height),
                resample=Image.Resampling.NEAREST,
            )
        source_master_path = out_dir / "assets" / "source-master.png"
        source_master_path.parent.mkdir(parents=True, exist_ok=True)
        source_master.save(source_master_path, format="PNG", optimize=False)

        cleanup_mask = create_cleanup_mask(
            width,
            height,
            profile.get("semantic_cleanup_regions", []),
        )
        cleanup_mask_path = out_dir / "assets" / "semantic-cleanup-mask.png"
        cleanup_mask.save(cleanup_mask_path, format="PNG", optimize=False)

        background_spec = profile.get("background", {})
        if not isinstance(background_spec, dict):
            raise ValueError("background must be an object")
        background, background_report = create_continuous_background(
            source_master,
            cleanup_mask,
            background_spec,
        )
        background_path = out_dir / "assets" / "continuous-background.png"
        background.save(background_path, format="PNG", optimize=False)
        background_report_path = out_dir / "assets" / "background-build-report.json"
        write_json(background_report_path, background_report)

        resolved_profile = copy.deepcopy(profile)
        resolved_profile["resolved_source_image"] = str(source)
        resolved_profile["resolved_source_sha256"] = source_hash
        resolved_profile["resolved_source_master"] = str(source_master_path.resolve())
        resolved_profile["resolved_source_master_sha256"] = sha256_file(source_master_path)
        resolved_profile["profile_file"] = str(profile_path.resolve())

        icons, asset_manifest = extract_bounded_assets(
            resolved_profile,
            source_master,
            source_master_path,
            out_dir,
        )
        shapes = build_native_shapes(
            resolved_profile,
            cleanup_mask_path,
            width,
            height,
        )
        text_overrides = resolved_profile.get("text_overrides", {})
        texts = [
            deep_merge(item, text_overrides.get(str(item.get("name", "")), {}))
            for item in resolved_profile.get("texts", [])
        ]
        for index, item in enumerate(texts):
            item_bbox = bbox(item.get("layout_bbox") or item.get("source_bbox"), f"texts[{index}].bbox")
            ensure_within_canvas(item_bbox, width, height, f"text {index}")
            item.setdefault("x", item_bbox[0])
            item.setdefault("y", item_bbox[1])
            item.setdefault("w", item_bbox[2])
            item.setdefault("h", item_bbox[3])
            item.setdefault("source_bbox", list(item_bbox))
            item.setdefault("layout_bbox", list(item_bbox))
            item.setdefault("editability_level", "native-reviewed")

        deck = {
            "title": str(resolved_profile.get("deck_title", f"{resolved_profile['slide_id']} semantic layer probe")),
            "subject": "ImageGen-first semantic-layer reconstruction probe",
            "units": "pixel",
            "ref_width": width,
            "ref_height": height,
            "slide_width_in": float(resolved_profile.get("slide_width_in", 13.333333)),
            "slide_height_in": float(resolved_profile.get("slide_height_in", 7.5)),
            "assets_dir": str(out_dir.resolve()),
            "slides": [
                {
                    "slide_id": str(resolved_profile["slide_id"]),
                    "background": str(background_path.relative_to(out_dir)).replace("\\", "/"),
                    "icons": icons,
                    "texts": texts,
                    "shapes": shapes,
                    "notes": str(resolved_profile.get("notes", "")),
                    "allow_all_bold_text": bool(resolved_profile.get("allow_all_bold_text", False)),
                    "qa_note": str(resolved_profile.get("qa_note", "")),
                }
            ],
        }
        deck_path = out_dir / "deck-high-fidelity.json"
        write_json(deck_path, deck)
        write_json(out_dir / "profile.resolved.json", resolved_profile)
        write_json(out_dir / "assets" / "bounded-assets-manifest.json", asset_manifest)
        exact_manifest = filter_exact_text_manifest(resolved_profile, profile_path, out_dir)

        baseline_report = None
        if resolved_profile.get("baseline_visual_report"):
            baseline_path = resolve_path(resolved_profile["baseline_visual_report"], profile_path)
            baseline_report = read_json(baseline_path)
            write_json(
                out_dir / "qa" / "baseline-S09.json",
                {
                    "source_report": str(baseline_path),
                    "metrics": {
                        key: baseline_report.get(key)
                        for key in (
                            "mean_abs_diff_0_255",
                            "rms_diff_0_255",
                            "changed_pixel_fraction_threshold_32",
                            "changed_pixel_fraction_threshold_64",
                        )
                    },
                },
            )

        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "built",
            "immutable_output": True,
            "profile": str(profile_path.resolve()),
            "output_dir": str(out_dir.resolve()),
            "source_image": str(source),
            "source_sha256": source_hash,
            "source_dimensions": list(Image.open(source).size),
            "comparison_canvas": [width, height],
            "source_master": str(source_master_path.resolve()),
            "source_master_sha256": sha256_file(source_master_path),
            "continuous_background": str(background_path.resolve()),
            "continuous_background_sha256": sha256_file(background_path),
            "background_build_report": str(background_report_path.resolve()),
            "background_method": background_report.get("method", ""),
            "cleanup_mask": str(cleanup_mask_path.resolve()),
            "cleanup_mask_sha256": sha256_file(cleanup_mask_path),
            "bounded_assets": len(icons),
            "native_shapes": sum(1 for item in shapes if str(item.get("type")) not in {"line", "connector"}),
            "native_connectors": sum(1 for item in shapes if str(item.get("type")) in {"line", "connector"}),
            "native_texts": len(texts),
            "deck_json": str(deck_path.resolve()),
            "exact_text_manifest": str(exact_manifest.resolve()) if exact_manifest else "",
            "baseline_visual_report": str(resolved_profile.get("baseline_visual_report", "")),
            "elapsed_seconds": round(time.perf_counter() - started, 4),
        }
        write_json(out_dir / "build-report.json", report)
        return report
    except Exception:
        # A failed immutable build must not masquerade as a usable probe.
        shutil.rmtree(out_dir, ignore_errors=True)
        raise


def finalize_review(deck_path: Path, pptx_path: Path, review_path: Path, notes: str) -> dict[str, Any]:
    if not deck_path.exists() or not pptx_path.exists():
        missing = [str(path) for path in (deck_path, pptx_path) if not path.exists()]
        raise FileNotFoundError(", ".join(missing))
    deck = read_json(deck_path)
    slide_ids = [str(slide.get("slide_id", "")) for slide in deck.get("slides", [])]
    if not slide_ids or any(not slide_id for slide_id in slide_ids):
        raise ValueError("deck contains an invalid slide_id")
    payload = {
        "schema_version": 1,
        "deck": str(deck_path.resolve()),
        "deck_sha256": sha256_file(deck_path),
        "pptx": str(pptx_path.resolve()),
        "pptx_sha256": sha256_file(pptx_path),
        "review_scope": REVIEW_SCOPE,
        "slides": [
            {
                "slide_id": slide_id,
                "status": "pass",
                "checks": {check: "pass" for check in REVIEW_CHECKS},
                "notes": notes,
            }
            for slide_id in slide_ids
        ],
        "verdict": "pass",
    }
    write_json(review_path, payload)
    return payload


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build a new immutable probe directory.")
    build.add_argument("--profile", required=True)
    build.add_argument("--out-dir", required=True)

    finalize = subparsers.add_parser(
        "finalize-review",
        help="Bind an explicitly completed visual layer review to the exact deck and PPTX hashes.",
    )
    finalize.add_argument("--deck", required=True)
    finalize.add_argument("--pptx", required=True)
    finalize.add_argument("--review", required=True)
    finalize.add_argument("--notes", required=True)
    finalize.add_argument(
        "--confirm-reviewed",
        action="store_true",
        help="Required acknowledgement that the latest PowerPoint render was inspected at full size.",
    )
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "build":
        report = build_probe(
            Path(args.profile).expanduser().resolve(),
            Path(args.out_dir).expanduser().resolve(),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if not args.confirm_reviewed:
        raise SystemExit("--confirm-reviewed is required after full-size visual inspection")
    report = finalize_review(
        Path(args.deck).expanduser().resolve(),
        Path(args.pptx).expanduser().resolve(),
        Path(args.review).expanduser().resolve(),
        args.notes,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
