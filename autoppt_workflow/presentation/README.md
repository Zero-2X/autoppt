# Presentation Orchestrator

This package adds a source-grounded presentation layer around the existing
PPT/ImageGen assembly pipeline. It does not replace the ImageGen runner or the
PowerPoint builders.

The stable route is:

```text
source files -> normalized evidence -> profile -> deck plan -> Slide IR
-> per-slide full-page ImageGen prompt -> image-only PPTX
-> semantic reconstruction -> PowerPoint render -> seven gates
```

`fullpage_imagegen_reconstruct` is always recorded as the default route. The
builtin-imagegen-only policy disables native-only generation and any silent
substitution of native PowerPoint drawing for the first-stage full-page visual.

The backend boundary is strict: presentation images come only from Codex's
built-in `image_gen` capability. This package never reads an ImageGen API key,
provider endpoint, proxy, provider SDK, ImageGen CLI, or local image command.
Mock pages are structural regression artifacts only. If a built-in call is
blocked, preserve the prompt/spec/manifest package and repair or retry that
same route; do not substitute another generator or promote mock output.

## Profiles

The profile registry includes:

- `innovation_competition_defense`
- `thesis_defense`
- `nsfc_application_defense`
- `nsfc_conclusion_defense`
- `academic_paper_report`
- `research_progress_report`

Each profile locks narrative order, focus, forbidden claims, style mapping,
page range, duration defaults, and no-animation behavior.

## Package artifacts

The PPT adapter writes these under `final/ppt/`:

```text
presentation_profile.json
source_manifest.json
figure_source_manifest.json
evidence_ledger.json
paper_analysis.json
requirement_matrix.json
deck_plan.md
deck_plan.json
slide_ir.json
design_spec.json
design_spec.md
spec_lock.json
source_map.md
imagegen_manifest.json
reconstruction/editability_manifest.json
validation/*.json
speaker_notes/*.md
```

Per-slide reconstruction runs additionally emit `component_manifest.json`.
This is the hybrid Object Router contract: Slide Manifest text is authoritative
for `native_text`, measured simple geometry routes to native shapes/connectors,
and complex visuals remain `svg_group` or `raster_asset`. It does not replace
the ImageGen-first provenance gate or the existing release gates.

The files are additive and safe to create on resume. Existing presentation handoff workbook,
PDF, `imagegen_prompts.json`, `images/`, `final_deck.pptx`, and `ppt_audit.json`
remain available under their original paths.

## Local recovery

`regenerate_ppt_slide()` regenerates one slide asset and writes a
`single_slide_regeneration_manifest.json`. It preserves the accepted deck and
marks that a reviewed merge/release round is still required.

Evidence changes can be mapped to affected pages with
`find_affected_slides()`. Speaker notes and anticipated questions are generated
without regenerating slide images.

## Persistent quality iteration

The optional post-generation quality loop is:

```text
PPTX -> inspect -> record findings -> local repair candidate ->
PowerPoint render -> independent gates -> visual regression check ->
accept/reject -> append project history and reusable lessons
```

Run it explicitly with:

```powershell
python autoppt_workflow/scripts/iterate_presentation_quality.py `
  --pptx <exact-delivery.pptx> --auto-repair --max-iterations 3
```

Or append `--iterate-quality --quality-auto-repair` to
`run_presentation_workflow.py`. Every round is written under
`final/ppt/reconstruction/quality_iterations/`; the project ledger is
`final/ppt/iteration_history.jsonl` and the cross-project lesson ledger is
`improvement/ppt-improvement-ledger.jsonl` and `improvement/style-handbook.md`.

If a candidate passes the iterator's non-regression policy, it can be copied
to a new delivery filename with `--promote-accepted-to <new.pptx>` (or
`--quality-promote-to` on the workflow wrapper). Promotion never overwrites
the input baseline.

The iterator never overwrites the accepted deck. A candidate is rejected when
composition, PowerPoint rendering, layout, or any slide-level visual metric
regresses. Human visual review and the semantic layer contract remain explicit
gates and cannot be auto-promoted by a numeric score.

## Image-level text fidelity loop

For every continuation round, the iterator must compare the exact PowerPoint
render with the source slide image at page level and at text-object level. The
text report records `source_bbox` (observed glyphs), `layout_bbox` (the native
PowerPoint frame), `render_bbox` (the rendered glyph region), declared font,
font size, weight, alignment, line count, color, local pixel difference,
position delta, size delta, and frame expansion ratio. A wide OCR container is
not accepted merely because its declared font size is correct.

The repair order is deliberately conservative:

```text
source glyph measurement -> reviewed text split/replace -> explicit bbox and
line-break repair -> compose -> Microsoft PowerPoint render -> per-slide
source/render/diff review -> text-fidelity report -> regression decision
```

Reviewed plans use `mode: explicit-only` when broad OCR-box shrinking could
change wrapping. Generic repairs remain available for low-risk singleton and
co-located duplicate cleanup, but they must not replace a reviewed
`layout_bbox`. Candidates are retained in a new iteration directory and are
promoted only when PowerPoint rendering, page-level visual metrics, exact text,
layout, and text-fidelity deltas do not regress the accepted baseline.

The text-fidelity report is diagnostic evidence, not a standalone acceptance
score. Each slide still requires source/render side-by-side inspection,
especially for CJK wrapping, duplicate glyph residue, text-to-image overlap,
font substitution, and antialiased cleanup damage.
