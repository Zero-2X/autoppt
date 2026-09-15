from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "autopptskills" / "scripts"
SCRIPT = SCRIPT_DIR / "reconstruct_imagegen_slide.py"


def load_module():
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        spec = importlib.util.spec_from_file_location("autoppt_reconstruct_slide", SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class ReconstructImagegenSlideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_native_connector_cleanup_writes_auditable_mask_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            image = np.full((100, 200, 3), 255, dtype=np.uint8)
            cv2.arrowedLine(image, (20, 50), (180, 50), (120, 40, 10), 3, tipLength=0.08)
            cv2.imwrite(str(source), image)
            connector = {
                "id": "line-001",
                "type": "connector",
                "bbox": [20, 50, 160, 1],
                "source_bbox": [20, 50, 160, 1],
                "x1": 20,
                "y1": 50,
                "x2": 180,
                "y2": 50,
                "line": "#0A2878",
                "begin_arrow": None,
                "end_arrow": "triangle",
                "confidence": 0.9,
            }
            analysis = {
                "texts": [],
                "shapes": [],
                "lines": [connector],
                "icon_candidates": [],
            }

            report = self.module._inpaint_background(
                source,
                analysis,
                {},
                root / "background.png",
                root / "combined-mask.png",
                root / "line-masks",
            )

            evidence = connector["cleanup_evidence"]
            self.assertEqual(evidence["status"], "pass")
            self.assertLess(evidence["post_cleanup_support"], evidence["source_support"])
            self.assertTrue(Path(connector["cleanup_mask"]).exists())
            self.assertEqual(connector["editability_level"], "native")
            self.assertEqual(connector["role"], "connector")
            self.assertEqual(report["line_cleanup_failures"], 0)


if __name__ == "__main__":
    unittest.main()
