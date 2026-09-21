# Workflow history and retained decisions

## User-approved preference update: 2026-09-20

The user explicitly requested information-rich text-and-image slides, pale
backgrounds, dark text, red emphasis, retained verified NSFC/university-defense
references, clean reconstructable typography and geometry, and visual identity
to the ImageGen master after reconstruction. These are approved workflow
preferences, not claims of a newly successful deck or historical benchmark.
See [approved-style-contract.md](approved-style-contract.md) for generation,
reconstruction and acceptance prompts. Old sparse-text repair advice is retired;
dark/minimal profiles now require explicit user selection. Pixel equality must
be measured; unresolved visible mismatch blocks release.

Use this reference when changing the skill, choosing between competing
reconstruction methods, or diagnosing a failure that has appeared before. It
records the reusable evidence from the full history, not one successful round.

## Evidence eras

### 1. Complete-page ImageGen established the visual baseline

Early work produced three distinct 22-slide decks from one evidence source.
The useful result was not any particular color theme. It proved that a shared
narrative can support multiple coherent visual systems when every slide has a
fresh, self-contained prompt and ImageGen renders the complete page.

Retain:

- source extraction, outline, slide script, and exact-text whitelist first;
- one fresh complete-page prompt per slide;
- strong style contracts that change visual language without changing facts;
- local regeneration of weak slides;
- immediate backend preflight and route switching when a batch path is absent.

Retire:

- starting from a generic visual template;
- reusing old masters without current provenance;
- waiting indefinitely on a missing key or unavailable backend;
- treating assembly success as proof of visual quality.

### 2. Multi-round editable reconstruction exposed geometry failures

A dense 22-slide defense deck required more than eighteen reconstruction and
repair rounds. OCR correction, reviewed text overrides, numeric-table recovery,
title repair, local masks, and Office temporary-directory isolation all proved
useful. The same work also exposed a major dead end: a 3 by 4 tiled background
created twelve square pictures per page, or 264 background pieces across the
deck. It could look close to the source while remaining a poor editable file.

Retain:

- separate `source_bbox`, cleanup mask, and `layout_bbox`;
- use OCR for geometry and reviewed manifests for final strings and numbers;
- use one attributable repair per weak slide;
- preserve accepted rounds and compare against them;
- redirect Office scratch space when low system-drive space mimics file damage.

Retire:

- tiled backgrounds as a normal gold route;
- broad inpainting over cards, charts, or icon clusters;
- accepting high object counts as proof of semantic editability;
- rebuilding the entire deck for one local defect.

### 3. Continuous-background reconstruction clarified the layer model

Later reconstruction kept one continuous non-semantic background per slide and
restored foreground semantics as native text, native frames and connectors,
bounded vectors, or bounded movable raster assets. This removed square
background fragments while preserving the ImageGen composition.

The durable layer contract is:

```text
one continuous background
+ native text
+ native simple frames, lines, arrows, and nodes
+ bounded local SVG only when Office renders it correctly
+ bounded movable PNG for complex or failed-vector content
```

When a panel contains complex artwork, its frame belongs in `shapes` and its
interior artwork may be a matching `movable-panel-content` asset. The frame must
not survive only as pixels in the background.

### 4. SVG experiments established the visual-fidelity veto

Eight isolated timeline icons were successfully traced into technically valid
SVG files. In real Microsoft PowerPoint, the outlines became faint or broken.
Replacing them with eight independent transparent PNG assets improved the
source-to-PowerPoint visual difference while keeping each icon movable.

Therefore:

- SVG syntax, path count, and standalone preview are only preflight evidence;
- the exact final PPTX must be exported by Microsoft PowerPoint;
- reject an SVG when contours fade, break, fill incorrectly, or move;
- preserve its rejection reason, source/final bbox, and visible fallback;
- never raise nominal vector count at the cost of visual fidelity.

### 5. The strongest accepted editable deck defined the current floor

A 15-slide accepted release demonstrated the current minimum quality floor:

- 162 native text boxes;
- 79 native shapes;
- 87 bounded movable pictures;
- zero background tiles;
- zero semantic full-slide pictures;
- exact-text coverage 229 of 229;
- successful Microsoft PowerPoint rendering and all-slide visual review.

Subsequent manual repairs still found a residual separator mark, raster-split
text, and an emphasis-color mismatch. This proves that exact-text coverage and
structural reports cannot replace full-size visual inspection.

