from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
import base64
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPOSER = ROOT / "autopptskills" / "scripts" / "compose_editable_pptx.mjs"


def _node_runtime() -> tuple[str, Path] | None:
    node = os.environ.get("RUNTIME_NODE") or shutil.which("node")
    module_root = os.environ.get("RUNTIME_NODE_MODULES")
    if node and module_root and (Path(module_root) / "pptxgenjs").exists():
        return node, Path(module_root)

    dependency_root = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
    )
    bundled_node = dependency_root / "node" / "bin" / "node.exe"
    bundled_modules = dependency_root / "node" / "node_modules"
    if bundled_node.exists() and (bundled_modules / "pptxgenjs").exists():
        return str(bundled_node), bundled_modules
    return None


def test_composer_maps_optional_text_and_shape_shadows_without_changing_defaults(
    tmp_path: Path,
) -> None:
    runtime = _node_runtime()
    if runtime is None:
        pytest.skip("PptxGenJS runtime is unavailable")
    node, module_root = runtime

    deck = {
        "slide_width_in": 13.333333,
        "slide_height_in": 7.5,
        "ref_width": 1600,
        "ref_height": 900,
        "units": "pixels",
        "slides": [
            {
                "shapes": [
                    {
                        "name": "shadowed-shape",
                        "type": "rounded_rect",
                        "x": 80,
                        "y": 80,
                        "w": 320,
                        "h": 160,
                        "fill": "FFFFFF",
                        "line": "123456",
                        "shadow": {
                            "type": "outer",
                            "color": "112233",
                            "opacity": 0.4,
                            "blur": 1.5,
                            "offset": 0,
                            "angle": 0,
                            "rotate_with_shape": True,
                        },
                    },
                    {
                        "name": "plain-shape",
                        "type": "rect",
                        "x": 440,
                        "y": 80,
                        "w": 160,
                        "h": 160,
                        "fill": "FFFFFF",
                        "line": "123456",
                    },
                ],
                "texts": [
                    {
                        "name": "shadowed-text",
                        "text": "Shadow",
                        "x": 80,
                        "y": 300,
                        "w": 320,
                        "h": 80,
                        "font": "Arial",
                        "size": 24,
                        "color": "FFFFFF",
                        "shadow": {
                            "type": "outer",
                            "color": "445566",
                            "opacity": 0.3,
                            "blur": 0.5,
                            "offset": 0,
                            "angle": 0,
                        },
                    },
                    {
                        "name": "plain-text",
                        "text": "Plain",
                        "x": 440,
                        "y": 300,
                        "w": 240,
                        "h": 80,
                        "font": "Arial",
                        "size": 24,
                        "color": "111111",
                    },
                ],
            }
        ],
    }
    deck_path = tmp_path / "deck.json"
    out_path = tmp_path / "shadow-probe.pptx"
    deck_path.write_text(json.dumps(deck), encoding="utf-8")

    env = os.environ.copy()
    env["NODE_PATH"] = str(module_root)
    completed = subprocess.run(
        [node, str(COMPOSER), str(deck_path), str(out_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    with zipfile.ZipFile(out_path) as archive:
        slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")

    assert slide_xml.count("<a:outerShdw") == 2
    assert 'val="112233"' in slide_xml
    assert 'val="445566"' in slide_xml
    assert slide_xml.count('dist="0"') == 2
    assert slide_xml.count('dir="60000"') == 2


def test_composer_sorts_native_shapes_by_explicit_z_index(tmp_path: Path) -> None:
    runtime = _node_runtime()
    if runtime is None:
        pytest.skip("PptxGenJS runtime is unavailable")
    node, module_root = runtime

    deck = {
        "slide_width_in": 13.333333,
        "slide_height_in": 7.5,
        "ref_width": 800,
        "ref_height": 450,
        "units": "pixels",
        "slides": [
            {
                "shapes": [
                    {
                        "name": "top-node",
                        "type": "rect",
                        "x": 200,
                        "y": 120,
                        "w": 160,
                        "h": 80,
                        "fill": "FFFFFF",
                        "line": "123456",
                        "z_index": 40,
                    },
                    {
                        "name": "back-panel",
                        "type": "rect",
                        "x": 80,
                        "y": 60,
                        "w": 500,
                        "h": 300,
                        "fill": "F4F5F6",
                        "line": "123456",
                        "z_index": 10,
                    },
                    {
                        "name": "middle-connector",
                        "type": "line",
                        "role": "connector",
                        "x": 120,
                        "y": 160,
                        "w": 360,
                        "h": 0,
                        "line": "123456",
                        "z_index": 20,
                    },
                ]
            }
        ],
    }
    deck_path = tmp_path / "deck.json"
    out_path = tmp_path / "z-index-probe.pptx"
    deck_path.write_text(json.dumps(deck), encoding="utf-8")

    env = os.environ.copy()
    env["NODE_PATH"] = str(module_root)
    completed = subprocess.run(
        [node, str(COMPOSER), str(deck_path), str(out_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["slides"][0]["native_shape_ordering"] == "explicit-z-index"
    with zipfile.ZipFile(out_path) as archive:
        slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")

    assert slide_xml.index('name="back-panel"') < slide_xml.index('name="middle-connector"')
    assert slide_xml.index('name="middle-connector"') < slide_xml.index('name="top-node"')


def test_composer_interleaves_bounded_images_and_native_outlines_by_z_index(
    tmp_path: Path,
) -> None:
    runtime = _node_runtime()
    if runtime is None:
        pytest.skip("PptxGenJS runtime is unavailable")
    node, module_root = runtime

    asset_path = tmp_path / "bounded.png"
    asset_path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL1WQAAAABJRU5ErkJggg=="
        )
    )
    deck = {
        "slide_width_in": 13.333333,
        "slide_height_in": 7.5,
        "ref_width": 800,
        "ref_height": 450,
        "units": "pixels",
        "slides": [
            {
                "icons": [
                    {
                        "name": "bounded-content",
                        "role": "movable-panel-content",
                        "file": str(asset_path),
                        "x": 100,
                        "y": 100,
                        "w": 300,
                        "h": 200,
                        "z_index": 20,
                    }
                ],
                "shapes": [
                    {
                        "name": "native-outline",
                        "type": "rounded_rect",
                        "role": "native-outline",
                        "x": 90,
                        "y": 90,
                        "w": 320,
                        "h": 220,
                        "line": "123456",
                        "z_index": 30,
                    }
                ],
            }
        ],
    }
    deck_path = tmp_path / "deck.json"
    out_path = tmp_path / "cross-layer-z-index.pptx"
    deck_path.write_text(json.dumps(deck), encoding="utf-8")

    env = os.environ.copy()
    env["NODE_PATH"] = str(module_root)
    completed = subprocess.run(
        [node, str(COMPOSER), str(deck_path), str(out_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["slides"][0]["foreground_object_ordering"] == "cross-layer-z-index"
    with zipfile.ZipFile(out_path) as archive:
        slide_xml = archive.read("ppt/slides/slide1.xml").decode("utf-8")

    assert slide_xml.index('name="bounded-content"') < slide_xml.index('name="native-outline"')
