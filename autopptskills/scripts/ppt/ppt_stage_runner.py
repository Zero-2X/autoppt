#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from stage45_adapter import run_ppt  # noqa: E402
    from style_contracts import style_profile_choices  # noqa: E402
else:
    from .stage45_adapter import run_ppt
    from ..style_contracts import style_profile_choices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AutoSearch PPT PPT/imagegen adapter.")
    parser.add_argument("topic_dir", help="Topic directory, such as sample/topic_xx")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="Structural smoke only; never a formal deliverable.")
    mode.add_argument("--real", action="store_true", help="Consume verified built-in image_gen outputs only.")
    parser.add_argument("--force", action="store_true", help="Rebuild PPT workspace.")
    parser.add_argument(
        "--style-profile",
        choices=style_profile_choices(),
        default="academic_light",
        help="Restrained ImageGen visual contract; academic_light is the general default.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    mock = bool(args.mock)
    result = run_ppt(Path(args.topic_dir), mock=mock, force=args.force, style_profile=args.style_profile)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
