# Gmail Cloud Bridge Deployment Runbook

This runbook deploys the exhaustive Gmail MCP cloud endpoint. It updates the
existing Gmail MCP Apps Script Web App; it does not deploy the optional
governance example in `examples/optional-appsscript/Code.gs`.

## Deployment gate

Complete these steps in order:

1. Open the existing Gmail MCP Apps Script project, not the optional governance example.
2. Enable the Advanced Gmail Service. Select the service named **Gmail**, API version **v1** (shown as `Gmail v1`).
3. Replace the Web App source with `tools/gmail/cloud/GmailMcpBridge.gs`.
4. Save the project and run a syntax check in the Apps Script editor.
5. Select **Deploy > Manage deployments**, edit the existing Web App, select **New version**, and deploy it.
6. Keep the existing deployment URL; do not create or distribute a replacement endpoint URL.
7. Complete controlled authorization if Google requests the newly required Gmail scopes. Confirm the expected account and scopes before allowing access.
8. Verify a zero-result `list_threads` request returns `complete=true`. Then run a real case query and confirm that it retains one stable snapshot across the complete page-token chain.
9. Verify one multi-message thread through cursor exhaustion and complete the documented hash/count checks for its manifest, messages, and body chunks.
10. **Only then** deploy the updated local Gmail MCP modules and Agent SKILL.

If the Advanced Gmail Service cannot be enabled, authorization cannot be
completed, or either verification fails, stop. Do not deploy the local SKILL
that activates the exhaustive gate.

## Sanitized verification examples

Run the following PowerShell checks only after the existing Web App has been
updated. Set the environment variables in the current local session; do not
commit them, print them, or place their values in a transcript. The values are
deliberately placeholders so that no URL, case ID, thread ID, page token,
cursor, or message body is stored in this repository.

```powershell
$ErrorActionPreference = "Stop"
$Utf8 = [System.Text.UTF8Encoding]::new($false)
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

function Assert-Equal([string]$Name, $Actual, $Expected) {
    if ($Actual -ne $Expected) { throw "FAIL: $Name" }
    Write-Host "PASS: $Name"
}

function Assert-True([string]$Name, [bool]$Condition) {
    if (-not $Condition) { throw "FAIL: $Name" }
    Write-Host "PASS: $Name"
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
    $pairs = @(
        foreach ($entry in $Parameters.GetEnumerator()) {
            "{0}={1}" -f [Uri]::EscapeDataString([string]$entry.Key), [Uri]::EscapeDataString([string]$entry.Value)
        }
    )
    $uri = $WebAppUrl.TrimEnd([char[]]"?&") + "?" + ($pairs -join "&")
    try {
        # Never pipe this response to Format-* or ConvertTo-Json: segments contain body text.
        return Invoke-RestMethod -Method Get -Uri $uri -ErrorAction Stop
    } catch {
        throw "FAIL: cloud request unavailable during sanitized verification"
    }
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
$pageToken = ""
do {
    Assert-Equal "page snapshot reused" ([string]$page.snapshot_before) $snapshot
    foreach ($threadIdValue in @($page.thread_ids)) {
        $threadId = [string]$threadIdValue
        if (-not $seenThreads.ContainsKey($threadId)) {
            $seenThreads[$threadId] = $true
            $threadIds += $threadId
        }
    }
    $pageToken = [string]$page.next_page_token
    Assert-Equal "page complete flag matches next token" ([bool]$page.complete) ([string]::IsNullOrEmpty($pageToken))
    if ($pageToken) {
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

The local CLI has the same argument shape for a post-deployment smoke check;
keep all values in environment variables and discard its output. This is a
placeholder only and does not replace the direct cloud checks above:

```powershell
$McpCli = Join-Path $env:USERPROFILE ".gemini\tools\gmail\gmail_mcp_server.py"
python $McpCli list-threads $env:GMAIL_VERIFY_CASE_ID --snapshot-before="" --page-token="" --max-results=1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "FAIL: local CLI list smoke check" }
python $McpCli read-thread-page $env:GMAIL_VERIFY_THREAD_ID $env:GMAIL_VERIFY_SNAPSHOT_BEFORE $env:GMAIL_VERIFY_CURSOR | Out-Null
if ($LASTEXITCODE -ne 0) { throw "FAIL: local CLI read smoke check" }
```

The check passes only when every `Assert-...` line reports `PASS`. Any
exception is a failure: do not activate the Agent gate. The script keeps
response objects in memory solely to compare counts, manifest hashes, UTF-8
byte counts, and body hashes; it never prints message bodies or writes tokens,
IDs, cookies, or credentials to logs.

## Collection contract

- `gmail_list_threads(query, snapshot_before, page_token, max_results)` creates
  or reuses the collection snapshot and exposes real Gmail page tokens.
- `gmail_read_thread_page(thread_id, snapshot_before, cursor)` reads every
  snapshot-eligible message and body chunk in the matched thread. Its cursor is
  exhausted before the thread is counted complete.
- The first successful list response establishes a non-empty
  `snapshot_before`; every later list and read call uses that exact value.
- The related-ID boundary is frozen only after every Case note has been
  processed. It includes the primary ID and supported related IDs explicitly
  present in the case notes; IDs discovered later in Gmail do not expand it.
- Attachments are excluded from content retrieval. Attachment metadata may be
  reported, but attachment bodies are outside this completeness contract.
- Any source, page, cursor, manifest, hash, count, or snapshot failure returns
  `Context collection incomplete` and blocks analysis and report generation.
- `gmail_search`, `gmail_read`, and `gmail_send` remain backward-compatible
  APIs. Search and read cannot satisfy the exhaustive completeness gate.

This cloud source is operational Gmail MCP code. It is intentionally separate
from the optional governance example, and `setup_env.ps1` does not copy it to
the local Gmail tools directory.

## Rollback

Redeploy the prior Apps Script version to the same Web App URL. If local deployment has already occurred, use this order before replacing any local files:

1. Stop Antigravity and deactivate the current exhaustive Agent SKILL.
2. Stop the independent Gmail broker, which may still own a Managed Edge
   context even after Antigravity exits:

   ```powershell
   python "%USERPROFILE%\.gemini\tools\gmail\gmail_brokerctl.py" stop
   python "%USERPROFILE%\.gemini\tools\gmail\gmail_brokerctl.py" status
   ```

   Confirm the stop completed and the follow-up status shows no running broker
   or Managed Edge process/context. Do not replace local files while either is still active.
3. Restore the prior package's
   `plugins/avaya-case-review/skills/case-review/SKILL.md` and prior Gmail MCP
   source under `tools/gmail` to the deployed
   `%USERPROFILE%\.gemini\config\plugins\avaya-case-review\` and
   `%USERPROFILE%\.gemini\tools\gmail\` paths, or rerun the prior package's
   installer as the supported local rollback.

Restart Antigravity only after the prior local package is restored.
Keep the exhaustive Agent gate inactive until the prior cloud version and the
zero-result, real-case pagination, and multi-message cursor checks pass again.
The existing Managed Edge broker and explicit `legacy_playwright` rollback
behavior remain unchanged.
