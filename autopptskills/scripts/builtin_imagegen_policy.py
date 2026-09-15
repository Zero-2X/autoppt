"""Hard policy for the repository's built-in ImageGen handoff.

The Codex ``image_gen`` tool is invoked by the agent, not by a repository
subprocess.  This module only validates and consumes the PNGs and provenance
sidecars produced by that built-in call.  It intentionally contains no API
client, CLI discovery, shell command, or provider fallback.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


BUILTIN_IMAGEGEN_BACKENDS = {"builtin", "builtin_image_gen"}
BUILTIN_IMAGEGEN_PROVENANCE = {"builtin-imagegen", "builtin_imagegen", "image_generation_call"}
DIRECT_FINAL_GENERATION_MODE = "direct_final_slide_imagegen"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class BuiltinImageGenBlocked(RuntimeError):
    """Raised when a real Stage45 run lacks verified built-in ImageGen output."""

    def __init__(self, issues: Iterable[str], *, report_path: Path | None = None) -> None:
        self.issues = list(issues)
        self.report_path = report_path
        suffix = "; ".join(self.issues) or "unknown_builtin_imagegen_blocker"
        if report_path:
            suffix += f"; blocker_report={report_path}"
        super().__init__(suffix)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slide_id(record: dict[str, Any]) -> str:
    for key in ("slide_id", "slide", "id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip().upper().startswith("S"):
            return value.strip()
    return ""


def _is_builtin_record(record: dict[str, Any]) -> bool:
    backend = str(record.get("backend") or record.get("imagegen_backend") or "").strip().lower()
    provenance = str(record.get("provenance_kind") or record.get("provenance") or "").strip().lower()
    generation_mode = str(record.get("generation_mode") or "").strip()
    status = str(record.get("status") or record.get("provenance_status") or "").strip().lower()
    # ``extract_builtin_imagegen_result.py`` records the native call id.  A
    # strong ``ig_`` id is required so a hand-written backend label cannot
    # masquerade as a built-in result.
    native_id = str(record.get("id") or record.get("imagegen_id") or "").strip().lower()
    backend_ok = backend in BUILTIN_IMAGEGEN_BACKENDS
    provenance_ok = provenance in BUILTIN_IMAGEGEN_PROVENANCE or provenance.startswith("builtin-")
    return (
        generation_mode == DIRECT_FINAL_GENERATION_MODE
        and status in {"generated", "completed"}
        and native_id.startswith("ig_")
        and (backend_ok or provenance_ok)
    )


def _candidate_sidecars(stage45_dir: Path, slide_id: str) -> list[Path]:
    return [
        stage45_dir / "assets" / "generated" / f"{slide_id}-pipeline.json",
        stage45_dir / "assets" / "slides" / f"{slide_id}.image_generation_metadata.json",
        stage45_dir / "assets" / "slides" / f"{slide_id}.imagegen_manifest.json",
        stage45_dir / "references" / f"{slide_id}-builtin-imagegen.json",
        stage45_dir / "references" / "asset-manifest.json",
        stage45_dir / "imagegen_manifest.json",
    ]


def _records_for_slide(stage45_dir: Path, slide_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in _candidate_sidecars(stage45_dir, slide_id):
        if not path.exists():
            continue
        payload = _load_json(path)
        for record in _walk_dicts(payload):
            record_slide = _slide_id(record)
            # A single asset-manifest can omit slide_id in a nested record only
            # when it has exactly one slide; otherwise do not cross-associate.
            if record_slide and record_slide != slide_id:
                continue
            digest = str(record.get("sha256") or record.get("image_sha256") or record.get("output_sha256") or "")
            key = (str(path.resolve()), record_slide, digest)
            if key in seen:
                continue
            seen.add(key)
            record = dict(record)
            record["_source_path"] = str(path)
            records.append(record)
    return records


def _resolve_image(stage45_dir: Path, final_path: str) -> Path:
    value = Path(final_path)
    return value.resolve() if value.is_absolute() else (stage45_dir / value).resolve()


def validate_builtin_imagegen_outputs(
    stage45_dir: Path,
    image_prompts: dict[str, Any] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Validate every requested slide against a built-in ImageGen sidecar.

    No environment variable is read here.  In particular, ``OPENAI_API_KEY``,
    provider URLs, CLI paths, and local command templates are deliberately
    irrelevant to this policy.
    """

    stage45_dir = Path(stage45_dir).resolve()
    prompts = image_prompts
    if prompts is None:
        prompt_path = stage45_dir / "image-prompts.json"
        prompts = _load_json(prompt_path) if prompt_path.exists() else None
    if not isinstance(prompts, dict):
        return ["builtin_imagegen_prompt_pack_missing"], []

    issues: list[str] = []
    accepted: list[dict[str, Any]] = []
    slides = prompts.get("slides") or []
    if not slides:
        return ["builtin_imagegen_prompt_pack_has_no_slides"], []
    for slide in slides:
        slide_id = str(slide.get("slide_id") or "S??")
        image = _resolve_image(stage45_dir, str(slide.get("final_path") or f"assets/slides/{slide_id}.png"))
        if not image.exists() or image.stat().st_size == 0:
            issues.append(f"builtin_imagegen_output_missing:{slide_id}")
            continue
        try:
            with image.open("rb") as handle:
                if handle.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
                    issues.append(f"builtin_imagegen_output_not_png:{slide_id}")
                    continue
            digest = _sha256(image)
        except OSError as exc:
            issues.append(f"builtin_imagegen_output_unreadable:{slide_id}:{exc.__class__.__name__}")
            continue

        records = _records_for_slide(stage45_dir, slide_id)
        if not records:
            issues.append(f"builtin_imagegen_provenance_missing:{slide_id}")
            continue
        matching = []
        forbidden = []
        for record in records:
            record_digest = str(record.get("sha256") or record.get("image_sha256") or record.get("output_sha256") or "").lower()
            if record_digest and record_digest != digest:
                continue
            if _is_builtin_record(record):
                matching.append(record)
            else:
                forbidden.append(record)
        if matching:
            accepted_record = dict(matching[0])
            accepted_record["slide_id"] = slide_id
            accepted_record["sha256"] = digest
            accepted_record["output_path"] = str(image)
            accepted.append(accepted_record)
        elif forbidden:
            backends = sorted({str(item.get("backend") or item.get("imagegen_backend") or "unknown") for item in forbidden})
            issues.append(f"forbidden_imagegen_backend:{slide_id}:{','.join(backends)}")
        else:
            issues.append(f"builtin_imagegen_sha256_mismatch:{slide_id}")
    return issues, accepted


