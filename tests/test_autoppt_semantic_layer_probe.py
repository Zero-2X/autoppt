from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "autopptskills" / "scripts" / "build_semantic_layer_probe.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_semantic_layer_probe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_profile_inheritance_merges_objects_and_replaces_lists(tmp_path: Path) -> None:
    module = load_module()
    parent = tmp_path / "parent.json"
    child = tmp_path / "child.json"
    write_json(
        parent,
        {
            "schema_version": 1,
            "slide_id": "S09",
            "source_image": "source.png",
            "texts": [{"name": "parent-title", "text": "parent"}],
            "native": {
                "panels": [{"name": "panel-a"}],
                "rectangles": [{"name": "node-a"}],
            },
            "bounded_asset_overrides": {
                "asset-a": {"layout_bbox": [1, 2, 3, 4], "keep_feather": 0.2}
            },
        },
    )
    write_json(
        child,
        {
            "extends": parent.name,
            "texts": [{"name": "child-title", "text": "child"}],
            "native": {"rectangles_append": [{"name": "node-b"}]},
            "bounded_asset_overrides": {"asset-a": {"keep_feather": 0.8}},
        },
    )

    resolved = module.load_profile(child)

    assert resolved["texts"] == [{"name": "child-title", "text": "child"}]
    assert resolved["native"]["panels"] == [{"name": "panel-a"}]
    assert resolved["native"]["rectangles"] == [{"name": "node-a"}]
    assert resolved["native"]["rectangles_append"] == [{"name": "node-b"}]
    assert resolved["bounded_asset_overrides"]["asset-a"] == {
        "layout_bbox": [1, 2, 3, 4],
        "keep_feather": 0.8,
    }
    assert "extends" not in resolved


def test_build_probe_records_provenance_local_cleanup_and_immutability(
    tmp_path: Path,
) -> None:
    module = load_module()
    source = tmp_path / "source.png"
    image = Image.new("RGB", (40, 30), "#224466")
    ImageDraw.Draw(image).rectangle((5, 5, 24, 19), fill="#CC3300")
    image.save(source)
    source_hash = sha256(source)

    profile = tmp_path / "profile.json"
    write_json(
        profile,
        {
            "schema_version": 1,
            "slide_id": "S01",
            "source_image": source.name,
            "expected_source_sha256": source_hash,
            "ref_width": 40,
            "ref_height": 30,
            "background": {
                "center_color": "F8FAFC",
                "edge_color": "F8FAFC",
                "top_color": "F8FAFC",
                "bottom_color": "F8FAFC",
                "vertical_mix": 0,
            },
            "semantic_cleanup_regions": [{"bbox": [0, 0, 20, 15], "radius": 2}],
            "bounded_assets": [
                {
                    "name": "asset-one",
                    "source_bbox": [5, 5, 20, 15],
                    "layout_bbox": [7, 6, 20, 15],
                    "frame_id": "frame-S01-one",
                    "frame_bbox": [1, 1, 30, 20],
                    "z_index": 23,
                    "erase_regions": [[1, 1, 2, 2]],
                    "erase_fill": "FFFFFF",
                    "keep_polygons": [[[0, 0], [19, 0], [0, 14]]],
                    "keep_feather": 0,
                }
            ],
            "native": {
                "panels": [
                    {
                        "name": "native-panel",
                        "type": "rounded_rect",
                        "bbox": [1, 1, 30, 20],
                        "frame_id": "frame-S01-one",
                        "corner_adjustment": 0.08,
                        "header_bbox": [1, 1, 30, 5],
                        "header_type": "rounded_rect",
                        "header_corner_adjustment": 0.08,
                    }
                ],
                "raw_shapes": [
                    {
                        "name": "native-node",
                        "type": "rect",
                        "source_bbox": [2, 20, 8, 5],
                        "z_index": 17,
                    }
                ]
            },
            "texts": [],
        },
    )
    out_dir = tmp_path / "probe-v1"

    report = module.build_probe(profile, out_dir)

    assert report["immutable_output"] is True
    assert report["source_sha256"] == source_hash
    assert report["bounded_assets"] == 1
    cleanup = Image.open(out_dir / "assets" / "semantic-cleanup-mask.png")
    assert cleanup.getpixel((5, 5)) == 255
    assert cleanup.getpixel((30, 25)) == 0

    deck = json.loads((out_dir / "deck-high-fidelity.json").read_text(encoding="utf-8"))
    icon = deck["slides"][0]["icons"][0]
    asset = Path(icon["file"])
    rendered = Image.open(asset).convert("RGBA")
    assert rendered.getpixel((1, 1))[:3] == (255, 255, 255)
    assert rendered.getpixel((1, 1))[3] == 255
    assert rendered.getpixel((19, 14))[3] == 0
    assert icon["source_bbox"] == [5, 5, 20, 15]
    assert icon["layout_bbox"] == [7, 6, 20, 15]
    assert icon["frame_id"] == "frame-S01-one"
    assert icon["frame_bbox"] == [1, 1, 30, 20]
    assert icon["z_index"] == 23
    assert icon["asset_sha256"] == sha256(asset)
    provenance = icon["source_provenance"]
    assert provenance["verified_imagegen_master"] is True
    assert provenance["original_source_sha256"] == source_hash
    assert provenance["source_sha256"] == report["source_master_sha256"]
    assert provenance["derived_transform"]["kind"] == "reviewed-local-semantic-cleanup"
    assert provenance["derived_transform"]["keep_polygons_local"]
    shapes = deck["slides"][0]["shapes"]
    assert shapes[0]["corner_adjustment"] == 0.08
    assert shapes[1]["corner_adjustment"] == 0.08
    assert shapes[0]["name"].endswith("__ca_0.0800")
    assert shapes[1]["name"].endswith("__ca_0.0800")
    assert shapes[-1]["z_index"] == 17

    with pytest.raises(FileExistsError, match="immutable probe output already exists"):
        module.build_probe(profile, out_dir)


