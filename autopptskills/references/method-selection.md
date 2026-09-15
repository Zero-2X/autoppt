# Method Selection For Imagegen-To-Editable PPTX

Use this reference after imagegen has produced the complete slide image. The goal is not to blindly vectorize every pixel. The goal is to preserve the imagegen art direction while rebuilding each semantic object with the most editable stable representation available.

## The Four Editability Levels

1. `native`: PowerPoint text, shapes, connectors, tables, and charts. Directly editable in PowerPoint.
2. `convertible-vector`: SVG/EMF line art. Selectable and scalable; path-level editing may require PowerPoint's Convert to Shape command.
3. `movable-image`: separate transparent PNG/WebP assets for complex imagegen artwork. Move, resize, crop, recolor with picture tools, but internal details are not editable.
4. `visual-only`: one or more full-slide pictures carrying semantic text and structure. This is not an editable deliverable.

Every slide manifest should report how much content remains at each level. Do not call level 3 or 4 fully editable.

## Routing Matrix

| Detected content | Preferred method | Stable output | Avoid |
| --- | --- | --- | --- |
| Normal Chinese/English text | OCR/manual correction plus measured bbox | Native text box | Keeping text baked into an image |
| Stylized 3D/brush/gradient art title | Preserve in verified imagegen raster and report as art text | Raster exception | Replacing it with a generic font and claiming fidelity |
| Card, divider, dot, straight arrow, simple flow box | Measured geometry | Native PowerPoint shape/connector | Tracing the whole slide as SVG |
| Table or chart with legible data | Reconstruct from source values | Native table/chart plus text | Raster chart with duplicated labels |
| Single-color line icon or logo | VTracer/Potrace/OpenCV contour trace | SVG, then optionally Convert to Shape | Photo-style tracing with thousands of paths |
| Complex illustration, map, robot, drone, product photo, photo-like infographic | Keep in clean imagegen-derived background or isolate as a region asset | Raster artwork | Crude native-shape redraw |
| Incidental text inside photos/screens/product labels | Keep with the complex raster unless explicitly requested | Raster exception | Duplicate OCR text over the photo |
| Dense relationship/network diagram | Native connectors and nodes; Graphviz only when topology is complex | Editable shapes or SVG | One flattened screenshot |
| Decorative paper/grid/ambient texture | Clean imagegen background | One full-slide background picture | Rebuilding noise as hundreds of shapes |

## OCR And Layout Analysis

Preferred order for Chinese PPT screenshots:

1. PaddleOCR/PP-StructureV3 when a local backend is available. It combines OCR with layout-region detection and is the strongest default for titles, text blocks, tables, and reading order.
2. Surya or docTR when multilingual document layout is more important than a small installation footprint.
3. EasyOCR for a lighter local fallback with bounding boxes.
4. Tesseract for clean conventional text when the correct language data is installed.
5. Manual/vision-assisted transcription for large stylized slide headings, followed by exact string verification.

OCR is only a measurement proposal. Reconcile it with the exact imagegen prompt/manifest text, then correct spelling, punctuation, reading order, and line breaks before composition. Store the corrected string and visible-glyph `source_bbox`; store a separate `layout_bbox` when the PowerPoint frame is expanded or aligned to a container. Never compose directly from unreviewed OCR output.

Official references:

- PaddleOCR and PP-StructureV3: `https://github.com/PaddlePaddle/PaddleOCR`
- Surya: `https://github.com/datalab-to/surya`
- docTR: `https://github.com/mindee/doctr`
- EasyOCR: `https://github.com/JaidedAI/EasyOCR`
- Tesseract: `https://github.com/tesseract-ocr/tesseract`

## Raster-To-Vector Methods

- VTracer is the preferred general raster-to-SVG tracer for flat graphics and line art. It is reproducible and exposes color/curve simplification controls.
- Potrace is strong for binary monochrome silhouettes and logos.
- Inkscape Trace Bitmap is useful for supervised desktop refinement but is less suitable as the only automated backend.
- OpenCV contours are best for simple measured outlines, connected components, and geometry detection. They are not a universal illustration vectorizer.

