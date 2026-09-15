from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

from .evidence import (
    build_figure_source_manifest,
    build_paper_analysis,
    build_requirement_matrix,
    build_source_manifest,
    write_source_map,
)
from .profiles import get_presentation_profile
from .schemas import (
    build_slide_ir,
    normalize_evidence_ledger,
    read_json,
    sha256_file,
    utc_now,
    validate_slide_contract,
    write_json,
)

PRESENTATION_ROUTES = (
    "fullpage_imagegen_reconstruct",
    "fullpage_imagegen_native_overlay",
    "existing_pptx_edit",
)


def normalize_presentation_route(route: str | None, *, explicit: bool = False) -> str:
    value = (route or "fullpage_imagegen_reconstruct").strip().lower().replace("-", "_")
    if value not in PRESENTATION_ROUTES:
        raise ValueError(f"unknown presentation route: {route}; choose from {', '.join(PRESENTATION_ROUTES)}")
    if value == "native_only":
        raise ValueError(
            "native_only is disabled by the builtin-imagegen-only workflow policy; "
            "use the built-in image_gen route and repair/retry any blocker"
        )
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_json(path: Path) -> dict[str, Any]:
    payload = read_json(path, {})
    return payload if isinstance(payload, dict) else {}


def _action_title(raw: dict[str, Any], index: int, profile: dict[str, Any]) -> str:
    title = str(raw.get("action_title") or raw.get("title") or raw.get("one_sentence_message") or "").strip()
    if title:
        return title
    narrative = profile.get("narrative", [])
    return str(narrative[index - 1] if narrative and index <= len(narrative) else f"第{index}页需要回答的核心问题")


def _role_for(index: int, count: int, profile: dict[str, Any], raw: dict[str, Any]) -> str:
    explicit = str(raw.get("page_role") or "").strip()
    if explicit:
        return explicit
    roles = profile.get("page_roles", [])
    if not roles:
        return "cover" if index == 1 else ("closing_summary" if index == count else "content")
    if index == 1 and "cover" in roles:
        return "cover"
    if index == count and "closing_summary" in roles:
        return "closing_summary"
    middle = [role for role in roles if role not in {"cover", "closing_summary"}]
    return middle[(index - 2) % len(middle)] if middle else "content"


def normalize_slide_brief(slide_brief: dict[str, Any], *, profile: dict[str, Any]) -> dict[str, Any]:
    raw_slides = slide_brief.get("slides", []) if isinstance(slide_brief, dict) else []
    count = len(raw_slides)
    slides: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_slides, start=1):
        item = dict(raw) if isinstance(raw, dict) else {}
        item["slide_id"] = str(item.get("slide_id") or f"S{index:02d}")
        item["title"] = _action_title(item, index, profile)
        item["action_title"] = item["title"]
        item["core_question"] = str(item.get("core_question") or item.get("slide_goal") or item.get("one_sentence_message") or f"{item['title']}需要由什么证据回答？").strip()
        item["page_role"] = _role_for(index, count, profile, item)
        item["speaker_duration_seconds"] = int(item.get("speaker_duration_seconds") or item.get("duration_seconds") or profile.get("default_duration_seconds", 60))
        existing_support = item.get("supporting_items") or item.get("must_say") or []
        item["supporting_items"] = [str(v).strip() for v in existing_support if str(v).strip()][:3]
        item["claim_ids"] = [str(v) for v in item.get("claim_ids", []) if str(v).strip()]
        slides.append(item)
    return {
        "schema_version": "slide-brief-presentation-v1",
        "deck_title": slide_brief.get("deck_title") or slide_brief.get("title") or "",
        "slides": slides,
        "profile": profile.get("profile_id"),
    }


