from __future__ import annotations

import json
import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

try:
    from .image_prompt_builder import build_image_prompts, write_json, write_prompt_pack
    from .imagegen_queue_builder import build_generation_queue
    from .pptx_builder import build_deck_spec, build_pptx
    from .slide_auditor import audit_ppt, write_json as write_audit_json
    from .builtin_imagegen_policy import (
        BuiltinImageGenBlocked,
        build_builtin_asset_manifest,
        validate_builtin_imagegen_outputs,
        write_builtin_blocker_report,
    )
    from .builtin_imagegen_handoff import prepare_handoff
except ImportError:  # pragma: no cover - supports direct script execution.
    from image_prompt_builder import build_image_prompts, write_json, write_prompt_pack
    from imagegen_queue_builder import build_generation_queue
    from pptx_builder import build_deck_spec, build_pptx
    from slide_auditor import audit_ppt, write_json as write_audit_json
    from builtin_imagegen_policy import (
        BuiltinImageGenBlocked,
        build_builtin_asset_manifest,
        validate_builtin_imagegen_outputs,
        write_builtin_blocker_report,
    )
    from builtin_imagegen_handoff import prepare_handoff

try:
    from autoppt_workflow.presentation.orchestrator import (
        build_defense_materials,
        build_imagegen_manifest,
        prepare_presentation_package,
        run_presentation_gates,
    )
except ImportError:  # pragma: no cover - direct PPT execution from its folder.
    _repo_root = Path(__file__).resolve().parents[2]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from autoppt_workflow.presentation.orchestrator import (
        build_defense_materials,
        build_imagegen_manifest,
        prepare_presentation_package,
        run_presentation_gates,
    )
from autoppt_workflow.presentation.profiles import get_presentation_profile


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def preflight_real_imagegen(workspace_dir: Path) -> list[str]:
    """Return blockers for the built-in ImageGen-only real path.

    This function deliberately does not inspect ``OPENAI_API_KEY``, provider
    URLs, CLI paths, or local command templates.  Those are forbidden routes;
    the only accepted input is a PNG plus provenance produced by the Codex
    built-in ``image_gen`` call.
    """
    prompt_path = Path(workspace_dir) / "image-prompts.json"
    prompts = read_json(prompt_path) if prompt_path.exists() else None
    issues, _records = validate_builtin_imagegen_outputs(Path(workspace_dir), prompts)
    policy = (prompts or {}).get("prompt_policy", {}) if isinstance(prompts, dict) else {}
    if policy.get("backend") != "builtin_image_gen":
        issues.append("builtin_imagegen_backend_policy_missing")
    if policy.get("builtin_imagegen_only") is not True:
        issues.insert(0, "builtin_imagegen_only_policy_missing")
    if policy.get("external_api_key_allowed") is not False:
        issues.append("external_api_key_route_not_explicitly_forbidden")
    if policy.get("external_cli_allowed") is not False:
        issues.append("external_cli_route_not_explicitly_forbidden")
    if policy.get("local_command_allowed") is not False:
        issues.append("local_imagegen_route_not_explicitly_forbidden")
    if policy.get("fallback_allowed") is not False:
        issues.append("builtin_imagegen_fallback_not_explicitly_forbidden")
    if policy.get("one_call_per_slide") is not True:
        issues.append("builtin_imagegen_one_call_policy_missing")
    if policy.get("on_block") != "retry_builtin_or_stop":
        issues.append("builtin_imagegen_block_policy_missing")
    return issues


