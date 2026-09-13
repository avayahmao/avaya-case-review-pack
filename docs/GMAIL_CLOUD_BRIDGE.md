# Gmail Cloud Bridge Maintainer Release Runbook

This maintainer-only runbook verifies the already-deployed exhaustive Gmail MCP
cloud endpoint against the **v1.10.1 release candidate**. It does not redeploy
the existing Gmail MCP Apps Script Web App unless verification proves a
mismatch and a maintainer separately authorizes that update. It never deploys
the optional governance example in
`examples/optional-appsscript/Code.gs`. `v1.10.0` remains the latest published
release. URL-only stable installation becomes active only after this gate
creates the v1.10.1 attestation, tag, and release; then `install-codex.ps1` or
`install.bat` performs local release-attestation and live compatibility checks
automatically and must not be used to deploy this cloud source.

## Maintainer release gate

From the candidate checkout, stamp the canonical source before opening Apps
Script. The second command must print the same digest and `git diff --exit-code`
must show that the second stamp made no change:

```powershell
$BridgeSource = Resolve-Path "tools/gmail/cloud/GmailMcpBridge.gs"
$FirstDigest = python tools/gmail/cloud/bridge_identity.py stamp --source $BridgeSource
if ($LASTEXITCODE -ne 0) { throw "FAIL: source stamp" }
$StampedBlob = git hash-object -- $BridgeSource
$SecondDigest = python tools/gmail/cloud/bridge_identity.py stamp --source $BridgeSource
if ($LASTEXITCODE -ne 0 -or $FirstDigest -cne $SecondDigest) { throw "FAIL: source stamp is not idempotent" }
if ((git hash-object -- $BridgeSource) -cne $StampedBlob) { throw "FAIL: second stamp changed source" }
git diff --exit-code -- tools/gmail/cloud/GmailMcpBridge.gs
if ($LASTEXITCODE -ne 0) { throw "FAIL: candidate source was not already stamped" }
```

Complete these steps in order:

1. Open the existing Gmail MCP Apps Script project, not the optional governance example.
2. Confirm its Advanced Gmail Service is named **Gmail** and uses API version **v1** (shown as `Gmail v1`).
3. Keep the existing deployment URL; do not create or distribute a replacement endpoint URL.
4. Run the `capabilities` comparison below against that existing deployment.
   The live protocol version, contract revision, source digest, and capability
   flags must match the final stamped candidate source.
5. If and only if step 4 proves a mismatch, stop. Obtain separate maintainer authorization
   before replacing the Web App source with
   `tools/gmail/cloud/GmailMcpBridge.gs`. After authorization, save and run a
   syntax check, then use **Deploy > Manage deployments**, edit the existing
   Web App, select **New version**, and retain the existing deployment URL.
   Restart this runbook from step 1 after any update.
6. Complete controlled authorization only if Google requests the required
   Gmail scopes. Confirm the expected account and scopes before allowing access.
7. Verify a zero-result `list_threads` request returns `complete=true`. Then run a real case query and confirm that it retains one stable snapshot across the complete page-token chain. Track every `next_page_token`; a repeated or regressing token, a missing `complete` field, a quota/timeout, or a 15-minute verification deadline is a failure.
8. Verify one multi-message thread through cursor exhaustion and complete the documented hash/count checks for its manifest, messages, and body chunks. Track every `next_cursor` with the same repeated/regressing-token, missing-`complete`, quota/timeout, and deadline guards.
9. Run the Managed Edge `verify-bridge` command below against a temporary
    attestation. It must compare the live protocol version, contract revision,
    and source digest and return exit code `0`.
10. Generate and validate the production attestation with the exact commands
    below.
11. **Only then, after every preceding gate passes,** may the local MCP modules or
    Agent package be activated, pushed, tagged, zipped, or published.

If the Advanced Gmail Service cannot be enabled, authorization cannot be
completed, or either verification fails, stop. Do not publish the local package
or its attestation.

## Sanitized verification examples

Run the following PowerShell checks against the existing Web App. If a
separately authorized update was required, restart these checks from the
beginning after that update. Set the environment variables in the current local session; do not
commit them, print them, or place their values in a transcript. The values are
deliberately placeholders so that no URL, case ID, thread ID, page token,
cursor, or message body is stored in this repository.

