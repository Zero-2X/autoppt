# QA And Validation

Use this before claiming a deck or skill run is complete.

## Skill Package Validation

Run the official skill validator:

```powershell
python <skill-creator-root>\scripts\quick_validate.py autopptskills
```

Check that the skill contains no personal paths or fixed service endpoints:

```powershell
python autopptskills\scripts\validate_skill_portability.py autopptskills --json-out qa\skill-portability.json
```

Compile bundled Python scripts:

```powershell
Get-ChildItem autopptskills\scripts -Recurse -Filter *.py | ForEach-Object { python -m py_compile $_.FullName }
```

Run the style-contract tests whenever profiles or prompt builders change. They
must prove that only `academic_minimal` is intentionally minimal and that every
prompt contains design-density, design-completion, and bidirectional quality
guardrails.

## Full-Slide Imagegen Deck Gate

The generation backend is part of the gate, not an implementation detail. A
valid run must identify Codex built-in `image_gen` as the backend. Any
`OPENAI_API_KEY`, provider endpoint, proxy, `STAGE45_IMAGEGEN_CLI`,
`LOCAL_IMAGEGEN_COMMAND`, or alternate-provider marker is a hard failure.
When the built-in call is blocked, preserve the prompt/spec/manifest package
and report `blocked`; do not make a mock or locally drawn page look like a
real visual pass.

For editable reconstruction, the default QA gate also requires `background_tile_pictures == 0`. A tile count above zero is a failure unless the run explicitly records the legacy tiled compatibility mode.

Run the blocking provenance and structure gate after image-only assembly:

```powershell
python autopptskills\scripts\verify_imagegen_first_gate.py <run-dir> --pptx <image-only.pptx> --report <run-dir>\qa\imagegen-first-gate-report.json
```

When built-in ImageGen produced the pages, add `--require-strong-ig-id`. This
requires every current PNG hash to match an `ig_...` rollout record and the
manifest backend to be the built-in capability.

Verify:

- every final slide image was produced by imagegen before PPTX assembly
- no script-rendered page was substituted for imagegen output
- `image-prompts.json` exists.
- Every slide has `slide_id`, prompt text, exact text, and final image path.
- Prompt policy is `direct_final_slide_imagegen`.
- For an official-source-inspired profile, deck, top-level prompt manifest, and
  every slide must carry the same protected `style_reference`; the three
  official-source policy flags must be true.
- Every final image exists in `assets/slides/`.
- `deck-spec.json` exists.
- `deck.output_mode` is `imagegen_full_slide`.
- `deck.generation_mode` is `direct_final_slide_imagegen`.
- Every deck slide uses `layout: full_slide_image`.
- The PPTX exists.
- Build report exists.
- Visual QA or audit report lists no blocking issues.
- `imagegen-first-gate-report.json` has `verdict: pass`.
- `slides_verified`, `manifest_full_slide_contracts`, PPTX slide count, picture count, and full-slide picture count all equal the expected slide count.
- image-only PPTX `text_boxes` and `native_shapes` both equal zero.

Useful command:

```powershell
python autopptskills\scripts\build_competition_ppt.py <deck-spec.json> --output <out.pptx> --report <build-report.json>
```

If this command fails, its error is usually authoritative for assembly readiness.

Passing `build_competition_ppt.py` only proves assembly. Passing `verify_imagegen_first_gate.py` proves that the assembled current hashes have accepted ImageGen provenance and that scripts did not add slide content objects. Do not start editable reconstruction if the gate fails.

When an existing planning manifest predates the protected official-source
contract, create an isolated candidate instead of editing its accepted images
or provenance in place:

```powershell
python autopptskills\scripts\migrate_official_style_candidate.py <source-run> <candidate-dir> `
  --style-profile engineering_institutional_blue `
  --verified-identity-text "<exact source-verified institution line>"
```

The candidate must contain zero slide images and zero copied provenance
records. Its static report can validate deck/top-level/per-slide contract
consistency, but every page still requires fresh ImageGen generation before a
real ImageGen-first pass is possible.

