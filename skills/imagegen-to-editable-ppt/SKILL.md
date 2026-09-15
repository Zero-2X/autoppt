---
name: imagegen-to-editable-ppt
description: Reconstruct verified ImageGen full-slide masters into semantically editable PPTX files using reviewed Slide Manifest content, Component Manifest routing, native text and simple geometry, bounded SVG/raster assets, and real PowerPoint QA. Use when visual masters already exist and editability is the requested next stage. Do not use it for source analysis, narrative planning, first-stage slide generation, or full-page screenshot/SVG delivery.
---

# ImageGen-to-editable PPTX reconstruction

Use this skill only as the post-generation reconstruction plugin for
`autopptskills/SKILL.md`. It consumes reviewed source truth and verified
full-slide ImageGen masters; it does not create a second presentation workflow.

## Input contract

Do not start reconstruction until these inputs exist:

- verified full-slide ImageGen PNG for every slide being reconstructed;
- ImageGen manifest with current file hashes and built-in `ig_...` provenance;
- reviewed Slide Manifest or equivalent exact-text/numeric whitelist;
- slide dimensions and stable slide IDs;
- requested delivery tier: editable draft or Gold editable release.

If a source image is not a verified ImageGen master, it may be analyzed as a
reference, but a Gold deliverable must recreate and verify the master through
the built-in ImageGen route first.

## Truth and visual precedence

```text
Slide Manifest (wording, numbers, formulas, identifiers)
  > reviewed source text
  > OCR (geometry and reading-order proposal only)

verified ImageGen PNG (visual master)
  -> component-manifest-v1
  -> native_text / native_shape / native_connector / svg_group / raster_asset
  -> editable PPTX
  -> real PowerPoint render and release evidence
```

Never use OCR to rewrite reviewed semantic content. Never describe a full-page
screenshot, `full.svg`, movable PNG, or imported SVG as fully native.

## Reconstruction workflow

1. Preflight OCR, PowerPoint, Node/PptxGenJS, vector/raster tools, disk space,
   and task-local temporary directories.
2. Detect candidate text, shapes, connectors, panels, icons, illustrations, and
   background regions without changing source truth.
3. Build `component_manifest.json`; assign stable IDs, `content_id`, semantic
   type, normalized bbox, z-order, render type, editability, confidence, and
   provenance.
4. Route each object using the table below. Preserve `source_bbox`, cleanup
   mask, and `layout_bbox` as separate geometries.
5. Remove routed foreground pixels from one continuous clean background. Hide
   each foreground object during review to detect duplicate text, frame ghosts,
   object-shaped patches, or residue.
6. Compose the editable PPTX, render the exact file with Microsoft PowerPoint,
   compare every slide with its verified master, repair local defects, and run
   the required release gates.

## Object router

| Object | Route | Acceptance condition |
| --- | --- | --- |
| Normal title/body/label/table text | `native_text` | Exact reviewed wording and final-PPTX text audit pass |
| Simple card/frame/divider | `native_shape` | Geometry and style match at slide scale; source pixels removed cleanly |
| Arrow or connection | `native_connector` | Direction, endpoints, weight, and cleanup evidence pass |
| Flat isolated line art | `svg_group` candidate | Bounded complexity and exact PowerPoint visual review pass |
| Complex figure/photo/interface/chart art | `raster_asset` | Bounded, movable, correctly cropped, and explicitly disclosed |
| Ambient paper/grid/texture | continuous background | One non-semantic full-slide image, zero tiles, zero semantic residue |

Use a native frame around bounded raster panel content when the frame is simple
geometry. Never keep a semantic frame only in the background.

## Component Manifest v1 contract

Every object records at least:

```text
id, semantic_type, parent_id, bbox, z_index, content_id,
render_type, style, editable, confidence, provenance
```

For semantic text, `content_id` must resolve to the Slide Manifest. Missing
`content_id` makes the object draft/warn evidence and blocks a Gold release.
Every rejected SVG candidate must include a concrete reason, source bbox, final
bbox, and existing fallback asset.

## Core commands

```powershell
python autopptskills/scripts/check_editable_backends.py `
  --json-out <run-dir>/qa/method-capabilities.json

python autopptskills/scripts/reconstruct_imagegen_slide.py `
  <reference.png> <run-dir> `
  --imagegen-manifest <imagegen-manifest.json> `
  --slide-manifest <slide-manifest.json> `
  --force-16x9

python autopptskills/scripts/component_manifest_qa.py `
  <run-dir>/component_manifest.json `
  --json-out <run-dir>/qa/component-manifest-qa.json

python autopptskills/scripts/layer_contract_gate.py `
  <run-dir>/deck-high-fidelity.json `
  --pptx <run-dir>/out/editable.pptx `
  --review <run-dir>/qa/layer-review.json `
  --out <run-dir>/qa/layer-contract-report.json
```

Review `analysis/detection-overlay.png`, `qa/reconstruction-report.json`, the
PowerPoint previews, and every slide comparison. Apply measured overrides and
rerun from saved analysis so repairs remain attributable and deterministic.

## Output contract

An editable reconstruction should preserve:

- `component_manifest.json` and its QA report;
- `deck.json` or `deck-high-fidelity.json`;
- one clean `background.png` per slide;
- bounded local assets and recorded routing decisions;
- composed `editable.pptx` and compose report;
- editability, exact-text, layer-contract, overflow, PowerPoint-render, and
  visual-comparison evidence appropriate to the requested tier.

For Gold delivery, continue through `final_visual_gate.py` and
`release_gate.py` with the main skill's layer-contract and design-quality
requirements. Structural composition alone is not completion.

## Failure and fallback rules

- Missing or mismatched provenance: stop and repair the ImageGen-first evidence.
- Bad wording or numbers: repair the Slide Manifest; do not accept OCR output.
- Cleanup halo, duplicate text, or frame ghost: tighten the local mask and
  counterfactually review the clean background.
- SVG fades, breaks, fills, or moves in PowerPoint: fall back to bounded PNG and
  record the visual rejection.
- Complex semantic content cannot be reconstructed faithfully: keep a bounded
  movable asset and disclose its editability level.
- PowerPoint COM or visual review is unavailable: preserve artifacts and report
  `blocked` for Gold delivery.

Read `autopptskills/references/image-to-editable-pptx.md` for schemas,
`autopptskills/references/method-selection.md` for routing details, and
`autopptskills/references/qa-and-validation.md` for the full release gates.
