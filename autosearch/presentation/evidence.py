from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .schemas import normalize_evidence_ledger, sha256_file, utc_now, write_json


_BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".pptx", ".pdf", ".xlsx", ".xls", ".docx", ".doc", ".zip"}
_SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", ".codex-tmp", ".runtime-temp", ".office_tmp", ".qa_tmp"}


def _iso_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except OSError:
        return ""


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".pdf", ".doc", ".docx"}:
        return "document"
    if suffix in {".xlsx", ".xls", ".csv", ".tsv"}:
        return "data"
    if suffix in {".pptx", ".ppt"}:
        return "presentation"
    if suffix in _BINARY_SUFFIXES:
        return "image_or_binary"
    if suffix in {".json", ".yaml", ".yml", ".toml"}:
        return "structured_text"
    if suffix in {".md", ".txt", ".tex", ".py", ".js", ".ts"}:
        return "text"
    return "other"


def iter_source_files(topic_dir: Path) -> Iterable[Path]:
    roots = [
        topic_dir / "sources",
        topic_dir / "source-materials",
        topic_dir / "requirements",
        topic_dir / "external_evidence",
        topic_dir / "workspace",
        topic_dir / "handoff",
        topic_dir / "final",
        topic_dir / "output",
    ]
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            parts = list(path.parts)
            if any(parts[index:index + 2] == ["final", "ppt"] for index in range(len(parts) - 1)):
                continue
            # Generated slide images and temporary render files are tracked via
            # slide/image manifests, not duplicated into the source audit.
            if "stage45_workspace" in path.parts and ("assets" in path.parts or "pptx" in path.parts):
                continue
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield path


