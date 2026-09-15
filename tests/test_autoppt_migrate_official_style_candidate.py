from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autopptskills.scripts.migrate_official_style_candidate import build_candidate


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class MigrateOfficialStyleCandidateTest(unittest.TestCase):
    def test_builds_isolated_candidate_that_requires_fresh_imagegen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_run = root / "source-run"
            output_dir = source_run / "official-v2"
            source_asset = source_run / "source" / "media" / "figure.png"
            source_asset.parent.mkdir(parents=True)
            source_asset.write_bytes(b"fixture-source")
            identity = "武汉理工大学 船海与能源动力工程学院"
            write_json(
                source_run / "image-prompts.json",
                {
                    "schema_version": 1,
                    "deck_title": "Fixture thesis",
                    "style_profile": "engineering_institutional_blue",
                    "prompt_policy": {},
                    "slides": [
                        {
                            "slide_id": "S01",
                            "headline": "封面",
                            "final_path": "assets/slides/S01.png",
                            "exact_text": [identity],
                            "source_asset_paths": [],
                            "prompt_zh": (
                                "生成一张完整、最终可用的中文PowerPoint幻灯片图片。\n"
                                "用途与受众：本科毕业设计答辩，面向武汉理工大学答辩教师。\n"
                                f"必须逐字显示且不得添加其他可见文字：1.「{identity}」"
                            ),
                        },
                        {
                            "slide_id": "S02",
                            "headline": "方法",
                            "final_path": "assets/slides/S02.png",
                            "exact_text": ["方法"],
                            "source_asset_paths": ["source/media/figure.png"],
                            "prompt_zh": (
                                "生成一张完整、最终可用的中文PowerPoint幻灯片图片。\n"
                                "用途与受众：本科毕业设计答辩，面向武汉理工大学答辩教师。"
                            ),
                        },
                    ],
                },
            )
            write_json(
                source_run / "deck-spec.json",
                {
                    "deck": {"title": "Fixture thesis"},
                    "slides": [
                        {"slide_id": "S01", "layout": "full_slide_image", "slide_image": "assets/slides/S01.png"},
                        {"slide_id": "S02", "layout": "full_slide_image", "slide_image": "assets/slides/S02.png"},
                    ],
                },
            )
            write_json(source_run / "style-contract.json", {"schema_version": 1})

            manifest = build_candidate(
                source_run,
                output_dir,
                style_profile="engineering_institutional_blue",
                verified_identity_text=[identity],
            )

            self.assertEqual(manifest["verdict"], "pass")
            self.assertEqual(manifest["counts"]["candidate_slide_images"], 0)
            prompts = json.loads((output_dir / "image-prompts.json").read_text(encoding="utf-8"))
            deck = json.loads((output_dir / "deck-spec.json").read_text(encoding="utf-8"))
            style = json.loads((output_dir / "style-contract.json").read_text(encoding="utf-8"))
            report = json.loads(
                (output_dir / "qa" / "official-contract-static-report.json").read_text(encoding="utf-8")
            )

            self.assertEqual(prompts["style_reference"], deck["deck"]["style_reference"])
            self.assertTrue(all(slide["style_reference"] == prompts["style_reference"] for slide in prompts["slides"]))
            self.assertTrue(prompts["prompt_policy"]["candidate_requires_fresh_imagegen"])
            self.assertFalse(prompts["prompt_policy"]["reuse_current_slide_images"])
            self.assertIn(identity, prompts["slides"][0]["prompt_zh"])
            self.assertNotIn(identity, prompts["slides"][1]["prompt_zh"])
            self.assertTrue((output_dir / prompts["slides"][1]["source_asset_paths"][0]).resolve().exists())
            self.assertEqual(style["context_only_sources"][0]["source_tier"], "tier_1_official_university_endpoint_context")
            self.assertFalse(style["context_only_sources"][0]["content_level_extraction_allowed"])
            self.assertFalse(report["checks"]["xjtu_active_visual_authority"])
            self.assertEqual(report["verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
