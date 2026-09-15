# Distilled production lessons

Use this reference when planning a new high-fidelity deck, diagnosing repeated
failures, or changing the skill itself. The rules below were retained only when
they generalized across prior image-only, multi-style, and editable runs.

## What consistently worked

### Full-slide generation

- Source extraction and slide scripts before visual prompting produced more
  coherent decks than starting from a template.
- One fresh complete-page prompt per slide preserved visual intent better than
  generating a blank background and adding local overlays.
- Strongly distinct style contracts can produce multiple decks from one source
  without changing the narrative evidence.
- The real bottleneck is usually image generation. Backend/key preflight prevents
  long waits on an unavailable batch path.
- Local regeneration of a failed page is faster and more attributable than
  rebuilding the whole deck.
- Short exact Chinese text, explicit negative constraints, and source-backed
  numbers reduce malformed glyphs and fabricated interface values.
- Conclusion-led titles, one dominant evidence composition, limited color, and
  projector-scale typography generalized better than decorative theme prompts.
- Restraint worked when it removed non-evidence effects, not when it removed
  design authorship. Non-minimal profiles needed a primary evidence anchor,
  reading path, scale contrast, domain-specific graphics, and deliberate edge
  composition to avoid looking like unfinished templates.
- `academic_minimal` worked best as an explicit profile. Treating minimalism as
  the fallback for every prompt failure made engineering, editorial, clinical,
  and dark-research pages too generic.

### Editable reconstruction

- A mixed semantic route is more stable than full-page vectorization: native
  text, native simple geometry, bounded vectors, bounded raster artwork, and one
  continuous clean background.
- `source_bbox`, cleanup masks, and `layout_bbox` solve different problems.
  Keeping them separate prevents both visual residue and CJK wrap drift.
- Reviewed overrides outperform repeated OCR when tables, metric rails, repeated
  lists, or stylized titles fragment into many detections.
- OCR is useful for geometry. Exact text and numeric values must come from the
  source manifest.
- Compact charts and icon-rich cards should remain bounded raster exceptions
  when destructive cleanup would damage the visual object.
- Transparent PNG assets are a legitimate editable tier when they are isolated,
  movable, measured, and disclosed.
- When complex artwork sits inside a card, pairing a native frame with a bounded
  interior asset preserves both editability and the ImageGen visual.

### Final QA

- Structural editability did not predict PowerPoint pixels. The exact final PPTX
  had to be opened and exported by Microsoft PowerPoint.
- Redirecting Office scratch space to a roomy project drive resolved failures
  that looked like corrupt PPTX or COM problems.
- Exact-text coverage did not catch residual separator dots, split raster labels,
  wrong emphasis colors, or faint/broken SVG contours. Full-size visual review
  remained mandatory.
- Per-slide comparison metrics were most useful for deciding whether a local
  repair improved one slide. They were not reliable as a cross-deck quality
  score.
- The best iteration pattern was one attributable change per weak slide,
  followed by affected gates and then a full-deck release gate.
- Technical passes did not guarantee a visually finished slide. Review also had
  to reject spectacle and under-design independently.
- Inheriting all unaffected slides from the last accepted round reduced
  regressions and made before/after evidence easier to audit.

## Latest three-style 18-slide evidence

A recent source-grounded run produced `academic_light`,
`engineering_blueprint`, and `deep_academic` variants with the same
18-slide narrative. All three final editable decks passed Microsoft PowerPoint
rendering, strict layout, semantic-layer review, 247/247 exact-text matching,
all-slide visual review, and gold release aggregation.

The reusable lessons were:

- the light profile could stay restrained while still using strong evidence
  composition and mature page rhythm;
- the engineering deck passed several technical gates before full-size review
  exposed duplicate symbols, malformed metric text, and a local overlap, so
  visual sign-off remained indispensable;
- rebuilding the complete dark deck to repair two pages introduced regressions
  on previously accepted pages;
- replacing only the two improved dark pages from the accepted baseline
  produced the strongest round;
- the final engineering round likewise replaced only one weak page and retained
  every already accepted slide.

