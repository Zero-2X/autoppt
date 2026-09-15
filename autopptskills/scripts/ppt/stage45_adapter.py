from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

try:
    from .image_prompt_builder import build_image_prompts, write_json, write_prompt_pack
    from .imagegen_queue_builder import build_generation_queue
    from .pptx_builder import build_deck_spec, build_pptx_with_stage45_builder
    from .slide_auditor import audit_ppt, write_json as write_audit_json
    from ..builtin_imagegen_policy import (
        BuiltinImageGenBlocked,
        build_builtin_asset_manifest,
        validate_builtin_imagegen_outputs,
        write_builtin_blocker_report,
    )
    _repo_root = Path(__file__).resolve().parents[3]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from autosearch.ppt.builtin_imagegen_handoff import prepare_handoff
except ImportError:  # pragma: no cover - supports direct script execution.
    from image_prompt_builder import build_image_prompts, write_json, write_prompt_pack
    from imagegen_queue_builder import build_generation_queue
    from pptx_builder import build_deck_spec, build_pptx_with_stage45_builder
    from slide_auditor import audit_ppt, write_json as write_audit_json
    _repo_root = Path(__file__).resolve().parents[3]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from autopptskills.scripts.builtin_imagegen_policy import (
        BuiltinImageGenBlocked,
        build_builtin_asset_manifest,
        validate_builtin_imagegen_outputs,
        write_builtin_blocker_report,
    )
    try:
        from autosearch.ppt.builtin_imagegen_handoff import prepare_handoff
    except ImportError:
        prepare_handoff = None


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def preflight_real_imagegen(stage45_dir: Path) -> list[str]:
    """Validate only PNGs and provenance from the built-in Codex image_gen tool."""
    prompt_path = Path(stage45_dir) / "image-prompts.json"
    prompts = read_json(prompt_path) if prompt_path.exists() else None
    issues, _records = validate_builtin_imagegen_outputs(Path(stage45_dir), prompts)
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


def update_workspace_state(topic_dir: Path, status: str, *, final_deck: Path, ppt_audit: Path) -> None:
    state_path = topic_dir / "workspace" / "state" / "workspace-state.json"
    if not state_path.exists():
        return
    state = read_json(state_path)
    state["current_stage"] = "ppt"
    state["current_stage_status"] = status
    state.setdefault("stage_status", {})["ppt"] = status
    state["active_focus"] = "PPT PPT/imagegen handoff complete" if status == "completed" else "PPT PPT/imagegen blocked"
    state["current_direction"] = "competition deck generated through Stage4.5 adapter"
    state["next_action"] = "pipeline_complete" if status == "completed" else "fix_ppt"
    state["next_actions"] = [state["next_action"]]
    state["resume_entrypoint"] = "final/ppt/ppt_audit.json"
    state["last_completed_artifact"] = "final/ppt/final_deck.pptx" if status == "completed" else "final/ppt/ppt_audit.json"
    state["required_inputs"] = [] if status == "completed" else ["inspect final/ppt/ppt_audit.json"]
    state["blocking_reason"] = "" if status == "completed" else "PPT PPT audit failed."
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
                "# PPT PPT Build Report",
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
        "stage": "ppt",
        "status": "blocked",
        "mock": False,
        "project_name": project_name,
        "slide_count": len(image_prompts.get("slides", [])),
        "final_workbook": str(topic_dir / "final" / "final_workbook.md"),
        "imagegen_prompts": str(final_ppt_dir / "imagegen_prompts.json"),
        "images_dir": str(final_ppt_dir / "images"),
        "final_deck": str(final_deck),
        "ppt_audit": str(final_ppt_dir / "ppt_audit.json"),
        "audit": audit,
    }


def find_one(paths: list[Path], description: str) -> Path:
    for path in paths:
        if path.exists():
            return path
    raise FileNotFoundError(f"Missing {description}: " + ", ".join(str(path) for path in paths))