def test_robust_polynomial_source_background_removes_masked_semantics(
    tmp_path: Path,
) -> None:
    import numpy as np

    module = load_module()
    width, height = 120, 80
    x_axis = np.linspace(-1.0, 1.0, width, dtype=np.float32)
    y_axis = np.linspace(-1.0, 1.0, height, dtype=np.float32)
    grid_x, grid_y = np.meshgrid(x_axis, y_axis)
    base = np.stack(
        [
            246.0 + 2.0 * grid_x + 1.5 * grid_y,
            248.0 + 1.0 * grid_x + 1.0 * grid_y,
            250.0 + 0.5 * grid_x + 1.0 * grid_y,
        ],
        axis=2,
    )
    base = np.clip(np.rint(base), 0, 255).astype(np.uint8)
    source_pixels = base.copy()
    source_pixels[8:15, 10:110] = [20, 50, 120]
    source_pixels[28:68, 18:52] = [235, 238, 243]
    source_pixels[28:68, 68:102] = [232, 236, 241]
    source = tmp_path / "source.png"
    Image.fromarray(source_pixels, "RGB").save(source)

    profile = tmp_path / "profile.json"
    write_json(
        profile,
        {
            "schema_version": 1,
            "slide_id": "S01",
            "source_image": source.name,
            "expected_source_sha256": sha256(source),
            "ref_width": width,
            "ref_height": height,
            "background": {
                "mode": "robust_polynomial_source",
                "polynomial": {
                    "degree": 2,
                    "sample_stride_px": 3,
                    "robust_iterations": 3,
                    "prefilter_sigma_px": 0,
                    "fit_exclusion_padding_px": 2,
                },
            },
            "semantic_cleanup_regions": [
                {"bbox": [10, 8, 100, 7]},
                {"bbox": [18, 28, 34, 40]},
                {"bbox": [68, 28, 34, 40]},
            ],
            "bounded_assets": [],
            "native": {},
            "texts": [],
        },
    )
    out_dir = tmp_path / "probe-polynomial"

    report = module.build_probe(profile, out_dir)

    background = np.asarray(
        Image.open(out_dir / "assets" / "continuous-background.png").convert("RGB")
    )
    assert float(np.mean(np.abs(background.astype(float) - base.astype(float)))) < 1.5
    background_report = json.loads(
        (out_dir / "assets" / "background-build-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert background_report["mode"] == "robust_polynomial_source"
    assert background_report["source_overlay_count"] == 0
    assert background_report["sample_count"] > 0
    assert report["background_method"] == (
        "robust-total-degree-polynomial-from-imagegen-master"
    )


def test_semantic_probe_rejects_unknown_background_mode() -> None:
    module = load_module()
    source = Image.new("RGB", (20, 12), "#FFFFFF")
    mask = Image.new("L", source.size, 0)

    with pytest.raises(ValueError, match="unsupported semantic probe background mode"):
        module.create_continuous_background(source, mask, {"mode": "mystery"})


def test_finalize_review_emits_every_layer_contract_check_and_hash(tmp_path: Path) -> None:
    module = load_module()
    deck = tmp_path / "deck.json"
    pptx = tmp_path / "deck.pptx"
    review = tmp_path / "layer-review.json"
    write_json(deck, {"slides": [{"slide_id": "S09"}]})
    pptx.write_bytes(b"pptx-test")

    payload = module.finalize_review(deck, pptx, review, "reviewed at full size")

    assert payload["deck_sha256"] == sha256(deck)
    assert payload["pptx_sha256"] == sha256(pptx)
    assert payload["slides"][0]["status"] == "pass"
    assert payload["slides"][0]["checks"] == {
        check: "pass" for check in module.REVIEW_CHECKS
    }
    assert "background_has_no_semantic_object_footprints" in payload["slides"][0]["checks"]
    assert json.loads(review.read_text(encoding="utf-8")) == payload