def update_workspace_state(
    topic_dir: Path,
    status: str,
    *,
    final_deck: Path,
    ppt_audit: Path,
    presentation_profile: str = "",
    imagegen_route: str = "",
) -> None:
    state_path = topic_dir / "workspace" / "state" / "workspace-state.json"
    if not state_path.exists():
        return
    state = read_json(state_path)
    state["current_phase"] = "ppt"
    state["current_phase_status"] = status
    state.setdefault("phase_status", {})["ppt"] = status
    state["active_focus"] = "PPT/imagegen handoff complete" if status == "completed" else "PPT/imagegen blocked"
    state["current_direction"] = "competition deck generated through ImageGen assembly adapter"
    if presentation_profile:
        state["presentation_profile"] = presentation_profile
    if imagegen_route:
        state["imagegen_route"] = imagegen_route
    state["next_action"] = "pipeline_complete" if status == "completed" else "fix_ppt"
    state["next_actions"] = [state["next_action"]]
    state["resume_entrypoint"] = "final/ppt/ppt_audit.json"
    state["last_completed_artifact"] = "final/ppt/final_deck.pptx" if status == "completed" else "final/ppt/ppt_audit.json"
    state["required_inputs"] = [] if status == "completed" else ["inspect final/ppt/ppt_audit.json"]
    state["blocking_reason"] = "" if status == "completed" else "PPT audit failed."
    state["ppt_outputs"] = {
        "final_deck": str(final_deck.relative_to(topic_dir)) if final_deck.exists() else str(final_deck),
        "ppt_audit": str(ppt_audit.relative_to(topic_dir)) if ppt_audit.exists() else str(ppt_audit),
    }
    write_json(state_path, state)


def write_ppt_failure(
    *,
    topic_dir: Path,
    final_ppt_dir: Path,
    image_prompts: dict[str, Any],
    project_name: str,
    reason: str,
    details: list[str],
    existing_final_deck: Path,
) -> dict[str, Any]:
    final_deck = final_ppt_dir / "final_deck.pptx"
    audit = {
        "verdict": "fail",
        "mock_mode": False,
        "mock_visual_risk": False,
        "slide_count": len(image_prompts.get("slides", [])),
        "pptx_exists": final_deck.exists(),
        "issues": [reason, *details],
        "warnings": [
            "real imagegen failed before a new verified deck was produced",
            "existing final_deck.pptx was preserved" if existing_final_deck.exists() else "no previous final_deck.pptx existed",
        ],
        "presentation_gate": {
            "judge_facing": False,
            "slide_count_8_to_12": 8 <= len(image_prompts.get("slides", [])) <= 12,
            "has_prompt_per_slide": all(
                bool(slide.get("prompt_zh") or slide.get("prompt_en"))
                for slide in image_prompts.get("slides", [])
            ),
            "no_placeholder_detected": False,
        },
        "slides": [
            {
                "slide_id": slide.get("slide_id", ""),
                "image_exists": (final_ppt_dir / "images" / f"{slide.get('slide_id', '')}.png").exists(),
                "prompt_exists": bool(slide.get("prompt_zh") or slide.get("prompt_en")),
                "headline": slide.get("headline", ""),
                "mock": False,
            }
            for slide in image_prompts.get("slides", [])
        ],
    }
    write_audit_json(final_ppt_dir / "ppt_audit.json", audit)
    write_text(
        final_ppt_dir / "ppt_build_report.md",
        "\n".join(
            [
                "# PPT Build Report",
                "",
                f"- Project: {project_name}",
                "- Mock Mode: False",
                "- Status: blocked",
                f"- Failure Reason: `{reason}`",
                f"- Final Deck Preserved: `{final_deck.exists()}`",
                "",
                "## Details",
                *[f"- `{item}`" for item in details],
                "",
            ]
        ),
    )
    update_workspace_state(topic_dir, "blocked", final_deck=final_deck, ppt_audit=final_ppt_dir / "ppt_audit.json")
    return {
        "phase": "ppt",
        "status": "blocked",
        "mock": False,
        "project_name": project_name,
        "slide_count": len(image_prompts.get("slides", [])),
        "final_workbook": str(topic_dir / "final" / "final_workbook.md"),
        "imagegen_prompts": str(final_ppt_dir / "imagegen_prompts.json"),
        "images_dir": str(final_ppt_dir / "images"),
        "final_deck": str(final_deck),
        "ppt_audit": str(final_ppt_dir / "ppt_audit.json"),
        "presentation_profile": image_prompts.get("presentation_profile", "innovation_competition_defense"),
        "validation_dir": str(final_ppt_dir / "validation"),
        "audit": audit,
    }


def find_one(paths: list[Path], description: str) -> Path:
    for path in paths:
        if path.exists():
            return path
    raise FileNotFoundError(f"Missing {description}: " + ", ".join(str(path) for path in paths))


