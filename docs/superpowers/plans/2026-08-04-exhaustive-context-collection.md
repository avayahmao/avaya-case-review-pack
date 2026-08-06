# Exhaustive Context Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent case-review generation until every CaseToMD note and every message in every Gmail thread matched by the primary and Case-note-derived record IDs has been enumerated, read, and cryptographically validated as complete.

**Architecture:** Add an Advanced Gmail Service cloud bridge with real page tokens and stateless thread-body cursors, expose two backward-compatible MCP tools through the existing Single Managed Edge broker, and enforce an Agent-side Context Coverage Ledger. Deploy and verify the cloud endpoint before activating the new SKILL gate so an intermediate rollout cannot disable all reviews.

**Tech Stack:** Google Apps Script V8 + Advanced Gmail Service, Python 3.10+, MCP Python SDK, Playwright Managed Edge broker, Node.js `node:test`, Python `unittest`, Markdown/HTML documentation, artifact-tool PowerPoint editing.

---

## Scope and Sequencing Constraints

- The approved design is `docs/superpowers/specs/2026-08-04-exhaustive-context-collection-design.md`.
- The cloud Web App source is distinct from `examples/optional-appsscript/Code.gs`.
- Existing `gmail_search`, `gmail_read`, and `gmail_send` schemas remain unchanged.
- The local default remains `GMAIL_BACKEND=edge_broker`; no automatic fallback is added.
- Cloud deployment and live protocol verification happen before the updated case-review SKILL is copied into the runtime plugin directory.
- If Advanced Gmail Service cannot be enabled or the Web App cannot be redeployed, stop at the external deployment gate and do not activate the new Agent rule.

## File Responsibility Map

| File | Responsibility |
|---|---|
| `tools/gmail/cloud/GmailMcpBridge.gs` | Complete cloud Web App source: legacy actions plus exhaustive list/read actions |
| `tests/js/gmail_cloud_bridge.test.mjs` | Node-based deterministic Apps Script tests with mocked Gmail/Utilities services |
| `tests/test_gmail_cloud_bridge.py` | Python unittest wrapper so cloud tests run in normal discovery |
| `tools/gmail/gmail_broker_protocol.py` | Broker method allowlist and unchanged 8 MiB wire contract |
| `tools/gmail/gmail_edge_broker.py` | Read-only retry classification and Apps Script action/parameter mapping |
| `tools/gmail/gmail_legacy_backend.py` | Explicit rollback URL mapping for new read-only methods |
| `tools/gmail/gmail_mcp_server.py` | MCP tool schemas, dispatch, and direct CLI probes |
| `plugins/avaya-case-review/skills/case-review/SKILL.md` | Complete Context Before Analysis workflow and blocking output |
| `tests/case_review_scenarios.json` | Exhaustive-coverage behavioral scenarios |
| `tests/test_case_review_contract.py` | Static Agent-contract and documentation parity enforcement |
| `tests/test_gmail_broker_protocol.py` | Allowed-method compatibility |
| `tests/test_gmail_edge_adapter.py` | URL mapping, validation, retry-safe behavior |
| `tests/test_gmail_mcp_backend.py` | Tool schemas, dispatch, CLI, and legacy compatibility |
| `tests/test_gmail_broker_integration.py` | End-to-end broker framing, retries, sanitization, and response-size behavior |
| `release-manifest.txt` | Distribute cloud deployment source without installing it locally |
| `tests/test_release_manifest.py` | Cloud source inclusion and local deployment exclusion |
| `docs/GMAIL_CLOUD_BRIDGE.md` | Exact Advanced Gmail Service and Web App deployment runbook |
| README/Manager/TDD/Gmail broker docs | User, manager, and architecture contract |
| `docs/PRESENTATION.html`, PPTX, PPTX tests | Current exhaustive-retrieval communication |

---

### Task 1: Add the Advanced Gmail Cloud Bridge

**Files:**
- Create: `tools/gmail/cloud/GmailMcpBridge.gs`
- Create: `tests/js/gmail_cloud_bridge.test.mjs`
- Create: `tests/test_gmail_cloud_bridge.py`

- [ ] **Step 1: Add the failing Python-to-Node test wrapper**

Create `tests/test_gmail_cloud_bridge.py`:

```python
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE_TEST = ROOT / "tests/js/gmail_cloud_bridge.test.mjs"


class GmailCloudBridgeTests(unittest.TestCase):
    def test_cloud_bridge_node_contract(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for Gmail cloud bridge tests")
        completed = subprocess.run(
            [node, "--test", str(NODE_TEST)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
```

Create `tests/js/gmail_cloud_bridge.test.mjs` initially with an import/read assertion for the missing cloud file so the test fails before implementation:

```javascript
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(currentDirectory, "../..");
const bridgePath = path.join(root, "tools/gmail/cloud/GmailMcpBridge.gs");

test("cloud bridge source exists", () => {
  assert.equal(fs.existsSync(bridgePath), true);
});
```

- [ ] **Step 2: Run the wrapper and verify the red state**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_gmail_cloud_bridge -v
```

Expected: FAIL because `tools/gmail/cloud/GmailMcpBridge.gs` does not exist.

- [ ] **Step 3: Implement the complete cloud bridge source**

Create `tools/gmail/cloud/GmailMcpBridge.gs` with these constants and dispatch surface:

```javascript
var GMAIL_BRIDGE_VERSION = 1;
var MAX_LIST_RESULTS = 100;
var DEFAULT_LIST_RESULTS = 100;
var BODY_CHUNK_MAX_BYTES = 96 * 1024;
var THREAD_PAGE_MAX_SEGMENTS = 4;

function doGet(e) {
  try {
    var parameters = (e && e.parameter) || {};
    var action = parameters.action || "search";
    if (action === "search") return jsonOutput_(legacySearch_(parameters));
    if (action === "read") return jsonOutput_(legacyRead_(parameters));
    if (action === "send") return jsonOutput_(legacySend_(parameters));
    if (action === "list_threads") return jsonOutput_(listThreads_(parameters));
    if (action === "read_thread_page") return jsonOutput_(readThreadPage_(parameters));
    return jsonOutput_({success: false, error: "Unknown action"});
  } catch (error) {
    return jsonOutput_({success: false, error: sanitizedError_(error)});
  }
}

