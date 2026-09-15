from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "autopptskills" / "scripts" / "background_counterfactual_review.py"


def load_module():
    spec = importlib.util.spec_from_file_location("background_counterfactual_review", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generates_hash_bound_pending_review_views(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "background.png"
    image = Image.new("RGB", (160, 90), "#f5f8fa")
    draw = ImageDraw.Draw(image)
    draw.rectangle((25, 20, 130, 70), outline="#123456", width=2)
    image.save(source)

    report_path = module.generate_review_views(
        source,
        tmp_path / "review",
        grid_cols=2,
        grid_rows=1,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["verdict"] == "pending"
    assert report["manual_review"]["status"] == "pending"
    assert report["input_sha256"] == module.sha256_file(source)
    assert len(report["global_evidence"]) == 3
    assert len(report["grid"]["crops"]) == 2
    for item in report["global_evidence"]:
        assert (report_path.parent / item["file"]).is_file()
    highpass = Image.open(report_path.parent / "background-highpass-gain16.png")
    assert np.asarray(highpass).std() > 0


def test_refuses_nonempty_review_directory(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "background.png"
    Image.new("RGB", (16, 9), "white").save(source)
    out_dir = tmp_path / "review"
    out_dir.mkdir()
    (out_dir / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already contains files"):
        module.generate_review_views(source, out_dir)
