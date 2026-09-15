#!/usr/bin/env python3
"""Check the Codex built-in ImageGen handoff without generating anything.

This command is intentionally an artifact/provenance checker. The Codex host
invokes the built-in ``image_gen`` tool; repository Python code only ingests,
verifies, and assembles its results. There is no API, CLI, proxy, or local
image-generation fallback here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .builtin_imagegen_policy import validate_builtin_imagegen_outputs, write_builtin_blocker_report
except ImportError:  # pragma: no cover - direct script execution
    SCRIPT_DIR = Path(__file__).resolve().parent
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from builtin_imagegen_policy import validate_builtin_imagegen_outputs, write_builtin_blocker_report


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", help="Stage45 workspace containing image-prompts.json.")
    parser.add_argument("--handoff", help="builtin-imagegen-handoff.json to verify.")
    parser.add_argument("--report", help="Machine-readable JSON report path.")
    # Retain old flags only to fail loudly instead of silently taking the old
    # provider path. They never invoke generation.
    parser.add_argument("--smoke", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-out", help=argparse.SUPPRESS)
    parser.add_argument("--imagegen-cli", help=argparse.SUPPRESS)
    parser.add_argument("--openai-base-url", help=argparse.SUPPRESS)
    parser.add_argument("--model", help=argparse.SUPPRESS)
    parser.add_argument("--size", help=argparse.SUPPRESS)
    parser.add_argument("--quality", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=int, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    legacy_flags = any(
        value is not None and value is not False
        for value in (
            args.smoke,
            args.smoke_out,
            args.imagegen_cli,
            args.openai_base_url,
            args.model,
            args.size,
            args.quality,
            args.timeout,
        )
    )
    stage = Path(args.stage).expanduser().resolve() if args.stage else None
    handoff = Path(args.handoff).expanduser().resolve() if args.handoff else None
    if handoff and not stage:
        stage = handoff.parent

    issues: list[str] = []
    report_payload: dict[str, object] = {
        "schema_version": "builtin-imagegen-backend-check-v1",
        "backend": "builtin_image_gen",
        "status": "blocked",
        "ready": False,
        "generation_attempted": False,
        # Existing shell keys may be used by unrelated LLM tasks.  They are
        # intentionally ignored here because this checker never reads or
        # forwards them to an image backend.
        "external_configuration_ignored": True,
        "issues": issues,
    }
    if legacy_flags:
        issues.append("legacy_api_or_cli_arguments_are_forbidden")
    if stage is None:
        issues.append("builtin_imagegen_stage_missing")
    elif not stage.exists():
        issues.append(f"builtin_imagegen_stage_missing:{stage}")
    else:
        prompt_path = stage / "image-prompts.json"
        prompts = load_json(prompt_path) if prompt_path.exists() else None
        validation_issues, records = validate_builtin_imagegen_outputs(stage, prompts)
        issues.extend(validation_issues)
        report_payload["stage"] = str(stage)
        report_payload["slides_verified"] = len(records)
        if handoff:
            report_payload["handoff"] = str(handoff)
            if not handoff.exists():
                issues.append("builtin_imagegen_handoff_missing")
            else:
                try:
                    handoff_payload = load_json(handoff)
                    if handoff_payload.get("status") != "completed":
                        issues.append("builtin_imagegen_handoff_not_completed")
                except (OSError, json.JSONDecodeError):
                    issues.append("builtin_imagegen_handoff_invalid")

    if not issues:
        report_payload["status"] = "ready"
        report_payload["ready"] = True
        report_payload["next_action"] = "Assemble the verified built-in ImageGen pages; no generation is performed by this command."
    else:
        report_payload["next_action"] = "Retry or repair the Codex built-in image_gen handoff; do not use API, CLI, proxy, local command, or mock."
        if stage and stage.exists():
            try:
                blocker = write_builtin_blocker_report(stage, issues, image_prompts=load_json(stage / "image-prompts.json"))
                report_payload["blocker_report"] = str(blocker)
            except (OSError, json.JSONDecodeError):
                pass

    if args.report:
        write_json(Path(args.report).expanduser().resolve(), report_payload)
    print(json.dumps(report_payload, ensure_ascii=False, indent=2))
    return 0 if report_payload["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
