#!/usr/bin/env python3
"""Validate and register pages produced by Codex built-in ``image_gen``.

Despite the historical filename, this script is not a generator. The host
agent must call the built-in tool and hand its PNG plus ``ig_`` provenance to
the stage directory first. This process only validates and writes assembly
metadata. API keys, provider endpoints, CLIs, local commands, and mocks are
never accepted as formal output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autopptskills.scripts.builtin_imagegen_policy import (  # noqa: E402
    BuiltinImageGenBlocked,
    build_builtin_asset_manifest,
    validate_builtin_imagegen_outputs,
    write_builtin_blocker_report,
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_stage(value: str) -> tuple[Path, Path]:
    path = Path(value).expanduser().resolve()
    if path.is_file():
        return path.parent, path
    return path, path / "image-prompts.json"


def require_builtin_policy(prompt_data: dict[str, Any]) -> None:
    policy = prompt_data.get("prompt_policy") or {}
    required = {
        "output_mode": "direct_final_slide_imagegen",
        "imagegen_required": True,
        "builtin_imagegen_only": True,
        "external_api_key_allowed": False,
        "external_cli_allowed": False,
        "local_command_allowed": False,
        "mock_formal_output_allowed": False,
        "per_slide_imagegen_required": True,
    }
    failures = [f"prompt_policy.{key}={policy.get(key)!r} (expected {value!r})" for key, value in required.items() if policy.get(key) != value]
    if failures:
        raise BuiltinImageGenBlocked(failures)


def update_deck_spec(stage: Path, prompts: dict[str, Any]) -> Path:
    path = stage / "deck-spec.json"
    slides = []
    for slide in prompts.get("slides", []):
        sid = str(slide.get("slide_id") or "")
        slides.append(
            {
                "slide_id": sid,
                "role": slide.get("page_role", ""),
                "layout": "full_slide_image",
                "headline": slide.get("headline", sid),
                "slide_image": slide.get("final_path", f"assets/slides/{sid}.png"),
                "imagegen_prompt_ref": sid,
                "source_refs": slide.get("source_refs", []),
            }
        )
    write_json(
        path,
        {
            "deck": {
                "title": prompts.get("deck_title", "Competition deck"),
                "output_mode": "imagegen_full_slide",
                "generation_mode": "direct_final_slide_imagegen",
                "imagegen_backend": "builtin_image_gen",
                "assembly_only": True,
                "presentation_profile": prompts.get("presentation_profile", ""),
                "imagegen_route": prompts.get("imagegen_route", "fullpage_imagegen_reconstruct"),
            },
            "slides": slides,
        },
    )
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_prompts", help="Path to image-prompts.json or its Stage45 directory.")
    parser.add_argument("--skip-existing", action="store_true", help=argparse.SUPPRESS)
    # Historical generation options are accepted only to produce an explicit
    # refusal, never to route a request to an external backend.
    parser.add_argument("--imagegen-cli", help=argparse.SUPPRESS)
    parser.add_argument("--local-command", help=argparse.SUPPRESS)
    parser.add_argument("--prefer-local", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--model", help=argparse.SUPPRESS)
    parser.add_argument("--size", help=argparse.SUPPRESS)
    parser.add_argument("--quality", help=argparse.SUPPRESS)
    parser.add_argument("--openai-base-url", help=argparse.SUPPRESS)
    parser.add_argument("--per-slide-timeout", type=int, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    forbidden_args = {
        key: value
        for key, value in vars(args).items()
        if key not in {"image_prompts", "skip_existing"} and value not in (None, False, "")
    }
    if forbidden_args:
        raise SystemExit(
            "External ImageGen generation is forbidden. This command only ingests "
            "Codex built-in image_gen outputs; remove legacy options: "
            + ", ".join(sorted(forbidden_args))
        )

    stage, prompt_path = resolve_stage(args.image_prompts)
    if not prompt_path.exists():
        raise SystemExit(f"Missing image prompt pack: {prompt_path}")
    prompts = load_json(prompt_path)
    require_builtin_policy(prompts)
    issues, _records = validate_builtin_imagegen_outputs(stage, prompts)
    if issues:
        report = write_builtin_blocker_report(stage, issues, image_prompts=prompts)
        raise SystemExit(
            "Built-in image_gen handoff is blocked; no alternate backend is permitted. "
            f"Issues: {', '.join(issues)}; blocker_report={report}"
        )
    manifest = build_builtin_asset_manifest(stage, prompts)
    manifest_path = stage / "references" / "asset-manifest.json"
    write_json(manifest_path, manifest)
    deck_spec = update_deck_spec(stage, prompts)
    print(json.dumps({"status": "ready_for_assembly", "backend": "builtin_image_gen", "asset_manifest": str(manifest_path), "deck_spec": str(deck_spec)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuiltinImageGenBlocked as exc:
        print(json.dumps({"status": "blocked", "issues": exc.issues}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
