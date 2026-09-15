"""Compatibility import for the repository-wide built-in ImageGen policy."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from autopptskills.scripts.builtin_imagegen_policy import (  # noqa: E402,F401
    BUILTIN_IMAGEGEN_BACKENDS,
    BUILTIN_IMAGEGEN_PROVENANCE,
    BuiltinImageGenBlocked,
    DIRECT_FINAL_GENERATION_MODE,
    build_builtin_asset_manifest,
    validate_builtin_imagegen_outputs,
    write_builtin_blocker_report,
)

__all__ = [
    "BUILTIN_IMAGEGEN_BACKENDS",
    "BUILTIN_IMAGEGEN_PROVENANCE",
    "BuiltinImageGenBlocked",
    "DIRECT_FINAL_GENERATION_MODE",
    "build_builtin_asset_manifest",
    "validate_builtin_imagegen_outputs",
    "write_builtin_blocker_report",
]