def find_final_workbook(topic_dir: Path) -> Path:
    stage8 = topic_dir / "workspace" / "stage8_handoff"
    candidates = sorted(stage8.glob("作品书_*_定稿.md"))
    if candidates:
        return candidates[0]
    output_candidates = sorted((topic_dir / "output").glob("作品书_*_定稿.md"))
    if output_candidates:
        return output_candidates[0]
    return find_one([stage8 / "作品书_定稿.md"], "final workbook markdown")


def load_project_name(topic_dir: Path) -> str:
    card_path = topic_dir / "workspace" / "stage4_idea_brief" / "idea-card.json"
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


def copy_ppt_outputs(stage45_dir: Path, final_ppt_dir: Path, image_prompts: dict[str, Any]) -> None:
    image_dir = final_ppt_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for slide in image_prompts.get("slides", []):
        slide_id = slide.get("slide_id")
        src = stage45_dir / slide.get("final_path", f"assets/slides/{slide_id}.png")
        dst = image_dir / f"{slide_id}.png"
        if src.exists():
            shutil.copy2(src, dst)


def run_real_stage45_imagegen(stage45_dir: Path) -> None:
    """Assemble from verified built-in ImageGen outputs; never invoke a backend."""
    stage45_dir = Path(stage45_dir).resolve()
    prompt_path = stage45_dir / "image-prompts.json"
    prompts = read_json(prompt_path) if prompt_path.exists() else None
    issues, _records = validate_builtin_imagegen_outputs(stage45_dir, prompts)
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
        report = write_builtin_blocker_report(stage45_dir, issues, image_prompts=prompts)
        raise BuiltinImageGenBlocked(issues, report_path=report)

    build_deck_spec(stage45_dir, prompts or {})
    manifest = build_builtin_asset_manifest(stage45_dir, prompts)
    write_json(stage45_dir / "references" / "asset-manifest.json", manifest)
    output_path = stage45_dir / "pptx" / "output" / "ppt_competition_deck.pptx"
    report_path = stage45_dir / "pptx" / "output" / "build-report.json"
    build_pptx_with_stage45_builder(stage45_dir, output_path, report_path)


