# Codex Plugin Host Compatibility Characterization

## Scope

This characterization covers the Codex CLI on Windows and the release Windows
desktop application. It is the compatibility gate for relative MCP arguments
and Git marketplace SHA pinning. It intentionally used disposable `CODEX_HOME`
profiles and did not copy or inspect credentials.

## Recorded environment

| Surface | Version | Marketplace source type | Status |
| --- | --- | --- | --- |
| Codex CLI | `0.153.4` | HTTPS Git (`https://github.com/avayahmao/avaya-case-review-pack`) | Blocked before MCP launch |
| Codex desktop | Release Windows desktop build (version pending capture) | Pending | Pending final release gate |

## Marketplace SHA result

The requested transaction used candidate SHA
`26121cd9cae336acba663a291c1755c7bf6a8f96`. Codex CLI accepted `--ref`, but
the Git checkout failed with exit code 128 because that SHA is not available
from the configured GitHub source (`fatal: unable to read tree`). GitHub's
advertised `HEAD` and `main` were
`b68a8fb46135fad92de3de8d9ca170254f540bf6` during this run.

Therefore `marketplace add --ref <commit-sha>` is **not verified** for the
required candidate. The remove/re-add restoration check was not meaningful and
was not treated as a pass. The isolated-profile transaction also establishes
that Codex CLI requires the configured `CODEX_HOME` directory to exist before
plugin commands run.

## Relative MCP result

The local fixture marketplace and `relative-path-probe` plugin installed in an
isolated profile. The CLI launch then stopped at API authentication, before
the model could call the tool. No normal profile credentials were read or
copied. Consequently, neither launch-path predicate was observed:

| Host | `script_under_installed_plugin_root` | `cwd_outside_installed_plugin_root` |
| --- | --- | --- |
| CLI `0.153.4` | not verified | not verified |
| Windows desktop | pending | pending |

`RELATIVE_MCP_ARGS=PENDING`.

## Decision

Do not proceed to Task 5 on the basis of this characterization. Re-run the
Git transaction against a source that contains the recorded candidate SHA and
run the installed fixture in a disposable, authenticated Windows account. The
desktop check remains a final release gate because the active desktop session
cannot safely reload a test plugin.
