# autoppt project boundary

## Retained scope

This project retains only the code needed to generate, reconstruct, audit, and
release PPT presentations:

- `autopptskills/`
- `autosearch/presentation/`
- `autosearch/ppt/`
- `autosearch/scripts/run_presentation_workflow.py`
- `autosearch/scripts/iterate_presentation_quality.py`
- `skills/imagegen-to-editable-ppt/`
- PPT-related tests, documentation, and environment configuration

## Excluded scope

The following are intentionally excluded:

- `autosearch/research/`, `autosearch/llm/`, research/experiment/paper prompts and templates
- `sample/`, `outputs/`, `runs/`, `workspaces/`, `tmp/`, caches, and Office temporary directories
- Paper writing, submission, review, experiment execution, and research-management code
- Project-specific one-off scripts and historical deck artifacts

## Runtime boundary

The PPT workflow may read user-provided source materials, but it must not make
paper production a runtime prerequisite. Presentation outputs belong under the
project's `final/ppt/` directory. Reusable lessons belong in `improvement/`.
An accepted PPTX is immutable and must never be overwritten by a later round.
