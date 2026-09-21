# Gold-standard PPT workflow architecture

This is the canonical architecture for the highest-quality route. It is derived
from repeated full-slide ImageGen decks and multi-round editable reconstruction,
not from a single presentation.

## Quality precedence

When two goals conflict, use this order:

1. source and numeric truth
2. quality of the accepted ImageGen visual master
3. visual fidelity of the exact final PowerPoint render
4. profile-appropriate design completion and audience readability
5. semantic editability of normal text and simple geometry
6. path-level vector depth

This ordering is deliberate. A clean transparent PNG that matches the visual
master is better than a nominal SVG that renders with broken or faint contours.
The fallback must be disclosed, but fidelity is not sacrificed to inflate a
vector count.

## End-to-end state machine

```text
0. environment and backend preflight
   -> 1. source evidence, exact text, numeric whitelist
   -> 2. narrative, page archetypes, evidence-led style-profile lock
   -> 3. one complete-page ImageGen prompt and image per slide
   -> 4. image-only PPTX and strong provenance gate
   -> 5. semantic decomposition and reviewed object routing
   -> 6. editable composition with one continuous clean background
   -> 7. technical gate: ZIP, layout, overflow, editability, exact text,
      Microsoft PowerPoint export, per-slide comparison artifacts
   -> 8. full-size human/model visual review of every slide
   -> 9. gold release aggregation, immutable output, and lesson capture
```

A later stage may start only when the previous blocking gate passes. Mock images,
non-Office previews, and structural audits are useful diagnostics but cannot
replace the corresponding real gate.

## Stage 0: preflight

- Inspect source files and current workspace state before generating.
- Check Codex built-in ImageGen readiness before a long batch. API-key,
  provider-CLI, proxy, and local-command routes are prohibited; a blocked
  built-in call must be repaired or retried in place.
- Check OCR, Node/PptxGenJS, vector, and PowerPoint capability before editable
  reconstruction.
- On Windows, record system-drive free space and choose a task-local
  `TEMP`/`TMP` directory on a drive with adequate space.
- Preserve prior accepted rounds. New work writes a new round.

## Stages 1-3: content and visual master

- Every visible factual claim has source references or is explicitly framing.
- Every number, date, identifier, score, coordinate, interface field, and table
  value comes from a reviewed whitelist.
- Select a stable profile from `references/style-system.md`; the general
  default is `academic_light`. `academic_minimal` is the only intentionally
  low-density profile.
- Lock `intentional_minimal`, `design_density`,
  `design_completion`, and `quality_guardrails` before generating.
- Give each page one conclusion and make the title state it when possible.
- Adjacent slides vary their silhouette; do not repeat a dashboard grid on every
  page.
- Each prompt is self-contained and requests one finished slide page, including
  exact short text, layout blueprint, evidence boundaries, negative constraints,
  design-completion requirements, and acceptance criteria.
- Apply a bidirectional style gate. Reject non-evidence spectacle, and also
  reject an unfinished title-plus-card scaffold, generic icon grid, timid scale,
  accidental whitespace, or a non-minimal page without a primary evidence
  anchor and reading path.
- Regenerate only failed pages unless the style contract itself failed.

## Stage 4: ImageGen-first gate

The image-only deck proves the visual master before editability work. It must
come from the built-in ImageGen capability:

- every current slide image hash has accepted ImageGen provenance;
- built-in ImageGen runs use strong `ig_...` evidence when exposed by the host,
  or a validated Codex `exec-...` host record with independent built-in fields;
- the generation manifest identifies the built-in backend and contains no
  provider/API-key/CLI fallback marker;
- every manifest entry contracts for a complete final page;
- every image-only slide contains exactly one full-slide picture;
- image-only slides contain zero script-added text boxes and native shapes.

Editable reconstruction cannot retroactively repair a failed provenance gate.

## Stages 5-6: semantic reconstruction

Route every object before composition:

| Object | Route |
| --- | --- |
| normal title/body/table label | native text |
| simple frame/divider/arrow/node | native shape or connector |
| isolated flat line icon | bounded SVG candidate |
| complex illustration/interface/photo | bounded movable raster |
| quiet paper/grid/ambient field | one continuous clean background |

### Background rule