function jsonOutput_(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}
```

Keep the deployed legacy behavior in named helpers:

```javascript
function legacySearch_(parameters) {
  var query = parameters.q || "is:unread";
  var threads = GmailApp.search(query, 0, 10);
  var emails = threads.map(function(thread) {
    var messages = thread.getMessages();
    var message = messages[messages.length - 1];
    return {
      id: message.getId(),
      threadId: thread.getId(),
      subject: message.getSubject(),
      from: message.getFrom(),
      date: message.getDate(),
      snippet: message.getPlainBody().substring(0, 150)
    };
  });
  return {success: true, count: emails.length, emails: emails};
}

function legacyRead_(parameters) {
  var message = GmailApp.getMessageById(requireString_(parameters.id, "id"));
  if (!message) return {success: false, error: "Message not found"};
  return {
    success: true,
    id: message.getId(),
    subject: message.getSubject(),
    from: message.getFrom(),
    to: message.getTo(),
    date: message.getDate(),
    body: message.getPlainBody()
  };
}

function legacySend_(parameters) {
  var to = requireString_(parameters.to, "to");
  var subject = requireString_(parameters.subject, "subject");
  var body = requireString_(parameters.body, "body");
  GmailApp.sendEmail(to, subject, body);
  return {success: true, message: "Email sent to " + to};
}
```

Implement exact-record validation, snapshot creation, and list pagination:

```javascript
function requireRecordId_(value) {
  var recordId = requireString_(value, "query");
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{2,79}$/.test(recordId)) {
    throw new Error("INVALID_RECORD_ID");
  }
  return recordId;
}

function normalizeSnapshot_(value) {
  var snapshot = value ? new Date(value) : new Date();
  if (isNaN(snapshot.getTime())) throw new Error("INVALID_SNAPSHOT");
  return snapshot.toISOString();
}

