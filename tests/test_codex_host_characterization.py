import json
import importlib.util
from pathlib import Path
import unittest


PROBE_ROOT = Path(__file__).parent / "fixtures" / "codex-relative-mcp-probe"


class CodexHostProbeFixtureTests(unittest.TestCase):
    def test_probe_manifest_uses_one_relative_existing_script(self):
        manifest = json.loads((PROBE_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        server = manifest["mcpServers"]["relative-path-probe"]
        self.assertEqual("python", server["command"])
        self.assertEqual(["probe/probe_mcp.py"], server["args"])
        self.assertTrue((PROBE_ROOT / server["args"][0]).is_file())
        self.assertNotIn("${", server["args"][0])


class CodexHostProbeProtocolTests(unittest.TestCase):
    def test_initialize_with_non_object_params_is_an_invalid_request(self):
        spec = importlib.util.spec_from_file_location("probe_mcp", PROBE_ROOT / "probe" / "probe_mcp.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        response = module.handle_request({"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": []})

        self.assertEqual({"code": -32600, "message": "Invalid Request"}, response["error"])
        self.assertEqual(7, response["id"])
