#!/usr/bin/env python3
"""Report local OCR, vectorization, segmentation, and PPTX backend readiness."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path


def _module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _pptxgenjs_candidates() -> list[Path]:
    candidates: list[Path] = []
    if os.environ.get("CODEX_PPTXGENJS"):
        candidates.append(Path(os.environ["CODEX_PPTXGENJS"]))
    for base in os.environ.get("NODE_PATH", "").split(os.pathsep):
        if base:
            candidates.append(Path(base) / "pptxgenjs")
            candidates.append(Path(base) / "pptxgenjs" / "dist" / "pptxgen.cjs.js")
    candidates.append(
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "node_modules"
        / "pptxgenjs"
    )
    return candidates


def _powerpoint_candidates() -> list[Path]:
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files"))]
    if os.environ.get("ProgramFiles(x86)"):
        roots.append(Path(os.environ["ProgramFiles(x86)"]))
    return [root / "Microsoft Office" / "root" / "Office16" / "POWERPNT.EXE" for root in roots]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out")
    args = parser.parse_args()

    modules = {
        "opencv": _module("cv2"),
        "scikit_image": _module("skimage"),
        "easyocr": _module("easyocr"),
        "pytesseract": _module("pytesseract"),
        "paddleocr": _module("paddleocr"),
        "doctr": _module("doctr"),
        "surya": _module("surya"),
        "vtracer": _module("vtracer"),
        "python_pptx_legacy": _module("pptx"),
    }
    binaries = {name: shutil.which(name) for name in ("tesseract", "potrace", "inkscape", "soffice")}
    pptxgen_candidates = _pptxgenjs_candidates()
    pptxgen = next((str(path) for path in pptxgen_candidates if path.exists()), None)
    powerpoint = next((str(path) for path in _powerpoint_candidates() if path.exists()), None)

    ocr_available = any(
        (modules["paddleocr"], modules["easyocr"], modules["doctr"], modules["surya"], bool(binaries["tesseract"]))
    )
    dedicated_vector_available = any(
        (modules["vtracer"], bool(binaries["potrace"]), bool(binaries["inkscape"]))
    )
    report = {
        "python": sys.executable,
        "modules": modules,
        "binaries": binaries,
        "pptxgenjs": pptxgen,
        "powerpoint_desktop": powerpoint,
        "routes": {
            "pptx_composer": "PptxGenJS" if pptxgen else "blocked",
            "final_renderer": "PowerPoint" if powerpoint else ("LibreOffice" if binaries["soffice"] else "artifact-tool"),
            "ocr": "available" if ocr_available else "manual-or-vision-assisted",
            "vector_trace": (
                "dedicated-tracer-available"
                if dedicated_vector_available
                else ("simple-contours-only" if modules["opencv"] else "native-shapes-or-movable-image")
            ),
            "segmentation": "chroma-key/alpha/connected-components",
        },
        "warnings": [],
    }
    if not pptxgen:
        report["warnings"].append("PptxGenJS missing: new editable composition route is blocked")
    if not ocr_available:
        report["warnings"].append("No OCR backend detected: corrected text layout must be supplied manually")
    if not modules["vtracer"] and not binaries["potrace"] and not binaries["inkscape"]:
        report["warnings"].append("No dedicated tracer detected: OpenCV is limited to simple contours")

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0 if pptxgen else 2


if __name__ == "__main__":
    raise SystemExit(main())
