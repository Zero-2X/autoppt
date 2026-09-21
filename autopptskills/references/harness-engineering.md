# Harness Engineering For PPT Production

Use this workflow to turn PPT quality from a subjective final glance into a sequence of measurable gates. A later stage may start only after the previous gate passes.

## State Machine

```text
source evidence
  -> reviewed slide plan
  -> per-slide numeric/text whitelist
  -> ImageGen complete-page generation
  -> ImageGen-first provenance gate
  -> image-only PPTX
  -> semantic editable reconstruction
  -> PowerPoint render and structure audits
  -> targeted weak-slide iteration
  -> final delivery and lesson capture
```

The editable route never replaces the ImageGen route. It consumes a verified ImageGen full-slide master and reconstructs its semantics afterward.

## Gate 1: Source And Numeric Integrity

- Give every visible claim one or more `source_refs` or mark it as framing rather than a verified result.
- Build a numeric whitelist for result, comparison, product-interface, and evaluation slides. Only source-backed numbers may appear.
- Treat names, timestamps, vessel identifiers, coordinates, customer fields, interface values, awards, and evaluation scores as numbers/data for this gate.
- Reject generated pages that introduce plausible-looking operational data. Regenerate only the failed slide with a negative delta that names the invented field.
- Keep rejected variants with a rejection reason. Never silently overwrite the evidence history.

## Gate 2: ImageGen-First Provenance

Run after the image-only PPTX has been assembled and before any editable reconstruction:

```powershell
python autopptskills\scripts\verify_imagegen_first_gate.py <run-dir> --pptx <image-only.pptx> --report <run-dir>\qa\imagegen-first-gate-report.json
```

For built-in ImageGen runs, require the strongest evidence:

```powershell
python autopptskills\scripts\verify_imagegen_first_gate.py <run-dir> --pptx <image-only.pptx> --require-strong-ig-id --report <run-dir>\qa\imagegen-first-gate-report.json
```

Pass only when:

- every current `Sxx.png` hash matches accepted ImageGen provenance
- strong mode matches every hash to an `ig_...` generation ID when that
  legacy id is available; Codex hosts that expose `exec-...` use the validated
  built-in backend/provenance/mode/status record instead
- every prompt contracts for one complete final PPT page image
- every image-only PPT slide contains exactly one full-slide picture
- image-only PPT totals are zero text boxes and zero native shapes

The assembler is allowed to decode, copy, hash, resize for placement, and add one existing full-slide picture to a blank slide. It is not allowed to draw page content.

## Gate 3: Image Review And Local Regeneration

- Review source fidelity, unsupported claims, Chinese character quality, hierarchy, density, and style consistency.
- Regenerate one failed slide at a time unless the deck-wide style contract is wrong.
- Record the accepted variant and the rejected variant reason.
- Do not let a visually attractive slide pass if its source or numeric gate fails.

## Gate 4: Semantic Reconstruction

Route objects before composition:

- normal text -> native PowerPoint text box
- simple boxes, dividers, arrows, and connectors -> native PowerPoint shapes
- isolated flat line art -> bounded SVG candidate
- complex photos, interfaces, maps, and ImageGen illustrations -> bounded movable raster region

Keep `source_bbox` as the visual detection/provenance box. Use a separate `layout_bbox` when the final PowerPoint text frame must be wider for CJK anti-wrap or container alignment. Layout checks use `layout_bbox`; provenance and visual comparison continue to use `source_bbox`.

For every selected native line or connector, persist the exact cleanup mask and
measure source-color support before and after cleanup. A failed measurement is
an unresolved semantic-layer defect; do not count the connector as safely
separated merely because a native line object exists.

Do not use the untouched complete ImageGen page as a hidden semantic shortcut with duplicated native objects. One full-slide picture is allowed when it is a cleaned, explicitly named, non-semantic continuous background. The final editable PPTX must have zero semantic full-slide pictures and, by default, zero background tiles.

## Gate 5: Editable Output Thresholds

Default acceptance targets for a high-editability deck:

- exact manifest text coverage: 100%
- final-PPTX exact-text token coverage: 100%; calculate this from native PPTX text objects, not only from OCR/build match reports
- replacement/mojibake characters: 0
- normal text reconstructed as native text: 100% unless explicitly listed as stylized art text
- `semantic_full_slide_pictures`: 0
- `background_tile_pictures`: 0 for a normal gold release
- one continuous non-semantic background picture per slide is allowed
- editability grade: `editable`
- editability score: reported as a diagnostic target, not a hard fidelity gate
- native text coverage: 100%
- native shape coverage: 100% for routed simple geometry
- complex-raster exception ratio: explicitly reported and bounded; no unbounded semantic full-slide raster
- strict layout warnings/errors: 0
- overflow test: pass
- `[Sources]` notes: every slide

