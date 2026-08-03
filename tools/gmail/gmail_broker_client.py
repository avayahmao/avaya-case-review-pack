"""Synchronous authenticated client for the per-user Gmail Edge broker."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from tools.gmail.gmail_broker_protocol import (
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    BrokerErrorCode,
    BrokerRequest,
)
from tools.gmail.gmail_broker_state import (
    AlreadyRunning,
    BrokerState,
    BrokerStateError,
    BrokerStateStore,
    StartupFileLock,
    is_stale_state,
    process_exists as default_process_exists,
)


CLIENT_TIMEOUT_SECONDS = 370.0
STARTUP_TIMEOUT_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.1


class BrokerClientError(RuntimeError):
    """A sanitized client or remote broker failure with a stable code."""

    def __init__(self, code: str | BrokerErrorCode, message: str | None = None) -> None:
        value = code.value if isinstance(code, BrokerErrorCode) else code
        if not isinstance(value, str) or not value:
            raise ValueError("broker client error code must be a non-empty string")
        self.code = value
        super().__init__(message or value)


class BrokerStartTimeout(BrokerClientError):
    def __init__(self, message: str = "Gmail Edge broker did not become ready") -> None:
        super().__init__("BROKER_START_TIMEOUT", message)


class BrokerUnavailable(BrokerClientError):
    def __init__(self, message: str = "Gmail Edge broker is unavailable") -> None:
        super().__init__("BROKER_UNAVAILABLE", message)


class BrokerProtocolMismatch(BrokerClientError):
    def __init__(self, message: str = "Gmail Edge broker protocol mismatch") -> None:
        super().__init__("BROKER_PROTOCOL_MISMATCH", message)


class BrokerClient:
    """Blocking broker API intended to be called through ``asyncio.to_thread``."""

    def __init__(
        self,
        *,
        state_store: BrokerStateStore | None = None,
        process_exists: Callable[[int], bool] = default_process_exists,
        launcher: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        executable: Path | str | None = None,
        broker_script: Path | str | None = None,
        startup_lock_factory: Callable[[], StartupFileLock] | None = None,
        startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        request_timeout: float = CLIENT_TIMEOUT_SECONDS,
    ) -> None:
        self._state_store = state_store or BrokerStateStore()
        self._process_exists = process_exists
        self._launcher = launcher or subprocess.Popen
        self._sleep = sleep
        self._clock = clock
        self._executable = Path(executable or sys.executable).resolve()
        self._broker_script = Path(
            broker_script or Path(__file__).with_name("gmail_edge_broker.py")
        ).resolve()
        self._startup_lock_factory = startup_lock_factory or (
            lambda: StartupFileLock(self._state_store.directory)
        )
        self._startup_timeout = float(startup_timeout)
        self._poll_interval = float(poll_interval)
        self._request_timeout = float(request_timeout)

    def request(self, method: str, params: dict[str, Any]) -> Any:
        """Ensure the advertised broker is healthy, then perform one request."""

        deadline = float(self._clock()) + self._request_timeout
        state = self._discover_healthy_state(deadline)
        if state is None:
            state = self._start_and_wait(deadline)
        return self._send(state, method, params, deadline)

    def _read_current_state(self) -> BrokerState | None:
        try:
            state = self._state_store.read()
        except BrokerStateError:
            return None
        if state is None:
            return None
        if state.protocol_version != PROTOCOL_VERSION:
            raise BrokerProtocolMismatch()
        if is_stale_state(state, process_exists=self._process_exists):
            return None
        return state

    def _discover_healthy_state(self, deadline: float) -> BrokerState | None:
        state = self._read_current_state()
        if state is None:
            return None
        try:
            health = self._send(state, "health", {}, deadline)
        except BrokerProtocolMismatch:
            raise
        except BrokerUnavailable:
            return None
        except BrokerClientError as exc:
            if exc.code == "REQUEST_TIMEOUT" and float(self._clock()) < deadline:
                return None
            if exc.code == "INVALID_REQUEST":
                return None
            raise
        if (
            not isinstance(health, dict)
            or type(health.get("protocol_version")) is not int
            or health["protocol_version"] != PROTOCOL_VERSION
        ):
            raise BrokerProtocolMismatch()
        return state

    def _start_and_wait(self, request_deadline: float) -> BrokerState:
        startup_deadline = min(
            request_deadline,
            float(self._clock()) + self._startup_timeout,
        )
        lock = self._startup_lock_factory()
        acquired = False
        process = None
        try:
            try:
                lock.acquire()
                acquired = True
            except AlreadyRunning:
                pass
            if acquired:
                state = self._discover_healthy_state(startup_deadline)
                if state is not None:
                    return state
                process = self._launch_broker()
            return self._poll_until_ready(startup_deadline, process)
        finally:
            if acquired:
                lock.release()

    def _launch_broker(self) -> Any:
        state_directory = self._state_store.directory.resolve()
        state_directory.mkdir(parents=True, exist_ok=True)
        command = [str(self._executable), str(self._broker_script)]
        environment = os.environ.copy()
        package_root = str(Path(__file__).resolve().parents[2])
        inherited_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            package_root
            if not inherited_python_path
            else os.pathsep.join((package_root, inherited_python_path))
        )
        options: dict[str, Any] = {
            "cwd": str(state_directory),
            "env": environment,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            return self._launcher(command, **options)
        except OSError:
            raise BrokerUnavailable("Unable to start the Gmail Edge broker") from None

    def _poll_until_ready(self, deadline: float, process: Any | None) -> BrokerState:
        while float(self._clock()) < deadline:
            state = self._discover_healthy_state(deadline)
            if state is not None:
                return state
            if process is not None and process.poll() is not None:
                raise BrokerUnavailable("Gmail Edge broker exited during startup")
            remaining = deadline - float(self._clock())
            self._sleep(min(self._poll_interval, remaining))
        raise BrokerStartTimeout()

    def _send(
        self,
        state: BrokerState,
        method: str,
        params: dict[str, Any],
        deadline: float,
    ) -> Any:
        request_id = str(uuid.uuid4())
        try:
            request = BrokerRequest(
                version=PROTOCOL_VERSION,
                id=request_id,
                token=state.token,
                method=method,
                params=params,
            )
            frame = (
                json.dumps(
                    {
                        "version": request.version,
                        "id": request.id,
                        "token": request.token,
                        "method": request.method,
                        "params": request.params,
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
        except (TypeError, ValueError, OverflowError):
            raise BrokerClientError(
                "INVALID_REQUEST",
                "Broker request is not valid",
            ) from None
        if len(frame) > MAX_FRAME_BYTES:
            raise BrokerClientError(
                "INVALID_REQUEST",
                "Broker request exceeds the size limit",
            )

        remaining = self._remaining(deadline)
        try:
            with closing(
                socket.create_connection(
                    (state.host, state.port),
                    timeout=remaining,
                )
            ) as connection:
                connection.settimeout(self._remaining(deadline))
                connection.sendall(frame)
                response_frame = bytearray()
                while not response_frame.endswith(b"\n"):
                    connection.settimeout(self._remaining(deadline))
                    chunk = connection.recv(
                        min(64 * 1024, MAX_FRAME_BYTES + 1 - len(response_frame))
                    )
                    if not chunk:
                        raise BrokerUnavailable(
                            "Gmail Edge broker closed the connection"
                        )
                    response_frame.extend(chunk)
                    if len(response_frame) > MAX_FRAME_BYTES:
                        raise BrokerClientError(
                            "RESPONSE_TOO_LARGE",
                            "Gmail Edge broker response exceeds the size limit",
                        )
        except socket.timeout:
            raise BrokerClientError(
                "REQUEST_TIMEOUT",
                "Gmail Edge broker request timed out",
            ) from None
        except OSError:
            raise BrokerUnavailable() from None

        return self._decode_response(bytes(response_frame), request_id)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - float(self._clock())
        if remaining <= 0:
            raise BrokerClientError(
                "REQUEST_TIMEOUT",
                "Gmail Edge broker request timed out",
            )
        return remaining

    @staticmethod
    def _decode_response(frame: bytes, request_id: str) -> Any:
        try:
            if not frame.endswith(b"\n"):
                raise ValueError
            body = frame[:-1]
            if b"\n" in body or b"\r" in body:
                raise ValueError
            response = json.loads(
                body.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_fields,
                parse_constant=_reject_json_constant,
            )
            if not isinstance(response, dict):
                raise ValueError
            if type(response.get("version")) is not int:
                raise ValueError
            if response["version"] != PROTOCOL_VERSION:
                raise ValueError
            if response.get("id") != request_id:
                raise ValueError
            if type(response.get("ok")) is not bool:
                raise ValueError
            expected_fields = (
                {"version", "id", "ok", "result"}
                if response["ok"]
                else {"version", "id", "ok", "error"}
            )
            if set(response) != expected_fields:
                raise ValueError
        except (KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
            raise BrokerProtocolMismatch() from None

        if response["ok"]:
            return response["result"]
        error = response["error"]
        if not isinstance(error, dict) or set(error) != {"code", "message"}:
            raise BrokerProtocolMismatch()
        code = error.get("code")
        message = error.get("message")
        try:
            remote_code = BrokerErrorCode(code)
        except (TypeError, ValueError):
            raise BrokerProtocolMismatch() from None
        if (
            not isinstance(message, str)
            or not message
            or message != message.strip()
            or not message.isprintable()
        ):
            raise BrokerProtocolMismatch()
        raise BrokerClientError(remote_code, message)


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-standard JSON constant")


__all__ = [
    "CLIENT_TIMEOUT_SECONDS",
    "POLL_INTERVAL_SECONDS",
    "STARTUP_TIMEOUT_SECONDS",
    "BrokerClient",
    "BrokerClientError",
    "BrokerProtocolMismatch",
    "BrokerStartTimeout",
    "BrokerUnavailable",
]
