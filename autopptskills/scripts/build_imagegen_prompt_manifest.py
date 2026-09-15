#!/usr/bin/env python3
"""Build imagegen-first deck and prompt manifests from a reviewed deck plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .style_contracts import (
        identity_prompt_guard,
        merge_style_contract,
        validate_identity_text_exceptions,
    )
except ImportError:  # pragma: no cover - supports direct script execution.
    from style_contracts import (
        identity_prompt_guard,
        merge_style_contract,
        validate_identity_text_exceptions,
    )


def _require(value: Any, label: str) -> Any:
    if value is None or value == "" or value == []:
        raise ValueError(f"missing required value: {label}")
    return value


def _prompt(deck: dict[str, Any], slide: dict[str, Any]) -> str:
    exact_text = "\n".join(f"- {line}" for line in slide["exact_text"])
    forbidden = ", ".join(deck.get("forbidden_visible_text", [])) or "none"
    style_reference = deck["style_reference"]
    reference_boundary = ""
    if style_reference["official_source_inspired"]:
        allowed = "; ".join(style_reference["allowed_extraction"])
        slide_identity_guard = identity_prompt_guard(style_reference, slide["exact_text"])
        reference_boundary = (
            "Reference status: official-source-inspired generic archetype; this is not an official template, "
            "affiliation, or endorsement.\n"
            f"Allowed reference extraction: {allowed}.\n"
            f"Institutional identity guard: {slide_identity_guard}\n"
        )
    use_case = deck.get(
        "use_case",
        "Chinese academic, competition, project, or thesis-defense presentation",
    )
    return (
        f"Use case: {use_case}\n"
        "Asset type: complete final 16:9 PowerPoint slide image, one page only\n"
        f"Project: {deck['title']}\n"
        f"Slide role: {slide['role']}\n"
        f"Primary message: {slide['message']}\n"
        "Canvas: 1920x1080 horizontal. The whole output must be one finished slide page.\n"
        f"Style profile: {deck['style_profile']}\n"
        f"Design system: {deck['style_contract']}\n"
        f"Color palette: {deck['palette']}\n"
        f"Typography: {deck['typography']}\n"
        f"Background discipline: {deck['background_rules']}\n"
        f"Layout discipline: {deck['layout_rules']}\n"
        f"Icon discipline: {deck['icon_rules']}\n"
        f"Design density: {deck['design_density']}; intentional minimal style: {str(deck['intentional_minimal']).lower()}\n"
        f"Design completion: {deck['design_completion']}\n"
        f"Quality boundary: {deck['quality_guardrails']}\n"
        f"{reference_boundary}"
        f"Information density: {slide.get('density_target', 'balanced: one message, one dominant visual, up to three supporting regions')}\n"
        "Exact on-slide text, render verbatim and do not invent additional labels:\n"
        f"{exact_text}\n"
        f"Visual composition: {slide['visual_brief']}\n"
        f"Source-grounded evidence: {slide['evidence_summary']}\n"
        "Composition rules: keep a stable title band; use one dominant visual system; "
        "show relationships, metrics, comparison, and evidence visually; maintain strong hierarchy; "
        "avoid empty decorative space; use no more than six major visual zones; preserve mature design finish "
        "without adding effects that do not explain the content.\n"
        "Vectorization-aware rules: use clean flat text regions, measurable card/line geometry, "
        "bounded simple icons, and clear separation between text and complex artwork. "
        "Keep complex photos and illustrations visually rich, but do not place normal text inside them.\n"
        f"Forbidden visible text: {forbidden}.\n"
        f"Style-specific negative constraints: {deck['negative_prompt']}.\n"
        "Hard constraints: no page number, no watermark, no fake logo, no unsupported number, "
        "no random English, no placeholder text, no gibberish, no text outside the slide, "
        "no blank template, no later local renderer substitute.\n"
        "Readability: all main Chinese text must remain legible on a projected screen; "
        "titles stay on one line; dense evidence uses compact but readable typography. "
        "The page must be neither overdecorated nor under-designed for the selected profile."
    )


def build(plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    deck = merge_style_contract(_require(plan.get("deck"), "deck"))
    slides = _require(plan.get("slides"), "slides")
    _require(deck.get("title"), "deck.title")
    for key in (
        "style_contract",
        "palette",
        "typography",
        "design_completion",
        "quality_guardrails",
    ):
        _require(deck.get(key), f"deck.{key}")

    deck_slides: list[dict[str, Any]] = []
    prompt_slides: list[dict[str, Any]] = []
    seen: set[str] = set()
    validate_identity_text_exceptions(
        deck,
        [str(item) for slide in slides for item in (slide.get("exact_text") or [])],
    )
    for index, slide in enumerate(slides, 1):
        slide_id = str(_require(slide.get("slide_id"), f"slides[{index}].slide_id"))
        if slide_id in seen:
            raise ValueError(f"duplicate slide_id: {slide_id}")
        seen.add(slide_id)
        for key in ("role", "headline", "message", "exact_text", "visual_brief", "evidence_summary", "source_refs"):
            _require(slide.get(key), f"{slide_id}.{key}")
        final_path = slide.get("final_path") or f"assets/slides/{slide_id}.png"
        evidence_refs = slide.get("evidence_refs") or slide["source_refs"]
        deck_slides.append({
            "slide_id": slide_id,
            "role": slide["role"],
            "layout": "full_slide_image",
            "headline": slide["headline"],
            "slide_image": final_path,
            "imagegen_prompt_ref": slide_id,
            "source_refs": slide["source_refs"],
            "evidence_refs": evidence_refs,
            "transition_from_previous": slide.get("transition_from_previous", ""),
        })
        prompt_slides.append({
            "slide_id": slide_id,
            "page_role": slide["role"],
            "headline": slide["headline"],
            "message": slide["message"],
            "layout_recipe": slide.get("layout_recipe", "information-dense visual narrative"),
            "image_size": "16:9",
            "final_path": final_path,
            "variant_paths": [f"assets/generated/{slide_id}-v1.png"],
            "exact_text": slide["exact_text"],
            "text_density_mode": slide.get("text_density_mode", "dense"),
            "density_target": slide.get("density_target", "80-140 Chinese characters plus 3-6 evidence points"),
            "style_profile": deck["style_profile"],
            "style_contract_summary": deck["style_contract"],
            "design_density": deck["design_density"],
            "intentional_minimal": deck["intentional_minimal"],
            "design_completion": deck["design_completion"],
            "quality_guardrails": deck["quality_guardrails"],
            "style_reference": deck["style_reference"],
            "layout_blueprint_summary": slide["visual_brief"],
            "source_assets": slide.get("source_assets", []),
            "source_refs": slide["source_refs"],
            "evidence_refs": evidence_refs,
            "prompt_zh": _prompt(deck, slide),
            "prompt_en": "",
            "negative_prompt": f"{deck['negative_prompt']}, gibberish, random English, fake numbers, placeholder, unreadable tiny text",
            "acceptance_criteria": slide.get("acceptance_criteria", [
                "complete final PPT page image",
                "source-grounded exact text regions",
                "high information density with clear hierarchy",
                "profile-appropriate design completion without spectacle or unfinished-template appearance",
                "vectorization-friendly text and geometry separation",
                "no unsupported facts",
            ]),
            "expected_output": "complete final PPT page image",
            "regeneration_hint": slide.get("regeneration_hint", "Fix only the failed density, fidelity, hierarchy, or text-separation issue."),
            "retry_prompt_delta": "",
        })

    deck_spec = {
        "deck": {
            "title": deck["title"],
            "style_profile": deck["style_profile"],
            "style_contract": deck["style_contract"],
            "design_density": deck["design_density"],
            "intentional_minimal": deck["intentional_minimal"],
            "style_reference": deck["style_reference"],
            "output_mode": "imagegen_full_slide",
            "generation_mode": "direct_final_slide_imagegen",
            "assembly_note": "One fresh imagegen full-slide image per PPT page; semantic reconstruction follows assembly.",
        },
        "slides": deck_slides,
    }
    prompt_policy = {
        "backend": "builtin_image_gen",
        "output_mode": "direct_final_slide_imagegen",
        "imagegen_required": True,
        "auto_invoke_builtin_imagegen": True,
        "builtin_imagegen_only": True,
        "external_api_key_allowed": False,
        "external_cli_allowed": False,
        "local_command_allowed": False,
        "mock_formal_output_allowed": False,
        "fallback_allowed": False,
        "one_call_per_slide": True,
        "on_block": "retry_builtin_or_stop",
        "per_slide_imagegen_required": True,
        "fresh_prompt_per_slide": True,
        "forbid_reusing_old_generations": True,
        "forbid_generic_master_template_first": True,
        "complete_final_page_required": True,
        "allow_text_free_visual_base_plus_local_overlay": False,
        "forbid_text_free_visual_base_plus_local_overlay": True,
        "no_native_ppt_overlay": True,
        "no_template_reuse": True,
        "no_script_generated_slide_content": True,
    }
    if deck["style_reference"]["official_source_inspired"]:
        prompt_policy.update(
            {
                "official_source_inspired_only": True,
                "forbid_official_template_claim": True,
                "forbid_institutional_identity_elements": True,
            }
        )

    prompts = {
        "deck_title": deck["title"],
        "style_profile": deck["style_profile"],
        "style_reference": deck["style_reference"],
        "prompt_policy": prompt_policy,
        "slides": prompt_slides,
    }
    return deck_spec, prompts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan")
    parser.add_argument("--deck-spec-out", required=True)
    parser.add_argument("--prompt-manifest-out", required=True)
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    deck_spec, prompts = build(plan)
    for path_value, data in (
        (args.deck_spec_out, deck_spec),
        (args.prompt_manifest_out, prompts),
    ):
        path = Path(path_value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"slides": len(deck_spec["slides"]), "deck": deck_spec["deck"]["title"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
