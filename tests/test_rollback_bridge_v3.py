from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE_TEST = ROOT / "tests/js/rollback_bridge_v3.test.mjs"


class RollbackBridgeV3Tests(unittest.TestCase):
    def test_rollback_tool_node_contract(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for the rollback tool tests")
        completed = subprocess.run(
            [node, "--test", str(NODE_TEST)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            timeout=600,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
