# autoppt: Standalone PPT production workflow

`autoppt` is the standalone presentation workflow extracted from
`autoresearch2ppt`. It turns source materials into source-grounded academic,
research, competition, and project presentations. It does not include paper
writing, research management, experiment execution, submission, or other
research pipelines.

## Intended use

- University thesis, proposal, mid-term, and completion defenses
- Research reports and project reviews
- Innovation, entrepreneurship, engineering, and academic competitions
- National Natural Science Foundation of China (NSFC) proposal defenses or reviews

## Canonical production chain

```text
source materials
  -> source/evidence manifest
  -> slide brief + exact-text and numeric whitelists
  -> one self-contained ImageGen prompt per slide
  -> built-in ImageGen full-slide master
  -> image-only PPTX
  -> semantic editable reconstruction
  -> Microsoft PowerPoint render
  -> all-slide visual/layer/text/release gates
  -> continuous-improvement ledger
```

The canonical contract is defined by
[`autopptskills/SKILL.md`](autopptskills/SKILL.md). It requires ImageGen-first
provenance, source truth, semantic reconstruction, and a Gold release gate. If
built-in ImageGen is unavailable, preserve the prompt/spec package and an exact
blocker report; never draw a substitute first-stage slide with PIL, SVG, HTML,
Canvas, matplotlib, or PowerPoint shapes.

## Reusable run contract

Every run must make this handoff explicit:

| Contract item | Required content |
| --- | --- |
| Inputs | Source materials, a topic workspace, and reviewed evidence when available |
| Planning | Outline, slide brief, exact-text whitelist, numeric whitelist, and style profile |
| Visual master | One self-contained built-in ImageGen prompt and one complete image per slide |
| Editable output | One continuous background plus native text/simple geometry and bounded local assets |
| Evidence | Provenance, manifests, PowerPoint render, per-slide comparisons, and review records |
| Release | Passing technical gates and explicit full-size visual review for every slide |

The run is `blocked`, not successful, when required evidence is missing.
Structural or mock output may diagnose plumbing, but it cannot be promoted to a
real visual or Gold release.

## Quick start

```powershell
# Structural smoke test only; never a visual deliverable
python autosearch/scripts/run_presentation_workflow.py <topic-dir> --mock --presentation-profile thesis_defense

# Real route: accepts only Codex built-in image_gen output
python autosearch/scripts/run_presentation_workflow.py <topic-dir> --real --presentation-profile thesis_defense --iterate-quality

# Regenerate one slide while preserving the accepted deck
python autosearch/scripts/run_presentation_workflow.py <topic-dir> --real --slide-id S03 --presentation-profile thesis_defense
```

`<topic-dir>` is a presentation project directory. It should contain at least
`source/`, `workspace/stage8_handoff/slide_brief.json`,
`workspace/stage8_handoff/ppt_outline.md`, and the source evidence files. The
workflow writes `final/ppt/`, speaker material, validation reports, and
iteration history inside that project directory.

## Repository boundaries

- `autopptskills/`: reusable PPT skill, style system, ImageGen-first policy,
  editable reconstruction, PowerPoint rendering, and release gates.
- `autosearch/presentation/`: source evidence, profiles, Slide IR, speaker
  notes, and presentation gate orchestration.
- `autosearch/ppt/`: per-slide prompts, ImageGen handoff, image-only PPTX
  assembly, and audits.
- `skills/imagegen-to-editable-ppt/`: the post-generation component-manifest
  and object-routing skill.
- `tests/`: workflow and gate tests.
- `docs/`: workflow and migration-boundary documentation.
- `improvement/`: reusable failure knowledge, vectorization decisions, and
  style guidance.

The repository intentionally excludes `autosearch/research`, paper/experiment/
submission templates, research samples, historical outputs, caches, temporary
directories, and unrelated root-level scripts.

## Continuous improvement

For every generation or quality iteration:

1. Read `improvement/ppt-improvement-ledger.jsonl` and
   `improvement/style-handbook.md`.
2. Record failures, visual/vector issues, root causes, repairs, and evidence.
3. Accept a candidate only when it does not repeat a known defect and does not
   regress against the accepted baseline.
4. Promote reusable fixes into `style-handbook.md`; keep project-specific
   exceptions in the project record.

The quality iterator reads this repository ledger by default. Use `--learn`
only when the run is intentionally allowed to update the global knowledge base.
