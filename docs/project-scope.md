# autoppt project boundary

## Retained scope

This project retains only the code needed to generate, reconstruct, audit, and
release PPT presentations:

- `autopptskills/`
- `autoppt_workflow/presentation/`
- `autoppt_workflow/ppt/`
- `autoppt_workflow/scripts/run_presentation_workflow.py`
- `autoppt_workflow/scripts/iterate_presentation_quality.py`
- PPT-related tests, documentation, and environment configuration

`autopptskills/` is the single canonical skill source in this repository.
The copy in the user's Codex skills directory is its runtime installation,
not a second independently maintained skill.

## Excluded scope

The following are intentionally excluded:

- Research, experiment, and paper prompts and templates
- `sample/`, `outputs/`, `runs/`, `workspaces/`, `tmp/`, caches, and Office temporary directories
- Paper writing, submission, review, experiment execution, and research-management code
- Project-specific one-off scripts and historical deck artifacts

## Runtime boundary

The PPT workflow may read user-provided source materials, but it must not make
paper production a runtime prerequisite. Presentation outputs belong under the
project's `final/ppt/` directory. Reusable lessons belong in `improvement/`.
An accepted PPTX is immutable and must never be overwritten by a later round.
