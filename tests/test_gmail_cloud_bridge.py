from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE_TEST = ROOT / "tests/js/gmail_cloud_bridge.test.mjs"


class GmailCloudBridgeTests(unittest.TestCase):
    def test_cloud_bridge_node_contract(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for Gmail cloud bridge tests")
        completed = subprocess.run(
            [node, "--test", str(NODE_TEST)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
