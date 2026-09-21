# Image To Editable PPTX Workflow

Apply the reconstruction and visual acceptance prompts in
[approved-style-contract.md](approved-style-contract.md). Freeze the accepted
ImageGen master and reproduce its text appearance, wrapping, position, color,
red emphasis, geometry, cropping and stacking without redesign. Ordinary text
and simple shapes remain native; complex scientific imagery may stay bounded
raster. Visible mismatch blocks release. Pixel equality is a measured claim,
not an advance guarantee; record unresolved font/renderer limitations.

For a reviewed measured plan, use
[measured-reconstruction.md](measured-reconstruction.md). It documents the
deterministic native-text/native-geometry composer, bounded icon tracing, asset
hashes, and the distinction between a native solid-color background and a
non-semantic raster background.

Use this when the input is one or more slide screenshots/images and the output must be editable `.pptx`.

## Editability Contract

The default reconstruction background policy is one continuous full-slide clean background. The legacy `pixel-anchored-background-tile` route is compatibility-only and must be explicitly requested; it is not acceptable for a normal final editable deliverable.

Reconstruct each slide by editability tier. Do not stop at one transparent picture layer when the user asked for editable PPTX.

1. Clean background image: only non-semantic paper/grid/ambient texture. One full-slide background picture is acceptable; a native flat `background_color` is also a continuous background and is preferred when it is sufficient.
2. Native PowerPoint shapes: simple card frames, rounded rectangles, straight lines, arrows, circles, dots, dividers, simple timelines, and basic flowchart boxes when editability matters.
3. Editable text boxes: all normal text, including titles, section labels, axis labels when readable, table labels when practical.
4. Raster artwork: complex illustrations, maps, robots, drones, product photos, ornate decorations, and stylized art text that cannot be faithfully represented as normal text. Keep it in the clean imagegen-derived background or split it into movable assets when isolation is reliable.

Art text, gradient lettering, brush lettering, badge text, and highly stylized title marks belong in the icon/decorative image layer, not the editable text layer.

Default target for editable PPTX:

- 100% normal text as PowerPoint text boxes.
- 80%+ simple geometric structure as native `shapes[]` when it can be measured.
- Complex artwork split into region or element image assets, not one full-slide picture, unless the user accepts a low-editability draft.
- `editable` means native text/shapes; SVG is `convertible-vector`; separate PNG assets are `movable-image`. Report these levels separately.

## Hard Rules

- Process slides one at a time in a unique run folder.
- Use the current source image as the only edit target for background/frame/icon imagegen work.
- A final reconstruction must start from an imagegen full-slide master with manifest evidence. For a non-imagegen screenshot, first recreate the complete page with imagegen; `--allow-unverified-imagegen` is analysis-only.
- Require a passing `imagegen-first-gate-report.json` before final editable reconstruction. Editable objects created later do not prove that the first-stage master came from ImageGen.
- Do not use the original screenshot as a full-slide background with duplicated text. A full-slide background is acceptable only after the selected editable foreground objects have been removed from the verified ImageGen master.
- Do not crop semantic assets from an unverified screenshot. Bounded crops from the verified ImageGen master are allowed as documented post-ImageGen derivatives when the source bbox, cleanup mask, alpha edge, final bbox, and asset hash are recorded.
- Do not use PPT shapes, PIL, SVG, HTML, Canvas, matplotlib, or screenshot rendering to fake imagegen-generated artwork. Native PPT shapes are allowed only for simple editable geometry measured from the source image, such as boxes, lines, arrows, dots, and connectors.
- Background, frame, and icon/decorative layers must either be direct imagegen outputs or documented post-imagegen derivatives in `imagegen-assets-manifest.json`.
- After imagegen, inspect every generated layer's dimensions. If any layer differs from the source image dimensions or aspect ratio, normalize the whole generated layer to the source canvas before chroma-key removal or PPTX composition. Whole-layer resize/crop is allowed for alignment; local cropping from the original source image is not.
- Include `source_bbox` for every positioned icon and text item. When the PowerPoint text frame is intentionally wider than the detected glyphs, also include `layout_bbox`; otherwise placement cannot be audited without confusing semantic bounds and anti-wrap bounds.
- If a full-slide icon layer drifts or overlaps text, do not keep prompting the same full-slide layer. Switch to region assets or individual assets and place them with measured bboxes.
- Keep title bands empty in region imagegen prompts; put text back as editable text boxes above the asset layer.
- Do not auto-vectorize the complete slide. Trace only isolated line-art elements after text and geometry have been removed from the raster target.
- Never use hidden, transparent, off-canvas, tiny, or 1pt proxy text to make a
  raster page appear editable; all visible ordinary text must be a native,
  in-bounds PowerPoint text object.
- Use `fit: shrink`, explicit line breaks, and measured `char_spacing` for reconstructed text. A visually similar font size is not enough if PowerPoint wraps the title differently.
- Each selected native line/connector must be removed from the clean background
  with a saved per-object mask. Record source color support, post-cleanup
  support, and residual ratio; failed or unmeasurable cleanup stays unresolved.