```powershell
$ErrorActionPreference = "Stop"
$Utf8 = [System.Text.UTF8Encoding]::new($false)
$verificationDeadline = (Get-Date).ToUniversalTime().AddMinutes(15)
$requiredInputs = @(
    "GMAIL_VERIFY_WEB_APP_URL",
    "GMAIL_VERIFY_CASE_ID",
    "GMAIL_VERIFY_ZERO_RESULT_ID"
)
foreach ($name in $requiredInputs) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Set $name in this PowerShell session; values are not printed."
    }
}
$WebAppUrl = [Environment]::GetEnvironmentVariable("GMAIL_VERIFY_WEB_APP_URL")
$CaseId = [Environment]::GetEnvironmentVariable("GMAIL_VERIFY_CASE_ID")
$ZeroResultId = [Environment]::GetEnvironmentVariable("GMAIL_VERIFY_ZERO_RESULT_ID")
$CandidateSource = Get-Content -LiteralPath "tools/gmail/cloud/GmailMcpBridge.gs" -Raw
$ExpectedBridgeVersion = [int]([regex]::Match($CandidateSource, '(?m)^var GMAIL_BRIDGE_VERSION = (\d+);$').Groups[1].Value)
$ExpectedContractRevision = [int]([regex]::Match($CandidateSource, '(?m)^var GMAIL_BRIDGE_CONTRACT_REVISION = (\d+);$').Groups[1].Value)
$ExpectedSourceDigest = [regex]::Match($CandidateSource, '(?m)^var GMAIL_BRIDGE_SOURCE_SHA256 = "([0-9a-f]{64})";$').Groups[1].Value

function Assert-Equal([string]$Name, $Actual, $Expected) {
    if ($Actual -ne $Expected) { throw "FAIL: $Name; do not publish local release package" }
    Write-Host "PASS: $Name"
}

function Assert-True([string]$Name, [bool]$Condition) {
    if (-not $Condition) { throw "FAIL: $Name; do not publish local release package" }
    Write-Host "PASS: $Name"
}

function Assert-VerificationDeadline([string]$Name) {
    if ((Get-Date).ToUniversalTime() -ge $verificationDeadline) {
        throw "FAIL: verification deadline exceeded during $Name; do not publish local release package"
    }
}

function Get-Sha256([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($Utf8.GetBytes($Value))).Replace("-", "").ToLowerInvariant())
    } finally {
        $sha.Dispose()
    }
}

function Get-Utf8ByteCount([string]$Value) {
    return $Utf8.GetByteCount($Value)
}

function Invoke-Bridge([hashtable]$Parameters) {
    Assert-VerificationDeadline "cloud request"
    $pairs = @(
        foreach ($entry in $Parameters.GetEnumerator()) {
            "{0}={1}" -f [Uri]::EscapeDataString([string]$entry.Key), [Uri]::EscapeDataString([string]$entry.Value)
        }
    )
    $uri = $WebAppUrl.TrimEnd([char[]]"?&") + "?" + ($pairs -join "&")
    try {
        # Never pipe this response to Format-* or ConvertTo-Json: segments contain body text.
        # Use Invoke-WebRequest -UseBasicParsing (required on Windows PowerShell 5.1) so the
        # raw JSON text survives alongside the parsed object: the cursor loop consumes parsed
        # fields, and the per-page byte-budget assertions below need the exact transport bytes
        # that Invoke-RestMethod would parse away.
        $response = Invoke-WebRequest -UseBasicParsing -Method Get -Uri $uri -TimeoutSec 60 -ErrorAction Stop
        Assert-VerificationDeadline "cloud response"
        $raw = [string]$response.Content
        $parsed = $raw | ConvertFrom-Json
        if ($null -eq $parsed -or $parsed.success -ne $true) {
            throw "cloud response failed"
        }
        $parsed | Add-Member -NotePropertyName raw_text -NotePropertyValue $raw
        return $parsed
    } catch {
        throw "FAIL: cloud request timeout/quota/error; do not publish local release package"
    }
}

# Compare the existing deployment before any deployment action is considered.
$liveCapabilities = Invoke-Bridge @{ action = "capabilities" }
Assert-Equal "live bridge protocol version" ([int]$liveCapabilities.bridge_version) $ExpectedBridgeVersion
Assert-Equal "live bridge contract revision" ([int]$liveCapabilities.contract_revision) $ExpectedContractRevision
Assert-Equal "live bridge source digest" ([string]$liveCapabilities.bridge_source_sha256) $ExpectedSourceDigest
foreach ($capability in @("stable_snapshots", "thread_pagination", "cursor_pagination", "manifest_sha256", "body_bytes", "body_sha256")) {
    Assert-True "live capability $capability" ($liveCapabilities.capabilities.$capability -eq $true)
}

# A known no-result placeholder must be supplied by the verifier; do not use a real case ID here.
$zero = Invoke-Bridge @{ action = "list_threads"; q = $ZeroResultId; max_results = "1" }
Assert-True "zero-result complete=true" ($zero.complete -eq $true)
Assert-Equal "zero-result next page token empty" ([string]$zero.next_page_token) ""
Assert-Equal "zero-result thread count is zero" (@($zero.thread_ids).Count) 0

# The first real-case request bootstraps the shared snapshot; every later page reuses it.
$page = Invoke-Bridge @{ action = "list_threads"; q = $CaseId; max_results = "1" }
$snapshot = [string]$page.snapshot_before
Assert-True "real-case snapshot is non-empty" (-not [string]::IsNullOrWhiteSpace($snapshot))
$threadIds = @()
$seenThreads = @{}
$seenPageTokens = @{}
$pageToken = ""
do {
    Assert-VerificationDeadline "list page"
    Assert-Equal "page snapshot reused" ([string]$page.snapshot_before) $snapshot
    foreach ($threadIdValue in @($page.thread_ids)) {
        $threadId = [string]$threadIdValue
        if (-not $seenThreads.ContainsKey($threadId)) {
            $seenThreads[$threadId] = $true
            $threadIds += $threadId
        }
    }
    Assert-True "list response includes complete" ($null -ne $page.complete)
    Assert-True "list response includes next page token" ($null -ne $page.next_page_token)
    $pageToken = [string]$page.next_page_token
    Assert-Equal "page complete flag matches next token" ([bool]$page.complete) ([string]::IsNullOrEmpty($pageToken))
    if ($pageToken) {
        if ($seenPageTokens.ContainsKey($pageToken)) {
            throw "FAIL: repeated or regressing page token; do not publish local release package"
        }
        $seenPageTokens[$pageToken] = $true
        $page = Invoke-Bridge @{
            action = "list_threads"
            q = $CaseId
            snapshot_before = $snapshot
            page_token = $pageToken
            max_results = "1"
        }
    }
} while ($pageToken)
Assert-True "real-case returned at least one thread" ($threadIds.Count -gt 0)

$threadsRead = 0
$messagesExpected = 0
$messagesRead = 0
$multiMessageFound = $false
foreach ($threadId in $threadIds) {
    $cursor = ""
    $cursorHistory = @{}
    $seenCursors = @{}
    $firstThreadPage = $true
    $expectedMessageCount = 0
    $messagesCompleted = 0
    $manifest = ""
    $messageIds = @()
    $seenMessages = @{}
    $bodyTextById = @{}
    $bodyBytesById = @{}
    $bodyHashById = @{}
    do {
        Assert-VerificationDeadline "thread cursor"
        if ($cursor -and $cursorHistory.ContainsKey($cursor)) { throw "FAIL: cursor did not advance" }
        if ($cursor) { $cursorHistory[$cursor] = $true }
        $readParameters = @{
            action = "read_thread_page"
            thread_id = $threadId
            snapshot_before = $snapshot
        }
        if ($cursor) { $readParameters.cursor = $cursor }
        $threadPage = Invoke-Bridge $readParameters
        Assert-Equal "thread snapshot reused" ([string]$threadPage.snapshot_before) $snapshot
        Assert-True "thread response includes complete" ($null -ne $threadPage.complete)
        Assert-True "thread response includes next cursor" ($null -ne $threadPage.next_cursor)
        # Page-size safety, measured on the exact transport bytes. inner is the raw
        # Apps Script JSON; wire models the broker frame, where the outer JSON
        # encoding re-escapes every quote and backslash (+1 byte each), plus a
        # 1 KiB conservative envelope for the frame wrapper fields:
        #   wire = utf8Len(raw) + count('"') + count('\') + 1 KiB
        # Get-Utf8ByteCount is required: string .Length counts UTF-16 code units,
        # which is not the UTF-8 byte length for non-ASCII content.
        $rawText = [string]$threadPage.raw_text
        $innerBytes = Get-Utf8ByteCount $rawText
        $escapedSurcharge = ([regex]::Matches($rawText, '["\\]')).Count
        $wireBytes = $innerBytes + $escapedSurcharge + 1024
        Assert-True "page inner bytes within cloud budget" ($innerBytes -le 6291456)
        Assert-True "page wire bytes within broker frame budget" ($wireBytes -le 8388608)
        $messageCount = [int]$threadPage.message_count
        if ($firstThreadPage) {
            $expectedMessageCount = $messageCount
            $manifest = [string]$threadPage.manifest_sha256
        } else {
            Assert-Equal "manifest hash stable across cursors" ([string]$threadPage.manifest_sha256) $manifest
            Assert-Equal "thread message count stable across cursors" $messageCount $expectedMessageCount
        }
        foreach ($segment in @($threadPage.segments)) {
            $messageId = [string]$segment.message_id
            if (-not $seenMessages.ContainsKey($messageId)) {
                $seenMessages[$messageId] = $true
                $messageIds += $messageId
                $bodyTextById[$messageId] = ""
            }
            $bodyTextById[$messageId] = [string]$bodyTextById[$messageId] + [string]$segment.body_chunk
            $bodyBytesById[$messageId] = [int]$segment.body_bytes
            $bodyHashById[$messageId] = [string]$segment.body_sha256
        }
        $messagesCompleted = [int]$threadPage.messages_completed
        $nextCursor = [string]$threadPage.next_cursor
        Assert-Equal "cursor complete flag matches next cursor" ([bool]$threadPage.complete) ([string]::IsNullOrEmpty($nextCursor))
        if ($nextCursor) {
            if ($seenCursors.ContainsKey($nextCursor)) {
                throw "FAIL: repeated or regressing cursor; do not publish local release package"
            }
            $seenCursors[$nextCursor] = $true
        }
        $cursor = $nextCursor
        $firstThreadPage = $false
    } while ($cursor)

    Assert-Equal "thread message count" $messageIds.Count $expectedMessageCount
    Assert-Equal "thread messages completed" $messagesCompleted $expectedMessageCount
    Assert-Equal "thread manifest hash" (Get-Sha256 ($messageIds -join "`n")) $manifest
    if ($expectedMessageCount -gt 1) { $multiMessageFound = $true }
    foreach ($messageId in $messageIds) {
        Assert-Equal "body byte count" (Get-Utf8ByteCount $bodyTextById[$messageId]) $bodyBytesById[$messageId]
        Assert-Equal "body hash" (Get-Sha256 $bodyTextById[$messageId]) $bodyHashById[$messageId]
    }
    $messagesExpected += $expectedMessageCount
    $messagesRead += $messageIds.Count
    $threadsRead += 1
}
Assert-Equal "thread count enumerated/read" $threadsRead $threadIds.Count
Assert-Equal "message count expected/read" $messagesRead $messagesExpected
Assert-True "at least one multi-message thread exercised" $multiMessageFound
Write-Host "PASS: response bodies, IDs, tokens, cursors, and secrets were not printed or logged"
```

After every zero-result, page-token, cursor, count, and hash assertion above
passes, create a temporary attestation and use the Managed Edge broker to
compare the live `capabilities` response. The broker output is sanitized; do
not redirect it to a committed file.

```powershell
$PluginVersion = (Get-Content -LiteralPath ".codex-plugin/plugin.json" -Raw | ConvertFrom-Json).version
$VerifiedAtUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$CandidateAttestation = Join-Path ([IO.Path]::GetTempPath()) ("bridge-attestation-" + [guid]::NewGuid().ToString("N") + ".json")
python tools/gmail/cloud/bridge_identity.py attest `
  --source tools/gmail/cloud/GmailMcpBridge.gs `
  --output $CandidateAttestation `
  --plugin-version $PluginVersion `
  --verified-at-utc $VerifiedAtUtc `
  --all-checks-passed
if ($LASTEXITCODE -ne 0) { throw "FAIL: temporary attestation generation" }
python tools/gmail/gmail_brokerctl.py verify-bridge `
  --source tools/gmail/cloud/GmailMcpBridge.gs `
  --attestation $CandidateAttestation `
  --plugin-version $PluginVersion | Out-Null
