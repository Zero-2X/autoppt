#!/usr/bin/env python3
"""Create an isolated official-style v2 prompt/deck candidate that requires fresh ImageGen pages."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
from pathlib import Path
from typing import Any

try:
    from .style_contracts import (
        OFFICIAL_REFERENCE_SOURCES,
        get_style_profile,
        identity_prompt_guard,
        merge_style_contract,
        validate_identity_text_exceptions,
    )
    from .verify_imagegen_first_gate import validate_official_source_contract
except ImportError:  # pragma: no cover - supports direct script execution.
    from style_contracts import (
        OFFICIAL_REFERENCE_SOURCES,
        get_style_profile,
        identity_prompt_guard,
        merge_style_contract,
        validate_identity_text_exceptions,
    )
    from verify_imagegen_first_gate import validate_official_source_contract


PROMPT_POLICY_V2: dict[str, Any] = {
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
    "one_call_per_slide": True,
    "on_block": "retry_builtin_or_stop",
    "per_slide_imagegen_required": True,
    "fresh_prompt_per_slide": True,
    "forbid_reusing_old_generations": True,
    "forbid_generic_master_template_first": True,
    "complete_final_page_required": True,
    "allow_text_free_visual_base_plus_local_overlay": False,
    "forbid_text_free_visual_base_plus_local_overlay": True,
    "no_native_ppt_overlay": True,
    "no_template_reuse": True,
    "no_script_generated_slide_content": True,
    "official_source_inspired_only": True,
    "forbid_official_template_claim": True,
    "forbid_institutional_identity_elements": True,
    "candidate_requires_fresh_imagegen": True,
    "reuse_current_slide_images": False,
}


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def rebase_path(value: str, source_run: Path, output_dir: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        return path.as_posix()
    absolute = (source_run / path).resolve()
    return Path(os.path.relpath(absolute, output_dir.resolve())).as_posix()


def identity_components(identity_text: list[str]) -> list[str]:
    components: list[str] = []
    for item in identity_text:
        for part in item.split():
            part = part.strip()
            if len(part) >= 3 and part not in components:
                components.append(part)
    return sorted(components, key=len, reverse=True)


def migrate_prompt(
    prompt: str,
    *,
    exact_text: list[str],
    style_reference: dict[str, Any],
) -> str:
    verified = [
        item
        for item in style_reference.get("verified_identity_text", [])
        if isinstance(item, str) and item.strip()
    ]
    components = identity_components(verified)
    migrated_lines: list[str] = []
    for raw_line in prompt.splitlines():
        line = raw_line
        if line.startswith("用途与受众："):
            line = (
                "用途与受众：本科毕业设计答辩，面向船舶与海洋工程、计算机视觉及系统实现方向评审；"
                "不得从受众描述推断或生成机构视觉身份。"
            )
        elif not line.startswith("必须逐字显示且不得添加其他可见文字："):
            for component in components:
                line = line.replace(component, "答辩单位")
        migrated_lines.append(line)

    allowed = "；".join(style_reference.get("allowed_extraction", []))
    guard = identity_prompt_guard(style_reference, exact_text)
    migrated_lines.extend(
        [
            "",
            "【官方来源启发契约 v2】",
            "参考定位：仅借鉴第一方来源中已去身份化的高层构图规律；本页不是官方模板、官方母版、机构背书或隶属关系证明。",
            f"允许抽取：{allowed}。",
            f"机构身份门禁：{guard}",
            "生成边界：必须依据本 v2 完整提示词重新执行 ImageGen；不得复制、链接或冒用旧版页图及其 provenance。",
        ]
    )
    return "\n".join(migrated_lines).strip() + "\n"


def prompt_pack(manifest: dict[str, Any]) -> str:
    lines = [
        "# 张正轩毕业答辩 v2 ImageGen 提示词候选",
        "",
        "> 候选仅包含规划与提示词，不含可冒用的旧页图或 provenance。每页必须重新执行 ImageGen。",
        "",
        f"- Style profile: `{manifest['style_profile']}`",
        f"- Slides: `{len(manifest['slides'])}`",
        "- Official template: `false`",
        "- Fresh ImageGen required: `true`",
        "",
    ]
    for slide in manifest["slides"]:
        lines.extend(
            [
                f"## {slide['slide_id']} · {slide.get('headline', '')}",
                "",
                f"- Prompt SHA-256: `{slide['prompt_sha256']}`",
                f"- Pending output: `{slide['final_path']}`",
                "",
                "```text",
                slide["prompt_zh"].rstrip(),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def build_candidate(
    source_run: Path,
    output_dir: Path,
    *,
    style_profile: str,
    verified_identity_text: list[str],
) -> dict[str, Any]:
    source_prompt_path = source_run / "image-prompts.json"
    source_deck_path = source_run / "deck-spec.json"
    source_style_path = source_run / "style-contract.json"
    source_prompts = read_json(source_prompt_path)
    source_deck = read_json(source_deck_path)
    source_style = read_json(source_style_path)

    resolved_style = merge_style_contract(
        {
            "style_profile": style_profile,
            "verified_identity_text": verified_identity_text,
        }
    )
    profile = get_style_profile(style_profile)
    style_reference = resolved_style["style_reference"]
    source_slides = source_prompts.get("slides", [])
    if not isinstance(source_slides, list) or not source_slides:
        raise ValueError("source image-prompts.json has no slides")
    all_exact_text = [
        str(item)
        for slide in source_slides
        for item in (slide.get("exact_text") or [])
    ]
    validate_identity_text_exceptions(resolved_style, all_exact_text)

    candidate_prompts = deepcopy(source_prompts)
    candidate_prompts["schema_version"] = 2
    candidate_prompts["candidate_status"] = "planning_only_fresh_imagegen_required"
    candidate_prompts["source_manifest_sha256"] = sha256_file(source_prompt_path)
    candidate_prompts["style_profile"] = style_profile
    candidate_prompts["style_reference"] = deepcopy(style_reference)
    policy = dict(candidate_prompts.get("prompt_policy", {}))
    policy.update(PROMPT_POLICY_V2)
    candidate_prompts["prompt_policy"] = policy

    migrated_slides: list[dict[str, Any]] = []
    for source_slide in source_slides:
        slide = deepcopy(source_slide)
        slide_id = str(slide.get("slide_id", "")).strip()
        if not slide_id:
            raise ValueError("every source prompt slide requires slide_id")
        exact_text = [str(item) for item in (slide.get("exact_text") or [])]
        slide["final_path"] = f"assets/slides/{slide_id}.png"
        slide["generation_status"] = "pending_fresh_imagegen_v2"
        slide["style_profile"] = style_profile
        slide["style_reference"] = deepcopy(style_reference)
        slide["design_density"] = resolved_style["design_density"]
        slide["intentional_minimal"] = resolved_style["intentional_minimal"]
        slide["design_completion"] = resolved_style["design_completion"]
        slide["quality_guardrails"] = resolved_style["quality_guardrails"]
        slide["source_asset_paths"] = [
            rebase_path(str(value), source_run, output_dir)
            for value in (slide.get("source_asset_paths") or [])
        ]
        slide["prompt_zh"] = migrate_prompt(
            str(slide.get("prompt_zh", "")),
            exact_text=exact_text,
            style_reference=style_reference,
        )
        slide["prompt_sha256"] = prompt_sha256(slide["prompt_zh"])
        migrated_slides.append(slide)
    candidate_prompts["slides"] = migrated_slides

    candidate_deck = deepcopy(source_deck)
    candidate_deck["schema_version"] = 2
    candidate_deck["status"] = "candidate_waiting_for_fresh_imagegen_assets"
    deck = dict(candidate_deck.get("deck", {}))
    deck.update(
        {
            "style_profile": style_profile,
            "style_reference": deepcopy(style_reference),
            "verified_identity_text": list(verified_identity_text),
            "allowed_identity_text": list(verified_identity_text),
            "design_density": resolved_style["design_density"],
            "intentional_minimal": resolved_style["intentional_minimal"],
            "style_contract": resolved_style["style_contract"],
            "design_completion": resolved_style["design_completion"],
            "quality_guardrails": resolved_style["quality_guardrails"],
            "output_mode": "imagegen_full_slide",
            "generation_mode": "direct_final_slide_imagegen",
            "slide_count": len(migrated_slides),
            "assembly_blocked_until_all_slide_images_exist": True,
            "fresh_imagegen_required": True,
            "current_asset_reuse_allowed": False,
        }
    )
    candidate_deck["deck"] = deck
    candidate_deck["slides"] = [
        {
            "slide_id": slide["slide_id"],
            "layout": "full_slide_image",
            "slide_image": slide["final_path"],
        }
        for slide in migrated_slides
    ]

    candidate_style = deepcopy(source_style)
    candidate_style["schema_version"] = 2
    candidate_style["candidate_status"] = "planning_only_fresh_imagegen_required"
    candidate_style["style_profile"] = style_profile
    candidate_style["profile_label"] = profile["label"]
    candidate_style["intentional_minimal"] = resolved_style["intentional_minimal"]
    candidate_style["design_density"] = resolved_style["design_density"]
    candidate_style["style_reference"] = deepcopy(style_reference)
    candidate_style["official_reference_basis"] = deepcopy(style_reference["sources"])
    xjtu_context = deepcopy(OFFICIAL_REFERENCE_SOURCES["xjtu_som_degree_defense"])
    xjtu_context.update(
        {
            "candidate_use": "endpoint_discovery_evidence_only",
            "content_level_extraction_allowed": False,
            "page_specific_visual_rule_allowed": False,
        }
    )
    candidate_style["context_only_sources"] = [xjtu_context]
    candidate_style["source_and_identity_policy"] = {
        "official_template_claim": False,
        "copy_source_master_geometry": False,
        "reuse_logo_seal_or_campus_image": False,
        "reuse_official_palette_exactly": False,
        "verified_identity_text": list(verified_identity_text),
        "identity_text_policy": "source_verified_exact_text_only_not_identity_asset",
        "xjtu_endpoint_policy": "discovery evidence only; no content-level or page-specific visual extraction",
        "github_policy": "workflow mechanics only when license permits; never visual authority for an official style claim",
    }
    candidate_style["migration"] = {
        "created_on": date.today().isoformat(),
        "source_run": str(source_run.resolve()),
        "source_style_contract_sha256": sha256_file(source_style_path),
        "requires_fresh_imagegen": True,
        "copied_slide_images": 0,
        "copied_provenance_records": 0,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "style-contract.json", candidate_style)
    write_json(output_dir / "image-prompts.json", candidate_prompts)
    write_json(output_dir / "deck-spec.json", candidate_deck)
    (output_dir / "imagegen-prompt-pack.md").write_text(
        prompt_pack(candidate_prompts), encoding="utf-8"
    )

    prompt_slides = {slide["slide_id"]: slide for slide in migrated_slides}
    contract_report, contract_errors = validate_official_source_contract(
        deck,
        candidate_prompts,
        candidate_deck["slides"],
        prompt_slides,
    )
    active_source_ids = {
        source.get("url") for source in style_reference.get("sources", []) if isinstance(source, dict)
    }
    xjtu_active = xjtu_context["url"] in active_source_ids
    identity_occurrences = {
        slide["slide_id"]: sum(
            slide["prompt_zh"].count(component)
            for component in identity_components(verified_identity_text)
        )
        for slide in migrated_slides
    }
    non_identity_slide_occurrences = {
        slide_id: count
        for slide_id, count in identity_occurrences.items()
        if not any(
            identity in prompt_slides[slide_id].get("exact_text", [])
            for identity in verified_identity_text
        )
        and count
    }
    source_asset_missing = sorted(
        {
            value
            for slide in migrated_slides
            for value in slide.get("source_asset_paths", [])
            if not (output_dir / value).resolve().exists()
        }
    )
    candidate_images = list((output_dir / "assets" / "slides").glob("*.png"))
    static_errors = list(contract_errors)
    if xjtu_active:
        static_errors.append("XJTU endpoint context leaked into active visual-authority sources")
    if non_identity_slide_occurrences:
        static_errors.append("verified institution text leaked into non-identity slide prompts")
    if source_asset_missing:
        static_errors.append("rebased source assets are missing")
    if candidate_images:
        static_errors.append("candidate unexpectedly contains slide images")
    static_report = {
        "schema_version": 1,
        "candidate_only": True,
        "release_evidence": False,
        "verdict": "pass" if not static_errors else "fail",
        "official_source_contract": contract_report,
        "checks": {
            "slide_count": len(migrated_slides),
            "deck_top_and_per_slide_style_reference_equal": not contract_errors,
            "xjtu_active_visual_authority": xjtu_active,
            "xjtu_context_only": not xjtu_context["content_level_extraction_allowed"],
            "non_identity_slide_name_occurrences": non_identity_slide_occurrences,
            "rebased_source_assets_missing": source_asset_missing,
            "candidate_slide_images_present": len(candidate_images),
            "candidate_provenance_records_present": 0,
        },
        "errors": static_errors,
        "boundary": "Static contract validation only. All 21 page images require fresh ImageGen generation before the real gate can pass.",
    }
    write_json(output_dir / "qa" / "official-contract-static-report.json", static_report)

    readme = f"""# 张正轩毕业答辩官方风格契约 v2 候选

