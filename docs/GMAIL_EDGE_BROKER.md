# Gmail Managed Edge Broker

The migration release uses one local broker process to own the dedicated
Managed Edge profile. Every Gmail MCP stdio process is a client; none of them
launches a browser in the default mode.

## Runtime contract

- Backend default: `GMAIL_BACKEND=edge_broker`.
- Explicit one-release rollback: `GMAIL_BACKEND=legacy_playwright`.
- Broker transport: authenticated NDJSON over `127.0.0.1`.
- Browser owner: one headless Edge context using
  `%USERPROFILE%\.gemini\tools\gmail\edge_broker_profile`.
- Browser work is serialized, so concurrent MCP processes cannot race the
  profile or page state.
- A broker that has been idle for two hours closes Edge and removes its state.
- The broker never logs queries, message IDs, recipients, subjects, bodies,
  cookies, tokens, or response content.

## Exhaustive case-review contract

**Complete Context Before Analysis** processes every Case note before freezing
the primary and note-derived related-ID boundary. The Advanced Gmail Service
cloud bridge then exposes `gmail_list_threads` and `gmail_read_thread_page` so
the Agent can read every message in every matched Gmail thread under one stable
snapshot, exhaust every page token and cursor, and verify counts and hashes.
Attachment bodies are excluded. Any incomplete source, pagination, cursor,
manifest, count, hash, or snapshot check returns `Context collection incomplete`
and blocks the review.

The cloud source is `tools/gmail/cloud/GmailMcpBridge.gs`, deployed to the
existing Gmail MCP Apps Script Web App before the local MCP modules and Agent
SKILL. It is not `examples/optional-appsscript/Code.gs`, and `setup_env.ps1`
does not deploy it locally. Follow `docs/GMAIL_CLOUD_BRIDGE.md` for the
Advanced Gmail Service deployment and verification gate. `gmail_search`,
`gmail_read`, and `gmail_send` remain backward-compatible APIs, but search and
read cannot satisfy exhaustive collection.

## Operator commands

Run these commands from the deployed Gmail tools directory (or use the full
path under `%USERPROFILE%\.gemini\tools\gmail`):

```powershell
python gmail_brokerctl.py status
python gmail_brokerctl.py diagnostics
python gmail_brokerctl.py start
python gmail_brokerctl.py login
python gmail_brokerctl.py stop
```

`status`, `diagnostics`, and `start` return sanitized JSON. Exit code `0`
means the broker is ready; exit code `10` means interactive authentication is
required; `20` means the broker or browser is unavailable; and `30` means a
protocol or application error. `login` opens a headful Edge context only for
the interactive SSO/MFA step, then restores the headless context in all exit
paths. Gmail requests arriving during login fail fast with
`LOGIN_IN_PROGRESS`.

## Authentication and state

The broker state directory is `%LOCALAPPDATA%\AvayaCaseReview\gmail-broker`.
It contains an atomically replaced `state.json`, a lifetime `broker.lock`, a
short-lived `startup.lock`, and a sanitized rotating `broker.log`. The broker
holds the lifetime lock for its entire process lifetime, which prevents two
brokers from owning the profile across Windows sessions or Fast User Switching.

The normal Edge profile and the legacy `chrome_profile` are never copied into
the broker profile. The legacy profile remains available for the explicit
rollback mode only.

## Troubleshooting

1. Run `python gmail_brokerctl.py status`.
2. If the exit code is `10`, run `python gmail_brokerctl.py login` and complete
   the SSO/MFA flow in the opened Edge window.
3. If the broker is unavailable, run `python gmail_brokerctl.py stop`, then
   retry a read-only `status` or `start`. The MCP client also lazy-starts one
   broker when a request arrives.
4. Use `diagnostics` to report PID, build ID, authentication state, queue
   depth, browser starts/crashes, uptime, and maximum browser concurrency.
5. Do not delete the profile or state directory while the broker is running.

### Explicit rollback

For one-release rollback, set `GMAIL_BACKEND=legacy_playwright` for the MCP
process and restart that process. The legacy backend launches the existing
per-request Playwright Chromium context with `chrome_profile`. There is no
automatic fallback: restore `GMAIL_BACKEND=edge_broker` after the read-only
rollback check. Do not use rollback to send mail unless separately authorized.

## Acceptance evidence

The migration is considered ready only when four MCP clients can complete a
20-request read-only soak with one broker PID, one Edge root process using the
dedicated profile, and `max_browser_concurrency: 1`; a broker restart retains
authentication; and the explicit legacy smoke test remains available.

The repository soak test (`tests/test_gmail_broker_soak.py`) exercises the
four-client/20-request path, one adapter start, serialized concurrency, timeout
and application-error mapping, and sentinel-free logs. A real workstation
deployment must additionally record the broker PID, exact Edge profile command
line, restart persistence, and read-only legacy rollback result without
capturing message content or query text.
