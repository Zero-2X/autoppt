#!/usr/bin/env python3
"""Extract a built-in ImageGen result from a Codex rollout JSONL file."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def find_rollout(sessions_root: Path, thread_id: str) -> Path:
    matches = []
    for path in sessions_root.rglob("*.jsonl"):
        if thread_id in path.name:
            matches.append(path)
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                if any(thread_id in line for _, line in zip(range(64), handle)):
                    matches.append(path)
        except OSError:
            continue
    if not matches:
        raise FileNotFoundError(f"No rollout JSONL found for thread {thread_id}")
    return max(matches, key=lambda item: item.stat().st_mtime_ns)


def imagegen_records(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = event.get("payload", {})
            if payload.get("type") != "image_generation_call" or not payload.get("result"):
                continue
            records.append(
                {
                    "timestamp": event.get("timestamp"),
                    "line_number": line_number,
                    "id": payload.get("id"),
                    "status": payload.get("status"),
                    "revised_prompt": payload.get("revised_prompt", ""),
                    "result": payload["result"],
                }
            )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="Destination PNG path")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--session-jsonl")
    source.add_argument("--thread-id")
    parser.add_argument(
        "--sessions-root",
        default=str(Path.home() / ".codex" / "sessions"),
        help="Codex sessions root used with --thread-id",
    )
    parser.add_argument("--index", type=int, default=-1, help="ImageGen record index; default latest")
    parser.add_argument("--metadata-out", help="Optional provenance JSON path")
    args = parser.parse_args()

    session_path = (
        Path(args.session_jsonl)
        if args.session_jsonl
        else find_rollout(Path(args.sessions_root), args.thread_id)
    )
    records = imagegen_records(session_path)
    if not records:
        raise RuntimeError(f"No completed ImageGen result found in {session_path}")
    try:
        record = records[args.index]
    except IndexError as exc:
        raise IndexError(f"ImageGen index {args.index} outside 0..{len(records) - 1}") from exc

    image_bytes = base64.b64decode(record.pop("result"), validate=True)
    if not image_bytes.startswith(PNG_SIGNATURE):
        raise ValueError("ImageGen result is not a PNG payload")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)

    metadata = {
        **record,
        "backend": "builtin_image_gen",
        "provenance_kind": "builtin-imagegen",
        "generation_mode": "direct_final_slide_imagegen",
        "status": "generated",
        "session_jsonl": str(session_path.resolve()),
        "record_index": args.index if args.index >= 0 else len(records) + args.index,
        "record_count": len(records),
        "output": str(output_path.resolve()),
        "bytes": len(image_bytes),
        "sha256": hashlib.sha256(image_bytes).hexdigest(),
    }
    if args.metadata_out:
        metadata_path = Path(args.metadata_out)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
