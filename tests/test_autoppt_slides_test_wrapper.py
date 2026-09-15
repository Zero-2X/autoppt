from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "autopptskills" / "scripts" / "run_slides_test.ps1"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell wrapper is Windows-specific")
def test_slides_test_wrapper_supplies_current_bundled_runtime_contract(tmp_path: Path) -> None:
    dependency_root = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
    )
    required_paths = [
        dependency_root / "python" / "python.exe",
        dependency_root / "node" / "bin" / "node.exe",
        dependency_root / "node" / "node_modules" / "@oai" / "artifact-tool" / "package.json",
        dependency_root / "bin" / "override",
    ]
    if not all(path.exists() for path in required_paths):
        pytest.skip("Bundled Codex presentation runtime is unavailable")

    fake_slides_test = tmp_path / "slides_test.py"
    fake_slides_test.write_text(
        """
import os
from pathlib import Path

expected_root = Path(os.environ["EXPECTED_RUNTIME_ROOT"]).resolve()
assert Path(os.environ["RUNTIME_NODE"]).resolve() == expected_root / "node" / "bin" / "node.exe"
assert Path(os.environ["RUNTIME_NODE_MODULES"]).resolve() == expected_root / "node" / "node_modules"
assert Path(os.environ["RUNTIME_BIN_DIR"]).resolve() == expected_root / "bin" / "override"
assert Path(os.environ["TEMP"]).is_dir()
assert Path(os.environ["TMP"]).resolve() == Path(os.environ["TEMP"]).resolve()
print("Test passed. No overflow detected.")
""".lstrip(),
        encoding="utf-8",
    )

    input_pptx = tmp_path / "input.pptx"
    input_pptx.write_bytes(b"not-read-by-the-fake-test")
    output_log = tmp_path / "slides-test.txt"
    temp_root = tmp_path / "slides-test-tmp"
    env = os.environ.copy()
    env["CODEX_RUNTIME_DEPENDENCIES"] = str(dependency_root)
    env["EXPECTED_RUNTIME_ROOT"] = str(dependency_root)

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WRAPPER),
            "-InputPptx",
            str(input_pptx),
            "-OutputLog",
            str(output_log),
            "-TempDirectory",
            str(temp_root),
            "-PresentationToolsRoot",
            str(fake_slides_test),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Test passed. No overflow detected." in output_log.read_text(encoding="utf-8")
    assert not any(temp_root.iterdir())
