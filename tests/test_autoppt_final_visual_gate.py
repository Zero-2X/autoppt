from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "autopptskills" / "scripts" / "final_visual_gate.py"


def load_module():
    spec = importlib.util.spec_from_file_location("autoppt_final_visual_gate", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_metrics(path: Path, value: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "mean_abs_diff_0_255": value,
                "rms_diff_0_255": value + 1,
                "changed_pixel_fraction_threshold_32": value / 100,
                "changed_pixel_fraction_threshold_64": value / 200,
            }
        ),
        encoding="utf-8",
    )


def write_minimal_pptx(path: Path, *, cx: int, cy: int) -> None:
    presentation_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        f'<p:sldSz cx="{cx}" cy="{cy}"/>'
        '</p:presentation>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/presentation.xml", presentation_xml)


class FinalVisualGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_source_inventory_rejects_mixed_canvas_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_dir = Path(temporary)
            slides = source_dir / "assets" / "slides"
            slides.mkdir(parents=True)
            Image.new("RGB", (160, 90), "white").save(slides / "S01.png")
            Image.new("RGB", (320, 180), "white").save(slides / "S02.png")

            report = self.module._source_inventory(source_dir, ["S01", "S02"])

            self.assertEqual(report["status"], "fail")
            self.assertIn("differs from deck source size", report["errors"][0])

    def test_relative_baseline_fails_when_any_metric_regresses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "current.json"
            baseline = root / "baseline.json"
            write_metrics(current, 2.0)
            write_metrics(baseline, 1.0)

            report = self.module._compare_to_baseline(current, baseline)

            self.assertEqual(report["status"], "fail")
            self.assertEqual(set(report["regressions"]), set(self.module.VISUAL_METRICS))

    def test_main_runs_layout_once_and_keeps_comparison_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "source"
            slides = source_dir / "assets" / "slides"
            slides.mkdir(parents=True)
            for slide_id in ("S01", "S02"):
                Image.new("RGB", (160, 90), "white").save(slides / f"{slide_id}.png")
            deck = root / "deck.json"
            deck.write_text(
                json.dumps(
                    {
                        "units": "pixel",
                        "ref_width": 160,
                        "ref_height": 90,
                        "slide_width_in": 13.333,
                        "slide_height_in": 7.5,
                        "slides": [
                            {"slide_id": "S01", "shapes": [], "icons": [], "texts": []},
                            {"slide_id": "S02", "shapes": [], "icons": [], "texts": []},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            pptx = root / "deck.pptx"
            write_minimal_pptx(pptx, cx=12191695, cy=6858000)
            baseline = root / "baseline"
            write_metrics(baseline / "S01" / "report.json", 1.0)
            write_metrics(baseline / "S02" / "report.json", 2.0)
            out_dir = root / "gate"
            calls: list[str] = []

            def fake_run(command, *, cwd):
                script_name = Path(command[1]).name
                calls.append(script_name)
                if script_name == "visual_compare_qa.py":
                    slide_id = Path(command[-1]).name
                    write_metrics(Path(command[-1]) / "report.json", 1.0 if slide_id == "S01" else 2.0)
                return {"command": command, "returncode": 0, "stdout": "", "stderr": ""}

            def fake_subprocess_run(command, **kwargs):
                preview_dir = Path(command[command.index("-OutputDirectory") + 1])
                preview_dir.mkdir(parents=True, exist_ok=True)
                for index in (1, 2):
                    Image.new("RGB", (160, 90), "white").save(preview_dir / f"slide-{index}.png")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            argv = [
                str(SCRIPT),
                str(source_dir),
                str(deck),
                str(pptx),
                "--out-dir",
                str(out_dir),
                "--compare-workers",
                "2",
                "--baseline-visual-dir",
                str(baseline),
            ]
            with (
                patch.object(self.module, "_run", side_effect=fake_run),
                patch.object(self.module.subprocess, "run", side_effect=fake_subprocess_run),
                patch.object(self.module.shutil, "disk_usage", return_value=SimpleNamespace(free=123)),
                patch.object(sys, "argv", argv),
            ):
                returncode = self.module.main()

            report = json.loads((out_dir / "final-visual-gate.json").read_text(encoding="utf-8"))
            self.assertEqual(returncode, 0)
            self.assertEqual(calls.count("layout_guard.py"), 1)
            self.assertEqual(
                [item["slide_id"] for item in report["visual_compare"]],
                ["S01", "S02"],
            )
            self.assertEqual(report["gates"]["relative_baseline"], "pass")
            self.assertEqual(report["gates"]["canvas_contract"], "pass")
            self.assertEqual(report["gates"]["renderer_immutable"], "pass")
            self.assertEqual(report["verdict"], "pass")

    def test_canvas_contract_rejects_powerpoint_width_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pptx = root / "normalized.pptx"
            write_minimal_pptx(pptx, cx=12192000, cy=6858000)

            report = self.module._pptx_canvas_contract(
                pptx,
                {"slide_width_in": 13.333, "slide_height_in": 7.5},
            )

            self.assertEqual(report["status"], "fail")
            self.assertIn("differs from the immutable deck contract", report["errors"][0])


if __name__ == "__main__":
    unittest.main()
