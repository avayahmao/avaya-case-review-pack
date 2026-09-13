# Codex Plugin Release Checklist

Use this checklist only for the supervised Windows release gate. Automated
coverage uses temporary `CODEX_HOME` directories, synthetic attestation data,
and command adapters; it never substitutes for the real marketplace, desktop,
or SSO evidence recorded here.

## Candidate identity

- [ ] Record the exact Codex CLI version: `________________`.
- [ ] Record the exact Windows desktop version: `________________`.
- [ ] Record the Python version used by the installer: `________________`.
- [ ] Record the candidate commit SHA: `________________`.
- [ ] Record the release tag and confirm it resolves to that candidate SHA:
  `________________`.
- [ ] Record the Cloud Bridge source SHA-256 from the release attestation:
  `________________`.
- [ ] Confirm the attestation plugin version, bridge version, and contract
  revision match the candidate: `________________`.

## Module-package MCP launch contract

The release launch contract is the installed `avaya_case_review_runtime`
package. Do not use, test, or record relative script paths as an MCP launch
option: the module-package commands below are the only supported launch gates.
- [ ] From a non-plugin working directory, confirm the installed runtime
  package resolves without `PYTHONPATH`, `cwd`, or a private Codex cache path.
- [ ] In the installed marketplace, Gmail is exactly
  `python -m avaya_case_review_runtime.gmail_mcp_server`.
- [ ] In the installed marketplace, CaseToMD is exactly
  `python -m avaya_case_review_runtime.casetomd_mcp_bridge`.
- [ ] Confirm neither MCP definition has a placeholder, private Codex cache
  path, `PYTHONPATH`, `cwd`, or non-stdio transport.

## Supervised installation

- [ ] Start from a fresh Windows profile and a unique temporary checkout.
- [ ] Install the exact candidate marketplace source and ref with
  `install-codex.ps1`.
- [ ] If prompted, complete the visible Managed Edge SSO/MFA interaction;
  record only `passed`, `cancelled`, or `blocked`: `________________`.
- [ ] Confirm the marketplace and enabled
  `avaya-case-review@avaya-case-review-pack` plugin are present.
- [ ] Start a new Codex desktop task and discover exactly these six tools:
  `gmail_search`, `gmail_read`, `gmail_send`, `gmail_list_threads`,
  `gmail_read_thread_page`, and `get_case_markdown`.
- [ ] Re-run the installer at the same source and ref; record idempotent
  reinstall result: `________________`.
- [ ] Exercise the documented same-source rollback; record rollback result:
  `________________`.

## Evidence hygiene

Do not record identities, URLs, case IDs, tokens, cursors, message bodies, or
message-derived hashes in this checklist, its supporting logs, commits, pull
requests, or release notes. Record only versions, commit SHA, Cloud Bridge
source digest, pass/fail statuses, and the fixed tool-name set above.

If any check fails, do not publish or activate the release. Follow the
existing cloud deployment and rollback runbooks instead of editing Codex cache
state.
