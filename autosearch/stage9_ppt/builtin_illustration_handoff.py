"""Prepare paper-illustration prompts for Codex's built-in ``image_gen``.

The repository cannot call the host's built-in image tool from a Python
subprocess.  This small adapter writes the prompt manifest and delegates the
actual PNG generation to :mod:`builtin_imagegen_handoff`.  It deliberately
contains no provider client, API-key lookup, local-model import, or fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .builtin_imagegen_handoff import (
    BuiltinImageGenHandoffBlocked,
    prepare_handoff,
)


ILLUSTRATION_PROMPT_POLICY: dict[str, Any] = {
    "backend": "builtin_image_gen",
    "output_mode": "direct_final_slide_imagegen",
    "imagegen_required": True,
    "auto_invoke_builtin_imagegen": True,
    "builtin_imagegen_only": True,
    "external_api_key_allowed": False,
    "external_cli_allowed": False,
    "local_command_allowed": False,
    "mock_formal_output_allowed": False,
    "fallback_allowed": False,
    "per_slide_imagegen_required": True,
    # The shared slide handoff validator is also used for one-figure queues.
    # Keep the canonical key so illustration manifests cannot silently relax
    # the one-call-per-item contract.
    "one_call_per_slide": True,
    "one_call_per_figure": True,
    "on_block": "retry_builtin_or_stop",
}


def write_illustration_handoff(
    *,
    output_dir: Path,
    figure_kind: str,
    prompt: str,
    final_path: str | None = None,
    reference_images: Iterable[str] = (),
    prompt_manifest: Path | None = None,
    handoff: Path | None = None,
    thread_id: str | None = None,
    session_jsonl: str | Path | None = None,
    sessions_root: str | Path | None = None,
) -> dict[str, Any]:
    """Write an illustration prompt pack and a built-in-only handoff queue."""

    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_kind = str(figure_kind).strip()
    if not figure_kind:
        raise BuiltinImageGenHandoffBlocked(["illustration_figure_kind_missing"])
    prompt = str(prompt).strip()
    if not prompt:
        raise BuiltinImageGenHandoffBlocked([f"illustration_prompt_missing:{figure_kind}"])

    target = str(final_path or f"{figure_kind}_illustration.png")
    manifest_path = (prompt_manifest or output_dir / "image-prompts.json").expanduser().resolve()
    payload = {
        "schema_version": "builtin-imagegen-illustration-prompts-v1",
        "artifact_kind": "paper_illustration",
        "figure_kind": figure_kind,
        "reference_images": [str(item) for item in reference_images],
        "prompt_policy": dict(ILLUSTRATION_PROMPT_POLICY),
        "slides": [
            {
                "slide_id": figure_kind,
                "prompt": prompt,
                "final_path": target,
                "reference_images": [str(item) for item in reference_images],
            }
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    prepared = prepare_handoff(
        manifest_path,
        output=handoff,
        thread_id=thread_id,
        session_jsonl=session_jsonl,
        sessions_root=sessions_root,
    )
    prepared["prompt_manifest"] = str(manifest_path)
    prepared["figure_kind"] = figure_kind
    prepared["final_path"] = target
    prepared["reference_images"] = [str(item) for item in reference_images]
    return prepared


__all__ = [
    "BuiltinImageGenHandoffBlocked",
    "ILLUSTRATION_PROMPT_POLICY",
    "write_illustration_handoff",
]