- Preserve stylized 3D/brush/gradient title art as raster and list it under `embedded_text_candidates`. Keep incidental text inside product photos, monitors, labels, or dense illustrations in the raster artwork unless the object itself is being rebuilt.
- Rejected icon traces must remain visually present and be listed under `unresolved` with a concrete reason such as `photo-like-complexity`, `too-many-colors`, `no-vector-paths`, `path-count>N`, or `powerpoint-contour-breakage`. Preserve them in the continuous background or isolate them as measured movable transparent PNG assets when extraction is clean.

## Suggested Run Folder

```text
image2pptx_runs/<timestamp>_<slug>/
  source/
  slide-01/
    prompts/
    background.png
    frame_raw.png
    frame.png
    regions/
      left-top_raw.png
      left-top.png
    icons/
    imagegen-assets-manifest.json
    layout.json
  deck.json
  out/editable.pptx
  preview/
  qa/
```

## Preferred Automated Workflow

1. Verify the image-only master deck and provenance:

```powershell
python autopptskills\scripts\verify_imagegen_first_gate.py <run-dir> --pptx <image-only.pptx> --report <run-dir>\qa\imagegen-first-gate-report.json
```

2. Verify OCR, OpenCV, SVG, Node/PptxGenJS, and PowerPoint capabilities:

```powershell
python autopptskills\scripts\check_editable_backends.py --json-out <run-dir>\qa\method-capabilities.json
```

3. Reconstruct the verified imagegen master. This performs OCR, manifest text reconciliation, semantic routing, foreground-only inpainting, native geometry detection, bounded icon tracing, composition, and reporting:

```powershell
python autopptskills\scripts\reconstruct_imagegen_slide.py <slide.png> <run-dir> --imagegen-manifest <image-prompts.json> --force-16x9
```

4. Inspect:
   - `analysis/analysis.json`
   - `analysis/detection-overlay.png`
   - `qa/reconstruction-report.json`
   - `out/editable.pptx`

5. Correct OCR/routing with a reviewed override file. Supported top-level
fields include `drop_ids`, `replace_text`, `text_updates`, `add_texts`,
`add_shapes`, `add_lines`, `add_icon_candidates`, `cleanup_regions`,
`panel_exclusions`, and `native_shapes`. Reviewed cleanup modes are
normalized through one classifier so text cleanup and standalone residue
cleanup cannot silently take different routes.

```json
{
  "drop_ids": ["line-017"],
  "replace_text": {"text-008": "医院/疾控仓库"},
  "text_updates": {
    "text-013": {
      "text": "社区/定点接收",
      "needs_review": false,
      "verified_by": "visual-review"
    }
  }
}
```

6. Rerun from the reviewed analysis so OCR/detection is deterministic:

```powershell
python autopptskills\scripts\reconstruct_imagegen_slide.py <slide.png> <run-dir> --imagegen-manifest <image-prompts.json> --analysis-json <run-dir>\analysis\analysis.json --overrides <review.json> --force-16x9
```

7. When only a few slides improved, create the next round from the last accepted
baseline and replace only the reviewed slide IDs:

```powershell
python autopptskills\scripts\merge_high_fidelity_round.py <accepted-deck.json> <patch-deck.json> --slides S03,S04 --out-dir <next-round>
```

The merge report hashes every inherited and replaced slide asset. Never rebuild
or overwrite the accepted round merely to repair one local page.

8. If the reviewed plan is measurement-led, compose it with
   `compose_measured_reconstruction.py` and retain `asset-provenance.json` and
   `native-traces.json`. Then run strict layout, PowerPoint rendering, editability audit, exact-text audit,
overflow detection, and visual comparison:

```powershell
python autopptskills\scripts\layout_guard.py <slide.png> <run-dir>\deck.json --strict
autopptskills\scripts\render_pptx_powerpoint.ps1 -InputPptx <run-dir>\out\editable.pptx -OutputDirectory <run-dir>\preview
python autopptskills\scripts\pptx_editability_audit.py <run-dir>\out\editable.pptx --min-text-boxes <expected> --min-native-shapes <expected> --min-convertible-vectors <expected> --max-semantic-full-slide-pictures 0 --min-grade editable --json-out <run-dir>\qa\editability-report.json
python autopptskills\scripts\pptx_exact_text_audit.py <run-dir>\out\editable.pptx <image-prompts.json> --json-out <run-dir>\qa\exact-text-report.json
autopptskills\scripts\run_slides_test.ps1 -InputPptx <run-dir>\out\editable.pptx -OutputLog <run-dir>\qa\slides-test.txt -TempDirectory <run-dir>\qa\.slides-test-tmp
python autopptskills\scripts\visual_compare_qa.py <slide.png> <run-dir>\preview\slide-1.png --out-dir <run-dir>\qa\visual
```

