from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "autopptskills" / "scripts" / "build_high_fidelity_reconstruction.py"
LAYER_GATE = ROOT / "autopptskills" / "scripts" / "layer_contract_gate.py"


def load_module():
    spec = importlib.util.spec_from_file_location("autoppt_high_fidelity", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HighFidelityReconstructionHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_color_bucket_preserves_measured_dark_academic_colors(self) -> None:
        self.assertEqual(self.module.color_bucket("062050"), "062050")
        self.assertEqual(self.module.color_bucket("0B505C"), "0B505C")
        self.assertEqual(self.module.color_bucket("B23E2B"), "B23E2B")

    def test_build_source_notes_from_outline_metadata(self) -> None:
        notes = self.module.build_source_notes(
            {
                "speaker_note_source_refs": ["paragraph-0001", "table-001"],
                "evidence_refs": ["EV-IDENTITY"],
                "recommended_media": [{"media_id": "media-001"}],
                "claim_boundary": "Do not overclaim.",
            },
            {
                "document": "C:/source/thesis.docx",
                "source_sha256": "abc123",
            },
        )

        self.assertTrue(notes.startswith("[Sources]\n"))
        self.assertIn("thesis.docx | SHA256 abc123", notes)
        self.assertIn("paragraph-0001, table-001", notes)
        self.assertIn("EV-IDENTITY", notes)
        self.assertIn("media-001", notes)
        self.assertIn("Do not overclaim.", notes)

    def test_build_source_notes_preserves_authored_notes(self) -> None:
        self.assertEqual(
            self.module.build_source_notes({"notes": "[Sources]\n- authored"}, {}),
            "[Sources]\n- authored",
        )

    def test_color_runs_collapse_near_word_noise_to_one_measured_color(self) -> None:
        words = [
            {"text": char, "bbox": {"x": index * 10, "y": 0, "w": 8, "h": 12}}
            for index, char in enumerate("判不准：")
        ]
        measured = ["AB2F1D", "AE3625", "A9321F", "AB2D1A"]
        with mock.patch.object(self.module, "foreground_color", side_effect=measured):
            runs, color = self.module.color_runs_for_line(
                "判不准：",
                {"words": words},
                image=None,
                np=None,
                words=words,
            )

        self.assertIsNone(runs)
        self.assertEqual(color, "AB2F1D")

    def test_surplus_numeric_ocr_fragment_does_not_duplicate_reference(self) -> None:
        lines = [
            {
                "bbox": {"x": 10, "y": 10, "w": 80, "h": 20},
                "words": [{"text": "primary", "bbox": {"x": 10, "y": 10, "w": 80, "h": 20}}],
            },
            {
                "bbox": {"x": 95, "y": 10, "w": 20, "h": 20},
                "words": [{"text": "stray", "bbox": {"x": 95, "y": 10, "w": 20, "h": 20}}],
            },
        ]

        with (
            mock.patch.object(
                self.module,
                "split_horizontal_word_clusters",
                side_effect=lambda line: [line["words"]],
            ),
            mock.patch.object(self.module, "numeric_tokens", return_value=["1"]),
            mock.patch.object(
                self.module,
                "compact_numeric_cluster",
                side_effect=lambda words, _expected: words[0]["text"],
            ),
            mock.patch.object(
                self.module,
                "aligned_words",
                side_effect=lambda _display, payload: payload["words"],
            ),
            mock.patch.object(
                self.module,
                "extend_numeric_words",
                side_effect=lambda words, _aligned, _expected: words,
            ),
            mock.patch.object(self.module, "expected_numeric_chunks", return_value=["MOTA 0.872"]),
            mock.patch.object(
                self.module,
                "render_expected_numeric_segment",
                side_effect=lambda _observed, chunks: chunks[0],
            ),
            mock.patch.object(self.module, "trailing_expected_punctuation", return_value=""),
        ):
            result = self.module.numeric_ocr_segments(lines, "MOTA 0.872")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "MOTA 0.872")

    def test_panel_exclusion_requires_reason_and_matches_measured_bbox(self) -> None:
        payload = {
            "slides": {
                "S01": {
                    "panel_exclusions": [
                        {
                            "bbox": [100, 200, 300, 80],
                            "reason": "reviewed false-positive panel",
                        }
                    ]
                }
            }
        }
        self.module.validate_override_payloads(payload)
        self.assertTrue(
            self.module.panel_matches_exclusion(
                {"bbox": [104, 196, 298, 84]},
                payload["slides"]["S01"]["panel_exclusions"][0],
            )
        )

        payload["slides"]["S01"]["panel_exclusions"][0]["reason"] = ""
        with self.assertRaisesRegex(ValueError, "auditable reason"):
            self.module.validate_override_payloads(payload)

    def test_cleanup_regions_merge_across_review_files(self) -> None:
        merged = self.module.merge_override_payloads(
            {
                "slides": {
                    "S14": {
                        "cleanup_regions": [
                            {
                                "mask_bbox": [10, 20, 30, 40],
                                "reason": "first residue",
                            }
                        ]
                    }
                }
            },
            {
                "slides": {
                    "S14": {
                        "cleanup_regions": [
                            {
                                "mask_bbox": [50, 60, 70, 80],
                                "reason": "second residue",
                            }
                        ]
                    }
                }
            },
        )

        self.assertEqual(len(merged["slides"]["S14"]["cleanup_regions"]), 2)

    def test_cleanup_region_accepts_border_median_fill_and_normalizes_legacy_aliases(self) -> None:
        mode, route = self.module.classify_cleanup_mode("border-median-fill")
        self.assertEqual((mode, route), ("border-median-fill", "reviewed-fill"))

        self.assertEqual(
            self.module.classify_cleanup_mode("solid"),
            ("solid-fill", "reviewed-fill"),
        )
        self.assertEqual(
            self.module.classify_cleanup_mode("sampled_fill"),
            ("edge-sample-fill", "reviewed-fill"),
        )

    def test_cleanup_region_rejects_unknown_mode_before_composition(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported reviewed cleanup mode"):
            self.module.classify_cleanup_mode("invented-cleanup")

    def test_explicit_optional_override_path_fails_closed_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            with self.assertRaisesRegex(FileNotFoundError, "--reviewed-overrides"):
                self.module.resolve_optional_json_path(
                    run_dir,
                    "missing.json",
                    option_name="--reviewed-overrides",
                    explicitly_requested=True,
                )
            optional = self.module.resolve_optional_json_path(
                run_dir,
                "missing.json",
                option_name="--reviewed-overrides",
                explicitly_requested=False,
            )
            self.assertEqual(optional, (run_dir / "missing.json").resolve())
            self.assertFalse(optional.exists())

    def test_option_was_explicit_supports_split_and_equals_forms(self) -> None:
        self.assertTrue(
            self.module.option_was_explicit(
                ["run", "--reviewed-overrides", "review.json"],
                "--reviewed-overrides",
            )
        )
        self.assertTrue(
            self.module.option_was_explicit(
                ["run", "--reviewed-overrides=review.json"],
                "--reviewed-overrides",
            )
        )
        self.assertFalse(
            self.module.option_was_explicit(["run"], "--reviewed-overrides")
        )

    def test_reviewed_panels_merge_and_resolve_relative_source_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review_dir = root / "review"
            source_dir = review_dir / "sources"
            source_dir.mkdir(parents=True)
            source = source_dir / "panel.png"
            source.write_bytes(b"source-evidence")
            review = review_dir / "reviewed.json"
            review.write_text(
                json.dumps(
                    {
                        "slides": {
                            "S01": {
                                "reviewed_panels": [
                                    {
                                        "frame_id": "frame-S01-reviewed-001",
                                        "frame_bbox": [20, 30, 240, 120],
                                        "content_bbox": [36, 48, 208, 84],
                                        "content_source_file": "sources/panel.png",
                                        "reason": "reviewed complex semantic panel",
                                        "native_frame": {
                                            "type": "rounded_rect",
                                            "fill": "F8FAFC",
                                            "line": "0B5A45",
                                            "line_width": 1.2,
                                        },
                                    }
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            loaded = self.module.load_override_payload(review)
            merged = self.module.merge_override_payloads(
                loaded,
                {
                    "slides": {
                        "S01": {
                            "reviewed_panels": [
                                {
                                    "frame_id": "frame-S01-reviewed-002",
                                    "frame_bbox": [300, 30, 240, 120],
                                    "content_bbox": [316, 48, 208, 84],
                                    "reason": "second reviewed semantic panel",
                                    "native_frame": {
                                        "type": "rect",
                                        "fill": "FFFFFF",
                                        "line": "082C5D",
                                        "line_width": 1.0,
                                    },
                                }
                            ]
                        }
                    }
                },
            )

            self.module.validate_override_payloads(merged)
            self.assertEqual(len(merged["slides"]["S01"]["reviewed_panels"]), 2)
            resolved = merged["slides"]["S01"]["reviewed_panels"][0][
                "_resolved_content_source_file"
            ]
            self.assertEqual(Path(resolved), source.resolve())

            source.unlink()
            with self.assertRaisesRegex(FileNotFoundError, "content_source_file does not exist"):
                self.module.validate_override_payloads(merged)

    def test_reviewed_panel_rejects_out_of_bounds_geometry(self) -> None:
        panel = {
            "frame_id": "frame-S01-reviewed-001",
            "frame_bbox": [300, 100, 150, 100],
            "content_bbox": [320, 120, 100, 60],
            "reason": "reviewed complex semantic panel",
            "native_frame": {
                "type": "rounded_rect",
                "fill": "F8FAFC",
                "line": "0B5A45",
                "line_width": 1.2,
            },
        }
        payload = {
            "slides": {
                "S01": {
                    "source_size": [400, 300],
                    "reviewed_panels": [panel],
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "frame_bbox is outside the source canvas"):
            self.module.validate_override_payloads(payload)

        panel["frame_bbox"] = [100, 80, 220, 140]
        panel["content_bbox"] = [280, 100, 80, 80]
        with self.assertRaisesRegex(ValueError, "content_bbox must be inside frame_bbox"):
            self.module.validate_override_payloads(payload)

    def test_reviewed_panel_suppression_is_local_and_empty_path_is_non_regressive(self) -> None:
        candidates = [
            {"bbox": [120, 120, 100, 60], "frame_id": "auto-contained"},
            {"bbox": [90, 95, 300, 200], "frame_id": "auto-overlap"},
            {"bbox": [500, 100, 100, 60], "frame_id": "auto-kept"},
        ]
        reviewed = [
            {
                "frame_id": "frame-S01-reviewed-001",
                "frame_bbox": [100, 100, 300, 200],
            }
        ]

        kept, suppressed = self.module.suppress_reviewed_panel_candidates(
            candidates, reviewed
        )
        self.assertEqual([item["frame_id"] for item in kept], ["auto-kept"])
        self.assertEqual(len(suppressed), 2)
        self.assertEqual(
            {item["suppression_reason"] for item in suppressed},
            {"contained-by-reviewed-panel", "high-overlap-with-reviewed-panel"},
        )
        self.assertTrue(
            all(
                item["suppressed_by_frame_id"] == "frame-S01-reviewed-001"
                for item in suppressed
            )
        )

        untouched, no_suppressions = self.module.suppress_reviewed_panel_candidates(
            candidates, []
        )
        self.assertEqual(untouched, candidates)
        self.assertEqual(no_suppressions, [])

    def test_reviewed_panel_content_asset_crops_current_imagegen_master(self) -> None:
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master = np.full((200, 300, 3), 245, dtype=np.uint8)
            master[60:110, 70:170] = [20, 80, 180]
            master_path = root / "S01.png"
            cv2.imwrite(str(master_path), master)
            entry = {
                "slide_id": "S01",
                "frame_id": "frame-S01-reviewed-001",
                "frame_bbox": [40, 30, 200, 130],
                "content_bbox": [70, 60, 100, 50],
                "reason": "reviewed semantic panel from ImageGen master",
                "native_frame": {
                    "type": "rounded_rect",
                    "fill": "F8FAFC",
                    "line": "0B5A45",
                    "line_width": 1.2,
                },
            }
            _, shape = self.module.make_reviewed_panel_frame(entry, 300, 200)
            asset, report = self.module.build_reviewed_panel_content_asset(
                entry,
                shape,
                master,
                master_path,
                root,
                1,
                cv2,
            )
            crop = cv2.imread(asset["file"], cv2.IMREAD_UNCHANGED)

            self.assertEqual(crop.shape[:2], (50, 100))
            self.assertEqual(asset["role"], "movable-panel-content")
            self.assertTrue(asset["reviewed_panel"])
            self.assertEqual(
                asset["source_provenance"]["kind"],
                "verified-imagegen-master-crop",
            )
            self.assertEqual(
                asset["source_provenance"]["source_sha256"],
                self.module.sha256_file(master_path),
            )
            self.assertEqual(report["route"], "reviewed-native-frame-plus-bounded-content")

    def test_reviewed_panel_content_asset_copies_external_source_provenance(self) -> None:
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review_dir = root / "review"
            source_dir = review_dir / "sources"
            source_dir.mkdir(parents=True)
            external = np.full((100, 160, 4), 0, dtype=np.uint8)
            external[15:55, 10:70] = [40, 90, 210, 255]
            external_path = source_dir / "diagram.png"
            cv2.imwrite(str(external_path), external)
            review_path = review_dir / "reviewed.json"
            review_path.write_text(
                json.dumps(
                    {
                        "slides": {
                            "S01": {
                                "reviewed_panels": [
                                    {
                                        "frame_id": "frame-S01-reviewed-001",
                                        "frame_bbox": [40, 30, 200, 130],
                                        "content_bbox": [70, 60, 100, 50],
                                        "content_source_file": "sources/diagram.png",
                                        "content_source_bbox": [10, 15, 60, 40],
                                        "reason": "reviewed external source panel",
                                        "native_frame": {
                                            "type": "rounded_rect",
                                            "fill": "F8FAFC",
                                            "line": "0B5A45",
                                            "line_width": 1.2,
                                        },
                                    }
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            loaded = self.module.load_override_payload(review_path)
            self.module.validate_override_payloads(loaded)
            entry = loaded["slides"]["S01"]["reviewed_panels"][0]
            entry["slide_id"] = "S01"
            master = np.full((200, 300, 3), 245, dtype=np.uint8)
            master_path = root / "S01.png"
            cv2.imwrite(str(master_path), master)
            _, shape = self.module.make_reviewed_panel_frame(entry, 300, 200)
            asset, _ = self.module.build_reviewed_panel_content_asset(
                entry,
                shape,
                master,
                master_path,
                root,
                1,
                cv2,
            )
            provenance = asset["source_provenance"]

            self.assertEqual(provenance["kind"], "external-source-crop")
            self.assertEqual(
                provenance["resolution_strategy"],
                "relative-to-override-json-directory-copied-into-run",
            )
            self.assertTrue(Path(provenance["source_file"]).exists())
            self.assertEqual(
                provenance["source_sha256"], self.module.sha256_file(external_path)
            )
            self.assertEqual(cv2.imread(asset["file"], cv2.IMREAD_UNCHANGED).shape[:2], (40, 60))

    def test_reviewed_panel_main_path_builds_separated_layers_and_passes_structural_gate(self) -> None:
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "assets" / "slides").mkdir(parents=True)
            (run_dir / "editable").mkdir(parents=True)
            (run_dir / "high_fidelity" / "ocr").mkdir(parents=True)
            source = np.full((360, 640, 3), 245, dtype=np.uint8)
            line_bgr = self.module.hex_to_bgr("0B5A45")
            cv2.rectangle(source, (100, 100), (399, 279), (250, 250, 250), -1)
            cv2.rectangle(source, (100, 100), (399, 279), line_bgr, 6)
            cv2.circle(source, (250, 190), 38, (30, 90, 210), -1)
            source_path = run_dir / "assets" / "slides" / "S01.png"
            cv2.imwrite(str(source_path), source)
            (run_dir / "editable" / "deck-editable.json").write_text(
                json.dumps({"title": "test", "slides": [{"slide_id": "S01"}]}),
                encoding="utf-8",
            )
            (run_dir / "image-prompts.json").write_text(
                json.dumps({"slides": [{"slide_id": "S01", "exact_text": []}]}),
                encoding="utf-8",
            )
            (run_dir / "high_fidelity" / "ocr" / "S01.json").write_text(
                json.dumps({"lines": []}), encoding="utf-8"
            )
            (run_dir / "high_fidelity" / "reviewed-overrides.json").write_text(
                json.dumps(
                    {
                        "slides": {
                            "S01": {
                                "source_size": [640, 360],
                                "reviewed_panels": [
                                    {
                                        "frame_id": "frame-S01-reviewed-001",
                                        "frame_bbox": [100, 100, 300, 180],
                                        "content_bbox": [140, 130, 220, 120],
                                        "reason": "reviewed semantic panel integration probe",
                                        "native_frame": {
                                            "type": "rounded_rect",
                                            "fill": "FAFAFA",
                                            "line": "0B5A45",
                                            "line_width": 3.9,
                                            "line_width_px": 6,
                                            "corner_radius_px": 4,
                                        },
                                    }
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            out_rel = "high_fidelity/reviewed-panel-probe"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(run_dir),
                    "--slides",
                    "S01",
                    "--out-dir",
                    out_rel,
                    "--tools-path",
                    str(ROOT / ".ppt_tools"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            out_dir = run_dir / out_rel
            deck_path = out_dir / "deck-high-fidelity.json"
            deck = json.loads(deck_path.read_text(encoding="utf-8"))
            slide = deck["slides"][0]
            reviewed_shapes = [
                item for item in slide["shapes"] if item.get("reviewed_panel")
            ]
            reviewed_assets = [
                item for item in slide["icons"] if item.get("reviewed_panel")
            ]

            self.assertEqual(len(reviewed_shapes), 1)
            self.assertEqual(len(reviewed_assets), 1)
            self.assertEqual(
                reviewed_shapes[0]["background_cleanup_scope"],
                "full-semantic-panel",
            )
            self.assertEqual(
                reviewed_shapes[0]["cleanup_evidence"]["status"], "pass"
            )
            self.assertEqual(
                reviewed_assets[0]["source_provenance"]["kind"],
                "verified-imagegen-master-crop",
            )
            self.assertEqual(
                reviewed_assets[0]["frame_id"], reviewed_shapes[0]["frame_id"]
            )

            pptx = out_dir / "probe.pptx"
            pptx.write_bytes(b"pptx")
            layer_report = out_dir / "qa" / "layer-contract-report.json"
            layer_review = out_dir / "qa" / "layer-review.json"
            gated = subprocess.run(
                [
                    sys.executable,
                    str(LAYER_GATE),
                    str(deck_path),
                    "--pptx",
                    str(pptx),
                    "--review",
                    str(layer_review),
                    "--out",
                    str(layer_report),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            gate_payload = json.loads(layer_report.read_text(encoding="utf-8"))
            self.assertEqual(gated.returncode, 2)
            self.assertEqual(gate_payload["structural"]["status"], "pass")
            self.assertEqual(
                gate_payload["slides"][0]["reviewed_panel_audits"][0]["status"],
                "pass",
            )

    def test_reviewed_native_shapes_merge_and_require_a_reason(self) -> None:
        merged = self.module.merge_override_payloads(
            {
                "slides": {
                    "S04": {
                        "native_shapes": [
                            {
                                "name": "left-card-frame",
                                "type": "rounded_rect",
                                "source_bbox": [20, 580, 520, 320],
                                "line": "35BDEB",
                                "background_cleanup": "outline-inpaint",
                                "reason": "reviewed dark card frame",
                            }
                        ]
                    }
                }
            },
            {
                "slides": {
                    "S04": {
                        "native_shapes": [
                            {
                                "name": "middle-card-frame",
                                "type": "rounded_rect",
                                "source_bbox": [560, 580, 520, 320],
                                "line": "35BDEB",
                                "background_cleanup": "outline-inpaint",
                                "reason": "reviewed dark card frame",
                            }
                        ]
                    }
                }
            },
        )

        self.assertEqual(len(merged["slides"]["S04"]["native_shapes"]), 2)
        self.module.validate_override_payloads(merged)
        merged["slides"]["S04"]["native_shapes"][0]["reason"] = ""
        with self.assertRaisesRegex(ValueError, "auditable reason"):
            self.module.validate_override_payloads(merged)

    def test_reviewed_native_frame_requires_background_cleanup(self) -> None:
        payload = {
            "slides": {
                "S01": {
                    "native_shapes": [
                        {
                            "name": "card-frame",
                            "type": "rounded_rect",
                            "source_bbox": [20, 30, 240, 120],
                            "line": "0B5A45",
                            "reason": "reviewed semantic card frame",
                        }
                    ]
                }
            }
        }

        with self.assertRaisesRegex(ValueError, "without removing the source frame"):
            self.module.validate_override_payloads(payload)

    def test_reviewed_native_three_layer_compound_requires_valid_parent(self) -> None:
        outer = {
            "name": "compound-outer",
            "frame_id": "frame-S01-compound-outer",
            "type": "rounded_rect",
            "source_bbox": [20, 30, 240, 120],
            "layout_bbox": [22, 32, 236, 116],
            "line": "0B5A45",
            "role": "measured-semantic-frame-compound-outer",
            "background_cleanup": "full-frame-directional",
            "z_order_within_compound": 0,
            "reason": "reviewed outer cleanup owner",
        }
        middle = {
            "name": "compound-middle",
            "frame_id": "frame-S01-compound-middle",
            "type": "rounded_rect",
            "source_bbox": [24, 34, 232, 112],
            "layout_bbox": [24, 34, 232, 112],
            "line": "FFFFFF",
            "role": "measured-semantic-frame-compound-middle",
            "background_cleanup": "none",
            "cleanup_delegated_to": outer["frame_id"],
            "z_order_within_compound": 1,
            "reason": "middle layer is removed by the outer full-frame cleanup",
        }
        inner = {
            "name": "compound-inner",
            "frame_id": "frame-S01-compound-inner",
            "type": "rounded_rect",
            "source_bbox": [30, 40, 220, 100],
            "layout_bbox": [30, 40, 220, 100],
            "line": "082C5D",
            "role": "measured-semantic-frame-compound-inner",
            "background_cleanup": "none",
            "cleanup_delegated_to": outer["frame_id"],
            "z_order_within_compound": 2,
            "reason": "inner layer is removed by the outer full-frame cleanup",
        }
        payload = {"slides": {"S01": {"native_shapes": [outer, middle, inner]}}}

        self.module.validate_override_payloads(payload)
        middle["cleanup_delegated_to"] = "frame-S01-missing"
        with self.assertRaisesRegex(ValueError, "cleanup delegate .* does not exist"):
            self.module.validate_override_payloads(payload)

    def test_reviewed_native_arrow_and_oval_masks_are_shape_scoped(self) -> None:
        import cv2
        import numpy as np

        arrow_mask = np.zeros((160, 260), dtype=np.uint8)
        arrow = {
            "type": "right_arrow",
            "source_bbox": [30, 40, 120, 42],
            "background_cleanup": "full-frame-directional",
            "cleanup_width_px": 4,
        }
        self.assertTrue(self.module.add_reviewed_native_shape_mask(arrow, arrow_mask, cv2))
        self.assertGreater(np.count_nonzero(arrow_mask), 1000)
        self.assertGreater(int(arrow_mask[40, 30]), 0)
        self.assertGreater(int(arrow_mask[61, 140]), 0)
        self.assertEqual(int(arrow_mask[39, 30]), 0)

        oval_mask = np.zeros((160, 260), dtype=np.uint8)
        oval = {
            "type": "oval",
            "source_bbox": [170, 30, 70, 90],
            "background_cleanup": "outline-directional",
            "cleanup_width_px": 3,
        }
        self.assertTrue(self.module.add_reviewed_native_shape_mask(oval, oval_mask, cv2))
        self.assertGreater(int(oval_mask[75, 170]), 0)
        self.assertEqual(int(oval_mask[75, 205]), 0)

        line_mask = np.zeros((160, 260), dtype=np.uint8)
        line = {
            "type": "line",
            "source_bbox": [30, 90, 150, 10],
            "x1": 30,
            "y1": 95,
            "x2": 180,
            "y2": 95,
            "background_cleanup": "outline-directional",
            "line_width_px": 10,
        }
        self.assertTrue(self.module.add_reviewed_native_shape_mask(line, line_mask, cv2))
        self.assertGreater(int(line_mask[101, 100]), 0)
        self.assertEqual(int(line_mask[105, 100]), 0)

    def test_reviewed_native_cleanup_marks_shape_for_layer_audit(self) -> None:
        shape = self.module.make_reviewed_native_shape(
            {
                "name": "process-arrow",
                "type": "right_arrow",
                "source_bbox": [10, 20, 100, 30],
                "background_cleanup": "full-frame-directional",
                "line": "082C5D",
                "reason": "reviewed semantic connector arrow",
            },
            200,
            100,
        )
        self.assertTrue(shape["requires_background_cleanup"])
        self.assertEqual(shape["background_cleanup"], "full-frame-directional")

    def test_line_cleanup_assessment_ignores_unrelated_photo_edges(self) -> None:
        result = self.module.reviewed_shape_cleanup_assessment(
            shape_type="connector",
            cleanup_applied=True,
            source_color_support=0.0,
            post_color_support=0.0,
            source_edge_support=0.31,
            post_edge_support=0.25,
            mean_abs_cleanup_delta=42.0,
            semantic_content_coverage=1.0,
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(
            result["support_mode"],
            "line-color-removal-plus-reviewed-mask-change",
        )
        self.assertEqual(result["post_cleanup_support"], 0.0)

    def test_line_cleanup_assessment_requires_observable_cleanup_change(self) -> None:
        result = self.module.reviewed_shape_cleanup_assessment(
            shape_type="oval",
            cleanup_applied=True,
            source_color_support=0.0,
            post_color_support=0.0,
            source_edge_support=0.20,
            post_edge_support=0.18,
            mean_abs_cleanup_delta=0.0,
            semantic_content_coverage=1.0,
        )

        self.assertEqual(result["status"], "fail")

    def test_panel_cleanup_assessment_keeps_edge_residual_strict(self) -> None:
        result = self.module.reviewed_shape_cleanup_assessment(
            shape_type="rounded_rect",
            cleanup_applied=True,
            source_color_support=0.0,
            post_color_support=0.0,
            source_edge_support=0.30,
            post_edge_support=0.24,
            mean_abs_cleanup_delta=42.0,
            semantic_content_coverage=1.0,
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["support_mode"], "color-or-edge-residual")

    def test_reviewed_native_compound_metadata_is_preserved(self) -> None:
        shape = self.module.make_reviewed_native_shape(
            {
                "name": "compound-middle",
                "frame_id": "frame-S01-compound-middle",
                "type": "rounded_rect",
                "source_bbox": [24, 34, 232, 112],
                "layout_bbox": [24, 34, 232, 112],
                "line": "FFFFFF",
                "role": "measured-semantic-frame-compound-middle",
                "background_cleanup": "none",
                "cleanup_delegated_to": "frame-S01-compound-outer",
                "z_order_within_compound": 1,
                "allow_raster_background_frame": True,
                "reason": "middle layer is removed by the outer full-frame cleanup",
            },
            960,
            540,
        )

        self.assertEqual(shape["compound_layer"], "middle")
        self.assertEqual(shape["z_order_within_compound"], 1)
        self.assertEqual(
            shape["cleanup_delegated_to"], "frame-S01-compound-outer"
        )
        self.assertTrue(shape["allow_raster_background_frame"])

    def test_reviewed_text_preserves_measured_character_spacing(self) -> None:
        item = self.module.make_reviewed_text_item(
            {
                "name": "closing-thanks",
                "text": "谢谢各位老师",
                "source_bbox": [100, 700, 420, 64],
                "layout_bbox": [96, 696, 440, 72],
                "size": 30,
                "char_spacing": 7.5,
                "line_spacing_multiple": 1.1,
                "runs": [
                    {
                        "text": "谢谢各位老师",
                        "char_spacing": 8.0,
                    }
                ],
            },
            1672,
            941,
        )

        self.assertEqual(item["char_spacing"], 7.5)
        self.assertEqual(item["line_spacing_multiple"], 1.1)
        self.assertEqual(item["runs"][0]["char_spacing"], 8.0)

    def test_horizontal_object_cleanup_samples_perpendicular_edges(self) -> None:
        import numpy as np

        region = np.full((24, 64, 3), 246, dtype=np.uint8)
        region[:, :8] = [20, 40, 90]
        region[:, -8:] = [20, 40, 90]
        cleanup_mask = np.zeros((24, 64), dtype=np.uint8)
        cleanup_mask[8:16, 8:56] = 255

        repaired = self.module._directional_repair_patch(
            region,
            cleanup_mask,
            np,
            direction="vertical",
        )

        self.assertGreater(int(repaired[12, 32].min()), 240)

    def test_wide_full_frame_rect_cleanup_uses_perpendicular_edges(self) -> None:
        direction = self.module.reviewed_shape_repair_direction(
            {
                "type": "rect",
                "source_bbox": [188, 242, 543, 81],
            },
            "full-frame-directional",
        )

        self.assertEqual(direction, "vertical")

    def test_tall_full_frame_rect_cleanup_uses_perpendicular_edges(self) -> None:
        direction = self.module.reviewed_shape_repair_direction(
            {
                "type": "rect",
                "source_bbox": [100, 80, 48, 260],
            },
            "full-frame-directional",
        )

        self.assertEqual(direction, "horizontal")

    def test_counterfactual_surface_repair_removes_semantic_bbox_gradient(self) -> None:
        import cv2
        import numpy as np

        image = np.full((120, 240, 3), 248, dtype=np.uint8)
        image[38:82, 42:198] = np.linspace(
            np.array([80, 120, 170], dtype=np.float32),
            np.array([210, 225, 235], dtype=np.float32),
            156,
        )[None, :, :]
        repaired, mask, report = self.module.counterfactual_surface_repair(
            image,
            [
                {
                    "name": "wide-bar",
                    "type": "rect",
                    "source_bbox": [42, 38, 156, 44],
                }
            ],
            [],
            [],
            {
                "padding_px": 6,
                "sigma_px": 22,
                "feather_px": 2,
                "reason": "test semantic footprint removal",
            },
            cv2,
            np,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["object_count"], 1)
        self.assertGreater(int(np.count_nonzero(mask)), 156 * 44)
        self.assertGreater(int(repaired[60, 120].min()), 240)

    def test_counterfactual_cleanup_config_merges_and_validates(self) -> None:
        config = {
            "enabled": True,
            "padding_px": 8,
            "sigma_px": 34,
            "feather_px": 3,
            "reason": "remove hidden object footprints",
        }
        merged = self.module.merge_override_payloads(
            {"slides": {"S07": {"counterfactual_background_cleanup": config}}}
        )

        self.module.validate_override_payloads(merged)
        self.assertEqual(
            merged["slides"]["S07"]["counterfactual_background_cleanup"],
            config,
        )

    def test_counterfactual_full_slide_polynomial_removes_structured_footprints(self) -> None:
        import cv2
        import numpy as np

        height, width = 140, 260
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
        image = base.copy()
        image[18:48, 12:248] = [236, 239, 243]
        image[62:108, 18:78] = [239, 241, 245]
        image[62:108, 100:160] = [238, 241, 244]
        image[62:108, 182:242] = [237, 240, 244]

        repaired, mask, report = self.module.counterfactual_surface_repair(
            image,
            [
                {"name": "title", "type": "rect", "source_bbox": [12, 18, 236, 30]},
                {"name": "card-a", "type": "rect", "source_bbox": [18, 62, 60, 46]},
                {"name": "card-b", "type": "rect", "source_bbox": [100, 62, 60, 46]},
                {"name": "card-c", "type": "rect", "source_bbox": [182, 62, 60, 46]},
            ],
            [],
            [],
            {
                "padding_px": 3,
                "sigma_px": 18,
                "feather_px": 1,
                "reason": "test full-slide structured-footprint removal",
                "global_surface": {
                    "enabled": True,
                    "apply_scope": "full-slide",
                    "degree": 2,
                    "sample_stride_px": 4,
                    "robust_iterations": 3,
                    "prefilter_sigma_px": 4,
                    "fit_exclusion_padding_px": 2,
                    "strength": 1.0,
                },
            },
            cv2,
            np,
        )

        self.assertEqual(report["global_surface"]["apply_scope"], "full-slide")
        self.assertEqual(report["mask_area_ratio"], 1.0)
        self.assertTrue(np.all(mask == 255))
        self.assertLess(
            float(np.mean(np.abs(repaired.astype(float) - base.astype(float)))),
            1.5,
        )
        self.assertLess(
            float(
                np.mean(
                    np.abs(
                        repaired[70:100, 110:150].astype(float)
                        - base[70:100, 110:150].astype(float)
                    )
                )
            ),
            1.5,
        )

    def test_counterfactual_global_surface_rejects_unknown_scope(self) -> None:
        config = {
            "enabled": True,
            "reason": "invalid scope test",
            "global_surface": {"enabled": True, "apply_scope": "content-only"},
        }

        with self.assertRaisesRegex(ValueError, "apply_scope"):
            self.module.validate_override_payloads(
                {"slides": {"S01": {"counterfactual_background_cleanup": config}}}
            )

    def test_closed_node_cleanup_uses_clean_surrounding_fill(self) -> None:
        import numpy as np

        region = np.full((40, 40, 3), 248, dtype=np.uint8)
        cleanup_mask = np.zeros((40, 40), dtype=np.uint8)
        cleanup_mask[6:34, 6:34] = 255
        region[18:22, :] = [30, 60, 120]
        region[:, 18:22] = [50, 70, 160]

        repaired = self.module._directional_repair_patch(
            region,
            cleanup_mask,
            np,
            direction="solid",
        )

        self.assertGreater(int(repaired[20, 20].min()), 240)

    def test_panel_extraction_binds_content_to_cleaned_native_frame(self) -> None:
        import cv2
        import numpy as np

        image = np.full((240, 400, 3), 244, dtype=np.uint8)
        x, y, width, height = 70, 50, 240, 130
        fill_bgr = [250.0, 250.0, 250.0]
        line_bgr = [70.0, 85.0, 35.0]
        cv2.rectangle(
            image,
            (x, y),
            (x + width - 1, y + height - 1),
            tuple(int(value) for value in fill_bgr),
            -1,
        )
        cv2.rectangle(
            image,
            (x, y),
            (x + width - 1, y + height - 1),
            tuple(int(value) for value in line_bgr),
            4,
        )
        cv2.circle(image, (x + width // 2, y + height // 2), 24, (40, 40, 210), -1)
        panel = {
            "bbox": [x, y, width, height],
            "frame_bbox": [x, y, width, height],
            "frame_id": "frame-S01-001",
            "fill_bgr": fill_bgr,
            "fill": "FAFAFA",
            "line_bgr": line_bgr,
            "line_color": "235546",
            "line_width_px": 4,
            "corner_radius_px": 4,
            "cleanup_padding_px": 6,
            "fill_mode": "native-fill-plus-bounded-content",
            "detection_confidence": 0.99,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            background, shapes, overlays, reports = self.module.extract_native_panels(
                image,
                Path(temp_dir),
                cv2,
                np,
                [panel],
            )

            self.assertEqual(len(shapes), 1)
            self.assertEqual(len(overlays), 1)
            self.assertEqual(shapes[0]["frame_id"], "frame-S01-001")
            self.assertEqual(overlays[0]["frame_id"], "frame-S01-001")
            self.assertEqual(shapes[0]["cleanup_evidence"]["status"], "pass")
            self.assertLessEqual(
                shapes[0]["cleanup_evidence"]["residual_ratio"],
                0.25,
            )
            self.assertTrue(Path(shapes[0]["cleanup_mask"]).exists())
            self.assertEqual(reports[0]["route"], "native-frame-plus-bounded-content")
            self.assertFalse(np.array_equal(background, image))
            overlay_pixels = cv2.imread(overlays[0]["file"], cv2.IMREAD_UNCHANGED)
            self.assertIsNotNone(overlay_pixels)
            self.assertEqual(overlay_pixels.shape[2], 4)
            transparent = overlay_pixels[:, :, 3] == 0
            self.assertTrue(np.any(transparent))
            overlay_left, overlay_top, _, _ = overlays[0]["content_bbox"]
            flat_x = x + 24 - overlay_left
            flat_y = y + 24 - overlay_top
            semantic_x = x + width // 2 - overlay_left
            semantic_y = y + height // 2 - overlay_top
            self.assertEqual(int(overlay_pixels[flat_y, flat_x, 3]), 0)
            self.assertGreater(int(overlay_pixels[semantic_y, semantic_x, 3]), 0)
            self.assertTrue(
                np.all(
                    overlay_pixels[:, :, :3][transparent]
                    == np.asarray(fill_bgr, dtype=np.uint8)
                )
            )

    def test_panel_overlay_preserves_semantic_icon_crossing_frame(self) -> None:
        import cv2
        import numpy as np

        image = np.full((220, 420, 3), 248, dtype=np.uint8)
        x, y, width, height = 120, 55, 240, 120
        fill_bgr = [248.0, 248.0, 248.0]
        line_bgr = [80.0, 45.0, 8.0]
        cv2.rectangle(
            image,
            (x, y),
            (x + width, y + height),
            tuple(int(value) for value in line_bgr),
            3,
        )
        cv2.circle(image, (x, y + height // 2), 28, (120, 55, 10), -1)
        panel = {
            "bbox": [x, y, width, height],
            "fill_bgr": fill_bgr,
            "line_bgr": line_bgr,
            "line_width_px": 3,
            "corner_radius_px": 8,
            "cleanup_padding_px": 10,
        }

        overlay, content_bbox, frame_mask = self.module.make_panel_overlay(
            image,
            panel,
            cv2,
            np,
        )
        left, top, _, _ = content_bbox
        self.assertLessEqual(left, x - 28)
        icon_frame_x = x - left
        icon_frame_y = y + height // 2 - top
        icon_outer_x = x - 24 - left
        plain_frame_x = x + width // 2 - left
        plain_frame_y = y - top

        self.assertGreater(int(overlay[icon_frame_y, icon_frame_x, 3]), 0)
        self.assertGreater(int(overlay[icon_frame_y, icon_outer_x, 3]), 0)
        if 0 <= plain_frame_y < overlay.shape[0] and 0 <= plain_frame_x < overlay.shape[1]:
            self.assertEqual(int(overlay[plain_frame_y, plain_frame_x, 3]), 0)
        else:
            self.assertLess(left + overlay.shape[1], x + width // 2)
        self.assertGreater(np.count_nonzero(frame_mask), 0)

    def test_flat_panel_without_semantic_content_uses_native_frame_only(self) -> None:
        import cv2
        import numpy as np

        image = np.full((220, 420, 3), 248, dtype=np.uint8)
        x, y, width, height = 90, 55, 250, 110
        fill_bgr = [248.0, 248.0, 248.0]
        line_bgr = [80.0, 45.0, 8.0]
        cv2.rectangle(image, (x, y), (x + width, y + height), tuple(line_bgr), 3)
        panel = {
            "bbox": [x, y, width, height],
            "frame_id": "frame-S01-plain",
            "fill_bgr": fill_bgr,
            "fill": "F8F8F8",
            "line_bgr": line_bgr,
            "line_color": "082D50",
            "line_width_px": 3,
            "corner_radius_px": 2,
            "cleanup_padding_px": 8,
            "fill_mode": "native-fill-plus-bounded-content",
            "detection_confidence": 0.99,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            _, shapes, overlays, reports = self.module.extract_native_panels(
                image,
                Path(temp_dir),
                cv2,
                np,
                [panel],
            )

        self.assertEqual(len(shapes), 1)
        self.assertEqual(overlays, [])
        self.assertEqual(reports[0]["route"], "native-frame-only")
        self.assertIsNone(reports[0]["overlay"])

    def test_directional_repair_accepts_single_pixel_mask_spans(self) -> None:
        import numpy as np

        region = np.full((7, 7, 3), 240, dtype=np.uint8)
        region[3, 3] = [10, 20, 30]
        cleanup_mask = np.zeros((7, 7), dtype=np.uint8)
        cleanup_mask[3, 3] = 255

        repaired = self.module._directional_repair_patch(
            region,
            cleanup_mask,
            np,
            direction="both",
        )

        self.assertEqual(repaired.shape, region.shape)
        self.assertTrue(np.array_equal(repaired[3, 3], np.array([240, 240, 240])))

    def test_frame_side_measurement_rejects_connector_contour_expansion(self) -> None:
        import cv2
        import numpy as np

        image = np.full((360, 620, 3), 248, dtype=np.uint8)
        x, y, width, height = 140, 105, 330, 190
        fill_bgr = [244.0, 246.0, 247.0]
        line_bgr = [76.0, 65.0, 4.0]
        cv2.rectangle(
            image,
            (x, y),
            (x + width, y + height),
            tuple(int(value) for value in fill_bgr),
            -1,
        )
        cv2.rectangle(
            image,
            (x, y),
            (x + width, y + height),
            tuple(int(value) for value in line_bgr),
            4,
        )
        cv2.line(
            image,
            (x + width // 2, y - 22),
            (x + width // 2, y + 2),
            tuple(int(value) for value in line_bgr),
            4,
        )

        refined, line_width, radius, evidence = self.module._refine_panel_geometry(
            image,
            [x - 4, y - 22, width + 8, height + 26],
            fill_bgr,
            line_bgr,
            6,
            np,
        )

        self.assertEqual(evidence["status"], "pass")
        self.assertLessEqual(abs(refined[0] - x), 2)
        self.assertLessEqual(abs(refined[1] - y), 2)
        self.assertLessEqual(abs(refined[2] - width), 3)
        self.assertLessEqual(abs(refined[3] - height), 3)
        self.assertLessEqual(line_width, 5)
        self.assertGreaterEqual(radius, 2)

    def test_content_rich_panel_is_detected_from_border_geometry(self) -> None:
        import cv2
        import numpy as np

        image = np.full((400, 700, 3), 248, dtype=np.uint8)
        x, y, width, height = 120, 90, 320, 170
        cv2.rectangle(image, (x, y), (x + width, y + height), (32, 78, 65), 4)
        for offset in range(0, 220, 22):
            cv2.line(
                image,
                (x + 35 + offset, y + 35),
                (x + 35 + offset, y + height - 30),
                (120, 150, 190),
                3,
            )
        cv2.rectangle(
            image,
            (x + 28, y + 28),
            (x + 175, y + height - 25),
            (170, 125, 75),
            -1,
        )
        cv2.circle(image, (x + 245, y + 90), 36, (35, 35, 210), -1)

        panels = self.module.detect_flat_panels(image, cv2, np)

        self.assertTrue(
            any(
                abs(panel["bbox"][0] - x) <= 6
                and abs(panel["bbox"][1] - y) <= 6
                and abs(panel["bbox"][2] - width) <= 12
                and abs(panel["bbox"][3] - height) <= 12
                for panel in panels
            )
        )
        matched = min(
            panels,
            key=lambda panel: abs(panel["bbox"][0] - x) + abs(panel["bbox"][1] - y),
        )
        self.assertEqual(matched["fill_mode"], "native-fill-plus-bounded-content")

    def test_panel_geometry_rejects_absurd_stroke_and_radius(self) -> None:
        import numpy as np

        wide_stroke = self.module.panel_geometry_rejection_reason(
            [100, 100, 640, 320],
            96,
            24,
            [248.0, 248.0, 248.0],
            [90.0, 120.0, 150.0],
            {
                "status": "pass",
                "side_support": {
                    "top": 0.9,
                    "bottom": 0.9,
                    "left": 0.9,
                    "right": 0.9,
                },
            },
            np,
        )
        huge_radius = self.module.panel_geometry_rejection_reason(
            [100, 100, 500, 100],
            3,
            60,
            [248.0, 248.0, 248.0],
            [80.0, 100.0, 130.0],
            {
                "status": "pass",
                "side_support": {
                    "top": 0.9,
                    "bottom": 0.9,
                    "left": 0.9,
                    "right": 0.9,
                },
            },
            np,
        )

        self.assertIn("implausible-line-width", wide_stroke)
        self.assertEqual(huge_radius, "implausible-corner-radius")

    def test_wide_rounded_card_keeps_its_native_border(self) -> None:
        self.assertEqual(
            self.module.panel_native_shape_type(
                {"bbox": [100, 100, 600, 90], "corner_radius_px": 8}
            ),
            "rounded_rect",
        )
        self.assertEqual(
            self.module.panel_native_shape_type(
                {"bbox": [100, 100, 600, 30], "corner_radius_px": 1}
            ),
            "rect",
        )

    def test_panel_line_color_uses_repeated_boundary_not_sparse_black_glyph(self) -> None:
        import cv2
        import numpy as np

        image = np.full((220, 420, 3), 250, dtype=np.uint8)
        x, y, width, height = 70, 45, 280, 130
        fill = np.asarray([246, 247, 248], dtype=np.uint8)
        line = np.asarray([180, 150, 105], dtype=np.uint8)
        cv2.rectangle(
            image,
            (x, y),
            (x + width, y + height),
            tuple(int(value) for value in fill),
            -1,
        )
        cv2.rectangle(
            image,
            (x, y),
            (x + width, y + height),
            tuple(int(value) for value in line),
            4,
        )
        cv2.rectangle(image, (x + 120, y), (x + 136, y + 10), (0, 0, 0), -1)

        sampled, _ = self.module._sample_panel_line_color(
            image,
            [x, y, width, height],
            fill.astype(np.float32),
            np,
        )

        self.assertLess(
            np.linalg.norm(np.asarray(sampled) - line.astype(np.float32)),
            28.0,
        )
        self.assertGreater(np.linalg.norm(np.asarray(sampled)), 80.0)

    def test_unmatched_semantic_reference_recovers_five_measured_labels(self) -> None:
        labels = ["桥区", "港区", "禁航区", "施工作业区", "通航密集水域"]
        lines = []
        for index, label in enumerate(labels):
            words = [
                {
                    "text": char,
                    "bbox": {"x": index * 200 + offset * 18, "y": 100, "w": 16, "h": 22},
                }
                for offset, char in enumerate(label)
            ]
            lines.append(
                {
                    "text": " ".join(label),
                    "bbox": {"x": index * 200, "y": 100, "w": len(label) * 18, "h": 22},
                    "words": words,
                }
            )

        recovered = self.module.recover_unmatched_reference_groups(
            "桥区 · 港区 · 禁航区 · 施工作业区 · 通航密集水域",
            lines,
        )

        self.assertEqual([item["expected_text"] for item in recovered], labels)
        self.assertEqual(len({item["line_index"] for item in recovered}), 5)

    def test_unmatched_label_does_not_reuse_claimed_title_line(self) -> None:
        lines = [
            {
                "text": "平台把多源感知到证据归档连成一条闭环",
                "bbox": {"x": 10, "y": 10, "w": 500, "h": 30},
                "words": [
                    {"text": char, "bbox": {"x": 10 + index * 12, "y": 10, "w": 11, "h": 30}}
                    for index, char in enumerate("平台把多源感知到证据归档连成一条闭环")
                ],
            }
        ]

        recovered = self.module.recover_unmatched_reference_groups(
            "多源感知",
            lines,
            excluded_line_indices={0},
        )

        self.assertEqual(recovered, [])

    def test_labelled_numeric_rows_preserve_prefix_units_and_suffix(self) -> None:
        lines = [
            {
                "text": "可 见 光 ：",
                "bbox": {"x": 10, "y": 10, "w": 80, "h": 20},
                "words": [{"text": "可见光：", "bbox": {"x": 10, "y": 10, "w": 80, "h": 20}}],
            },
            {
                "text": "2560 × 1440 @25 fps / 30 倍 光 学 变 倍",
                "bbox": {"x": 10, "y": 35, "w": 260, "h": 20},
                "words": [
                    {
                        "text": "2560×1440 @25 fps / 30倍光学变倍",
                        "bbox": {"x": 10, "y": 35, "w": 260, "h": 20},
                    }
                ],
            },
        ]

        rows = self.module.labelled_numeric_visual_rows(
            "可见光：2560×1440 @25 fps / 30倍光学变倍",
            lines,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            self.module.partition_expected(
                "可见光：2560×1440 @25 fps / 30倍光学变倍",
                rows,
            ),
            ["可见光：", "2560×1440 @25 fps / 30倍光学变倍"],
        )

    def test_labelled_numeric_row_cleanup_uses_continuous_aligned_word_bbox(self) -> None:
        row = {
            "bbox": {"x": 1177, "y": 486, "w": 422, "h": 39},
            "words": [
                {"text": "准确率", "bbox": {"x": 1184, "y": 486, "w": 108, "h": 39}},
                {"text": "83.0%", "bbox": {"x": 1309, "y": 488, "w": 113, "h": 36}},
                {"text": "94.0%", "bbox": {"x": 1482, "y": 487, "w": 117, "h": 37}},
            ],
        }

        rectangles = self.module.cleanup_rectangles_for_visual_row(row, row["words"])

        self.assertEqual(rectangles, [(1184, 486, 415, 39)])

    def test_labelled_numeric_row_cleanup_excludes_leading_icon_false_positive(self) -> None:
        row = {
            "bbox": {"x": 87, "y": 604, "w": 704, "h": 32},
            "words": [
                {"text": "0", "bbox": {"x": 87, "y": 604, "w": 31, "h": 31}},
                {"text": "GZSD", "bbox": {"x": 162, "y": 607, "w": 82, "h": 27}},
                {"text": "Ours", "bbox": {"x": 256, "y": 607, "w": 67, "h": 27}},
                {"text": "：", "bbox": {"x": 329, "y": 612, "w": 7, "h": 22}},
                {"text": "Base", "bbox": {"x": 362, "y": 610, "w": 58, "h": 24}},
                {"text": "mAP", "bbox": {"x": 430, "y": 610, "w": 58, "h": 24}},
                {"text": "28", "bbox": {"x": 498, "y": 607, "w": 36, "h": 27}},
                {"text": "·", "bbox": {"x": 536, "y": 628, "w": 7, "h": 6}},
                {"text": "6", "bbox": {"x": 546, "y": 607, "w": 17, "h": 27}},
                {"text": "/", "bbox": {"x": 576, "y": 607, "w": 14, "h": 29}},
                {"text": "№", "bbox": {"x": 602, "y": 612, "w": 29, "h": 22}},
                {"text": "vel", "bbox": {"x": 631, "y": 611, "w": 29, "h": 23}},
                {"text": "mAP", "bbox": {"x": 669, "y": 612, "w": 50, "h": 22}},
                {"text": "15", "bbox": {"x": 730, "y": 607, "w": 33, "h": 27}},
                {"text": "·", "bbox": {"x": 766, "y": 628, "w": 6, "h": 6}},
                {"text": "3", "bbox": {"x": 774, "y": 607, "w": 17, "h": 27}},
            ],
        }

        words = self.module.aligned_words(
            "GZSD Ours：Base mAP 28.6 / Novel mAP 15.3",
            row,
        )
        rectangles = self.module.cleanup_rectangles_for_visual_row(row, words)

        self.assertEqual(words[0]["text"], "GZSD")
        self.assertEqual(rectangles, [(162, 607, 629, 29)])

    def test_compact_semantic_text_keeps_the_measured_bbox(self) -> None:
        match = {
            "reference_index": 2,
            "reference": {"bold": True},
            "score": 1.0,
        }
        line = {
            "words": [
                {
                    "text": "准确率 83.0% → 94.0%",
                    "bbox": {"x": 100, "y": 200, "w": 300, "h": 40},
                }
            ]
        }

        item = self.module.make_text_item(
            match,
            "准确率 83.0% → 94.0%",
            [100, 200, 300, 40],
            [line],
            1920,
            1080,
            "FFFFFF",
            0,
            None,
            "compact",
        )

        self.assertEqual(item["source_bbox"], [100, 200, 300, 40])
        self.assertEqual(item["layout_bbox"], [100, 200, 300, 40])
        self.assertEqual(item["layout_mode"], "compact")


if __name__ == "__main__":
    unittest.main()