One full-slide picture is acceptable when it is explicitly named and audited as
the non-semantic continuous background. The failure condition is a semantic
full-slide shortcut or a background split into many tiles. Therefore:

- `background_pictures == slide_count` can be valid;
- `background_tile_pictures == 0` is the normal gold requirement;
- `semantic_full_slide_pictures == 0` is mandatory.

### Frame and panel rule

Simple cards, frames, dividers, arrows, and nodes are semantic geometry. They
must be represented as native shapes/connectors and must not remain only in the
background. When a panel contains complex artwork, use a native frame plus a
bounded `movable-panel-content` asset at the same measured bbox.

Run `scripts/layer_contract_gate.py` before a vNext release. Its structural
checks catch missing backgrounds, tiles, non-native text/shapes, unbounded
assets, and panel content without a matching native frame. Its generated
per-slide review also requires visual confirmation that the clean background
does not retain duplicate frame lines or semantic text.

### Text rule

`source_bbox` records where the source glyphs were observed. `layout_bbox`
records the final PowerPoint frame. Cleanup masks are separate again. Do not
collapse these three geometries.

OCR supplies a proposal for geometry and reading order. The final string comes
from the exact-text manifest. Numeric tables may infer a grid, but may never
infer displayed values.

### Icon and vector rule

SVG acceptance has two gates:

1. technical: bounded path count, correct colors, no embedded normal text, valid
   local geometry;
2. visual: the exact PPTX renders correctly in Microsoft PowerPoint at slide
   scale.

If the visual gate fails, keep the object visually present by either preserving
it in the clean background or extracting it into a separately movable
transparent PNG. Record the SVG candidate, rejection reason, fallback asset,
source bbox, and final bbox.

## Stages 7-8: release QA

Technical gates create evidence; they do not perform the final visual judgment.

Required technical evidence:

- PPTX ZIP integrity and expected slide XML count;
- strict layout pass;
- official overflow pass;
- editable grade, 100% routed native text/shape coverage, zero replacement
  characters, and zero semantic full-slide shortcuts;
- exact-text token coverage of 100% from the final PPTX;
- successful export of every slide by Microsoft PowerPoint;
- source, preview, side-by-side, blend, heatmap, and metrics for every slide.
- strict layer-contract pass and explicit per-slide background/frame review for
  new vNext gold releases.

Then inspect every slide at full size and the full-deck montage. Review:

- old glyph residue and duplicate text;
- CJK wrapping, punctuation, color runs, and character spacing;
- card edges, separator dots, chart labels, table cells, and mask damage;
- SVG/PNG icon position, contour integrity, and scale;
- image crops, overlaps, hierarchy, density, and ending-page quality.
- spectacle control: no non-evidence cinematic, neon, 3D, wallpaper, poster, or
  branding treatment competing with the claim;
- design completion: profile-appropriate evidence anchor, reading path, scale
  contrast, domain-specific vocabulary, and deliberate composition. For
  `academic_minimal`, verify deliberate negative space rather than accidental
  emptiness.

Mean absolute pixel difference is useful for comparing two rounds of the same
slide. It is not a universal pass threshold.

## Stage 9: immutable release and learning

- Aggregate all reports with `scripts/release_gate.py`.
- A missing or pending all-slide review returns `blocked`.
- New Gold releases use `--require-design-quality` so every visual-review row
  passes `spectacle_control` and `design_completion`.
- When only selected pages improve, create the new round with
  `scripts/merge_high_fidelity_round.py`; inherit all unaffected pages and
  verify their asset hashes.
- Save the final report beside the final PPTX.
- Do not overwrite the accepted deck after its release report and hash exist.
- Record weak slides, local changes, before/after evidence, rejected variants,
  and reusable lessons.

## Minimal durable artifacts

```text
image-prompts.json
deck-spec.json
assets/slides/Sxx.png
qa/imagegen-first-gate-report.json
deck-high-fidelity.json
qa/compose-report.json
qa/editability-report.json
qa/exact-text-report.json
qa/layer-review.json
qa/layer-contract-report.json
qa/final-gate/final-visual-gate.json
qa/visual-review.json
qa/release-report.json
qa/baseline-merge-report.json when a round inherits accepted pages
final editable PPTX
```
