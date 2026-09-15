import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "autopptskills" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from component_manifest import build_component_manifest  # noqa: E402
from component_manifest_qa import validate  # noqa: E402


def test_component_manifest_routes_content_from_slide_manifest():
    analysis = {
        "size": {"width": 1000, "height": 562},
        "texts": [{"id": "text-1", "text": "开放词汇目标检测", "bbox": [100, 50, 300, 40], "confidence": 0.9}],
        "shapes": [{"id": "shape-1", "type": "rounded_rect", "bbox": [90, 130, 400, 200]}],
        "lines": [],
        "icon_candidates": [],
    }
    manifest = {"slide_id": "S07", "title": "开放词汇目标检测"}
    result = build_component_manifest(analysis, slide_id="S07", slide_manifest=manifest)
    text = next(item for item in result["objects"] if item["render_type"] == "native_text")
    assert text["content_id"] == "S07.title"
    assert text["editable"] is True
    assert result["coordinate_system"]["type"] == "normalized"
    assert validate(result)["verdict"] == "pass"
