"""Explicit one-release fallback for the legacy Playwright Gmail backend.

The module deliberately imports Playwright inside the request function.  The
default Edge broker path therefore keeps the MCP process free of browser
imports and cannot accidentally create a second browser owner.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


PROFILE_DIR = os.path.join(os.path.dirname(__file__), "chrome_profile")
APPS_SCRIPT_URL = (
    "https://script.google.com/a/macros/avaya.com/s/"
    "AKfycbwfqUGLMBppaPEtdzAC74_TeT34shpYkIVv5FMY1JjhqPDH0MXEp-WdeTOp8zmCDL0F/exec"
)


async def query_apps_script(action: str, extra_params: str = "") -> str:
    """Run one legacy Playwright request with the existing profile."""

    # Keep this import lazy: broker mode must not import or start Playwright.
    from playwright.async_api import async_playwright

    url = f"{APPS_SCRIPT_URL}?action={action}{extra_params}"
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        body_text = ""
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url)
            await page.wait_for_load_state("networkidle")
            if not page.is_closed():
                body_text = await page.text_content("body") or ""
        finally:
            try:
                await context.close()
            except Exception:
                pass
        return body_text


def _required_string(params: dict[str, Any], name: str, default: str = "") -> str:
    value = params.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"Gmail parameter {name} must be a string")
    return value


async def legacy_query(method: str, params: dict[str, Any]) -> str:
    """Map the stable Gmail method contract to the legacy Apps Script URL."""

    if not isinstance(params, dict):
        raise ValueError("Gmail request parameters must be an object")
    if method == "gmail_search":
        query = _required_string(params, "query", "is:unread")
        return await query_apps_script("search", f"&q={urllib.parse.quote(query)}")
    if method == "gmail_read":
        message_id = _required_string(params, "message_id")
        return await query_apps_script("read", f"&id={message_id}")
    if method == "gmail_send":
        to = _required_string(params, "to")
        subject = _required_string(params, "subject")
        body = _required_string(params, "body")
        return await query_apps_script(
            "send",
            "&to="
            + urllib.parse.quote(to)
            + "&subject="
            + urllib.parse.quote(subject)
            + "&body="
            + urllib.parse.quote(body),
        )
    raise ValueError(f"Unsupported Gmail method: {method}")


__all__ = ["APPS_SCRIPT_URL", "PROFILE_DIR", "legacy_query", "query_apps_script"]
