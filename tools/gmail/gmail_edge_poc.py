"""Isolated Managed Edge authentication proof of concept for Gmail MCP.

This module never reads or prints Gmail response bodies. It is not imported by
the production Gmail MCP server.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

if __package__:
    from .gmail_edge_common import (
        APP_SCRIPT_URL,
        AuthState,
        ProbeResult,
        build_action_url,
        classify_response,
        validate_profile_path,
    )
else:
    from gmail_edge_common import (
        APP_SCRIPT_URL,
        AuthState,
        ProbeResult,
        build_action_url,
        classify_response,
        validate_profile_path,
    )

from playwright.async_api import (
    BrowserContext,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


PROBE_QUERY = "subject:__avaya_gmail_edge_poc__"


def exit_code_for(state: AuthState) -> int:
    if state is AuthState.AUTHENTICATED:
        return 0
    if state in {
        AuthState.AUTH_REQUIRED_MICROSOFT,
        AuthState.AUTH_REQUIRED_GOOGLE,
    }:
        return 10
    if state is AuthState.BROWSER_ERROR:
        return 20
    return 30


def build_probe_url(base_url: str = APP_SCRIPT_URL) -> str:
    return build_action_url(
        "search",
        {"q": PROBE_QUERY},
        base_url=base_url,
    )


def validate_repeat_count(count: int) -> int:
    if not 1 <= count <= 20:
        raise ValueError("repeat count must be between 1 and 20")
    return count


def summarize_results(results: list[ProbeResult]) -> dict[str, object]:
    auth_required = {
        AuthState.AUTH_REQUIRED_MICROSOFT,
        AuthState.AUTH_REQUIRED_GOOGLE,
    }
    errors = {
        AuthState.APP_ERROR,
        AuthState.BROWSER_ERROR,
        AuthState.UNKNOWN,
    }
    return {
        "total": len(results),
        "authenticated": sum(
            result.state is AuthState.AUTHENTICATED for result in results
        ),
        "authentication_required": sum(
            result.state in auth_required for result in results
        ),
        "errors": sum(result.state in errors for result in results),
        "context_reused": True,
        "probes": [result.to_public_dict() for result in results],
    }


def _browser_error(elapsed_ms: int = 0) -> ProbeResult:
    return ProbeResult(
        state=AuthState.BROWSER_ERROR,
        http_status=None,
        final_host="",
        final_path="",
        body_length=0,
        elapsed_ms=elapsed_ms,
    )


async def poll_page_auth(
    page,
    http_status: int | None,
    *,
    timeout_seconds: int,
) -> ProbeResult:
    started = time.perf_counter()
    deadline = time.monotonic() + timeout_seconds
    last_result = _browser_error()
    while time.monotonic() < deadline:
        if page.is_closed():
            return _browser_error(
                round((time.perf_counter() - started) * 1000)
            )
        try:
            body = (await page.text_content("body") or "").strip()
        except Exception:
            # SSO replaces the document several times. A destroyed execution
            # context during navigation is expected and must not abort login.
            await page.wait_for_timeout(500)
            continue
        parsed = urlparse(page.url)
        last_result = ProbeResult(
            state=classify_response(page.url, http_status, body),
            http_status=http_status,
            final_host=parsed.netloc,
            final_path=parsed.path,
            body_length=len(body),
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )
        if last_result.state is AuthState.AUTHENTICATED:
            return last_result
        await page.wait_for_timeout(1000)
    return last_result


class ManagedEdgeSession:
    def __init__(self, profile_dir: Path, *, headless: bool) -> None:
        user_home = Path(os.environ.get("USERPROFILE", Path.home()))
        self.profile_dir = validate_profile_path(profile_dir, user_home)
        self.headless = headless
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "ManagedEdgeSession":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            self._context = (
                await self._playwright.chromium.launch_persistent_context(
                    channel="msedge",
                    user_data_dir=str(self.profile_dir),
                    headless=self.headless,
                )
            )
        except Exception:
            await self._playwright.stop()
            self._playwright = None
            raise
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def probe(self) -> ProbeResult:
        if self._context is None:
            raise RuntimeError("ManagedEdgeSession is not started")

        async with self._lock:
            started = time.perf_counter()
            page = await self._context.new_page()
            try:
                response = await page.goto(
                    build_probe_url(),
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                http_status = response.status if response else None
                parsed = urlparse(page.url)
                early_state = classify_response(page.url, http_status, "")
                if early_state in {
                    AuthState.AUTH_REQUIRED_MICROSOFT,
                    AuthState.AUTH_REQUIRED_GOOGLE,
                }:
                    return ProbeResult(
                        state=early_state,
                        http_status=http_status,
                        final_host=parsed.netloc,
                        final_path=parsed.path,
                        body_length=0,
                        elapsed_ms=round(
                            (time.perf_counter() - started) * 1000
                        ),
                    )
                try:
                    await page.wait_for_load_state("networkidle", timeout=30_000)
                except PlaywrightTimeoutError:
                    pass
                body = (await page.text_content("body") or "").strip()
                return ProbeResult(
                    state=classify_response(
                        page.url,
                        http_status,
                        body,
                    ),
                    http_status=http_status,
                    final_host=parsed.netloc,
                    final_path=parsed.path,
                    body_length=len(body),
                    elapsed_ms=round((time.perf_counter() - started) * 1000),
                )
            except Exception:
                return _browser_error(
                    round((time.perf_counter() - started) * 1000)
                )
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

    async def wait_for_login(self, timeout_seconds: int = 300) -> ProbeResult:
        if self._context is None:
            raise RuntimeError("ManagedEdgeSession is not started")

        async with self._lock:
            page = (
                self._context.pages[0]
                if self._context.pages
                else await self._context.new_page()
            )
            try:
                response = await page.goto(
                    build_probe_url(),
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                return await poll_page_auth(
                    page,
                    response.status if response else None,
                    timeout_seconds=timeout_seconds,
                )
            except Exception:
                return _browser_error(
                    round((time.perf_counter() - started) * 1000)
                )


def _default_profile() -> Path:
    user_home = Path(os.environ.get("USERPROFILE", Path.home()))
    return user_home / ".gemini/tools/gmail/edge_poc_profile"


def _print_json(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


async def _run_status(profile: Path) -> int:
    try:
        async with ManagedEdgeSession(profile, headless=True) as session:
            result = await session.probe()
    except Exception:
        result = _browser_error()
    _print_json(result.to_public_dict())
    return exit_code_for(result.state)


async def _run_repeat(profile: Path, count: int) -> int:
    count = validate_repeat_count(count)
    results: list[ProbeResult] = []
    try:
        async with ManagedEdgeSession(profile, headless=True) as session:
            for _ in range(count):
                results.append(await session.probe())
    except Exception:
        results.append(_browser_error())
    summary = summarize_results(results)
    _print_json(summary)
    if summary["authentication_required"]:
        return 10
    if any(result.state is AuthState.BROWSER_ERROR for result in results):
        return 20
    if summary["errors"]:
        return 30
    return 0


async def _run_login(profile: Path, timeout_seconds: int) -> int:
    print(
        "Complete corporate SSO/MFA in the Managed Edge window. "
        "Success is reported only after the Apps Script response is reached.",
        file=sys.stderr,
    )
    try:
        async with ManagedEdgeSession(profile, headless=False) as session:
            result = await session.wait_for_login(timeout_seconds)
    except Exception:
        result = _browser_error()
    _print_json(result.to_public_dict())
    return exit_code_for(result.state)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Isolated Managed Edge authentication PoC for Gmail MCP"
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=_default_profile(),
        help="Dedicated PoC profile path",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Run one headless auth probe")
    login = subparsers.add_parser("login", help="Complete interactive SSO")
    login.add_argument("--timeout", type=int, default=300)
    repeat = subparsers.add_parser(
        "repeat",
        help="Run repeated probes through one Edge context",
    )
    repeat.add_argument("--count", type=int, default=5)
    return parser


async def _dispatch(args: argparse.Namespace) -> int:
    profile = validate_profile_path(
        args.profile,
        Path(os.environ.get("USERPROFILE", Path.home())),
    )
    if args.command == "status":
        return await _run_status(profile)
    if args.command == "login":
        if not 1 <= args.timeout <= 900:
            raise ValueError("login timeout must be between 1 and 900 seconds")
        return await _run_login(profile, args.timeout)
    if args.command == "repeat":
        return await _run_repeat(profile, args.count)
    raise ValueError(f"Unknown command: {args.command}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_dispatch(args))
    except ValueError as error:
        parser.error(str(error))
    return 30


if __name__ == "__main__":
    raise SystemExit(main())
