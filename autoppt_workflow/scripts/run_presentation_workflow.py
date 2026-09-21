#!/usr/bin/env python3
"""Run or resume the profile-aware PPT presentation workflow.

This CLI coordinates content planning, verified ImageGen handoffs, PPTX
assembly, and presentation quality checks through the presentation adapter.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autoppt_workflow.presentation.orchestrator import build_defense_materials, prepare_presentation_package, run_presentation_gates
from autoppt_workflow.presentation.profiles import get_presentation_profile, presentation_profile_choices
from autoppt_workflow.ppt.ppt_adapter import regenerate_ppt_slide, run_ppt


def _quality_pptx(topic_dir: Path, explicit: str = "", result: dict | None = None) -> Path | None:
    """Resolve the exact PPTX to iterate without guessing across old rounds."""
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.exists() else None
    for key in ("delivery_pptx", "final_pptx", "pptx", "output_pptx"):
        value = (result or {}).get(key)
        if value:
            path = Path(str(value)).expanduser().resolve()
            if path.exists():
                return path
    delivery = topic_dir / "final" / "ppt" / "delivery"
    candidates = sorted(delivery.glob("*.pptx"), key=lambda item: item.stat().st_mtime, reverse=True) if delivery.exists() else []
    return candidates[0] if candidates else None


def _run_quality_iteration(topic_dir: Path, args: argparse.Namespace, *, result: dict | None = None) -> dict:
    pptx = _quality_pptx(topic_dir, args.quality_pptx, result)
    if pptx is None:
        return {"status": "blocked", "error": "quality iteration PPTX could not be resolved"}
    command = [
        sys.executable,
        str(ROOT / "autoppt_workflow" / "scripts" / "iterate_presentation_quality.py"),
        "--pptx",
        str(pptx),
        "--max-iterations",
        str(args.quality_max_iterations),
    ]
    if args.quality_auto_repair:
        command.append("--auto-repair")
    if args.quality_repair_plan:
        command.extend(["--repair-plan", str(Path(args.quality_repair_plan).expanduser().resolve())])
    if args.quality_promote_to:
        command.extend(["--promote-accepted-to", str(Path(args.quality_promote_to).expanduser().resolve())])
    import subprocess

    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {"status": "completed" if completed.returncode == 0 else "blocked", "command": command, "returncode": completed.returncode, "stdout": completed.stdout or "", "stderr": completed.stderr or "", "pptx": str(pptx)}


def _record_learning(topic_dir: Path) -> dict:
    """Persist this run's failures, warnings and reusable PPT lessons."""
    recorder = ROOT / "scripts" / "update_ppt_knowledge.py"
    if not recorder.exists():
        return {"status": "blocked", "error": f"missing recorder: {recorder}"}
    import subprocess

    completed = subprocess.run(
        [sys.executable, str(recorder), str(topic_dir)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    payload = {"status": "completed" if completed.returncode == 0 else "blocked", "returncode": completed.returncode}
    if completed.stdout:
        try:
            payload["record"] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload["stdout"] = completed.stdout[-4000:]
    if completed.stderr:
        payload["stderr"] = completed.stderr[-4000:]
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile-aware ImageGen-first presentation workflow.")
    parser.add_argument("topic_dir")
    parser.add_argument("--presentation-profile", choices=tuple(presentation_profile_choices()), default="innovation_competition_defense")
    parser.add_argument("--style-profile", default="", help="Optional autopptskills style profile override.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", help="Structural smoke only; always blocked from formal delivery.")
    mode.add_argument("--real", action="store_true", help="Consume verified Codex built-in image_gen outputs only.")
    parser.add_argument("--force", action="store_true", help="Rebuild the ImageGen assembly workspace.")
    parser.add_argument("--slide-id", default="", help="Regenerate only this slide asset and preserve the accepted deck.")
    parser.add_argument("--speaker-only", action="store_true", help="Generate speaker notes/questions from the current Slide IR without regenerating images.")
    parser.add_argument("--audit-only", action="store_true", help="Run the seven presentation gates against existing artifacts without generating images.")
    parser.add_argument("--imagegen-route", choices=("fullpage_imagegen_reconstruct", "fullpage_imagegen_native_overlay", "existing_pptx_edit"), default="", help="Explicit route override; image generation remains built-in image_gen only.")
    parser.add_argument("--iterate-quality", action="store_true", help="Run the persistent inspect-repair-reinspect quality loop after this workflow action.")
    parser.add_argument("--quality-pptx", default="", help="Exact PPTX to pass to the quality iterator; otherwise resolve the newest delivery PPTX.")
    parser.add_argument("--quality-max-iterations", type=int, default=3)
    parser.add_argument("--quality-auto-repair", action="store_true", help="Enable conservative local JSON repairs in the quality iterator.")
    parser.add_argument("--quality-repair-plan", default="", help="Optional reviewed JSON repair plan consumed by the quality iterator.")
    parser.add_argument("--quality-promote-to", default="", help="Optional new PPTX path for an accepted candidate; the original delivery is never overwritten.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    topic_dir = Path(args.topic_dir).expanduser().resolve()
    if not topic_dir.exists():
        raise SystemExit(f"topic directory not found: {topic_dir}")
    profile = get_presentation_profile(args.presentation_profile)
    if args.speaker_only:
        package = prepare_presentation_package(
            topic_dir,
            profile_name=args.presentation_profile,
            evidence_paths=[
                topic_dir / "workspace" / "evidence_workspace" / "evidence-ledger.json",
                topic_dir / "workspace" / "research" / "evidence-ledger.json",
            ],
        )
        materials = build_defense_materials(topic_dir, package=package, reports={})
        print(json.dumps({"status": "completed", "presentation_profile": profile["profile_id"], "speaker_materials": materials}, ensure_ascii=False, indent=2))
        return 0
    if args.audit_only:
        package = prepare_presentation_package(
            topic_dir,
            profile_name=args.presentation_profile,
            evidence_paths=[
                topic_dir / "workspace" / "evidence_workspace" / "evidence-ledger.json",
                topic_dir / "workspace" / "research" / "evidence-ledger.json",
            ],
            imagegen_route=args.imagegen_route or None,
        )
        prompts_path = topic_dir / "final" / "ppt" / "imagegen_prompts.json"
        prompts = json.loads(prompts_path.read_text(encoding="utf-8-sig")) if prompts_path.exists() else None
        audit_path = topic_dir / "final" / "ppt" / "ppt_audit.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8-sig")) if audit_path.exists() else {}
        reports = run_presentation_gates(
            topic_dir,
            package=package,
            prompts=prompts,
            workspace_dir=topic_dir / "final" / "ppt" / "imagegen_workspace",
            final_deck=topic_dir / "final" / "ppt" / "final_deck.pptx",
            mock=bool(audit.get("mock_mode", False)),
        )
        payload = {"status": "completed", "presentation_profile": profile["profile_id"], "reports": reports}
        if args.iterate_quality:
            payload["quality_iteration"] = _run_quality_iteration(topic_dir, args, result={"pptx": str(topic_dir / "final" / "ppt" / "final_deck.pptx")})
        payload["continuous_improvement"] = _record_learning(topic_dir)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if all(report.get("verdict") == "pass" for report in reports.values()) else 2
    if not args.mock and not args.real:
        raise SystemExit("Choose exactly one generation mode: --real (built-in image_gen only) or --mock (structural smoke only).")
    if args.slide_id:
        result = regenerate_ppt_slide(
            topic_dir,
            args.slide_id,
            mock=not args.real,
            presentation_profile=args.presentation_profile,
            style_profile=args.style_profile or None,
            imagegen_route=args.imagegen_route or None,
        )
    else:
        result = run_ppt(
            topic_dir,
            mock=not args.real,
            force=args.force,
            style_profile=args.style_profile or None,
            presentation_profile=args.presentation_profile,
            imagegen_route=args.imagegen_route or None,
        )
    if args.iterate_quality:
        result = {**result, "quality_iteration": _run_quality_iteration(topic_dir, args, result=result)}
    result = {**result, "continuous_improvement": _record_learning(topic_dir)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    quality_status = (result.get("quality_iteration") or {}).get("status")
    return 0 if (result.get("status") == "completed" or result.get("status") == "generated") and quality_status != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