Report bounded raster regions separately. A complex screenshot or photo remaining as one movable crop is an intentional editability tier, not a native-vector claim.
- Treat pixel-anchored background tiles as a distinct high-fidelity layer role. They may preserve visual similarity without being semantically editable, but they must never be counted as a full-slide raster shortcut. Treat movable panel-content crops as disclosed complex-raster exceptions and score them separately from background coverage.
- The editability report must expose `native_text_coverage`, `native_shape_coverage`, `complex_raster_exception_ratio`, and `full_slide_raster_shortcut`; do not collapse these into a raw picture count.
- When reviewed text spans multiple glyph islands, record several cleanup boxes and one layout box. This preserves a single coherent editable object without erasing intervening artwork.
- Treat PowerPoint itself as a renderer under test. A reconstruction round is not accepted until the exact final PPTX opens in Microsoft PowerPoint and all slides export from that application; structural and non-Office previews remain supporting evidence only.
- If Office fails before opening a large deck, audit scratch-space pressure first and redirect `TEMP`/`TMP` to the project drive before diagnosing the PPTX as corrupt.
- Treat the official overflow detector as an environment-sensitive gate on Windows. Use `run_slides_test.ps1` so its Python runtime and JavaScript `@oai/artifact-tool` resolve from the same bundled Codex runtime, and accept only the explicit no-overflow pass message.

## Gate 6: Visual Quality

Render with Microsoft PowerPoint, then inspect every page at full size and as a montage. A gold release cannot substitute another renderer. Check:

- title wrapping and Chinese spacing
- text-to-text and text-to-image overlap
- image crop and aspect distortion
- hierarchy, information capacity, and adjacent-slide rhythm
- visual continuity from the accepted ImageGen master

Pixel identity is not the goal of semantic reconstruction. Large pixel differences are expected when text and geometry are reflowed into native objects. Judge fidelity from exact content coverage, recognizable visual system, preserved evidence relationships, and the absence of full-slide raster shortcuts.

Efficiency changes must preserve the same gates. Run the layout guard once for
the whole deck after confirming every source image uses the same canvas, and
parallelize only independent per-slide comparisons with 2-4 workers. If an
accepted baseline exists, fail the technical gate when any recorded visual
metric regresses, then still perform the required human/model visual review.

The release record must contain one explicit visual-review entry per slide. A
successful comparison command or generated heatmap proves only that comparison
artifacts exist; it is not the review decision.

### Visual residue sub-gate

Exact-text coverage is necessary but insufficient. A slide fails this sub-gate when any of the following appears in the PowerPoint render:

- an old ImageGen glyph remains underneath a native replacement
- a native replacement is duplicated, offset, or assigned to the wrong metric cell
- a percentage, decimal, identifier, or label wraps differently enough to change the visual reading
- a measured override is applied without masking the full antialiased source region

Use `mask_bbox` for the raster cleanup region and `layout_bbox` for the editable text frame. They are intentionally different. Set `replace_match: true` when a low-confidence OCR match must be removed before the reviewed measured text is inserted.

For oversized titles on light header bands directly above dark cards, automatic inpaint can pull dark pixels upward and create a false wedge behind the editable title. Treat this as a blocking visual-residue defect. Replace the title through a reviewed override with a tightly bounded light cleanup fill and a separately measured title `layout_bbox`, then rerender in PowerPoint.

### Numeric table sub-gate

For repeated experiment tables, cluster OCR numeric boxes into rows and columns. OCR provides geometry only. Resolve the displayed strings exclusively from the source-backed exact-text whitelist. Report every cell and whether its geometry was observed or inferred. A table can pass only when the rendered values, column positions, and decimal/percent punctuation agree with the ImageGen master.

## Iteration Ledger

For every round, record:

- weak slides and concrete failure modes
- changed prompt, crop, bbox, content, or object routing
- metrics before and after
- rejected variants
- remaining bounded raster exceptions

Prefer attributable local changes. Examples include widening a crowded timeline, moving a product screenshot below controls, restoring omitted evidence bands, or separating a dense closing page into claims and next steps. Re-run only the gates affected by the change, followed by the final full-deck gate set.

## Final Report

Summarize at least:

- ImageGen provenance coverage
- source/data fidelity
- exact text and Unicode integrity
- vectorization/editability effectiveness
- visual quality after reconstruction
- information capacity
- narrative coherence
- unresolved raster/vector exceptions
- visual residue and wrong-match defects found after the final PowerPoint render
- all-slide visual-review coverage and reviewer notes

Use measured audit values when available. Label visual scores as reviewed judgments and state their basis; do not present them as laboratory measurements.
