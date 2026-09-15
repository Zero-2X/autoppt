# PPT style and quality handbook

This handbook is continuously maintained from accepted runs and documented
failures. It is a reusable decision aid, not a substitute for the source,
slide manifest, or release gates.

## Overall objective

For thesis defenses, research reports, competitions, and NSFC reviews, optimize
for clear evidence, conclusion-first communication, restrained but complete
visual design, editability, and auditability. Start with `academic_light`:
light paper, low-saturation navy/teal, one controlled accent, clear CJK
hierarchy, and graphics tied to the evidence.

## Stable style principles

- Give every slide one primary conclusion. Make the title state the conclusion
  or the question being answered whenever possible.
- Establish the reading path before adding secondary information; avoid evenly
  distributed card walls.
- Every non-minimal page needs a primary evidence anchor, scale contrast, and
  domain-specific visual language.
- Explain charts, processes, and mechanisms with direct annotations rather than
  decorative icons standing in for evidence.
- Reject neon, cyber HUDs, lens flares, unsupported 3D, fake logos, fake awards,
  invented metrics, giant hero backgrounds, and glassmorphism.
- Do not copy university identity systems, official funder forms, seals, or
  apparently official headers. Preserve academic credibility without implying
  false endorsement.

## High-risk failure modes and repairs

| Failure mode | Typical cause | Preferred repair |
| --- | --- | --- |
| Title plus bullets looks unfinished | No primary evidence anchor; prompt describes text only | Rewrite the slide goal, add a readable evidence graph/process/comparison, and make the title state the conclusion |
| Page is empty or looks like a wireframe | Minimalism applied without enough evidence | Increase the primary visual scale and add controlled secondary evidence/annotations; do not add decoration randomly |
| Repeated card grid | Component template replaced the narrative | Use one dominant composition: timeline, causal chain, layered section, comparison, or mechanism diagram |
| Garbled CJK text | ImageGen was asked to render long text | Shorten visible text; route important wording through the exact-text whitelist and native text; regenerate a malformed master instead of overlay-patching it |
| Vector trace is faint, broken, or incorrectly filled | Complex art was forced into SVG or PowerPoint renders it differently | Fall back to bounded raster; use native/SVG only for simple line art, frames, arrows, and nodes; record the rejection reason |
| Background cleanup leaves halos or ghosts | Inpaint mask is too broad or semantic edges were erased | Use a tight source bbox, preserve borders/icons/antialiasing, and repair against the PowerPoint render |
| Native text duplicates the master | OCR text was not aligned with the mask or manifest | Remove duplicate OCR using the reviewed source bbox, then rerun exact-text and visual gates |
| PPT overflows or wraps unexpectedly | Only the PNG was inspected | Export real PowerPoint every round; fix bbox, font size, line spacing, and safe margins |
| Metrics were changed by design | Visual composition drifted from source truth | Use Slide Manifest > reviewed source > OCR; do not generate unsupported numbers |

## Editable reconstruction decisions

- Normal text: native PowerPoint text box.
- Simple cards, lines, arrows, and nodes: native shapes/connectors.
- Isolated flat line art: SVG only after exact PowerPoint visual review.
- Complex research figures, photos, interfaces, and chart artwork: bounded
  movable raster or SVG group.
- Paper texture and ambient fields: one continuous background per slide; never
  tile a background in the normal Gold route.

Every rejected vector candidate must record `source_bbox`, `layout_bbox`, a
concrete rejection reason, and a fallback asset.

## Release checklist

Require ImageGen provenance, readable PPTX ZIP, official overflow evidence,
100% exact-text coverage, zero replacement characters, successful real
PowerPoint export, full-size visual review, continuous-background and semantic
layer audits, decisions for every rejected vector, and explicit release-gate
sign-off.
