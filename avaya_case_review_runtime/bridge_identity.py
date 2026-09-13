"""Deterministic identity and attestation helpers for the Gmail cloud bridge."""

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from . import __version__


ATTESTATION_SCHEMA_VERSION = 1
BRIDGE_PROTOCOL_VERSION = 4
CONTRACT_REVISION = 1
BRIDGE_SOURCE_SHA256 = "14f8542b9ed19f1bb84ea2fb0209f8c70151f0d427b48453b904683187e884c0"
BROKER_BUILD_ID = (
    f"{__version__}-b{BRIDGE_PROTOCOL_VERSION}-r{CONTRACT_REVISION}-"
    f"{BRIDGE_SOURCE_SHA256}"
)
IDENTITY_FIELD = "GMAIL_BRIDGE_SOURCE_SHA256"
ZERO_DIGEST = "0" * 64
REQUIRED_CHECKS = frozenset({
    "advanced_gmail_v1",
    "zero_result_complete",
    "stable_snapshot_pagination",
    "cursor_exhaustion",
    "manifest_message_count_hashes",
    "sensitive_output_absent",
})
REQUIRED_ATTESTATION_KEYS = frozenset({
    "schema_version",
    "plugin_version",
    "bridge_version",
    "contract_revision",
    "bridge_source_sha256",
    "verified_at_utc",
    "checks",
})

IDENTITY_RE = re.compile(
    r'(?m)^var GMAIL_BRIDGE_SOURCE_SHA256 = "([0-9a-f]{64})";$'
)
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_UTC_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z"
)


def compute_source_sha256(source: str) -> str:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(IDENTITY_RE.finditer(normalized))
    if len(matches) != 1:
        raise ValueError("bridge source must contain exactly one identity assignment")
    match = matches[0]
    canonical = normalized[: match.start(1)] + ZERO_DIGEST + normalized[match.end(1) :]
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_source_identity(source: str) -> str:
    digest = compute_source_sha256(source)
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    embedded_digest = IDENTITY_RE.search(normalized)
    if embedded_digest is None:
        raise ValueError("bridge source must contain exactly one identity assignment")
    if embedded_digest.group(1) != digest:
        raise ValueError("bridge source identity does not match its computed digest")
    return digest


def _write_text_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temporary_file:
            temporary_file.write(text)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _read_source(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def stamp_source(path: Path) -> str:
    source = _read_source(path)
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    digest = compute_source_sha256(normalized)
    matches = list(IDENTITY_RE.finditer(normalized))
    if len(matches) != 1:
        raise ValueError("bridge source must contain exactly one identity assignment")
    match = matches[0]
    stamped = normalized[: match.start(1)] + digest + normalized[match.end(1) :]
    _write_text_atomically(path, stamped)
    return digest


def _require_utc_timestamp(value: object) -> str:
    if not isinstance(value, str) or not _UTC_TIMESTAMP_RE.fullmatch(value):
        raise ValueError("verified_at_utc must be an RFC 3339 UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("verified_at_utc must be an RFC 3339 UTC timestamp ending in Z") from error
    return value


def write_attestation(
    source_path: Path,
    output_path: Path,
    plugin_version: str,
    verified_at_utc: str,
) -> dict[str, object]:
    if not isinstance(plugin_version, str) or not plugin_version:
        raise ValueError("plugin_version must be a non-empty string")
    _require_utc_timestamp(verified_at_utc)
    attestation: dict[str, object] = {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "plugin_version": plugin_version,
        "bridge_version": BRIDGE_PROTOCOL_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "bridge_source_sha256": validate_source_identity(_read_source(source_path)),
        "verified_at_utc": verified_at_utc,
        "checks": {name: True for name in sorted(REQUIRED_CHECKS)},
    }
    _write_text_atomically(output_path, json.dumps(attestation, indent=2, sort_keys=True) + "\n")
    return attestation


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("attestation JSON contains duplicate keys")
        result[key] = value
    return result


def _load_attestation(path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("attestation is not valid JSON") from error
    if not isinstance(loaded, dict):
        raise ValueError("attestation must be a JSON object")
    return loaded


def _require_exact_keys(value: dict[str, object], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError("attestation " + label + " keys do not match the required contract")


def _require_exact_integer(value: object, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        raise ValueError("attestation " + label + " does not match the required contract")


def validate_attestation(
    source_path: Path,
    attestation_path: Path,
    expected_plugin_version: str,
) -> dict[str, object]:
    attestation = _load_attestation(attestation_path)
    _require_exact_keys(attestation, REQUIRED_ATTESTATION_KEYS, "top-level")
    _require_exact_integer(attestation["schema_version"], ATTESTATION_SCHEMA_VERSION, "schema version")
    _require_exact_integer(attestation["bridge_version"], BRIDGE_PROTOCOL_VERSION, "bridge version")
    _require_exact_integer(attestation["contract_revision"], CONTRACT_REVISION, "contract revision")
    if type(attestation["plugin_version"]) is not str or attestation["plugin_version"] != expected_plugin_version:
        raise ValueError("attestation plugin version does not match")
    digest = attestation["bridge_source_sha256"]
    if type(digest) is not str or not _DIGEST_RE.fullmatch(digest):
        raise ValueError("attestation bridge source digest is invalid")
    _require_utc_timestamp(attestation["verified_at_utc"])
    checks = attestation["checks"]
    if not isinstance(checks, dict):
        raise ValueError("attestation checks must be an object")
    _require_exact_keys(checks, REQUIRED_CHECKS, "check")
    if any(type(value) is not bool or not value for value in checks.values()):
        raise ValueError("attestation checks must all be true booleans")
    if digest != validate_source_identity(_read_source(source_path)):
        raise ValueError("attestation bridge source digest does not match")
    return attestation


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stamp = commands.add_parser("stamp", help="stamp the bridge source identity")
    stamp.add_argument("--source", type=Path, required=True)
    attest = commands.add_parser("attest", help="write a successful bridge attestation")
    attest.add_argument("--source", type=Path, required=True)
    attest.add_argument("--output", type=Path, required=True)
    attest.add_argument("--plugin-version", required=True)
    attest.add_argument("--verified-at-utc", required=True)
    attest.add_argument("--all-checks-passed", action="store_true", required=True)
    validate = commands.add_parser("validate", help="validate a bridge release attestation")
    validate.add_argument("--source", type=Path, required=True)
    validate.add_argument("--attestation", type=Path, required=True)
    validate.add_argument("--plugin-version", required=True)
    return parser


def main() -> int:
    arguments = _build_parser().parse_args()
    if arguments.command == "stamp":
        print(stamp_source(arguments.source))
    elif arguments.command == "attest":
        if not arguments.all_checks_passed:
            raise ValueError("attest requires --all-checks-passed")
        print(json.dumps(write_attestation(
            arguments.source,
            arguments.output,
            arguments.plugin_version,
            arguments.verified_at_utc,
        ), sort_keys=True))
    else:
        validate_attestation(arguments.source, arguments.attestation, arguments.plugin_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
