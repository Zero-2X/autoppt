#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ppt_adapter import run_ppt  # noqa: E402

try:
    from autoppt_workflow.presentation.profiles import presentation_profile_choices
except ImportError:  # pragma: no cover
    presentation_profile_choices = lambda: ("innovation_competition_defense", "thesis_defense", "nsfc_application_defense", "nsfc_conclusion_defense", "academic_paper_report", "research_progress_report")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AutoPPT Workflow PPT/ImageGen adapter.")
    parser.add_argument("topic_dir", help="Topic directory, such as sample/topic_xx")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="Structural smoke only; always blocked from formal delivery.")
    mode.add_argument("--real", action="store_true", help="Consume verified built-in image_gen outputs only.")
    parser.add_argument("--force", action="store_true", help="Rebuild PPT workspace.")
    parser.add_argument(
        "--style-profile",
        default="",
        help="ImageGen visual contract; academic_light is the restrained default.",
    )
    parser.add_argument(
        "--presentation-profile",
        choices=tuple(presentation_profile_choices()),
        default="innovation_competition_defense",
        help="Defense narrative and page contract profile.",
    )
    parser.add_argument(
        "--imagegen-route",
        choices=("fullpage_imagegen_reconstruct", "fullpage_imagegen_native_overlay", "existing_pptx_edit"),
        default="",
        help="Explicit route override; all image generation remains built-in image_gen only.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    mock = bool(args.mock)
    result = run_ppt(
        Path(args.topic_dir),
        mock=mock,
        force=args.force,
        style_profile=args.style_profile or None,
        presentation_profile=args.presentation_profile,
        imagegen_route=args.imagegen_route or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
