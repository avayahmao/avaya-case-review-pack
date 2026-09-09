import json
import importlib.util
from pathlib import Path
import subprocess
import sys
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
    def run_probe(self, *requests):
        process = subprocess.run(
            [sys.executable, str(PROBE_ROOT / "probe" / "probe_mcp.py")],
            cwd=PROBE_ROOT.parent,
            input="\n".join(requests) + "\n",
            capture_output=True,
            check=True,
            text=True,
        )
        self.assertEqual("", process.stderr)
        return [json.loads(line) for line in process.stdout.splitlines()]

    def test_initialize_with_non_object_params_is_an_invalid_request(self):
        spec = importlib.util.spec_from_file_location("probe_mcp", PROBE_ROOT / "probe" / "probe_mcp.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        response = module.handle_request({"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": []})

        self.assertEqual({"code": -32600, "message": "Invalid Request"}, response["error"])
        self.assertEqual(7, response["id"])

    def test_newline_delimited_requests_support_every_allowed_method(self):
        responses = self.run_probe(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "report_launch_context"}}),
        )

        self.assertEqual([1, 2, 3], [response["id"] for response in responses])
        self.assertEqual("relative-path-probe", responses[0]["result"]["serverInfo"]["name"])
        self.assertEqual("2024-11-05", responses[0]["result"]["protocolVersion"])
        self.assertEqual(["report_launch_context"], [tool["name"] for tool in responses[1]["result"]["tools"]])

        tool_result = responses[2]["result"]
        reported_context = json.loads(tool_result["content"][0]["text"])
        self.assertEqual({"script_path", "cwd"}, set(reported_context))
        self.assertEqual(str((PROBE_ROOT / "probe" / "probe_mcp.py").resolve()), reported_context["script_path"])
        self.assertEqual(str(PROBE_ROOT.parent.resolve()), reported_context["cwd"])
        self.assertEqual(reported_context, tool_result["structuredContent"])

    def test_unknown_method_returns_method_not_found(self):
        response = self.run_probe(json.dumps({"jsonrpc": "2.0", "id": 4, "method": "unknown"}))[0]

        self.assertEqual(4, response["id"])
        self.assertEqual({"code": -32601, "message": "Method not found"}, response["error"])

    def test_malformed_json_returns_invalid_request(self):
        response = self.run_probe("{")[0]

        self.assertIsNone(response["id"])
        self.assertEqual({"code": -32600, "message": "Invalid Request"}, response["error"])

    def test_non_object_and_missing_method_requests_return_invalid_request(self):
        responses = self.run_probe("[]", json.dumps({"jsonrpc": "2.0", "id": 5}))

        self.assertEqual([None, 5], [response["id"] for response in responses])
        for response in responses:
            self.assertEqual({"code": -32600, "message": "Invalid Request"}, response["error"])