该目录是隔离的规划与提示词候选，不覆盖父目录的当前页图、accepted 母版、provenance ledger 或 image-only PPTX。

- 风格：`{style_profile}`
- 页数：`{len(migrated_slides)}`
- 官方模板声明：`false`
- 当前页图复用：`false`
- 必须重新 ImageGen：`true`
- 静态契约报告：`qa/official-contract-static-report.json`
- ImageGen-first fixture 测试：`qa/imagegen-first-fixture-junit.xml`（仅测试门禁逻辑，不是生成证明）

`assets/slides/` 当前应为空。只有使用本目录 `image-prompts.json` 的逐页完整提示词重新生成 21 张页面、写入真实 ImageGen provenance，并重新组装 image-only PPTX 后，真实 ImageGen-first gate 才有资格通过。

西安交通大学管理学院端点只保留为 endpoint discovery evidence；CLI 未核验正文，因此禁止内容级抽取、页面视觉规则抽取和资产复用。
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    artifact_paths = sorted(
        path for path in output_dir.rglob("*") if path.is_file() and path.name != "candidate-manifest.json"
    )
    candidate_manifest = {
        "schema_version": 1,
        "candidate_only": True,
        "release_evidence": False,
        "created_on": date.today().isoformat(),
        "source_run": str(source_run.resolve()),
        "source_inputs": {
            "image-prompts.json": sha256_file(source_prompt_path),
            "deck-spec.json": sha256_file(source_deck_path),
            "style-contract.json": sha256_file(source_style_path),
        },
        "artifacts": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in artifact_paths
        ],
        "counts": {
            "slides": len(migrated_slides),
            "candidate_slide_images": 0,
            "copied_provenance_records": 0,
        },
        "verdict": static_report["verdict"],
        "next_gate": "fresh ImageGen for all 21 prompts, then real provenance-bound image-only assembly gate",
    }
    write_json(output_dir / "candidate-manifest.json", candidate_manifest)
    return candidate_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_run", help="Existing run containing image-prompts.json and deck-spec.json.")
    parser.add_argument("output_dir", help="Isolated output directory for the v2 candidate.")
    parser.add_argument("--style-profile", default="engineering_institutional_blue")
    parser.add_argument(
        "--verified-identity-text",
        action="append",
        default=[],
        help="Exact source-verified institution text; repeat when needed.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = build_candidate(
        Path(args.source_run).expanduser().resolve(),
        Path(args.output_dir).expanduser().resolve(),
        style_profile=args.style_profile,
        verified_identity_text=list(args.verified_identity_text),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
