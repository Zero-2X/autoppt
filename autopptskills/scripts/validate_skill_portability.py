#!/usr/bin/env python3
"""Reject machine-specific paths and service endpoints from a reusable skill."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".py", ".ps1", ".mjs", ".json"}
DOC_SUFFIXES = {".md", ".yaml", ".yml"}
NUMERIC_HTTP_RE = re.compile(r"https?://(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?", re.IGNORECASE)
WINDOWS_ABSOLUTE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
USER_PROFILE_RE = re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s`'\"<>]+", re.IGNORECASE)
IGNORED_PARTS = {"__pycache__", ".git", "node_modules"}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        yield path


def scan(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in iter_text_files(root):
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(
                {
                    "file": str(path.relative_to(root)),
                    "line": 0,
                    "rule": "unreadable-text-file",
                    "excerpt": str(exc),
                }
            )
            continue
        for line_number, line in enumerate(lines, start=1):
            rules: list[str] = []
            if NUMERIC_HTTP_RE.search(line):
                rules.append("hardcoded-numeric-service-endpoint")
            if USER_PROFILE_RE.search(line):
                rules.append("hardcoded-user-profile")
            if path.suffix.lower() in DOC_SUFFIXES and WINDOWS_ABSOLUTE_RE.search(line):
                rules.append("absolute-windows-path-in-documentation")
            for rule in rules:
                findings.append(
                    {
                        "file": str(path.relative_to(root)),
                        "line": line_number,
                        "rule": rule,
                        "excerpt": line.strip()[:240],
                    }
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "skill_root",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1]),
        help="Skill directory; defaults to the parent of scripts/.",
    )
    parser.add_argument("--json-out", help="Optional machine-readable report path.")
    args = parser.parse_args()

    root = Path(args.skill_root).expanduser().resolve()
    findings = scan(root) if root.exists() else []
    errors = [] if root.exists() else [f"skill root does not exist: {root}"]
    verdict = "pass" if not findings and not errors else "fail"
    report = {
        "policy": "portable-codex-skill-v1",
        "skill_root": str(root),
        "files_scanned": sum(1 for _ in iter_text_files(root)) if root.exists() else 0,
        "findings": findings,
        "errors": errors,
        "verdict": verdict,
    }
    if args.json_out:
        write_json(Path(args.json_out).expanduser().resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if verdict == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
