# Project Integration

Use this reference when working inside the repository that contains the
project-local `autopptskills/` folder or a close clone of that repository.

## Mandatory Generation Order

For actual PPT generation, scripts cannot be the slide renderer. In this project, scripts are only allowed to prepare prompts/specs, invoke imagegen, verify outputs, and assemble generated full-slide images.

Required order:

```text
source materials
-> project profile / outline / slide scripts
-> one prompt per slide
-> imagegen generates every complete slide image
-> build_image_deck.py places those images into PPTX
```

### Built-in ImageGen-only policy

The image-generation step above is a hard platform boundary: use only Codex's
built-in `image_gen` capability. Do not configure or invoke
`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `IMAGEGEN_CLI`,
`LOCAL_IMAGEGEN_COMMAND`, a provider SDK, a proxy, or a second image backend.
The ImageGen assembly scripts may validate and assemble images that the built-in tool
already produced, but they are not authorized to generate replacement images.
If built-in ImageGen is unavailable, keep the prompt/spec/manifest artifacts,
write a blocked report with the exact error, and repair/retry the built-in
route. A mock run is structural evidence only and cannot be promoted to a
real visual result.

Do not use `build_image_deck.py`, `compose_*pptx.py`, PIL, SVG, HTML, Canvas, matplotlib, or PowerPoint shapes to create final slide content before imagegen. Those tools are post-imagegen assembly or editable reconstruction tools, not a replacement for imagegen.

## Preferred Project Routes

### Existing PPT topic workspace

Use this when a topic folder already has presentation handoff materials:

```text
topic_.../
  final/final_workbook.md or workspace/presentation_handoff/*定稿.md
  workspace/presentation_handoff/slide_brief.json
  workspace/presentation_handoff/ppt_outline.md
  workspace/presentation_handoff/visual-manifest.json
  workspace/evidence_workspace/evidence-ledger.json
```

Run the copied adapter from this skill or the repository source:

```powershell
python autopptskills\scripts\ppt\ppt_runner.py <topic_dir> --mock --style-profile academic_light
```

Use `--mock` only for structural verification. Real visual completion requires
fresh output from the built-in ImageGen capability and must not be claimed from
mock slides or any API/CLI/local substitute.
The CLI reads its profile choices from `scripts/style_contracts.py`; do not
duplicate a hard-coded list in downstream adapters.

### Full-slide ImageGen workspace

Use this when building directly from application materials, reports, proposals, or competition source files.

Expected folder:

```text
imagegen_ppt_generation/
  source-materials/
  project-profile.json
  style-profile.json
  design-spec.md
  spec-lock.json
  outline.md
  deck-outline.json
  slide-scripts.json
  image-prompts.json
  references/imagegen-prompt-pack.md
  references/asset-manifest.json
  deck-spec.json
  assets/slides/Sxx.png
  pptx/output/
```

If the workspace does not exist, create the folder structure and planning artifacts before imagegen. Do not start from a visual template.

## Local Commands

Check the built-in ImageGen readiness and current artifact manifest before a
long run. Do not use a key-based backend checker as a generation step:

```powershell
python autopptskills\scripts\check_imagegen_backend.py --workspace <workspace_dir> --report <workspace_dir>\imagegen-backend-check.json
```

Validate built-in generated images and assemble:

```powershell
python autopptskills\scripts\run_imagegen_ppt.py <workspace_dir> --output <out.pptx> --report <build-report.json>
```

Assemble existing generated slide images:

```powershell
python autopptskills\scripts\build_image_deck.py <deck-spec.json> --output <out.pptx> --report <build-report.json>
```

## Project-Specific Invariants

- `image-prompts.json` must set `prompt_policy.output_mode` to `direct_final_slide_imagegen`.
- `deck-spec.json` must set `deck.output_mode` to `imagegen_full_slide`.
- `deck-spec.json` must set `deck.generation_mode` to `direct_final_slide_imagegen`.
- Every slide layout must be `full_slide_image`.
- Every slide image path must exist before PPTX assembly.
- Each prompt must include evidence anchors or source references when evidence is available.
- The PPTX builder is an image container only; it must not add native text overlays.

## Handoff Outputs

For project handoff, produce or preserve:

- `image-prompts.json`
- `references/imagegen-prompt-pack.md`
- `references/asset-manifest.json`
- `deck-spec.json`
- generated `assets/slides/Sxx.png`
- final `.pptx`
- build report
- visual QA or audit report
- any regeneration log for failed slides

For a gold editable handoff, also preserve:

- `deck-high-fidelity.json` and compose report
- editability and final-PPTX exact-text reports
- official overflow evidence
- Microsoft PowerPoint previews and every-slide comparison artifacts
- all-slide `visual-review.json`
- icon/vector decision report when candidates existed
- aggregated `release-report.json`

## Known Bottlenecks

- If the built-in ImageGen call is blocked, do not wait on an unrelated batch
  job or switch providers. Report the exact built-in blocker, keep
  prompt/spec/manifest artifacts ready, and repair or retry that route.
- If image generation is slow, say that image generation is the bottleneck, not PPT export.
- If only assembly is needed, run `build_image_deck.py` directly only after verifying all image paths are fresh imagegen outputs for the current run.
- Do not add provider endpoints or ImageGen credentials to arguments,
  environment variables, or private `.env` files for this workflow. The
  built-in capability owns authentication and routing.
