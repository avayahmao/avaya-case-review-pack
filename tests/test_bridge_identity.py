import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.gmail.cloud.bridge_identity import (
    BRIDGE_PROTOCOL_VERSION,
    CONTRACT_REVISION,
    IDENTITY_FIELD,
    REQUIRED_CHECKS,
    compute_source_sha256,
    stamp_source,
    validate_attestation,
    write_attestation,
)


IDENTITY_LINE = 'var GMAIL_BRIDGE_SOURCE_SHA256 = "' + "0" * 64 + '";'
SOURCE = IDENTITY_LINE + "\nvar X = 1;\n"
UTC_TIMESTAMP = "2026-09-09T12:34:56Z"


class BridgeSourceIdentityTests(unittest.TestCase):
    def test_hash_normalizes_line_endings_and_zeroes_only_identity(self):
        lf = 'var GMAIL_BRIDGE_SOURCE_SHA256 = "' + "a" * 64 + '";\nvar X = 1;\n'
        crlf = lf.replace("\n", "\r\n").replace("a" * 64, "b" * 64)

        self.assertEqual(compute_source_sha256(lf), compute_source_sha256(crlf))

    def test_hash_rejects_missing_or_duplicate_identity_assignment(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            compute_source_sha256("var X = 1;\n")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            compute_source_sha256(IDENTITY_LINE + "\n" + IDENTITY_LINE + "\n")

    def test_stamp_source_replaces_the_identity_with_its_computed_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "GmailMcpBridge.gs"
            source_path.write_text(SOURCE, encoding="utf-8", newline="")

            digest = stamp_source(source_path)

            self.assertEqual(digest, compute_source_sha256(source_path.read_text(encoding="utf-8")))
            self.assertIn('"' + digest + '"', source_path.read_text(encoding="utf-8"))


class BridgeAttestationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.source_path = Path(self.directory.name) / "GmailMcpBridge.gs"
        self.attestation_path = Path(self.directory.name) / "bridge_release_attestation.json"
        self.source_path.write_text(SOURCE, encoding="utf-8", newline="")
        stamp_source(self.source_path)

    def tearDown(self):
        self.directory.cleanup()

    def write_valid_attestation(self):
        return write_attestation(
            self.source_path,
            self.attestation_path,
            plugin_version="1.10.1",
            verified_at_utc=UTC_TIMESTAMP,
        )

    def write_payload(self, payload):
        self.attestation_path.write_text(json.dumps(payload), encoding="utf-8", newline="")

    def test_validate_attestation_returns_a_complete_matching_attestation(self):
        expected = self.write_valid_attestation()

        actual = validate_attestation(self.source_path, self.attestation_path, "1.10.1")

        self.assertEqual(actual, expected)
        self.assertEqual(actual["bridge_version"], BRIDGE_PROTOCOL_VERSION)
        self.assertEqual(actual["contract_revision"], CONTRACT_REVISION)
        self.assertEqual(set(actual["checks"]), REQUIRED_CHECKS)

    def test_write_attestation_rejects_an_unstamped_source(self):
        self.source_path.write_text(SOURCE, encoding="utf-8", newline="")

        with self.assertRaises(ValueError):
            self.write_valid_attestation()

        self.assertFalse(self.attestation_path.exists())

    def test_validate_attestation_rejects_a_stale_embedded_source_digest(self):
        self.write_valid_attestation()
        stale_source = self.source_path.read_text(encoding="utf-8").replace(
            compute_source_sha256(SOURCE), "f" * 64
        )
        self.source_path.write_text(stale_source, encoding="utf-8", newline="")

        with self.assertRaises(ValueError):
            validate_attestation(self.source_path, self.attestation_path, "1.10.1")

    def test_validate_attestation_rejects_each_strict_contract_violation(self):
        valid = self.write_valid_attestation()
        cases = []

        missing_key = copy.deepcopy(valid)
        del missing_key["verified_at_utc"]
        cases.append(("missing top-level key", missing_key))

        extra_key = copy.deepcopy(valid)
        extra_key["unexpected"] = True
        cases.append(("extra top-level key", extra_key))

        missing_check = copy.deepcopy(valid)
        del missing_check["checks"]["advanced_gmail_v1"]
        cases.append(("missing check", missing_check))

        extra_check = copy.deepcopy(valid)
        extra_check["checks"]["unexpected"] = True
        cases.append(("extra check", extra_check))

        non_boolean_check = copy.deepcopy(valid)
        non_boolean_check["checks"]["advanced_gmail_v1"] = 1
        cases.append(("non-boolean check", non_boolean_check))

        false_check = copy.deepcopy(valid)
        false_check["checks"]["advanced_gmail_v1"] = False
        cases.append(("failed check", false_check))

        malformed_timestamp = copy.deepcopy(valid)
        malformed_timestamp["verified_at_utc"] = "2026-09-09T12:34:56+00:00"
        cases.append(("non-Z timestamp", malformed_timestamp))

        bad_version = copy.deepcopy(valid)
        bad_version["plugin_version"] = "1.10.2"
        cases.append(("attestation plugin version mismatch", bad_version))

        bad_digest = copy.deepcopy(valid)
        bad_digest["bridge_source_sha256"] = "f" * 64
        cases.append(("source digest mismatch", bad_digest))

        for name, payload in cases:
            with self.subTest(name=name):
                self.write_payload(payload)
                with self.assertRaises(ValueError):
                    validate_attestation(self.source_path, self.attestation_path, "1.10.1")

    def test_validate_attestation_rejects_duplicate_json_keys(self):
        self.attestation_path.write_text(
            '{"schema_version": 1, "schema_version": 1}', encoding="utf-8", newline=""
        )

        with self.assertRaises(ValueError):
            validate_attestation(self.source_path, self.attestation_path, "1.10.1")

    def test_cli_validate_accepts_the_attestation_without_mutating_it(self):
        self.write_valid_attestation()
        helper_path = Path("tools/gmail/cloud/bridge_identity.py")
        result = subprocess.run(
            [
                sys.executable,
                str(helper_path),
                "validate",
                "--source",
                str(self.source_path),
                "--attestation",
                str(self.attestation_path),
                "--plugin-version",
                "1.10.1",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
