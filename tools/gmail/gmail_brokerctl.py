"""Operator control CLI for the per-user Gmail Edge broker."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.gmail.gmail_broker_client import BrokerClient, BrokerClientError
from tools.gmail.cloud.bridge_identity import REQUIRED_CHECKS, validate_attestation


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
_REQUIRED_CAPABILITIES = frozenset(
    {
        "stable_snapshots",
        "thread_pagination",
        "cursor_pagination",
        "manifest_sha256",
        "body_bytes",
        "body_sha256",
    }
)
_CAPABILITIES_FIELDS = frozenset(
    {
        "success",
        "bridge_version",
        "contract_revision",
        "bridge_source_sha256",
        "capabilities",
    }
)
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE_SOURCE_PATH = Path(__file__).with_name("cloud") / "GmailMcpBridge.gs"
_PLUGIN_MANIFEST_PATH = _ROOT / ".codex-plugin" / "plugin.json"


class _InvalidResultError(ValueError):
    pass


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidResultError
        result[key] = value
    return result


def _plugin_version() -> str:
    try:
        manifest = json.loads(
            _PLUGIN_MANIFEST_PATH.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_fields,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, _InvalidResultError):
        raise _InvalidResultError from None
    if not isinstance(manifest, dict):
        raise _InvalidResultError
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise _InvalidResultError
    return version


def parse_capabilities_response(raw: object) -> dict[str, object]:
    """Strictly parse the public cloud compatibility response without echoing it."""

    if isinstance(raw, str):
        try:
            raw = json.loads(raw, object_pairs_hook=_reject_duplicate_fields)
        except (json.JSONDecodeError, _InvalidResultError):
            raise _InvalidResultError from None
    if not isinstance(raw, dict):
        raise _InvalidResultError
    if not _CAPABILITIES_FIELDS.issubset(raw):
        raise _InvalidResultError
    success = raw["success"]
    bridge_version = raw["bridge_version"]
    contract_revision = raw["contract_revision"]
    source_digest = raw["bridge_source_sha256"]
    capabilities = raw["capabilities"]
    if type(success) is not bool or not success:
        raise _InvalidResultError
    if type(bridge_version) is not int or type(contract_revision) is not int:
        raise _InvalidResultError
    if not isinstance(source_digest, str) or not _DIGEST_RE.fullmatch(source_digest):
        raise _InvalidResultError
    if not isinstance(capabilities, dict) or not _REQUIRED_CAPABILITIES.issubset(capabilities):
        raise _InvalidResultError
    selected_capabilities: dict[str, bool] = {}
    for name in _REQUIRED_CAPABILITIES:
        value = capabilities[name]
        if type(value) is not bool:
            raise _InvalidResultError
        selected_capabilities[name] = value
    return {
        "success": success,
        "bridge_version": bridge_version,
        "contract_revision": contract_revision,
        "bridge_source_sha256": source_digest,
        "capabilities": selected_capabilities,
    }


def verify_bridge_compatibility(
    attestation: dict[str, object], live: dict[str, object]
) -> dict[str, bool]:
    """Compare every public compatibility value without exposing either payload."""

    required_attestation = {
        "bridge_version",
        "contract_revision",
        "bridge_source_sha256",
        "checks",
    }
    if not required_attestation.issubset(attestation):
        raise _InvalidResultError
    required_live = {
        "bridge_version",
        "contract_revision",
        "bridge_source_sha256",
        "capabilities",
    }
    if not required_live.issubset(live):
        raise _InvalidResultError
    if (
        live["bridge_version"] != attestation["bridge_version"]
        or live["contract_revision"] != attestation["contract_revision"]
        or live["bridge_source_sha256"] != attestation["bridge_source_sha256"]
    ):
        raise _InvalidResultError
    checks = attestation["checks"]
    capabilities = live["capabilities"]
    if not isinstance(checks, dict) or not isinstance(capabilities, dict):
        raise _InvalidResultError
    if set(checks) != REQUIRED_CHECKS or set(capabilities) != _REQUIRED_CAPABILITIES:
        raise _InvalidResultError
    if any(type(checks[name]) is not bool or not checks[name] for name in REQUIRED_CHECKS):
        raise _InvalidResultError
    if any(
        type(capabilities[name]) is not bool or not capabilities[name]
        for name in _REQUIRED_CAPABILITIES
    ):
        raise _InvalidResultError
    return {"compatible": True}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control the Gmail Edge broker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show broker and authentication status")
    subparsers.add_parser("diagnostics", help="Show sanitized broker diagnostics")
    subparsers.add_parser("login", help="Complete interactive Gmail authentication")
    subparsers.add_parser("start", help="Ensure the broker is running")
    subparsers.add_parser("stop", help="Stop the running broker")
    verify_bridge = subparsers.add_parser(
        "verify-bridge", help="Verify the deployed Cloud Bridge against an attestation"
    )
    verify_bridge.add_argument("--attestation", type=Path, required=True)
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


def _print_bridge_incompatible() -> int:
    _print_json(
        {
            "ok": False,
            "code": "BRIDGE_INCOMPATIBLE",
            "message": "Cloud Bridge is incompatible with the local attestation",
        }
    )
    return EXIT_INVALID


def _success_exit_code(command: str, result: dict[str, Any]) -> int:
    if command not in {"status", "diagnostics", "start"}:
        return EXIT_SUCCESS
    edge_state = result.get("edge_state")
    # A freshly lazy-started broker has not probed Gmail yet. Treat STARTING
    # as authentication-required so the installer/control flow performs the
    # one permitted interactive login instead of silently declaring readiness.
    if edge_state in _AUTH_REQUIRED_STATES or edge_state == "STARTING":
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
    broker_client = (
        BrokerClient(request_timeout=60)
        if client is None and args.command == "verify-bridge"
        else BrokerClient()
        if client is None
        else client
    )
    try:
        if args.command == "verify-bridge":
            attestation = validate_attestation(
                _BRIDGE_SOURCE_PATH,
                args.attestation,
                _plugin_version(),
            )
            live = parse_capabilities_response(
                broker_client.request("bridge_capabilities", {})
            )
            sanitized = verify_bridge_compatibility(attestation, live)
        else:
            if args.command == "login":
                result = broker_client.request("auth_login", {})
            elif args.command == "stop":
                result = broker_client.request_existing("shutdown", {})
            else:
                result = broker_client.request("health", {})
            sanitized = _sanitize_result(args.command, result)
    except BrokerClientError as error:
        return _print_client_error(error)
    except (ValueError, _InvalidResultError):
        if args.command == "verify-bridge":
            return _print_bridge_incompatible()
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
