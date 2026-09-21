from __future__ import annotations

from datetime import date
import unittest

from autopptskills.scripts.build_imagegen_prompt_manifest import build
from autopptskills.scripts.ppt.image_prompt_builder import build_image_prompts
from autopptskills.scripts.style_contracts import (
    FORBIDDEN_INSTITUTIONAL_IDENTITY_ELEMENTS,
    OFFICIAL_REFERENCE_SOURCES,
    OFFICIAL_SOURCE_ARCHETYPE_IDS,
    STYLE_PROFILES,
    get_style_profile,
    merge_style_contract,
    style_profile_choices,
)


class StyleContractsTest(unittest.TestCase):
    def test_prompt_routes_preserve_all_reviewed_support(self) -> None:
        from autoppt_workflow.ppt.image_prompt_builder import build_image_prompts as production_build

        support = [f"已审核证据{i}：方法条件与结果解释" for i in range(1, 7)]
        brief = {"slides": [{
            "title": "方法验证", "page_role": "content",
            "one_sentence_message": "对照实验支持研究结论",
            "supporting_items": support,
        }]}
        for builder in (build_image_prompts, production_build):
            with self.subTest(builder=builder.__module__):
                slide = builder(
                    project_name="风格回归检查", slide_brief=brief,
                    slide_count_min=1, slide_count_max=1,
                )["slides"][0]
                self.assertEqual(slide["supporting_items"], support)
                self.assertTrue(set(support).issubset(slide["exact_text"]))
                self.assertTrue(all(item in slide["prompt_zh"] for item in support))
                self.assertEqual(slide["text_density_mode"], "information-rich-readable")

    def test_stable_profile_catalog_is_complete(self) -> None:
        self.assertEqual(
            style_profile_choices(),
            (
                "academic_light",
                "academic_minimal",
                "deep_academic",
                "editorial_warm",
                "engineering_blueprint",
                "clinical_clean",
                "graduate_defense_navy",
                "institutional_purple_light",
                "engineering_institutional_blue",
                "science_dark_contrast",
                "nsfc_review_light",
            ),
        )
        required = {
            "label",
            "use_when",
            "intentional_minimal",
            "design_density",
            "style_contract",
            "palette",
            "typography",
            "background_rules",
            "layout_rules",
            "icon_rules",
            "design_completion",
            "quality_guardrails",
            "negative_prompt",
        }
        for profile in STYLE_PROFILES.values():
            self.assertTrue(required.issubset(profile))
            self.assertIn("per slide", profile["layout_rules"])
            self.assertTrue(profile["design_completion"].strip())
            self.assertTrue(profile["quality_guardrails"].strip())
        self.assertTrue(STYLE_PROFILES["academic_minimal"]["intentional_minimal"])
        for profile_id, profile in STYLE_PROFILES.items():
            if profile_id != "academic_minimal":
                self.assertFalse(profile["intentional_minimal"])
                self.assertNotEqual(profile["design_density"], "intentional-low")

    def test_aliases_resolve_without_changing_canonical_id(self) -> None:
        self.assertEqual(get_style_profile("engineering")["profile_id"], "engineering_blueprint")
        self.assertEqual(get_style_profile("warm")["profile_id"], "editorial_warm")
        self.assertEqual(get_style_profile("clinical")["profile_id"], "clinical_clean")
        self.assertEqual(get_style_profile("minimal")["profile_id"], "academic_minimal")
        self.assertEqual(get_style_profile("graduate-defense")["profile_id"], "graduate_defense_navy")
        self.assertEqual(get_style_profile("purple-light")["profile_id"], "institutional_purple_light")
        self.assertEqual(get_style_profile("institutional-blue")["profile_id"], "engineering_institutional_blue")
        self.assertEqual(get_style_profile("science-dark")["profile_id"], "science_dark_contrast")
        self.assertEqual(get_style_profile("nsfc")["profile_id"], "nsfc_review_light")

    def test_official_source_archetypes_record_provenance_and_identity_bans(self) -> None:
        required_source_fields = {
            "title",
            "publisher",
            "url",
            "source_tier",
            "source_status",
            "access_method",
            "accessed_on",
            "access_evidence",
            "license_status",
            "extraction_scope",
            "asset_reuse_allowed",
            "allowed_extraction",
        }
        expected_bans = set(FORBIDDEN_INSTITUTIONAL_IDENTITY_ELEMENTS)
        self.assertEqual(set(OFFICIAL_SOURCE_ARCHETYPE_IDS), {
            "graduate_defense_navy",
            "institutional_purple_light",
            "engineering_institutional_blue",
            "science_dark_contrast",
            "nsfc_review_light",
        })
        referenced_source_ids = {
            source_id
            for profile_id in OFFICIAL_SOURCE_ARCHETYPE_IDS
            for source_id in STYLE_PROFILES[profile_id]["source_ids"]
        }
        visual_authority_source_ids = {
            source_id
            for source_id, source in OFFICIAL_REFERENCE_SOURCES.items()
            if source.get("visual_authority_eligible", True)
        }
        self.assertEqual(referenced_source_ids, visual_authority_source_ids)
        self.assertNotIn("xjtu_som_degree_defense", referenced_source_ids)
        self.assertEqual(
            {source["accessed_on"] for source in OFFICIAL_REFERENCE_SOURCES.values()},
            {"2026-09-03"},
        )
        for profile_id in OFFICIAL_SOURCE_ARCHETYPE_IDS:
            profile = get_style_profile(profile_id)
            reference = profile["style_reference"]
            self.assertEqual(reference["reference_mode"], "official-source-inspired-generic-archetype")
            self.assertTrue(reference["official_source_inspired"])
            self.assertFalse(reference["official_template"])
            self.assertTrue(reference["sources"])
            self.assertTrue(reference["allowed_extraction"])
            self.assertTrue(expected_bans.issubset(reference["forbidden_identity_elements"]))
            self.assertIn("not an official template", reference["identity_guard"])
            self.assertIn("university emblem", reference["identity_guard"])
            self.assertIn("campus photograph", reference["identity_guard"])
            self.assertIn("NSFC logo", reference["identity_guard"])
            for source in reference["sources"]:
                self.assertTrue(required_source_fields.issubset(source))
                self.assertTrue(source["url"].startswith(("http://", "https://")))
                self.assertTrue(source["source_tier"].startswith("tier_1_official_"))
                self.assertEqual(source["source_status"], "active")
                self.assertEqual(source["access_method"], "GET")
                date.fromisoformat(source["accessed_on"])
                evidence = source["access_evidence"]
                self.assertEqual(evidence["http_status"], 200)
                self.assertGreater(evidence["response_bytes"], 0)
                self.assertTrue(evidence["content_type"])
                self.assertTrue(evidence["effective_url"].startswith(("http://", "https://")))
                self.assertIn("--request GET", evidence["reproduction_command"])
                self.assertIn("<source-url>", evidence["reproduction_command"])
                self.assertIn("no ", source["license_status"].lower())
                self.assertEqual(source["extraction_scope"], "generic_composition_only_deidentified")
                self.assertFalse(source["asset_reuse_allowed"])
                self.assertTrue(source["allowed_extraction"])

        whut_access = OFFICIAL_REFERENCE_SOURCES["whut_administrative_presentation"]["access_evidence"]
        whut = OFFICIAL_REFERENCE_SOURCES["whut_administrative_presentation"]
        self.assertEqual(whut["title"], "校长办公会议题汇报模板（2025版）")
        self.assertEqual(whut_access["verified_page_title"], whut["title"])
        self.assertEqual(whut_access["published_on"], "2025-09-19")
        self.assertEqual(whut_access["attachment_title"], "校长办公会汇报议题模版.pptx")
        self.assertEqual(whut_access["head_probe_http_status"], 404)
        self.assertIn("use GET", whut_access["health_check_note"])
        xjtu_access = OFFICIAL_REFERENCE_SOURCES["xjtu_som_degree_defense"]["access_evidence"]
        self.assertEqual(xjtu_access["response_bytes"], 7030)
        self.assertIn("网站正在加载中", xjtu_access["content_access_note"])
        self.assertIn("JavaScript browser-validation page", xjtu_access["content_access_note"])
        self.assertIn("interactive browser", xjtu_access["content_access_note"])
        self.assertIn("does not assert the article title", xjtu_access["content_access_note"])
        xjtu = OFFICIAL_REFERENCE_SOURCES["xjtu_som_degree_defense"]
        self.assertFalse(xjtu["visual_authority_eligible"])
        self.assertEqual(xjtu["extraction_scope"], "endpoint_context_only_content_unverified")
        self.assertIn("no page-specific", xjtu["allowed_extraction"][0])
        ustc = OFFICIAL_REFERENCE_SOURCES["ustc_academic_presentation"]
        self.assertEqual(ustc["access_evidence"]["response_bytes"], 43541)
        nsfc = OFFICIAL_REFERENCE_SOURCES["nsfc_2026_program_guide"]
        self.assertEqual(nsfc["title"], "申请规定")
        self.assertEqual(nsfc["access_evidence"]["verified_document_title"], "申请规定")
        self.assertIn("not the complete 2026 program guide", nsfc["access_evidence"]["document_context_note"])

    def test_explicit_overrides_remain_local(self) -> None:
        deck = merge_style_contract(
            {
                "style_profile": "graduate_defense_navy",
                "style_overrides": {
                    "palette": "custom restrained palette",
                    "negative_prompt": "extra local decoration ban",
                },
            }
        )
        self.assertEqual(deck["palette"], "custom restrained palette")
        self.assertIn("continuous", deck["background_rules"])
        self.assertIn("university emblem", deck["negative_prompt"])
        self.assertIn("extra local decoration ban", deck["negative_prompt"])
        self.assertFalse(deck["style_reference"]["official_template"])
        self.assertTrue(deck["style_reference"]["official_source_inspired"])

    def test_official_source_override_conflicts_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "protected provenance"):
            merge_style_contract(
                {
                    "style_profile": "graduate_defense_navy",
                    "style_overrides": {
                        "style_reference": {"official_template": True},
                    },
                }
            )
        with self.assertRaisesRegex(ValueError, "protected identity boundary"):
            merge_style_contract(
                {
                    "style_profile": "graduate_defense_navy",
                    "style_overrides": {
                        "style_contract": "Copy the official template and show a university logo",
                    },
                }
            )

    def test_official_source_override_scanner_uses_ascii_token_boundaries(self) -> None:
        deck = merge_style_contract(
            {
                "style_profile": "graduate_defense_navy",
                "style_overrides": {
                    "palette": "analogous muted blue-green palette with restrained copper",
                },
            }
        )
        self.assertIn("analogous", deck["palette"])
        with self.assertRaisesRegex(ValueError, "protected identity boundary"):
            merge_style_contract(
                {
                    "style_profile": "graduate_defense_navy",
                    "style_overrides": {
                        "style_contract": "show a university_logo in the title band",
                    },
                }
            )

    def test_official_source_override_values_require_prompt_safe_types(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a non-empty string"):
            merge_style_contract(
                {
                    "style_profile": "graduate_defense_navy",
                    "style_overrides": {
                        "style_contract": {"university_logo": True},
                    },
                }
            )

    def test_verified_identity_text_is_an_exact_content_exception(self) -> None:
        identity_text = "武汉理工大学 船海与能源动力工程学院"
        plan = {
            "deck": {
                "title": "Verified thesis defense",
                "style_profile": "engineering_institutional_blue",
                "allowed_identity_text": [identity_text],
            },
            "slides": [
                {
                    "slide_id": "S01",
                    "role": "cover",
                    "headline": "Thesis defense",
                    "message": "Thesis defense",
                    "exact_text": ["本科毕业设计答辩", identity_text],
                    "visual_brief": "A restrained source-backed cover.",
                    "evidence_summary": "Verified thesis identity fields.",
                    "source_refs": ["EV-IDENTITY"],
                },
                {
                    "slide_id": "S02",
                    "role": "content",
                    "headline": "Method overview",
                    "message": "Method overview",
                    "exact_text": ["Method overview"],
                    "visual_brief": "A restrained source-backed method diagram.",
                    "evidence_summary": "Verified method evidence.",
                    "source_refs": ["EV-METHOD"],
                }
            ],
        }
        deck_spec, prompts = build(plan)
        reference = prompts["style_reference"]
        self.assertEqual(reference["verified_identity_text"], [identity_text])
        self.assertEqual(reference["allowed_identity_text"], [identity_text])
        self.assertEqual(deck_spec["deck"]["style_reference"], reference)
        self.assertIn("Verified identity-text exception", prompts["slides"][0]["prompt_zh"])
        self.assertIn(identity_text, prompts["slides"][0]["prompt_zh"])
        self.assertIn("ordinary on-slide text", prompts["slides"][0]["prompt_zh"])
        self.assertIn(
            "unverified or decorative university or school name",
            prompts["slides"][0]["negative_prompt"],
        )
        self.assertNotIn(identity_text, prompts["slides"][1]["prompt_zh"])
        self.assertIn(
            "No institution identity text is authorized on this slide",
            prompts["slides"][1]["prompt_zh"],
        )

        ppt = build_image_prompts(
            project_name="Verified thesis defense",
            slide_brief={
                "slides": [
                    {
                        "title": identity_text,
                        "one_sentence_message": "本科毕业设计答辩",
                        "slide_goal": "Identify the verified defense context",
                        "source_section": "verified thesis cover",
                        "must_say": [],
                        "visual_hint": "A restrained source-backed cover",
                    }
                ]
            },
            slide_count_min=1,
            slide_count_max=1,
            style_profile="engineering_institutional_blue",
            verified_identity_text=identity_text,
        )
        self.assertEqual(ppt["style_reference"]["verified_identity_text"], [identity_text])
        self.assertIn("ordinary on-slide text", ppt["slides"][0]["prompt_zh"])

    def test_identity_like_cover_text_requires_explicit_verification(self) -> None:
        plan = {
            "deck": {
                "title": "Unverified thesis defense",
                "style_profile": "engineering_institutional_blue",
            },
            "slides": [
                {
                    "slide_id": "S01",
                    "role": "cover",
                    "headline": "Thesis defense",
                    "message": "Thesis defense",
                    "exact_text": ["武汉理工大学 船海与能源动力工程学院"],
                    "visual_brief": "A restrained cover.",
                    "evidence_summary": "Identity text has not been explicitly verified.",
                    "source_refs": ["EV-IDENTITY"],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "must be explicitly source-verified"):
            build(plan)

    def test_non_official_ppt_profile_remains_compatible(self) -> None:
        ppt = build_image_prompts(
            project_name="General academic report",
            slide_brief={
                "slides": [
                    {
                        "title": "Conclusion",
                        "one_sentence_message": "Evidence supports the conclusion",
                        "slide_goal": "Explain the result",
                        "source_section": "results",
                        "must_say": ["Source-backed evidence"],
                        "visual_hint": "One dominant result figure",
                    }
                ]
            },
            slide_count_min=1,
            slide_count_max=1,
            style_profile="academic_light",
        )
        self.assertFalse(ppt["style_reference"]["official_source_inspired"])
        self.assertNotIn("official_source_inspired_only", ppt["prompt_policy"])
        self.assertNotIn("Official-Source Reference Boundary:", ppt["slides"][0]["prompt_zh"])

    def test_prompt_contract_guards_against_spectacle_and_underdesign(self) -> None:
        plan = {
            "deck": {
                "title": "Test deck",
                "style_profile": "engineering_blueprint",
            },
            "slides": [
                {
                    "slide_id": "S01",
                    "role": "content",
                    "headline": "A conclusion",
                    "message": "A conclusion",
                    "exact_text": ["A conclusion", "Evidence"],
                    "visual_brief": "A measured engineering system with one primary evidence anchor.",
                    "evidence_summary": "Source-backed evidence.",
                    "source_refs": ["E01"],
                }
            ],
        }
        deck_spec, prompts = build(plan)
        slide = prompts["slides"][0]
        self.assertFalse(deck_spec["deck"]["intentional_minimal"])
        self.assertEqual(slide["design_density"], "technical-rich")
        self.assertIn("Design completion:", slide["prompt_zh"])
        self.assertIn("Quality boundary:", slide["prompt_zh"])
        self.assertIn("neither overdecorated nor under-designed", slide["prompt_zh"])

    def test_official_source_archetype_metadata_reaches_both_prompt_routes(self) -> None:
        plan = {
            "deck": {
                "title": "Test review deck",
                "style_profile": "nsfc_review_light",
            },
            "slides": [
                {
                    "slide_id": "S01",
                    "role": "content",
                    "headline": "Evidence supports the method",
                    "message": "Evidence supports the method",
                    "exact_text": ["Evidence supports the method"],
                    "visual_brief": "One reviewable evidence chain.",
                    "evidence_summary": "Source-backed evidence.",
                    "source_refs": ["E01"],
                }
            ],
        }
        deck_spec, prompts = build(plan)
        reference = prompts["style_reference"]
        self.assertTrue(reference["official_source_inspired"])
        self.assertEqual(deck_spec["deck"]["style_reference"], reference)
        self.assertEqual(prompts["slides"][0]["style_reference"], reference)
        self.assertTrue(prompts["prompt_policy"]["forbid_official_template_claim"])
        self.assertTrue(prompts["prompt_policy"]["forbid_institutional_identity_elements"])
        self.assertIn("not an official template", prompts["slides"][0]["prompt_zh"])
        self.assertIn("Do not show or imitate any university emblem", prompts["slides"][0]["prompt_zh"])

        ppt = build_image_prompts(
            project_name="Thesis project",
            slide_brief={
                "slides": [
                    {
                        "title": "Conclusion",
                        "one_sentence_message": "Evidence supports the conclusion",
                        "slide_goal": "Explain the result",
                        "source_section": "results",
                        "must_say": ["Source-backed evidence"],
                        "visual_hint": "One dominant result figure",
                    }
                ]
            },
            slide_count_min=1,
            slide_count_max=1,
            style_profile="graduate_defense_navy",
        )
        self.assertTrue(ppt["style_reference"]["official_source_inspired"])
        self.assertTrue(ppt["prompt_policy"]["forbid_institutional_identity_elements"])
        self.assertEqual(ppt["slides"][0]["style_reference"], ppt["style_reference"])
        self.assertIn("Official-Source Reference Boundary:", ppt["slides"][0]["prompt_zh"])
        self.assertNotIn("西安交通大学管理学院", ppt["slides"][0]["prompt_zh"])


if __name__ == "__main__":
    unittest.main()