## Stage9 Audit Gate

When using the copied Stage9 adapter, inspect:

```text
final/ppt/imagegen_prompts.json
final/ppt/images/
final/ppt/final_deck.pptx
final/ppt/ppt_audit.json
final/ppt/ppt_build_report.md
```

`ppt_audit.json` must pass for a completed handoff. If `mock_mode` is true, structural plumbing is proven but final visual quality is not.

## Image-To-Editable Gate

Verify:

- one run folder per task
- source images copied into the run folder
- verified imagegen full-slide master and its prompt manifest saved; `--allow-unverified-imagegen` is not used for final handoff
- `imagegen-assets-manifest.json` exists per slide
- the clean post-imagegen background and required vector/raster assets exist
- generated image layers have been normalized to the source canvas when dimensions differ
- every positioned text/icon/native shape has `source_bbox`; intentionally expanded or container-aligned text also has `layout_bbox`
- `layout_guard.py --strict` has no blocking placement issues
- `pptx_editability_audit.py` reports the expected editable text boxes and flags overuse of full-slide pictures
- audit output includes an editability grade, native/text/picture area signals, Unicode/CJK text evidence, and unresolved full-slide semantic layers
- preferred `compose_editable_pptx.mjs` generated the `.pptx` and wrote a compose report
- preview images exist
- `visual_compare_qa.py` produced side-by-side, overlay, heatmap, and report outputs
- CJK text is verified from the PPTX text/XML, not only from the PNG preview renderer
- final render uses PowerPoint when available; the rendering engine and font availability are recorded
- if PowerPoint COM is unavailable, preserve the exact HRESULT/session error in the QA record and label the final pixel gate blocked; do not infer PowerPoint visual success from a structural pass or an earlier round
- if Office cannot open a large media-heavy deck, record system-drive free space and retry with task-local `TEMP`/`TMP` on a drive with enough room before classifying the deck as invalid
- every glyph-cleanup override is visually checked for repair rectangles, smeared borders, erased icons, and chart damage; compact complex charts may remain bounded movable raster exceptions when native reconstruction would reduce fidelity
- every routed foreground object is also reviewed counterfactually by hiding or
  moving it; an object-shaped inpaint patch, shadow, gradient, or silhouette in
  the clean background is a blocking semantic-layer defect even when the normal
  composite render and original-color residual metric pass
- accidental text-to-text and text-to-image overlap is zero or explicitly waived in layout metadata
- `reconstruction-report.json` lists unresolved trace candidates and `embedded_text_candidates`; every rejected trace has a concrete reason
- normal text count, native shape/connector count, and convertible SVG count meet reviewed expectations
- replacement-character count is zero and CJK text exists in slide XML when Chinese text is expected
- the preceding ImageGen-first report passed; editable QA cannot retroactively repair a failed first-stage provenance gate
- new Gold visual review checks both `spectacle_control` and
  `design_completion`; clean-but-generic pages and decorative spectacle both
  fail
- when only selected slides change, `baseline-merge-report.json` proves every
  inherited and replaced asset hash

Validate background/frame/text/asset separation for new gold releases:

```powershell
python autopptskills\scripts\layer_contract_gate.py <run-dir>\deck-high-fidelity.json --pptx <run-dir>\out\editable.pptx --review <run-dir>\qa\layer-review.json --out <run-dir>\qa\layer-contract-report.json
```

The first run creates a pending review template when needed. Review every
PowerPoint-rendered slide and mark all checks pass only after confirming one
continuous background, no semantic text or duplicate frame lines in that
background, native simple frames, and correctly positioned bounded assets.

The layout guard accepts `pixel`, `pixels`, and `px` as equivalent units. It validates `x/y/w/h` against `layout_bbox` when present and otherwise against `source_bbox`.

Recommended final commands:

The reproducible final gate is:

