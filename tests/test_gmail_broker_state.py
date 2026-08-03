import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.gmail.gmail_broker_state import (
    ALLOWED_LOG_FIELDS,
    LIFECYCLE_COUNTER_FIELDS,
    AlreadyRunning,
    BrokerState,
    BrokerStateError,
    BrokerStateStore,
    LifetimeFileLock,
    SanitizedRotatingLogger,
    StartupFileLock,
    UnsafeLogFieldError,
    apply_windows_acl,
    default_broker_paths,
    is_stale_state,
    process_exists,
)


WINDOWS_POWERSHELL = shutil.which("powershell.exe")
REAL_WINDOWS_ACL = os.name == "nt" and WINDOWS_POWERSHELL is not None

_READ_WINDOWS_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$target = [Environment]::GetEnvironmentVariable(
    'AVAYA_GMAIL_BROKER_ACL_TARGET',
    [EnvironmentVariableTarget]::Process
)
if ([IO.Directory]::Exists($target)) {
    $security = [IO.Directory]::GetAccessControl($target)
} elseif ([IO.File]::Exists($target)) {
    $security = [IO.File]::GetAccessControl($target)
} else {
    throw 'ACL target does not exist.'
}
$rules = @(
    $security.GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    ) | ForEach-Object {
        [PSCustomObject]@{
            sid = $_.IdentityReference.Value
            type = [string]$_.AccessControlType
            rights = [string]$_.FileSystemRights
            inheritance = [string]$_.InheritanceFlags
            propagation = [string]$_.PropagationFlags
            inherited = [bool]$_.IsInherited
        }
    }
)
[PSCustomObject]@{
    owner = $security.GetOwner(
        [Security.Principal.SecurityIdentifier]
    ).Value
    rules = $rules
} | ConvertTo-Json -Depth 5 -Compress
"""


def read_windows_acl(path):
    environment = dict(os.environ)
    environment["AVAYA_GMAIL_BROKER_ACL_TARGET"] = str(Path(path).resolve())
    result = subprocess.run(
        [
            WINDOWS_POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _READ_WINDOWS_ACL_SCRIPT,
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(result.stdout)


def rewrite_file_bytes(path):
    with Path(path).open("r+b") as stream:
        content = stream.read()
        stream.seek(0)
        stream.write(content)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


def assert_private_windows_acl(
    test_case,
    path,
    *,
    directory,
    allow_inherited=False,
):
    acl = read_windows_acl(path)
    rules = acl["rules"]
    expected_sids = {acl["owner"], "S-1-5-18"}
    test_case.assertNotEqual(acl["owner"], "S-1-5-18")
    test_case.assertEqual(len(rules), 2, rules)
    test_case.assertEqual({rule["sid"] for rule in rules}, expected_sids)
    test_case.assertTrue(all(rule["type"] == "Allow" for rule in rules), rules)
    test_case.assertTrue(
        all(rule["rights"] == "FullControl" for rule in rules),
        rules,
    )
    if not allow_inherited:
        test_case.assertTrue(all(not rule["inherited"] for rule in rules), rules)
    if directory:
        expected_flags = {"ContainerInherit", "ObjectInherit"}
        for rule in rules:
            test_case.assertEqual(
                set(rule["inheritance"].split(", ")),
                expected_flags,
            )
            test_case.assertEqual(rule["propagation"], "None")
    else:
        test_case.assertTrue(
            all(rule["inheritance"] == "None" for rule in rules),
            rules,
        )


def make_state(**overrides):
    values = {
        "protocol_version": 1,
        "build_id": "test-build",
        "instance_id": "test-instance",
        "pid": 12345,
        "host": "127.0.0.1",
        "port": 41000,
        "token": "SENSITIVE_BROKER_TOKEN",
        "started_at": "2026-08-03T00:00:00Z",
    }
    values.update(overrides)
    return BrokerState(**values)


class BrokerPathTests(unittest.TestCase):
    def test_default_paths_are_under_the_per_user_local_app_data_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                paths = default_broker_paths()

        expected = Path(tmp) / "AvayaCaseReview" / "gmail-broker"
        self.assertEqual(paths.directory, expected)
        self.assertEqual(paths.state_file, expected / "state.json")
        self.assertEqual(paths.log_file, expected / "broker.log")
        self.assertEqual(paths.broker_lock_file, expected / "broker.lock")
        self.assertEqual(paths.startup_lock_file, expected / "startup.lock")


class BrokerStateTests(unittest.TestCase):
    def make_store(self, directory):
        return BrokerStateStore(directory, acl_applier=None)

    def test_atomic_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            state = make_state()

            store.write(state)

            self.assertEqual(store.read(), state)
            self.assertEqual(
                set(json.loads(store.state_file.read_text(encoding="utf-8"))),
                {
                    "protocol_version",
                    "build_id",
                    "instance_id",
                    "pid",
                    "host",
                    "port",
                    "token",
                    "started_at",
                },
            )
            self.assertEqual(list(Path(tmp).glob(".state.json.*.tmp")), [])

    def test_state_repr_redacts_token(self):
        rendered = repr(make_state())

        self.assertNotIn("SENSITIVE_BROKER_TOKEN", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_missing_state_returns_none_without_creating_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "not-created"
            store = self.make_store(state_dir)

            self.assertIsNone(store.read())
            self.assertFalse(state_dir.exists())

    def test_read_rejects_missing_extra_duplicate_and_invalid_fields(self):
        state_payload = {
            "protocol_version": 1,
            "build_id": "test-build",
            "instance_id": "test-instance",
            "pid": 12345,
            "host": "127.0.0.1",
            "port": 41000,
            "token": "secret",
            "started_at": "2026-08-03T00:00:00Z",
        }
        invalid_documents = []
        missing = dict(state_payload)
        missing.pop("build_id")
        invalid_documents.append(json.dumps(missing))
        extra = dict(state_payload, debug=True)
        invalid_documents.append(json.dumps(extra))
        invalid_documents.append(
            '{"protocol_version":1,"build_id":"a","build_id":"b",'
            '"instance_id":"i","pid":1,"host":"127.0.0.1",'
            '"port":1,"token":"t","started_at":"now"}'
        )
        wrong_type = dict(state_payload, pid=True)
        invalid_documents.append(json.dumps(wrong_type))
        invalid_documents.append("not-json")

        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            for document in invalid_documents:
                with self.subTest(document=document):
                    store.state_file.write_text(document, encoding="utf-8")
                    with self.assertRaises(BrokerStateError):
                        store.read()

    def test_failed_atomic_replace_preserves_previous_state_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            original = make_state(instance_id="original")
            store.write(original)

            with patch(
                "tools.gmail.gmail_broker_state.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaises(OSError):
                    store.write(make_state(instance_id="replacement"))

            self.assertEqual(store.read(), original)
            self.assertEqual(list(Path(tmp).glob(".state.json.*.tmp")), [])

    def test_cleanup_requires_matching_acquired_owner_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            store.write(make_state(instance_id="replacement"))
            owner_lock = LifetimeFileLock(
                store.paths.broker_lock_file,
                acl_applier=None,
            )

            with self.assertRaises(RuntimeError):
                store.cleanup("replacement", owner_lock=owner_lock)

            with owner_lock:
                self.assertFalse(
                    store.cleanup("old-instance", owner_lock=owner_lock)
                )
                self.assertEqual(store.read().instance_id, "replacement")
                self.assertTrue(
                    store.cleanup("replacement", owner_lock=owner_lock)
                )
            self.assertIsNone(store.read())

    def test_cleanup_rejects_lock_for_another_state_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(root / "one")
            store.write(make_state())
            wrong_lock = LifetimeFileLock(
                root / "two" / "broker.lock",
                acl_applier=None,
            )

            with wrong_lock:
                with self.assertRaises(ValueError):
                    store.cleanup("test-instance", owner_lock=wrong_lock)

            self.assertIsNotNone(store.read())

    def test_old_instance_cannot_delete_replacement_after_releasing_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(root)
            old_lock = LifetimeFileLock(
                store.paths.broker_lock_file,
                acl_applier=None,
            )
            replacement_lock = LifetimeFileLock(
                store.paths.broker_lock_file,
                acl_applier=None,
            )
            with old_lock:
                store.write(make_state(instance_id="old"))
            with replacement_lock:
                store.write(make_state(instance_id="replacement"))

            with self.assertRaises(RuntimeError):
                store.cleanup("old", owner_lock=old_lock)

            self.assertEqual(store.read().instance_id, "replacement")

    def test_missing_pid_marks_state_stale(self):
        seen = []

        self.assertTrue(
            is_stale_state(
                make_state(pid=999999),
                process_exists=lambda pid: seen.append(pid) or False,
            )
        )
        self.assertEqual(seen, [999999])

    def test_existing_pid_keeps_state_current(self):
        self.assertFalse(
            is_stale_state(make_state(), process_exists=lambda pid: True)
        )


class RecordingLockBackend:
    def __init__(self, acquire_error=None, release_error=None):
        self.acquire_error = acquire_error
        self.release_error = release_error
        self.calls = []
        self.stream = None

    def acquire(self, stream):
        self.calls.append("acquire")
        self.stream = stream
        if self.acquire_error is not None:
            raise self.acquire_error

    def release(self, stream):
        self.calls.append("release")
        self.stream = stream
        if self.release_error is not None:
            raise self.release_error


class LifetimeFileLockTests(unittest.TestCase):
    def test_injected_backend_is_held_for_context_lifetime_and_release_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = RecordingLockBackend()
            lock = LifetimeFileLock(
                Path(tmp) / "broker.lock",
                backend=backend,
                acl_applier=None,
            )

            with lock:
                self.assertTrue(lock.is_acquired)
                self.assertFalse(backend.stream.closed)
                self.assertEqual(backend.calls, ["acquire"])

            self.assertFalse(lock.is_acquired)
            self.assertTrue(backend.stream.closed)
            self.assertEqual(backend.calls, ["acquire", "release"])
            lock.release()
            self.assertEqual(backend.calls, ["acquire", "release"])

    def test_contended_injected_backend_raises_already_running_and_closes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = RecordingLockBackend(
                acquire_error=OSError(errno.EACCES, "locked")
            )
            lock = LifetimeFileLock(
                Path(tmp) / "broker.lock",
                backend=backend,
                acl_applier=None,
            )

            with self.assertRaises(AlreadyRunning):
                lock.acquire()

            self.assertFalse(lock.is_acquired)
            self.assertTrue(backend.stream.closed)

    def test_release_closes_file_even_when_backend_unlock_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = RecordingLockBackend(
                release_error=OSError(errno.EIO, "unlock failed")
            )
            lock = LifetimeFileLock(
                Path(tmp) / "broker.lock",
                backend=backend,
                acl_applier=None,
            )
            lock.acquire()

            with self.assertRaises(OSError):
                lock.release()

            self.assertFalse(lock.is_acquired)
            self.assertTrue(backend.stream.closed)

    def test_startup_lock_uses_short_lived_startup_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = RecordingLockBackend()
            lock = StartupFileLock(
                Path(tmp),
                backend=backend,
                acl_applier=None,
            )

            self.assertEqual(lock.path, Path(tmp) / "startup.lock")
            with lock:
                self.assertTrue(lock.is_acquired)
            self.assertFalse(lock.is_acquired)

    @unittest.skipUnless(os.name == "nt", "requires Windows process APIs")
    def test_process_exists_does_not_call_os_kill_on_windows(self):
        with patch(
            "tools.gmail.gmail_broker_state.os.kill",
            side_effect=AssertionError("os.kill is destructive on Windows"),
        ):
            self.assertTrue(process_exists(os.getpid()))

    @unittest.skipUnless(os.name == "nt", "requires Windows process APIs")
    def test_process_exists_does_not_terminate_live_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready_path = Path(tmp) / "holder.ready"
            holder = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys, time; from pathlib import Path; "
                        "Path(sys.argv[1]).write_text('ready', encoding='utf-8'); "
                        "time.sleep(30)"
                    ),
                    str(ready_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=getattr(
                    subprocess,
                    "CREATE_NEW_PROCESS_GROUP",
                    0,
                ),
            )
            try:
                deadline = time.monotonic() + 10
                while (
                    not ready_path.exists()
                    and time.monotonic() < deadline
                ):
                    if holder.poll() is not None:
                        _, stderr = holder.communicate()
                        self.fail(
                            "process holder exited before ready: "
                            f"{holder.returncode}, stderr={stderr!r}"
                        )
                    time.sleep(0.02)
                self.assertTrue(
                    ready_path.exists(),
                    "process holder did not become ready",
                )

                project_root = Path(__file__).resolve().parents[1]
                probe = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        (
                            "from tools.gmail.gmail_broker_state import "
                            "process_exists; import sys; "
                            "print(process_exists(int(sys.argv[1])))"
                        ),
                        str(holder.pid),
                    ],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(
                    probe.returncode,
                    0,
                    (probe.stdout, probe.stderr),
                )
                self.assertEqual(probe.stdout.strip(), "True")
                self.assertIsNone(
                    holder.poll(),
                    "process_exists terminated the process it inspected",
                )
            finally:
                if holder.poll() is None:
                    holder.terminate()
                try:
                    holder.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    holder.kill()
                    holder.wait(timeout=10)
                holder.communicate()

    @unittest.skipUnless(
        REAL_WINDOWS_ACL,
        "requires Windows msvcrt locking and Windows PowerShell",
    )
    def test_real_two_subprocesses_cannot_hold_broker_lock_together(self):
        holder_script = """
