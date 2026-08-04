"""Gmail MCP stdio adapter with an Edge-broker default and explicit rollback."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from tools.gmail.gmail_broker_client import BrokerClient, BrokerClientError
from tools.gmail.gmail_legacy_backend import legacy_query


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


DEFAULT_BACKEND = "edge_broker"
LEGACY_BACKEND = "legacy_playwright"
_CONTEXT_METHODS = frozenset({"gmail_list_threads", "gmail_read_thread_page"})
_CONTEXT_BACKEND_ERROR_TEXT = (
    "[Gmail backend error: APP_ERROR] Gmail backend operation failed"
)
_USAGE = (
    "Usage: python gmail_mcp_server.py "
    "<search|read|send|list-threads|read-thread-page> [args...]\n"
    "list-threads first-page probes: --snapshot-before=<value> "
    "--page-token=<value> --max-results=<1-100>"
)
_BROKER_ERROR_MESSAGES = {
    "AUTH_REQUIRED": "Interactive Gmail authentication is required; run gmail_brokerctl.py login",
    "LOGIN_IN_PROGRESS": "Interactive Gmail login is already in progress",
    "REQUEST_TIMEOUT": "Gmail broker request timed out",
    "BROWSER_ERROR": "Managed Edge browser operation failed",
    "BROKER_UNAVAILABLE": "Gmail Edge broker is unavailable",
    "BROKER_START_TIMEOUT": "Gmail Edge broker did not become ready",
    "BROKER_PROTOCOL_MISMATCH": "Gmail Edge broker protocol mismatch",
    "RESPONSE_TOO_LARGE": "Gmail broker response exceeded the size limit",
    "INVALID_REQUEST": "Gmail broker rejected the request",
    "APP_ERROR": "Gmail broker application error",
}


def get_backend_name() -> str:
    """Read the explicit backend switch for each MCP process."""

    return os.environ.get("GMAIL_BACKEND", DEFAULT_BACKEND)


def _broker_error_text(error: BrokerClientError) -> str:
    code = error.code if error.code in _BROKER_ERROR_MESSAGES else "APP_ERROR"
    return f"[Gmail broker error: {code}] {_BROKER_ERROR_MESSAGES[code]}"


async def query_backend(method: str, params: dict[str, Any]) -> str:
    """Execute a Gmail method through the selected backend without fallback."""

    try:
        backend = get_backend_name()
        if backend == DEFAULT_BACKEND:
            result = await asyncio.to_thread(BrokerClient().request, method, params)
            if not isinstance(result, str):
                return "[Gmail broker error: APP_ERROR] Gmail broker returned an invalid result"
            return result
        if backend == LEGACY_BACKEND:
            return await legacy_query(method, params)
        raise RuntimeError(f"Unsupported GMAIL_BACKEND: {backend}")
    except BrokerClientError as error:
        return _broker_error_text(error)
    except Exception:
        if method in _CONTEXT_METHODS:
            return _CONTEXT_BACKEND_ERROR_TEXT
        raise


def _parse_max_results(value: Any) -> int:
    """Convert a direct-CLI page size without accepting booleans or fractions."""

    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("max_results must be an integer")
    try:
        max_results = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("max_results must be an integer") from error
    if not 1 <= max_results <= 100:
        raise ValueError("max_results must be between 1 and 100")
    return max_results


def _parse_list_threads_args(args: list[Any]) -> dict[str, Any]:
    """Parse positional and PowerShell-safe named list-threads arguments."""

    if len(args) < 2 or not isinstance(args[1], str) or not args[1].strip():
        raise ValueError("query is required")
    query = args[1]
    remaining = list(args[2:])
    if any(isinstance(value, str) and value.startswith("--") for value in remaining):
        snapshot_before = ""
        page_token = ""
        max_results_value: Any = "100"
        seen: set[str] = set()
        index = 0
        while index < len(remaining):
            value = remaining[index]
            if not isinstance(value, str):
                raise ValueError("list-threads options must be strings")
            if value.startswith("--snapshot-before="):
                option = "snapshot_before"
                parsed_value = value.split("=", 1)[1]
            elif value.startswith("--page-token="):
                option = "page_token"
                parsed_value = value.split("=", 1)[1]
            elif value.startswith("--max-results="):
                option = "max_results"
                parsed_value = value.split("=", 1)[1]
            elif value in {"--snapshot-before", "--page-token", "--max-results"}:
                option = value[2:].replace("-", "_")
                index += 1
                if index >= len(remaining) or not isinstance(remaining[index], str):
                    raise ValueError(f"{value} requires a value")
                parsed_value = remaining[index]
            else:
                raise ValueError("unknown list-threads option")
            if option in seen:
                raise ValueError(f"duplicate {option} option")
            seen.add(option)
            if option == "snapshot_before":
                snapshot_before = parsed_value
            elif option == "page_token":
                page_token = parsed_value
            else:
                max_results_value = parsed_value
            index += 1
        max_results = _parse_max_results(max_results_value)
    else:
        if len(remaining) > 3:
            raise ValueError("too many list-threads arguments")
        snapshot_before = remaining[0] if len(remaining) > 0 else ""
        page_token = remaining[1] if len(remaining) > 1 else ""
        max_results = _parse_max_results(remaining[2] if len(remaining) > 2 else "100")
    return {
        "query": query,
        "snapshot_before": snapshot_before,
        "page_token": page_token,
        "max_results": max_results,
    }


def _is_context_error(result: str) -> bool:
    return result.startswith(("[Gmail backend error:", "[Gmail broker error:"))


app = Server("gmail")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="gmail_search",
            description="Search Gmail inbox using queries like 'is:unread', 'from:boss', or case IDs like '1-23659220672'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="gmail_read",
            description="Read an email message by message ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Email message ID"}
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="gmail_send",
            description="Send an email",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Subject"},
                    "body": {"type": "string", "description": "Email body content"},
                },
                "required": ["to", "subject", "body"],
            },
        ),
        Tool(
            name="gmail_list_threads",
            description=(
                "Enumerate one complete page of Gmail thread IDs for an exact record ID "
                "within a shared collection snapshot"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Exact case or related record ID",
                    },
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
        ),
        Tool(
            name="gmail_read_thread_page",
            description=(
                "Read one page of normalized Gmail message-body segments for a thread "
                "within a shared collection snapshot"
            ),
            inputSchema={
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
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]):
    if name == "gmail_search":
        params = {"query": arguments.get("query", "is:unread")}
    elif name == "gmail_read":
        params = {"message_id": arguments.get("message_id", "")}
    elif name == "gmail_send":
        params = {
            "to": arguments.get("to", ""),
            "subject": arguments.get("subject", ""),
            "body": arguments.get("body", ""),
        }
    elif name == "gmail_list_threads":
        params = {
            "query": arguments.get("query", ""),
            "snapshot_before": arguments.get("snapshot_before", ""),
            "page_token": arguments.get("page_token", ""),
            "max_results": arguments.get("max_results", 100),
        }
    elif name == "gmail_read_thread_page":
        params = {
            "thread_id": arguments.get("thread_id", ""),
            "snapshot_before": arguments.get("snapshot_before", ""),
            "cursor": arguments.get("cursor", ""),
        }
    else:
        raise ValueError(f"Unknown tool: {name}")
    try:
        result = await query_backend(name, params)
    except Exception:
        if name not in _CONTEXT_METHODS:
            raise
        result = _CONTEXT_BACKEND_ERROR_TEXT
    return [TextContent(type="text", text=result)]


async def main(argv: list[str] | None = None):
    args = sys.argv[1:] if argv is None else argv
    if args:
        action = args[0]
        if action == "search":
            query = args[1] if len(args) > 1 else "is:unread"
            result = await query_backend("gmail_search", {"query": query})
        elif action == "read":
            message_id = args[1] if len(args) > 1 else ""
            result = await query_backend("gmail_read", {"message_id": message_id})
        elif action == "send":
            result = await query_backend(
                "gmail_send",
                {"to": args[1], "subject": args[2], "body": args[3]},
            )
        elif action == "list-threads":
            try:
                params = _parse_list_threads_args(args)
            except ValueError:
                print(_USAGE)
                return 2
            try:
                result = await query_backend("gmail_list_threads", params)
            except Exception:
                print(_CONTEXT_BACKEND_ERROR_TEXT)
                return 1
            print(result)
            return 1 if _is_context_error(result) else 0
        elif action == "read-thread-page":
            thread_id = args[1] if len(args) > 1 else ""
            snapshot_before = args[2] if len(args) > 2 else ""
            cursor = args[3] if len(args) > 3 else ""
            try:
                result = await query_backend(
                    "gmail_read_thread_page",
                    {
                        "thread_id": thread_id,
                        "snapshot_before": snapshot_before,
                        "cursor": cursor,
                    },
                )
            except Exception:
                print(_CONTEXT_BACKEND_ERROR_TEXT)
                return 1
            print(result)
            return 1 if _is_context_error(result) else 0
        elif action in {"--help", "-h"}:
            print(_USAGE)
            return 0
        else:
            print(_USAGE)
            return 2
        print(result)
        return 0

    async with stdio_server() as streams:
        await app.run(
            streams[0],
            streams[1],
            app.create_initialization_options(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


__all__ = [
    "DEFAULT_BACKEND",
    "LEGACY_BACKEND",
    "_CONTEXT_BACKEND_ERROR_TEXT",
    "_parse_list_threads_args",
    "_parse_max_results",
    "app",
    "call_tool",
    "get_backend_name",
    "list_tools",
    "main",
    "query_backend",
]
