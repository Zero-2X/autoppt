from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "autopptskills" / "scripts" / "merge_high_fidelity_round.py"


def load_module():
    spec = importlib.util.spec_from_file_location("autoppt_merge_round", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MergeHighFidelityRoundTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_replaces_only_selected_slide_and_copies_verified_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_dir = root / "baseline"
            patch_dir = root / "patch"
            out_dir = root / "round-next"
            for directory in (baseline_dir, patch_dir):
                (directory / "assets" / "S01").mkdir(parents=True)
                (directory / "assets" / "S02").mkdir(parents=True)
            (baseline_dir / "assets" / "S01" / "marker.txt").write_text("baseline-1", encoding="utf-8")
            (baseline_dir / "assets" / "S02" / "marker.txt").write_text("baseline-2", encoding="utf-8")
            (patch_dir / "assets" / "S01" / "marker.txt").write_text("patch-1", encoding="utf-8")
            (patch_dir / "assets" / "S02" / "marker.txt").write_text("patch-2", encoding="utf-8")

            shared = {
                "units": "pixels",
                "ref_width": 1920,
                "ref_height": 1080,
                "slide_width_in": 13.333,
                "slide_height_in": 7.5,
            }
            baseline = {
                **shared,
                "assets_dir": str(baseline_dir),
                "slides": [
                    {"slide_id": "S01", "texts": [{"text": "keep"}]},
                    {"slide_id": "S02", "texts": [{"text": "old"}]},
                ],
            }
            patch = {
                **shared,
                "assets_dir": str(patch_dir),
                "slides": [
                    {"slide_id": "S01", "texts": [{"text": "unselected patch"}]},
                    {"slide_id": "S02", "texts": [{"text": "new"}]},
                ],
            }
            baseline_path = baseline_dir / "deck.json"
            patch_path = patch_dir / "deck.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            patch_path.write_text(json.dumps(patch), encoding="utf-8")

            output, report_path = self.module.merge_round(
                baseline_path,
                patch_path,
                out_dir,
                ["S02"],
            )

            merged = json.loads(output.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["slides"][0]["texts"][0]["text"], "keep")
            self.assertEqual(merged["slides"][1]["texts"][0]["text"], "new")
            self.assertEqual((out_dir / "assets" / "S01" / "marker.txt").read_text(), "baseline-1")
            self.assertEqual((out_dir / "assets" / "S02" / "marker.txt").read_text(), "patch-2")
            self.assertEqual(report["verdict"], "pass")
            self.assertEqual(report["selected_slides"], ["S02"])

    def test_refuses_to_overwrite_a_nonempty_round(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary) / "existing"
            out_dir.mkdir()
            (out_dir / "accepted.txt").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "already contains files"):
                self.module.merge_round(Path("missing"), Path("missing"), out_dir, ["S01"])


if __name__ == "__main__":
    unittest.main()
