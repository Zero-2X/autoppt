from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


EVIDENCE_ID_RE = re.compile(r"\b(?:auto_ev|ev|E)_[A-Za-z0-9_.-]+\b|\bE\d{1,4}\b")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def evidence_items_from_ledger(ledger: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(ledger, dict):
        return []
    raw = ledger.get("evidence_items") or ledger.get("evidence") or ledger.get("items") or []
    return [item for item in raw if isinstance(item, dict)]


def normalize_evidence_item(item: dict[str, Any], *, index: int = 1) -> dict[str, Any]:
    evidence_id = str(
        item.get("evidence_id") or item.get("id") or item.get("claim_id") or f"E{index:02d}"
    ).strip()
    source = str(
        item.get("source_file")
        or item.get("source_path")
        or item.get("link_or_path")
        or item.get("source")
        or ""
    ).strip()
    claim = str(item.get("claim") or item.get("fact") or item.get("summary") or item.get("title") or "").strip()
    locations = _as_list(item.get("source_locations") or item.get("location") or item.get("support_sections"))
    location_text = "; ".join(str(value).strip() for value in locations if str(value).strip())
    return {
        "evidence_id": evidence_id,
        "fact_or_data": str(item.get("fact_or_data") or item.get("fact") or claim).strip(),
        "title": str(item.get("title") or item.get("source_title") or evidence_id).strip(),
        "source_file": source,
        "source_location": location_text,
        "page": item.get("page") or item.get("page_no"),
        "figure": item.get("figure") or item.get("figure_no") or item.get("figure_id"),
        "table": item.get("table") or item.get("table_no") or item.get("table_id"),
        "chapter": item.get("chapter") or item.get("section"),
        "confirmed": bool(item.get("confirmed", item.get("verified", item.get("is_confirmed", False)))),
        "ppt_allowed": bool(item.get("ppt_allowed", item.get("allowed_in_ppt", True))),
        "supports_claims": [str(v) for v in _as_list(item.get("supports_claims") or item.get("can_support")) if str(v).strip()],
        "cannot_support": [str(v) for v in _as_list(item.get("cannot_support") or item.get("cannot_prove")) if str(v).strip()],
        "reliability": str(item.get("reliability") or "unknown").strip().lower(),
        "risk_level": str(item.get("risk_level") or "unknown").strip().lower(),
        "risk_notes": str(item.get("risk_notes") or item.get("boundary") or "").strip(),
        "claim": claim,
        "raw": item,
    }


def normalize_evidence_ledger(ledgers: Iterable[dict[str, Any]], *, source_label: str = "") -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ledger in ledgers:
        for index, raw_item in enumerate(evidence_items_from_ledger(ledger), start=1):
            item = normalize_evidence_item(raw_item, index=index)
            if item["evidence_id"] in seen:
                continue
            seen.add(item["evidence_id"])
            normalized.append(item)
    return {
        "schema_version": "presentation-evidence-v1",
        "generated_at": utc_now(),
        "source_label": source_label,
        "evidence_items": normalized,
        "summary": {
            "count": len(normalized),
            "confirmed_count": sum(1 for item in normalized if item["confirmed"]),
            "ppt_allowed_count": sum(1 for item in normalized if item["ppt_allowed"]),
            "unconfirmed_ids": [item["evidence_id"] for item in normalized if not item["confirmed"]],
        },
    }


def _slide_text(slide: dict[str, Any]) -> list[str]:
    values = [
        slide.get("action_title"), slide.get("title"), slide.get("one_sentence_message"),
        slide.get("core_question"), slide.get("slide_goal"),
    ]
    values.extend(_as_list(slide.get("must_say")))
    values.extend(_as_list(slide.get("supporting_items")))
    return [str(v).strip() for v in values if str(v).strip()]


def _evidence_ids(slide: dict[str, Any], known_ids: set[str]) -> list[str]:
    candidates = []
    for key in ("evidence_ids", "evidence_refs", "claim_ids"):
        candidates.extend(_as_list(slide.get(key)))
    found: list[str] = []
    for value in candidates:
        text = str(value)
        matches = EVIDENCE_ID_RE.findall(text)
        values = matches or ([text.strip()] if text.strip() in known_ids else [])
        for match in values:
            if match in known_ids and match not in found:
                found.append(match)
    return found


def build_slide_ir(
    slide_brief: dict[str, Any],
    *,
    profile: dict[str, Any],
    evidence_ledger: dict[str, Any],
    image_root: str = "assets/slides",
) -> dict[str, Any]:
    raw_slides = list(slide_brief.get("slides", [])) if isinstance(slide_brief, dict) else []
    evidence = evidence_ledger.get("evidence_items", []) if isinstance(evidence_ledger, dict) else []
    known_ids = {str(item.get("evidence_id")) for item in evidence if item.get("evidence_id")}
    slide_irs: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_slides, start=1):
        slide = dict(raw) if isinstance(raw, dict) else {}
        slide_id = str(slide.get("slide_id") or f"S{index:02d}")
        title = str(slide.get("action_title") or slide.get("title") or slide_id).strip()
        core_question = str(
            slide.get("core_question")
            or slide.get("question")
            or slide.get("slide_goal")
            or f"本页需要回答什么问题？"
        ).strip()
        support = [str(v).strip() for v in _as_list(slide.get("supporting_items") or slide.get("must_say")) if str(v).strip()]
        support = support[:3]
        evidence_ids = _evidence_ids(slide, known_ids)
        source_refs = [str(v).strip() for v in _as_list(slide.get("source_locations") or slide.get("source_refs") or slide.get("source_section")) if str(v).strip()]
        slide_irs.append(
            {
                "slide_id": slide_id,
                "page_role": str(slide.get("page_role") or ("cover" if index == 1 else "content")),
                "action_title": title,
                "core_question": core_question,
                "main_visual": {
                    "type": str(slide.get("main_visual_type") or profile.get("imagegen_route", "fullpage_imagegen_reconstruct")),
                    "source": str(slide.get("main_visual_source") or f"{image_root}/{slide_id}.png"),
                },
                "supporting_items": support,
                "claim_ids": [str(v) for v in _as_list(slide.get("claim_ids")) if str(v).strip()],
                "evidence_ids": evidence_ids,
                "speaker_duration_seconds": int(slide.get("speaker_duration_seconds") or slide.get("duration_seconds") or profile.get("default_duration_seconds", 60)),
                "previous_slide_link": slide_irs[-1]["slide_id"] if slide_irs else None,
                "next_slide_link": None,
                "source_locations": source_refs,
                "exact_text": _slide_text(slide),
                "visual_hint": str(slide.get("visual_hint") or "").strip(),
                "source_slide": slide,
            }
        )
    for index, item in enumerate(slide_irs):
        item["next_slide_link"] = slide_irs[index + 1]["slide_id"] if index + 1 < len(slide_irs) else None
    return {
        "schema_version": "slide-ir-v1",
        "generated_at": utc_now(),
        "presentation_profile": profile.get("profile_id"),
        "imagegen_route": profile.get("imagegen_route", "fullpage_imagegen_reconstruct"),
        "slides": slide_irs,
    }


def validate_slide_contract(slide_ir: dict[str, Any], *, require_evidence: bool = True) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    slides = slide_ir.get("slides", []) if isinstance(slide_ir, dict) else []
    for item in slides:
        sid = str(item.get("slide_id", "?"))
        if not str(item.get("action_title", "")).strip():
            issues.append(f"{sid}:missing_action_title")
        if not str(item.get("core_question", "")).strip():
            issues.append(f"{sid}:missing_core_question")
        if not item.get("main_visual"):
            issues.append(f"{sid}:missing_main_visual")
        if len(item.get("supporting_items", [])) > 3:
            issues.append(f"{sid}:too_many_supporting_items")
        if require_evidence and not item.get("evidence_ids"):
            warnings.append(f"{sid}:missing_evidence_ids")
        if int(item.get("speaker_duration_seconds") or 0) <= 0:
            issues.append(f"{sid}:invalid_speaker_duration")
    return {
        "schema_version": "slide-contract-v1",
        "verdict": "pass" if not issues else "fail",
        "slide_count": len(slides),
        "issues": issues,
        "warnings": warnings,
        "total_duration_seconds": sum(int(item.get("speaker_duration_seconds") or 0) for item in slides),
    }
