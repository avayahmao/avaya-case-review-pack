# Codex Plugin Release Checklist

Use this checklist only for the supervised Windows release gate. Automated
coverage uses temporary `CODEX_HOME` directories, synthetic attestation data,
and command adapters; it never substitutes for the real marketplace, desktop,
or SSO evidence recorded here.

## Completed maintainer cloud gates

- [x] Confirm Version 17 is active.
- [x] Confirm live source identity and capabilities match the candidate.
- [x] Complete all 6 repeated probes successfully.
- [x] Complete exhaustive zero-result, page, cursor, count, manifest, UTF-8,
  and body-integrity verification.
- [x] Complete candidate `gmail_brokerctl.py verify-bridge` successfully.
- [x] Validate the production release attestation against the candidate source
  and plugin version.

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

## Publication sequence

Complete these gates in order. Leave every box unchecked until that exact
external action has fresh evidence, and never force a branch or tag update.

- [ ] **Push the candidate branch and verify its exact remote SHA.**

  ```powershell
  $CandidateBranch = (git branch --show-current).Trim()
  $CandidateSha = (git rev-parse HEAD).Trim()
  git push origin "HEAD:refs/heads/$CandidateBranch"
  $RemoteCandidateSha = ((git ls-remote origin "refs/heads/$CandidateBranch") -split '\s+')[0]
  if ($RemoteCandidateSha -cne $CandidateSha) { throw "Remote candidate SHA mismatch" }
  ```

- [ ] **Run explicit-SHA clean-profile acceptance.** Use the pushed
  `$CandidateSha` in a clean Windows profile and record only sanitized results.

- [ ] **Fast-forward and verify `origin/main`.**

  ```powershell
  git push origin HEAD:main
  $RemoteMainSha = ((git ls-remote origin refs/heads/main) -split '\s+')[0]
  if ($RemoteMainSha -cne $CandidateSha) { throw "Remote main SHA mismatch" }
  $DefaultBranchCheckout = Join-Path ([IO.Path]::GetTempPath()) ("avaya-main-" + [guid]::NewGuid().ToString("N"))
  git clone --depth 1 --branch main https://github.com/avayahmao/avaya-case-review-pack $DefaultBranchCheckout
  $DefaultReadme = Get-Content -LiteralPath (Join-Path $DefaultBranchCheckout "README.md") -Raw
  $StableBootstrap = "git clone --depth 1 --branch v1.11.0 https://github.com/avayahmao/avaya-case-review-pack <unique-temp-directory>"
  if (-not $DefaultReadme.Contains($StableBootstrap) -or -not $DefaultReadme.Contains("git describe --exact-match --tags HEAD")) { throw "Default-branch README is missing the stable v1.11.0 bootstrap" }
  ```

  Verify the default-branch README from a new shallow `main` checkout exposes
  the exact stable v1.11.0 clone command and exact-tag check before creating
  the tag.

- [ ] **Create and verify the annotated immutable tag at the accepted SHA.**

  ```powershell
  git tag -a v1.11.0 $CandidateSha -m "v1.11.0"
  git push origin refs/tags/v1.11.0
  $RemoteTagSha = ((git ls-remote origin "refs/tags/v1.11.0^{}") -split '\s+')[0]
  if ($RemoteTagSha -cne $CandidateSha) { throw "Remote tag SHA mismatch" }
  ```

- [ ] **Run URL-only acceptance** in a second clean Windows profile using only
  the canonical GitHub URL request.

- [ ] **Build and verify the release ZIP.** Do not build from the candidate
  worktree. Use this exact procedure to build outside Git from a fresh, clean,
  detached checkout of `v1.11.0`, and confirm the tag peels to the accepted
  candidate SHA:

  ```powershell
  $ReleaseCheckout = Join-Path ([IO.Path]::GetTempPath()) ("avaya-v1.11.0-" + [guid]::NewGuid().ToString("N"))
  $ArchivePath = Join-Path ([IO.Path]::GetTempPath()) "avaya-case-review-pack-v1.11.0.zip"
  git clone --no-checkout https://github.com/avayahmao/avaya-case-review-pack $ReleaseCheckout
  git -C $ReleaseCheckout checkout --detach v1.11.0
  $TaggedSha = (git -C $ReleaseCheckout rev-parse HEAD).Trim()
  if ($TaggedSha -cne $CandidateSha) { throw "Tagged checkout SHA mismatch" }
  if (@(git -C $ReleaseCheckout status --porcelain).Count -ne 0) { throw "Tagged checkout is not clean" }
  @'
  import sys
  import zipfile
  from pathlib import Path

  checkout = Path(sys.argv[1])
  archive_path = Path(sys.argv[2])
  manifest = [
      line.strip()
      for line in (checkout / "release-manifest.txt").read_text(encoding="utf-8").splitlines()
      if line.strip() and not line.lstrip().startswith("#")
  ]
  with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
      for name in manifest:
          archive.write(checkout / name, name)
  with zipfile.ZipFile(archive_path) as archive:
      actual = archive.namelist()
      if actual != manifest:
          raise SystemExit("ZIP entry list does not exactly equal release-manifest.txt")
      for name in manifest:
          if archive.read(name) != (checkout / name).read_bytes():
              raise SystemExit(f"ZIP member bytes differ from tagged checkout: {name}")
  '@ | python - $ReleaseCheckout $ArchivePath
  if ($LASTEXITCODE -ne 0) { throw "Release ZIP verification failed" }
  if (@(git -C $ReleaseCheckout status --porcelain).Count -ne 0) { throw "Tagged checkout changed during ZIP build" }
  ```

  Require the ZIP entry list to equal the tagged checkout's manifest exactly
  and every member to equal its corresponding tagged file byte-for-byte. Keep
  the ZIP outside Git.

- [ ] **Publish and verify the GitHub Release.** Only after every prior gate:

  ```powershell
  gh release create v1.11.0 $ArchivePath --title "Codex URL installation repair" --notes-file NOTES-v1.11.0.md --latest
  gh release view v1.11.0
  ```

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
- [ ] Validate `release-manifest.txt` without building the final ZIP: reject
  missing, extra, duplicate, rooted, traversal, or backslash entries. Build
  the release ZIP only in the ordered publication sequence, after the
  immutable tag and URL-only acceptance gates.

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