import sys
import time
from pathlib import Path
from tools.gmail.gmail_broker_state import LifetimeFileLock

lock_path, ready_path, release_path = map(Path, sys.argv[1:])
with LifetimeFileLock(lock_path):
    ready_path.write_text("ready", encoding="utf-8")
    while not release_path.exists():
        time.sleep(0.02)
"""
        contender_script = """
import sys
from pathlib import Path
from tools.gmail.gmail_broker_state import AlreadyRunning, LifetimeFileLock

try:
    with LifetimeFileLock(Path(sys.argv[1])):
        print("ACQUIRED", flush=True)
except AlreadyRunning:
    print("ALREADY_RUNNING", flush=True)
"""
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp) / "broker-state"
            lock_path = temp_dir / "broker.lock"
            ready_path = temp_dir / "holder.ready"
            release_path = temp_dir / "holder.release"
            environment = dict(os.environ)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            holder = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    holder_script,
                    str(lock_path),
                    str(ready_path),
                    str(release_path),
                ],
                cwd=project_root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 10
                while not ready_path.exists() and time.monotonic() < deadline:
                    if holder.poll() is not None:
                        stdout, stderr = holder.communicate()
                        self.fail(
                            f"lock holder exited early ({holder.returncode}): "
                            f"stdout={stdout!r}, stderr={stderr!r}"
                        )
                    time.sleep(0.02)
                self.assertTrue(ready_path.exists(), "lock holder did not become ready")

                contender = subprocess.run(
                    [sys.executable, "-c", contender_script, str(lock_path)],
                    cwd=project_root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                )

                self.assertEqual(contender.stdout.strip(), "ALREADY_RUNNING")
                self.assertEqual(contender.stderr, "")
            finally:
                release_path.touch()
                try:
                    holder.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    holder.kill()
                    holder.wait(timeout=10)
            stdout, stderr = holder.communicate()
            self.assertEqual(holder.returncode, 0, (stdout, stderr))
            with LifetimeFileLock(lock_path):
                self.assertTrue(lock_path.is_file())
            rewrite_file_bytes(lock_path)
            assert_private_windows_acl(self, lock_path, directory=False)

    @unittest.skipUnless(os.name == "nt", "default ACL application is Windows-only")
    def test_lock_secures_directory_and_lock_file_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "broker.lock"
            backend = RecordingLockBackend()
            with patch(
                "tools.gmail.gmail_broker_state.apply_windows_acl"
            ) as acl_applier:
                with LifetimeFileLock(lock_path, backend=backend):
                    pass

        self.assertEqual(
            [call.args[0] for call in acl_applier.call_args_list],
            [Path(tmp), lock_path],
        )


class WindowsAclTests(unittest.TestCase):
    def test_injected_powershell_runner_builds_exact_sid_acl(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()

            apply_windows_acl(
                target,
                current_user_sid="S-1-5-21-1234",
                runner=runner,
            )

        self.assertEqual(len(calls), 1)
        command, kwargs = calls[0]
        self.assertTrue(command[0].lower().endswith("powershell.exe"))
        self.assertEqual(command[1:6], [
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
        ])
        script = command[6]
        self.assertIn("DirectorySecurity", script)
        self.assertIn("FileSecurity", script)
        self.assertIn("SetAccessRuleProtection($true, $false)", script)
        self.assertIn("S-1-5-18", script)
        self.assertNotIn("icacls", script.lower())
        self.assertNotIn("Administrators", script)
        self.assertNotIn("OWNER RIGHTS", script)
        self.assertEqual(
            kwargs["env"]["AVAYA_GMAIL_BROKER_ACL_TARGET"],
            str(target),
        )
        self.assertEqual(
            kwargs["env"]["AVAYA_GMAIL_BROKER_ACL_USER_SID"],
            "S-1-5-21-1234",
        )
        self.assertTrue(kwargs["check"])
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])

    @unittest.skipUnless(os.name == "nt", "default ACL application is Windows-only")
    def test_state_store_secures_directory_and_atomic_temp_file_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "tools.gmail.gmail_broker_state.apply_windows_acl"
            ) as acl_applier:
                store = BrokerStateStore(Path(tmp))
                store.write(make_state())

        secured_paths = [call.args[0] for call in acl_applier.call_args_list]
        self.assertEqual(secured_paths[0], Path(tmp))
        self.assertEqual(len(secured_paths), 2)
        self.assertEqual(secured_paths[1].parent, Path(tmp))
        self.assertTrue(secured_paths[1].name.startswith(".state.json."))

    @unittest.skipUnless(REAL_WINDOWS_ACL, "requires Windows PowerShell ACLs")
    def test_real_state_replace_uses_exact_directory_and_file_acls(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "broker-state"
            store = BrokerStateStore(state_dir)

            store.write(make_state(instance_id="first"))
            replacement = make_state(instance_id="replacement")
            store.write(replacement)

            self.assertEqual(store.read(), replacement)
            rewrite_file_bytes(store.state_file)
            assert_private_windows_acl(self, state_dir, directory=True)
            assert_private_windows_acl(self, store.state_file, directory=False)

    @unittest.skipUnless(REAL_WINDOWS_ACL, "requires Windows PowerShell ACLs")
    def test_real_log_rotation_preserves_private_writable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "broker-state"
            log_path = state_dir / "broker.log"
            logger = SanitizedRotatingLogger(
                log_path,
                max_bytes=200,
                backup_count=2,
            )
            try:
                for index in range(10):
                    logger.info(
                        "request_finished",
                        request_id=f"req-{index}",
                        method="gmail_search",
                        result_code="OK",
                        elapsed_ms=index,
                    )
            finally:
                logger.close()

            log_files = sorted(state_dir.glob("broker.log*"))
            self.assertGreaterEqual(len(log_files), 2, log_files)
            assert_private_windows_acl(self, state_dir, directory=True)
            for path in log_files:
                rewrite_file_bytes(path)
                assert_private_windows_acl(
                    self,
                    path,
                    directory=False,
                    allow_inherited=True,
                )


class SanitizedRotatingLoggerTests(unittest.TestCase):
    def test_allowed_field_contract_is_explicit_and_finite(self):
        self.assertEqual(
            LIFECYCLE_COUNTER_FIELDS,
            frozenset(
                {
                    "request_count",
                    "browser_start_count",
                    "browser_crash_count",
                    "current_browser_concurrency",
                    "max_browser_concurrency",
                    "uptime_seconds",
                }
            ),
        )
        self.assertEqual(
            ALLOWED_LOG_FIELDS,
            frozenset(
                {
                    "timestamp",
                    "level",
                    "event",
                    "request_id",
                    "method",
                    "result_code",
                    "elapsed_ms",
                    "queue_wait_ms",
                    "queue_depth",
                }
            )
            | LIFECYCLE_COUNTER_FIELDS,
        )

    def test_writes_one_json_line_containing_only_approved_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "broker.log"
            logger = SanitizedRotatingLogger(log_path, acl_applier=None)
            try:
                logger.info(
                    "request_finished",
                    request_id="req-1",
                    method="gmail_search",
                    result_code="OK",
                    elapsed_ms=15,
                    queue_wait_ms=2,
                    queue_depth=0,
                    request_count=1,
                    browser_start_count=1,
                    browser_crash_count=0,
                    current_browser_concurrency=0,
                    max_browser_concurrency=1,
                    uptime_seconds=5,
                )
            finally:
                logger.close()

            lines = log_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(set(payload), ALLOWED_LOG_FIELDS)
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["event"], "request_finished")
        self.assertTrue(payload["timestamp"].endswith("Z"))

    def test_rejects_arbitrary_or_sensitive_fields_without_sentinel_leakage(self):
        sentinel = "SENTINEL_SECRET_7b91"
        forbidden_fields = (
            "debug_detail",
            "token",
            "params",
            "query",
            "body",
            "subject",
            "sender",
            "recipient",
            "message_id",
            "cookie",
        )
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "broker.log"
            logger = SanitizedRotatingLogger(log_path, acl_applier=None)
            try:
                logger.info("broker_started", result_code="OK")
                for field in forbidden_fields:
                    with self.subTest(field=field):
                        with self.assertRaises(UnsafeLogFieldError) as raised:
                            logger.error(
                                "request_rejected",
                                **{field: sentinel},
                            )
                        self.assertNotIn(sentinel, str(raised.exception))
            finally:
                logger.close()

            logged = "".join(
                path.read_text(encoding="utf-8")
                for path in Path(tmp).glob("broker.log*")
            )

        self.assertNotIn(sentinel, logged)
        self.assertEqual(len(logged.splitlines()), 1)

    def test_rejects_invalid_safe_field_values_before_writing(self):
        invalid_fields = (
            {"elapsed_ms": -1},
            {"queue_depth": True},
            {"request_count": 1.5},
            {"method": "gmail search with query"},
            {"result_code": "failure: secret"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "broker.log"
            logger = SanitizedRotatingLogger(log_path, acl_applier=None)
            try:
                for fields in invalid_fields:
                    with self.subTest(fields=fields):
                        with self.assertRaises(ValueError):
                            logger.info("request_finished", **fields)
            finally:
                logger.close()

            self.assertEqual(log_path.read_text(encoding="utf-8"), "")

    def test_rotates_sanitized_json_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "broker.log"
            logger = SanitizedRotatingLogger(
                log_path,
                max_bytes=200,
                backup_count=2,
                acl_applier=None,
            )
            try:
                for index in range(10):
                    logger.info(
                        "request_finished",
                        request_id=f"req-{index}",
                        method="gmail_search",
                        result_code="OK",
                        elapsed_ms=index,
                    )
            finally:
                logger.close()

            log_files = sorted(Path(tmp).glob("broker.log*"))
            self.assertGreaterEqual(len(log_files), 2)
            for path in log_files:
                for line in path.read_text(encoding="utf-8").splitlines():
                    self.assertLessEqual(set(json.loads(line)), ALLOWED_LOG_FIELDS)

    def test_uses_default_per_user_log_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                logger = SanitizedRotatingLogger(acl_applier=None)
                try:
                    expected = (
                        Path(tmp)
                        / "AvayaCaseReview"
                        / "gmail-broker"
                        / "broker.log"
                    )
                    self.assertEqual(logger.path, expected)
                finally:
                    logger.close()

    @unittest.skipUnless(os.name == "nt", "default ACL application is Windows-only")
    def test_logger_secures_directory_and_log_file_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "broker.log"
            with patch(
                "tools.gmail.gmail_broker_state.apply_windows_acl"
            ) as acl_applier:
                logger = SanitizedRotatingLogger(log_path)
                logger.close()

        self.assertEqual(
            [call.args[0] for call in acl_applier.call_args_list],
            [Path(tmp), log_path],
        )


if __name__ == "__main__":
    unittest.main()
