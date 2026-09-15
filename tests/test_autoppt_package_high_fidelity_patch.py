from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "autopptskills" / "scripts" / "package_high_fidelity_patch.py"


def load_module():
    spec = importlib.util.spec_from_file_location("package_high_fidelity_patch", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_packages_paths_and_normalizes_pixel_canvas(tmp_path: Path) -> None:
    module = load_module()
    baseline_dir = tmp_path / "baseline"
    source_dir = tmp_path / "source"
    out_dir = tmp_path / "packaged"
    baseline_dir.mkdir()
    (source_dir / "assets").mkdir(parents=True)
    background = source_dir / "assets" / "background.png"
    icon = source_dir / "icon.png"
    mask = source_dir / "mask.png"
    background.write_bytes(b"background")
    icon.write_bytes(b"icon")
    mask.write_bytes(b"mask")

    baseline = {
        "units": "pixels",
        "ref_width": 1920,
        "ref_height": 1080,
        "slide_width_in": 13.333,
        "slide_height_in": 7.5,
        "assets_dir": str(baseline_dir),
        "slides": [{"slide_id": "S01"}],
    }
    source = {
        "units": "pixel",
        "ref_width": 1600,
        "ref_height": 900,
        "slide_width_in": 13.333333,
        "slide_height_in": 7.5,
        "assets_dir": str(source_dir),
        "slides": [
            {
                "slide_id": "S09",
                "background": "assets/background.png",
                "texts": [
                    {
                        "x": 100,
                        "y": 50,
                        "w": 200,
                        "h": 40,
                        "source_bbox": [100, 50, 200, 40],
                    }
                ],
                "icons": [
                    {
                        "file": str(icon),
                        "x": 400,
                        "y": 200,
                        "w": 80,
                        "h": 60,
                        "cleanup_mask": str(mask),
                        "cleanup_evidence": {"cleanup_mask": str(mask)},
                        "source_provenance": {
                            "source_file": str(icon),
                            "input_source_file": "../authoring-context/icon.png",
                            "resolved_input_source_file": str(icon),
                            "source_bbox": [10, 20, 30, 40],
                        },
                    }
                ],
            }
        ],
    }
    baseline_path = baseline_dir / "deck.json"
    source_path = source_dir / "deck.json"
    write_json(baseline_path, baseline)
    write_json(source_path, source)

    deck_path, report_path = module.package_patch(
        source_path, baseline_path, "S09", out_dir
    )

    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    slide = deck["slides"][0]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert deck["units"] == "pixels"
    assert deck["ref_width"] == 1920
    assert deck["slide_width_in"] == 13.333
    assert slide["texts"][0]["source_bbox"] == [120, 60, 240, 48]
    assert [slide["icons"][0][key] for key in ("x", "y", "w", "h")] == [
        480,
        240,
        96,
        72,
    ]
    assert slide["icons"][0]["source_provenance"]["source_bbox"] == [10, 20, 30, 40]
    assert not Path(slide["background"]).is_absolute()
    assert (out_dir / slide["background"]).is_file()
    assert (out_dir / slide["icons"][0]["file"]).is_file()
    assert slide["icons"][0]["cleanup_mask"] == slide["icons"][0]["cleanup_evidence"]["cleanup_mask"]
    assert (
        slide["icons"][0]["source_provenance"]["input_source_file"]
        == slide["icons"][0]["source_provenance"]["resolved_input_source_file"]
    )
    assert report["status"] == "pass"
    assert report["geometry_scale"] == {"x": 1.2, "y": 1.2}
    assert report["copied_file_count"] == 3
    assert len(report["rewritten_dependency_aliases"]) == 1
    assert report["unresolved_file_references"] == []


def test_rejects_unresolved_dependency_field(tmp_path: Path) -> None:
    module = load_module()
    baseline_dir = tmp_path / "baseline"
    source_dir = tmp_path / "source"
    out_dir = tmp_path / "packaged"
    baseline_dir.mkdir()
    source_dir.mkdir()
    background = source_dir / "background.png"
    background.write_bytes(b"background")
    baseline = {
        "units": "pixels",
        "ref_width": 1920,
        "ref_height": 1080,
        "slide_width_in": 13.333,
        "slide_height_in": 7.5,
        "assets_dir": str(baseline_dir),
        "slides": [{"slide_id": "S01"}],
    }
    source = {
        "units": "pixels",
        "ref_width": 1920,
        "ref_height": 1080,
        "slide_width_in": 13.333,
        "slide_height_in": 7.5,
        "assets_dir": str(source_dir),
        "slides": [
            {
                "slide_id": "S01",
                "background": str(background),
                "source_file": "../missing/source.png",
            }
        ],
    }
    baseline_path = baseline_dir / "deck.json"
    source_path = source_dir / "deck.json"
    write_json(baseline_path, baseline)
    write_json(source_path, source)

    with pytest.raises(RuntimeError, match="packaging failed"):
        module.package_patch(source_path, baseline_path, "S01", out_dir)

    report = json.loads((out_dir / "qa" / "package-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert report["unresolved_file_references"] == [
        {"json_path": "$.slides[0].source_file", "value": "../missing/source.png"}
    ]


def test_refuses_nonempty_output(tmp_path: Path) -> None:
    module = load_module()
    out_dir = tmp_path / "existing"
    out_dir.mkdir()
    (out_dir / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="already contains files"):
        module.package_patch(
            tmp_path / "source.json",
            tmp_path / "baseline.json",
            "S01",
            out_dir,
        )
