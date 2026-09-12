# Codex Plugin Host Compatibility Characterization

## Scope

This characterization covers the Codex CLI on Windows and the release Windows
desktop application. It records the empirical ruling for MCP launch arguments
and the Git marketplace SHA-pinning gate. It intentionally used disposable
`CODEX_HOME` profiles and did not copy or inspect credentials.

## Recorded environment

| Surface | Version | Marketplace source type | Status |
| --- | --- | --- | --- |
| Codex CLI | `0.154` | HTTPS Git (`https://github.com/avayahmao/avaya-case-review-pack`) | SHA marketplace test passed; relative MCP script launch failed outside plugin CWD |
| Codex desktop | Release Windows desktop build (version pending capture) | Pending | Pending final release gate |

## Marketplace SHA result

The local worktree's initial candidate SHA was not published on GitHub, so it
could not characterize a public-Git marketplace. The transaction was repeated
against the full `origin/main` SHA:
`b68a8fb46135fad92de3de8d9ca170254f540bf6`.

In a newly created temporary `CODEX_HOME`, all results were successful:

| Check | Result |
| --- | --- |
| `marketplace add --ref <origin/main SHA>` | `true` |
| Plugin add | `true` |
| Plugin remove | `true` |
| Marketplace remove | `true` |
| Marketplace re-add at the same SHA | `true` |
| Re-added marketplace checkout HEAD equals requested SHA | `true` |

`MARKETPLACE_SHA_REF=SUPPORTED` for Codex CLI `0.153.4` with a public HTTPS
Git source. The isolated-profile transaction also establishes that Codex CLI
requires the configured `CODEX_HOME` directory to exist before plugin commands
run.

## Relative MCP result

Codex CLI `0.154` was run from a working directory outside the installed probe
plugin. With `args: ["probe/probe_mcp.py"]`, the probe process never started
and Codex reported an MCP handshake failure. Changing only that argument to the
absolute script path registered the server and called
`report_launch_context` successfully. This isolates argument resolution as the
failure and rules out the probe implementation and MCP protocol.

| Host | Relative script argument | Absolute script argument |
| --- | --- | --- |
| CLI `0.154` outside plugin CWD | failed before process start | registered and called successfully |
| Windows desktop | no longer required for selecting the safer fallback | pending final installed-package gate |

`RELATIVE_MCP_ARGS=UNSUPPORTED`.

## Decision

Use the selected Python-package fallback. The plugin launches
`avaya_case_review_runtime.gmail_mcp_server` and
`avaya_case_review_runtime.casetomd_mcp_bridge` with `python -m`; compatibility
scripts remain only as thin aliases/entry points. Do not use relative script
arguments, placeholder variables, cache discovery, or cache mutation. Desktop
evidence remains the final installed-package release gate.
