# Codex Plugin Host Compatibility Characterization

## Scope

This characterization covers the Codex CLI on Windows and the release Windows
desktop application. It is the compatibility gate for relative MCP arguments
and Git marketplace SHA pinning. It intentionally used disposable `CODEX_HOME`
profiles and did not copy or inspect credentials.

## Recorded environment

| Surface | Version | Marketplace source type | Status |
| --- | --- | --- | --- |
| Codex CLI | `0.153.4` | HTTPS Git (`https://github.com/avayahmao/avaya-case-review-pack`) | SHA marketplace test passed; MCP launch pending authentication |
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

The local fixture marketplace and `relative-path-probe` plugin installed in an
isolated profile. `OPENAI_API_KEY` availability was checked as a boolean only:
`false`. The CLI launch was not retried because the disposable profile is not
authenticated. No normal-profile credentials were read or copied. Consequently,
neither launch-path predicate was observed:

| Host | `script_under_installed_plugin_root` | `cwd_outside_installed_plugin_root` |
| --- | --- | --- |
| CLI `0.153.4` | not verified | not verified |
| Windows desktop | pending | pending |

`RELATIVE_MCP_ARGS=PENDING`.

## Decision

Do not treat relative MCP arguments as supported until the installed fixture is
run in a disposable, authenticated Windows account. The desktop check remains
a final release gate because the active desktop session cannot safely reload a
test plugin.
