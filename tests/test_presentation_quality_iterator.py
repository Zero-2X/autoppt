from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "autosearch" / "scripts" / "iterate_presentation_quality.py"


def load_module():
    spec = importlib.util.spec_from_file_location("presentation_quality_iterator", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_only_repair_is_local_and_does_not_mutate_input():
    module = load_module()
    deck = {
        "slides": [
            {
                "slide_id": "S01",
                "texts": [
                    {"id": "t1", "text": "A", "source_bbox": [10, 10, 20, 20], "layout_bbox": [0, 0, 100, 100]},
                    {"id": "t2", "text": "目标", "source_bbox": [50, 50, 30, 20], "layout_bbox": [50, 50, 30, 20]},
                ],
            }
        ]
    }
    plan = {"mode": "explicit-only", "actions": [{"slide_id": "S01", "action": "remove_text", "text_id": "t1"}]}
    candidate, actions = module.auto_repair_deck(deck, {}, plan)
    assert [item["id"] for item in deck["slides"][0]["texts"]] == ["t1", "t2"]
    assert [item["id"] for item in candidate["slides"][0]["texts"]] == ["t2"]
    assert actions[0]["status"] == "applied"


def test_generic_repair_drops_only_co_located_singleton_and_duplicate():
    module = load_module()
    deck = {
        "slides": [
            {
                "slide_id": "S01",
                "texts": [
                    {"id": "a", "text": "A", "confidence": 0.9, "source_bbox": [10, 10, 10, 10], "layout_bbox": [0, 0, 80, 80]},
                    {"id": "b", "text": "识别", "confidence": 0.9, "source_bbox": [20, 20, 20, 20], "layout_bbox": [20, 20, 20, 20]},
                    {"id": "c", "text": "识别", "confidence": 0.2, "source_bbox": [20, 20, 20, 20], "layout_bbox": [20, 20, 20, 20]},
                ],
            }
        ]
    }
    candidate, actions = module.auto_repair_deck(deck, {"findings": []}, None)
    ids = [item["id"] for item in candidate["slides"][0]["texts"]]
    assert ids == ["b"]
    assert any(action["reason"] == "isolated-single-letter-artifact" for action in actions)
    assert any(action["reason"] == "co-located-duplicate-text" for action in actions)


def test_visual_regression_requires_all_metrics_and_all_slides(tmp_path: Path):
    module = load_module()
    baseline = tmp_path / "baseline"
    current = tmp_path / "current"
    for root, value in ((baseline, 1.0), (current, 1.0)):
        payload = {
            "mean_abs_diff_0_255": value,
            "rms_diff_0_255": value,
            "changed_pixel_fraction_threshold_32": 0.1,
            "changed_pixel_fraction_threshold_64": 0.05,
        }
        (root / "S01").mkdir(parents=True)
        (root / "S01" / "report.json").write_text(json.dumps(payload), encoding="utf-8")
    result = module.visual_regressions(current, baseline, ["S01", "S02"])
    assert result["status"] == "blocked"
    assert result["slides"][0]["status"] == "pass"
    assert result["slides"][1]["status"] == "blocked"


def test_jsonl_append_preserves_history(tmp_path: Path):
    module = load_module()
    path = tmp_path / "history.jsonl"
    module.append_jsonl(path, {"iteration_id": "one"})
    module.append_jsonl(path, {"iteration_id": "two"})
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["iteration_id"] for row in rows] == ["one", "two"]