def _prompt_contract(slide: dict[str, Any], profile: dict[str, Any], evidence_ids: list[str]) -> dict[str, Any]:
    title = str(slide.get("action_title") or slide.get("title") or "").strip()
    return {
        "slide_id": slide.get("slide_id"),
        "page_role": slide.get("page_role", "content"),
        "title": title,
        "one_sentence_message": slide.get("one_sentence_message") or slide.get("core_question", ""),
        "must_say": slide.get("supporting_items", [])[:3],
        "action_title": title,
        "core_question": slide.get("core_question", ""),
        "main_visual": {
            "type": profile.get("imagegen_route", "fullpage_imagegen_reconstruct"),
            "source": f"assets/slides/{slide.get('slide_id')}.png",
        },
        "supporting_items": slide.get("supporting_items", [])[:3],
        "claim_ids": slide.get("claim_ids", []),
        "evidence_ids": evidence_ids,
        "speaker_duration_seconds": slide.get("speaker_duration_seconds", profile.get("default_duration_seconds", 60)),
        "source_locations": [str(v) for v in (slide.get("source_locations") or slide.get("source_refs") or [slide.get("source_section", "")]) if str(v).strip()],
        "source_section": slide.get("source_section", ""),
        "visual_hint": slide.get("visual_hint", ""),
        "one_sentence_message": slide.get("one_sentence_message") or slide.get("core_question", ""),
    }


def _deck_plan_markdown(deck_plan: dict[str, Any]) -> str:
    lines = [
        f"# Deck Plan — {deck_plan.get('deck_title', '')}",
        "",
        f"- Profile: `{deck_plan.get('presentation_profile', '')}`",
        f"- ImageGen route: `{deck_plan.get('imagegen_route', '')}`",
        f"- Slide count: `{len(deck_plan.get('slides', []))}`",
        f"- Total speaking time (seconds): `{deck_plan.get('total_duration_seconds', 0)}`",
        "",
        "| Slide | Role | Action Title | Core Question | Evidence | Duration |",
        "|---|---|---|---|---|---:|",
    ]
    for slide in deck_plan.get("slides", []):
        lines.append(
            f"| {slide.get('slide_id')} | {slide.get('page_role')} | {slide.get('action_title','').replace('|','/')} | {slide.get('core_question','').replace('|','/')} | {', '.join(slide.get('evidence_ids', [])) or 'review'} | {slide.get('speaker_duration_seconds', 0)}s |"
        )
    lines.extend(["", "## Planning rules", "", "- Each slide answers one core question and has one primary visual.", "- Action titles are conclusions, not topic labels; confirm wording against the source evidence before release.", "- A missing evidence link is a review item, never permission to invent a claim.", "- Full-page ImageGen remains the default visual route; native reconstruction is a later semantic layer.", ""])
    return "\n".join(lines)


