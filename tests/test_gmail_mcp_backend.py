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
from tools.gmail import gmail_legacy_backend
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

    def test_explicit_legacy_backend_routes_thread_context_methods_without_fallback(self):
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
                        "gmail_list_threads",
                        {"query": "case", "max_results": 10},
                    )
                    return result, legacy

        result, legacy = asyncio.run(exercise())
        self.assertEqual(result, "legacy-result")
        legacy.assert_awaited_once_with(
            "gmail_list_threads",
            {"query": "case", "max_results": 10},
        )

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
    def test_tool_names_and_input_schemas_preserve_legacy_tools_and_append_context_tools(self):
        tools = asyncio.run(gmail_mcp_server.list_tools())
        self.assertEqual(
            [tool.name for tool in tools],
            [
                "gmail_search",
                "gmail_read",
                "gmail_send",
                "gmail_list_threads",
                "gmail_read_thread_page",
            ],
        )
        self.assertEqual(tools[0].inputSchema, {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        })
        self.assertEqual(tools[1].inputSchema, {
            "type": "object",
            "properties": {"message_id": {"type": "string", "description": "Email message ID"}},
            "required": ["message_id"],
        })
        self.assertEqual(tools[2].inputSchema, {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Subject"},
                "body": {"type": "string", "description": "Email body content"},
            },
            "required": ["to", "subject", "body"],
        })
        self.assertEqual(
            tools[3].description,
            "Enumerate one complete page of Gmail thread IDs for an exact record ID within a shared collection snapshot",
        )
        self.assertEqual(
            tools[3].inputSchema,
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Exact case or related record ID"},
                    "snapshot_before": {
                        "type": "string",
                        "description": "Shared RFC3339 snapshot; empty only on the first page",
                    },
                    "page_token": {
                        "type": "string",
                        "description": "Opaque Gmail page token from the prior response",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Maximum thread IDs returned in this page",
                    },
                },
                "required": ["query", "max_results"],
            },
        )
        self.assertEqual(
            tools[4].inputSchema,
            {
                "type": "object",
                "properties": {
                    "thread_id": {"type": "string", "description": "Gmail thread ID"},
                    "snapshot_before": {
                        "type": "string",
                        "description": "Shared RFC3339 collection snapshot",
                    },
                    "cursor": {
                        "type": "string",
                        "description": "Opaque cursor from the prior response",
                    },
                },
                "required": ["thread_id", "snapshot_before"],
            },
        )

    def test_call_tool_maps_arguments_to_broker_contract(self):
        async def exercise():
            cases = (
                ("gmail_search", {"query": "case"}, {"query": "case"}),
                ("gmail_read", {"message_id": "message-1"}, {"message_id": "message-1"}),
                (
                    "gmail_send",
                    {"to": "recipient@example.com", "subject": "subject", "body": "body"},
                    {"to": "recipient@example.com", "subject": "subject", "body": "body"},
                ),
                (
                    "gmail_list_threads",
                    {
                        "query": "1-23508794022",
                        "snapshot_before": "",
                        "page_token": "",
                        "max_results": 100,
                    },
                    {
                        "query": "1-23508794022",
                        "snapshot_before": "",
                        "page_token": "",
                        "max_results": 100,
                    },
                ),
                (
                    "gmail_read_thread_page",
                    {
                        "thread_id": "thread-1",
                        "snapshot_before": "2026-08-04T10:15:30Z",
                        "cursor": "",
                    },
                    {
                        "thread_id": "thread-1",
                        "snapshot_before": "2026-08-04T10:15:30Z",
                        "cursor": "",
                    },
                ),
            )
            for name, arguments, expected_params in cases:
                with self.subTest(name=name):
                    with patch.object(gmail_mcp_server, "query_backend", return_value="ok") as query:
                        result = await gmail_mcp_server.call_tool(name, arguments)
                    self.assertEqual(result[0].text, "ok")
                    query.assert_awaited_once_with(name, expected_params)

        asyncio.run(exercise())


