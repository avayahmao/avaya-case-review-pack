# Single Managed Edge Broker Design

**Date:** 2026-08-03
**Status:** Approved architecture; written specification awaiting final review

## Context

The production Gmail MCP currently launches one Playwright Chromium persistent context per request. Multiple MCP server processes can therefore open the same profile independently, and every request pays browser startup and SSO-state costs.

The Managed Edge PoC proved that an isolated Edge profile can:

- authenticate through Avaya Microsoft/MCAS SSO;
- complete repeated Gmail Apps Script probes through one context;
- retain authentication across process restarts;
- avoid modifying the production Chromium profile or the user's normal Edge profile.

Production migration now requires one process to own Edge and its profile while all Gmail MCP processes act as clients.

## Goals

1. Guarantee one broker process and one Edge browser owner per Windows user.
2. Allow any number of Gmail MCP stdio processes to share that broker.
3. Serialize all browser operations to prevent profile and page-state races.
4. Preserve the existing `gmail_search`, `gmail_read`, and `gmail_send` MCP contracts.
5. Return structured authentication errors instead of login HTML.
6. Support interactive SSO/MFA through broker-controlled context switching.
7. Lazy-start the broker and stop it after two hours of inactivity.
8. Retain an explicit legacy backend for one release as rollback.

## Non-Goals

- Do not expose a remote DevTools/CDP endpoint.
- Do not allow MCP processes to launch Edge directly in broker mode.
- Do not bypass Conditional Access, MFA, TLS, or browser security.
- Do not log email bodies, recipient data, cookies, authentication tokens, or message contents.
- Do not automatically fall back to legacy mode after an authentication or broker error.
- Do not remove the legacy backend until one stable release has completed.
- Do not reuse the user's normal Edge profile.

## Architecture

```text
Gmail MCP process 1 ─┐
Gmail MCP process 2 ─┼─> Broker Client ─> 127.0.0.1 NDJSON ─> Single Edge Broker
Gmail MCP process N ─┘                                      │
                                                           ├─ Request queue
                                                           ├─ Auth state machine
                                                           └─ One Edge context/profile
                                                                    │
                                                                    └─ Gmail Apps Script
```

## Components

### `gmail_edge_common.py`

Shared, browser-independent primitives extracted from the successful PoC:

- authentication-state enum;
- safe response classifier;
- public diagnostic result;
- profile-path validation;
- probe URL construction;
- response redaction helpers.

Both the PoC and production broker import this module.

### `gmail_edge_broker.py`

The only process allowed to open the production Edge broker profile.

Responsibilities:

- acquire the per-user singleton mutex;
- bind a loopback TCP server;
- generate a per-start authentication token;
- publish broker state atomically;
- own one long-lived Managed Edge context;
- queue and serialize Gmail actions;
- classify authentication redirects;
- switch between headless and interactive contexts for login;
- restart Edge once after a browser crash;
- close Edge and exit after the idle timeout;
- remove its state file on clean shutdown.

### `gmail_broker_client.py`

Shared client used by every Gmail MCP process and control CLI.

Responsibilities:

- read and validate the broker state file;
- perform authenticated health checks;
- start the broker when absent;
- wait for the singleton broker to become ready;
- send one framed request;
- enforce response timeout and maximum size;
- translate broker errors into typed client errors;
- never launch a browser.

### `gmail_brokerctl.py`

Operator CLI:

- `status`
- `login`
- `start`
- `stop`
- `diagnostics`

Diagnostics expose only protocol version, PID, Edge state, authentication state, request counts, queue depth, uptime, and timing.

### `gmail_mcp_server.py`

Remains the stdio MCP entrypoint.

In broker mode it becomes a thin adapter:

- validate MCP arguments;
- map tool name to broker method;
- send the broker request;
- return the existing Apps Script response text;
- map `AUTH_REQUIRED`, timeout, and broker errors to explicit tool messages.

It must not import or start Playwright in broker mode.

### Legacy backend

Move the current Playwright-per-request implementation into a focused legacy module. Backend selection is explicit:

- `GMAIL_BACKEND=edge_broker` — default for the migration release;
- `GMAIL_BACKEND=legacy_playwright` — rollback only.

