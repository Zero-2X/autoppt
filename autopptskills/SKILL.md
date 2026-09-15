---
name: autopptskills
description: Create, reconstruct, audit, and release source-grounded PowerPoint decks through an ImageGen-first workflow. Use for academic, project, research, competition, or thesis presentations, image-only decks, and image-to-editable PPTX work that requires semantic layers and real PowerPoint QA. Do not use it to replace built-in ImageGen with script-drawn first-stage slides or to describe raster assets as native or path-editable.
---

# AutoPPTSkills

Produce a presentation whose claims are traceable, whose visual master is
generated slide by slide with built-in ImageGen, whose editable version has
honest semantic layers, and whose exact final PPTX has passed real PowerPoint
rendering and explicit all-slide review.

This file is the reusable operating contract. Load detailed references only for
the route being executed.

## Definition of done

A run is complete only when the requested delivery tier is proven:

| Delivery tier | Required proof |
| --- | --- |
| Planning package | Reviewed evidence map, outline, Slide Manifest, exact-text/numeric whitelist, style contract, and one self-contained prompt per slide |
| Image-only deck | Planning proof plus verified built-in ImageGen provenance, complete slide images, image-only PPTX, and visual review |
| Editable draft | Verified visual masters plus Component Manifest, routed objects, continuous backgrounds, native text/simple geometry, bounded assets, and structural QA |
| Gold editable release | Editable draft proof plus exact-text pass, layer-contract pass, official overflow pass, exact final-PPTX PowerPoint export, every-slide comparisons, full-size visual sign-off, and aggregate release pass |

Do not claim a higher tier from lower-tier evidence. A mock run proves only
structural plumbing. Missing built-in ImageGen, Microsoft PowerPoint rendering,
or required visual review makes the relevant tier `blocked`, not `pass`.

## Decision precedence

When goals conflict, preserve this order:

1. Source, factual, numeric, and formula truth.
2. Quality of the accepted ImageGen visual master.
3. Fidelity of the exact final Microsoft PowerPoint render.
4. Audience readability and profile-appropriate design completion.
5. Semantic editability of normal text and simple geometry.
6. Path-level vector depth.

Never reduce fidelity merely to increase the nominal vector count.

## Canonical workflow

```text
0. inspect sources, workspace, tools, and prior accepted rounds
-> 1. build evidence map, Slide Manifest, exact-text and numeric whitelist
-> 2. lock narrative, page archetypes, style profile, and slide prompts
-> 3. generate one complete built-in ImageGen master per slide
-> 4. assemble image-only PPTX and verify current-image provenance
-> 5. decompose verified masters and route semantic objects
-> 6. compose editable PPTX with one continuous clean background per slide
-> 7. run structural, text, layer, overflow, PowerPoint, and visual gates
-> 8. release an immutable accepted round and capture reusable lessons
```

A later blocking stage may not repair or excuse a failed earlier gate.

## Route the request

| Request | Read before acting | Expected stopping point |
| --- | --- | --- |
| Source documents to a new deck | `references/project-integration.md`, `references/imagegen-full-slide.md`, `references/style-system.md` | Planning, image-only, or Gold tier requested by the user |
| Existing slide images to editable PPTX | `references/image-to-editable-pptx.md`, `references/method-selection.md` | Editable draft or Gold tier |
| High-fidelity/final delivery | Also read `references/workflow-architecture.md`, `references/harness-engineering.md`, `references/production-lessons.md`, and `references/qa-and-validation.md` | Gold tier only after every required gate passes |
| Inspect an existing run | `references/qa-and-validation.md` | Evidence-backed report; do not mutate unless asked |
| Select or repair visual style | `references/style-system.md`; for official-source-inspired patterns also read `references/official-source-archetypes.md` | Reviewed style contract and affected-slide regeneration plan |
| Change this skill or its global rules | `references/history-and-decisions.md` | A portable validated skill; do not universalize one slide-specific repair |

A non-ImageGen screenshot may be analyzed as a reference, but a new Gold
deliverable must first recreate it as a verified built-in ImageGen master.

## Stage contracts

### 0. Preflight and run identity

- Inspect current files, accepted rounds, manifests, and delivery target before
  generating anything.
- Give each run an isolated directory. Treat accepted rounds as immutable.
- Check built-in ImageGen readiness before a long batch. Check OCR,
  Node/PptxGenJS, vector tools, disk space, and Microsoft PowerPoint before
  editable reconstruction.
- On Windows, direct `TEMP` and `TMP` to a task-local directory on a drive with
  adequate space when Office rendering is involved.