if ($LASTEXITCODE -ne 0) { throw "FAIL: live protocol/contract/source comparison" }
python tools/gmail/cloud/bridge_identity.py validate `
  --source tools/gmail/cloud/GmailMcpBridge.gs `
  --attestation $CandidateAttestation `
  --plugin-version $PluginVersion
if ($LASTEXITCODE -ne 0) { throw "FAIL: temporary attestation validation" }
Move-Item -LiteralPath $CandidateAttestation -Destination tools/gmail/cloud/bridge_release_attestation.json -Force
python tools/gmail/cloud/bridge_identity.py validate `
  --source tools/gmail/cloud/GmailMcpBridge.gs `
  --attestation tools/gmail/cloud/bridge_release_attestation.json `
  --plugin-version $PluginVersion
if ($LASTEXITCODE -ne 0) { throw "FAIL: production attestation validation" }
```

Do not run either local installer, activate either Agent skill, push, tag,
build the release ZIP, or publish the release until the source-stamp
idempotence check, exhaustive verification loop, live Managed Edge comparison,
and final production-attestation validation have all passed in that order.

The check passes only when every `Assert-...` line reports `PASS`. Any repeated
or regressing page token/cursor, missing `complete`, deadline expiry, quota,
timeout, count/hash mismatch, or remaining process/state is a failure; do not
publish or activate the local release package.
The script keeps response objects in memory solely to compare counts, manifest
hashes, UTF-8 byte counts, and body hashes;
it never prints message bodies or writes tokens, IDs, cookies, or credentials
to logs.

## Collection contract

- `gmail_list_threads(query, snapshot_before, page_token, max_results)` creates
  or reuses the collection snapshot and exposes real Gmail page tokens.
- `gmail_read_thread_page(thread_id, snapshot_before, cursor)` reads every
  snapshot-eligible message and body chunk in the matched thread. Its cursor is
  exhausted before the thread is counted complete.
- The first successful list response establishes a non-empty
  `snapshot_before`; every later list and read call uses that exact value.
- Gmail search timestamps have second-level precision. The bridge queries
  `before:<next whole second>` and reads through the end of that same second,
  so a thread returned by `gmail_list_threads` cannot become an empty
  snapshot page because of millisecond rounding.
- The Agent processes every Case note before Gmail collection but sends exactly
  one list query: the primary raw Case ID. Supported related IDs explicitly
  present in Case notes remain source-ledger context only; neither note-derived
  nor Gmail-discovered related IDs expand the Gmail query plan.
- Attachments are excluded from content retrieval. Attachment metadata may be
  reported, but attachment bodies are outside this completeness contract. Gmail
  may externalize a large `text/plain` or `text/html` MIME body behind
  `body.attachmentId`; when that part has no filename or attachment disposition,
  the bridge retrieves it through `Gmail.Users.Messages.Attachments.get` and
  includes it as message text rather than treating it as an attachment. The
  Advanced Gmail Service may also materialize inline `body.data` (and fetched
  attachment `data`) as an Apps Script byte array rather than a base64url
  string; the bridge decodes that byte array as UTF-8 before normalization.
- Any source, page, cursor, manifest, hash, count, or snapshot failure returns
  `Context collection incomplete` and blocks analysis and report generation.
- `gmail_search`, `gmail_read`, and `gmail_send` remain backward-compatible
  APIs. Search and read cannot satisfy the exhaustive completeness gate.
- Legacy search remains bounded to 10 results by default and accepts an
  optional bounded `max_results`; exhaustive callers must use the paginated
  context tools instead.
- Thread pages are intentionally stateless. The normal path re-fetches the
  full thread on every page, but the ordered message list and manifest hash
  are derived from message IDs and internal dates only; payload bodies are
  decoded and normalized exclusively for the segments the current page emits.
  If Gmail rejects an oversized full-thread response, the bridge re-fetches a
  minimal manifest and full-fetches only the messages needed by the current
  page. Every page still derives the same snapshot-filtered message count and
  manifest hash. CacheService is not used because stale manifests, cache-size
  limits, and cross-run invalidation would weaken the completeness contract.
- Page capacity is bounded three ways: at most 32 body segments per page, and
  the serialized page must stay within both transport budgets — the Apps
  Script response itself (`inner`, 6 MiB, enforced by `MAX_RESPONSE_BYTES`)
  and the broker frame, because the broker's outer JSON encoding re-escapes
  every quote and backslash (`wire` = inner + one byte per `"` or `\`, 8 MiB,
  matching the broker's `MAX_FRAME_BYTES`). A first segment that alone
  exceeds either real limit fails with the sanitized `RESPONSE_TOO_LARGE` —
  the same failure mode earlier bridge versions produced after full-page
  serialization — so the set of collectible threads is unchanged.