def find_final_workbook(topic_dir: Path) -> Path:
    handoff = topic_dir / "workspace" / "presentation_handoff"
    candidates = sorted(handoff.glob("作品书_*_定稿.md"))
    if candidates:
        return candidates[0]
    output_candidates = sorted((topic_dir / "output").glob("作品书_*_定稿.md"))
    if output_candidates:
        return output_candidates[0]
    return find_one([handoff / "作品书_定稿.md"], "final workbook markdown")


def load_project_name(topic_dir: Path) -> str:
    card_path = topic_dir / "workspace" / "idea_brief" / "idea-card.json"
    if card_path.exists():
        card = read_json(card_path)
        return str(card.get("project_name") or card.get("title") or topic_dir.name)
    return topic_dir.name.replace("topic_", "")


def font(size: int) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:
                pass
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font_obj: ImageFont.ImageFont, max_width: int) -> list[str]:
    chars = list(text)
    lines: list[str] = []
    current = ""
    for char in chars:
        test = current + char
        bbox = draw.textbbox((0, 0), test, font=font_obj)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines[:4]


def render_mock_slide(path: Path, *, project_name: str, slide: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1280, 720
    img = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(img)
    title_font = font(54)
    body_font = font(31)
    small_font = font(23)
    tag_font = font(20)

    slide_id = str(slide.get("slide_id", "Sxx"))
    title = str(slide.get("headline", slide_id))
    source = slide.get("source_refs", [""])[0] if slide.get("source_refs") else ""
    exact_text = [str(item) for item in slide.get("exact_text", []) if str(item).strip()]

    draw.rectangle((0, 0, width, 86), fill="#0F172A")
    draw.text((46, 24), project_name, fill="#E2E8F0", font=small_font)
    draw.text((width - 128, 24), slide_id, fill="#A7F3D0", font=small_font)
    draw.rounded_rectangle((56, 126, 804, 594), radius=18, fill="#FFFFFF", outline="#CBD5E1", width=2)
    draw.rounded_rectangle((842, 126, 1218, 594), radius=18, fill="#E0F2FE", outline="#7DD3FC", width=2)

    y = 156
    for line in wrap_text(draw, title, title_font, 690):
        draw.text((92, y), line, fill="#0F172A", font=title_font)
        y += 64
    y += 12
    for item in exact_text[1:5]:
        for line in wrap_text(draw, item, body_font, 660):
            draw.text((104, y), line, fill="#334155", font=body_font)
            y += 42
        y += 6

    draw.ellipse((940, 176, 1118, 354), fill="#38BDF8", outline="#0284C7", width=5)
    draw.line((1030, 354, 1030, 496), fill="#0284C7", width=8)
    draw.line((932, 424, 1128, 424), fill="#0284C7", width=8)
    draw.text((888, 526), "MOCK IMAGEGEN", fill="#0369A1", font=tag_font)
    if source:
        draw.text((56, 642), f"source: {source}", fill="#64748B", font=tag_font)
    draw.text((1014, 642), "PPT mock", fill="#94A3B8", font=tag_font)
    img.save(path, quality=95)


def copy_ppt_outputs(workspace_dir: Path, final_ppt_dir: Path, image_prompts: dict[str, Any]) -> None:
    image_dir = final_ppt_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for slide in image_prompts.get("slides", []):
        slide_id = slide.get("slide_id")
        src = workspace_dir / slide.get("final_path", f"assets/slides/{slide_id}.png")
        dst = image_dir / f"{slide_id}.png"
        if src.exists():
            shutil.copy2(src, dst)


def run_real_imagegen(workspace_dir: Path) -> None:
    """Assemble a real deck from verified built-in ImageGen outputs only.

    The actual ``image_gen`` call is a Codex built-in tool invocation owned by
    the agent.  This repository process is intentionally a consumer/validator;
    it never shells out to an API/CLI/local provider and never reads an API key.
    """
    workspace_dir = Path(workspace_dir).resolve()
    prompt_path = workspace_dir / "image-prompts.json"
    prompts = read_json(prompt_path) if prompt_path.exists() else None
    issues, _records = validate_builtin_imagegen_outputs(workspace_dir, prompts)
    policy = (prompts or {}).get("prompt_policy", {}) if isinstance(prompts, dict) else {}
    if policy.get("builtin_imagegen_only") is not True:
        issues.insert(0, "builtin_imagegen_only_policy_missing")
    if policy.get("external_api_key_allowed") is not False:
        issues.append("external_api_key_route_not_explicitly_forbidden")
    if policy.get("external_cli_allowed") is not False:
        issues.append("external_cli_route_not_explicitly_forbidden")
    if policy.get("local_command_allowed") is not False:
        issues.append("local_imagegen_route_not_explicitly_forbidden")
    if issues:
        report = write_builtin_blocker_report(workspace_dir, issues, image_prompts=prompts)
        raise BuiltinImageGenBlocked(issues, report_path=report)

    build_deck_spec(workspace_dir, prompts or {})
    manifest = build_builtin_asset_manifest(workspace_dir, prompts)
    write_json(workspace_dir / "references" / "asset-manifest.json", manifest)
    output_path = workspace_dir / "pptx" / "output" / "ppt_competition_deck.pptx"
    report_path = workspace_dir / "pptx" / "output" / "build-report.json"
    build_pptx(workspace_dir, output_path, report_path)


def run_ppt(
    topic_dir: Path,
    *,
    mock: bool = False,
    force: bool = False,
    style_profile: str | None = None,
    presentation_profile: str = "innovation_competition_defense",
    imagegen_route: str | None = None,
) -> dict[str, Any]:
    topic_dir = topic_dir.resolve()
    final_dir = topic_dir / "final"
    final_ppt_dir = final_dir / "ppt"
    workspace_dir = final_ppt_dir / "imagegen_workspace"
    source_dir = workspace_dir / "source-materials"
    refs_dir = workspace_dir / "references"
    slides_dir = workspace_dir / "assets" / "slides"
    output_dir = workspace_dir / "pptx" / "output"

    project_name = load_project_name(topic_dir)
    workbook_path = find_final_workbook(topic_dir)
    slide_brief_path = find_one(
        [
            topic_dir / "workspace" / "presentation_handoff" / "slide_brief.json",
            topic_dir / "handoff" / "slide_brief.json",
        ],
        "slide_brief.json",
    )
    ppt_outline_path = find_one(
        [
            topic_dir / "workspace" / "presentation_handoff" / "ppt_outline.md",
            topic_dir / "handoff" / "ppt_outline.md",
        ],
        "ppt_outline.md",
    )
    evidence_path = find_one(
        [topic_dir / "workspace" / "evidence_workspace" / "evidence-ledger.json"],
        "evidence-ledger.json",
    )
    research_evidence_path = topic_dir / "workspace" / "research" / "evidence-ledger.json"

    if force and workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    refs_dir.mkdir(parents=True, exist_ok=True)
    slides_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    final_ppt_dir.mkdir(parents=True, exist_ok=True)

    final_workbook = final_dir / "final_workbook.md"
    final_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(workbook_path, final_workbook)
    shutil.copy2(workbook_path, source_dir / "final_workbook.md")
    shutil.copy2(slide_brief_path, source_dir / "slide_brief.json")
    shutil.copy2(ppt_outline_path, source_dir / "ppt_outline.md")
    shutil.copy2(evidence_path, source_dir / "evidence-ledger.json")
    if research_evidence_path.exists():
        shutil.copy2(research_evidence_path, source_dir / "research-evidence-ledger.json")
    shutil.copy2(slide_brief_path, final_ppt_dir / "slide_brief.json")
    shutil.copy2(ppt_outline_path, final_ppt_dir / "ppt_outline.md")

    visual_manifest = topic_dir / "workspace" / "presentation_handoff" / "visual-manifest.json"
    if visual_manifest.exists():
        shutil.copy2(visual_manifest, source_dir / "visual-manifest.json")

    slide_brief = read_json(slide_brief_path)
    evidence_ledgers = [read_json(evidence_path)]
    if research_evidence_path.exists():
        evidence_ledgers.append(read_json(research_evidence_path))
    profile = get_presentation_profile(presentation_profile)
    package = prepare_presentation_package(
        topic_dir,
        profile_name=presentation_profile,
        slide_brief_path=slide_brief_path,
        evidence_paths=[evidence_path, research_evidence_path] if research_evidence_path.exists() else [evidence_path],
        imagegen_route=imagegen_route,
    )
    profile = package["profile"]
    effective_style = style_profile or str(profile.get("style_profile") or "academic_light")
    planned_slide_brief = {"deck_title": package["deck_plan"].get("deck_title") or project_name, "slides": package["deck_plan"].get("slides", [])}
    image_prompts = build_image_prompts(
        project_name=project_name,
        slide_brief=planned_slide_brief,
        evidence_ledgers=evidence_ledgers,
        slide_count_min=int(profile.get("default_slide_range", (8, 12))[0]),
        slide_count_max=int(profile.get("default_slide_range", (8, 12))[1]),
        style_profile=effective_style,
    )
    image_prompts["presentation_profile"] = presentation_profile
    image_prompts["imagegen_route"] = profile.get("imagegen_route", "fullpage_imagegen_reconstruct")
    image_prompts["slide_contract_schema"] = "slide-ir-v1"
    image_prompts["deck_plan_path"] = str(package["paths"].get("deck_plan", ""))
    write_json(workspace_dir / "image-prompts.json", image_prompts)
    write_json(final_ppt_dir / "imagegen_prompts.json", image_prompts)
    write_prompt_pack(refs_dir / "imagegen-prompt-pack.md", image_prompts)
    if not mock:
        handoff_path = workspace_dir / "builtin-imagegen-handoff.json"
        if not handoff_path.exists():
            try:
                prepare_handoff(workspace_dir / "image-prompts.json", output=handoff_path)
            except Exception as exc:  # noqa: BLE001 - report the exact handoff blocker below.
                write_text(
                    refs_dir / "builtin-imagegen-handoff-prepare-error.txt",
                    f"{exc.__class__.__name__}: {exc}\n",
                )
    prompt_dir = final_ppt_dir / "prompts"
    root_prompt_dir = topic_dir / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    root_prompt_dir.mkdir(parents=True, exist_ok=True)
    for prompt_slide in image_prompts.get("slides", []):
        sid = str(prompt_slide.get("slide_id"))
        prompt_text = str(prompt_slide.get("prompt_zh") or prompt_slide.get("prompt_en") or "")
        prompt_file = prompt_dir / f"{sid}.md"
        prompt_file.write_text(f"# ImageGen Prompt — {sid}\n\n{prompt_text}\n", encoding="utf-8")
        shutil.copy2(prompt_file, root_prompt_dir / prompt_file.name)

    queue = build_generation_queue(workspace_dir, image_prompts, mock=mock)
    if mock:
        for item in queue:
            slide = next(s for s in image_prompts["slides"] if s["slide_id"] == item["slide_id"])
            render_mock_slide(Path(item["final_path"]), project_name=project_name, slide=slide)
            item["status"] = "generated"
        write_json(workspace_dir / "imagegen-queue.json", {"mock": mock, "items": queue})
        build_deck_spec(workspace_dir, image_prompts)
        imagegen_pptx = output_dir / "ppt_competition_deck.pptx"
        build_report = output_dir / "build-report.json"
        build_pptx(workspace_dir, imagegen_pptx, build_report)
    else:
        write_json(workspace_dir / "imagegen-queue.json", {"mock": mock, "items": queue})
        build_deck_spec(workspace_dir, image_prompts)
        preflight_issues = preflight_real_imagegen(workspace_dir)
        if preflight_issues:
            blocker_report = write_builtin_blocker_report(
                workspace_dir,
                preflight_issues,
                image_prompts=image_prompts,
            )
            run_presentation_gates(
                topic_dir,
                package=package,
                prompts=image_prompts,
                workspace_dir=workspace_dir,
                final_deck=final_ppt_dir / "final_deck.pptx",
                mock=False,
            )
            build_defense_materials(topic_dir, package=package, reports={})
            return write_ppt_failure(
                topic_dir=topic_dir,
                final_ppt_dir=final_ppt_dir,
                image_prompts=image_prompts,
                project_name=project_name,
                reason="ppt_real_imagegen_preflight_failed",
                details=[*preflight_issues, f"blocker_report={blocker_report}"],
                existing_final_deck=final_ppt_dir / "final_deck.pptx",
            )
        try:
            run_real_imagegen(workspace_dir)
        except BuiltinImageGenBlocked as exc:
            run_presentation_gates(topic_dir, package=package, prompts=image_prompts, workspace_dir=workspace_dir, final_deck=final_ppt_dir / "final_deck.pptx", mock=False)
            build_defense_materials(topic_dir, package=package, reports={})
            return write_ppt_failure(
                topic_dir=topic_dir,
                final_ppt_dir=final_ppt_dir,
                image_prompts=image_prompts,
                project_name=project_name,
                reason="builtin_imagegen_required",
                details=[*exc.issues, f"blocker_report={exc.report_path}"],
                existing_final_deck=final_ppt_dir / "final_deck.pptx",
            )
        imagegen_pptx = output_dir / "ppt_competition_deck.pptx"
    final_deck = final_ppt_dir / "final_deck.pptx"
    shutil.copy2(imagegen_pptx, final_deck)
    copy_ppt_outputs(workspace_dir, final_ppt_dir, image_prompts)

    audit = audit_ppt(
        image_prompts=image_prompts,
        image_dir=final_ppt_dir / "images",
        pptx_path=final_deck,
        mock=mock,
        asset_manifest_path=workspace_dir / "references" / "asset-manifest.json",
        slide_range=tuple(profile.get("default_slide_range", (8, 12))),
        presentation_profile=presentation_profile,
    )
    write_audit_json(final_ppt_dir / "ppt_audit.json", audit)
    imagegen_manifest = build_imagegen_manifest(
        prompts=image_prompts,
        workspace_dir=workspace_dir,
        asset_manifest_path=workspace_dir / "references" / "asset-manifest.json",
    )
    sidecar_dir = workspace_dir / "assets" / "slides"
    final_sidecar_dir = final_ppt_dir / "assets" / "slides"
    final_sidecar_dir.mkdir(parents=True, exist_ok=True)
    for slide in image_prompts.get("slides", []):
        sid = str(slide.get("slide_id"))
        prompt_text = str(slide.get("prompt_zh") or slide.get("prompt_en") or "")
        prompt_sidecar = sidecar_dir / f"{sid}.imagegen_prompt.md"
        metadata_sidecar = sidecar_dir / f"{sid}.image_generation_metadata.json"
        write_text(prompt_sidecar, f"# ImageGen Prompt — {sid}\n\n{prompt_text}\n")
        write_json(metadata_sidecar, {
            "schema_version": "image-generation-metadata-v1",
            "slide_id": sid,
            "model": "gpt-image-2",
            "prompt_file": str(prompt_sidecar),
            "input_assets": slide.get("source_assets", []),
            "generated_at": imagegen_manifest.get("generated_at"),
            "human_modified": False,
            "visual_review": "pending",
            "route": "fullpage_imagegen_reconstruct",
        })
        shutil.copy2(prompt_sidecar, final_sidecar_dir / prompt_sidecar.name)
        shutil.copy2(metadata_sidecar, final_sidecar_dir / metadata_sidecar.name)
        for record in imagegen_manifest.get("slides", []):
            if str(record.get("slide_id")) == sid:
                record["fullpage_image"] = record.get("output_path", "")
                record["imagegen_prompt"] = str(prompt_sidecar)
                record["image_generation_metadata"] = str(metadata_sidecar)
                write_json(sidecar_dir / f"{sid}.imagegen_manifest.json", {"schema_version": "imagegen-manifest-v1", "slide": record})
                shutil.copy2(sidecar_dir / f"{sid}.imagegen_manifest.json", final_sidecar_dir / f"{sid}.imagegen_manifest.json")
    metadata_payload = {
        "schema_version": "image-generation-metadata-v1",
        "generated_at": imagegen_manifest.get("generated_at"),
        "route": "fullpage_imagegen_reconstruct",
        "slides": [
            {
                "slide_id": item.get("slide_id"),
                "model": item.get("model"),
                "prompt_sha256": item.get("prompt_sha256"),
                "output_path": item.get("output_path"),
                "output_sha256": item.get("output_sha256"),
                "status": item.get("status"),
                "human_modified": item.get("human_modified", False),
                "visual_review": item.get("visual_review", "pending"),
            }
            for item in imagegen_manifest.get("slides", [])
        ],
    }
    write_json(workspace_dir / "image_generation_metadata.json", metadata_payload)
    write_json(final_ppt_dir / "image_generation_metadata.json", metadata_payload)
    write_json(workspace_dir / "imagegen_manifest.json", imagegen_manifest)
    write_json(final_ppt_dir / "imagegen_manifest.json", imagegen_manifest)
    package["paths"]["imagegen_manifest"] = str(final_ppt_dir / "imagegen_manifest.json")
    reports = run_presentation_gates(
        topic_dir,
        package=package,
        prompts=image_prompts,
        workspace_dir=workspace_dir,
        final_deck=final_deck,
        mock=mock,
    )
    defense_materials = build_defense_materials(topic_dir, package=package, reports=reports)
    write_json(final_ppt_dir / "presentation_run_manifest.json", {
        "schema_version": "presentation-run-v1",
        "generated_at": package.get("source_manifest", {}).get("generated_at"),
        "presentation_profile": presentation_profile,
        "style_profile": effective_style,
        "imagegen_route": profile.get("imagegen_route"),
        "ppt_audit": str(final_ppt_dir / "ppt_audit.json"),
        "validation_dir": str(final_ppt_dir / "validation"),
        "defense_materials": defense_materials,
        "artifacts": package.get("paths", {}),
    })
    workflow_log = final_ppt_dir / "workflow.log"
    workflow_log.write_text(
        "\n".join(
            [
                f"{datetime.now(timezone.utc).isoformat()} route={profile.get('imagegen_route')} profile={presentation_profile} ppt_audit={audit.get('verdict')}",
                f"validation_dir={final_ppt_dir / 'validation'}",
                f"speaker_notes_dir={final_ppt_dir / 'speaker_notes'}",
                "reconstruction_status=planned; render_status=blocked_until_real_render",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        shutil.copy2(workflow_log, topic_dir / "workflow.log")
    except OSError:
        pass
    write_text(
        final_ppt_dir / "ppt_build_report.md",
        "\n".join(
            [
                "# PPT Build Report",
                "",
                f"- Project: {project_name}",
                f"- Mock Mode: {mock}",
                f"- Slide Count: {len(image_prompts.get('slides', []))}",
                f"- Final Deck: `{final_deck}`",
                f"- Audit Verdict: `{audit['verdict']}`",
                "- Adapter Source: `AutoPPT Workflow` ImageGen assembly policy and PPTX builder",
                "",
            ]
        ),
    )
    # Mock pages are generated with local drawing code solely to exercise
    # plumbing. They are never formal output, even if their structural audit
    # passes. Keep the diagnostic artifact but fail closed at the workflow
    # boundary so a script-rendered slide cannot be promoted accidentally.
    status = "completed" if audit["verdict"] == "pass" and not mock else "blocked"
    if mock:
        audit["formal_output_eligible"] = False
        audit.setdefault("issues", []).append("mock_output_is_not_formal_imagegen")
        audit.setdefault("warnings", []).append("code-rendered mock pages are structural diagnostics only")
    update_workspace_state(
        topic_dir,
        status,
        final_deck=final_deck,
        ppt_audit=final_ppt_dir / "ppt_audit.json",
        presentation_profile=presentation_profile,
        imagegen_route=str(profile.get("imagegen_route") or "fullpage_imagegen_reconstruct"),
    )
    return {
        "phase": "ppt",
        "status": status,
        "mock": mock,
        "project_name": project_name,
        "slide_count": len(image_prompts.get("slides", [])),
        "final_workbook": str(final_workbook),
        "imagegen_prompts": str(final_ppt_dir / "imagegen_prompts.json"),
        "images_dir": str(final_ppt_dir / "images"),
        "final_deck": str(final_deck),
        "ppt_audit": str(final_ppt_dir / "ppt_audit.json"),
        "presentation_profile": presentation_profile,
        "validation_dir": str(final_ppt_dir / "validation"),
        "speaker_notes": defense_materials,
        "presentation_reports": reports,
        "audit": audit,
        "formal_output_eligible": bool(status == "completed" and not mock),
        "blocking_reason": "mock_output_is_not_formal_imagegen" if mock else "",
    }


def regenerate_ppt_slide(
    topic_dir: Path,
    slide_id: str,
    *,
    mock: bool = False,
    presentation_profile: str = "innovation_competition_defense",
    style_profile: str | None = None,
    imagegen_route: str | None = None,
) -> dict[str, Any]:
    """Regenerate one slide while preserving the accepted deck and other assets.

    Real mode temporarily narrows the ImageGen assembly prompt pack to the requested
    slide, then restores the original prompt pack even when the backend fails.
    The function never replaces ``final_deck.pptx``; callers can assemble a new
    deck in a later merge/release round after reviewing the changed asset.
    """
    topic_dir = topic_dir.resolve()
    final_ppt_dir = topic_dir / "final" / "ppt"
    workspace_dir = final_ppt_dir / "imagegen_workspace"
    prompts_path = workspace_dir / "image-prompts.json"
    if not prompts_path.exists():
        raise FileNotFoundError(f"missing ImageGen assembly prompt pack: {prompts_path}")
    prompts = read_json(prompts_path)
    slide = next((item for item in prompts.get("slides", []) if str(item.get("slide_id")) == str(slide_id)), None)
    if slide is None:
        raise KeyError(f"unknown slide_id: {slide_id}")
    project_name = load_project_name(topic_dir)
    target = workspace_dir / str(slide.get("final_path") or f"assets/slides/{slide_id}.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    queue = {"mock": mock, "items": [{"slide_id": slide_id, "final_path": str(target), "status": "planned"}]}
    if mock:
        render_mock_slide(target, project_name=project_name, slide=slide)
        queue["items"][0]["status"] = "generated"
    else:
        original = prompts_path.read_text(encoding="utf-8")
        narrowed = dict(prompts)
        narrowed["slides"] = [slide]
        try:
            prompts_path.write_text(json.dumps(narrowed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                prepare_handoff(
                    prompts_path,
                    output=workspace_dir / "single-slide-builtin-imagegen-handoff.json",
                )
            except Exception as exc:  # noqa: BLE001 - preserve exact handoff blocker.
                write_text(
                    workspace_dir / "references" / "single-slide-builtin-imagegen-handoff-prepare-error.txt",
                    f"{exc.__class__.__name__}: {exc}\n",
                )
            issues = preflight_real_imagegen(workspace_dir)
            if issues:
                report = write_builtin_blocker_report(workspace_dir, issues, image_prompts=narrowed)
                raise BuiltinImageGenBlocked(issues, report_path=report)
            run_real_imagegen(workspace_dir)
            if not target.exists():
                raise FileNotFoundError(f"built-in ImageGen output missing after resume: {target}")
            queue["items"][0]["status"] = "generated"
        finally:
            prompts_path.write_text(original, encoding="utf-8")
    final_image = final_ppt_dir / "images" / f"{slide_id}.png"
    final_image.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, final_image)
    manifest = build_imagegen_manifest(
        prompts=prompts,
        workspace_dir=workspace_dir,
        asset_manifest_path=workspace_dir / "references" / "asset-manifest.json",
    )
    for record in manifest.get("slides", []):
        if str(record.get("slide_id")) == str(slide_id):
            record["status"] = "generated"
            record["human_modified"] = False
            record["visual_review"] = "pending"
    write_json(workspace_dir / "imagegen_manifest.json", manifest)
    write_json(final_ppt_dir / "imagegen_manifest.json", manifest)
    partial_manifest = final_ppt_dir / "single_slide_regeneration_manifest.json"
    write_json(partial_manifest, {
        "schema_version": "single-slide-regeneration-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "slide_id": slide_id,
        "presentation_profile": presentation_profile,
        "style_profile": style_profile,
        "imagegen_route": imagegen_route or prompts.get("imagegen_route") or "fullpage_imagegen_reconstruct",
        "image": str(final_image),
        "image_sha256": hashlib.sha256(final_image.read_bytes()).hexdigest(),
        "status": "generated",
        "deck_merge_required": True,
        "accepted_final_deck_preserved": (final_ppt_dir / "final_deck.pptx").exists(),
    })
    return {"status": "generated", "slide_id": slide_id, "image": str(final_image), "manifest": str(partial_manifest), "deck_merge_required": True}
