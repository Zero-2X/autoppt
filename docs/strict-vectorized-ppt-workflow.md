# Strict editable reconstruction workflow

1. Generate and freeze one ImageGen master per slide. Record each source hash,
   exact-text whitelist, and `source_bbox`.
2. Use one continuous background for ambient texture. Render all titles, body
   text, labels, and numbers as visible native PowerPoint text boxes.
3. Use native shapes/connectors for card boundaries, dividers, arrows, and nodes.
   Register an isolated simple icon as `convertible-vector` only when it passes
   PowerPoint visual review.
4. Keep complex photos/illustrations and lettering that cannot map to stable
   fonts as explicit `embedded_text_candidate` or `movable-image` exceptions,
   with a reason, source bbox, and layout bbox.
5. Reject `text-raster-fallback`, hidden 1x1 exact-text proxies, and transparent
   text pretending to be editable. Enforce this fail-closed with
   `semantic_editability_gate.py`.
6. Keep every round in its own directory and never overwrite an accepted round.
   After real Microsoft PowerPoint rendering, create source, preview,
   side-by-side, and diff-heatmap artifacts for every slide.
7. Release only when structure, PowerPoint rendering, slide comparisons, layer
   review, and full-size visual review all pass. Pixel metrics cannot replace
   editability or human/model sign-off.

## Historical exception pattern

Earlier rounds used a small number of ImageGen calligraphic titles as
`embedded_text_candidate` objects with a same-position native approximation.
This is an auditable fallback, not a claim that every glyph is path-editable.