def build_deck_plan(*, slide_brief: dict[str, Any], profile: dict[str, Any], evidence_ledger: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_slide_brief(slide_brief, profile=profile)
    evidence_items = evidence_ledger.get("evidence_items", []) if isinstance(evidence_ledger, dict) else []
    known_ids = [str(item.get("evidence_id")) for item in evidence_items if item.get("evidence_id")]
    slides: list[dict[str, Any]] = []
    for slide in normalized["slides"]:
        explicit = slide.get("evidence_ids") or slide.get("evidence_refs") or []
        ids: list[str] = []
        for value in explicit:
            text = str(value)
            for match in re.findall(r"(?:auto_ev|ev)[A-Za-z0-9_.-]*|E\d{1,4}", text):
                if match in known_ids and match not in ids:
                    ids.append(match)
            if text in known_ids and text not in ids:
                ids.append(text)
        evidence_assignment = "explicit"
        if not ids and known_ids:
            ids = [known_ids[(len(slides)) % len(known_ids)]]
            evidence_assignment = "fallback_round_robin_review_required"
        prompt_contract = _prompt_contract(slide, profile, ids)
        prompt_contract["evidence_assignment"] = evidence_assignment
        slides.append(prompt_contract)
    for index, slide in enumerate(slides):
        slide["previous_slide_link"] = slides[index - 1]["slide_id"] if index else None
        slide["next_slide_link"] = slides[index + 1]["slide_id"] if index + 1 < len(slides) else None
    plan = {
        "schema_version": "deck-plan-v1",
        "generated_at": utc_now(),
        "deck_title": normalized.get("deck_title") or "",
        "presentation_profile": profile.get("profile_id"),
        "style_profile": profile.get("style_profile"),
        "imagegen_route": profile.get("imagegen_route", "fullpage_imagegen_reconstruct"),
        "slides": slides,
        "total_duration_seconds": sum(int(item.get("speaker_duration_seconds") or 0) for item in slides),
        "rules": {
            "one_question_per_slide": profile.get("one_question_per_slide", True),
            "one_primary_visual": profile.get("one_primary_visual", True),
            "max_supporting_items": profile.get("max_supporting_items", 3),
            "action_title_required": profile.get("action_title_required", True),
        },
    }
    return plan


def build_design_spec(*, profile: dict[str, Any], deck_title: str) -> dict[str, Any]:
    return {
        "schema_version": "design-spec-v1",
        "generated_at": utc_now(),
        "deck_title": deck_title,
        "presentation_profile": profile.get("profile_id"),
        "style_profile": profile.get("style_profile"),
        "colors": profile.get("style_profile"),
        "typography": "large projector-readable Chinese sans-serif; short labels; no tiny footnotes",
        "spacing": "measured 16:9 grid with generous margins and explicit object bboxes in reconstruction",
        "chart_palette": "source chart colors first; otherwise restrained profile palette",
        "image_rendering": "full-page ImageGen first; source-grounded photos/figures preferred; no fabricated metrics",
        "icon_style": "bounded flat icons or source assets; editable class recorded per object",
        "decoration_density": "evidence-serving only; reject spectacle and unfinished scaffolds",
        "animation_policy": profile.get("animation_policy", "no_animation"),
        "citation_style": profile.get("citation_style", "compact_source_footer"),
        "route_policy": {
            "default": "fullpage_imagegen_reconstruct",
            "allowed": ["fullpage_imagegen_reconstruct", "fullpage_imagegen_native_overlay", "existing_pptx_edit"],
            "native_only_disabled_by_builtin_imagegen_policy": True,
        },
        "quality_guardrails": profile.get("forbidden", []),
    }


def build_spec_lock(*, profile: dict[str, Any], design_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "spec-lock-v1",
        "locked_at": utc_now(),
        "presentation_profile": profile.get("profile_id"),
        "imagegen_route": profile.get("imagegen_route"),
        "design_spec_sha256": _sha256_text(json.dumps(design_spec, ensure_ascii=False, sort_keys=True)),
        "locked_rules": [
            "fullpage_imagegen_required_before_reconstruction",
            "source_grounded_text_and_numbers_only",
            "one_core_question_and_one_primary_visual_per_slide",
            "no_animation_for_default_delivery",
            "movable_image_is_not_fully_editable",
        ],
    }


def build_imagegen_manifest(*, prompts: dict[str, Any], stage45_dir: Path | None = None, asset_manifest_path: Path | None = None, route: str | None = None) -> dict[str, Any]:
    asset_manifest = _safe_json(asset_manifest_path) if asset_manifest_path else {}
    generated_by_slide = {str(item.get("slide_id")): item for item in asset_manifest.get("slides", []) if isinstance(item, dict)}
    records: list[dict[str, Any]] = []
    for slide in prompts.get("slides", []):
        sid = str(slide.get("slide_id"))
        prompt = str(slide.get("prompt_zh") or slide.get("prompt_en") or "")
        record = generated_by_slide.get(sid, {})
        image_path = None
        if stage45_dir:
            candidate = stage45_dir / str(slide.get("final_path") or f"assets/slides/{sid}.png")
            if candidate.exists():
                image_path = candidate
        if not image_path and record.get("path"):
            candidate = Path(str(record.get("path")))
            if candidate.exists():
                image_path = candidate
        records.append(
            {
                "slide_id": sid,
                "model": record.get("model") or "gpt-image-2",
                "prompt_sha256": _sha256_text(prompt),
                "prompt_ref": f"prompts/{sid}.md",
                "input_assets": slide.get("source_assets", []),
                "output_path": str(image_path.resolve()) if image_path else str(slide.get("final_path", "")),
                "output_sha256": sha256_file(image_path) if image_path else "",
                "generated_at": record.get("generated_at") or record.get("timestamp") or "",
                "status": record.get("status") or ("generated" if image_path else "planned"),
                "human_modified": bool(record.get("human_modified", False)),
                "visual_review": record.get("visual_review", "pending"),
                "route": route or prompts.get("imagegen_route") or "fullpage_imagegen_reconstruct",
            }
        )
    return {
        "schema_version": "imagegen-manifest-v1",
        "generated_at": utc_now(),
        "route": route or prompts.get("imagegen_route") or "fullpage_imagegen_reconstruct",
        "model_policy": "record actual model per slide; never claim a generated image when status is planned or blocked",
        "slides": records,
    }


def build_reconstruction_manifest(*, slide_ir: dict[str, Any], imagegen_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create the stable hybrid reconstruction contract.

    This keeps the existing planned-layer manifest compatible while adding the
    component-level routing/provenance fields needed by the img2pptx-derived
    Object Router.  It is a plan until a per-slide reconstruction run writes
    measured bboxes and confidence values.
    """
    generated = {str(item.get("slide_id")): item for item in (imagegen_manifest or {}).get("slides", [])}
    slides = []
    for slide in slide_ir.get("slides", []):
        sid = str(slide.get("slide_id"))
        exact_text = []
        for key in ("action_title", "title", "subtitle", "core_question"):
            value = slide.get(key)
            if isinstance(value, str) and value.strip():
                exact_text.append(value.strip())
        for key in ("supporting_items", "must_say", "labels", "footnotes"):
            values = slide.get(key) or []
            if isinstance(values, str):
                values = [values]
            exact_text.extend(str(value).strip() for value in values if str(value).strip())
        components = [
            {
                "id": f"{sid}::background",
                "semantic_type": "background",
                "parent_id": None,
                "bbox": [0.0, 0.0, 1.0, 1.0],
                "z_index": 0,
                "content_id": None,
                "render_type": "raster_asset",
                "style": {},
                "editable": False,
                "confidence": 1.0,
                "provenance": "imagegen_master",
            },
            {
                "id": f"{sid}::title",
                "semantic_type": "title",
                "parent_id": None,
                "bbox": None,
                "z_index": 100,
                "content_id": f"{sid}.action_title",
                "render_type": "native_text",
                "style": {},
                "editable": True,
                "confidence": 0.0,
                "provenance": "slide_manifest",
            },
            {
                "id": f"{sid}::geometry",
                "semantic_type": "simple_geometry",
                "parent_id": None,
                "bbox": None,
                "z_index": 80,
                "content_id": None,
                "render_type": "native_shape",
                "style": {},
                "editable": True,
                "confidence": 0.0,
                "provenance": "measured_visual_reference",
            },
        ]
        slides.append(
            {
                "slide_id": sid,
                "source_imagegen_master": generated.get(sid, {}).get("output_path") or slide.get("main_visual", {}).get("source"),
                "content_authority": "slide_manifest > reviewed_source_text > OCR_geometry",
                "exact_text": list(dict.fromkeys(exact_text)),
                "components": components,
                "layers": [
                    {"id": f"{sid}-background", "semantic_role": "background", "editable_class": "visual_only", "source": "continuous_fullpage_imagegen_background"},
                    {"id": f"{sid}-title", "semantic_role": "title", "editable_class": "native", "source": "source_text_or_evidence_ledger"},
                    {"id": f"{sid}-support", "semantic_role": "supporting_text", "editable_class": "native", "source": "source_text_or_evidence_ledger"},
                    {"id": f"{sid}-geometry", "semantic_role": "simple_geometry", "editable_class": "native", "source": "measured_reconstruction_when_present"},
                    {"id": f"{sid}-evidence", "semantic_role": "complex_evidence_asset", "editable_class": "movable_image", "source": "original_figure_or_verified_imagegen_crop"},
                ],
                "reconstruction_status": "planned",
                "review_required": True,
            }
        )
    return {
        "schema_version": "component-manifest-v1",
        "generated_at": utc_now(),
        "route": "fullpage_imagegen_reconstruct",
        "editability_classes": ["native", "convertible-vector", "movable-image", "visual-only", "needs-review"],
        "render_types": ["native_text", "native_shape", "native_connector", "native_table", "native_chart", "svg_group", "raster_asset"],
        "slides": slides,
    }


def prepare_presentation_package(
    topic_dir: Path,
    *,
    profile_name: str = "innovation_competition_defense",
    slide_brief_path: Path | None = None,
    evidence_paths: Iterable[Path] = (),
    prompts: dict[str, Any] | None = None,
    existing_paper_analysis: Path | None = None,
    imagegen_route: str | None = None,
) -> dict[str, Any]:
    topic_dir = topic_dir.resolve()
    profile = get_presentation_profile(profile_name)
    if imagegen_route is not None:
        profile["imagegen_route"] = normalize_presentation_route(imagegen_route, explicit=True)
    package_dir = topic_dir / "final" / "ppt"
    package_dir.mkdir(parents=True, exist_ok=True)
    slide_brief_path = slide_brief_path or topic_dir / "workspace" / "stage8_handoff" / "slide_brief.json"
    slide_brief = _safe_json(slide_brief_path)
    ledgers = [_safe_json(path) for path in evidence_paths if path and path.exists()]
    evidence_ledger = normalize_evidence_ledger(ledgers, source_label="; ".join(str(path) for path in evidence_paths))
    source_manifest = build_source_manifest(topic_dir, extra_paths=[slide_brief_path, *list(evidence_paths)])
    figure_manifest = build_figure_source_manifest(topic_dir, source_manifest=source_manifest)
    deck_plan = build_deck_plan(slide_brief=slide_brief, profile=profile, evidence_ledger=evidence_ledger)
    slide_ir = build_slide_ir({"slides": deck_plan.get("slides", [])}, profile=profile, evidence_ledger=evidence_ledger)
    # Preserve explicit deck-plan fields that are not part of the old slide brief.
    slide_ir["slides"] = [dict(item, **{k: v for k, v in plan.items() if k not in {"source_slide"}}) for item, plan in zip(slide_ir.get("slides", []), deck_plan.get("slides", []))]
    design_spec = build_design_spec(profile=profile, deck_title=deck_plan.get("deck_title", ""))
    spec_lock = build_spec_lock(profile=profile, design_spec=design_spec)
    paper_analysis = build_paper_analysis(
        profile=profile,
        slide_ir=slide_ir,
        evidence_ledger=evidence_ledger,
        figure_manifest=figure_manifest,
        existing=_safe_json(existing_paper_analysis) if existing_paper_analysis and existing_paper_analysis.exists() else None,
    )
    requirement_matrix = build_requirement_matrix(profile=profile, slide_ir=slide_ir, evidence_ledger=evidence_ledger)
    paths = {
        "profile": package_dir / "presentation_profile.json",
        "source_manifest": package_dir / "source_manifest.json",
        "figure_source_manifest": package_dir / "figure_source_manifest.json",
        "evidence_ledger": package_dir / "evidence_ledger.json",
        "paper_analysis": package_dir / "paper_analysis.json",
        "requirement_matrix": package_dir / "requirement_matrix.json",
        "deck_plan": package_dir / "deck_plan.json",
        "deck_plan_md": package_dir / "deck_plan.md",
        "slide_ir": package_dir / "slide_ir.json",
        "design_spec": package_dir / "design_spec.json",
        "design_spec_md": package_dir / "design_spec.md",
        "spec_lock": package_dir / "spec_lock.json",
        "spec_lock_md": package_dir / "spec_lock.md",
        "source_map": package_dir / "source_map.md",
        "prompts_dir": package_dir / "prompts",
    }
    write_json(paths["profile"], profile)
    write_json(paths["source_manifest"], source_manifest)
    write_json(paths["figure_source_manifest"], figure_manifest)
    write_json(paths["evidence_ledger"], evidence_ledger)
    write_json(paths["paper_analysis"], paper_analysis)
    write_json(paths["requirement_matrix"], requirement_matrix)
    write_json(paths["deck_plan"], deck_plan)
    paths["deck_plan_md"].write_text(_deck_plan_markdown(deck_plan) + "\n", encoding="utf-8")
    write_json(paths["slide_ir"], slide_ir)
    write_json(paths["design_spec"], design_spec)
    paths["design_spec_md"].write_text("# Design Spec\n\n" + "\n".join(f"- **{key}**: {value}" for key, value in design_spec.items() if key not in {"quality_guardrails", "route_policy"}) + "\n", encoding="utf-8")
    write_json(paths["spec_lock"], spec_lock)
    paths["spec_lock_md"].write_text(
        "# Spec Lock\n\n"
        + "\n".join(f"- **{key}**: {value}" for key, value in spec_lock.items() if key != "locked_rules")
        + "\n\n## Locked rules\n\n"
        + "\n".join(f"- {rule}" for rule in spec_lock.get("locked_rules", []))
        + "\n",
        encoding="utf-8",
    )
    write_source_map(paths["source_map"], source_manifest=source_manifest, evidence_ledger=evidence_ledger, slide_ir=slide_ir)
    paths["prompts_dir"].mkdir(parents=True, exist_ok=True)
    for slide in deck_plan.get("slides", []):
        (paths["prompts_dir"] / f"{slide.get('slide_id')}.md").write_text(
            f"# {slide.get('slide_id')} — {slide.get('action_title', '')}\n\n"
            f"- Page role: `{slide.get('page_role', '')}`\n"
            f"- Core question: {slide.get('core_question', '')}\n"
            f"- Evidence IDs: {', '.join(slide.get('evidence_ids', [])) or 'review required'}\n\n"
            "The complete ImageGen prompt is written after the prompt builder runs.\n",
            encoding="utf-8",
        )
    # Mirror the canonical planning/evidence artifacts at project root because
    # the long-lived project contract names them there. The final/ppt copies
    # remain the PPT handoff location and are the source of truth for runs.
    for key in (
        "evidence_ledger", "paper_analysis", "requirement_matrix", "source_manifest",
        "figure_source_manifest", "deck_plan", "deck_plan_md", "slide_ir", "design_spec_md", "spec_lock_md", "source_map",
    ):
        root_name = {
            "deck_plan_md": "deck_plan.md",
            "design_spec_md": "design_spec.md",
            "spec_lock_md": "spec_lock.md",
            "source_map": "source_map.md",
        }.get(key, f"{key}.json")
        shutil.copy2(paths[key], topic_dir / root_name)
    if prompts is not None:
        imagegen_manifest = build_imagegen_manifest(prompts=prompts)
        write_json(package_dir / "imagegen_manifest.json", imagegen_manifest)
        paths["imagegen_manifest"] = package_dir / "imagegen_manifest.json"
    reconstruction_manifest = build_reconstruction_manifest(slide_ir=slide_ir, imagegen_manifest=None)
    write_json(package_dir / "reconstruction" / "editability_manifest.json", reconstruction_manifest)
    paths["reconstruction_manifest"] = package_dir / "reconstruction" / "editability_manifest.json"
    return {
        "profile": profile,
        "deck_plan": deck_plan,
        "slide_ir": slide_ir,
        "evidence_ledger": evidence_ledger,
        "source_manifest": source_manifest,
        "figure_source_manifest": figure_manifest,
        "requirement_matrix": requirement_matrix,
        "paths": {key: str(path) for key, path in paths.items()},
        "contract_report": validate_slide_contract(slide_ir, require_evidence=False),
    }


def _gate(verdict: str, *, issues: list[str] | None = None, warnings: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"schema_version": "presentation-gate-v1", "generated_at": utc_now(), "verdict": verdict, "issues": issues or [], "warnings": warnings or [], **extra}


def run_presentation_gates(
    topic_dir: Path,
    *,
    package: dict[str, Any],
    prompts: dict[str, Any] | None = None,
    stage45_dir: Path | None = None,
    final_deck: Path | None = None,
    mock: bool = False,
) -> dict[str, Any]:
    topic_dir = topic_dir.resolve()
    validation_dir = topic_dir / "final" / "ppt" / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    source = package.get("source_manifest", {})
    evidence = package.get("evidence_ledger", {})
    deck_plan = package.get("deck_plan", {})
    slide_ir = package.get("slide_ir", {})
    contract = package.get("contract_report", validate_slide_contract(slide_ir))
    source_issues = []
    if not source.get("sources"):
        source_issues.append("no_source_files_discovered")
    source_report = _gate("pass" if not source_issues else "fail", issues=source_issues, source_count=source.get("source_count", 0), unreadable=source.get("summary", {}).get("unreadable", 0))
    evidence_issues = []
    if not evidence.get("evidence_items"):
        evidence_issues.append("evidence_ledger_empty")
    unconfirmed = [item.get("evidence_id") for item in evidence.get("evidence_items", []) if not item.get("confirmed")]
    evidence_report = _gate("pass" if not evidence_issues else "fail", issues=evidence_issues, warnings=[f"unconfirmed_evidence:{eid}" for eid in unconfirmed[:20]], evidence_count=len(evidence.get("evidence_items", [])))
    plan_issues = list(contract.get("issues", []))
    plan_report = _gate("pass" if not plan_issues else "fail", issues=plan_issues, warnings=contract.get("warnings", []), slide_count=len(deck_plan.get("slides", [])), total_duration_seconds=deck_plan.get("total_duration_seconds", 0), profile=deck_plan.get("presentation_profile"))
    image_issues = []
    image_warnings = []
    if prompts is None:
        image_issues.append("imagegen_prompts_missing")
    else:
        for slide in prompts.get("slides", []):
            if not slide.get("prompt_zh") and not slide.get("prompt_en"):
                image_issues.append(f"{slide.get('slide_id')}:missing_prompt")
            if not slide.get("evidence_refs"):
                image_warnings.append(f"{slide.get('slide_id')}:missing_evidence_refs")
            if "Evidence anchors:" not in str(slide.get("prompt_zh", "")):
                image_issues.append(f"{slide.get('slide_id')}:missing_evidence_anchor_block")
        if stage45_dir:
            manifest_path = stage45_dir / "references" / "asset-manifest.json"
            manifest = build_imagegen_manifest(prompts=prompts, stage45_dir=stage45_dir, asset_manifest_path=manifest_path)
            planned = [item for item in manifest.get("slides", []) if item.get("status") == "planned"]
            reused = [item for item in manifest.get("slides", []) if item.get("status") in {"skipped_existing", "existing"}]
            missing_images = [item.get("slide_id") for item in manifest.get("slides", []) if not item.get("output_sha256")]
            if planned and not mock:
                image_issues.extend(f"{item.get('slide_id')}:image_not_generated" for item in planned)
            if reused and not mock:
                image_issues.extend(f"{item.get('slide_id')}:image_reused_existing" for item in reused)
            if missing_images:
                image_issues.extend(f"{sid}:image_missing" for sid in missing_images)
            image_report_manifest = manifest
        else:
            image_report_manifest = {}
    if mock:
        image_warnings.append("mock_images_do_not_prove_final_visual_quality")
    image_report = _gate("warn" if not image_issues and mock else ("pass" if not image_issues else "fail"), issues=image_issues, warnings=image_warnings, route="fullpage_imagegen_reconstruct", mock_mode=mock, manifest=image_report_manifest if prompts is not None else {})
    reconstruction_report = _gate("blocked", issues=["reconstruction_not_run"], warnings=["semantic editability requires a later reconstruction pass"], final_deck=str(final_deck or ""))
    render_report = _gate("blocked", issues=["powerpoint_render_not_run"], warnings=["structural preparation is not visual acceptance"], final_deck=str(final_deck or ""))
    defense_issues = []
    if not deck_plan.get("slides"):
        defense_issues.append("no_slides")
    if deck_plan.get("total_duration_seconds", 0) <= 0:
        defense_issues.append("total_duration_missing")
    defense_report = _gate("pass" if not defense_issues else "fail", issues=defense_issues, warnings=["anticipated_questions_and_speaker_notes are generated after final slide review"] if not defense_issues else [])
    reports = {
        "source_report": source_report,
        "evidence_report": evidence_report,
        "deck_plan_report": plan_report,
        "imagegen_report": image_report,
        "reconstruction_report": reconstruction_report,
        "render_report": render_report,
        "defense_readiness_report": defense_report,
    }
    for name, payload in reports.items():
        write_json(validation_dir / f"{name}.json", payload)
    write_json(validation_dir / "presentation_gate_summary.json", {"schema_version": "presentation-gates-v1", "generated_at": utc_now(), "reports": reports, "verdict": "pass" if all(item["verdict"] == "pass" for item in reports.values()) else "blocked"})
    return reports


def build_defense_materials(topic_dir: Path, *, package: dict[str, Any], reports: dict[str, Any]) -> dict[str, str]:
    """Create source-grounded notes/scripts without regenerating slide images."""
    out_dir = topic_dir.resolve() / "final" / "ppt" / "speaker_notes"
    out_dir.mkdir(parents=True, exist_ok=True)
    slides = package.get("slide_ir", {}).get("slides", [])
    notes: list[str] = ["# Speaker Notes", ""]
    script: list[str] = ["# Defense Script", ""]
    questions: list[str] = ["# Anticipated Questions", "", "## Innovation and value", "", "- 创新点与已有工作的区别是什么？", "- 这个问题为什么值得研究？", "- 项目或研究的实际贡献是什么？", "", "## Method and data", "", "- 数据从哪里来？", "- 实验是否可重复？", "- 为什么选择这个方法？", "- 指标是否足以支持结论？", "", "## Boundary and risk", "", "- 项目有什么局限？", "- 如果核心假设不成立怎么办？", "- 当前结果能否推广？", "- 下一步研究是什么？", ""]
    for slide in slides:
        sid = slide.get("slide_id", "")
        title = slide.get("action_title", "")
        transition = f"从上一页到本页，我们转向：{title}。"
        body = f"本页回答：{slide.get('core_question', '')}。重点依据：{', '.join(slide.get('evidence_ids', [])) or '待补证据'}。"
        close = "因此，本页只保留与该结论直接相关的证据。"
        duration = int(slide.get("speaker_duration_seconds") or 0)
        notes.extend([f"## {sid} — {title}", "", f"- 转场：{transition}", f"- 核心讲解：{body}", f"- 视觉说明：主视觉路线为 `{slide.get('main_visual', {}).get('type', 'fullpage_imagegen_reconstruct')}`。", f"- 收束：{close}", f"- 建议时长：{duration} 秒", f"- 证据：{', '.join(slide.get('evidence_ids', [])) or '待补'}", ""])
        script.extend([f"## {sid} {title}", "", transition, body, close, ""])
    (out_dir / "speaker_notes.md").write_text("\n".join(notes), encoding="utf-8")
    (out_dir / "defense_script.md").write_text("\n".join(script), encoding="utf-8")
    (out_dir / "anticipated_questions.md").write_text("\n".join(questions), encoding="utf-8")
    return {name: str(out_dir / name) for name in ("speaker_notes.md", "defense_script.md", "anticipated_questions.md")}


def find_affected_slides(*, previous_evidence: dict[str, Any], current_evidence: dict[str, Any], slide_ir: dict[str, Any]) -> list[str]:
    """Return slides whose evidence links changed; used by resume/local reruns."""
    def index(payload: dict[str, Any]) -> dict[str, str]:
        return {str(item.get("evidence_id")): json.dumps(item, ensure_ascii=False, sort_keys=True) for item in payload.get("evidence_items", []) if item.get("evidence_id")}
    before, after = index(previous_evidence), index(current_evidence)
    changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
    affected = []
    for slide in slide_ir.get("slides", []):
        if changed.intersection(str(value) for value in slide.get("evidence_ids", [])):
            affected.append(str(slide.get("slide_id")))
    return affected