- Expected fetch, validation, normalization, manifest, cursor, and response
  failures return stable sanitized codes. `APP_ERROR` is reserved for
  unexpected failures so a collection blocker remains actionable without
  exposing message content.

This cloud source is operational Gmail MCP code. It is intentionally separate
from the optional governance example, and `setup_env.ps1` does not copy it to
the local Gmail tools directory.

## Rollback

Redeploy the prior Apps Script version to the same Web App URL. If local deployment has already occurred, use this order before replacing any local files:

1. Stop Antigravity and deactivate the current exhaustive Agent SKILL.
2. Stop the independent Gmail broker, which may still own a Managed Edge
   context even after Antigravity exits:

   ```powershell
   $McpCtl = Join-Path $env:USERPROFILE '.gemini\tools\gmail\gmail_brokerctl.py'
   python $McpCtl stop
   $stopExit = $LASTEXITCODE
   if ($stopExit -notin @(0, 20)) { throw 'FAIL: broker stop command did not complete safely' }
   ```

   Do not invoke the broker's status subcommand here: when the broker is
   absent, that subcommand can start a new broker. A stop exit code of `0` is
   success. An already-absent broker may return the documented unavailable code `20` and
   is also safe to verify with the native check below. Any other exit code is
   a failure.
3. Prove that the broker and its Managed Edge child have exited without any
   broker CLI command that can start them. Set the expected deployed paths and
   poll for at most 15 seconds:

   ```powershell
   $BrokerRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'AvayaCaseReview\gmail-broker'
   $StateFile = Join-Path $BrokerRoot 'state.json'
   $LockFile = Join-Path $BrokerRoot 'broker.lock'
   $BrokerScript = Join-Path $env:USERPROFILE '.gemini\tools\gmail\gmail_edge_broker.py'
   $EdgeProfile = Join-Path $env:USERPROFILE '.gemini\tools\gmail\edge_broker_profile'
   $deadline = (Get-Date).ToUniversalTime().AddSeconds(15)

   function Test-BrokerLockFree([string]$Path) {
       if (-not (Test-Path -LiteralPath $Path)) { return $true }
       $stream = $null
       try {
           $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
           $stream.Lock(0, 1)
           $stream.Unlock(0, 1)
           return $true
       } catch {
           return $false
       } finally {
           if ($null -ne $stream) { $stream.Dispose() }
       }
   }

   do {
       $statePresent = Test-Path -LiteralPath $StateFile
       $statePid = $null
       if ($statePresent) {
           try {
               $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
               $statePid = [int]$state.pid
           } catch {
               throw 'FAIL: broker state is unreadable; do not replace local files'
           }
       }
       $dedicatedProcesses = @(
           Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
               $commandLine = [string]$_.CommandLine
               $commandLine -and (
                   $commandLine.IndexOf($BrokerScript, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                   $commandLine.IndexOf($EdgeProfile, [StringComparison]::OrdinalIgnoreCase) -ge 0
               )
           }
       )
       $stateProcess = if ($null -ne $statePid) {
           @(Get-CimInstance Win32_Process -Filter "ProcessId=$statePid" -ErrorAction SilentlyContinue)
       } else { @() }
       $lockFree = Test-BrokerLockFree $LockFile
       if (-not $statePresent -and $stateProcess.Count -eq 0 -and $dedicatedProcesses.Count -eq 0 -and $lockFree) { break }
       Start-Sleep -Milliseconds 250
   } while ((Get-Date).ToUniversalTime() -lt $deadline)

   if ($statePresent -or $stateProcess.Count -gt 0 -or $dedicatedProcesses.Count -gt 0 -or -not $lockFree) {
       throw 'FAIL: broker state, PID, lock, or Managed Edge process remains active'
   }
   Write-Host 'PASS: broker state/PID/lock and dedicated Managed Edge processes are gone'
   ```

   The native check passes only when `state.json` is gone, the advertised PID
   has no process, no process command line contains the dedicated broker script
   or `edge_broker_profile`, and the secured `broker.lock` byte can be acquired
   and released. A remaining state file, PID, lock, or dedicated process is a
   failure; do not replace files until the check passes.
4. Rerun the prior package's installer. This is the only supported local
   rollback; do not manually replace deployed files while any broker or Edge
   process remains active.

Restart Antigravity only after the prior local package is restored.
Keep the exhaustive Agent gate inactive until the prior cloud version and the
zero-result, real-case pagination, and multi-message cursor checks pass again.
The existing Managed Edge broker and explicit `legacy_playwright` rollback
behavior remain unchanged.