### 6. Three-style 18-slide production separated restraint from minimalism

A later run generated and reconstructed three 18-slide decks from the same
project document: `academic_light`, `engineering_blueprint`, and
`deep_academic`. Each final deck passed strict layout, semantic-layer review,
real Microsoft PowerPoint rendering, 247/247 exact-text matching, all-slide
visual review, and gold release aggregation.

The run exposed two new general lessons:

1. "Not flamboyant" cannot become "always minimal." The engineering and dark
   profiles needed specific systems, deployment scenes, maps, interfaces,
   source imagery, measured detail, and stronger composition to feel complete.
2. Technical gates cannot decide which round looks best. One engineering round
   passed structural gates before human review found several visible defects,
   and one complete dark-deck rebuild regressed already accepted pages.

The successful repair pattern was to create a new round from the last accepted
baseline and replace only the reviewed weak pages. This became
`merge_high_fidelity_round.py`, which verifies inherited and replaced asset
hashes instead of silently rebuilding the deck.

The durable style interpretation is now:

- restraint removes meaningless effects;
- `academic_minimal` is the explicit low-density option;
- every non-minimal profile must pass a design-completion review in addition to
  spectacle control;
- a generic title-plus-card scaffold is a failure even when it is clean.

### 7. The 11-slide thesis-defense run made measured reconstruction portable

The latest thesis-defense delivery supplied the missing concrete bridge between
the abstract layer contract and a reproducible editable PPTX. A complete
ImageGen master was frozen and hash-bound first; a separate image-only PPTX
served as the visual checkpoint. A reviewed measured plan then placed 176
native text objects and 273 planned native geometry objects, traced only 25
isolated flat icons into OOXML freeforms, and kept complex scene/science content
as 28 bounded movable image assets in the final PPTX.

The run also confirmed that a native solid-color slide fill satisfies the
continuous-background contract. It does not need a full-slide raster image,
and it is preferable when the field is flat. Long CJK titles and metrics were
fixed by measured `layout_bbox`, explicit line breaks, stable font choices and
`fit: shrink`, followed by an actual PowerPoint render—not by overlaying hidden
or transparent proxy text.

Retain the generic `measured-reconstruction.md` route and composer in the skill;
keep the 11-slide geometry plan and page-specific repairs in the project run.
The current release evidence is a floor for process quality, not a universal
object-count target.

## Current decision precedence

When objectives conflict, decide in this order:

1. source truth and numeric correctness;
2. quality of the complete ImageGen master;
3. visual match of the exact final PPTX in Microsoft PowerPoint;
4. profile-appropriate design completion and audience readability;
5. semantic editability of normal text and simple geometry;
6. path-level vector depth.

This ordering allows one continuous raster background and bounded PNG
exceptions while forbidding semantic full-slide shortcuts, background tiles,
and visually degraded vectors.

## Retained and retired routes

| Route | Status | Reason |
| --- | --- | --- |
| Fresh per-slide complete ImageGen page | retained | Best first-stage visual authorship and page coherence |
| Image-only PPTX before reconstruction | retained | Immutable visual baseline and provenance checkpoint |
| Native text plus native simple geometry | retained | Highest-value semantic editability |
| Bounded SVG with Office visual pass | retained conditionally | Useful only when final contours remain faithful |
| Bounded transparent PNG fallback | retained conditionally | Better than a broken vector and still movable |
| One non-semantic continuous background | retained | Preserves the original full-page field without square fragments |
| Weak-slide merge from an accepted round | retained | Preserves accepted pages, makes changes attributable, and reduces regressions |
| Tiled background | legacy only | Visually close but structurally poor and not a new gold default |
| Whole-page tracing | retired | Path explosion and damaged gradients/artwork |
| Script-drawn first-stage slides | retired | Replaces ImageGen visual authorship with a template renderer |
| Automatic metrics as visual acceptance | retired | Misses residue, wrapping, color, and vector defects |
| Universal minimalism as a safety fallback | retired | Prevents spectacle but also removes necessary evidence richness and finish |
| Full-deck rebuild for a local page defect | retired | Regresses accepted slides and hides the scope of change |

## Rule for future learning

Add a new universal rule only after it appears across more than one slide or
run, or when a single failure threatens correctness, portability, or release
integrity. Keep project-specific repairs in the run ledger rather than turning
them into global prompt clutter.
