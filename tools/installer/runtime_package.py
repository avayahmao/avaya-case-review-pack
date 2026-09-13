"""Validate and smoke-test the installed Avaya Case Review runtime package."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import subprocess
import sys
import unicodedata
import zipfile
from email.parser import Parser
from pathlib import Path


DISTRIBUTION_NAME = "avaya-case-review-runtime"
NORMALIZED_DISTRIBUTION_NAME = "avaya_case_review_runtime"
REQUIRED_WHEEL_MEMBERS = frozenset(
    {
        "avaya_case_review_runtime/gmail_mcp_server.py",
        "avaya_case_review_runtime/casetomd_mcp_bridge.py",
    }
)
EXPECTED_TOOLS = {
    "avaya_case_review_runtime.gmail_mcp_server": frozenset(
        {
            "gmail_search",
            "gmail_read",
            "gmail_send",
            "gmail_list_threads",
            "gmail_read_thread_page",
        }
    ),
    "avaya_case_review_runtime.casetomd_mcp_bridge": frozenset(
        {"get_case_markdown"}
    ),
}
_NORMALIZE_RE = re.compile(r"[-_.]+")


class RuntimePackageError(ValueError):
    """A sanitized runtime package validation failure."""


def _normalized_name(value: str) -> str:
    return _NORMALIZE_RE.sub("_", value).lower()


def _canonical_member_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value) if isinstance(value, str) else value
    if (
        not isinstance(normalized, str)
        or not normalized
        or "\\" in normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
    ):
        raise RuntimePackageError("wheel member path is invalid")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise RuntimePackageError("wheel member path is invalid")
    canonical_parts = [part.casefold() for part in parts]
    reserved = {"con", "prn", "aux", "nul"} | {
        f"{prefix}{number}"
        for prefix in ("com", "lpt")
        for number in range(1, 10)
    }
    for part in canonical_parts:
        if part.endswith((" ", ".")) or ":" in part:
            raise RuntimePackageError("wheel member path is invalid")
        if part.split(".", 1)[0].rstrip(" .") in reserved:
            raise RuntimePackageError("wheel member path is invalid")
    if canonical_parts[0].rstrip(" .") == "tools":
        raise RuntimePackageError("wheel contains a forbidden package")
    return "/".join(canonical_parts)


def installed_version() -> dict[str, object]:
    try:
        version = importlib.metadata.version(DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError:
        return {"distribution": DISTRIBUTION_NAME, "installed": False}
    return {
        "distribution": DISTRIBUTION_NAME,
        "installed": True,
        "version": version,
    }


def validate_wheel(path: Path, expected_version: str) -> dict[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            members: dict[str, str] = {}
            for info in archive.infolist():
                canonical = _canonical_member_name(info.orig_filename)
                if canonical in members:
                    raise RuntimePackageError("wheel contains aliased member paths")
                members[canonical] = info.orig_filename
            metadata_members = [
                original
                for canonical, original in members.items()
                if canonical.endswith(".dist-info/metadata")
                and canonical.count("/") == 1
            ]
            if len(metadata_members) != 1:
                raise RuntimePackageError("wheel metadata contract is invalid")
            metadata_text = archive.read(metadata_members[0]).decode("utf-8")
            metadata = Parser().parsestr(metadata_text)
    except RuntimePackageError:
        raise
    except (OSError, RuntimeError, UnicodeError, zipfile.BadZipFile, KeyError) as error:
        raise RuntimePackageError("wheel archive is invalid") from error

    name = metadata.get("Name")
    version = metadata.get("Version")
    if not isinstance(name, str) or _normalized_name(name) != NORMALIZED_DISTRIBUTION_NAME:
        raise RuntimePackageError("wheel distribution name does not match")
    if not isinstance(version, str) or version != expected_version:
        raise RuntimePackageError("wheel distribution version does not match")
    expected_metadata = (
        f"{NORMALIZED_DISTRIBUTION_NAME}-{expected_version}.dist-info/metadata".casefold()
    )
    if _canonical_member_name(metadata_members[0]) != expected_metadata:
        raise RuntimePackageError("wheel metadata identity does not match")
    canonical_required = {_canonical_member_name(member) for member in REQUIRED_WHEEL_MEMBERS}
    if not canonical_required.issubset(members):
        raise RuntimePackageError("wheel required module contract is incomplete")
    return {"distribution": DISTRIBUTION_NAME, "version": expected_version}


def _mcp_requests() -> str:
    requests = (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "runtime-package-smoke", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    return "".join(json.dumps(request, separators=(",", ":")) + "\n" for request in requests)


def _smoke_module(python: str, work_dir: Path, module: str, expected: frozenset[str]) -> None:
    try:
        completed = subprocess.run(
            [python, "-m", module],
            input=_mcp_requests().encode("utf-8"),
            cwd=work_dir,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimePackageError("runtime module smoke test could not complete") from error
    if completed.returncode:
        raise RuntimePackageError("runtime module smoke test failed")
    try:
        stdout = completed.stdout.decode("utf-8")
        responses = [
            json.loads(line) for line in stdout.splitlines() if line.strip()
        ]
        initialized = next(response for response in responses if response.get("id") == 1)
        listed = next(response for response in responses if response.get("id") == 2)
        if not isinstance(initialized["result"]["protocolVersion"], str):
            raise RuntimePackageError("runtime initialize response is invalid")
        tools = listed["result"]["tools"]
        actual = {tool["name"] for tool in tools if isinstance(tool, dict)}
    except (UnicodeError, json.JSONDecodeError, KeyError, StopIteration, TypeError) as error:
        raise RuntimePackageError("runtime module smoke response is invalid") from error
    if actual != expected:
        raise RuntimePackageError("runtime module tool contract does not match")


def smoke(python: str, work_dir: Path) -> dict[str, str]:
    if not work_dir.is_dir():
        raise RuntimePackageError("runtime smoke work directory is unavailable")
    for module, expected in EXPECTED_TOOLS.items():
        _smoke_module(python, work_dir, module, expected)
    return {"smoke": "ok"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("installed-version")
    validate = commands.add_parser("validate-wheel")
    validate.add_argument("--wheel", type=Path, required=True)
    validate.add_argument("--version", required=True)
    smoke_parser = commands.add_parser("smoke")
    smoke_parser.add_argument("--python", required=True)
    smoke_parser.add_argument("--work-dir", type=Path, required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "installed-version":
            result = installed_version()
        elif arguments.command == "validate-wheel":
            result = validate_wheel(arguments.wheel, arguments.version)
        else:
            result = smoke(arguments.python, arguments.work_dir)
    except RuntimePackageError as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 1
    except Exception:
        print(
            json.dumps(
                {"ok": False, "error": "runtime package operation failed"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
