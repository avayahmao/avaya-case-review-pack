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

    backend = get_backend_name()
    if backend == DEFAULT_BACKEND:
        try:
            result = await asyncio.to_thread(BrokerClient().request, method, params)
        except BrokerClientError as error:
            return _broker_error_text(error)
        if not isinstance(result, str):
            return "[Gmail broker error: APP_ERROR] Gmail broker returned an invalid result"
        return result
    if backend == LEGACY_BACKEND:
        return await legacy_query(method, params)
    raise RuntimeError(f"Unsupported GMAIL_BACKEND: {backend}")


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
    else:
        raise ValueError(f"Unknown tool: {name}")
    result = await query_backend(name, params)
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
        else:
            print("Usage: python gmail_mcp_server.py <search|read|send> [args...]")
            return
        print(result)
        return

    async with stdio_server() as streams:
        await app.run(
            streams[0],
            streams[1],
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())


__all__ = [
    "DEFAULT_BACKEND",
    "LEGACY_BACKEND",
    "app",
    "call_tool",
    "get_backend_name",
    "list_tools",
    "main",
    "query_backend",
]
