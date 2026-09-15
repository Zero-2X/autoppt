from __future__ import annotations

import importlib.util
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "autopptskills" / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_container_bbox_prefers_tight_ocr_bbox():
    audit = load_script("audit_character_frame_separation.py")
    assert audit.bbox_area([0, 0, 200, 80]) / audit.bbox_area([40, 20, 80, 20]) == 10


def test_color_mask_tracks_target_strokes_without_erasing_container():
    cleanup = load_script("character_mask_cleanup.py")
    crop = np.full((80, 240, 3), [190, 45, 25], dtype=np.uint8)
    cv2.putText(crop, "TEST", (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (248, 245, 240), 3, cv2.LINE_AA)
    mask = cleanup.color_mask(crop, np.asarray([248, 245, 240], dtype=np.uint8), 36.0)
    ratio = np.count_nonzero(mask) / mask.size
    assert 0.01 < ratio < 0.20


def test_svg_trace_is_bounded_and_contains_metadata(tmp_path: Path):
    cleanup = load_script("character_mask_cleanup.py")
    mask = np.zeros((50, 80), dtype=np.uint8)
    cv2.rectangle(mask, (10, 10), (30, 40), 255, -1)
    out = tmp_path / "glyph.svg"
    count = cleanup.contours_to_svg(mask, "#123456", out, {"text": "字"})
    payload = out.read_text(encoding="utf-8")
    assert count == 1
    assert 'viewBox="0 0 80 50"' in payload
    assert "字" in payload