function snapshotQuery_(recordId, snapshotBefore) {
  var epoch = Math.floor(new Date(snapshotBefore).getTime() / 1000) + 1;
  return '"' + recordId.replace(/"/g, "") + '" before:' + epoch;
}

function listThreads_(parameters) {
  var recordId = requireRecordId_(parameters.q);
  var snapshotBefore = normalizeSnapshot_(parameters.snapshot_before);
  var maxResults = parseBoundedInt_(
    parameters.max_results,
    DEFAULT_LIST_RESULTS,
    1,
    MAX_LIST_RESULTS,
    "max_results"
  );
  var options = {
    q: snapshotQuery_(recordId, snapshotBefore),
    maxResults: maxResults
  };
  if (parameters.page_token) {
    options.pageToken = requireString_(parameters.page_token, "page_token");
  }
  var response = Gmail.Users.Threads.list("me", options) || {};
  var threadIds = (response.threads || []).map(function(thread) {
    return requireString_(thread.id, "thread_id");
  });
  var nextPageToken = response.nextPageToken || "";
  return {
    success: true,
    bridge_version: GMAIL_BRIDGE_VERSION,
    query: recordId,
    snapshot_before: snapshotBefore,
    thread_ids: threadIds,
    next_page_token: nextPageToken,
    complete: nextPageToken === ""
  };
}
```

Implement stateless cursor validation:

```javascript
function encodeCursor_(state) {
  var json = JSON.stringify(state);
  return Utilities.base64EncodeWebSafe(json, Utilities.Charset.UTF_8);
}

function decodeCursor_(cursor, threadId, snapshotBefore) {
  if (!cursor) return {version: 1, message_index: 0, chunk_index: 0};
  var decoded = Utilities.newBlob(Utilities.base64DecodeWebSafe(cursor))
    .getDataAsString("UTF-8");
  var state = JSON.parse(decoded);
  if (
    state.version !== 1 ||
    state.thread_id !== threadId ||
    state.snapshot_before !== snapshotBefore ||
    !isNonNegativeInt_(state.message_index) ||
    !isNonNegativeInt_(state.chunk_index)
  ) {
    throw new Error("INVALID_CURSOR");
  }
  return state;
}
```

Implement MIME traversal, body normalization, UTF-8-safe chunking, SHA-256, and ordered message manifests with these concrete helpers:

```javascript
function headers_(payload) {
  var result = {};
  ((payload && payload.headers) || []).forEach(function(header) {
    result[String(header.name || "").toLowerCase()] = String(header.value || "");
  });
  return result;
}

function decodeBodyData_(data) {
  if (!data) return "";
  return Utilities.newBlob(Utilities.base64DecodeWebSafe(data))
    .getDataAsString("UTF-8");
}

function findMimeBody_(part, targetMime) {
  if (!part) return "";
  if (part.mimeType === targetMime && part.body && part.body.data) {
    return decodeBodyData_(part.body.data);
  }
  var children = part.parts || [];
  for (var index = 0; index < children.length; index += 1) {
    var value = findMimeBody_(children[index], targetMime);
    if (value !== "") return value;
  }
  return "";
}

function htmlToText_(html) {
  return String(html || "")
    .replace(/<br\s*\/?\s*>/gi, "\n")
    .replace(/<\/p\s*>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function attachmentNames_(part, output) {
  if (!part) return output;
  if (part.filename) output.push(String(part.filename));
  (part.parts || []).forEach(function(child) {
    attachmentNames_(child, output);
  });
  return output;
}

function utf8Length_(value) {
  return Utilities.newBlob(String(value), "text/plain").getBytes().length;
}

function splitUtf8_(value, maxBytes) {
  var chunks = [];
  var current = "";
  Array.from(String(value)).forEach(function(codePoint) {
    var candidate = current + codePoint;
    if (current !== "" && utf8Length_(candidate) > maxBytes) {
      chunks.push(current);
      current = codePoint;
    } else {
      current = candidate;
    }
  });
  chunks.push(current);
  return chunks;
}

function sha256Hex_(value) {
  return Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    String(value),
    Utilities.Charset.UTF_8
  ).map(function(byteValue) {
    var unsigned = byteValue < 0 ? byteValue + 256 : byteValue;
    return ("0" + unsigned.toString(16)).slice(-2);
  }).join("");
}

function splitAddresses_(value) {
  if (!value) return [];
  return String(value).split(",").map(function(item) {
    return item.trim();
  }).filter(function(item) { return item !== ""; });
}

function normalizeMessage_(message) {
  var payload = message.payload || {};
  var headerMap = headers_(payload);
  var plain = findMimeBody_(payload, "text/plain");
  var body = plain !== "" ? plain : htmlToText_(findMimeBody_(payload, "text/html"));
  return {
    message_id: requireString_(message.id, "message_id"),
    thread_id: requireString_(message.threadId, "thread_id"),
    internal_date: new Date(Number(message.internalDate)).toISOString(),
    from: headerMap.from || "",
    to: splitAddresses_(headerMap.to),
    cc: splitAddresses_(headerMap.cc),
    subject: headerMap.subject || "",
    body_bytes: utf8Length_(body),
    body_sha256: sha256Hex_(body),
    body_chunks: splitUtf8_(body, BODY_CHUNK_MAX_BYTES),
    attachment_names: attachmentNames_(payload, [])
  };
}

function compareMessageOrder_(left, right) {
  var dateDifference = Number(left.internalDate) - Number(right.internalDate);
  if (dateDifference !== 0) return dateDifference;
  return String(left.id).localeCompare(String(right.id));
}

function emitSegments_(messages, cursor, maxSegments) {
  var messageIndex = cursor.message_index;
  var chunkIndex = cursor.chunk_index;
  var segments = [];
  var messagesCompleted = messageIndex;
  while (messageIndex < messages.length && segments.length < maxSegments) {
    var message = messages[messageIndex];
    var chunks = message.body_chunks;
    segments.push({
      message_id: message.message_id,
      thread_id: message.thread_id,
      internal_date: message.internal_date,
      from: message.from,
      to: message.to,
      cc: message.cc,
      subject: message.subject,
      body_chunk: chunks[chunkIndex],
      chunk_index: chunkIndex,
      chunk_count: chunks.length,
      body_bytes: message.body_bytes,
      body_sha256: message.body_sha256,
      attachment_names: message.attachment_names
    });
    chunkIndex += 1;
    if (chunkIndex >= chunks.length) {
      messageIndex += 1;
      chunkIndex = 0;
      messagesCompleted = messageIndex;
    }
  }
  return {
    segments: segments,
    messages_completed: messagesCompleted,
    next_message_index: messageIndex,
    next_chunk_index: chunkIndex
  };
}
```

The emitted cursor state is:

```javascript
{
  version: 1,
  thread_id: threadId,
  snapshot_before: snapshotBefore,
  message_index: nextMessageIndex,
  chunk_index: nextChunkIndex
}
```

`readThreadPage_` must:

```javascript
function readThreadPage_(parameters) {
  var threadId = requireString_(parameters.thread_id, "thread_id");
  var snapshotBefore = normalizeSnapshot_(parameters.snapshot_before);
  var snapshotMs = new Date(snapshotBefore).getTime();
  var thread = Gmail.Users.Threads.get("me", threadId, {format: "full"});
  if (!thread || !thread.messages) throw new Error("THREAD_NOT_FOUND");

  var messages = thread.messages
    .filter(function(message) {
      return Number(message.internalDate) <= snapshotMs;
    })
    .sort(compareMessageOrder_)
    .map(normalizeMessage_);

  var manifest = messages.map(function(message) { return message.message_id; });
  var manifestSha256 = sha256Hex_(manifest.join("\n"));
  var cursor = decodeCursor_(parameters.cursor || "", threadId, snapshotBefore);
  var page = emitSegments_(messages, cursor, THREAD_PAGE_MAX_SEGMENTS);
  var complete = page.next_message_index >= messages.length;

  return {
    success: true,
    bridge_version: GMAIL_BRIDGE_VERSION,
    thread_id: threadId,
    snapshot_before: snapshotBefore,
    message_count: messages.length,
    manifest_sha256: manifestSha256,
    segments: page.segments,
    messages_completed: page.messages_completed,
    next_cursor: complete ? "" : encodeCursor_({
      version: 1,
      thread_id: threadId,
      snapshot_before: snapshotBefore,
      message_index: page.next_message_index,
      chunk_index: page.next_chunk_index
    }),
    complete: complete
  };
}
```

Each normalized message must contain the fields approved in the design. Compute `body_sha256` over the complete normalized UTF-8 body before chunking. `emitSegments_` emits no more than four 96 KiB chunks per response and never splits a Unicode code point.

At the bottom, expose pure helpers to the Node VM without changing Apps Script dispatch:

```javascript
var GmailBridgeTestExports = {
  decodeCursor: decodeCursor_,
  encodeCursor: encodeCursor_,
  listThreads: listThreads_,
  normalizeMessage: normalizeMessage_,
  normalizeSnapshot: normalizeSnapshot_,
  readThreadPage: readThreadPage_,
  sha256Hex: sha256Hex_,
  splitUtf8: splitUtf8_,
  snapshotQuery: snapshotQuery_
};
```

- [ ] **Step 4: Replace the Node smoke test with exhaustive behavior tests**

Load the `.gs` file with `vm.runInContext`, inject mocked `Gmail`, `GmailApp`, `Utilities`, and `ContentService`, then test:

```javascript
test("list_threads preserves nextPageToken and shared snapshot", () => {
  const api = loadBridge({
    listResponse: {
      threads: [{id: "thread-1"}, {id: "thread-2"}],
      nextPageToken: "page-2"
    }
  });
  const result = api.listThreads({
    q: "1-23508794022",
    snapshot_before: "2026-08-04T10:15:30Z",
    max_results: "100"
  });
  assert.deepEqual(result.thread_ids, ["thread-1", "thread-2"]);
  assert.equal(result.next_page_token, "page-2");
  assert.equal(result.complete, false);
  assert.equal(result.snapshot_before, "2026-08-04T10:15:30.000Z");
});

test("read_thread_page filters after-snapshot mail and preserves every earlier message", () => {
  const api = loadBridge({threadResponse: buildThreeMessageThread()});
  const result = api.readThreadPage({
    thread_id: "thread-1",
    snapshot_before: "2026-08-04T10:15:30Z",
    cursor: ""
  });
  assert.equal(result.message_count, 2);
  assert.equal(result.segments[0].message_id, "message-oldest");
  assert.equal(result.segments.at(-1).message_id, "message-newer");
  assert.equal(result.complete, true);
});
```

Add tests for legacy actions, zero results, exact record-ID rejection, real page token propagation, cursor round trip, cursor/thread mismatch, cursor/snapshot mismatch, HTML-only bodies, multipart traversal, attachment metadata without payload, chronological tie breaking, long Unicode body chunking, stable manifest hash, body byte count/hash, and four-segment response budget.

- [ ] **Step 5: Run the cloud bridge tests**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_gmail_cloud_bridge -v
```

Expected: PASS with all Node subtests green.

- [ ] **Step 6: Commit the cloud source and tests**

```powershell
git add -- tools/gmail/cloud/GmailMcpBridge.gs tests/js/gmail_cloud_bridge.test.mjs tests/test_gmail_cloud_bridge.py
git diff --cached --check
git commit -m "feat(gmail): add exhaustive cloud bridge"
```

---

### Task 2: Extend Broker Protocol and Browser Adapters

**Files:**
- Modify: `tools/gmail/gmail_broker_protocol.py:15-25`
- Modify: `tools/gmail/gmail_edge_broker.py:92-93,378-403`
- Modify: `tools/gmail/gmail_legacy_backend.py:64-88`
- Modify: `tests/test_gmail_broker_protocol.py:39-55`
- Modify: `tests/test_gmail_edge_adapter.py:214-340`
- Modify: `tests/test_gmail_mcp_backend.py:28-115`

- [ ] **Step 1: Write failing allowed-method and URL-mapping tests**

Update the expected broker allowlist:

```python
self.assertEqual(
    ALLOWED_METHODS,
    {
        "health",
        "gmail_search",
        "gmail_read",
        "gmail_send",
        "gmail_list_threads",
        "gmail_read_thread_page",
        "auth_login",
        "shutdown",
    },
)
```

Extend `test_maps_all_gmail_methods_and_creates_one_page_per_execute` with:

```python
await adapter.execute(
    "gmail_list_threads",
    {
        "query": "1-23508794022",
        "snapshot_before": "2026-08-04T10:15:30Z",
        "page_token": "page-2",
        "max_results": 100,
    },
)
await adapter.execute(
    "gmail_read_thread_page",
    {
        "thread_id": "thread-1",
        "snapshot_before": "2026-08-04T10:15:30Z",
        "cursor": "cursor-2",
    },
)
```

Assert URL actions and parameters are exactly:

```python
(
    "list_threads",
    {
        "q": ["1-23508794022"],
        "snapshot_before": ["2026-08-04T10:15:30Z"],
        "page_token": ["page-2"],
        "max_results": ["100"],
    },
)
(
    "read_thread_page",
    {
        "thread_id": ["thread-1"],
        "snapshot_before": ["2026-08-04T10:15:30Z"],
        "cursor": ["cursor-2"],
    },
)
```

Add invalid-parameter cases for blank record IDs, non-integer/bool page sizes, page sizes outside 1-100, missing snapshots, missing thread IDs, and non-string cursor/token values.

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_gmail_broker_protocol tests.test_gmail_edge_adapter tests.test_gmail_mcp_backend -v
```

Expected: FAIL because new methods are not allowed or mapped.

- [ ] **Step 3: Add protocol and adapter mappings**

Add both method names to `ALLOWED_METHODS` and to `_SAFE_READ_METHODS`:

```python
_SAFE_READ_METHODS = frozenset(
    {
        "gmail_search",
        "gmail_read",
        "gmail_list_threads",
        "gmail_read_thread_page",
    }
)
```

Add typed helpers in `ManagedEdgeAdapter`:

```python
@staticmethod
def _optional_string(params: dict[str, Any], name: str) -> str:
    value = params.get(name, "")
    if not isinstance(value, str):
        raise BrowserApplicationError("Gmail request parameters are invalid")
    return value

@staticmethod
def _bounded_int(params: dict[str, Any], name: str, minimum: int, maximum: int) -> int:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BrowserApplicationError("Gmail request parameters are invalid")
    if value < minimum or value > maximum:
        raise BrowserApplicationError("Gmail request parameters are invalid")
    return value
```

Extend `_build_method_url`:

```python
elif method == "gmail_list_threads":
    action = "list_threads"
    mapped = {
        "q": self._required_string(params, "query"),
        "snapshot_before": self._optional_string(params, "snapshot_before"),
        "page_token": self._optional_string(params, "page_token"),
        "max_results": str(self._bounded_int(params, "max_results", 1, 100)),
    }
elif method == "gmail_read_thread_page":
    action = "read_thread_page"
    mapped = {
        "thread_id": self._required_string(params, "thread_id"),
        "snapshot_before": self._required_string(params, "snapshot_before"),
        "cursor": self._optional_string(params, "cursor"),
    }
```

Omit optional empty query parameters from `build_action_url` by filtering empty values as well as `action`.

Extend `legacy_query` with identical action mappings; the backend remains explicit rollback and does not perform automatic fallback.

- [ ] **Step 4: Run focused tests**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit protocol and adapter support**

```powershell
git add -- tools/gmail/gmail_broker_protocol.py tools/gmail/gmail_edge_broker.py tools/gmail/gmail_legacy_backend.py tests/test_gmail_broker_protocol.py tests/test_gmail_edge_adapter.py tests/test_gmail_mcp_backend.py
git diff --cached --check
git commit -m "feat(gmail): route exhaustive context methods"
```

---

### Task 3: Expose Exhaustive MCP Tools and Direct Probes

**Files:**
- Modify: `tools/gmail/gmail_mcp_server.py:76-155`
- Modify: `tests/test_gmail_mcp_backend.py:115-180`

- [ ] **Step 1: Add failing tool-schema and dispatch tests**

Preserve the first three existing tool contracts and append:

```python
self.assertEqual(
    [tool.name for tool in tools],
    [
        "gmail_search",
        "gmail_read",
        "gmail_send",
        "gmail_list_threads",
        "gmail_read_thread_page",
    ],
)
```

Assert exact schemas:

```python
list_schema = tools[3].inputSchema
self.assertEqual(list_schema["required"], ["query", "max_results"])
self.assertEqual(list_schema["properties"]["max_results"], {
    "type": "integer",
    "minimum": 1,
    "maximum": 100,
    "description": "Maximum thread IDs returned in this page",
})

thread_schema = tools[4].inputSchema
self.assertEqual(thread_schema["required"], ["thread_id", "snapshot_before"])
```

Add dispatch assertions:

```python
query.assert_awaited_once_with(
    "gmail_list_threads",
    {
        "query": "1-23508794022",
        "snapshot_before": "",
        "page_token": "",
        "max_results": 100,
    },
)
```

Add direct CLI cases:

```python
(
    ["list-threads", "1-23508794022", "", "", "100"],
    (
        "gmail_list_threads",
        {
            "query": "1-23508794022",
            "snapshot_before": "",
            "page_token": "",
            "max_results": 100,
        },
    ),
)
(
    ["read-thread-page", "thread-1", "2026-08-04T10:15:30Z", ""],
    (
        "gmail_read_thread_page",
        {
            "thread_id": "thread-1",
            "snapshot_before": "2026-08-04T10:15:30Z",
            "cursor": "",
        },
    ),
)
```

- [ ] **Step 2: Run the MCP backend tests and verify failure**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_gmail_mcp_backend -v
```

Expected: FAIL because the tools and CLI modes do not exist.

- [ ] **Step 3: Implement tool schemas, dispatch, and CLI modes**

Append tools with these descriptions:

```python
Tool(
    name="gmail_list_threads",
    description=(
        "Enumerate one complete page of Gmail thread IDs for an exact record ID "
        "within a shared collection snapshot"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Exact case or related record ID"},
            "snapshot_before": {"type": "string", "description": "Shared RFC3339 snapshot; empty only on the first page"},
            "page_token": {"type": "string", "description": "Opaque Gmail page token from the prior response"},
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "Maximum thread IDs returned in this page",
            },
        },
        "required": ["query", "max_results"],
    },
)
```

Add the approved `gmail_read_thread_page` schema and dispatch mappings. Parse CLI `max_results` with an explicit integer conversion that rejects booleans, non-numeric input, and values outside 1-100. Update usage text to list all five modes.

- [ ] **Step 4: Run MCP and direct-script tests**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_gmail_mcp_backend -v
python tools/gmail/gmail_mcp_server.py --help
```

Expected: tests PASS and direct invocation prints sanitized usage without importing a browser.

- [ ] **Step 5: Commit the MCP tools**

```powershell
git add -- tools/gmail/gmail_mcp_server.py tests/test_gmail_mcp_backend.py
git diff --cached --check
git commit -m "feat(gmail): expose exhaustive context tools"
```

---

### Task 4: Add Broker Integration and Safety Coverage

**Files:**
- Modify: `tests/test_gmail_broker_integration.py`
- Modify: `tests/test_gmail_broker_client.py`
- Modify: `tests/test_gmail_broker_soak.py`
- Modify: `tests/test_gmail_broker_state.py`

- [ ] **Step 1: Add failing read-only retry and sanitization tests**

Add integration cases that issue both new methods through real broker framing and assert:

```python
self.assertEqual(
    [call.method for call in adapter.calls],
    ["gmail_list_threads", "gmail_read_thread_page"],
)
self.assertNotIn(record_id_sentinel, log_path.read_text(encoding="utf-8"))
self.assertNotIn(cursor_sentinel, log_path.read_text(encoding="utf-8"))
```

Test safe retry behavior:

```python
for method, params in (
    (
        "gmail_list_threads",
        {"query": "1-23508794022", "snapshot_before": "", "page_token": "", "max_results": 100},
    ),
    (
        "gmail_read_thread_page",
        {"thread_id": "thread-1", "snapshot_before": "2026-08-04T10:15:30Z", "cursor": ""},
    ),
):
    with self.subTest(method=method):
        self.assertEqual(await request_with_one_browser_failure(method, params), "ok")
```

Add response tests immediately below the 8 MiB limit and above it. Add a soak mix containing old and new read methods from four clients.

- [ ] **Step 2: Run integration/safety tests and verify the red state**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_gmail_broker_integration tests.test_gmail_broker_client tests.test_gmail_broker_soak tests.test_gmail_broker_state -v
```

Expected: this is a regression-hardening task after Tasks 2-3. The tests may already PASS; if so, record the green baseline and do not manufacture a production change.

- [ ] **Step 3: Make only the minimal integration corrections**

Tasks 2-3 should already satisfy routing. If the regression tests are green immediately, record that this task adds coverage only and make no production edit. If a test exposes a defect, limit the correction to broker method categorization, request validation, or the sanitized logging allowlist. Never log params, queries, tokens, cursors, thread IDs, message IDs, or result bodies.

- [ ] **Step 4: Run the integration and soak tests**

Run the command from Step 2.

Expected: PASS with no sentinel in logs.

- [ ] **Step 5: Commit integration coverage**

```powershell
git add -- tests/test_gmail_broker_integration.py tests/test_gmail_broker_client.py tests/test_gmail_broker_soak.py tests/test_gmail_broker_state.py tools/gmail/gmail_edge_broker.py tools/gmail/gmail_broker_state.py
git diff --cached --check
git commit -m "test(gmail): cover exhaustive broker traffic"
```

Only add a production file if Step 3 changed it.

---

### Task 5: Enforce Complete Context Before Analysis in the Agent

**Files:**
- Modify: `plugins/avaya-case-review/skills/case-review/SKILL.md:35-112,180-230,269-285`
- Modify: `tests/test_case_review_contract.py`
- Modify: `tests/case_review_scenarios.json`

- [ ] **Step 1: Add failing Agent-contract tests**

Add this exact helper beside the existing extraction helpers, then add the tests:

```python
def extract_between(content: str, start_marker: str, end_marker: str) -> str:
    start = content.index(start_marker)
    end = content.index(end_marker, start)
    return content[start:end]
```

```python
def test_complete_context_gate_precedes_analysis(self):
    retrieve = extract_between(
        self.skill,
        "### Step 2 - Retrieve Required Sources",
        "### Step 4 - Analyze Only What the Evidence Supports",
    )
    for marker in [
        "Complete Context Before Analysis",
        "every discrete Case note",
        "gmail_list_threads",
        "gmail_read_thread_page",
        "next_page_token",
        "next_cursor",
        "Context Coverage Ledger",
        "Context collection incomplete — review not generated.",
    ]:
        self.assertIn(marker, retrieve)
    self.assertLess(
        self.skill.index("Complete Context Before Analysis"),
        self.skill.index("### Step 4 - Analyze Only What the Evidence Supports"),
    )


def test_incomplete_context_output_contains_no_review_sections(self):
    failure = extract_fenced_block_after(
        self.skill,
        "Context collection incomplete — review not generated.",
    )
    for forbidden in [
        "Executive Summary",
        "Technical & Incident Assessment",
        "Progress Summary",
        "Root cause",
        "Appendix A",
    ]:
        self.assertNotIn(forbidden, failure)
```

Add ledger equality markers and assertions that the old relevance-only wording (`Read relevant messages`, `prioritizing`) is absent from the Gmail collection section.

- [ ] **Step 2: Add exhaustive behavior scenarios**

Append these scenario IDs with concrete expected behavior and contract markers:

```json
{
  "id": "all_case_notes_before_gmail",
  "input": "The CaseToMD record contains status pings, technical notes, and multiple related record IDs.",
  "expected": "Process and count every Case note before freezing the primary-plus-related-ID Gmail query set.",
  "contract_markers": ["every discrete Case note", "case_notes_discovered == case_notes_processed", "freeze the record-ID query set"]
},
{
  "id": "multipage_gmail_threads",
  "input": "A record-ID Gmail search returns several pages and duplicate threads across IDs.",
  "expected": "Follow every next page token, deduplicate by thread ID, preserve match provenance, and do not analyze until all queries complete.",
  "contract_markers": ["next_page_token", "thread_id", "record_id_queries_completed"]
},
{
  "id": "every_message_in_thread",
  "input": "A matched Gmail thread contains multiple messages and one large chunked body.",
  "expected": "Read every message and body chunk, verify counts and SHA-256, then mark the thread complete.",
  "contract_markers": ["gmail_read_thread_page", "body_hashes_verified", "threads_read_complete"]
},
{
  "id": "incomplete_context_blocks_review",
  "input": "A pagination call fails after some Case notes, threads, and messages were already retrieved.",
  "expected": "Output only the context-collection failure counts and blocker; generate no partial review sections.",
  "contract_markers": ["Context collection incomplete — review not generated.", "Partial results", "must not output Executive Summary"]
},
{
  "id": "complete_zero_gmail_results",
  "input": "Every frozen record-ID query returns zero threads with complete pagination.",
  "expected": "Treat Gmail coverage as complete with zero threads and continue from the fully processed Case record.",
  "contract_markers": ["zero-result query", "complete=true", "all query pagination chains"]
}
```

Add scenarios for token loops, disappearing threads, snapshot-after messages, and attachment metadata/out-of-scope content.

- [ ] **Step 3: Run focused contract tests and verify failure**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest `
  tests.test_case_review_contract.CaseReviewContractTests.test_complete_context_gate_precedes_analysis `
  tests.test_case_review_contract.CaseReviewContractTests.test_incomplete_context_output_contains_no_review_sections `
  tests.test_case_review_contract.CaseReviewContractTests.test_regression_matrix_covers_required_scenarios -v
```

Expected: FAIL against the relevance-filtered Gmail workflow.

- [ ] **Step 4: Rewrite retrieval steps and add the completeness gate**

In `SKILL.md`, keep CaseToMD retrieval first, then add:

```markdown
### Complete Context Before Analysis

Before generating any review content, process every discrete Case note returned by CaseToMD, freeze the primary Case ID plus every supported related record ID explicitly present in those notes, enumerate every Gmail thread for every frozen ID, and read every message in every unique matched thread. Relevance ranking may affect display only after this gate passes; it must never determine what is retrieved or read.
```

Replace the Gmail steps with exact pagination/cursor loops using the two new tools. Add the internal Context Coverage Ledger fields and equality checks from the design.

Add the exact blocking output:

```text
Context collection incomplete — review not generated.

Case notes: <processed>/<discovered>
Record-ID queries: <completed>/<planned>
Gmail threads: <completed>/<discovered>
Gmail messages: <completed>/<expected>
Blocker: <exact sanitized failure>
```

State explicitly that this failure output contains no review template sections, partial RCA, ownership conclusion, or Evidence Appendix. A retry starts from the raw Case ID with a new snapshot and does not reuse the partial corpus.

Add final reflection checks for note/query/thread/message/chunk/hash equality and stable manifest hashes. Add the principle to Non-Negotiable Rules.

- [ ] **Step 5: Run the contract module**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_case_review_contract -v
```

Expected: PASS.

- [ ] **Step 6: Commit the Agent gate**

```powershell
git add -- plugins/avaya-case-review/skills/case-review/SKILL.md tests/test_case_review_contract.py tests/case_review_scenarios.json
git diff --cached --check
git commit -m "feat(case-review): require complete source context"
```

Do not copy this SKILL to the deployed runtime yet.

---

### Task 6: Distribute Cloud Source and Align Core Documentation

**Files:**
- Create: `docs/GMAIL_CLOUD_BRIDGE.md`
- Modify: `release-manifest.txt`
- Modify: `tests/test_release_manifest.py`
- Modify: `README.md`, `README.html`
- Modify: `AGENTS.md`
- Modify: `docs/MANAGER_ONBOARDING_GUIDE.md`, `.html`
- Modify: `docs/TECHNICAL_DESIGN_DOCUMENT.md`, `.html`
- Modify: `docs/GMAIL_EDGE_BROKER.md`
- Modify: `docs/RELEASE_NOTES.md`, `.html`
- Modify: `tests/test_case_review_contract.py`

- [ ] **Step 1: Add failing distribution and documentation tests**

Require:

```python
self.assertIn("tools/gmail/cloud/GmailMcpBridge.gs", manifest_entries)
self.assertNotIn("GmailMcpBridge.gs", installer_deployment_filenames)
```

Add document parity markers to README, Manager Guide, TDD, and Gmail broker guide:

```python
required = [
    "Complete Context Before Analysis",
    "every Case note",
    "every message in every matched Gmail thread",
    "Context collection incomplete",
    "Advanced Gmail Service",
]
```

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_release_manifest tests.test_case_review_contract -v
```

Expected: FAIL because the cloud source and documentation are absent.

- [ ] **Step 3: Add the cloud deployment runbook**

Create `docs/GMAIL_CLOUD_BRIDGE.md` with exact deployment order:

1. Open the existing Gmail MCP Apps Script project, not the optional governance example.
2. Add the Advanced Gmail Service named `Gmail`, API version `v1`.
3. Replace the Gmail Web App source with `tools/gmail/cloud/GmailMcpBridge.gs`.
4. Save and run a syntax check in the editor.
5. Deploy > Manage deployments > Edit the existing Web App > New version > Deploy.
6. Keep the existing deployment URL.
7. Complete controlled authorization if Google requests new Gmail scopes.
8. Verify a zero-result `list_threads` call returns `complete=true` and a real case query provides a stable snapshot/page-token chain.
9. Verify one multi-message thread through cursor exhaustion and hash/count checks.
10. Only then deploy the updated local MCP and Agent SKILL.

Include rollback: redeploy the prior Apps Script version and keep the exhaustive Agent gate inactive.

- [ ] **Step 4: Align release and runtime documentation**

Add `tools/gmail/cloud/GmailMcpBridge.gs` to `release-manifest.txt`, but do not add it to `$GmailDeploymentFiles` in `setup_env.ps1`.

Update docs to explain:

- exhaustive tools and snapshot semantics;
- related-ID boundary;
- attachments excluded;
- strict blocking behavior;
- cloud source versus optional governance example;
- deployment sequencing;
- existing tools remain compatible.

Add an Unreleased release-note entry; do not bump the plugin version or publish a release in this task.

- [ ] **Step 5: Run documentation, manifest, HTML, and full tests**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_release_manifest tests.test_case_review_contract -v
python -m unittest discover -s tests -p 'test_*.py' -v
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Commit distribution and core docs**

```powershell
git add -- tools/gmail/cloud/GmailMcpBridge.gs release-manifest.txt tests/test_release_manifest.py docs/GMAIL_CLOUD_BRIDGE.md README.md README.html AGENTS.md docs/MANAGER_ONBOARDING_GUIDE.md docs/MANAGER_ONBOARDING_GUIDE.html docs/TECHNICAL_DESIGN_DOCUMENT.md docs/TECHNICAL_DESIGN_DOCUMENT.html docs/GMAIL_EDGE_BROKER.md docs/RELEASE_NOTES.md docs/RELEASE_NOTES.html tests/test_case_review_contract.py
git diff --cached --check
git commit -m "docs(gmail): document exhaustive context deployment"
```

The cloud source may already be committed by Task 1; staging it again is harmless only if unchanged. Verify the cached diff before committing.

---

### Task 7: Synchronize Presentation Sources

**Files:**
- Modify: `docs/PRESENTATION.html`
- Modify: `docs/Avaya_Case_Review_Suite_Presentation.pptx`
- Modify: `tests/test_case_review_contract.py`
- Modify: `tests/test_presentation_pptx_contract.py`

- [ ] **Step 1: Add failing HTML/PPTX retrieval-contract assertions**

Require visible presentation text that states:

```text
Complete Context Before Analysis
Every Case note
Every message in every matched Gmail thread
Incomplete collection blocks the review
```

Prohibit any presentation claim that Gmail reads only key/relevant/prioritized messages.

- [ ] **Step 2: Run focused presentation tests and verify failure**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest `
  tests.test_case_review_contract.CaseReviewContractTests.test_adm_spec_and_presentation_follow_layered_contract `
  tests.test_presentation_pptx_contract -v
```

Expected: FAIL because presentation sources do not describe exhaustive retrieval.

- [ ] **Step 3: Update HTML presentation copy**

Add concise, audience-facing copy to the existing retrieval/architecture slides. Do not add a dense new architecture diagram. Keep the current six-section report slide and evidence-bounded claims.

- [ ] **Step 4: Update the existing PPTX through the Presentations skill**

Use `presentations:Presentations` in template-following mode:

- inspect all 12 source slides;
- map every output slide to an inherited source slide;
- edit inherited text elements in place with `@oai/artifact-tool`;
- preserve master/layout/theme semantics;
- render and inspect all slides;
- run fidelity, overflow, and empty-placeholder checks;
- add no unsupported claims or external assets.

- [ ] **Step 5: Run presentation and full tests**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_presentation_pptx_contract tests.test_case_review_contract -v
python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: PASS with no visible overflow or stale copy.

- [ ] **Step 6: Commit presentation parity**

```powershell
git add -- docs/PRESENTATION.html docs/Avaya_Case_Review_Suite_Presentation.pptx tests/test_case_review_contract.py tests/test_presentation_pptx_contract.py
git diff --cached --check
git commit -m "docs(presentation): explain exhaustive context gate"
```

---

### Task 8: Deploy Cloud First, Then Activate Local Runtime

**Files:**
- Deploy cloud source: `tools/gmail/cloud/GmailMcpBridge.gs`
- Deploy local tools through: `setup_env.ps1`
- Deploy Agent source: `plugins/avaya-case-review/skills/case-review/SKILL.md`
- Runtime Agent target: `%USERPROFILE%\.gemini\config\plugins\avaya-case-review\skills\case-review\SKILL.md`

- [ ] **Step 1: Run the complete repository gate before external deployment**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest discover -s tests -p 'test_*.py' -v
git diff --check
git status --short
```

Expected: all tests PASS and tracked working tree is clean.

- [ ] **Step 2: Deploy the existing Web App's new version**

Follow `docs/GMAIL_CLOUD_BRIDGE.md` exactly. Do not create a second governance Web App and do not change the configured Web App URL.

This step is an explicit external gate. If the Advanced Gmail Service cannot be enabled or deployment authorization is unavailable, report BLOCKED and do not proceed to local Agent activation.

- [ ] **Step 3: Verify cloud zero-result pagination through the local source CLI**

After the deployment is live and authentication is valid:

```powershell
python tools/gmail/gmail_mcp_server.py list-threads CTASK999999999999999999 "" "" 100
```

Expected JSON fields:

```json
{
  "success": true,
  "thread_ids": [],
  "next_page_token": "",
  "complete": true
}
```

- [ ] **Step 4: Verify a real multi-page or multi-message case safely**

Use an approved test Case ID. Record the returned snapshot. Follow every page token. Select one returned thread, follow every cursor, and verify stable `manifest_sha256`, message count, body byte counts, and body SHA-256 values. Do not print message bodies into logs or the implementation record.

- [ ] **Step 5: Deploy local runtime files**

Run the installer only after cloud verification:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_env.ps1
```

Expected: the explicit Gmail deployment allowlist remains intact, the broker is restarted safely, and authentication is requested only if status returns exit code 10.

- [ ] **Step 6: Verify runtime source parity and broker status**

```powershell
$sourceSkill = Resolve-Path '.\plugins\avaya-case-review\skills\case-review\SKILL.md'
$runtimeSkill = Join-Path $env:USERPROFILE '.gemini\config\plugins\avaya-case-review\skills\case-review\SKILL.md'
$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceSkill).Hash
$runtimeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $runtimeSkill).Hash
if ($sourceHash -ne $runtimeHash) { throw 'Runtime SKILL does not match source' }
python "$env:USERPROFILE\.gemini\tools\gmail\gmail_brokerctl.py" status
```

Expected: hashes match and broker status is authenticated or returns the documented authentication-required state.

- [ ] **Step 7: Run one end-to-end case-review completeness PoC**

Use a Case ID with multiple Case notes and at least one multi-message Gmail thread. Verify the Agent processes all notes, freezes only Case-note-derived IDs, exhausts all pages/cursors, and generates the review only after its ledger passes. Then simulate one failed page and verify only the blocking response is returned.

- [ ] **Step 8: Commit any deployment-record-only correction**

Do not commit credentials, deployment URLs, queries, message IDs, bodies, screenshots containing mail, profiles, broker state, or logs. If no repository correction is required, create no commit for this task.

---

### Task 9: Final Cross-Layer Review and Release Readiness

**Files:**
- Verify all changed files
- Do not bump version or create a GitHub Release unless separately authorized

- [ ] **Step 1: Run the final automated matrix**

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest discover -s tests -p 'test_*.py' -v
Get-Content -Raw tools/gmail/cloud/GmailMcpBridge.gs | node --check
git diff --check
git fsck --no-dangling
```

