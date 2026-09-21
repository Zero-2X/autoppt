"""Bridge the repository workflow to Codex's built-in ``image_gen`` tool.

The repository cannot invoke the built-in tool from a Python subprocess.  This
module therefore implements the safe boundary between the two sides:

* ``prepare`` writes a prompt queue and an explicit built-in-only contract;
* the Codex agent calls ``image_gen`` once for each pending slide;
* ``ingest`` reads the completed ``image_generation_call`` record from the
  current Codex rollout JSONL, materialises its PNG, and writes provenance;
* ``verify`` blocks until every slide has a matching ``ig_`` record.

There is intentionally no API client, CLI invocation, local-provider command,
or API-key lookup in this file.  A blocked built-in call must be retried or
reported as blocked; it must never be silently routed through another backend.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .builtin_imagegen_policy import (
        DIRECT_FINAL_GENERATION_MODE,
        validate_builtin_imagegen_outputs,
    )
except ImportError:  # pragma: no cover - direct script execution
    from builtin_imagegen_policy import (  # type: ignore
        DIRECT_FINAL_GENERATION_MODE,
        validate_builtin_imagegen_outputs,
    )


SCHEMA_VERSION = "builtin-imagegen-handoff-v1"
PROVENANCE_SCHEMA_VERSION = "builtin-imagegen-provenance-v1"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

BUILTIN_ONLY_POLICY: dict[str, Any] = {
    "backend": "builtin_image_gen",
    "builtin_imagegen_only": True,
    "auto_invoke_builtin_imagegen": True,
    "external_api_key_allowed": False,
    "external_cli_allowed": False,
    "local_command_allowed": False,
    "mock_formal_output_allowed": False,
    "fallback_allowed": False,
    "one_call_per_slide": True,
    "on_block": "retry_builtin_or_stop",
}

# These fields must be present in ``image-prompts.json`` as well as the handoff
# manifest.  Keeping the bridge contract in both artifacts prevents a stale or
# hand-edited prompt pack from silently relaxing the built-in-only rule.
REQUIRED_PROMPT_POLICY: dict[str, Any] = {
    "backend": "builtin_image_gen",
    "builtin_imagegen_only": True,
    "external_api_key_allowed": False,
    "external_cli_allowed": False,
    "local_command_allowed": False,
    "mock_formal_output_allowed": False,
    "fallback_allowed": False,
    "one_call_per_slide": True,
    "on_block": "retry_builtin_or_stop",
}


class BuiltinImageGenHandoffBlocked(RuntimeError):
    """Raised when the built-in handoff cannot be completed safely."""

    def __init__(self, issues: Iterable[str], *, report_path: Path | None = None) -> None:
        self.issues = list(issues)
        self.report_path = report_path
        message = "; ".join(self.issues) or "builtin_imagegen_handoff_blocked"
        if report_path:
            message += f"; blocker_report={report_path}"
        super().__init__(message)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _prompt_text(slide: dict[str, Any]) -> str:
    value = slide.get("prompt_zh") or slide.get("prompt_en") or slide.get("prompt")
    if not str(value or "").strip():
        raise BuiltinImageGenHandoffBlocked([f"missing_prompt:{slide.get('slide_id', '')}"])
    return str(value).strip()


def _validate_prompt_policy(prompt_data: dict[str, Any]) -> list[str]:
    policy = prompt_data.get("prompt_policy")
    if not isinstance(policy, dict):
        return ["builtin_imagegen_prompt_policy_missing"]
    issues: list[str] = []
    for key, expected in REQUIRED_PROMPT_POLICY.items():
        if policy.get(key) != expected:
            issues.append(f"prompt_policy.{key}_must_be_{expected!r}")
    if policy.get("output_mode") != DIRECT_FINAL_GENERATION_MODE:
        issues.append("prompt_policy.output_mode_must_be_direct_final_slide_imagegen")
    if policy.get("imagegen_required") is not True:
        issues.append("prompt_policy.imagegen_required_must_be_true")
    if policy.get("per_slide_imagegen_required") is not True:
        issues.append("prompt_policy.per_slide_imagegen_required_must_be_true")
    return issues


def _find_rollout(sessions_root: Path, thread_id: str) -> Path | None:
    if not thread_id or not sessions_root.exists():
        return None
    # Rollout filenames normally end with the thread id.  Prefer that cheap
    # lookup; scanning multi-hundred-megabyte JSONL histories is both slow and
    # unnecessary for the normal Codex session.
    named = [path for path in sessions_root.rglob("*.jsonl") if thread_id in path.name]
    if named:
        return max(named, key=lambda item: item.stat().st_mtime_ns)
    # Older sessions may not encode the id in the filename.  Inspect only a
    # short prefix in that case, matching the extractor's bounded lookup.
    matches: list[Path] = []
    for path in sessions_root.rglob("*.jsonl"):
        try:
            with path.open("r", encoding="utf-8") as handle:
                for _ in range(64):
                    line = handle.readline()
                    if not line:
                        break
                    if thread_id in line:
                        matches.append(path)
                        break
        except OSError:
            continue
    return max(matches, key=lambda item: item.stat().st_mtime_ns) if matches else None


def _resolve_session_jsonl(
    *,
    session_jsonl: str | Path | None = None,
    thread_id: str | None = None,
    sessions_root: str | Path | None = None,
) -> Path | None:
    if session_jsonl:
        path = Path(session_jsonl).expanduser().resolve()
        return path if path.exists() else None
    resolved_thread = str(thread_id or os.getenv("CODEX_THREAD_ID", "")).strip()
    if not resolved_thread:
        return None
    root = Path(sessions_root or (Path.home() / ".codex" / "sessions")).expanduser()
    return _find_rollout(root, resolved_thread)


def _imagegen_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
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
                    "id": payload.get("id", ""),
                    "status": payload.get("status", ""),
                    "revised_prompt": payload.get("revised_prompt", ""),
                    "result": payload.get("result", ""),
                }
            )
    return records


def _usable_records(records: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    usable: list[tuple[int, dict[str, Any]]] = []
    for index, record in enumerate(records):
        status = str(record.get("status", "")).lower()
        imagegen_id = str(record.get("id", ""))
        if status == "completed" and imagegen_id.startswith("ig_"):
            usable.append((index, record))
    return usable


def _workspace_from_handoff(path: Path, handoff: dict[str, Any]) -> Path:
    value = handoff.get("workspace_dir")
    if value:
        workspace = Path(str(value)).expanduser()
        return workspace.resolve() if workspace.is_absolute() else (path.parent / workspace).resolve()
    return path.parent.resolve()


def _blocked_report_path(handoff_path: Path) -> Path:
    return _workspace_from_handoff(handoff_path, {}) / "references" / "builtin-imagegen-handoff-blocker.json"


def write_blocked_report(
    handoff_path: Path,
    issues: Iterable[str],
    *,
    handoff: dict[str, Any] | None = None,
) -> Path:
    handoff = handoff or {}
    workspace = _workspace_from_handoff(handoff_path, handoff)
    path = workspace / "references" / "builtin-imagegen-handoff-blocker.json"
    slides = handoff.get("slides") if isinstance(handoff.get("slides"), list) else []
    payload = {
        "schema_version": "builtin-imagegen-handoff-blocker-v1",
        "status": "blocked",
        "reason": "builtin_imagegen_required",
        "policy": dict(BUILTIN_ONLY_POLICY),
        "handoff": str(handoff_path.resolve()),
        "issues": list(issues),
        "pending_slides": [
            str(item.get("slide_id"))
            for item in slides
            if str(item.get("status", "pending")) != "generated"
        ],
        "next_action": (
            "Retry the Codex built-in image_gen call for each pending slide, then run "
            "builtin_imagegen_handoff.py ingest/verify. Do not use API, CLI, local command, or mock."
        ),
    }
    _write_json(path, payload)
    return path


def prepare_handoff(
    prompt_manifest: Path,
    *,
    output: Path | None = None,
    thread_id: str | None = None,
    session_jsonl: str | Path | None = None,
    sessions_root: str | Path | None = None,
) -> dict[str, Any]:
    prompt_manifest = prompt_manifest.expanduser().resolve()
    handoff_path = (output or prompt_manifest.parent / "builtin-imagegen-handoff.json").expanduser().resolve()
    try:
        prompt_data = _load_json(prompt_manifest)
    except (OSError, UnicodeError, json.JSONDecodeError):
        prompt_data = None
    if not isinstance(prompt_data, dict):
        blocked = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "created_at": _utc_now(),
            "workspace_dir": str(prompt_manifest.parent.resolve()),
            "prompt_manifest": str(prompt_manifest),
            "policy": dict(BUILTIN_ONLY_POLICY),
            "slides": [],
        }
        _write_json(handoff_path, blocked)
        report = write_blocked_report(handoff_path, ["invalid_image_prompts_json"], handoff=blocked)
        raise BuiltinImageGenHandoffBlocked(["invalid_image_prompts_json"], report_path=report)
    issues = _validate_prompt_policy(prompt_data)
    slides = prompt_data.get("slides")
    if not isinstance(slides, list) or not slides:
        issues.append("image_prompts_has_no_slides")
        slides = []
    queue: list[dict[str, Any]] = []
    for slide in slides:
        if not isinstance(slide, dict):
            issues.append("invalid_slide_record")
            continue
        slide_id = str(slide.get("slide_id") or "").strip()
        if not slide_id:
            issues.append("slide_id_missing")
            continue
        prompt = _prompt_text(slide)
        final_path = str(slide.get("final_path") or f"assets/slides/{slide_id}.png")
        queue.append(
            {
                "slide_id": slide_id,
                "prompt": prompt,
                "prompt_sha256": _sha256_bytes(prompt.encode("utf-8")),
                "final_path": final_path,
                "status": "pending",
                "record_index": None,
                "imagegen_id": "",
                "provenance_sidecar": f"assets/generated/{slide_id}-pipeline.json",
            }
        )
    if issues:
        blocked = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "created_at": _utc_now(),
            "workspace_dir": str(prompt_manifest.parent.resolve()),
            "prompt_manifest": str(prompt_manifest),
            "policy": dict(BUILTIN_ONLY_POLICY),
            "slides": queue,
        }
        _write_json(handoff_path, blocked)
        report = write_blocked_report(handoff_path, issues, handoff=blocked)
        raise BuiltinImageGenHandoffBlocked(issues, report_path=report)

    # Do not scan the current (possibly very large) Codex rollout merely to
    # prepare a queue.  When no explicit JSONL is supplied, ingest resolves the
    # current thread after the agent has made the next built-in call and uses
    # the latest unused completed record.  An explicit session path opts into a
    # baseline count for deterministic multi-call ingestion.
    resolved_session = (
        _resolve_session_jsonl(
            session_jsonl=session_jsonl,
            thread_id=thread_id,
            sessions_root=sessions_root,
        )
        if session_jsonl
        else None
    )
    baseline_count = len(_imagegen_records(resolved_session)) if resolved_session else 0
    resolved_thread = str(thread_id or os.getenv("CODEX_THREAD_ID", "")).strip()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "ready_for_builtin_calls",
        "created_at": _utc_now(),
        "workspace_dir": str(prompt_manifest.parent.resolve()),
        "prompt_manifest": str(prompt_manifest),
        "thread_id": resolved_thread,
        "session_jsonl": str(resolved_session) if resolved_session else "",
        "baseline_record_count": baseline_count,
        "policy": dict(BUILTIN_ONLY_POLICY),
        "agent_instruction": (
            "For every pending slide, call only the Codex built-in image_gen tool once with its prompt. "
            "After each completed call, run ingest for that slide. On failure, retry the built-in call; "
            "never use an API key, CLI, local provider, or mock image."
        ),
        "slides": queue,
    }
    _write_json(handoff_path, payload)
    return payload


def _select_record(
    records: list[dict[str, Any]],
    *,
    handoff: dict[str, Any],
    record_index: int | None,
) -> tuple[int, dict[str, Any]]:
    usable = _usable_records(records)
    if record_index is not None:
        if record_index < 0:
            record_index = len(records) + record_index
        if record_index < 0 or record_index >= len(records):
            raise BuiltinImageGenHandoffBlocked([f"record_index_out_of_range:{record_index}"])
        record = records[record_index]
        if (record_index, record) not in usable:
            raise BuiltinImageGenHandoffBlocked([f"record_is_not_completed_builtin_imagegen:{record_index}"])
        return record_index, record
    baseline = int(handoff.get("baseline_record_count") or 0)
    used = {
        int(item.get("record_index"))
        for item in handoff.get("slides", [])
        if isinstance(item, dict) and str(item.get("record_index", "")).lstrip("-").isdigit()
    }
    candidates = [(index, record) for index, record in usable if index >= baseline and index not in used]
    if not candidates:
        raise BuiltinImageGenHandoffBlocked(["no_new_completed_builtin_imagegen_record"])
    return candidates[-1]


def ingest_slide(
    handoff_path: Path,
    slide_id: str,
    *,
    record_index: int | None = None,
    session_jsonl: str | Path | None = None,
    thread_id: str | None = None,
    sessions_root: str | Path | None = None,
) -> dict[str, Any]:
    handoff_path = handoff_path.expanduser().resolve()
    handoff = _load_json(handoff_path)
    if not isinstance(handoff, dict) or handoff.get("schema_version") != SCHEMA_VERSION:
        raise BuiltinImageGenHandoffBlocked(["invalid_builtin_imagegen_handoff_manifest"])
    if handoff.get("policy") != BUILTIN_ONLY_POLICY:
        report = write_blocked_report(handoff_path, ["builtin_only_policy_mismatch"], handoff=handoff)
        raise BuiltinImageGenHandoffBlocked(["builtin_only_policy_mismatch"], report_path=report)
    slides = handoff.get("slides") if isinstance(handoff.get("slides"), list) else []
    target = next((item for item in slides if isinstance(item, dict) and str(item.get("slide_id")) == str(slide_id)), None)
    if target is None:
        raise BuiltinImageGenHandoffBlocked([f"unknown_slide_id:{slide_id}"])

    resolved_session = _resolve_session_jsonl(
        session_jsonl=session_jsonl or handoff.get("session_jsonl"),
        thread_id=thread_id or handoff.get("thread_id"),
        sessions_root=sessions_root,
    )
    if resolved_session is None:
        report = write_blocked_report(handoff_path, ["builtin_imagegen_rollout_jsonl_missing"], handoff=handoff)
        raise BuiltinImageGenHandoffBlocked(["builtin_imagegen_rollout_jsonl_missing"], report_path=report)
    records = _imagegen_records(resolved_session)
    try:
        selected_index, record = _select_record(records, handoff=handoff, record_index=record_index)
        image_bytes = base64.b64decode(str(record.get("result", "")), validate=True)
    except BuiltinImageGenHandoffBlocked as exc:
        report = write_blocked_report(handoff_path, exc.issues, handoff=handoff)
        raise BuiltinImageGenHandoffBlocked(exc.issues, report_path=report) from exc
    except (ValueError, binascii.Error) as exc:
        report = write_blocked_report(handoff_path, [f"builtin_imagegen_result_decode_failed:{exc.__class__.__name__}"], handoff=handoff)
        raise BuiltinImageGenHandoffBlocked(["builtin_imagegen_result_decode_failed"], report_path=report) from exc
    if not image_bytes.startswith(PNG_SIGNATURE):
        report = write_blocked_report(handoff_path, [f"builtin_imagegen_result_not_png:{slide_id}"], handoff=handoff)
        raise BuiltinImageGenHandoffBlocked([f"builtin_imagegen_result_not_png:{slide_id}"], report_path=report)

    workspace = _workspace_from_handoff(handoff_path, handoff)
    output_path = Path(str(target.get("final_path") or f"assets/slides/{slide_id}.png"))
    output_path = output_path.resolve() if output_path.is_absolute() else (workspace / output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)
    digest = _sha256_file(output_path)
    generated_at = _utc_now()
    sidecar_path = workspace / "assets" / "generated" / f"{slide_id}-pipeline.json"
    sidecar = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "slide_id": str(slide_id),
        "status": "generated",
        "backend": "builtin",
        "provenance_kind": "builtin-imagegen",
        "generation_mode": DIRECT_FINAL_GENERATION_MODE,
        "id": str(record.get("id") or ""),
        "imagegen_id": str(record.get("id") or ""),
        "session_jsonl": str(resolved_session.resolve()),
        "record_index": selected_index,
        "record_line_number": record.get("line_number"),
        "timestamp": record.get("timestamp"),
        "revised_prompt": str(record.get("revised_prompt") or "")[:4000],
        "prompt_sha256": target.get("prompt_sha256", ""),
        "final_path": str(output_path.relative_to(workspace)) if output_path.is_relative_to(workspace) else str(output_path),
        "output_path": str(output_path),
        "sha256": digest,
        "bytes": len(image_bytes),
        "generated_at": generated_at,
    }
    _write_json(sidecar_path, sidecar)

    target.update(
        {
            "status": "generated",
            "record_index": selected_index,
            "imagegen_id": str(record.get("id") or ""),
            "sha256": digest,
            "bytes": len(image_bytes),
            "generated_at": generated_at,
            "provenance_sidecar": str(sidecar_path.relative_to(workspace)) if sidecar_path.is_relative_to(workspace) else str(sidecar_path),
        }
    )
    handoff["session_jsonl"] = str(resolved_session.resolve())
    handoff["status"] = "completed" if all(item.get("status") == "generated" for item in slides) else "in_progress"
    _write_json(handoff_path, handoff)
    return {"status": "generated", "slide_id": str(slide_id), "output": str(output_path), "sidecar": str(sidecar_path), "imagegen_id": sidecar["imagegen_id"], "record_index": selected_index}


def verify_handoff(handoff_path: Path, *, report_path: Path | None = None) -> dict[str, Any]:
    handoff_path = handoff_path.expanduser().resolve()
    try:
        handoff = _load_json(handoff_path)
    except (OSError, json.JSONDecodeError):
        payload = {"schema_version": "builtin-imagegen-handoff-report-v1", "status": "blocked", "issues": ["handoff_manifest_missing_or_invalid"]}
        path = report_path or handoff_path.with_name("builtin-imagegen-handoff-report.json")
        _write_json(path, payload)
        return payload
    issues: list[str] = []
    if handoff.get("schema_version") != SCHEMA_VERSION:
        issues.append("invalid_builtin_imagegen_handoff_manifest")
    if handoff.get("policy") != BUILTIN_ONLY_POLICY:
        issues.append("builtin_only_policy_mismatch")
    workspace = _workspace_from_handoff(handoff_path, handoff)
    prompt_path = Path(str(handoff.get("prompt_manifest") or workspace / "image-prompts.json"))
    if not prompt_path.is_absolute():
        prompt_path = (handoff_path.parent / prompt_path).resolve()
    prompts = _load_json(prompt_path) if prompt_path.exists() else None
    if not isinstance(prompts, dict):
        issues.append("builtin_imagegen_prompt_pack_missing")
    else:
        issues.extend(_validate_prompt_policy(prompts))
    validation_issues, accepted = validate_builtin_imagegen_outputs(workspace, prompts if isinstance(prompts, dict) else None)
    issues.extend(validation_issues)
    slides = handoff.get("slides") if isinstance(handoff.get("slides"), list) else []
    for item in slides:
        if not isinstance(item, dict):
            issues.append("invalid_handoff_slide_record")
            continue
        if item.get("status") != "generated":
            issues.append(f"handoff_slide_not_generated:{item.get('slide_id', '')}")
        if not str(item.get("imagegen_id") or "").startswith("ig_"):
            issues.append(f"handoff_slide_missing_strong_ig_id:{item.get('slide_id', '')}")
    payload = {
        "schema_version": "builtin-imagegen-handoff-report-v1",
        "status": "pass" if not issues else "blocked",
        "verdict": "pass" if not issues else "blocked",
        "handoff": str(handoff_path),
        "policy": dict(BUILTIN_ONLY_POLICY),
        "slides_expected": len(slides),
        "slides_verified": len(accepted),
        "issues": issues,
        "next_action": "Proceed to image-only PPTX assembly." if not issues else "Retry built-in image_gen for pending slides; no alternate backend is permitted.",
    }
    path = report_path or (workspace / "references" / "builtin-imagegen-handoff-report.json")
    _write_json(path, payload)
    if issues:
        write_blocked_report(handoff_path, issues, handoff=handoff)
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare, ingest, and verify built-in Codex ImageGen handoffs.")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="Write the built-in-only handoff manifest.")
    prepare.add_argument("prompt_manifest")
    prepare.add_argument("--output")
    prepare.add_argument("--thread-id")
    prepare.add_argument("--session-jsonl")
    prepare.add_argument("--sessions-root")

    ingest = sub.add_parser("ingest", help="Materialise one completed built-in ImageGen call.")
    ingest.add_argument("handoff")
    ingest.add_argument("--slide-id", required=True)
    ingest.add_argument("--record-index", type=int)
    ingest.add_argument("--session-jsonl")
    ingest.add_argument("--thread-id")
    ingest.add_argument("--sessions-root")

    verify = sub.add_parser("verify", help="Verify all slides and strong built-in provenance.")
    verify.add_argument("handoff")
    verify.add_argument("--report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            payload = prepare_handoff(
                Path(args.prompt_manifest),
                output=Path(args.output) if args.output else None,
                thread_id=args.thread_id,
                session_jsonl=args.session_jsonl,
                sessions_root=args.sessions_root,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "ingest":
            payload = ingest_slide(
                Path(args.handoff),
                args.slide_id,
                record_index=args.record_index,
                session_jsonl=args.session_jsonl,
                thread_id=args.thread_id,
                sessions_root=args.sessions_root,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        payload = verify_handoff(Path(args.handoff), report_path=Path(args.report) if args.report else None)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("verdict") == "pass" else 1
    except BuiltinImageGenHandoffBlocked as exc:
        print(json.dumps({"status": "blocked", "issues": exc.issues, "report": str(exc.report_path) if exc.report_path else ""}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