For a full deck, `final_visual_gate.py` performs one deck-wide layout check and
runs 2-4 per-slide comparisons in parallel. When a prior round is the accepted
floor, add `--baseline-visual-dir <accepted-final-gate>\visual`; missing evidence
blocks the gate and any worsened MAE, RMS, or changed-pixel fraction fails it.

Use the manual chroma-key/region workflow only when the automated decomposition cannot isolate a required complex object cleanly. Use `compose_editable_pptx.py` only for legacy compatibility.

## Text And Character Layout Rules

- Do text extraction before image layer generation so prompts can reserve text-free bands.
- Use measured `source_bbox` for the original visible glyphs and `layout_bbox` for the final PowerPoint frame when anti-wrap expansion or container alignment is intentional. Do not overwrite one with the other.
- Set text box margins to 0 unless a measured inset is intentional.
- Use explicit `size` in points for large titles. Use `size_px` or `size_ratio` only when the source measurement is reliable.
- Use explicit line breaks. Do not depend on PowerPoint's automatic wrapping to reproduce a reference layout.
- Default `fit` to `shrink`, not `resize`; resizing the box changes measured placement.
- Use `char_spacing` only after visual measurement. Do not fake tracking by inserting spaces between Chinese characters.
- Give each text object a semantic `name` so it is identifiable in PowerPoint's Selection Pane and in QA reports.
- Verify the PPTX XML/text via `pptx_editability_audit.py`; the bundled PNG preview may fail to render CJK fonts correctly.
- If the preview renderer shows Chinese as boxes or bars but the PPTX audit shows correct Unicode text, treat the PNG preview as a renderer limitation and verify in PowerPoint or by XML/text extraction.

## Native Shape Schema

Use `shapes[]` for simple editable geometry:

```json
{
  "shapes": [
    {
      "type": "rounded_rect",
      "x": 0.04,
      "y": 0.17,
      "w": 0.21,
      "h": 0.24,
      "source_bbox": [88, 211, 464, 298],
      "fill": "#FFFFFF",
      "opacity": 0.0,
      "line": "#0B5A45",
      "line_width": 1.5
    },
    {
      "type": "line",
      "x": 0.25,
      "y": 0.29,
      "w": 0.06,
      "h": 0.0,
      "source_bbox": [552, 361, 132, 0],
      "line": "#C95D16",
      "line_width": 1.2
    }
  ]
}
```

Supported shape types include `rect`, `rounded_rect`, `oval`, `line`, `right_arrow`, `left_arrow`, `up_arrow`, `down_arrow`, `triangle`, `diamond`, `hexagon`, and related simple PowerPoint shapes.

## Minimal Layout Shape

Use source image pixel coordinates or fractions consistently. Prefer keeping page assets in the same slide folder and omit `assets_dir` when possible.

```json
{
  "size": {"width": 1280, "height": 720},
  "slides": [
    {
      "background": "slide-01/background.png",
      "frame": "slide-01/frame.png",
      "texts": [
        {
          "text": "Editable title",
          "x": 0.08,
          "y": 0.08,
          "w": 0.6,
          "h": 0.12,
          "source_bbox": [164, 92, 1229, 138],
          "layout_bbox": [130, 92, 1297, 138],
          "font_size": 32,
          "font": "Microsoft YaHei",
          "color": "#111827",
          "bold": true
        }
      ],
      "icons": [
        {
          "file": "slide-01/icons/icon_001.png",
          "x": 0.72,
          "y": 0.24,
          "w": 0.12,
          "h": 0.12,
          "source_bbox": [1475, 276, 246, 138]
        }
      ]
    }
  ]
}
```

## Completion Gate

- Each slide has `imagegen-assets-manifest.json`.
- Background, frame, and icon/decorative layers have real imagegen source evidence.
- Text is editable where normal text can be faithfully represented.
- Simple frames/connectors are native shapes when high editability is requested.
- Stylized art text and incidental text inside complex artwork are listed under `embedded_text_candidates`; these are explicit raster exceptions, not silent failures.
- The only normal full-slide picture is the continuous non-semantic background; semantic full-slide shortcuts and background tiles are zero.
- Every rejected vector candidate has a concrete reason and remains visually present either in the clean background or as a separately movable raster fallback.
- `pptx_editability_audit.py` reports the expected text count and flags full-slide picture overuse.
- The audit grade is `editable` or an explicitly accepted `mixed`; never hand off `visual-only` as editable.
- The editability score is an object-structure metric, not a claim that every pixel is editable. Read it together with `reconstruction-report.json` unresolved and embedded lists.
- PowerPoint preview and comparison artifacts exist for every slide, and every slide has an explicit visual-review decision.
- The visual review checks both spectacle control and design completion. A
  non-minimal slide must retain the ImageGen master's evidence anchor,
  hierarchy, reading path, scale contrast, and intended richness; a minimal
  slide must retain deliberate negative space rather than accidental emptiness.
- A local repair inherits every unaffected slide and asset from the last
  accepted baseline, with the merge report proving which slide IDs changed.
- The final `.pptx` opens and contains the expected slide count.