```powershell
python autopptskills\scripts\final_visual_gate.py <source-run-dir> <run-dir>\deck-high-fidelity.json <run-dir>\out\editable.pptx --out-dir <run-dir>\qa\final-gate --compare-workers 4 --baseline-visual-dir <accepted-final-gate>\visual
```

It records layout, zero-background-tile editability, PowerPoint renderer status, exact Office errors, and per-slide visual comparison in `final-visual-gate.json`. A `blocked` verdict means the deck was not visually accepted; it must not be relabeled as a pass from structural evidence alone.

The baseline argument is optional when no accepted predecessor exists. When it
is supplied, every slide must have a readable baseline report and all four
diagnostic metrics (MAE, RMS, changed-pixel fractions at 32 and 64) must be no
worse. This is a regression veto, not a substitute for full-size visual review.

```powershell
python autopptskills\scripts\layout_guard.py <source.png> <run-dir>\deck.json --strict
autopptskills\scripts\render_pptx_powerpoint.ps1 -InputPptx <run-dir>\out\editable.pptx -OutputDirectory <run-dir>\preview
autopptskills\scripts\run_slides_test.ps1 -InputPptx <run-dir>\out\editable.pptx -OutputLog <run-dir>\qa\slides-test.txt -TempDirectory <run-dir>\qa\.slides-test-tmp
python autopptskills\scripts\pptx_editability_audit.py <run-dir>\out\editable.pptx --min-text-boxes <expected> --min-native-shapes <expected> --min-convertible-vectors <expected> --max-semantic-full-slide-pictures 0 --min-grade editable --json-out <run-dir>\qa\editability-report.json
python autopptskills\scripts\pptx_exact_text_audit.py <run-dir>\out\editable.pptx <run-dir>\image-prompts.json --json-out <run-dir>\qa\exact-text-pptx.json
python autopptskills\scripts\visual_compare_qa.py <source.png> <run-dir>\preview\slide-1.png --out-dir <run-dir>\qa\visual
```

The Windows wrapper is required when the official renderer would otherwise derive `@oai/artifact-tool` from a workspace-relative `HOME`. It must report `status: pass`; a zero process exit without the explicit `Test passed. No overflow detected.` message is not sufficient.

Do not report build-analysis match counts as final native-text coverage. `pptx_exact_text_audit.py` reads the final PPTX itself, tokenizes composite exact-text entries, and permits legitimate table/header/value and multi-text-box composition while still requiring every semantic and numeric token to exist as native PowerPoint text.

Visual-difference metrics are diagnostic, not automatic truth. Inspect `side_by_side.png` at full resolution for text wrapping, character spacing, icon deformation, inpaint residue, and connector direction before accepting the run.

## Gold Release Aggregation

`final_visual_gate.py` is the technical visual gate. It proves that strict
layout, editability, Microsoft PowerPoint export, and comparison generation ran
successfully for every slide. It does not replace the full-size visual review.

Create `visual-review.json` with one entry for every slide. If the file is
missing, `release_gate.py` creates a pending template and returns `blocked`.
After reviewing every PowerPoint-rendered page, record:

```json
{
  "schema_version": 3,
  "pptx": "<absolute-path-to-final.pptx>",
  "pptx_sha256": "...",
  "review_scope": "all_slides_full_size_and_montage",
  "design_quality_required": true,
  "institutional_identity_review_required": true,
  "slides": [
    {
      "slide_id": "S01",
      "status": "pass",
      "checks": {
        "text_residue": "pass",
        "wrapping_and_spacing": "pass",
        "color_and_emphasis": "pass",
        "icons_and_vectors": "pass",
        "crop_overlap_and_hierarchy": "pass",
        "spectacle_control": "pass",
        "design_completion": "pass",
        "institutional_identity_absence": "pass"
      },
      "notes": ""
    }
  ],
  "verdict": "pass"
}
```

`institutional_identity_absence` is required automatically when the bound
ImageGen-first report identifies an official-source-inspired profile. It means
that no emblem, seal, campus identity asset, copied master geometry, official
template claim, or unapproved institution name appears. A name explicitly
listed as verified exact identity text is ordinary content and does not fail
this check.