There is no automatic fallback. Silent fallback would reintroduce multiple profile owners and hide broker failures.

## Broker State

Directory:

`%LOCALAPPDATA%\AvayaCaseReview\gmail-broker\`

Files:

- `state.json` — current endpoint and process metadata;
- `broker.log` — sanitized lifecycle/health log with rotation;
- `startup.lock` — short-lived client startup coordination.

The Edge profile remains separate:

`%USERPROFILE%\.gemini\tools\gmail\edge_broker_profile`

### State schema

```json
{
  "protocol_version": 1,
  "pid": 12345,
  "host": "127.0.0.1",
  "port": 49152,
  "token": "random-per-start-token",
  "started_at": "2026-08-03T00:00:00Z"
}
```

The state file is written to a temporary file and atomically replaced only after the broker is ready.

## Single-Instance Control

Use a Windows named mutex scoped to the current user session:

`Local\AvayaCaseReview.GmailEdgeBroker.v1`

Rules:

1. The broker must acquire the mutex before opening the state file or Edge.
2. A second broker exits without touching the profile.
3. Multiple clients may race to start the broker; only the mutex owner continues.
4. Clients poll the health method until one broker publishes valid state.
5. Stale state is ignored when the PID is absent or health/token validation fails.

The startup lock reduces redundant process launches; the named mutex remains the authoritative singleton boundary.

## Transport and Protocol

Use `asyncio.start_server` bound to `127.0.0.1` and an ephemeral port.

Framing: one UTF-8 JSON object per line.

Request:

```json
{
  "version": 1,
  "id": "uuid",
  "token": "random-per-start-token",
  "method": "gmail_search",
  "params": {"query": "1-23508794022"}
}
```

Success:

```json
{
  "version": 1,
  "id": "uuid",
  "ok": true,
  "result": "Apps Script response text"
}
```

Error:

```json
{
  "version": 1,
  "id": "uuid",
  "ok": false,
  "error": {
    "code": "AUTH_REQUIRED",
    "message": "Interactive Gmail authentication is required"
  }
}
```

Allowed methods:

- `health`
- `gmail_search`
- `gmail_read`
- `gmail_send`
- `auth_login`
- `shutdown`

Security limits:

- reject non-loopback connections;
- constant-time token comparison;
- 8 MiB request/response limit;
- 60-second Gmail request timeout;
- 330-second interactive login timeout;
- reject unknown fields, versions, and methods;
- never include token or params in logs.

## Browser Ownership and Queueing

The broker launches:

```python
playwright.chromium.launch_persistent_context(
    channel="msedge",
    user_data_dir=edge_broker_profile,
    headless=True,
)
```

All browser operations execute under one `asyncio.Lock`.

Each operation:

1. creates a new page;
2. navigates to the case-bounded Apps Script URL;
3. detects Microsoft, MCAS, or Google login redirects before reading a body;
4. waits for the application response;
5. returns the response text without logging it;
6. closes the page;
7. updates activity and timing counters.

The lock guarantees a maximum browser-operation concurrency of one even when many clients submit requests concurrently.

## Authentication State Machine

States:

- `STARTING`
- `AUTHENTICATED`
- `AUTH_REQUIRED_MICROSOFT`
- `AUTH_REQUIRED_GOOGLE`
- `LOGIN_IN_PROGRESS`
- `BROWSER_ERROR`
- `STOPPED`

### Normal request

- An authenticated response is returned normally.
- A Microsoft/MCAS/Google redirect returns `AUTH_REQUIRED`.
- Login HTML is never returned as Gmail data.

### Interactive login

`gmail_brokerctl login` sends `auth_login`.

The broker:

1. acquires the operation lock;
2. stops accepting new Gmail work into execution while requests remain queued;
3. closes the headless context;
4. opens a headful Edge context with the same broker profile;
5. waits for an authenticated Apps Script response;
6. closes the headful context;
7. reopens the headless context;
8. runs one verification probe;
9. returns success only if verification is authenticated.

Only the broker opens the profile, so no profile lock conflict occurs during login.

## Lifecycle

### Lazy start

On the first MCP request:

1. client reads broker state;
2. health check fails or state is absent;
3. client starts `pythonw.exe gmail_edge_broker.py serve` hidden;
4. broker singleton wins the mutex and publishes state;
5. client waits up to 15 seconds for health;
6. request proceeds.

### Idle shutdown

- Idle timeout: two hours since the last completed request.
- No shutdown while a request or login is active.
- Close the Edge context before exiting.
- Remove state atomically.

### Crash recovery

- If Edge crashes, recreate the context once and retry only safe read operations.
- Do not automatically retry `gmail_send`, because delivery status may be ambiguous.
- If the broker process dies, the next client ignores stale state and starts a replacement.
- Browser crash counters and last error code are visible in diagnostics.

## Client and MCP Error Contract

Typed errors:

- `AUTH_REQUIRED`
- `BROKER_START_TIMEOUT`
- `BROKER_UNAVAILABLE`
- `BROKER_PROTOCOL_MISMATCH`
- `REQUEST_TIMEOUT`
- `RESPONSE_TOO_LARGE`
- `BROWSER_ERROR`
- `APP_ERROR`
- `INVALID_REQUEST`

MCP output must clearly state the error and operator command when action is possible, for example:

`AUTH_REQUIRED: run python gmail_brokerctl.py login`

## Installer Changes

The migration release:

1. installs Python `mcp` and `playwright`;
2. keeps the Chromium binary installation for one-release legacy rollback;
3. deploys broker, client, control, common, and legacy modules;
4. creates the broker state directory;
5. restricts the directory ACL to the current user;
6. sets `GMAIL_BACKEND=edge_broker` in MCP configuration;
7. runs broker `status`;
8. opens interactive login only when status returns `AUTH_REQUIRED`;
9. never starts a second browser owner.

The existing `chrome_profile` remains untouched for rollback.

## Observability

Allowed log fields:

- UTC timestamp;
- request ID;
- method name;
- result/error code;
- elapsed milliseconds;
- queue wait milliseconds;
- queue depth;
- broker and Edge lifecycle events.

Forbidden log fields:

- request params;
- Gmail query text;
- email body, subject, sender, recipients, or message ID;
- Apps Script response body;
- broker token;
- cookies or profile contents.

## Testing

### Unit tests

- protocol schema and version rejection;
- token validation;
- size and timeout limits;
- auth-state mapping;
- backend selection;
- send retry prohibition;
- stale-state detection;
- profile path isolation.

### Integration tests

Use a fake browser adapter and real loopback broker:

- four simulated MCP clients;
- 20 concurrent search/read requests;
- one broker instance;
- one browser-adapter instance;
- maximum browser concurrency equals one;
- response IDs match requests;
- unauthorized and malformed requests are rejected;
- broker restart recovers stale state;
- idle shutdown waits for active requests.

### Live tests

- broker login with a fresh `edge_broker_profile`;
- four actual MCP processes;
- concurrent case-bounded queries;
- broker and Edge PID count;
- authentication persistence across broker restart;
- explicit `AUTH_REQUIRED` after controlled session invalidation when feasible;
- legacy rollback smoke test.

## Migration

1. Add broker modules and tests without changing the default backend.
2. Run fake-browser concurrency and protocol tests.
3. Deploy broker mode to the current workstation.
4. Authenticate `edge_broker_profile`.
5. Run four-process/20-request live soak.
6. Set broker mode as default for the migration release.
7. Preserve `legacy_playwright` as an explicit rollback mode for one release.
8. Remove legacy mode only after production observation and user approval.

## Rollback

Set:

`GMAIL_BACKEND=legacy_playwright`

Restart Antigravity/Codex MCP processes. The existing production `chrome_profile` remains available and unchanged.

Rollback does not delete broker state or profile automatically; cleanup is a separate explicit operation.

## Acceptance Criteria

The production migration is complete when:

- four MCP processes use one broker PID and one Edge root process;
- 20 concurrent test requests complete successfully;
- measured maximum browser concurrency is one;
- no profile lock or duplicate-browser error occurs;
- existing Gmail tool names and response behavior remain compatible;
- broker restart preserves authentication;
- authentication expiry returns structured `AUTH_REQUIRED`;
- logs contain no sensitive request or email data;
- installer only prompts for login when required;
- legacy rollback works;
- all unit, integration, contract, installer, syntax, and whitespace checks pass.
