# Measured ImageGen Reconstruction Route

Use this route when a complete ImageGen slide has already been accepted and
the editable PPTX must preserve its measured composition. It is the bridge
between a frozen visual master and a real semantic PowerPoint layer model; it
is not a first-stage slide generator.

## Measurement contract

Keep the accepted source image and its SHA-256 hash immutable. A reviewed
`measured-plan.json` contains `ref_width`, `ref_height`, and one slide record
per master. Each slide may contain:

- `texts`: reviewed exact strings with `source_bbox`, `layout_bbox`, measured
  font, color runs, explicit line breaks, `fit: shrink`, and
  `editability_level: native-reviewed`;
- `shapes`: simple frames, dividers, arrows, nodes, and other measurable
  geometry with non-zero extents for lines and a stable z-order;
- `assets`: bounded crops with `source_bbox`, route, color/ink hints, and a
  concrete reason when the route is `movable-image` rather than native.

`source_bbox` records what was observed in the master. `layout_bbox` records
the final PowerPoint frame, which may be wider to prevent CJK wrapping drift.
These fields must not be collapsed into one approximate rectangle.

## Representation routing

1. Ordinary text and simple geometry are emitted as native PowerPoint objects.
2. An isolated, flat, low-complexity icon may use `native-trace`; the contour
   must be bounded, have a finite path budget, and be post-processed into an
   OOXML freeform shape.
3. Photos, dense charts, interfaces, scenes, gradients, and complex scientific
   figures stay as separately movable bounded images when tracing would reduce
   fidelity. The plan must record the rejection reason and the asset hash.
4. A flat native slide fill (`background_color`) is a valid continuous
   background. Do not manufacture a full-slide bitmap just to satisfy the
   background contract. A raster background, when needed, is one continuous
   non-semantic image, never a tile grid.

Never embed the complete master as a semantic full-slide picture. Never add
hidden, transparent, off-canvas, or tiny proxy text. A successful object count
does not override the native-text and visual-fidelity contracts.

## Reusable composer

```powershell
python autopptskills\scripts\compose_measured_reconstruction.py \
  <measured-plan.json> --out-dir <round-dir>
```

The composer validates source dimensions and crop bounds, records source and
asset hashes, writes `deck.json`, `compose-report.json`,
`asset-provenance.json`, and `native-traces.json`, then emits the editable
PPTX. Run the semantic gate before Office rendering; run the final visual,
exact-text, overflow, layer-contract, and release gates afterward.

## Typography and repair loop

Measure title and metric frames from the master, use explicit line breaks, and
adjust font size/character spacing only after a real PowerPoint render. If a
title wraps or a metric changes reading, fix the measured `layout_bbox`, font,
or break in the plan; do not cover it with a raster label. A local repair must
create a new accepted round and preserve all unaffected slide and asset hashes.

## Current evidence floor

The accepted thesis-defense run used this route for 11 slides: 176 native text
objects, 273 planned native geometry objects, 25 native traced icon contours,
and 28 bounded local image assets in the final PPTX. These counts describe an
evidence-backed run, not a universal quota; scientific meaning and visual
fidelity take precedence over path count.