Vectorization acceptance checks:

- Path count is bounded. Reject traces with excessive tiny paths.
- The SVG does not contain text that should be a native text box.
- The exact final PPTX has been rendered by Microsoft PowerPoint and the contour, fill, stroke weight, transparency, and position remain acceptable at slide scale. Browser, SVG, or Pillow previews alone are insufficient.
- The vector asset is an individual element or region, not a full-slide semantic substitute.
- A rejected trace has an explicit reason and remains visually present. It may stay in the continuous background or become a separately movable transparent PNG when clean extraction is reliable.
- Treat imported SVG as `convertible-vector`. Claim `native` only after the actual PowerPoint object is verified as an editable shape. Some Office builds do not expose `ConvertToShape()` through COM, so SVG fallback is expected.

Official references:

- VTracer: `https://github.com/visioncortex/vtracer`
- Potrace: `https://potrace.sourceforge.net/`
- OpenCV contours: `https://docs.opencv.org/4.x/d4/d73/tutorial_py_contours_begin.html`

## Segmentation And Object Extraction

Use deterministic methods first:

1. Chroma-key or alpha extraction for imagegen assets generated on a required key-color background.
2. Connected components for separated objects on a transparent sheet.
3. Region bboxes for dense slides where each region is semantically independent.
4. SAM 2 or Grounding DINO only when promptable segmentation is installed and deterministic masks can be reviewed.

SAM-class models can isolate objects, but they do not recover editable text, chart data, or PowerPoint semantics. Treat their masks as asset extraction, not as a full conversion method.

Official reference: `https://github.com/facebookresearch/sam2`

## PPTX Assembly Backends

Preferred order for this skill:

1. PptxGenJS for new reproducible decks. It creates native text, shapes, images, charts, and tables and supports object naming, fixed coordinates, character spacing, and shrink-to-fit.
2. PowerPoint COM for Windows-only final rendering, inspection, or features that require the real Office engine.
3. `python-pptx` only as a legacy compatibility route for existing project scripts. Do not select it for new work when PptxGenJS is available.
4. LibreOffice UNO for environments without PowerPoint, with additional visual QA because rendering and font metrics differ.

Official reference: `https://github.com/gitbrent/PptxGenJS`

## Local Capability Routing

Before a run, record backend readiness in `qa/method-capabilities.json`:

```powershell
python autopptskills\scripts\check_editable_backends.py --json-out qa\method-capabilities.json
```

- PowerPoint desktop: available or missing.
- PptxGenJS: available or missing.
- OpenCV/scikit-image: available or missing.
- OCR backend and Chinese model/language data: available or missing.
- VTracer/Potrace/Inkscape: available or missing.
- SAM-class segmentation: available or missing.

Missing optional backends must cause a route downgrade, not silent substitution. For example, if VTracer is missing, use native shapes for simple geometry and movable PNG assets for complex line art; do not claim vector editability.

## Stable Default Route

For most imagegen-generated Chinese defense slides:

1. Preserve one clean imagegen background.
2. Extract and verify all normal text against the imagegen manifest.
3. Measure and recreate card frames, dividers, arrows, connectors, and simple nodes as native shapes.
4. Remove only selected foreground text/icon pixels from the imagegen master; preserve complex photos, illustrations, art titles, and rejected trace candidates in the raster.
5. Trace only isolated single-color line art when a vector backend is installed, then accept it only after PowerPoint-scale visual review.
6. Compose with PptxGenJS.
7. Render with PowerPoint when available.
8. Pass strict layout, overflow, final-PPTX exact text, PowerPoint rendering, all-slide visual review, editability, Unicode, and unresolved-object review.

This mixed route is more stable than attempting to turn an entire AI-generated slide into thousands of editable vector paths.
