from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "autopptskills" / "scripts" / "release_gate.py"
REVIEW_CHECKS = (
    "text_residue",
    "wrapping_and_spacing",
    "color_and_emphasis",
    "icons_and_vectors",
    "crop_overlap_and_hierarchy",
)
DESIGN_REVIEW_CHECKS = (
    "spectacle_control",
    "design_completion",
)
INSTITUTIONAL_REVIEW_CHECKS = ("institutional_identity_absence",)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def make_pptx(path: Path, slides: int = 2) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/presentation.xml", "<presentation/>")
        for index in range(1, slides + 1):
            archive.writestr(f"ppt/slides/slide{index}.xml", "<slide/>")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseGateTest(unittest.TestCase):
    def prepare(
        self,
        root: Path,
        *,
        include_review: bool = True,
        official_source_inspired: bool = False,
        include_identity_review: bool = False,
    ) -> list[str]:
        pptx = root / "final.pptx"
        make_pptx(pptx)
        pptx_hash = sha256(pptx)

        editability = root / "editability.json"
        write_json(
            editability,
            {
                "pptx": str(pptx.resolve()),
                "verdict": "pass",
                "totals": {
                    "slides": 2,
                    "background_tile_pictures": 0,
                    "semantic_full_slide_pictures": 0,
                    "convertible_vectors": 0,
                },
                "editability": {
                    "grade": "editable",
                    "score": 84.6,
                    "native_text_coverage": 1.0,
                    "native_shape_coverage": 1.0,
                },
                "unicode": {
                    "slide_xml_count": 2,
                    "replacement_character_count": 0,
                },
            },
        )
        technical = root / "technical.json"
        write_json(
            technical,
            {
                "verdict": "pass",
                "pptx": str(pptx.resolve()),
                "slide_ids": ["S01", "S02"],
                "gates": {
                    "layout": "pass",
                    "editability": "pass",
                    "powerpoint_render": "pass",
                    "visual_compare": "pass",
                },
                "powerpoint": {
                    "status": "pass",
                    "renderer": "Microsoft PowerPoint",
                },
                "editability": {"report": str(editability.resolve())},
            },
        )
        imagegen = root / "imagegen.json"
        imagegen_payload = {
            "verdict": "pass",
            "slides_expected": 2,
            "slides_verified": 2,
            "manifest_full_slide_contracts": 2,
            "require_strong_ig_id": True,
            "strong_ig_id_slides": 2,
            "errors": [],
        }
        if official_source_inspired:
            imagegen_payload.update(
                {
                    "official_source_inspired": True,
                    "official_source_contract": {"required": True, "status": "pass"},
                }
            )
        write_json(imagegen, imagegen_payload)
        exact = root / "exact.json"
        write_json(
            exact,
            {
                "verdict": "pass",
                "pptx": str(pptx.resolve()),
                "slides": 2,
                "token_coverage": 1.0,
                "tokens": 8,
                "matched_tokens": 8,
                "missing_tokens": 0,
            },
        )
        overflow = root / "overflow.txt"
        overflow.write_text("Test passed. No overflow detected.\n", encoding="utf-8")

        review = root / "visual-review.json"
        if include_review:
            review_checks = REVIEW_CHECKS + (INSTITUTIONAL_REVIEW_CHECKS if include_identity_review else ())
            review_payload = {
                "schema_version": 3 if include_identity_review else 1,
                "pptx": str(pptx.resolve()),
                "pptx_sha256": pptx_hash,
                "review_scope": "all_slides_full_size_and_montage",
                "slides": [
                    {
                        "slide_id": slide_id,
                        "status": "pass",
                        "checks": {name: "pass" for name in review_checks},
                        "notes": "",
                    }
                    for slide_id in ("S01", "S02")
                ],
                "verdict": "pass",
            }
            if include_identity_review:
                review_payload["institutional_identity_review_required"] = True
            write_json(review, review_payload)

        fallback = root / "icon.png"
        fallback.write_bytes(b"png")
        icons = root / "icons.json"
        write_json(
            icons,
            {
                "mappings": [
                    {
                        "id": "icon-01",
                        "source_bbox": [10, 20, 30, 40],
                        "deck_bbox": [11, 21, 31, 41],
                        "asset": str(fallback.resolve()),
                        "vector_candidate": str((root / "icon.svg").resolve()),
                        "vector_rejection_reason": "powerpoint-contour-breakage",
                    }
                ]
            },
        )
        output = root / "release.json"
        return [
            str(SCRIPT),
            str(pptx),
            "--imagegen-first-report",
            str(imagegen),
            "--technical-gate-report",
            str(technical),
            "--exact-text-report",
            str(exact),
            "--overflow-report",
            str(overflow),
            "--visual-review",
            str(review),
            "--icon-decisions",
            str(icons),
            "--out",
            str(output),
        ]

    def test_gold_release_passes_complete_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = [sys.executable, *self.prepare(root)]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(report["verdict"], "pass")
            self.assertEqual(report["gates"]["archive"]["slide_count"], 2)
            self.assertEqual(report["gates"]["icon_decisions"]["status"], "pass")

    def test_missing_visual_review_creates_pending_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = [sys.executable, *self.prepare(root, include_review=False)]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2)
            review = json.loads(
                (root / "visual-review.json").read_text(encoding="utf-8")
            )
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(review["verdict"], "pending")
            self.assertEqual(report["verdict"], "blocked")

    def test_required_design_quality_blocks_legacy_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = self.prepare(root)
            arguments.append("--require-design-quality")
            completed = subprocess.run(
                [sys.executable, *arguments], capture_output=True, text=True
            )
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["verdict"], "blocked")
            self.assertIn(
                "spectacle_control",
                " ".join(report["gates"]["visual_review"]["errors"]),
            )

    def test_required_design_quality_accepts_explicit_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = self.prepare(root)
            review_path = root / "visual-review.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            for slide in review["slides"]:
                slide["checks"].update(
                    {name: "pass" for name in DESIGN_REVIEW_CHECKS}
                )
            review["schema_version"] = 2
            review["design_quality_required"] = True
            write_json(review_path, review)
            arguments.append("--require-design-quality")
            completed = subprocess.run(
                [sys.executable, *arguments], capture_output=True, text=True
            )
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["verdict"], "pass")
            self.assertEqual(
                report["gates"]["visual_review"]["required_checks"],
                [*REVIEW_CHECKS, *DESIGN_REVIEW_CHECKS],
            )

    def test_official_source_release_blocks_without_identity_absence_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = self.prepare(root, official_source_inspired=True)
            completed = subprocess.run(
                [sys.executable, *arguments], capture_output=True, text=True
            )
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            visual = report["gates"]["visual_review"]
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["verdict"], "blocked")
            self.assertIn("institutional_identity_absence", visual["required_checks"])
            self.assertTrue(
                any("institutional identity review" in error for error in visual["errors"])
            )

    def test_official_source_release_accepts_identity_absence_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = self.prepare(
                root,
                official_source_inspired=True,
                include_identity_review=True,
            )
            completed = subprocess.run(
                [sys.executable, *arguments], capture_output=True, text=True
            )
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            visual = report["gates"]["visual_review"]
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["verdict"], "pass")
            self.assertTrue(visual["institutional_identity_review_required"])
            self.assertIn("institutional_identity_absence", visual["required_checks"])

    def test_official_source_release_rejects_inconsistent_imagegen_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = self.prepare(
                root,
                official_source_inspired=True,
                include_identity_review=True,
            )
            imagegen_path = root / "imagegen.json"
            imagegen = json.loads(imagegen_path.read_text(encoding="utf-8"))
            imagegen["official_source_inspired"] = False
            write_json(imagegen_path, imagegen)

            completed = subprocess.run(
                [sys.executable, *arguments], capture_output=True, text=True
            )
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["verdict"], "fail")
            self.assertTrue(
                any(
                    "flags are inconsistent" in error
                    for error in report["gates"]["imagegen_first"]["errors"]
                )
            )

    def test_known_failure_takes_precedence_over_pending_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = self.prepare(root, include_review=False)
            imagegen = root / "imagegen.json"
            payload = json.loads(imagegen.read_text(encoding="utf-8"))
            payload["slides_verified"] = 1
            write_json(imagegen, payload)
            completed = subprocess.run(
                [sys.executable, *arguments], capture_output=True, text=True
            )
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["gates"]["imagegen_first"]["status"], "fail")
            self.assertEqual(report["gates"]["visual_review"]["status"], "blocked")
            self.assertEqual(report["verdict"], "fail")

    def test_accepted_vector_requires_powerpoint_visual_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = self.prepare(root)
            vector = root / "icon.svg"
            vector.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            icons = root / "icons.json"
            write_json(
                icons,
                {
                    "mappings": [
                        {
                            "id": "icon-01",
                            "source_bbox": [10, 20, 30, 40],
                            "deck_bbox": [11, 21, 31, 41],
                            "vector_candidate": str(vector.resolve()),
                            "accepted_as": "convertible-vector",
                        }
                    ]
                },
            )
            completed = subprocess.run(
                [sys.executable, *arguments], capture_output=True, text=True
            )
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["gates"]["icon_decisions"]["status"], "fail")
            self.assertIn(
                "accepted vector lacks PowerPoint visual pass",
                " ".join(report["gates"]["icon_decisions"]["errors"]),
            )

    def test_convertible_vector_coverage_is_allowed_with_explicit_icon_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = self.prepare(root)
            editability = root / "editability.json"
            payload = json.loads(editability.read_text(encoding="utf-8"))
            payload["totals"].update({"convertible_vectors": 1, "semantic_full_slide_pictures": 0})
            payload["editability"]["native_shape_coverage"] = 0.5
            write_json(editability, payload)
            vector = root / "icon.svg"
            vector.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            fallback = root / "fallback.png"
            fallback.write_bytes(b"png")
            icons = root / "icons.json"
            write_json(
                icons,
                {
                    "mappings": [
                        {
                            "id": "icon-01",
                            "source_bbox": [10, 20, 30, 40],
                            "deck_bbox": [11, 21, 31, 41],
                            "vector_candidate": str(vector.resolve()),
                            "accepted_as": "convertible-vector",
                            "vector_accepted": True,
                            "final_asset": str(vector.resolve()),
                            "powerpoint_visual_review": "pass",
                        }
                    ]
                },
            )
            arguments.extend(["--icon-decisions", str(icons.resolve())])
            completed = subprocess.run([sys.executable, *arguments], capture_output=True, text=True)
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["gates"]["technical"]["status"], "pass")
            self.assertEqual(report["gates"]["icon_decisions"]["status"], "pass")

    def test_required_layer_contract_blocks_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = self.prepare(root)
            arguments.append("--require-layer-contract")
            completed = subprocess.run(
                [sys.executable, *arguments], capture_output=True, text=True
            )
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["verdict"], "blocked")
            self.assertEqual(report["gates"]["layer_contract"]["status"], "blocked")

    def test_required_layer_contract_accepts_bound_strict_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = self.prepare(root)
            pptx = root / "final.pptx"
            layer_report = root / "layer-contract.json"
            write_json(
                layer_report,
                {
                    "verdict": "pass",
                    "pptx": str(pptx.resolve()),
                    "pptx_sha256": sha256(pptx),
                    "slide_count": 2,
                    "strict": True,
                    "totals": {"backgrounds": 2, "background_tiles": 0},
                    "structural": {"status": "pass"},
                    "review": {"status": "pass"},
                },
            )
            arguments.extend(
                [
                    "--layer-contract-report",
                    str(layer_report),
                    "--require-layer-contract",
                ]
            )
            completed = subprocess.run(
                [sys.executable, *arguments], capture_output=True, text=True
            )
            report = json.loads((root / "release.json").read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["verdict"], "pass")
            self.assertEqual(report["gates"]["layer_contract"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