Therefore, weak-page inheritance is the default repair route. A full-deck
regeneration is justified only when the narrative or deck-wide style contract
is wrong.

## Rejected approaches and why

| Anti-pattern | Why it failed | Replacement |
| --- | --- | --- |
| Script-drawn first-stage slides | Violates ImageGen-first visual authorship and often looks templated | Generate each complete page with ImageGen |
| Waiting on batch generation without backend readiness | Appears stalled and wastes the run | Preflight first; switch to an available per-slide route or stop |
| Reusing old slide images or masters | Breaks provenance and source specificity | Fresh current-run prompts and images |
| One repeated card-grid layout | Produces UI/dashboard sameness and weak presentation rhythm | Vary page archetypes around one dominant composition |
| Treating restraint as universal minimalism | Produces clean but generic, sparse, or unfinished non-minimal decks | Make `academic_minimal` explicit; require profile-appropriate design completion elsewhere |
| Fixing unreadable text by stripping the whole composition | Removes the evidence anchor and design finish | Shorten copy and recompose while preserving the selected profile |
| Background split into 3x4 or similar tiles | Creates many square picture objects and poor editing behavior | One continuous clean non-semantic background |
| Requiring zero raw full-slide pictures | Incorrectly rejects a valid continuous background | Require zero semantic full-slide shortcuts and zero tiles |
| Auto-vectorizing the whole page | Creates thousands of meaningless paths and damages gradients/artwork | Trace only bounded flat candidates |
| Accepting SVG because it is syntactically valid | PowerPoint may render contours faint, broken, or filled | Accept only after exact-PPTX PowerPoint visual review |
| Forcing a failed SVG instead of using raster | Raises nominal vector count while lowering fidelity | Use a measured movable transparent PNG and record the rejection |
| Keeping every rejected icon baked into the background | Prevents moving a cleanly extractable object | Allow either background preservation or isolated PNG fallback |
| Broad inpainting across cards/charts | Smears borders, removes marks, or creates dark wedges | Tight masks or measured solid fills on flat regions |
| Treating exact text as visual pass | Misses residue, wrapping, color, and icon defects | All-slide full-size review after PowerPoint render |
| Treating visual diff return code as human review | A metrics script only proves artifacts were produced | Require a signed all-slide visual-review manifest |
| Rebuilding the whole deck for a local weak page | Regresses accepted slides and obscures attribution | Merge only reviewed slide IDs into a new immutable round |
| Overwriting the accepted round | Loses baseline and weakens attribution | Create a new round and compare before/after |

## Practical decisions

### When to regenerate the ImageGen page

Regenerate when the visual master itself has malformed text, invented facts,
wrong numbers, wrong style, bad hierarchy, or missing content. Do not try to fix
these first-stage defects only during editable reconstruction.

For a non-minimal profile, regeneration must preserve or improve the primary
evidence anchor and design completion. Remove unsupported spectacle, not useful
visual structure. Add source-backed evidence, annotation, comparison, mechanism,
crop, or spatial relationships when the page is too bare.

### When to adjust layout metadata

Adjust `layout_bbox`, explicit line breaks, font size, character spacing, or
object position when the semantic object is correct but PowerPoint wrapping or
placement differs.

### When to rebuild an asset

Rebuild or recrop only the affected asset when its mask, alpha edge, crop,
contour, or source separation is wrong. Preserve the rest of the slide.

### When to inherit an accepted round

When a patch improves only selected slide IDs, use
`merge_high_fidelity_round.py` to create a new round from the accepted
baseline, replace only those slide assets and deck entries, and verify every
inherited/replaced asset hash. Do not use a complete rebuild as a convenient
copy operation.

### When to keep raster

Keep raster when the object is photo-like, gradient-rich, highly stylized,
contains inseparable incidental text, or loses fidelity under vector/native
reconstruction. Make the exception bounded and movable where reliable.

### When to block release

Block when source truth is uncertain, ImageGen provenance is missing, exact text
is incomplete, PowerPoint cannot render the exact final file, overflow remains,
visual review is pending, or a vector/raster exception is undisclosed.