### 1. Content truth

- Build or verify a source/evidence manifest and stable evidence IDs.
- Create the outline, Slide Manifest, exact visible text, numeric/formula
  whitelist, and evidence boundary for every slide.
- Every factual claim must cite evidence or be explicitly labeled as framing,
  interpretation, limitation, or planned work.
- OCR may propose reading order and geometry. It may not override reviewed
  wording, technical terms, identifiers, numbers, formulas, or table values.

### 2. Narrative and visual contract

- Give every slide one conclusion or one question to answer. Prefer a title
  that states the conclusion.
- Choose a stable profile by audience and evidence type. The default is
  `academic_light`; `academic_minimal` is the only intentionally low-density
  profile.
- Lock color, type hierarchy, density, evidence graphics, page-archetype rhythm,
  prohibited effects, and CJK handling before generation.
- Use one dominant composition per slide. Reject both non-evidence spectacle and
  unfinished title-plus-bullet/card scaffolds.
- Write one self-contained prompt per slide containing the exact short text,
  layout blueprint, evidence anchors, source boundaries, style contract,
  negative constraints, and acceptance criteria.

### 3. Built-in ImageGen visual masters

Every first-stage final slide image must come from Codex built-in `image_gen`.
Do not read or use `OPENAI_API_KEY`, a provider endpoint or SDK, a proxy,
`STAGE45_IMAGEGEN_CLI`, `LOCAL_IMAGEGEN_COMMAND`, ComfyUI, Stable Diffusion, or
another backend on this route.

For every pending slide:

1. Make one built-in `image_gen` call with that slide's complete prompt.
2. Ingest the returned `ig_...` result through
   `autosearch/ppt/builtin_imagegen_handoff.py` or the equivalent repository
   handoff.
3. Record prompt, slide ID, output path, current file hash, backend identity,
   and provenance.
4. Review the complete page. Regenerate only failed slides unless the deck-wide
   style contract is wrong.

Scripts may prepare prompts, materialize tool results, assemble images,
reconstruct objects, and run QA. They must not draw substitute first-stage
slides with PIL, SVG, HTML, Canvas, matplotlib, or PowerPoint shapes.

If built-in ImageGen is blocked, preserve the prompt/spec/manifest package and
the exact error. Retry or repair the same built-in route; do not switch
backends. Mock images remain visibly marked structural fixtures.

### 4. Image-only proof

- Assemble only the current generated slide images; add no script-generated
  text boxes or shapes.
- Require one full-slide image per slide and zero extra semantic objects.
- Run the ImageGen-first gate against the current image hashes and require
  strong `ig_...` IDs for a real delivery.
- Review all slides for content truth, malformed text, visual hierarchy,
  consistency, and profile completion before reconstruction.

### 5-6. Semantic editable reconstruction

Use `component-manifest-v1` as the bridge from a verified visual master to
editable objects. Every routed component records its semantic type,
`content_id`, normalized bbox, z-order, render type, confidence, editability,
and provenance. `content_id` must resolve to reviewed Slide Manifest content
when the component carries semantic text.

| Content | Preferred representation |
| --- | --- |
| Normal title, body, label, or table text | Native PowerPoint text box |
| Simple card, line, divider, arrow, or node | Native PowerPoint shape/connector |
| Flat isolated line art | Bounded SVG candidate, accepted only after PowerPoint visual review |
| Complex illustration, photo, interface, or chart artwork | Bounded movable raster asset |
| Paper, grid, or ambient texture | One continuous non-semantic full-slide background |

Preserve three separate geometries: `source_bbox` for provenance, cleanup mask
for pixel removal, and `layout_bbox` for final placement. A routed foreground
object must reveal a visually neutral background when hidden. Reject duplicate
text, frame ghosts, object-shaped patches, shadows, gradients, or silhouettes
left in the background.

Never trace the complete page. Report `native`, `convertible-vector`,
`movable-image`, and `visual-only` separately. A movable PNG or imported SVG is
not fully native. Record the source/final bbox, fallback asset, and concrete
reason for every rejected vector.

### 7. QA and Gold release

Technical success does not imply visual acceptance. A Gold release requires:

- readable PPTX ZIP and expected slide count;
- ImageGen-first pass for every current slide hash;
- strict layout and official overflow passes;
- 100% routed native text/simple-shape coverage and zero semantic full-slide shortcuts;
- exact-text token coverage of 100% and zero replacement characters in the final PPTX;
- strict layer-contract pass: one continuous background, zero tiles, native
  simple frames, bounded local assets, and no duplicated semantic residue;
