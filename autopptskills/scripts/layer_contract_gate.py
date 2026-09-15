#!/usr/bin/env python3
"""Validate continuous backgrounds and semantic object-layer separation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PASS = "pass"
FAIL = "fail"
BLOCKED = "blocked"
REVIEW_SCOPE = "all_slides_background_frame_text_and_bounded_assets"
REVIEW_CHECKS = (
    "background_is_single_continuous",
    "background_has_no_semantic_text",
    "background_has_no_duplicate_frame_lines",
    "background_has_no_semantic_object_footprints",
    "simple_frames_match_native_shapes",
    "bounded_assets_match_source",
)
NATIVE_LEVELS = {"native", "native-reviewed"}
BOUNDED_ASSET_LEVELS = {
    "movable-image",
    "convertible-vector",
    "native-vector",
    "native",
}
BACKGROUND_TILE_ROLES = {
    "pixel-anchored-background-tile",
    "background-tile",
    "background_tile",
}
MAX_FRAME_RESIDUAL_SUPPORT = 0.12
MAX_RECORDED_RESIDUAL_RATIO = 0.35
MIN_FRAME_MASK_COVERAGE = 0.55
MIN_REVIEWED_PANEL_FRAME_MASK_COVERAGE = 0.70
MIN_REVIEWED_PANEL_CONTENT_MASK_COVERAGE = 0.98
BBOX_CONTAINMENT_TOLERANCE = 2.0
COMPOUND_LAYER_RANK = {"outer": 0, "middle": 1, "inner": 2}


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


def valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, (int, float)) for number in value)
        and value[2] > 0
        and value[3] > 0
    )


def object_bbox(item: dict[str, Any]) -> list[float] | None:
    candidate = item.get("layout_bbox") or item.get("final_bbox")
    if valid_bbox(candidate):
        return [float(value) for value in candidate]
    fallback = [item.get(key) for key in ("x", "y", "w", "h")]
    if valid_bbox(fallback):
        return [float(value) for value in fallback]
    return None


def bbox_matches(left: list[float], right: list[float]) -> bool:
    tolerances = [3.0, 3.0, max(3.0, left[2] * 0.02), max(3.0, left[3] * 0.02)]
    return all(abs(a - b) <= tolerance for a, b, tolerance in zip(left, right, tolerances))


def bbox_contains(outer: list[float], inner: list[float]) -> bool:
    tolerance = BBOX_CONTAINMENT_TOLERANCE
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[0] + inner[2] <= outer[0] + outer[2] + tolerance
        and inner[1] + inner[3] <= outer[1] + outer[3] + tolerance
    )


def compound_layer(item: dict[str, Any]) -> str:
    explicit = str(item.get("compound_layer") or item.get("layer") or "").lower()
    if explicit:
        return explicit
    role = str(item.get("role", "")).lower()
    return next(
        (layer for layer in COMPOUND_LAYER_RANK if f"compound-{layer}" in role),
        "",
    )


def cleanup_delegate_id(item: dict[str, Any]) -> str:
    return str(item.get("cleanup_delegated_to", "")).strip()


def cleanup_region_bbox(item: dict[str, Any]) -> list[float] | None:
    for candidate in (
        item.get("cleanup_bbox"),
        item.get("source_bbox"),
        item.get("mask_bbox"),
        (item.get("cleanup_evidence") or {}).get("mask_bbox"),
    ):
        if valid_bbox(candidate):
            return [float(value) for value in candidate]
    return None


def resolve_asset(value: Any, deck_path: Path, assets_dir: Path | None = None) -> Path | None:
    if not value:
        return None
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path.resolve()
    candidates = [(deck_path.parent / path).resolve()]
    if assets_dir is not None:
        candidates.append((assets_dir / path).resolve())
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def decode_image(path: Path, mode: str = "RGB") -> tuple[Any, str]:
    """Decode an image fully; a PNG suffix must contain actual PNG bytes."""

    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - production dependency guard
        raise RuntimeError(f"image decode backend unavailable: {exc}") from exc

    with Image.open(path) as image:
        image_format = str(image.format or "").upper()
        if path.suffix.lower() == ".png" and image_format != "PNG":
            raise ValueError(
                f"expected PNG bytes, decoded format={image_format or 'unknown'}"
            )
        image.load()
        pixels = np.asarray(image.convert(mode)).copy()
    return pixels, image_format


def reference_size(deck: dict[str, Any]) -> tuple[float, float] | None:
    width = deck.get("ref_width")
    height = deck.get("ref_height")
    size = deck.get("size") if isinstance(deck.get("size"), dict) else {}
    width = width or size.get("width")
    height = height or size.get("height")
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return None
    if width <= 0 or height <= 0:
        return None
    return float(width), float(height)


def frame_shape(item: dict[str, Any]) -> bool:
    role = str(item.get("role", "")).lower()
    shape_type = str(item.get("type", "")).lower()
    return shape_type in {"rect", "rounded_rect"} and any(
        token in role for token in ("panel", "frame", "card")
    )


def line_shape(item: dict[str, Any]) -> bool:
    role = str(item.get("role", "")).lower()
    shape_type = str(item.get("type", "")).lower()
    return shape_type in {"line", "connector"} or role in {
        "line",
        "connector",
        "divider",
    }


def frame_bbox(item: dict[str, Any]) -> list[float] | None:
    candidate = item.get("frame_bbox")
    if valid_bbox(candidate):
        return [float(value) for value in candidate]
    return object_bbox(item)


def scaled_bbox(
    bbox: list[float],
    image_width: int,
    image_height: int,
    ref_size: tuple[float, float] | None,
) -> tuple[int, int, int, int] | None:
    ref_width, ref_height = ref_size or (float(image_width), float(image_height))
    scale_x = image_width / ref_width
    scale_y = image_height / ref_height
    x, y, width, height = bbox
    left = max(0, min(image_width, int(round(x * scale_x))))
    top = max(0, min(image_height, int(round(y * scale_y))))
    right = max(left, min(image_width, int(round((x + width) * scale_x))))
    bottom = max(top, min(image_height, int(round((y + height) * scale_y))))
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top


def frame_band(
    item: dict[str, Any],
    image_shape: tuple[int, ...],
    ref_size: tuple[float, float] | None,
) -> Any:
    import numpy as np

    image_height, image_width = image_shape[:2]
    bbox = frame_bbox(item)
    if bbox is None:
        return np.zeros((image_height, image_width), dtype=bool)
    mapped = scaled_bbox(bbox, image_width, image_height, ref_size)
    if mapped is None:
        return np.zeros((image_height, image_width), dtype=bool)
    left, top, width, height = mapped
    ref_width, ref_height = ref_size or (float(image_width), float(image_height))
    scale = (image_width / ref_width + image_height / ref_height) / 2.0
    source_width = float(item.get("line_width_px", item.get("line_width", 1.0)))
    half_band = max(2, int(round(max(1.0, source_width * scale) / 2.0)) + 2)
    right = left + width - 1
    bottom = top + height - 1
    mask = np.zeros((image_height, image_width), dtype=bool)
    mask[
        max(0, top - half_band) : min(image_height, top + half_band + 1),
        left : right + 1,
    ] = True
    mask[
        max(0, bottom - half_band) : min(image_height, bottom + half_band + 1),
        left : right + 1,
    ] = True
    mask[
        top : bottom + 1,
        max(0, left - half_band) : min(image_width, left + half_band + 1),
    ] = True
    mask[
        top : bottom + 1,
        max(0, right - half_band) : min(image_width, right + half_band + 1),
    ] = True
    return mask


def line_band(
    item: dict[str, Any],
    image_shape: tuple[int, ...],
    ref_size: tuple[float, float] | None,
) -> Any:
    import numpy as np
    from PIL import Image, ImageDraw

    image_height, image_width = image_shape[:2]
    ref_width, ref_height = ref_size or (float(image_width), float(image_height))
    scale_x = image_width / ref_width
    scale_y = image_height / ref_height
    bbox = object_bbox(item) or frame_bbox(item)
    if bbox is None:
        return np.zeros((image_height, image_width), dtype=bool)
    x, y, width, height = bbox
    start_x = float(item.get("x1", x))
    start_y = float(item.get("y1", y))
    end_x = float(item.get("x2", x + width))
    end_y = float(item.get("y2", y + height))
    start = (int(round(start_x * scale_x)), int(round(start_y * scale_y)))
    end = (int(round(end_x * scale_x)), int(round(end_y * scale_y)))
    source_width = float(item.get("line_width_px", item.get("line_width", 1.0)))
    scale = (scale_x + scale_y) / 2.0
    cleanup_width = max(3, int(round(max(1.0, source_width * scale))) + 4)
    mask_image = Image.new("L", (image_width, image_height), 0)
    draw = ImageDraw.Draw(mask_image)
    draw.line([start, end], fill=255, width=cleanup_width)
    arrow_radius = max(5, cleanup_width * 2)
    for point, arrow in (
        (start, item.get("begin_arrow")),
        (end, item.get("end_arrow")),
    ):
        if arrow:
            draw.ellipse(
                [
                    point[0] - arrow_radius,
                    point[1] - arrow_radius,
                    point[0] + arrow_radius,
                    point[1] + arrow_radius,
                ],
                fill=255,
            )
    return np.asarray(mask_image) > 0


def native_shape_band(
    item: dict[str, Any],
    image_shape: tuple[int, ...],
    ref_size: tuple[float, float] | None,
) -> Any:
    """Approximate the semantic pixels of a reviewed simple native shape."""

    import numpy as np
    from PIL import Image, ImageDraw

    image_height, image_width = image_shape[:2]
    bbox = object_bbox(item) or frame_bbox(item)
    if bbox is None:
        return np.zeros((image_height, image_width), dtype=bool)
    mapped = scaled_bbox(bbox, image_width, image_height, ref_size)
    if mapped is None:
        return np.zeros((image_height, image_width), dtype=bool)
    left, top, width, height = mapped
    right = left + width - 1
    bottom = top + height - 1
    ref_width, ref_height = ref_size or (float(image_width), float(image_height))
    scale = (image_width / ref_width + image_height / ref_height) / 2.0
    source_width = float(item.get("line_width_px", item.get("line_width", 1.0)))
    cleanup_width = max(3, int(round(max(1.0, source_width * scale))) + 4)
    shape_type = str(item.get("type", "")).lower()
    mask_image = Image.new("L", (image_width, image_height), 0)
    draw = ImageDraw.Draw(mask_image)
    if shape_type in {"oval", "ellipse"}:
        if item.get("fill") and float(item.get("opacity", 1.0)) > 0:
            draw.ellipse([left, top, right, bottom], fill=255)
        else:
            draw.ellipse([left, top, right, bottom], outline=255, width=cleanup_width)
    elif shape_type in {"right_arrow", "left_arrow"}:
        shaft_top = int(round(top + height * 0.31))
        shaft_bottom = int(round(top + height * 0.69))
        neck = int(round(left + width * 0.62))
        points = [
            (left, shaft_top),
            (neck, shaft_top),
            (neck, top),
            (right, top + height // 2),
            (neck, bottom),
            (neck, shaft_bottom),
            (left, shaft_bottom),
        ]
        if shape_type == "left_arrow":
            points = [(left + right - x, y) for x, y in points]
        draw.polygon(points, fill=255)
    elif shape_type in {"up_arrow", "down_arrow"}:
        shaft_left = int(round(left + width * 0.31))
        shaft_right = int(round(left + width * 0.69))
        neck = int(round(top + height * 0.38))
        points = [
            (shaft_left, bottom),
            (shaft_left, neck),
            (left, neck),
            (left + width // 2, top),
            (right, neck),
            (shaft_right, neck),
            (shaft_right, bottom),
        ]
        if shape_type == "down_arrow":
            points = [(x, top + bottom - y) for x, y in points]
        draw.polygon(points, fill=255)
    else:
        draw.rectangle([left, top, right, bottom], outline=255, width=cleanup_width)
    return np.asarray(mask_image) > 0


def place_cleanup_mask(
    mask_pixels: Any,
    mask_bbox: Any,
    background_shape: tuple[int, ...],
    ref_size: tuple[float, float] | None,
) -> Any:
    import numpy as np
    from PIL import Image

    background_height, background_width = background_shape[:2]
    if mask_pixels.ndim == 3:
        mask_pixels = mask_pixels[:, :, 0]
    if mask_pixels.shape == (background_height, background_width):
        return mask_pixels > 0
    if not valid_bbox(mask_bbox):
        raise ValueError("local cleanup mask requires a valid mask_bbox")
    mapped = scaled_bbox(
        [float(value) for value in mask_bbox],
        background_width,
        background_height,
        ref_size,
    )
    if mapped is None:
        raise ValueError("cleanup mask bbox is outside the background canvas")
    left, top, width, height = mapped
    resized = Image.fromarray(mask_pixels.astype("uint8")).resize(
        (width, height),
        resample=Image.Resampling.NEAREST,
    )
    placed = np.zeros((background_height, background_width), dtype=bool)
    placed[top : top + height, left : left + width] = np.asarray(resized) > 0
    return placed


def parse_rgb(value: Any) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    if len(text) != 6:
        raise ValueError(f"invalid frame line color: {value!r}")
    try:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError as exc:
        raise ValueError(f"invalid frame line color: {value!r}") from exc


def local_color_support(
    background_pixels: Any,
    band: Any,
    color: Any,
) -> tuple[float, float, float]:
    """Return support in the semantic band, nearby ambient support, and excess.

    Watercolor and paper-grain slide backgrounds often contain large regions
    close to a pale frame color.  In that case absolute color support inside a
    frame band is not proof that the original frame line survived cleanup.  The
    excess over a nearby control ring is the auditable residual signal.
    """

    import cv2
    import numpy as np

    rgb = np.asarray(parse_rgb(color), dtype=np.float32)
    selected = background_pixels[band].astype(np.float32)
    support = (
        float(np.mean(np.linalg.norm(selected - rgb, axis=1) <= 48.0))
        if selected.size
        else 0.0
    )
    # Restrict the control-ring dilation to the semantic object's local
    # bounding region. A full-slide MaxFilter per frame made the audit
    # needlessly quadratic on 39 high-resolution pages.
    ys, xs = np.where(band)
    if not len(xs):
        return support, 0.0, support
    pad = 14
    left = max(0, int(xs.min()) - pad)
    top = max(0, int(ys.min()) - pad)
    right = min(background_pixels.shape[1], int(xs.max()) + pad + 1)
    bottom = min(background_pixels.shape[0], int(ys.max()) + pad + 1)
    local_band = band[top:bottom, left:right]
    kernel = np.ones((25, 25), np.uint8)
    expanded = cv2.dilate(local_band.astype(np.uint8), kernel, iterations=1) > 0
    ring = expanded & ~local_band
    control = background_pixels[top:bottom, left:right][ring].astype(np.float32)
    ambient_support = (
        float(np.mean(np.linalg.norm(control - rgb, axis=1) <= 48.0))
        if control.size
        else 0.0
    )
    return support, ambient_support, max(0.0, support - ambient_support)


def audit_frame_cleanup(
    item: dict[str, Any],
    background_pixels: Any,
    deck_path: Path,
    assets_dir: Path | None,
    ref_size: tuple[float, float] | None,
    *,
    expected_band: Any | None = None,
    semantic_label: str = "frame line",
) -> tuple[dict[str, Any], list[str]]:
    import numpy as np

    name = str(item.get("name", "frame"))
    evidence = item.get("cleanup_evidence")
    errors: list[str] = []
    if not isinstance(evidence, dict):
        return {"name": name, "status": FAIL}, [
            f"{name}: cleanup evidence is missing"
        ]
    if evidence.get("status") != PASS:
        errors.append(f"{name}: cleanup evidence status is not pass")
    recorded_support = evidence.get(
        "post_cleanup_excess_support",
        evidence.get("post_cleanup_support", evidence.get("post_cleanup_frame_support")),
    )
    if not isinstance(recorded_support, (int, float)):
        errors.append(f"{name}: post-cleanup support is missing")
    elif float(recorded_support) > MAX_FRAME_RESIDUAL_SUPPORT:
        errors.append(
            f"{name}: recorded post-cleanup residual support is too high "
            f"({float(recorded_support):.4f})"
        )
    recorded_ratio = evidence.get("residual_ratio")
    if not isinstance(recorded_ratio, (int, float)):
        errors.append(f"{name}: residual_ratio is missing")
    elif (
        isinstance(recorded_support, (int, float))
        and float(recorded_support) > MAX_FRAME_RESIDUAL_SUPPORT
        and float(recorded_ratio) > MAX_RECORDED_RESIDUAL_RATIO
    ):
        errors.append(
            f"{name}: recorded residual_ratio is too high ({float(recorded_ratio):.4f})"
        )

    cleanup_mask = resolve_asset(
        item.get("cleanup_mask") or evidence.get("cleanup_mask"),
        deck_path,
        assets_dir,
    )
    if cleanup_mask is None or not cleanup_mask.exists():
        errors.append(f"{name}: cleanup mask is missing")
        return {"name": name, "status": FAIL}, errors
    try:
        mask_pixels, mask_format = decode_image(cleanup_mask, "L")
        if mask_format != "PNG":
            raise ValueError(
                f"cleanup mask must be PNG, decoded format={mask_format or 'unknown'}"
            )
        placed_mask = place_cleanup_mask(
            mask_pixels,
            item.get("mask_bbox") or evidence.get("mask_bbox"),
            background_pixels.shape,
            ref_size,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"{name}: cleanup mask decode failed: {exc}")
        return {
            "name": name,
            "status": FAIL,
            "cleanup_mask": str(cleanup_mask),
        }, errors

    band = expected_band if expected_band is not None else frame_band(
        item, background_pixels.shape, ref_size
    )
    band_pixels = int(np.count_nonzero(band))
    coverage = (
        float(np.count_nonzero(band & placed_mask) / band_pixels)
        if band_pixels
        else 0.0
    )
    if coverage < MIN_FRAME_MASK_COVERAGE:
        errors.append(
            f"{name}: cleanup mask covers only {coverage:.3f} of the {semantic_label} band"
        )

    line_color = (
        evidence.get("line_color") or item.get("line_color") or item.get("line")
    )
    try:
        support, ambient_support, excess_support = local_color_support(
            background_pixels,
            band,
            line_color,
        )
    except ValueError as exc:
        errors.append(f"{name}: {exc}")
        support = 1.0
        ambient_support = 0.0
        excess_support = 1.0
    if excess_support > MAX_FRAME_RESIDUAL_SUPPORT:
        errors.append(
            f"{name}: duplicate {semantic_label} remains in background "
            f"(support={support:.4f}, ambient={ambient_support:.4f}, "
            f"excess={excess_support:.4f})"
        )
    return {
        "name": name,
        "frame_id": str(item.get("frame_id", "")),
        "status": PASS if not errors else FAIL,
        "cleanup_mask": str(cleanup_mask),
        "mask_coverage": round(coverage, 6),
        "background_frame_support": round(support, 6),
        "background_ambient_support": round(ambient_support, 6),
        "background_excess_support": round(excess_support, 6),
    }, errors


def audit_delegated_frame_cleanup(
    item: dict[str, Any],
    frame_shapes_by_id: dict[str, list[dict[str, Any]]],
    direct_audits: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    name = str(item.get("name", "frame"))
    delegate_id = cleanup_delegate_id(item)
    errors: list[str] = []
    audit = {
        "name": name,
        "frame_id": str(item.get("frame_id", "")),
        "cleanup_delegated_to": delegate_id,
        "status": FAIL,
    }
    delegate_items = frame_shapes_by_id.get(delegate_id, [])
    if len(delegate_items) != 1:
        errors.append(
            f"{name}: cleanup delegate does not bind to exactly one native frame: "
            f"{delegate_id or '<missing>'}"
        )
        return audit, errors
    delegate = delegate_items[0]
    if cleanup_delegate_id(delegate):
        errors.append(f"{name}: cleanup delegate must perform direct cleanup")
    cleanup_mode = str(delegate.get("background_cleanup", "")).lower()
    if cleanup_mode != "full-frame-directional":
        errors.append(
            f"{name}: cleanup delegate must use full-frame-directional cleanup"
        )
    delegate_audit = direct_audits.get(delegate_id)
    if not isinstance(delegate_audit, dict) or delegate_audit.get("status") != PASS:
        errors.append(f"{name}: cleanup delegate did not pass direct cleanup audit")

    cleanup_bbox = cleanup_region_bbox(delegate)
    if cleanup_bbox is None:
        errors.append(f"{name}: delegated cleanup region bbox is missing")
    else:
        for label, candidate in (
            ("source_bbox", item.get("source_bbox")),
            ("layout_bbox", item.get("layout_bbox")),
        ):
            if not valid_bbox(candidate):
                errors.append(f"{name}: delegated {label} is invalid")
            elif not bbox_contains(
                cleanup_bbox, [float(value) for value in candidate]
            ):
                errors.append(f"{name}: {label} is outside delegated cleanup region")

    child_layer = compound_layer(item)
    parent_layer = compound_layer(delegate)
    if child_layer not in {"middle", "inner"} or parent_layer != "outer":
        errors.append(
            f"{name}: delegated cleanup requires outer parent and middle/inner child layers"
        )
    child_z = item.get("z_order_within_compound")
    parent_z = delegate.get("z_order_within_compound")
    if not isinstance(child_z, (int, float)) or not isinstance(parent_z, (int, float)):
        errors.append(f"{name}: delegated cleanup requires numeric compound z-order")
    elif float(child_z) <= float(parent_z):
        errors.append(f"{name}: z-order must be greater than its cleanup delegate")

    audit.update(
        {
            "status": PASS if not errors else FAIL,
            "compound_layer": child_layer,
            "delegate_compound_layer": parent_layer,
            "cleanup_region_bbox": cleanup_bbox or [],
            "delegate_audit_status": (
                delegate_audit.get("status")
                if isinstance(delegate_audit, dict)
                else FAIL
            ),
        }
    )
    return audit, errors


def audit_reviewed_panel_asset(
    item: dict[str, Any],
    frame: dict[str, Any],
    frame_cleanup_audit: dict[str, Any] | None,
    asset_path: Path | None,
    background_pixels: Any,
    deck_path: Path,
    assets_dir: Path | None,
    ref_size: tuple[float, float] | None,
    *,
    require_cleanup: bool,
) -> tuple[dict[str, Any], list[str]]:
    """Verify reviewed panel geometry, provenance, and full semantic cleanup."""

    import numpy as np

    name = str(item.get("name", "reviewed-panel-content"))
    frame_id = str(item.get("frame_id", "")).strip()
    errors: list[str] = []
    content_bbox = item.get("content_bbox")
    asset_bbox = object_bbox(item)
    native_bbox = frame_bbox(frame)
    if not valid_bbox(content_bbox):
        errors.append(f"{name}: reviewed panel content_bbox is invalid")
        content_values = None
    else:
        content_values = [float(value) for value in content_bbox]
    if content_values is not None and asset_bbox is not None and not bbox_matches(
        content_values, asset_bbox
    ):
        errors.append(f"{name}: content_bbox does not match the bounded asset bbox")
    if content_values is not None and native_bbox is not None and not bbox_contains(
        native_bbox, content_values
    ):
        errors.append(f"{name}: content_bbox is outside the bound native frame")
    if ref_size is not None:
        canvas_bbox = [0.0, 0.0, float(ref_size[0]), float(ref_size[1])]
        if native_bbox is not None and not bbox_contains(canvas_bbox, native_bbox):
            errors.append(f"{name}: bound native frame is outside the slide canvas")
        if content_values is not None and not bbox_contains(canvas_bbox, content_values):
            errors.append(f"{name}: content_bbox is outside the slide canvas")
    if not bool(frame.get("reviewed_panel")):
        errors.append(f"{name}: bound native frame is not marked as reviewed_panel")
    if str(frame.get("background_cleanup_scope", "")) != "full-semantic-panel":
        errors.append(f"{name}: native frame lacks full-semantic-panel cleanup scope")
    if str(item.get("background_cleanup_scope", "")) != "full-semantic-panel":
        errors.append(f"{name}: panel asset lacks full-semantic-panel cleanup scope")

    cleanup_evidence = frame.get("cleanup_evidence")
    if not isinstance(cleanup_evidence, dict):
        errors.append(f"{name}: reviewed panel cleanup evidence is missing")
        cleanup_details: dict[str, Any] = {}
    else:
        cleanup_details = cleanup_evidence
        recorded_coverage = cleanup_evidence.get("semantic_content_coverage")
        if not isinstance(recorded_coverage, (int, float)):
            errors.append(f"{name}: semantic content cleanup coverage is missing")
        elif float(recorded_coverage) < MIN_REVIEWED_PANEL_CONTENT_MASK_COVERAGE:
            errors.append(
                f"{name}: recorded semantic content cleanup coverage is too low "
                f"({float(recorded_coverage):.4f})"
            )
        if cleanup_evidence.get("background_cleanup_scope") != "full-semantic-panel":
            errors.append(f"{name}: cleanup evidence lacks full-semantic-panel scope")

    frame_mask_coverage = 0.0
    content_mask_coverage = 0.0
    if require_cleanup:
        if not isinstance(frame_cleanup_audit, dict) or frame_cleanup_audit.get("status") != PASS:
            errors.append(f"{name}: bound native frame did not pass cleanup audit")
        cleanup_mask = resolve_asset(
            frame.get("cleanup_mask")
            or cleanup_details.get("cleanup_mask"),
            deck_path,
            assets_dir,
        )
        if cleanup_mask is None or not cleanup_mask.exists():
            errors.append(f"{name}: reviewed panel cleanup mask is missing")
        elif background_pixels is None:
            errors.append(f"{name}: reviewed panel background could not be decoded")
        else:
            try:
                mask_pixels, mask_format = decode_image(cleanup_mask, "L")
                if mask_format != "PNG":
                    raise ValueError(
                        f"cleanup mask must be PNG, decoded format={mask_format or 'unknown'}"
                    )
                placed_mask = place_cleanup_mask(
                    mask_pixels,
                    frame.get("mask_bbox") or cleanup_details.get("mask_bbox"),
                    background_pixels.shape,
                    ref_size,
                )
                if native_bbox is not None:
                    mapped_frame = scaled_bbox(
                        native_bbox,
                        background_pixels.shape[1],
                        background_pixels.shape[0],
                        ref_size,
                    )
                    if mapped_frame is not None:
                        left, top, width, height = mapped_frame
                        region = placed_mask[top : top + height, left : left + width]
                        frame_mask_coverage = float(np.mean(region)) if region.size else 0.0
                if content_values is not None:
                    mapped_content = scaled_bbox(
                        content_values,
                        background_pixels.shape[1],
                        background_pixels.shape[0],
                        ref_size,
                    )
                    if mapped_content is not None:
                        left, top, width, height = mapped_content
                        region = placed_mask[top : top + height, left : left + width]
                        content_mask_coverage = float(np.mean(region)) if region.size else 0.0
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(f"{name}: reviewed panel cleanup mask decode failed: {exc}")
        if frame_mask_coverage < MIN_REVIEWED_PANEL_FRAME_MASK_COVERAGE:
            errors.append(
                f"{name}: cleanup mask covers only {frame_mask_coverage:.3f} of the panel frame area"
            )
        if content_mask_coverage < MIN_REVIEWED_PANEL_CONTENT_MASK_COVERAGE:
            errors.append(
                f"{name}: cleanup mask covers only {content_mask_coverage:.3f} of the semantic content area"
            )

    provenance = item.get("source_provenance")
    provenance_kind = ""
    if not isinstance(provenance, dict):
        errors.append(f"{name}: reviewed panel source provenance is missing")
    else:
        provenance_kind = str(provenance.get("kind", ""))
        if provenance_kind not in {
            "verified-imagegen-master-crop",
            "external-source-crop",
        }:
            errors.append(f"{name}: unsupported reviewed panel source provenance kind")
        source_path = resolve_asset(
            provenance.get("source_file"), deck_path, assets_dir
        )
        expected_source_hash = str(provenance.get("source_sha256", "")).lower()
        if source_path is None or not source_path.exists():
            errors.append(f"{name}: reviewed panel provenance source file is missing")
        elif not expected_source_hash:
            errors.append(f"{name}: reviewed panel provenance source sha256 is missing")
        elif sha256_file(source_path).lower() != expected_source_hash:
            errors.append(f"{name}: reviewed panel provenance source sha256 mismatch")
        if not valid_bbox(provenance.get("source_bbox")):
            errors.append(f"{name}: reviewed panel provenance source_bbox is invalid")
        source_dimensions = provenance.get("source_dimensions")
        if (
            not isinstance(source_dimensions, list)
            or len(source_dimensions) != 2
            or any(
                not isinstance(value, (int, float)) or value <= 0
                for value in source_dimensions
            )
        ):
            errors.append(f"{name}: reviewed panel provenance source dimensions are invalid")
        elif valid_bbox(provenance.get("source_bbox")) and not bbox_contains(
            [0.0, 0.0, float(source_dimensions[0]), float(source_dimensions[1])],
            [float(value) for value in provenance["source_bbox"]],
        ):
            errors.append(f"{name}: reviewed panel provenance source_bbox is out of bounds")
        if provenance_kind == "external-source-crop":
            if not str(provenance.get("input_source_file", "")).strip():
                errors.append(f"{name}: external panel input source path is missing")
            strategy = str(provenance.get("resolution_strategy", ""))
            if strategy not in {
                "absolute-input-path-copied-into-run",
                "relative-to-override-json-directory-copied-into-run",
            }:
                errors.append(f"{name}: external panel source resolution strategy is invalid")
            if strategy.startswith("relative-") and not str(
                provenance.get("override_file", "")
            ).strip():
                errors.append(f"{name}: external panel override origin is missing")
        elif provenance_kind == "verified-imagegen-master-crop" and not bool(
            provenance.get("verified_imagegen_master")
        ):
            errors.append(f"{name}: ImageGen master provenance is not verified")

    expected_asset_hash = str(item.get("asset_sha256", "")).lower()
    if asset_path is None or not asset_path.exists():
        pass
    elif not expected_asset_hash:
        errors.append(f"{name}: reviewed panel asset sha256 is missing")
    elif sha256_file(asset_path).lower() != expected_asset_hash:
        errors.append(f"{name}: reviewed panel asset sha256 mismatch")

    return {
        "name": name,
        "frame_id": frame_id,
        "status": PASS if not errors else FAIL,
        "frame_bbox": native_bbox or [],
        "content_bbox": content_values or [],
        "frame_mask_coverage": round(frame_mask_coverage, 6),
        "content_mask_coverage": round(content_mask_coverage, 6),
        "source_provenance_kind": provenance_kind,
    }, errors


def review_template(
    deck_path: Path,
    deck_hash: str,
    pptx: Path,
    pptx_hash: str,
    slide_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "deck": str(deck_path),
        "deck_sha256": deck_hash,
        "pptx": str(pptx),
        "pptx_sha256": pptx_hash,
        "review_scope": REVIEW_SCOPE,
        "slides": [
            {
                "slide_id": slide_id,
                "status": "pending",
                "checks": {check: "pending" for check in REVIEW_CHECKS},
                "notes": "",
            }
            for slide_id in slide_ids
        ],
        "verdict": "pending",
    }


def review_gate(
    path: Path,
    deck_path: Path,
    deck_hash: str,
    pptx: Path,
    pptx_hash: str,
    slide_ids: list[str],
) -> dict[str, Any]:
    if not path.exists():
        write_json(path, review_template(deck_path, deck_hash, pptx, pptx_hash, slide_ids))
        return {
            "status": BLOCKED,
            "report": str(path),
            "error": "pending layer-review template created",
        }
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": FAIL, "report": str(path), "errors": [str(exc)]}

    errors: list[str] = []
    if payload.get("verdict") != PASS:
        errors.append(f"verdict={payload.get('verdict')!r}")
    if payload.get("review_scope") != REVIEW_SCOPE:
        errors.append("layer review scope mismatch")
    if payload.get("deck_sha256") != deck_hash:
        errors.append("layer review deck hash mismatch")
    if payload.get("pptx_sha256") != pptx_hash:
        errors.append("layer review PPTX hash mismatch")
    rows_list = list(payload.get("slides", []))
    rows = {str(row.get("slide_id")): row for row in rows_list}
    if len(rows_list) != len(slide_ids) or set(rows) != set(slide_ids):
        errors.append("layer review slide coverage mismatch")
    for slide_id in slide_ids:
        row = rows.get(slide_id, {})
        if row.get("status") != PASS:
            errors.append(f"{slide_id}: layer review status is not pass")
            continue
        checks = row.get("checks", {})
        pending = [check for check in REVIEW_CHECKS if checks.get(check) != PASS]
        if pending:
            errors.append(f"{slide_id}: pending checks: {', '.join(pending)}")
    return {
        "status": PASS if not errors else BLOCKED,
        "report": str(path),
        "reviewed_slides": sum(1 for row in rows.values() if row.get("status") == PASS),
        "errors": errors,
    }


def validate_slide(
    slide: dict[str, Any],
    deck_path: Path,
    assets_dir: Path | None,
    strict: bool,
    ref_size: tuple[float, float] | None,
) -> dict[str, Any]:
    slide_id = str(slide.get("slide_id", "")).strip() or "unnamed"
    errors: list[str] = []
    background = resolve_asset(slide.get("background"), deck_path, assets_dir)
    background_pixels = None
    background_format = ""
    if background is None:
        errors.append("missing single continuous background")
    elif not background.exists():
        errors.append(f"background asset missing: {background}")
    else:
        try:
            background_pixels, background_format = decode_image(background, "RGB")
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"background image decode failed: {exc}")

    texts = list(slide.get("texts", []))
    shapes = list(slide.get("shapes", []))
    assets = list(slide.get("icons", []))
    frame_shapes_by_id: dict[str, list[dict[str, Any]]] = {}
    audited_frames: list[dict[str, Any]] = []
    audited_lines: list[dict[str, Any]] = []
    reviewed_panel_audits: list[dict[str, Any]] = []
    direct_frame_audits: dict[str, dict[str, Any]] = {}
    direct_frame_errors: dict[str, list[str]] = {}
    frame_shapes = 0
    for index, item in enumerate(shapes):
        name = str(item.get("name", f"shape-{index}"))
        if str(item.get("editability_level", "")).lower() not in NATIVE_LEVELS:
            errors.append(f"{name}: simple shape is not native")
        source_bbox = item.get("source_bbox")
        final_bbox = object_bbox(item)
        if not valid_bbox(source_bbox):
            errors.append(f"{name}: invalid source_bbox")
        if final_bbox is None:
            errors.append(f"{name}: invalid final bbox")
        role = str(item.get("role", "")).lower()
        if any(token in role for token in ("panel", "frame", "card", "divider")):
            frame_shapes += 1
        if frame_shape(item):
            item_frame_id = str(item.get("frame_id", "")).strip()
            if not item_frame_id:
                errors.append(f"{name}: native frame requires frame_id")
            else:
                frame_shapes_by_id.setdefault(item_frame_id, []).append(item)
            if (
                strict
                and bool(item.get("allow_raster_background_frame"))
                and not cleanup_delegate_id(item)
            ):
                errors.append(
                    f"{name}: allow_raster_background_frame cannot satisfy strict cleanup"
                )

    for item_frame_id, items in frame_shapes_by_id.items():
        if len(items) > 1:
            errors.append(
                f"frame_id={item_frame_id}: expected exactly one native frame, "
                f"found {len(items)}"
            )
    if strict and background_pixels is not None:
        for item_frame_id, items in frame_shapes_by_id.items():
            if len(items) != 1:
                continue
            if cleanup_delegate_id(items[0]):
                continue
            audit, audit_errors = audit_frame_cleanup(
                items[0],
                background_pixels,
                deck_path,
                assets_dir,
                ref_size,
            )
            direct_frame_audits[item_frame_id] = audit
            direct_frame_errors[item_frame_id] = audit_errors

        delegated_by_parent: dict[str, list[dict[str, Any]]] = {}
        for item_frame_id, items in frame_shapes_by_id.items():
            if len(items) != 1:
                continue
            item = items[0]
            delegate_id = cleanup_delegate_id(item)
            if delegate_id:
                audit, audit_errors = audit_delegated_frame_cleanup(
                    item,
                    frame_shapes_by_id,
                    direct_frame_audits,
                )
                delegated_by_parent.setdefault(delegate_id, []).append(item)
            else:
                audit = direct_frame_audits[item_frame_id]
                audit_errors = direct_frame_errors[item_frame_id]
            audited_frames.append(audit)
            errors.extend(audit_errors)

        for parent_id, children in delegated_by_parent.items():
            parent_items = frame_shapes_by_id.get(parent_id, [])
            if len(parent_items) != 1:
                continue
            members = [parent_items[0], *children]
            layers = [compound_layer(member) for member in members]
            if len(layers) != len(set(layers)):
                errors.append(
                    f"frame_id={parent_id}: compound cleanup group contains duplicate layers"
                )
            for left_index, left in enumerate(members):
                left_layer = compound_layer(left)
                left_z = left.get("z_order_within_compound")
                if left_layer not in COMPOUND_LAYER_RANK or not isinstance(
                    left_z, (int, float)
                ):
                    continue
                for right in members[left_index + 1 :]:
                    right_layer = compound_layer(right)
                    right_z = right.get("z_order_within_compound")
                    if right_layer not in COMPOUND_LAYER_RANK or not isinstance(
                        right_z, (int, float)
                    ):
                        continue
                    if left_layer == right_layer:
                        continue
                    lower_z, upper_z = (
                        (float(left_z), float(right_z))
                        if COMPOUND_LAYER_RANK[left_layer]
                        < COMPOUND_LAYER_RANK[right_layer]
                        else (float(right_z), float(left_z))
                    )
                    if lower_z >= upper_z:
                        errors.append(
                            f"frame_id={parent_id}: compound layer z-order is not strictly "
                            "increasing from outer to inner"
                        )
                        break
        for item in shapes:
            if frame_shape(item):
                continue
            if not bool(item.get("requires_background_cleanup")):
                continue
            is_line = line_shape(item)
            audit, audit_errors = audit_frame_cleanup(
                item,
                background_pixels,
                deck_path,
                assets_dir,
                ref_size,
                expected_band=(
                    line_band(item, background_pixels.shape, ref_size)
                    if is_line
                    else native_shape_band(item, background_pixels.shape, ref_size)
                ),
                semantic_label="native line" if is_line else "native shape",
            )
            audited_lines.append(audit)
            errors.extend(audit_errors)

    for index, item in enumerate(texts):
        name = str(item.get("name", f"text-{index}"))
        if str(item.get("editability_level", "")).lower() not in NATIVE_LEVELS:
            errors.append(f"{name}: normal text is not native")
        if not valid_bbox(item.get("source_bbox")):
            errors.append(f"{name}: invalid source_bbox")
        if object_bbox(item) is None:
            errors.append(f"{name}: invalid final bbox")

    background_tiles = 0
    bounded_assets = 0
    panel_content_assets = 0
    for index, item in enumerate(assets):
        name = str(item.get("name", f"asset-{index}"))
        role = str(item.get("role", "")).lower()
        is_tile = role in BACKGROUND_TILE_ROLES or name.lower().startswith("hf-tile-")
        if is_tile:
            background_tiles += 1
            if strict:
                errors.append(f"{name}: background tile is forbidden in strict mode")
            continue
        bounded_assets += 1
        if str(item.get("editability_level", "")).lower() not in BOUNDED_ASSET_LEVELS:
            errors.append(f"{name}: unsupported bounded-asset editability level")
        if not role:
            errors.append(f"{name}: bounded asset role is missing")
        source_bbox = item.get("source_bbox")
        final_bbox = object_bbox(item)
        if not valid_bbox(source_bbox):
            errors.append(f"{name}: invalid source_bbox")
        if final_bbox is None:
            errors.append(f"{name}: invalid final bbox")
        asset_path = resolve_asset(item.get("file") or item.get("asset"), deck_path, assets_dir)
        if asset_path is None or not asset_path.exists():
            errors.append(f"{name}: bounded asset file is missing")
        elif asset_path.suffix.lower() == ".png":
            try:
                decode_image(asset_path, "RGBA")
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(f"{name}: PNG asset decode failed: {exc}")
        if role == "movable-panel-content":
            panel_content_assets += 1
            item_frame_id = str(item.get("frame_id", "")).strip()
            if not item_frame_id:
                errors.append(f"{name}: movable panel content requires frame_id")
                continue
            matching_frames = frame_shapes_by_id.get(item_frame_id, [])
            if len(matching_frames) != 1:
                errors.append(
                    f"{name}: frame_id={item_frame_id} does not bind to exactly one "
                    "native frame"
                )
                continue
            asset_frame_bbox = item.get("frame_bbox")
            native_frame_bbox = frame_bbox(matching_frames[0])
            if not valid_bbox(asset_frame_bbox):
                errors.append(f"{name}: invalid frame_bbox")
            elif native_frame_bbox is None or not bbox_matches(
                [float(value) for value in asset_frame_bbox], native_frame_bbox
            ):
                errors.append(f"{name}: frame_bbox does not match bound native frame")
            if bool(item.get("reviewed_panel")):
                audit, audit_errors = audit_reviewed_panel_asset(
                    item,
                    matching_frames[0],
                    direct_frame_audits.get(item_frame_id),
                    asset_path,
                    background_pixels,
                    deck_path,
                    assets_dir,
                    ref_size,
                    require_cleanup=strict,
                )
                reviewed_panel_audits.append(audit)
                errors.extend(audit_errors)

    return {
        "slide_id": slide_id,
        "status": PASS if not errors else FAIL,
        "background": str(background) if background else "",
        "background_mode": "single" if background else "missing",
        "background_format": background_format,
        "background_dimensions": (
            [int(background_pixels.shape[1]), int(background_pixels.shape[0])]
            if background_pixels is not None
            else []
        ),
        "background_tiles": background_tiles,
        "native_texts": len(texts),
        "native_shapes": len(shapes),
        "frame_shapes": frame_shapes,
        "bounded_assets": bounded_assets,
        "panel_content_assets": panel_content_assets,
        "reviewed_panel_assets": len(reviewed_panel_audits),
        "frame_cleanup_audits": audited_frames,
        "reviewed_panel_audits": reviewed_panel_audits,
        "line_cleanup_audits": audited_lines,
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deck", help="deck-high-fidelity.json")
    parser.add_argument("--pptx", required=True, help="Exact final PPTX to bind to the review evidence.")
    parser.add_argument("--review", required=True, help="Per-slide layer review JSON; a pending template is created when missing.")
    parser.add_argument("--out", required=True, help="Layer-contract report JSON.")
    parser.add_argument("--allow-background-tiles", action="store_true", help="Legacy compatibility mode; never use for a new gold release.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    deck_path = Path(args.deck).expanduser().resolve()
    pptx = Path(args.pptx).expanduser().resolve()
    review_path = Path(args.review).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()

    if not deck_path.exists() or not pptx.exists():
        missing = [str(path) for path in (deck_path, pptx) if not path.exists()]
        report = {
            "policy": "semantic-layer-contract-v1",
            "deck": str(deck_path),
            "pptx": str(pptx),
            "verdict": BLOCKED,
            "errors": [f"missing input: {value}" for value in missing],
        }
        write_json(out, report)
        return 2

    try:
        deck = read_json(deck_path)
    except (OSError, json.JSONDecodeError) as exc:
        write_json(
            out,
            {
                "policy": "semantic-layer-contract-v1",
                "deck": str(deck_path),
                "pptx": str(pptx),
                "verdict": FAIL,
                "errors": [str(exc)],
            },
        )
        return 2

    deck_hash = sha256_file(deck_path)
    pptx_hash = sha256_file(pptx)
    assets_value = deck.get("assets_dir")
    assets_dir = resolve_asset(assets_value, deck_path) if assets_value else None
    slides = list(deck.get("slides", []))
    ref_size = reference_size(deck)
    slide_reports = [
        validate_slide(
            slide,
            deck_path,
            assets_dir,
            not args.allow_background_tiles,
            ref_size,
        )
        for slide in slides
    ]
    slide_ids = [report["slide_id"] for report in slide_reports]
    structural_errors = [
        f"{report['slide_id']}: {error}"
        for report in slide_reports
        for error in report["errors"]
    ]
    structural_status = PASS if slides and not structural_errors else FAIL
    review = review_gate(
        review_path,
        deck_path,
        deck_hash,
        pptx,
        pptx_hash,
        slide_ids,
    )
    if structural_status == FAIL:
        verdict = FAIL
    elif review.get("status") == BLOCKED:
        verdict = BLOCKED
    elif review.get("status") != PASS:
        verdict = FAIL
    else:
        verdict = PASS

    report = {
        "policy": "semantic-layer-contract-v1",
        "deck": str(deck_path),
        "deck_sha256": deck_hash,
        "pptx": str(pptx),
        "pptx_sha256": pptx_hash,
        "strict": not args.allow_background_tiles,
        "slide_count": len(slides),
        "totals": {
            "backgrounds": sum(1 for item in slide_reports if item["background_mode"] == "single"),
            "background_tiles": sum(item["background_tiles"] for item in slide_reports),
            "native_texts": sum(item["native_texts"] for item in slide_reports),
            "native_shapes": sum(item["native_shapes"] for item in slide_reports),
            "frame_shapes": sum(item["frame_shapes"] for item in slide_reports),
            "bounded_assets": sum(item["bounded_assets"] for item in slide_reports),
            "panel_content_assets": sum(item["panel_content_assets"] for item in slide_reports),
        },
        "structural": {"status": structural_status, "errors": structural_errors},
        "review": review,
        "slides": slide_reports,
        "verdict": verdict,
    }
    write_json(out, report)
    print(json.dumps({"verdict": verdict, "report": str(out)}, ensure_ascii=False))
    return 0 if verdict == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