def build_source_manifest(topic_dir: Path, *, extra_paths: Iterable[Path] = ()) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    paths = list(iter_source_files(topic_dir))
    for path in extra_paths:
        if path.exists() and path.is_file() and path.resolve() not in {p.resolve() for p in paths}:
            paths.append(path)
    for path in sorted(paths):
        try:
            stat = path.stat()
            records.append(
                {
                    "path": str(path.resolve()),
                    "relative_path": str(path.resolve().relative_to(topic_dir.resolve())).replace("\\", "/"),
                    "kind": _kind(path),
                    "suffix": path.suffix.lower(),
                    "bytes": stat.st_size,
                    "sha256": sha256_file(path),
                    "modified_at": _iso_mtime(path),
                    "readable": True,
                    "status": "available",
                }
            )
        except (OSError, ValueError) as exc:
            records.append(
                {
                    "path": str(path),
                    "relative_path": str(path),
                    "kind": _kind(path),
                    "readable": False,
                    "status": "error",
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
            )
    return {
        "schema_version": "source-manifest-v1",
        "generated_at": utc_now(),
        "topic_dir": str(topic_dir.resolve()),
        "source_count": len(records),
        "sources": records,
        "summary": {
            "documents": sum(item["kind"] == "document" for item in records),
            "data_files": sum(item["kind"] == "data" for item in records),
            "presentations": sum(item["kind"] == "presentation" for item in records),
            "images_or_binary": sum(item["kind"] == "image_or_binary" for item in records),
            "unreadable": sum(not item.get("readable", False) for item in records),
        },
    }


def build_figure_source_manifest(topic_dir: Path, *, source_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    candidates = []
    if source_manifest:
        candidates.extend(item for item in source_manifest.get("sources", []) if item.get("kind") == "image_or_binary")
    for index, item in enumerate(candidates, start=1):
        path = Path(str(item.get("path", "")))
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}:
            continue
        records.append(
            {
                "figure_id": f"FIG-{index:03d}",
                "source_file": str(path),
                "source_location": item.get("relative_path", ""),
                "figure_number": None,
                "table_number": None,
                "data_meaning": "待从原始论文/实验资料确认",
                "direct_observation": "待人工或论文解析确认",
                "evidence_boundary": "图像存在不等于其语义、单位和统计显著性已确认",
                "can_support": [],
                "cannot_support": ["未经解析的因果结论", "未经核对的精确数值"],
                "preferred_use": "source_original_crop",
                "editable_class": "movable_image",
            }
        )
    return {
        "schema_version": "figure-source-manifest-v1",
        "generated_at": utc_now(),
        "topic_dir": str(topic_dir.resolve()),
        "figures": records,
    }


def build_paper_analysis(
    *,
    profile: dict[str, Any],
    slide_ir: dict[str, Any],
    evidence_ledger: dict[str, Any],
    figure_manifest: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(existing, dict) and existing.get("schema_version"):
        result = dict(existing)
        result.setdefault("generated_at", utc_now())
        result.setdefault("figures", figure_manifest.get("figures", []))
        return result
    slides = slide_ir.get("slides", [])
    claims = []
    for slide in slides:
        claims.append(
            {
                "slide_id": slide.get("slide_id"),
                "slide_claim": slide.get("action_title", ""),
                "direct_observation": "由对应 evidence_ids/原始图表确认",
                "interpretation": "仅允许写入与证据边界一致的解释",
                "evidence_ids": slide.get("evidence_ids", []),
            }
        )
    return {
        "schema_version": "paper-analysis-v1",
        "generated_at": utc_now(),
        "profile": profile.get("profile_id"),
        "research_object": "待由论文/科研资料确认；当前以页面契约和证据账本为索引",
        "research_question": [slide.get("core_question", "") for slide in slides[:3] if slide.get("core_question")],
        "research_strategy": "source_grounded_presentation",
        "methods": [],
        "figures": figure_manifest.get("figures", []),
        "claims": claims,
        "limitations": ["未提供论文解析时，不自动补写研究结论、图表数值或因果关系"],
        "evidence_count": len(evidence_ledger.get("evidence_items", [])),
    }


def build_requirement_matrix(*, profile: dict[str, Any], slide_ir: dict[str, Any], evidence_ledger: dict[str, Any]) -> dict[str, Any]:
    slides = slide_ir.get("slides", [])
    evidence_ids = {str(item.get("evidence_id")) for item in evidence_ledger.get("evidence_items", [])}
    rows: list[dict[str, Any]] = []
    for index, requirement in enumerate(profile.get("required_focus", []), start=1):
        needle = str(requirement).lower()
        covered_slides = []
        for slide in slides:
            corpus = " ".join(str(v) for v in [slide.get("action_title"), slide.get("core_question"), *slide.get("supporting_items", [])]).lower()
            if needle in corpus or any(token and token in corpus for token in needle.replace("/", " ").split() if len(token) > 1):
                covered_slides.append(slide.get("slide_id"))
        linked_evidence = sorted({eid for slide in slides if slide.get("slide_id") in covered_slides for eid in slide.get("evidence_ids", []) if eid in evidence_ids})
        rows.append(
            {
                "requirement_id": f"REQ-{index:02d}",
                "requirement": requirement,
                "covered_by_slides": covered_slides,
                "evidence_ids": linked_evidence,
                "status": "covered" if covered_slides and linked_evidence else ("planned" if covered_slides else "missing"),
            }
        )
    return {
        "schema_version": "requirement-matrix-v1",
        "generated_at": utc_now(),
        "profile": profile.get("profile_id"),
        "requirements": rows,
        "summary": {
            "count": len(rows),
            "covered": sum(item["status"] == "covered" for item in rows),
            "planned": sum(item["status"] == "planned" for item in rows),
            "missing": sum(item["status"] == "missing" for item in rows),
        },
    }


def write_source_map(path: Path, *, source_manifest: dict[str, Any], evidence_ledger: dict[str, Any], slide_ir: dict[str, Any]) -> None:
    lines = ["# Source Map", "", "Generated by the presentation orchestrator. Paths and evidence IDs are traceability anchors; they are not claims by themselves.", "", "## Sources", ""]
    for item in source_manifest.get("sources", []):
        lines.append(f"- `{item.get('relative_path', item.get('path', ''))}` — {item.get('kind', 'unknown')} — sha256 `{item.get('sha256', '')}`")
    lines.extend(["", "## Evidence to slides", ""])
    for slide in slide_ir.get("slides", []):
        refs = ", ".join(slide.get("evidence_ids", [])) or "(none; review required)"
        lines.append(f"- `{slide.get('slide_id')}` **{slide.get('action_title', '')}** ← {refs}")
    lines.extend(["", "## Evidence boundaries", ""])
    for item in evidence_ledger.get("evidence_items", []):
        lines.append(f"- `{item.get('evidence_id')}`: {item.get('source_file') or '(source not recorded)'}; {item.get('source_location') or 'location not recorded'}; supports: {', '.join(item.get('supports_claims', [])) or 'not declared'}; cannot support: {', '.join(item.get('cannot_support', [])) or 'not declared'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_existing_json(paths: Iterable[Path]) -> dict[str, Any] | None:
    for path in paths:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            continue
    return None