class LegacyBackendThreadContextTests(unittest.TestCase):
    def test_list_threads_matches_the_broker_url_contract(self):
        async def exercise():
            with patch.object(gmail_legacy_backend, "query_apps_script", return_value="ok") as query:
                result = await gmail_legacy_backend.legacy_query(
                    "gmail_list_threads",
                    {
                        "query": "case & owner",
                        "snapshot_before": "2026-08-05T00:00:00Z",
                        "page_token": "next-page",
                        "max_results": 50,
                    },
                )
                return result, query

        result, query = asyncio.run(exercise())
        self.assertEqual(result, "ok")
        query.assert_awaited_once_with(
            "list_threads",
            "&q=case%20%26%20owner&snapshot_before=2026-08-05T00%3A00%3A00Z&page_token=next-page&max_results=50",
        )

    def test_read_thread_page_omits_an_empty_optional_cursor(self):
        async def exercise():
            with patch.object(gmail_legacy_backend, "query_apps_script", return_value="ok") as query:
                result = await gmail_legacy_backend.legacy_query(
                    "gmail_read_thread_page",
                    {"thread_id": "thread-1", "snapshot_before": "snapshot", "cursor": ""},
                )
                return result, query

        result, query = asyncio.run(exercise())
        self.assertEqual(result, "ok")
        query.assert_awaited_once_with(
            "read_thread_page",
            "&thread_id=thread-1&snapshot_before=snapshot",
        )

    def test_read_thread_page_preserves_a_populated_cursor(self):
        async def exercise():
            with patch.object(gmail_legacy_backend, "query_apps_script", return_value="ok") as query:
                result = await gmail_legacy_backend.legacy_query(
                    "gmail_read_thread_page",
                    {
                        "thread_id": "thread-1",
                        "snapshot_before": "snapshot",
                        "cursor": "cursor 2",
                    },
                )
                return result, query

        result, query = asyncio.run(exercise())
        self.assertEqual(result, "ok")
        query.assert_awaited_once_with(
            "read_thread_page",
            "&thread_id=thread-1&snapshot_before=snapshot&cursor=cursor%202",
        )

    def test_thread_context_rejects_invalid_parameters(self):
        invalid_calls = (
            ("gmail_list_threads", {"query": "case", "max_results": True}),
            ("gmail_list_threads", {"query": "case"}),
            ("gmail_list_threads", {"query": "case", "max_results": 0}),
            ("gmail_list_threads", {"query": "case", "max_results": 101}),
            ("gmail_list_threads", {"max_results": 1}),
            ("gmail_list_threads", {"query": "", "max_results": 1}),
            ("gmail_list_threads", {"query": "case", "snapshot_before": 1, "max_results": 1}),
            ("gmail_list_threads", {"query": "case", "page_token": 1, "max_results": 1}),
            ("gmail_read_thread_page", {"snapshot_before": "snapshot"}),
            ("gmail_read_thread_page", {"thread_id": "thread"}),
            ("gmail_read_thread_page", {"thread_id": "", "snapshot_before": "snapshot"}),
            ("gmail_read_thread_page", {"thread_id": "thread", "snapshot_before": ""}),
            ("gmail_read_thread_page", {"thread_id": "thread", "snapshot_before": "snapshot", "cursor": 1}),
        )
        for method, params in invalid_calls:
            with self.subTest(method=method, params=params):
                with self.assertRaises(ValueError):
                    asyncio.run(gmail_legacy_backend.legacy_query(method, params))


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
            (
                ["list-threads", "1-23508794022", "", "", "100"],
                (
                    "gmail_list_threads",
                    {
                        "query": "1-23508794022",
                        "snapshot_before": "",
                        "page_token": "",
                        "max_results": 100,
                    },
                ),
            ),
            (
                ["read-thread-page", "thread-1", "2026-08-04T10:15:30Z", ""],
                (
                    "gmail_read_thread_page",
                    {
                        "thread_id": "thread-1",
                        "snapshot_before": "2026-08-04T10:15:30Z",
                        "cursor": "",
                    },
                ),
            ),
        ):
            with self.subTest(argv=argv):
                calls = []
                with patch.object(gmail_mcp_server, "query_backend", side_effect=fake_query):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        asyncio.run(gmail_mcp_server.main(argv))
                self.assertEqual(calls, [expected])
                self.assertEqual(stdout.getvalue().strip(), "result")

    def test_list_threads_cli_rejects_invalid_max_results(self):
        async def fake_query(method, params):
            calls.append((method, params))
            return "result"

        for invalid in (True, "True", "not-a-number", "0", "101"):
            with self.subTest(invalid=invalid):
                calls = []
                with patch.object(gmail_mcp_server, "query_backend", side_effect=fake_query):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        asyncio.run(
                            gmail_mcp_server.main(
                                ["list-threads", "1-23508794022", "", "", invalid]
                            )
                        )
                self.assertEqual(calls, [])
                self.assertIn("<search|read|send|list-threads|read-thread-page>", stdout.getvalue())

    def test_direct_help_is_sanitized_and_does_not_import_a_browser(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, "tools/gmail/gmail_mcp_server.py", "--help"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("<search|read|send|list-threads|read-thread-page>", completed.stdout)
        self.assertNotIn("playwright", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
