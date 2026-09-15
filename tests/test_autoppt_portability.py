from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "autopptskills"
SCRIPT = SKILL / "scripts" / "validate_skill_portability.py"


class SkillPortabilityTest(unittest.TestCase):
    def test_repository_skill_has_no_machine_specific_findings(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), str(SKILL)],
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(payload["verdict"], "pass")
        self.assertEqual(payload["findings"], [])

    def test_numeric_endpoint_and_documented_absolute_path_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SKILL.md").write_text(
                "Workspace: D:\\example\\project\nEndpoint: http://10.2.3.4:8080/v1\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), str(root)],
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            rules = {finding["rule"] for finding in payload["findings"]}
            self.assertEqual(completed.returncode, 2)
            self.assertIn("absolute-windows-path-in-documentation", rules)
            self.assertIn("hardcoded-numeric-service-endpoint", rules)


if __name__ == "__main__":
    unittest.main()
