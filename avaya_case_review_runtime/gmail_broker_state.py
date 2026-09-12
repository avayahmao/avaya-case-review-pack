"""Per-user discovery state for the single Gmail Edge broker."""

from __future__ import annotations

import errno
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Protocol


STATE_FILE_NAME = "state.json"
LOG_FILE_NAME = "broker.log"
BROKER_LOCK_FILE_NAME = "broker.lock"
STARTUP_LOCK_FILE_NAME = "startup.lock"

_STATE_FIELDS = frozenset(
    {
        "protocol_version",
        "build_id",
        "instance_id",
        "pid",
        "host",
        "port",
        "token",
        "started_at",
    }
)


class BrokerStateError(ValueError):
    """Raised when broker discovery state does not match the strict schema."""


class AlreadyRunning(RuntimeError):
    """Raised when another broker owns the lifetime file lock."""


@dataclass(frozen=True)
class BrokerPaths:
    """All per-user runtime paths used by the broker."""

    directory: Path
    state_file: Path
    log_file: Path
    broker_lock_file: Path
    startup_lock_file: Path

    @classmethod
    def from_directory(cls, directory: Path | str) -> "BrokerPaths":
        root = Path(directory)
        return cls(
            directory=root,
            state_file=root / STATE_FILE_NAME,
            log_file=root / LOG_FILE_NAME,
            broker_lock_file=root / BROKER_LOCK_FILE_NAME,
            startup_lock_file=root / STARTUP_LOCK_FILE_NAME,
        )


def default_broker_paths(
    local_app_data: Path | str | None = None,
    *,
    user_home: Path | str | None = None,
) -> BrokerPaths:
    """Return the current user's broker paths without creating them."""

    if local_app_data is None:
        configured = os.environ.get("LOCALAPPDATA")
        if configured:
            local_app_data = configured
        else:
            home = Path(user_home) if user_home is not None else Path.home()
            local_app_data = home / "AppData" / "Local"
    directory = Path(local_app_data) / "AvayaCaseReview" / "gmail-broker"
    return BrokerPaths.from_directory(directory)


@dataclass(frozen=True, repr=False)
class BrokerState:
    protocol_version: int
    build_id: str
    instance_id: str
    pid: int
    host: str
    port: int
    token: str
    started_at: str

    def __post_init__(self) -> None:
        _require_positive_integer("protocol_version", self.protocol_version)
        _require_nonempty_string("build_id", self.build_id)
        _require_nonempty_string("instance_id", self.instance_id)
        _require_positive_integer("pid", self.pid)
        _require_nonempty_string("host", self.host)
        if self.host != "127.0.0.1":
            raise BrokerStateError("host must be the IPv4 loopback address")
        _require_positive_integer("port", self.port)
        if self.port > 65535:
            raise BrokerStateError("port must be between 1 and 65535")
        _require_nonempty_string("token", self.token)
        _require_nonempty_string("started_at", self.started_at)

    def __repr__(self) -> str:
        return (
            "BrokerState("
            f"protocol_version={self.protocol_version!r}, "
            f"build_id={self.build_id!r}, "
            f"instance_id={self.instance_id!r}, "
            f"pid={self.pid!r}, "
            f"host={self.host!r}, "
            f"port={self.port!r}, "
            "token='[REDACTED]', "
            f"started_at={self.started_at!r})"
        )


def _require_positive_integer(field_name: str, value: object) -> None:
    if type(value) is not int or value <= 0:
        raise BrokerStateError(f"{field_name} must be a positive integer")


