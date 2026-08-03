"""Operator control CLI for the per-user Gmail Edge broker."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.gmail.gmail_broker_client import BrokerClient, BrokerClientError


EXIT_SUCCESS = 0
EXIT_AUTH_REQUIRED = 10
EXIT_UNAVAILABLE = 20
EXIT_INVALID = 30

_HEALTH_INTEGER_FIELDS = frozenset(
    {
        "protocol_version",
        "pid",
        "queue_depth",
        "request_count",
        "browser_start_count",
        "browser_crash_count",
        "current_browser_concurrency",
        "max_browser_concurrency",
        "uptime_seconds",
    }
)
_HEALTH_STRING_FIELDS = frozenset({"edge_state", "build_id", "instance_id"})
_AUTH_REQUIRED_STATES = frozenset(
    {"AUTH_REQUIRED", "AUTH_REQUIRED_MICROSOFT", "AUTH_REQUIRED_GOOGLE"}
)
_ERROR_CONTRACT = {
    "AUTH_REQUIRED": (
        EXIT_AUTH_REQUIRED,
        "Gmail authentication is required; run gmail_brokerctl.py login",
    ),
    "BROKER_START_TIMEOUT": (
        EXIT_UNAVAILABLE,
        "Gmail Edge broker did not become ready",
    ),
    "BROKER_UNAVAILABLE": (EXIT_UNAVAILABLE, "Gmail Edge broker is unavailable"),
    "REQUEST_TIMEOUT": (EXIT_UNAVAILABLE, "Gmail Edge broker request timed out"),
    "BROWSER_ERROR": (EXIT_UNAVAILABLE, "Managed Edge browser operation failed"),
    "BROKER_PROTOCOL_MISMATCH": (
        EXIT_INVALID,
        "Gmail Edge broker protocol mismatch",
    ),
    "RESPONSE_TOO_LARGE": (
        EXIT_INVALID,
        "Gmail Edge broker response exceeded the size limit",
    ),
    "APP_ERROR": (EXIT_INVALID, "Gmail broker application error"),
    "INVALID_REQUEST": (EXIT_INVALID, "Gmail broker request was invalid"),
    "LOGIN_IN_PROGRESS": (
        EXIT_INVALID,
        "Interactive Gmail login is already in progress",
    ),
}


class _InvalidResultError(ValueError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control the Gmail Edge broker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show broker and authentication status")
    subparsers.add_parser("diagnostics", help="Show sanitized broker diagnostics")
    subparsers.add_parser("login", help="Complete interactive Gmail authentication")
    subparsers.add_parser("start", help="Ensure the broker is running")
    subparsers.add_parser("stop", help="Stop the running broker")
    return parser


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))


def _sanitize_result(command: str, result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise _InvalidResultError
    if command in {"status", "diagnostics", "start"}:
        sanitized: dict[str, Any] = {}
        for field in _HEALTH_INTEGER_FIELDS:
            if field in result:
                value = result[field]
                if type(value) is not int or value < 0:
                    raise _InvalidResultError
                sanitized[field] = value
        for field in _HEALTH_STRING_FIELDS:
            if field in result:
                value = result[field]
                if not isinstance(value, str) or not value:
                    raise _InvalidResultError
                sanitized[field] = value
        return sanitized
    if command == "login":
        state = result.get("state")
        if not isinstance(state, str) or not state:
            raise _InvalidResultError
        return {"state": state}
    if command == "stop":
        stopping = result.get("stopping")
        if type(stopping) is not bool:
            raise _InvalidResultError
        return {"stopping": stopping}
    raise _InvalidResultError


def _success_exit_code(command: str, result: dict[str, Any]) -> int:
    if command not in {"status", "diagnostics", "start"}:
        return EXIT_SUCCESS
    edge_state = result.get("edge_state")
    if edge_state in _AUTH_REQUIRED_STATES:
        return EXIT_AUTH_REQUIRED
    if edge_state == "BROWSER_ERROR":
        return EXIT_UNAVAILABLE
    if edge_state == "APP_ERROR":
        return EXIT_INVALID
    return EXIT_SUCCESS


def _print_client_error(error: BrokerClientError) -> int:
    exit_code, message = _ERROR_CONTRACT.get(
        error.code,
        (EXIT_INVALID, "Gmail broker operation failed"),
    )
    code = error.code if error.code in _ERROR_CONTRACT else "APP_ERROR"
    _print_json({"ok": False, "code": code, "message": message})
    return exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    client: BrokerClient | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    broker_client = BrokerClient() if client is None else client
    try:
        if args.command == "login":
            result = broker_client.request("auth_login", {})
        elif args.command == "stop":
            result = broker_client.request_existing("shutdown", {})
        else:
            result = broker_client.request("health", {})
        sanitized = _sanitize_result(args.command, result)
    except BrokerClientError as error:
        return _print_client_error(error)
    except _InvalidResultError:
        _print_json(
            {
                "ok": False,
                "code": "INVALID_REQUEST",
                "message": "Broker returned an invalid result",
            }
        )
        return EXIT_INVALID
    except Exception:
        _print_json(
            {
                "ok": False,
                "code": "APP_ERROR",
                "message": "Gmail broker operation failed",
            }
        )
        return EXIT_INVALID
    _print_json({"ok": True, "command": args.command, "result": sanitized})
    return _success_exit_code(args.command, sanitized)


if __name__ == "__main__":
    raise SystemExit(main())