def run_ppt(topic_dir: Path, *, mock: bool = True, force: bool = False, style_profile: str = "academic_light") -> dict[str, Any]:
    topic_dir = topic_dir.resolve()
    final_dir = topic_dir / "final"
    final_ppt_dir = final_dir / "ppt"
    stage45_dir = final_ppt_dir / "stage45_workspace"
    source_dir = stage45_dir / "source-materials"
    refs_dir = stage45_dir / "references"
    slides_dir = stage45_dir / "assets" / "slides"
    output_dir = stage45_dir / "pptx" / "output"

    project_name = load_project_name(topic_dir)
    workbook_path = find_final_workbook(topic_dir)
    slide_brief_path = find_one(
        [
            topic_dir / "workspace" / "stage8_handoff" / "slide_brief.json",
            topic_dir / "handoff" / "slide_brief.json",
        ],
        "slide_brief.json",
    )
    ppt_outline_path = find_one(
        [
            topic_dir / "workspace" / "stage8_handoff" / "ppt_outline.md",
            topic_dir / "handoff" / "ppt_outline.md",
        ],
        "ppt_outline.md",
    )
    evidence_path = find_one(
        [topic_dir / "workspace" / "stage2_idea_generation" / "evidence-ledger.json"],
        "evidence-ledger.json",
    )
    research_evidence_path = topic_dir / "workspace" / "research" / "evidence-ledger.json"

    if force and stage45_dir.exists():
        shutil.rmtree(stage45_dir)
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

    visual_manifest = topic_dir / "workspace" / "stage8_handoff" / "visual-manifest.json"
    if visual_manifest.exists():
        shutil.copy2(visual_manifest, source_dir / "visual-manifest.json")

    slide_brief = read_json(slide_brief_path)
    evidence_ledgers = [read_json(evidence_path)]
    if research_evidence_path.exists():
        evidence_ledgers.append(read_json(research_evidence_path))
    image_prompts = build_image_prompts(
        project_name=project_name,
        slide_brief=slide_brief,
        evidence_ledgers=evidence_ledgers,
        style_profile=style_profile,
    )
    write_json(stage45_dir / "image-prompts.json", image_prompts)
    write_json(final_ppt_dir / "imagegen_prompts.json", image_prompts)
    write_prompt_pack(refs_dir / "imagegen-prompt-pack.md", image_prompts)
    if not mock and prepare_handoff is not None:
        handoff_path = stage45_dir / "builtin-imagegen-handoff.json"
        if not handoff_path.exists():
            try:
                prepare_handoff(stage45_dir / "image-prompts.json", output=handoff_path)
            except Exception as exc:  # noqa: BLE001 - preserve a diagnosable blocker.
                write_text(refs_dir / "builtin-imagegen-handoff-prepare-error.txt", f"{exc.__class__.__name__}: {exc}\n")

    queue = build_generation_queue(stage45_dir, image_prompts, mock=mock)
    if mock:
        for item in queue:
            slide = next(s for s in image_prompts["slides"] if s["slide_id"] == item["slide_id"])
            render_mock_slide(Path(item["final_path"]), project_name=project_name, slide=slide)
            item["status"] = "generated"
        write_json(stage45_dir / "imagegen-queue.json", {"mock": mock, "items": queue})
        build_deck_spec(stage45_dir, image_prompts)
        stage45_pptx = output_dir / "ppt_competition_deck.pptx"
        stage45_report = output_dir / "build-report.json"
        build_pptx_with_stage45_builder(stage45_dir, stage45_pptx, stage45_report)
    else:
        write_json(stage45_dir / "imagegen-queue.json", {"mock": mock, "items": queue})
        build_deck_spec(stage45_dir, image_prompts)
        preflight_issues = preflight_real_imagegen(stage45_dir)
        if preflight_issues:
            blocker_report = write_builtin_blocker_report(stage45_dir, preflight_issues, image_prompts=image_prompts)
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
            run_real_stage45_imagegen(stage45_dir)
        except BuiltinImageGenBlocked as exc:
            return write_ppt_failure(
                topic_dir=topic_dir,
                final_ppt_dir=final_ppt_dir,
                image_prompts=image_prompts,
                project_name=project_name,
                reason="builtin_imagegen_required",
                details=[*exc.issues, f"blocker_report={exc.report_path}"],
                existing_final_deck=final_ppt_dir / "final_deck.pptx",
            )
        stage45_pptx = output_dir / "ppt_competition_deck.pptx"
    final_deck = final_ppt_dir / "final_deck.pptx"
    shutil.copy2(stage45_pptx, final_deck)
    copy_ppt_outputs(stage45_dir, final_ppt_dir, image_prompts)

    audit = audit_ppt(
        image_prompts=image_prompts,
        image_dir=final_ppt_dir / "images",
        pptx_path=final_deck,
        mock=mock,
        asset_manifest_path=stage45_dir / "references" / "asset-manifest.json",
    )
    write_audit_json(final_ppt_dir / "ppt_audit.json", audit)
    write_text(
        final_ppt_dir / "ppt_build_report.md",
        "\n".join(
            [
                "# PPT PPT Build Report",
                "",
                f"- Project: {project_name}",
                f"- Mock Mode: {mock}",
                f"- Slide Count: {len(image_prompts.get('slides', []))}",
                f"- Final Deck: `{final_deck}`",
                f"- Audit Verdict: `{audit['verdict']}`",
                "- Adapter Source: `research-workflow-pipeline` Stage4.5 policy and PPTX builder",
                "",
            ]
        ),
    )
    status = "completed" if audit["verdict"] == "pass" else "blocked"
    update_workspace_state(topic_dir, status, final_deck=final_deck, ppt_audit=final_ppt_dir / "ppt_audit.json")
    return {
        "stage": "ppt",
        "status": status,
        "mock": mock,
        "project_name": project_name,
        "slide_count": len(image_prompts.get("slides", [])),
        "final_workbook": str(final_workbook),
        "imagegen_prompts": str(final_ppt_dir / "imagegen_prompts.json"),
        "images_dir": str(final_ppt_dir / "images"),
        "final_deck": str(final_deck),
        "ppt_audit": str(final_ppt_dir / "ppt_audit.json"),
        "audit": audit,
    }