Aggregate the immutable release evidence:

```powershell
python autopptskills\scripts\release_gate.py <final.pptx> `
  --imagegen-first-report <qa\imagegen-first-gate-report.json> `
  --technical-gate-report <qa\final-gate\final-visual-gate.json> `
  --exact-text-report <qa\exact-text-report.json> `
  --overflow-report <qa\slides-test.txt> `
  --visual-review <qa\visual-review.json> `
  --layer-contract-report <qa\layer-contract-report.json> `
  --require-layer-contract `
  --require-design-quality `
  --icon-decisions <qa\icon-decisions.json> `
  --out <qa\release-report.json>
```

Omit `--icon-decisions` only when the run had no icon/vector candidates. A
release pass requires a readable PPTX ZIP, matching report paths and hash,
ImageGen-first pass, all technical gates, 100% exact-text coverage, the explicit
overflow pass message, and one reviewed pass per slide.

`--require-design-quality` preserves legacy reports when omitted. For every
new Gold release it is required: `spectacle_control` confirms that visual
effects remain evidence-serving, while `design_completion` confirms that the
selected profile is fully authored and not an unfinished generic scaffold.

Every `icon-decisions.json` mapping must include `source_bbox` and one of
`layout_bbox`, `deck_bbox`, or `final_bbox`. A rejected SVG must provide a
concrete rejection reason and an existing fallback asset. An accepted vector
must point to the final SVG/EMF asset and record a real PowerPoint visual result,
for example `"powerpoint_visual_review": "pass"`. Technical SVG validity alone
does not satisfy the release gate.

`--require-layer-contract` and `--require-design-quality` are the vNext gold
defaults. They remain flags rather than unconditional legacy requirements so
previously accepted releases remain auditable without rewriting their
historical evidence. New editable releases must provide a strict passing
layer-contract report and explicit spectacle-control/design-completion review.

## Failure Handling

- Built-in ImageGen blocked: report the exact blocker, leave prompts/specs and
  the manifest ready, then repair or retry the built-in route. Do not use an
  API key, proxy, CLI, local command, mock page, or another provider as a
  visual substitute.
- Missing image: generate or copy only that slide image, then rerun assembly.
- Bad generated text: reduce exact text, improve line breaks, and regenerate the whole page.
- Style drift: revise the style contract and regenerate affected slides.
- Overdecorated page: remove non-evidence effects while preserving the primary
  evidence anchor and profile identity, then regenerate only that page.
- Under-designed page: add source-backed evidence, annotation, comparison,
  mechanism, crop, or spatial relationships; do not add arbitrary decoration
  and do not force every profile into minimalism.
- Editable reconstruction mismatch: adjust `layout.json` first; regenerate image layers only when the layer content itself is wrong.
- Full-slide icon layer drift: switch to region assets or individual assets; do not keep retrying the same full-slide prompt.
- Oversized title cleanup bleed: when a light title band touches a dark card, replace automatic inpaint with a reviewed light fill scoped to the title glyph band and restore the title using a measured `layout_bbox`; verify in the PowerPoint render.
- Vector trace explosion: reduce the region, simplify colors/curves, or keep the item as a separate image asset; do not import thousands of meaningless paths.
- No usable vector paths: keep the original object in the imagegen-derived raster, record `no-vector-paths`, and do not claim vector editability.
- Text wrap mismatch: preserve the measured bbox, add explicit line breaks, then adjust font size/character spacing with shrink-to-fit enabled.
- Intentional CJK text-frame expansion: preserve the glyph `source_bbox`, record the final `layout_bbox`, and rerun strict layout validation.
- Full-deck regression after a local repair: merge only reviewed slide IDs from
  the patch round into the last accepted baseline with
  `merge_high_fidelity_round.py`, then rerun affected gates and the full
  release gate.
- Low-space Windows host: set `TEMP` and `TMP` to a project-local QA temp folder before rendering, and prefer `run_slides_test.ps1` so official-tool scratch files are isolated and removed after a pass.
