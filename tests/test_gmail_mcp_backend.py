import asyncio
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.gmail import gmail_mcp_server
from tools.gmail.gmail_broker_client import BrokerClientError


class RecordingBrokerClient:
    instances = []

    def __init__(self):
        self.calls = []
        self.__class__.instances.append(self)

    def request(self, method, params):
        self.calls.append((method, params))
        return "broker-result"


class BackendRoutingTests(unittest.TestCase):
    def setUp(self):
        RecordingBrokerClient.instances.clear()

    def test_default_backend_is_edge_broker_and_does_not_import_playwright(self):
        root = Path(__file__).resolve().parents[1]
        code = (
            "import sys; "
            "from tools.gmail import gmail_mcp_server as m; "
            "print(m.get_backend_name()); "
            "print(any(name.startswith('playwright') for name in sys.modules))"
        )
        env = os.environ.copy()
        env.pop("GMAIL_BACKEND", None)
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), ["edge_broker", "False"])

    def test_edge_broker_routes_method_and_parameters(self):
        async def exercise():
            with patch.object(gmail_mcp_server, "BrokerClient", RecordingBrokerClient):
                with patch.object(gmail_mcp_server, "get_backend_name", return_value="edge_broker"):
                    return await gmail_mcp_server.query_backend(
                        "gmail_search", {"query": "1-23508794022"}
                    )

        self.assertEqual(asyncio.run(exercise()), "broker-result")
        self.assertEqual(
            RecordingBrokerClient.instances[0].calls,
            [("gmail_search", {"query": "1-23508794022"})],
        )

    def test_legacy_backend_is_explicit_and_does_not_fallback(self):
        async def exercise():
            with patch.object(
                gmail_mcp_server,
                "get_backend_name",
                return_value="legacy_playwright",
            ):
                with patch.object(
                    gmail_mcp_server,
                    "legacy_query",
                    return_value="legacy-result",
                ) as legacy:
                    result = await gmail_mcp_server.query_backend(
                        "gmail_read", {"message_id": "message-1"}
                    )
                    return result, legacy

        result, legacy = asyncio.run(exercise())
        self.assertEqual(result, "legacy-result")
        legacy.assert_awaited_once_with("gmail_read", {"message_id": "message-1"})

    def test_unknown_backend_is_rejected_without_fallback(self):
        async def exercise():
            with patch.object(
                gmail_mcp_server,
                "get_backend_name",
                return_value="unexpected",
            ):
                with patch.object(gmail_mcp_server, "legacy_query") as legacy:
                    with self.assertRaisesRegex(RuntimeError, "Unsupported GMAIL_BACKEND"):
                        await gmail_mcp_server.query_backend("gmail_search", {"query": "case"})
                    legacy.assert_not_called()

        asyncio.run(exercise())

    def test_broker_error_becomes_explicit_text_and_not_login_html(self):
        async def exercise():
            with patch.object(gmail_mcp_server, "BrokerClient") as client_type:
                client_type.return_value.request.side_effect = BrokerClientError(
                    "AUTH_REQUIRED", "<html>login page secret"
                )
                with patch.object(gmail_mcp_server, "get_backend_name", return_value="edge_broker"):
                    return await gmail_mcp_server.call_tool(
                        "gmail_search", {"query": "case"}
                    )

        response = asyncio.run(exercise())
        self.assertEqual(len(response), 1)
        text = response[0].text
        self.assertIn("AUTH_REQUIRED", text)
        self.assertNotIn("<html>", text)
        self.assertNotIn("login page secret", text)


class ToolContractTests(unittest.TestCase):
    def test_tool_names_and_input_schemas_remain_unchanged(self):
        tools = asyncio.run(gmail_mcp_server.list_tools())
        self.assertEqual([tool.name for tool in tools], [
            "gmail_search",
            "gmail_read",
            "gmail_send",
        ])
        self.assertEqual(tools[0].inputSchema["required"], ["query"])
        self.assertEqual(tools[1].inputSchema["required"], ["message_id"])
        self.assertEqual(tools[2].inputSchema["required"], ["to", "subject", "body"])

    def test_call_tool_maps_arguments_to_existing_broker_contract(self):
        async def exercise():
            with patch.object(gmail_mcp_server, "query_backend", return_value="ok") as query:
                result = await gmail_mcp_server.call_tool(
                    "gmail_send",
                    {"to": "recipient@example.com", "subject": "subject", "body": "body"},
                )
                return result, query

        result, query = asyncio.run(exercise())
        self.assertEqual(result[0].text, "ok")
        query.assert_awaited_once_with(
            "gmail_send",
            {"to": "recipient@example.com", "subject": "subject", "body": "body"},
        )


class DirectCliTests(unittest.TestCase):
    def test_direct_cli_modes_route_through_selected_backend(self):
        async def fake_query(method, params):
            calls.append((method, params))
            return "result"

        for argv, expected in (
            (["search", "case"], ("gmail_search", {"query": "case"})),
            (["read", "message-1"], ("gmail_read", {"message_id": "message-1"})),
            (["send", "to@example.com", "subject", "body"], (
                "gmail_send",
                {"to": "to@example.com", "subject": "subject", "body": "body"},
            )),
        ):
            with self.subTest(argv=argv):
                calls = []
                with patch.object(gmail_mcp_server, "query_backend", side_effect=fake_query):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        asyncio.run(gmail_mcp_server.main(argv))
                self.assertEqual(calls, [expected])
                self.assertEqual(stdout.getvalue().strip(), "result")


if __name__ == "__main__":
    unittest.main()
