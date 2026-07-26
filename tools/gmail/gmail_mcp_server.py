import sys
import json
import os
import asyncio
import urllib.parse
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from playwright.async_api import async_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PROFILE_DIR = os.path.join(os.path.dirname(__file__), "chrome_profile")
APPS_SCRIPT_URL = "https://script.google.com/a/macros/avaya.com/s/AKfycbwfqUGLMBppaPEtdzAC74_TeT34shpYkIVv5FMY1JjhqPDH0MXEp-WdeTOp8zmCDL0F/exec"

app = Server("gmail")

async def query_apps_script(action, extra_params=""):
    url = f"{APPS_SCRIPT_URL}?action={action}{extra_params}"
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        body_text = await page.text_content("body")
        await context.close()
        return body_text

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
                "required": ["query"]
            }
        ),
        Tool(
            name="gmail_read",
            description="Read an email message by message ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Email message ID"}
                },
                "required": ["message_id"]
            }
        ),
        Tool(
            name="gmail_send",
            description="Send an email",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Subject"},
                    "body": {"type": "string", "description": "Email body content"}
                },
                "required": ["to", "subject", "body"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "gmail_search":
        q = arguments.get("query", "is:unread")
        res = await query_apps_script("search", f"&q={urllib.parse.quote(q)}")
        return [TextContent(type="text", text=res)]
    elif name == "gmail_read":
        msg_id = arguments.get("message_id", "")
        res = await query_apps_script("read", f"&id={msg_id}")
        return [TextContent(type="text", text=res)]
    elif name == "gmail_send":
        to = arguments.get("to", "")
        subject = arguments.get("subject", "")
        body = arguments.get("body", "")
        res = await query_apps_script("send", f"&to={urllib.parse.quote(to)}&subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}")
        return [TextContent(type="text", text=res)]
    raise ValueError(f"Unknown tool: {name}")

async def main():
    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action == "search":
            q = sys.argv[2] if len(sys.argv) > 2 else "is:unread"
            res = await query_apps_script("search", f"&q={urllib.parse.quote(q)}")
            print(res)
        elif action == "read":
            msg_id = sys.argv[2] if len(sys.argv) > 2 else ""
            res = await query_apps_script("read", f"&id={msg_id}")
            print(res)
        elif action == "send":
            to = sys.argv[2]
            subject = sys.argv[3]
            body = sys.argv[4]
            res = await query_apps_script("send", f"&to={urllib.parse.quote(to)}&subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}")
            print(res)
        return

    async with stdio_server() as streams:
        await app.run(
            streams[0],
            streams[1],
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