Expected: all checks PASS.

- [ ] **Step 2: Audit current contract and stale wording**

```powershell
rg -n "Read relevant messages|prioritizing commitments|partial review|first 10|GmailApp.search\(.*0, 10\)" plugins README.md README.html docs tests tools/gmail/cloud
```

Expected: the legacy `search` compatibility implementation may retain its 10-result behavior only inside the clearly labeled legacy action; the case-review contract and current documentation contain no relevance-filtered collection rule.

- [ ] **Step 3: Audit secrets and runtime artifacts**

```powershell
git ls-files | rg -i "chrome_profile|edge_broker_profile|cookie|token|credential|broker.*\.log|\.zip$"
```

Expected: no runtime profile, secret, log, or ZIP artifact is tracked. Source filenames such as `gmail_broker_protocol.py` are not false positives.

- [ ] **Step 4: Request final spec and quality reviews**

Review the complete implementation against `docs/superpowers/specs/2026-08-04-exhaustive-context-collection-design.md`. Fix every missing requirement or Important quality issue, then rerun the full matrix.

- [ ] **Step 5: Record final status**

Report repository commits, test count, cloud deployment state, runtime hash parity, live PoC result, and whether the working tree is clean. State explicitly that no release was created unless separately authorized.

---

## Completion Criteria

- Every Case note returned by CaseToMD is counted and processed before Gmail collection.
- The Gmail query universe contains only the primary ID and Case-note-derived related record IDs.
- Every query reaches page-token exhaustion under one snapshot.
- Every unique thread and every snapshot-eligible message reaches cursor exhaustion.
- Every message body reassembles to the advertised UTF-8 byte count and SHA-256.
- Any incomplete source blocks all review sections and returns only sanitized coverage counts.
- Attachments remain outside the content gate while filenames may be recorded.
- Existing Gmail tools and Managed Edge behavior remain backward compatible.
- Advanced Gmail Service cloud source is version controlled, distributed, and clearly separate from the optional governance example.
- Cloud deployment succeeds before the Agent gate is activated locally.
- Documentation and presentations describe the same exhaustive behavior.
- Full tests, live zero-result probe, live multi-message probe, runtime hash comparison, and final cross-layer reviews pass.
