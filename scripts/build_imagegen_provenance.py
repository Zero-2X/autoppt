from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: build_imagegen_provenance.py SESSION_JSONL MASTERS_DIR OUTPUT_JSON", file=sys.stderr)
        return 2
    session, masters_dir, output = map(Path, sys.argv[1:])
    records = {}
    for line in session.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("payload", {}).get("item", {})
        if isinstance(item, dict) and item.get("kind") == "image_gen.generation" and item.get("result"):
            records[item.get("id")] = item
    # Map local master filenames to the exact generation call id retained in the rollout.
    ids = {
        "01_title.png": "exec-860ae3ca-2e85-4848-bba6-66d76544be7c",
        "02_problem_goal.png": "exec-c3fbc18a-bde0-4880-8de0-05345a09e4d1",
        "03_route.png": "exec-8ecb5df1-e66b-49f8-9234-7dae1d78cac0",
        "04_dataset.png": "exec-0a44ccf7-be11-48fd-a6fb-8edf0e11008b",
        "05_detection.png": "exec-05680c63-54d9-4b89-8735-51eea28eb70f",
        "06_tracking.png": "exec-adc5a7ac-897a-4ab7-b8dc-e216ae882224",
        "07_speed_ais.png": "exec-c7b5325e-a055-4818-89ca-862fb7b10809",
        "08_system.png": "exec-3a5e0ac2-bac4-4d06-84f4-c935207911c9",
        "09_monitoring.png": "exec-8c45b9b6-3188-409e-ad01-d9c89b1a6890",
        "10_results.png": "exec-ced7260b-7660-4e30-8f25-6f8e5cb7b037",
        "11_limits_outlook.png": "exec-d089753c-39d5-4c80-8a16-8e74056a65db",
    }
    slides = []
    for filename, generation_id in ids.items():
        path = masters_dir / filename
        item = records.get(generation_id)
        if not path.exists() or not item:
            raise FileNotFoundError(f"missing master or rollout record for {filename}: {generation_id}")
        data = path.read_bytes()
        slides.append({
            "slide_id": path.stem,
            "output": str(path.resolve()),
            "output_sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "id": generation_id,
            "imagegen_id": generation_id,
            "status": "generated",
            "backend": "builtin_image_gen",
            "provenance_kind": "builtin-imagegen",
            "generation_mode": "direct_final_slide_imagegen",
            "revised_prompt": item.get("revisedPrompt", ""),
        })
    result = {
        "schema_version": "builtin-imagegen-provenance-v1",
        "backend": "builtin_image_gen",
        "provenance_kind": "builtin-imagegen",
        "generation_mode": "direct_final_slide_imagegen",
        "session_jsonl": str(session.resolve()),
        "slides": slides,
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"slides": len(slides), "output": str(out.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
