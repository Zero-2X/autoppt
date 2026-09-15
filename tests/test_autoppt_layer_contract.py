from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "autopptskills" / "scripts" / "layer_contract_gate.py"
REVIEW_CHECKS = (
    "background_is_single_continuous",
    "background_has_no_semantic_text",
    "background_has_no_duplicate_frame_lines",
    "background_has_no_semantic_object_footprints",
    "simple_frames_match_native_shapes",
    "bounded_assets_match_source",
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class LayerContractGateTest(unittest.TestCase):
    def prepare(
        self,
        root: Path,
        *,
        tiled: bool = False,
        residual_frame: bool = False,
        native_line: bool = False,
        residual_line: bool = False,
        corrupt_background: bool = False,
        panel_frame_id: str = "frame-S01-001",
    ) -> tuple[list[str], Path, Path]:
        background = root / "background.png"
        panel = root / "panel.png"
        cleanup_mask = root / "frame-cleanup-mask.png"
        frame_bbox = [100, 200, 300, 180]
        line_color = "235546"
        background_image = Image.new("RGB", (960, 540), "#F4F5F6")
        if residual_frame:
            draw = ImageDraw.Draw(background_image)
            draw.rounded_rectangle(
                [100, 200, 399, 379],
                radius=10,
                outline=f"#{line_color}",
                width=6,
            )
        if residual_line:
            ImageDraw.Draw(background_image).line(
                [(500, 270), (680, 270)],
                fill="#C95D16",
                width=6,
            )
        background_image.save(background)
        if corrupt_background:
            background.write_bytes(b"not-a-png")
        Image.new("RGBA", (300, 180), (255, 255, 255, 0)).save(panel)
        mask_image = Image.new("L", (960, 540), 0)
        ImageDraw.Draw(mask_image).rounded_rectangle(
            [96, 196, 403, 383],
            radius=14,
            outline=255,
            width=12,
        )
        mask_image.save(cleanup_mask)
        pptx = root / "final.pptx"
        pptx.write_bytes(b"pptx")
        icons = [
            {
                "name": "panel-content",
                "file": str(panel.resolve()),
                "x": 100,
                "y": 200,
                "w": 300,
                "h": 180,
                "source_bbox": [100, 200, 300, 180],
                "frame_bbox": frame_bbox,
                "frame_id": panel_frame_id,
                "cleanup_mask": str(cleanup_mask.resolve()),
                "mask_bbox": [0, 0, 960, 540],
                "cleanup_evidence": {
                    "status": "pass",
                    "cleanup_mask": str(cleanup_mask.resolve()),
                    "mask_bbox": [0, 0, 960, 540],
                    "line_color": line_color,
                    "post_cleanup_support": 0.0,
                    "residual_ratio": 0.0,
                },
                "editability_level": "movable-image",
                "role": "movable-panel-content",
            }
        ]
        if tiled:
            icons.append(
                {
                    "name": "hf-tile-r0-c0",
                    "file": str(background.resolve()),
                    "x": 0,
                    "y": 0,
                    "w": 960,
                    "h": 540,
                    "source_bbox": [0, 0, 960, 540],
                    "editability_level": "movable-image",
                    "role": "pixel-anchored-background-tile",
                }
            )
        deck = root / "deck-high-fidelity.json"
        write_json(
            deck,
            {
                "title": "test",
                "ref_width": 960,
                "ref_height": 540,
                "assets_dir": str(root.resolve()),
                "slides": [
                    {
                        "slide_id": "S01",
                        "background": str(background.resolve()),
                        "texts": [
                            {
                                "name": "title",
                                "text": "结论标题",
                                "x": 80,
                                "y": 40,
                                "w": 800,
                                "h": 80,
                                "source_bbox": [80, 40, 800, 80],
                                "editability_level": "native",
                            }
                        ],
                        "shapes": [
                            {
                                "name": "panel-frame",
                                "type": "rounded_rect",
                                "x": 100,
                                "y": 200,
                                "w": 300,
                                "h": 180,
                                "source_bbox": [100, 200, 300, 180],
                                "frame_bbox": frame_bbox,
                                "frame_id": "frame-S01-001",
                                "line_color": line_color,
                                "line_width_px": 6,
                                "cleanup_mask": str(cleanup_mask.resolve()),
                                "mask_bbox": [0, 0, 960, 540],
                                "cleanup_evidence": {
                                    "status": "pass",
                                    "cleanup_mask": str(cleanup_mask.resolve()),
                                    "mask_bbox": [0, 0, 960, 540],
                                    "line_color": line_color,
                                    "post_cleanup_support": 0.0,
                                    "residual_ratio": 0.0,
                                },
                                "editability_level": "native",
                                "role": "measured-flat-panel",
                            }
                        ],
                        "icons": icons,
                    }
                ],
            },
        )
        if native_line:
            line_cleanup_mask = root / "line-cleanup-mask.png"
            line_mask_image = Image.new("L", (960, 540), 0)
            ImageDraw.Draw(line_mask_image).line(
                [(500, 270), (680, 270)],
                fill=255,
                width=14,
            )
            line_mask_image.save(line_cleanup_mask)
            payload = json.loads(deck.read_text(encoding="utf-8"))
            payload["slides"][0]["shapes"].append(
                {
                    "name": "process-connector",
                    "type": "connector",
                    "x": 500,
                    "y": 270,
                    "w": 180,
                    "h": 1,
                    "x1": 500,
                    "y1": 270,
                    "x2": 680,
                    "y2": 270,
                    "source_bbox": [500, 270, 180, 1],
                    "line": "C95D16",
                    "line_color": "C95D16",
                    "line_width_px": 6,
                    "cleanup_mask": str(line_cleanup_mask.resolve()),
                    "cleanup_evidence": {
                        "status": "pass",
                        "cleanup_mask": str(line_cleanup_mask.resolve()),
                        "line_color": "C95D16",
                        "post_cleanup_support": 0.0,
                        "residual_ratio": 0.0,
                    },
                    "editability_level": "native",
                    "role": "connector",
                    "requires_background_cleanup": True,
                }
            )
            write_json(deck, payload)
        review = root / "layer-review.json"
        report = root / "layer-contract-report.json"
        command = [
            str(SCRIPT),
            str(deck),
            "--pptx",
            str(pptx),
            "--review",
            str(review),
            "--out",
            str(report),
        ]
        return command, review, report

    def add_three_layer_compound(
        self,
        root: Path,
        command: list[str],
        *,
        variant: str = "valid",
    ) -> None:
        deck = Path(command[1])
        payload = json.loads(deck.read_text(encoding="utf-8"))
        cleanup_mask = root / "compound-cleanup-mask.png"
        mask_image = Image.new("L", (960, 540), 0)
        ImageDraw.Draw(mask_image).rounded_rectangle(
            [500, 150, 839, 369],
            radius=18,
            fill=255,
        )
        mask_image.save(cleanup_mask)
        outer_id = "frame-S01-compound-outer"
        outer = {
            "name": "compound-outer",
            "frame_id": outer_id,
            "type": "rounded_rect",
            "x": 504,
            "y": 154,
            "w": 332,
            "h": 212,
            "source_bbox": [500, 150, 340, 220],
            "layout_bbox": [504, 154, 332, 212],
            "frame_bbox": [504, 154, 332, 212],
            "line": "082C5D",
            "line_color": "082C5D",
            "line_width_px": 4,
            "background_cleanup": "full-frame-directional",
            "requires_background_cleanup": True,
            "cleanup_mask": str(cleanup_mask.resolve()),
            "mask_bbox": [0, 0, 960, 540],
            "cleanup_evidence": {
                "status": "pass",
                "method": "full-frame-directional",
                "cleanup_mask": str(cleanup_mask.resolve()),
                "mask_bbox": [0, 0, 960, 540],
                "line_color": "082C5D",
                "post_cleanup_support": 0.0,
                "residual_ratio": 0.0,
            },
            "compound_layer": "outer",
            "z_order_within_compound": 0,
            "editability_level": "native-reviewed",
            "role": "measured-semantic-frame-compound-outer",
        }
        middle = {
            "name": "compound-middle",
            "frame_id": "frame-S01-compound-middle",
            "type": "rounded_rect",
            "x": 510,
            "y": 160,
            "w": 320,
            "h": 200,
            "source_bbox": [510, 160, 320, 200],
            "layout_bbox": [510, 160, 320, 200],
            "frame_bbox": [510, 160, 320, 200],
            "line": "FFFFFF",
            "line_color": "FFFFFF",
            "line_width_px": 2,
            "background_cleanup": "none",
            "requires_background_cleanup": False,
            "cleanup_delegated_to": outer_id,
            "compound_layer": "middle",
            "z_order_within_compound": 1,
            "allow_raster_background_frame": True,
            "editability_level": "native-reviewed",
            "role": "measured-semantic-frame-compound-middle",
        }
        inner = {
            "name": "compound-inner",
            "frame_id": "frame-S01-compound-inner",
            "type": "rounded_rect",
            "x": 520,
            "y": 170,
            "w": 300,
            "h": 180,
            "source_bbox": [520, 170, 300, 180],
            "layout_bbox": [520, 170, 300, 180],
            "frame_bbox": [520, 170, 300, 180],
            "line": "082C5D",
            "line_color": "082C5D",
            "line_width_px": 2,
            "background_cleanup": "none",
            "requires_background_cleanup": False,
            "cleanup_delegated_to": outer_id,
            "compound_layer": "inner",
            "z_order_within_compound": 2,
            "editability_level": "native-reviewed",
            "role": "measured-semantic-frame-compound-inner",
        }
        if variant == "missing-parent":
            middle["cleanup_delegated_to"] = "frame-S01-compound-missing"
        elif variant == "failed-parent":
            outer["cleanup_evidence"]["status"] = "fail"
        elif variant == "outside-parent":
            inner.update(
                {
                    "x": 820,
                    "source_bbox": [820, 170, 120, 180],
                    "layout_bbox": [820, 170, 120, 180],
                    "frame_bbox": [820, 170, 120, 180],
                }
            )
        elif variant == "invalid-z-order":
            inner["z_order_within_compound"] = 1
        elif variant == "invalid-layer":
            inner["compound_layer"] = "middle"
        elif variant == "allow-only":
            middle.pop("cleanup_delegated_to")
        elif variant != "valid":
            raise ValueError(f"unsupported compound variant: {variant}")
        payload["slides"][0]["shapes"].extend([outer, middle, inner])
        write_json(deck, payload)

    def add_reviewed_panel(
        self,
        root: Path,
        command: list[str],
        *,
        variant: str = "valid",
    ) -> None:
        deck = Path(command[1])
        payload = json.loads(deck.read_text(encoding="utf-8"))
        frame_id = "frame-S01-reviewed-001"
        frame_bbox = [500, 80, 320, 240]
        content_bbox = [540, 120, 240, 160]
        line_color = "0B5A45"
        cleanup_mask = root / "reviewed-panel-cleanup-mask.png"
        mask_image = Image.new("L", (960, 540), 0)
        draw = ImageDraw.Draw(mask_image)
        if variant == "outline-only":
            draw.rounded_rectangle(
                [500, 80, 819, 319], radius=16, outline=255, width=10
            )
        else:
            draw.rounded_rectangle([494, 74, 825, 325], radius=20, fill=255)
        mask_image.save(cleanup_mask)

        source = root / "reviewed-panel-source.png"
        Image.new("RGBA", (120, 80), (40, 90, 180, 255)).save(source)
        content = root / "reviewed-panel-content.png"
        Image.new("RGBA", (240, 160), (40, 90, 180, 255)).save(content)
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        content_sha = hashlib.sha256(content.read_bytes()).hexdigest()
        frame = {
            "name": "reviewed-panel-frame",
            "frame_id": frame_id,
            "type": "rounded_rect",
            "x": frame_bbox[0],
            "y": frame_bbox[1],
            "w": frame_bbox[2],
            "h": frame_bbox[3],
            "source_bbox": frame_bbox,
            "layout_bbox": frame_bbox,
            "frame_bbox": frame_bbox,
            "content_bbox": content_bbox,
            "fill": "F8FAFC",
            "opacity": 1.0,
            "line": line_color,
            "line_color": line_color,
            "line_width": 1.2,
            "line_width_px": 4,
            "background_cleanup": "full-frame-directional",
            "background_cleanup_scope": "full-semantic-panel",
            "requires_background_cleanup": True,
            "cleanup_mask": str(cleanup_mask.resolve()),
            "mask_bbox": [0, 0, 960, 540],
            "cleanup_evidence": {
                "status": "pass",
                "method": "reviewed-panel-full-region-directional",
                "cleanup_mask": str(cleanup_mask.resolve()),
                "mask_bbox": [0, 0, 960, 540],
                "line_color": line_color,
                "post_cleanup_support": 0.0,
                "residual_ratio": 0.0,
                "background_cleanup_scope": "full-semantic-panel",
                "content_bbox": content_bbox,
                "semantic_content_coverage": 1.0,
            },
            "reviewed_panel": True,
            "editability_level": "native-reviewed",
            "role": "reviewed-semantic-frame",
        }
        asset = {
            "name": "reviewed-panel-content",
            "file": str(content.resolve()),
            "x": content_bbox[0],
            "y": content_bbox[1],
            "w": content_bbox[2],
            "h": content_bbox[3],
            "source_bbox": content_bbox,
            "layout_bbox": content_bbox,
            "content_bbox": content_bbox,
            "content_source_bbox": [0, 0, 120, 80],
            "frame_bbox": frame_bbox,
            "frame_id": frame_id,
            "cleanup_mask": str(cleanup_mask.resolve()),
            "mask_bbox": [0, 0, 960, 540],
            "cleanup_evidence": frame["cleanup_evidence"],
            "background_cleanup_scope": "full-semantic-panel",
            "source_provenance": {
                "kind": "external-source-crop",
                "input_source_file": "sources/reviewed-panel-source.png",
                "override_file": str((root / "reviewed-overrides.json").resolve()),
                "resolution_strategy": "relative-to-override-json-directory-copied-into-run",
                "source_file": str(source.resolve()),
                "source_sha256": source_sha,
                "source_dimensions": [120, 80],
                "source_bbox": [0, 0, 120, 80],
            },
            "asset_sha256": content_sha,
            "reviewed_panel": True,
            "editability_level": "movable-image",
            "role": "movable-panel-content",
        }
        if variant == "missing-source":
            asset["source_provenance"]["source_file"] = str(
                (root / "missing-source.png").resolve()
            )
        elif variant == "out-of-bounds":
            invalid_content_bbox = [780, 120, 100, 160]
            asset.update(
                {
                    "x": invalid_content_bbox[0],
                    "y": invalid_content_bbox[1],
                    "w": invalid_content_bbox[2],
                    "h": invalid_content_bbox[3],
                    "source_bbox": invalid_content_bbox,
                    "layout_bbox": invalid_content_bbox,
                    "content_bbox": invalid_content_bbox,
                }
            )
        elif variant not in {"valid", "outline-only"}:
            raise ValueError(f"unsupported reviewed panel variant: {variant}")
        payload["slides"][0]["shapes"].append(frame)
        payload["slides"][0]["icons"].append(asset)
        write_json(deck, payload)

    def test_missing_review_creates_pending_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command, review, report = self.prepare(Path(tmp))
            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            template = json.loads(review.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(payload["verdict"], "blocked")
            self.assertEqual(payload["structural"]["status"], "pass")
            self.assertEqual(template["verdict"], "pending")

    def test_reviewed_continuous_layer_contract_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command, review, report = self.prepare(Path(tmp))
            subprocess.run([sys.executable, *command], capture_output=True, text=True)
            template = json.loads(review.read_text(encoding="utf-8"))
            template["verdict"] = "pass"
            template["slides"][0]["status"] = "pass"
            template["slides"][0]["checks"] = {
                check: "pass" for check in REVIEW_CHECKS
            }
            write_json(review, template)
            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(payload["verdict"], "pass")
            self.assertEqual(payload["totals"]["backgrounds"], 1)
            self.assertEqual(payload["totals"]["background_tiles"], 0)
            self.assertEqual(payload["totals"]["frame_shapes"], 1)

    def test_strict_mode_accepts_reviewed_panel_with_external_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command, _, report = self.prepare(root)
            self.add_reviewed_panel(root, command)

            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            reviewed_audits = payload["slides"][0]["reviewed_panel_audits"]
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(payload["structural"]["status"], "pass")
            self.assertEqual(len(reviewed_audits), 1)
            self.assertEqual(reviewed_audits[0]["status"], "pass")
            self.assertEqual(
                reviewed_audits[0]["source_provenance_kind"],
                "external-source-crop",
            )
            self.assertGreaterEqual(reviewed_audits[0]["frame_mask_coverage"], 0.70)
            self.assertGreaterEqual(reviewed_audits[0]["content_mask_coverage"], 0.98)

    def test_strict_mode_rejects_invalid_reviewed_panel_contracts(self) -> None:
        cases = {
            "missing-source": "provenance source file is missing",
            "out-of-bounds": "content_bbox is outside the bound native frame",
            "outline-only": "semantic content area",
        }
        for variant, expected_error in cases.items():
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                command, _, report = self.prepare(root)
                self.add_reviewed_panel(root, command, variant=variant)

                completed = subprocess.run(
                    [sys.executable, *command], capture_output=True, text=True
                )
                payload = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(payload["verdict"], "fail")
                self.assertIn(
                    expected_error,
                    " ".join(payload["structural"]["errors"]),
                )

    def test_existing_automatic_panel_path_has_no_reviewed_panel_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command, _, report = self.prepare(Path(tmp))
            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            slide = payload["slides"][0]

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(payload["structural"]["status"], "pass")
            self.assertEqual(slide["panel_content_assets"], 1)
            self.assertEqual(slide["reviewed_panel_assets"], 0)
            self.assertEqual(slide["reviewed_panel_audits"], [])

    def test_strict_mode_rejects_background_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command, _, report = self.prepare(Path(tmp), tiled=True)
            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(payload["verdict"], "fail")
            self.assertIn("background tile is forbidden", " ".join(payload["structural"]["errors"]))

    def test_strict_mode_rejects_duplicate_frame_pixels_in_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command, _, report = self.prepare(Path(tmp), residual_frame=True)
            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(payload["verdict"], "fail")
            self.assertIn(
                "duplicate frame line remains in background",
                " ".join(payload["structural"]["errors"]),
            )

    def test_strict_mode_accepts_native_connector_with_clean_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command, review, report = self.prepare(Path(tmp), native_line=True)
            subprocess.run([sys.executable, *command], capture_output=True, text=True)
            template = json.loads(review.read_text(encoding="utf-8"))
            template["verdict"] = "pass"
            template["slides"][0]["status"] = "pass"
            template["slides"][0]["checks"] = {
                check: "pass" for check in REVIEW_CHECKS
            }
            write_json(review, template)

            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            line_audits = payload["slides"][0]["line_cleanup_audits"]
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(payload["verdict"], "pass")
            self.assertEqual(len(line_audits), 1)
            self.assertEqual(line_audits[0]["name"], "process-connector")
            self.assertEqual(line_audits[0]["status"], "pass")
            self.assertGreaterEqual(line_audits[0]["mask_coverage"], 0.95)
            self.assertEqual(line_audits[0]["background_frame_support"], 0.0)

    def test_strict_mode_rejects_native_connector_pixels_in_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command, _, report = self.prepare(
                Path(tmp), native_line=True, residual_line=True
            )
            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            line_audits = payload["slides"][0]["line_cleanup_audits"]
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(payload["verdict"], "fail")
            self.assertEqual(len(line_audits), 1)
            self.assertEqual(line_audits[0]["status"], "fail")
            self.assertGreater(line_audits[0]["background_frame_support"], 0.12)
            self.assertIn(
                "duplicate native line remains in background",
                " ".join(payload["structural"]["errors"]),
            )

    def test_strict_mode_accepts_three_layer_delegated_compound_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command, _, report = self.prepare(root)
            self.add_three_layer_compound(root, command)

            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            audits = payload["slides"][0]["frame_cleanup_audits"]
            delegated = [item for item in audits if item.get("cleanup_delegated_to")]
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(payload["structural"]["status"], "pass")
            self.assertEqual(len(delegated), 2)
            self.assertTrue(all(item["status"] == "pass" for item in delegated))

    def test_strict_mode_rejects_invalid_delegated_compound_cleanup(self) -> None:
        cases = {
            "missing-parent": "cleanup delegate does not bind to exactly one native frame",
            "failed-parent": "cleanup delegate did not pass direct cleanup audit",
            "outside-parent": "layout_bbox is outside delegated cleanup region",
            "invalid-z-order": "compound layer z-order is not strictly increasing",
            "invalid-layer": "compound cleanup group contains duplicate layers",
            "allow-only": "allow_raster_background_frame cannot satisfy strict cleanup",
        }
        for variant, expected_error in cases.items():
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                command, _, report = self.prepare(root)
                self.add_three_layer_compound(root, command, variant=variant)

                completed = subprocess.run(
                    [sys.executable, *command], capture_output=True, text=True
                )
                payload = json.loads(report.read_text(encoding="utf-8"))
                errors = " ".join(payload["structural"]["errors"])
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(payload["verdict"], "fail")
                self.assertIn(expected_error, errors)

    def test_panel_content_requires_exact_frame_id_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command, _, report = self.prepare(
                Path(tmp), panel_frame_id="frame-S01-wrong"
            )
            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(payload["verdict"], "fail")
            self.assertIn(
                "does not bind to exactly one native frame",
                " ".join(payload["structural"]["errors"]),
            )

    def test_corrupt_png_background_fails_structural_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command, _, report = self.prepare(Path(tmp), corrupt_background=True)
            completed = subprocess.run(
                [sys.executable, *command], capture_output=True, text=True
            )
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(payload["verdict"], "fail")
            self.assertIn(
                "background image decode failed",
                " ".join(payload["structural"]["errors"]),
            )


if __name__ == "__main__":
    unittest.main()
