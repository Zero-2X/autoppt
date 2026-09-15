# Skills used by this repository

## Skill selection

| Skill | Use it for | Boundary |
| --- | --- | --- |
| [`autopptskills/SKILL.md`](../autopptskills/SKILL.md) | The complete source-grounded, ImageGen-first presentation workflow | Default repository contract; includes planning, visual masters, reconstruction, PowerPoint QA, and release |
| [`imagegen-to-editable-ppt/SKILL.md`](imagegen-to-editable-ppt/SKILL.md) | Post-generation reconstruction of a verified full-slide master | A component-manifest and object-routing plugin; not a second deck-generation workflow |

## External skill boundaries

- `imagegen`: use only for complete per-slide visual masters or bitmap edits;
  this repository does not use external image-generation APIs or CLIs.
- `karpathy-guidelines`: use its small, verifiable, low-complexity change
  discipline when editing workflow code.
- `autopptskills`: use for academic reports, thesis defenses, competitions,
  NSFC reviews, and image-to-editable PPTX work.

The repository-local skill files and `autopptskills/SKILL.md` are authoritative.
Do not import paper, experiment, or research skills from the source repository.
