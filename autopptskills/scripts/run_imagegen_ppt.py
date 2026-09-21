#!/usr/bin/env python3
"""Assemble and gate a deck after a Codex built-in ImageGen handoff.

This wrapper never invokes an ImageGen API or CLI. Generation happens only through the Codex host's
built-in ``image_gen`` tool; this wrapper validates the handoff, assembles the
image-only PPTX, and runs structural provenance checks.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(str(part) for part in cmd))
    subprocess.run(cmd, check=True)


def resolve_workspace(value: str) -> tuple[Path, Path]:
    path = Path(value).expanduser().resolve()
    if path.is_file():
        return path.parent, path
    return path, path / "image-prompts.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace")
    parser.add_argument("--output")
    parser.add_argument("--report")
    parser.add_argument("--gate-report")
    # Old generator flags remain parseable only so callers get a clear policy
    # error rather than accidentally invoking a provider.
    parser.add_argument("--imagegen-cli", help=argparse.SUPPRESS)
    parser.add_argument("--model", help=argparse.SUPPRESS)
    parser.add_argument("--size", help=argparse.SUPPRESS)
    parser.add_argument("--quality", help=argparse.SUPPRESS)
    parser.add_argument("--openai-base-url", help=argparse.SUPPRESS)
    parser.add_argument("--skip-existing", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--per-slide-timeout", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    forbidden = {key: value for key, value in vars(args).items() if key not in {"workspace", "output", "report", "gate_report"} and value not in (None, False, "")}
    if forbidden:
        raise SystemExit("External ImageGen generation is forbidden; this wrapper only ingests Codex built-in image_gen outputs. Remove: " + ", ".join(sorted(forbidden)))

    workspace, prompt_path = resolve_workspace(args.workspace)
    if not prompt_path.exists():
        raise SystemExit(f"Missing image prompt pack: {prompt_path}")
    output = Path(args.output).expanduser().resolve() if args.output else workspace / "pptx" / "output" / f"{workspace.name}.pptx"
    report = Path(args.report).expanduser().resolve() if args.report else output.with_name("build-report.json")
    gate_report = Path(args.gate_report).expanduser().resolve() if args.gate_report else output.with_name("imagegen-first-gate-report.json")

    run([sys.executable, str(SCRIPT_DIR / "register_imagegen_outputs.py"), str(prompt_path)])
    run([sys.executable, str(SCRIPT_DIR / "build_image_deck.py"), str(workspace / "deck-spec.json"), "--output", str(output), "--report", str(report)])
    run([sys.executable, str(SCRIPT_DIR / "verify_imagegen_first_gate.py"), str(workspace), "--pptx", str(output), "--require-strong-ig-id", "--report", str(gate_report)])
    print(f"\nDone: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