def build_builtin_asset_manifest(
    stage45_dir: Path,
    image_prompts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical asset manifest for verified built-in outputs.

    This helper is deliberately side-effect free.  Callers may write the
    returned manifest only after ``validate_builtin_imagegen_outputs`` reports
    no issues, which keeps a partial or provider-generated page from being
    promoted into the formal Stage45 evidence chain.
    """

    stage45_dir = Path(stage45_dir).resolve()
    prompts = image_prompts
    if prompts is None:
        prompt_path = stage45_dir / "image-prompts.json"
        prompts = _load_json(prompt_path) if prompt_path.exists() else None
    issues, records = validate_builtin_imagegen_outputs(stage45_dir, prompts)
    if issues:
        raise BuiltinImageGenBlocked(issues)
    by_slide = {str(item.get("slide_id")): item for item in records}
    slides = []
    for slide in (prompts or {}).get("slides", []):
        slide_id = str(slide.get("slide_id") or "")
        record = dict(by_slide.get(slide_id, {}))
        slides.append(
            {
                "slide_id": slide_id,
                "status": "generated",
                "backend": "builtin",
                "imagegen_backend": "builtin_image_gen",
                "provenance_kind": "builtin-imagegen",
                "generation_mode": DIRECT_FINAL_GENERATION_MODE,
                "provenance_strength": "strong-ig-id" if str(record.get("id") or record.get("imagegen_id") or "").startswith("ig_") else "builtin-provenance",
                "id": str(record.get("id") or record.get("imagegen_id") or ""),
                "imagegen_id": str(record.get("id") or record.get("imagegen_id") or ""),
                "final_path": str(record.get("output_path") or slide.get("final_path") or ""),
                "output_path": str(record.get("output_path") or ""),
                "sha256": str(record.get("sha256") or ""),
                "output_sha256": str(record.get("sha256") or ""),
                "bytes": int(record.get("bytes") or 0),
                "prompt_sha256": str(slide.get("prompt_sha256") or record.get("prompt_sha256") or ""),
                "provenance_sidecar": str(record.get("_source_path") or ""),
                "generated_at": str(record.get("generated_at") or record.get("timestamp") or ""),
            }
        )
    return {
        "schema_version": "builtin-imagegen-asset-manifest-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generation_mode": DIRECT_FINAL_GENERATION_MODE,
        "backend": "builtin_image_gen",
        "policy": {
            "builtin_imagegen_only": True,
            "external_api_key_allowed": False,
            "external_cli_allowed": False,
            "local_command_allowed": False,
            "mock_formal_output_allowed": False,
        },
        "slides": slides,
    }


def write_builtin_blocker_report(
    stage45_dir: Path,
    issues: Iterable[str],
    *,
    image_prompts: dict[str, Any] | None = None,
    report_path: Path | None = None,
) -> Path:
    stage45_dir = Path(stage45_dir).resolve()
    path = report_path or (stage45_dir / "references" / "builtin-imagegen-blocker.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    slides = (image_prompts or {}).get("slides") or []
    payload = {
        "schema_version": "builtin-imagegen-blocker-v1",
        "status": "blocked",
        "reason": "builtin_imagegen_required",
        "policy": {
            "backend": "builtin_image_gen",
            "external_api_key_allowed": False,
            "external_cli_allowed": False,
            "local_command_allowed": False,
            "mock_formal_output_allowed": False,
        },
        "issues": list(issues),
        "required_artifacts": [
            {
                "slide_id": str(slide.get("slide_id") or ""),
                "output": str(slide.get("final_path") or ""),
                "provenance": f"assets/generated/{slide.get('slide_id')}-pipeline.json",
                "provenance_backend": "builtin_image_gen",
            }
            for slide in slides
        ],
        "next_action": "Invoke the built-in image_gen tool for each slide, save each PNG and matching sidecar, then rerun Stage45.",
        "resume_entrypoint": "autopptskills/scripts/ppt/ppt_stage_runner.py <topic_dir> --real",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "BUILTIN_IMAGEGEN_BACKENDS",
    "BUILTIN_IMAGEGEN_PROVENANCE",
    "BuiltinImageGenBlocked",
    "DIRECT_FINAL_GENERATION_MODE",
    "validate_builtin_imagegen_outputs",
    "build_builtin_asset_manifest",
    "write_builtin_blocker_report",
]
