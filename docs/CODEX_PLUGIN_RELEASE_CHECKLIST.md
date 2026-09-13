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
- [ ] Verify the existing Apps Script deployment against the final stamped
  source by following `docs/GMAIL_CLOUD_BRIDGE.md`; do not redeploy it merely
  because a release is being prepared.
- [ ] If the existing deployment is proven mismatched, record the mismatch and
  obtain separate maintainer authorization before updating the existing Web
  App. Restart every cloud verification gate after any authorized update.

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

## Local automated gates

- [ ] Run the complete Python suite on each supported release host (Python 3.10 through 3.13):
  `python -m unittest discover -s tests -p "test_*.py"`.
- [ ] Run the complete cloud and rollback Node suites:
  `node --test tests/js/gmail_cloud_bridge.test.mjs tests/js/rollback_bridge_v3.test.mjs`.
- [ ] Compile every shipped Python tree:
  `python -m compileall avaya_case_review_runtime tools plugins`.
- [ ] Parse both installers with Windows PowerShell 5.1:
  `powershell.exe -NoProfile -Command "$e=$null; [System.Management.Automation.PSParser]::Tokenize((Get-Content -LiteralPath './install-codex.ps1' -Raw),[ref]$e)|Out-Null; if($e){throw $e}; [System.Management.Automation.PSParser]::Tokenize((Get-Content -LiteralPath './setup_env.ps1' -Raw),[ref]$e)|Out-Null; if($e){throw $e}"`.
- [ ] Verify `install-codex.ps1`, `setup_env.ps1`, `install.bat`, and every
  shipped `*.ps1`, `*.bat`, and `*.cmd` begins with a UTF-8 BOM and contains
  CRLF only; record the command and pass result without file contents.
- [ ] Run `git diff --check` and record a clean result.
- [ ] Build the ZIP strictly from `release-manifest.txt`, then compare the
  normalized sorted ZIP entry list with the non-comment manifest entries and
  fail on any missing, extra, duplicate, traversal, or backslash entry. Do not
  add the ZIP to Git.

## Supervised installation

- [ ] Start from a fresh Windows profile and a unique temporary checkout.
- [ ] From the unique checkout, install the exact candidate commit with
  `./install-codex.ps1 -MarketplaceSource https://github.com/avayahmao/avaya-case-review-pack -MarketplaceRef <candidate-SHA> -AllowUnreleasedRef`;
  record the resolved installed SHA and require an exact match.
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
- [ ] After the candidate is tagged and before publication, start a separate
  clean Codex task and use only the canonical request
  `install this plugin: https://github.com/avayahmao/avaya-case-review-pack`.
  Confirm it resolves the release tag to the candidate SHA and passes every
  installer gate without local-path assistance.
- [ ] From that URL-only installation, perform one evidence-complete case review:
  exhaust the Case notes, the single primary-ID Gmail thread-page
  chain, and every message cursor; require the Context Coverage Ledger
  equalities, deterministic full presentation, and durable follow-up record.
  Record only pass/fail and sanitized counts.

## Evidence hygiene

Do not record identities, URLs, case IDs, tokens, cursors, message bodies, or
message-derived hashes in this checklist, its supporting logs, commits, pull
requests, or release notes. Record only versions, commit SHA, Cloud Bridge
source digest, pass/fail statuses, and the fixed tool-name set above.

If any check fails, do not publish or activate the release. Follow the
existing cloud deployment and rollback runbooks instead of editing Codex cache
state.