- successful export of the exact final PPTX by Microsoft PowerPoint;
- source, preview, side-by-side, blend, heatmap, and metrics for every slide;
- explicit full-size review of every slide and the montage, including text
  residue, wrapping, spacing, emphasis, icons, tables, crops, overlap,
  spectacle control, and design completion;
- decisions for every vector candidate and bounded-raster exception;
- aggregate `release_gate.py` verdict `pass` with
  `--require-layer-contract` and `--require-design-quality`.

Pixel metrics are comparison evidence, never an automatic acceptance rule.
Missing Office rendering or incomplete visual review must remain `blocked`.

### 8. Immutable release and learning

- Save the final PPTX, hashes, manifests, reports, review files, rejected
  variants, and iteration ledger together.
- Never overwrite an accepted round. If only selected slides improve, create a
  new round with `scripts/merge_high_fidelity_round.py` and verify inherited and
  replaced asset hashes.
- Convert repeated, evidence-backed lessons into the improvement ledger or a
  focused reference. Keep project-specific exceptions in the project record.

## Minimal durable artifacts

```text
image-prompts.json
deck-spec.json
assets/slides/Sxx.png
qa/imagegen-first-gate-report.json
component_manifest.json                 # editable route
deck-high-fidelity.json                 # editable route
qa/compose-report.json                  # editable route
qa/editability-report.json              # Gold route
qa/exact-text-report.json               # Gold route
qa/layer-review.json                    # Gold route
qa/layer-contract-report.json           # Gold route
qa/final-gate/final-visual-gate.json    # Gold route
qa/visual-review.json                   # Gold route
qa/release-report.json                  # Gold route
final PPTX
```

## Core commands

```powershell
# Editable capability preflight
python autopptskills\scripts\check_editable_backends.py --json-out <run-dir>\qa\method-capabilities.json

# Reconstruct one verified ImageGen master
python autopptskills\scripts\reconstruct_imagegen_slide.py <slide.png> <run-dir> --imagegen-manifest <image-prompts.json> --slide-manifest <slide-manifest.json> --force-16x9

# Validate the semantic bridge
python autopptskills\scripts\component_manifest_qa.py <run-dir>\component_manifest.json --json-out <run-dir>\qa\component-manifest-qa.json

# Validate final semantic layers
python autopptskills\scripts\layer_contract_gate.py <deck-high-fidelity.json> --pptx <final.pptx> --review <qa\layer-review.json> --out <qa\layer-contract-report.json>
```

Read `references/qa-and-validation.md` for the complete release command set and
report schemas.

## Failure routing

- Unsupported or conflicting fact: stop content production for that claim and
  repair the evidence/whitelist.
- Malformed ImageGen text or weak composition: regenerate the complete affected
  slide master.
- Style drift across the deck: repair the style contract, then regenerate only
  affected slides unless the contract is globally invalid.
- Reconstruction mismatch: adjust measured routing/layout first; regenerate an
  asset only when its pixels are wrong.
- Broken SVG in PowerPoint: use a bounded transparent PNG and record the visual
  rejection.
- Background residue: tighten the cleanup mask and verify the counterfactual
  background with the foreground object hidden.
- Full-deck regression after a local repair: merge the reviewed slide into the
  last accepted baseline and rerun affected gates plus the aggregate release gate.
- Missing PowerPoint export or visual sign-off: preserve all evidence and report
  `blocked`; do not infer success from ZIP validity or a non-Office preview.

## Reference map

- `references/workflow-architecture.md`: canonical architecture and precedence.
- `references/project-integration.md`: repository inputs, routes, and handoff outputs.
- `references/imagegen-full-slide.md`: prompt-per-slide production and schemas.
- `references/style-system.md`: profile selection and bidirectional design-quality gate.
- `references/official-source-archetypes.md`: source/license tiers and identity boundaries.
- `references/image-to-editable-pptx.md`: detailed reconstruction procedure and schemas.
- `references/method-selection.md`: OCR/vector/raster/native routing.
- `references/harness-engineering.md`: state machine, iteration ledger, and evidence gates.
- `references/qa-and-validation.md`: complete validation and release commands.
- `references/production-lessons.md`: retained practices and rejected approaches.
- `references/history-and-decisions.md`: evidence history and global-rule change policy.

Keep work focused on the highest unmet gate. Do not call a deck complete until
the requested tier is proven by its own artifacts and exact final-state checks.
