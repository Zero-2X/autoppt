from __future__ import annotations

import importlib.util
import hashlib
import json
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

    def test_slide_scoped_list_overrides_do_not_leak_mapping_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            override_path = Path(temporary) / "overrides.json"
            override_path.write_text(
                json.dumps(
                    {
                        "add_texts": {
                            "S02": [
                                {
                                    "id": "reviewed-label",
                                    "text": "Reviewed label",
                                    "bbox": [1, 2, 3, 4],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            analysis = {
                "slide_id": "S01",
                "texts": [],
                "shapes": [],
                "lines": [],
                "icon_candidates": [],
                "unresolved": [],
            }

            result = self.module._apply_overrides(analysis, override_path)

            self.assertEqual(result["texts"], [])

    def test_visual_first_text_only_drops_auto_geometry_but_keeps_text(self) -> None:
        analysis = {
            "texts": [{"id": "text-001", "text": "Title"}],
            "shapes": [{"id": "shape-001"}],
            "lines": [{"id": "line-001"}],
            "icon_candidates": [{"id": "icon-001"}],
        }

        result = self.module._apply_visual_first_text_only(analysis)

        self.assertEqual(result["texts"], [{"id": "text-001", "text": "Title"}])
        self.assertEqual(result["shapes"], [])
        self.assertEqual(result["lines"], [])
        self.assertEqual(result["icon_candidates"], [])
        self.assertTrue(result["visual_first_text_only"])

    def test_manifest_verification_requires_matching_builtin_ig_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "S01.png"
            source.write_bytes(b"not-a-real-png-but-hashable")
            prompt_manifest = root / "image-prompts.json"
            prompt_manifest.write_text(
                json.dumps({"slides": [{"slide_id": "S01", "final_path": "S01.png"}]}),
                encoding="utf-8",
            )

            verified, reason = self.module._verify_imagegen_manifest(prompt_manifest, source)
            self.assertFalse(verified)
            self.assertIn("strong ig_", reason or "")

            sidecar = root / "assets" / "generated" / "S01-pipeline.json"
            sidecar.parent.mkdir(parents=True)
            sidecar.write_text(
                json.dumps(
                    {
                        "slide_id": "S01",
                        "status": "generated",
                        "backend": "builtin",
                        "provenance_kind": "builtin-imagegen",
                        "generation_mode": "direct_final_slide_imagegen",
                        "id": "ig_test_record",
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "output_path": str(source),
                    }
                ),
                encoding="utf-8",
            )
            verified, reason = self.module._verify_imagegen_manifest(prompt_manifest, source)
            self.assertTrue(verified, reason)


if __name__ == "__main__":
    unittest.main()
