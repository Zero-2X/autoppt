from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:
    from autopptskills.scripts.approved_style import APPROVED_STYLE_PROMPT
    from autopptskills.scripts.style_contracts import get_style_profile
except ImportError:  # pragma: no cover
    for parent in Path(__file__).resolve().parents:
        if (parent / "autopptskills" / "scripts" / "style_contracts.py").exists():
            sys.path.insert(0, str(parent))
            break
    from autopptskills.scripts.approved_style import APPROVED_STYLE_PROMPT
    from autopptskills.scripts.style_contracts import get_style_profile


PROMPT_POLICY: dict[str, Any] = {
    # The repository cannot invoke Codex's built-in image_gen from a
    # subprocess.  These fields make the handoff contract explicit so a
    # downstream bridge cannot silently select an API, CLI, or mock backend.
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
    "default_visual_route": "fullpage_imagegen_reconstruct",
    "allowed_visual_routes": [
        "fullpage_imagegen_reconstruct",
        "fullpage_imagegen_native_overlay",
        "existing_pptx_edit",
    ],
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_slide_id(slide_no: int) -> str:
    return f"S{slide_no:02d}"


def slide_text_items(slide: dict[str, Any]) -> list[str]:
    items = [
        str(slide.get("action_title") or slide.get("title", "")).strip(),
        str(slide.get("one_sentence_message") or slide.get("core_question", "")).strip(),
    ]
    support = slide.get("supporting_items") or slide.get("must_say", [])
    items.extend(str(item).strip() for item in support)
    return [item for item in items if item]


def normalize_evidence_items(ledgers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ledger in ledgers:
        raw_items = ledger.get("evidence_items") or ledger.get("evidence") or ledger.get("items") or []
        for item in raw_items:
            if isinstance(item, dict) and item.get("evidence_id"):
                items.append(item)
    return items


def evidence_anchor_text(item: dict[str, Any]) -> str:
    evidence_id = str(item.get("evidence_id", "")).strip()
    title = str(item.get("title") or item.get("source_title") or item.get("source_path") or "").strip()
    claim = str(item.get("claim") or item.get("summary") or "").strip()
    reliability = str(item.get("reliability", "")).strip()
    text = title or claim or evidence_id
    return f"{evidence_id}: {text[:90]} | reliability={reliability or 'unknown'}"


def evidence_refs_for_slide(evidence_items: list[dict[str, Any]], slide_index: int, limit: int = 3) -> list[str]:
    usable = [
        item for item in evidence_items
        if str(item.get("reliability", "")).strip().lower() in {"high", "medium", ""}
    ]
    if not usable:
        return []
    offset = (slide_index - 1) % len(usable)
    ordered = usable[offset:] + usable[:offset]
    return [evidence_anchor_text(item) for item in ordered[:limit]]


def load_improvement_context(limit: int = 12) -> dict[str, Any]:
    """Load recent PPT lessons without making generation depend on a run log."""
    root = Path(__file__).resolve().parents[2]
    ledger = root / "improvement" / "ppt-improvement-ledger.jsonl"
    handbook = root / "improvement" / "style-handbook.md"
    rules: list[str] = []
    failures: list[str] = []
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            for value in row.get("learned_rules", []) if isinstance(row, dict) else []:
                text = str(value).strip()
                if text and text not in rules:
                    rules.append(text)
            reusable = str(row.get("reusable_rule", "")).strip() if isinstance(row, dict) else ""
            if reusable and reusable not in rules:
                rules.append(reusable)
            for value in row.get("failures", []) if isinstance(row, dict) else []:
                text = str(value).strip()
                if text and text not in failures:
                    failures.append(text)
            problem = str(row.get("problem", "")).strip() if isinstance(row, dict) else ""
            if problem and row.get("status") not in {"accepted", "resolved"} and problem not in failures:
                failures.append(problem)
    handbook_excerpt = ""
    if handbook.exists():
        handbook_excerpt = handbook.read_text(encoding="utf-8")[:3500]
    return {"rules": rules[-20:], "failures": failures[-20:], "handbook_excerpt": handbook_excerpt}


def build_prompt_zh(project_name: str, slide: dict[str, Any], slide_id: str, evidence_refs: list[str], style_profile: dict[str, Any] | None = None, improvement_context: dict[str, Any] | None = None) -> str:
    title = str(slide.get("action_title") or slide.get("title", slide_id)).strip()
    message = str(slide.get("one_sentence_message") or slide.get("core_question", "")).strip()
    goal = str(slide.get("slide_goal", "")).strip()
    source_section = str(slide.get("source_section", "")).strip()
    visual_hint = str(slide.get("visual_hint", "")).strip()
    must_say = "；".join(str(item).strip() for item in (slide.get("supporting_items") or slide.get("must_say", [])) if str(item).strip())

    evidence_anchor_block = "\n".join(f"- {item}" for item in evidence_refs) or "- none"

    style = style_profile or get_style_profile("academic_light")
    context = improvement_context or {}
    learned_rules = "\n".join(f"- {item}" for item in context.get("rules", [])) or "- No prior run-specific rules; follow the style contract."
    known_failures = "\n".join(f"- {item}" for item in context.get("failures", [])) or "- No recorded failures."
    return f"""Canvas:
16:9 horizontal presentation slide, 1280x720 or 1920x1080, complete final PPT page image.

Slide Purpose:
{goal or "Make this page clear for competition judges."}

Source-Grounded Content:
Project: {project_name}
Source section: {source_section or "final works book"}
Main message: {message}
Required talking points: {must_say or "use only source-supported points"}
Evidence anchors:
{evidence_anchor_block}

Exact On-Slide Text:
Title: {title}
Main line: {message}
Render the reviewed title, main line, and all necessary talking points verbatim. Use grouped readable short sentences and explicit line breaks; preserve explanation, units, conditions, and conclusions.

Approved Workflow Style:
{APPROVED_STYLE_PROMPT}

Style Contract:
Profile: {style['profile_id']}. {style['style_contract']}
Palette: {style['palette']}
Typography: {style['typography']}
Background discipline: {style['background_rules']}
Layout discipline: {style['layout_rules']}
Icon discipline: {style['icon_rules']}
Animation policy: no animation; compose a static complete slide page.

Continuous Improvement Context (must avoid repeating these failures):
Known failure signals from prior PPT runs:
{known_failures}
Reusable rules already validated:
{learned_rules}

Layout Blueprint:
One strong headline and one dominant visual composition. Follow the slide-specific visual hint. Use supporting cards only for genuinely independent regions; do not default to a repeated dashboard grid. Keep generous margins and large text.

Visual Elements:
{visual_hint or "source-grounded conceptual diagram that explains the slide message"}

Typography And Readability:
Large Chinese text, high contrast, no tiny footnotes, all labels readable from a projector.

Evidence And Asset Safety:
Use the evidence anchors only as factual boundaries. Do not invent numbers, logos, rankings, screenshots, certificates, awards, customers, or UI states. Mark conceptual visuals as conceptual through generic system diagrams.

Negative Constraints:
No watermark, no random English, no gibberish Chinese, no placeholder text, no template marks, no old slide reuse, no local overlay placeholders.
Avoid: {style['negative_prompt']}.

Acceptance Criteria:
The image itself is a complete final slide page. Judges can understand the point within five seconds. The page feels restrained and academic, has one clear hierarchy, and contains no blank areas that look unfinished.

Regeneration Plan:
If text is unreadable, repair grouping, explicit line breaks and text-region sizes, then regenerate the full page while retaining reviewed evidence and explanatory text. Return to content planning if wording must change; never reduce the page to title plus labels."""


def build_image_prompts(
    *,
    project_name: str,
    slide_brief: dict[str, Any],
    evidence_ledgers: list[dict[str, Any]] | None = None,
    slide_count_min: int = 8,
    slide_count_max: int = 12,
    style_profile: str = "academic_light",
) -> dict[str, Any]:
    raw_slides = list(slide_brief.get("slides", []))
    if not raw_slides:
        raise ValueError("slide_brief.json contains no slides.")
    slides = raw_slides[:slide_count_max]
    if len(slides) < slide_count_min:
        raise ValueError(f"PPT requires at least {slide_count_min} slides; got {len(slides)}.")

    evidence_items = normalize_evidence_items(evidence_ledgers or [])
    style = get_style_profile(style_profile)
    improvement_context = load_improvement_context()
    prompt_slides: list[dict[str, Any]] = []
    for index, slide in enumerate(slides, start=1):
        slide_id = normalize_slide_id(index)
        evidence_refs = evidence_refs_for_slide(evidence_items, index)
        prompt_slides.append(
            {
                "slide_id": slide_id,
                "page_role": slide.get("page_role") or ("cover" if index == 1 else ("closing" if index == len(slides) else "content")),
                "headline": slide.get("action_title") or slide.get("title", slide_id),
                "layout_recipe": "judge-facing-infographic",
                "image_size": "16:9",
                "final_path": f"assets/slides/{slide_id}.png",
                "variant_paths": [f"assets/generated/{slide_id}-v1.png"],
                "exact_text": slide_text_items(slide),
                "text_density_mode": "information-rich-readable",
                "style_profile": style["profile_id"],
                "style_contract_summary": style["style_contract"],
                "layout_blueprint_summary": slide.get("visual_hint", ""),
                "core_question": slide.get("core_question", ""),
                "supporting_items": list(slide.get("supporting_items") or slide.get("must_say") or []),
                "claim_ids": list(slide.get("claim_ids") or []),
                "evidence_ids": list(slide.get("evidence_ids") or []),
                "speaker_duration_seconds": int(slide.get("speaker_duration_seconds") or slide.get("duration_seconds") or 60),
                "previous_slide_link": slide.get("previous_slide_link"),
                "next_slide_link": slide.get("next_slide_link"),
                "source_locations": list(slide.get("source_locations") or []),
                "source_assets": [],
                "source_refs": [slide.get("source_section", ""), *evidence_refs],
                "evidence_refs": evidence_refs,
                "prompt_zh": build_prompt_zh(project_name, slide, slide_id, evidence_refs, style, improvement_context),
                "prompt_en": "",
                "negative_prompt": style["negative_prompt"],
                "acceptance_criteria": [
                    "complete final PPT page image",
                    "readable Chinese text",
                    "single clear judge-facing message",
                    "no unsupported facts",
                ],
                "expected_output": "complete final PPT page image",
                "regeneration_hint": "Repair grouping, line breaks, text regions and readability while preserving reviewed scientific information; never reduce to title plus labels.",
                "retry_prompt_delta": "",
                "source_slide": slide,
            }
        )

    return {
        "deck_title": project_name,
        "style_profile": style["profile_id"],
        "improvement_context": improvement_context,
        "prompt_policy": PROMPT_POLICY,
        "slides": prompt_slides,
    }


def write_prompt_pack(path: Path, image_prompts: dict[str, Any]) -> None:
    lines = [f"# Imagegen Prompt Pack - {image_prompts.get('deck_title', '')}", ""]
    for slide in image_prompts.get("slides", []):
        lines.extend(
            [
                f"## {slide.get('slide_id')} - {slide.get('headline', '')}",
                "",
                str(slide.get("prompt_zh", "")).strip(),
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