def _require_nonempty_string(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise BrokerStateError(f"{field_name} must be a non-empty string")


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BrokerStateError(f"duplicate state field: {key}")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise BrokerStateError("non-standard JSON constants are not allowed")


_WINDOWS_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$target = [Environment]::GetEnvironmentVariable(
    'AVAYA_GMAIL_BROKER_ACL_TARGET',
    [EnvironmentVariableTarget]::Process
)
$userSidText = [Environment]::GetEnvironmentVariable(
    'AVAYA_GMAIL_BROKER_ACL_USER_SID',
    [EnvironmentVariableTarget]::Process
)
if ([string]::IsNullOrWhiteSpace($target)) {
    throw 'ACL target is required.'
}
if ([string]::IsNullOrWhiteSpace($userSidText)) {
    $userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
} else {
    $userSid = New-Object Security.Principal.SecurityIdentifier($userSidText)
}
$systemSid = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
$rights = [Security.AccessControl.FileSystemRights]::FullControl
$allow = [Security.AccessControl.AccessControlType]::Allow
$noPropagation = [Security.AccessControl.PropagationFlags]::None

if ([IO.Directory]::Exists($target)) {
    $security = New-Object Security.AccessControl.DirectorySecurity
    $security.SetAccessRuleProtection($true, $false)
    $security.SetOwner($userSid)
    $inheritance = (
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    )
    $userRule = New-Object Security.AccessControl.FileSystemAccessRule `
        -ArgumentList @($userSid, $rights, $inheritance, $noPropagation, $allow)
    $systemRule = New-Object Security.AccessControl.FileSystemAccessRule `
        -ArgumentList @($systemSid, $rights, $inheritance, $noPropagation, $allow)
    [void]$security.AddAccessRule($userRule)
    [void]$security.AddAccessRule($systemRule)
    [IO.Directory]::SetAccessControl($target, $security)
} elseif ([IO.File]::Exists($target)) {
    $security = New-Object Security.AccessControl.FileSecurity
    $security.SetAccessRuleProtection($true, $false)
    $security.SetOwner($userSid)
    $userRule = New-Object Security.AccessControl.FileSystemAccessRule `
        -ArgumentList @($userSid, $rights, $allow)
    $systemRule = New-Object Security.AccessControl.FileSystemAccessRule `
        -ArgumentList @($systemSid, $rights, $allow)
    [void]$security.AddAccessRule($userRule)
    [void]$security.AddAccessRule($systemRule)
    [IO.File]::SetAccessControl($target, $security)
} else {
    throw 'ACL target does not exist.'
}
"""
_SID_PATTERN = re.compile(r"S-\d+(?:-\d+)+\Z", re.IGNORECASE)


def apply_windows_acl(
    path: Path | str,
    *,
    current_user_sid: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Replace a runtime path's DACL with current-user and SYSTEM rules."""

    target = Path(path).resolve(strict=False)
    if current_user_sid is not None and (
        not isinstance(current_user_sid, str)
        or _SID_PATTERN.fullmatch(current_user_sid) is None
    ):
        raise ValueError("current_user_sid must be a valid Windows SID")
    environment = dict(os.environ)
    environment["AVAYA_GMAIL_BROKER_ACL_TARGET"] = str(target)
    environment.pop("AVAYA_GMAIL_BROKER_ACL_USER_SID", None)
    if current_user_sid is not None:
        environment["AVAYA_GMAIL_BROKER_ACL_USER_SID"] = current_user_sid
    runner(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _WINDOWS_ACL_SCRIPT,
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


_DEFAULT_ACL = object()


class BrokerStateStore:
    """Strict, atomic broker-state persistence."""

    def __init__(
        self,
        directory: Path | str | None = None,
        *,
        acl_applier: Callable[[Path], None] | None | object = _DEFAULT_ACL,
    ) -> None:
        self.paths = (
            default_broker_paths()
            if directory is None
            else BrokerPaths.from_directory(directory)
        )
        self.directory = self.paths.directory
        self.state_file = self.paths.state_file
        if acl_applier is _DEFAULT_ACL:
            self._acl_applier: Callable[[Path], None] | None = (
                apply_windows_acl if os.name == "nt" else None
            )
        elif acl_applier is None or callable(acl_applier):
            self._acl_applier = acl_applier
        else:
            raise TypeError("acl_applier must be callable or None")

    def read(self) -> BrokerState | None:
        try:
            raw = self.state_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as exc:
            raise BrokerStateError("unable to read broker state") from exc

        try:
            payload = json.loads(
                raw,
                object_pairs_hook=_strict_json_object,
                parse_constant=_reject_json_constant,
            )
        except BrokerStateError:
            raise
        except (json.JSONDecodeError, UnicodeError, TypeError) as exc:
            raise BrokerStateError("broker state is not valid UTF-8 JSON") from exc

        if not isinstance(payload, dict):
            raise BrokerStateError("broker state must be a JSON object")
        fields = frozenset(payload)
        if fields != _STATE_FIELDS:
            raise BrokerStateError("broker state fields do not match the schema")
        try:
            return BrokerState(**payload)
        except TypeError as exc:
            raise BrokerStateError("broker state fields do not match the schema") from exc

    def write(self, state: BrokerState) -> None:
        if not isinstance(state, BrokerState):
            raise TypeError("state must be a BrokerState")

        self.directory.mkdir(parents=True, exist_ok=True)
        self._apply_acl(self.directory)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.directory,
            prefix=f".{STATE_FILE_NAME}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    asdict(state),
                    stream,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._apply_acl(temporary_path)
            os.replace(temporary_path, self.state_file)
        except BaseException:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            raise

    def cleanup(
        self,
        instance_id: str,
        *,
        owner_lock: "LifetimeFileLock",
    ) -> bool:
        _require_nonempty_string("instance_id", instance_id)
        if not isinstance(owner_lock, LifetimeFileLock):
            raise TypeError("owner_lock must be a LifetimeFileLock")
        if not owner_lock.is_acquired:
            raise RuntimeError("broker owner lock must be held during cleanup")
        if (
            owner_lock.path.resolve(strict=False)
            != self.paths.broker_lock_file.resolve(strict=False)
        ):
            raise ValueError("owner_lock does not protect this state directory")
        state = self.read()
        if state is None or state.instance_id != instance_id:
            return False
        try:
            self.state_file.unlink()
        except FileNotFoundError:
            return False
        return True

    def _apply_acl(self, path: Path) -> None:
        if self._acl_applier is not None:
            self._acl_applier(path)


def process_exists(pid: int) -> bool:
    """Return whether a process is present without requiring access to it."""

    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        return True
    return True


def _windows_process_exists(pid: int) -> bool:
    """Query Windows process state without sending a console-control signal."""

    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    error_invalid_parameter = 87

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        pid,
    )
    if not handle:
        error = ctypes.get_last_error()
        if error == error_access_denied:
            return True
        if error == error_invalid_parameter:
            return False
        return False

    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(
            handle,
            ctypes.byref(exit_code),
        ):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def is_stale_state(
    state: BrokerState,
    *,
    process_exists: Callable[[int], bool] = process_exists,
) -> bool:
    """Return true when the process advertised by state is no longer present."""

    if not isinstance(state, BrokerState):
        raise TypeError("state must be a BrokerState")
    return not process_exists(state.pid)


class LockBackend(Protocol):
    """Backend seam for the platform byte-range lock."""

    def acquire(self, stream: BinaryIO) -> None: ...

    def release(self, stream: BinaryIO) -> None: ...


class MsvcrtLockBackend:
    """Non-blocking one-byte Windows file-lock backend."""

    def acquire(self, stream: BinaryIO) -> None:
        try:
            import msvcrt
        except ImportError as exc:  # pragma: no cover - Windows production path
            raise OSError(errno.ENOSYS, "msvcrt locking is unavailable") from exc
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

    def release(self, stream: BinaryIO) -> None:
        try:
            import msvcrt
        except ImportError as exc:  # pragma: no cover - Windows production path
            raise OSError(errno.ENOSYS, "msvcrt locking is unavailable") from exc
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


_LOCK_CONTENTION_ERRNOS = frozenset(
    value
    for value in (
        errno.EACCES,
        errno.EAGAIN,
        getattr(errno, "EDEADLK", None),
    )
    if value is not None
)


class LifetimeFileLock:
    """Hold the broker's authoritative owner lock until explicit release."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        backend: LockBackend | None = None,
        acl_applier: Callable[[Path], None] | None | object = _DEFAULT_ACL,
    ) -> None:
        self.path = (
            default_broker_paths().broker_lock_file if path is None else Path(path)
        )
        self._backend = backend if backend is not None else MsvcrtLockBackend()
        if acl_applier is _DEFAULT_ACL:
            self._acl_applier: Callable[[Path], None] | None = (
                apply_windows_acl if os.name == "nt" else None
            )
        elif acl_applier is None or callable(acl_applier):
            self._acl_applier = acl_applier
        else:
            raise TypeError("acl_applier must be callable or None")
        self._stream: BinaryIO | None = None

    @property
    def is_acquired(self) -> bool:
        return self._stream is not None

    def acquire(self) -> "LifetimeFileLock":
        if self._stream is not None:
            raise RuntimeError("file lock is already acquired by this object")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._apply_acl(self.path.parent)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        stream = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b"\0")
                stream.flush()
                os.fsync(stream.fileno())
            stream.seek(0)
            self._apply_acl(self.path)
        except BaseException:
            stream.close()
            raise

        try:
            self._backend.acquire(stream)
        except OSError as exc:
            stream.close()
            if exc.errno in _LOCK_CONTENTION_ERRNOS:
                raise AlreadyRunning(
                    f"another Gmail Edge broker owns {self.path}"
                ) from exc
            raise
        except BaseException:
            stream.close()
            raise

        self._stream = stream
        return self

    def _apply_acl(self, path: Path) -> None:
        if self._acl_applier is not None:
            self._acl_applier(path)

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        self._stream = None
        try:
            self._backend.release(stream)
        finally:
            stream.close()

    def __enter__(self) -> "LifetimeFileLock":
        return self.acquire()

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.release()


class StartupFileLock(LifetimeFileLock):
    """Optional short-lived lock for coordinating racing client startups."""

    def __init__(
        self,
        directory: Path | str | None = None,
        *,
        backend: LockBackend | None = None,
        acl_applier: Callable[[Path], None] | None | object = _DEFAULT_ACL,
    ) -> None:
        paths = (
            default_broker_paths()
            if directory is None
            else BrokerPaths.from_directory(directory)
        )
        super().__init__(
            paths.startup_lock_file,
            backend=backend,
            acl_applier=acl_applier,
        )


LIFECYCLE_COUNTER_FIELDS = frozenset(
    {
        "request_count",
        "browser_start_count",
        "browser_crash_count",
        "current_browser_concurrency",
        "max_browser_concurrency",
        "uptime_seconds",
    }
)
ALLOWED_LOG_FIELDS = frozenset(
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
) | LIFECYCLE_COUNTER_FIELDS
_CALLER_LOG_FIELDS = ALLOWED_LOG_FIELDS - {"timestamp", "level", "event"}
_NUMERIC_LOG_FIELDS = frozenset(
    {"elapsed_ms", "queue_wait_ms", "queue_depth"}
) | LIFECYCLE_COUNTER_FIELDS
_LOG_FIELD_ORDER = (
    "request_id",
    "method",
    "result_code",
    "elapsed_ms",
    "queue_wait_ms",
    "queue_depth",
    "request_count",
    "browser_start_count",
    "browser_crash_count",
    "current_browser_concurrency",
    "max_browser_concurrency",
    "uptime_seconds",
)
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
_EVENT_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_METHOD_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_RESULT_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


class UnsafeLogFieldError(ValueError):
    """Raised before unapproved structured data can reach the broker log."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SanitizedRotatingLogger:
    """Write allowlisted JSON lifecycle records to a rotating file."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        max_bytes: int = 1_000_000,
        backup_count: int = 3,
        acl_applier: Callable[[Path], None] | None | object = _DEFAULT_ACL,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if type(backup_count) is not int or backup_count <= 0:
            raise ValueError("backup_count must be a positive integer")
        if not callable(clock):
            raise TypeError("clock must be callable")

        self.path = default_broker_paths().log_file if path is None else Path(path)
        if acl_applier is _DEFAULT_ACL:
            self._acl_applier: Callable[[Path], None] | None = (
                apply_windows_acl if os.name == "nt" else None
            )
        elif acl_applier is None or callable(acl_applier):
            self._acl_applier = acl_applier
        else:
            raise TypeError("acl_applier must be callable or None")
        self._clock = clock
        self._closed = False

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._apply_acl(self.path.parent)
        self._handler = RotatingFileHandler(
            self.path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=False,
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._apply_acl(self.path)
        self._logger = logging.getLogger(
            f"avaya.gmail_broker.sanitized.{id(self)}"
        )
        self._logger.handlers.clear()
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        self._logger.addHandler(self._handler)

    def log(self, level: str, event: str, **fields: object) -> None:
        if self._closed:
            raise RuntimeError("logger is closed")
        if not isinstance(level, str) or level not in _LEVELS:
            raise ValueError("level is not allowed")
        if not isinstance(event, str) or _EVENT_PATTERN.fullmatch(event) is None:
            raise ValueError("event is not a safe lifecycle name")
        if not set(fields).issubset(_CALLER_LOG_FIELDS):
            raise UnsafeLogFieldError("one or more structured log fields are not allowed")

        for field, value in fields.items():
            self._validate_field(field, value)

        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        timestamp = now.astimezone(timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        payload: dict[str, object] = {
            "timestamp": timestamp,
            "level": level,
            "event": event,
        }
        for field in _LOG_FIELD_ORDER:
            if field in fields:
                payload[field] = fields[field]
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        self._logger.log(_LEVELS[level], encoded)
        self._handler.flush()

    def debug(self, event: str, **fields: object) -> None:
        self.log("DEBUG", event, **fields)

    def info(self, event: str, **fields: object) -> None:
        self.log("INFO", event, **fields)

    def warning(self, event: str, **fields: object) -> None:
        self.log("WARNING", event, **fields)

    def error(self, event: str, **fields: object) -> None:
        self.log("ERROR", event, **fields)

    def critical(self, event: str, **fields: object) -> None:
        self.log("CRITICAL", event, **fields)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._logger.removeHandler(self._handler)
        self._handler.close()

    def __enter__(self) -> "SanitizedRotatingLogger":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def _apply_acl(self, path: Path) -> None:
        if self._acl_applier is not None:
            self._acl_applier(path)

    @staticmethod
    def _validate_field(field: str, value: object) -> None:
        if field in _NUMERIC_LOG_FIELDS:
            if type(value) is not int or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
            return
        pattern = {
            "request_id": _REQUEST_ID_PATTERN,
            "method": _METHOD_PATTERN,
            "result_code": _RESULT_CODE_PATTERN,
        }[field]
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise ValueError(f"{field} is not a safe log value")
