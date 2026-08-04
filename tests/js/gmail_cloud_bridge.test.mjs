import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import test from "node:test";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const bridgePath = resolve(here, "../../tools/gmail/cloud/GmailMcpBridge.gs");

function webSafe(value) {
  return Buffer.from(value, "utf8").toString("base64url");
}

function rawMessage({
  id,
  threadId = "thread-1",
  internalDate = "2026-08-04T10:00:00.000Z",
  headers = {},
  mimeType = "text/plain",
  body = "",
  parts,
  filename = "",
}) {
  return {
    id,
    threadId,
    internalDate: String(new Date(internalDate).getTime()),
    payload: {
      mimeType,
      filename,
      headers: Object.entries(headers).map(([name, value]) => ({ name, value })),
      body: parts ? {} : { data: webSafe(body) },
      parts,
    },
  };
}

function legacyMessage({
  id = "legacy-message",
  threadId = "legacy-thread",
  subject = "Legacy subject",
  from = "sender@example.com",
  to = "recipient@example.com",
  cc = "",
  date = "2026-08-04T10:00:00.000Z",
  html = "<p>Legacy body</p>",
  plain = "Legacy body",
}) {
  return {
    getId: () => id,
    getThread: () => ({ getId: () => threadId }),
    getSubject: () => subject,
    getFrom: () => from,
    getTo: () => to,
    getCc: () => cc,
    getDate: () => new Date(date),
    getBody: () => html,
    getPlainBody: () => plain,
  };
}

function loadBridge({ listPages = {}, threads = {}, legacyThreads = [], legacyMessages = {} } = {}) {
  const calls = { list: [], get: [], search: [], sent: [], blob: 0 };
  const Utilities = {
    Charset: { UTF_8: "UTF-8" },
    DigestAlgorithm: { SHA_256: "SHA_256" },
    newBlob(value) {
      calls.blob += 1;
      const bytes = Array.isArray(value) || Buffer.isBuffer(value)
        ? Buffer.from(value)
        : Buffer.from(String(value), "utf8");
      return {
        getBytes: () => Array.from(bytes),
        getDataAsString: () => bytes.toString("utf8"),
      };
    },
    base64EncodeWebSafe(bytes) {
      return Buffer.from(bytes).toString("base64url");
    },
    base64DecodeWebSafe(value) {
      if (!/^[A-Za-z0-9_-]*={0,2}$/.test(value)) throw new Error("invalid base64");
      return Array.from(Buffer.from(value, "base64url"));
    },
    computeDigest(_algorithm, value) {
      return Array.from(createHash("sha256").update(String(value), "utf8").digest());
    },
  };
  const context = {
    console,
    JSON,
    Date,
    Math,
    Number,
    String,
    Array,
    Object,
    RegExp,
    Error,
    Buffer,
    Utilities,
    Gmail: {
      Users: {
        Threads: {
          list(userId, options) {
            calls.list.push({ userId, options: { ...options } });
            const pageKey = options.pageToken || "first";
            const hasPage = Object.prototype.hasOwnProperty.call(listPages, pageKey);
            return structuredClone(hasPage ? listPages[pageKey] : { threads: [] });
          },
          get(userId, threadId, options) {
            calls.get.push({ userId, threadId, options: { ...options } });
            const hasThread = Object.prototype.hasOwnProperty.call(threads, threadId);
            return structuredClone(hasThread ? threads[threadId] : { id: threadId, messages: [] });
          },
        },
      },
    },
    GmailApp: {
      search(query, start, limit) {
        calls.search.push({ query, start, limit });
        return legacyThreads;
      },
      getMessageById(id) {
        if (!legacyMessages[id]) throw new Error("Message not found");
        return legacyMessages[id];
      },
      sendEmail(to, subject, body) {
        calls.sent.push({ to, subject, body });
      },
    },
    ContentService: {
      MimeType: { JSON: "application/json" },
      createTextOutput(data) {
        return {
          data,
          mimeType: null,
          setMimeType(mimeType) {
            this.mimeType = mimeType;
            return this;
          },
        };
      },
    },
  };
  vm.createContext(context);
  vm.runInContext(readFileSync(bridgePath, "utf8"), context, { filename: bridgePath });
  return { api: context.GmailBridgeTestExports, calls, context };
}

function bodySegment(message) {
  return message.segments[0];
}

test("list_threads uses an exact snapshot query and preserves Gmail pagination", () => {
  const { api, calls } = loadBridge({
    listPages: {
      first: { threads: [{ id: "thread-a" }, { id: "thread-b" }], nextPageToken: "opaque-next" },
      "opaque-next": { threads: [{ id: "thread-c" }] },
    },
  });
  const snapshot = "2026-08-04T10:15:30.250Z";
  const first = api.listThreads({ q: "1-23508794022", snapshot_before: snapshot, max_results: "999" });
  const second = api.listThreads({ q: "1-23508794022", snapshot_before: snapshot, page_token: first.next_page_token });

  assert.deepEqual(Array.from(first.thread_ids), ["thread-a", "thread-b"]);
  assert.equal(first.next_page_token, "opaque-next");
  assert.equal(first.complete, false);
  assert.deepEqual(Array.from(second.thread_ids), ["thread-c"]);
  assert.equal(second.next_page_token, "");
  assert.equal(second.complete, true);
  assert.equal(calls.list[0].userId, "me");
  assert.equal(calls.list[0].options.q, '"1-23508794022" before:1785838531');
  assert.equal(calls.list[0].options.maxResults, 100);
  assert.equal(calls.list[1].options.q, calls.list[0].options.q);
  assert.equal(calls.list[1].options.pageToken, "opaque-next");
});

test("list_threads handles zero results and rejects non-record queries", () => {
  const { api, calls } = loadBridge();
  const response = api.listThreads({ q: "INC7445969", snapshot_before: "2026-08-04T10:15:30Z", max_results: 0 });

  assert.deepEqual(Array.from(response.thread_ids), []);
  assert.equal(response.complete, true);
  assert.equal(response.next_page_token, "");
  assert.equal(calls.list[0].options.maxResults, 1);
  assert.throws(
    () => api.listThreads({ q: "1-23 OR is:unread", snapshot_before: "2026-08-04T10:15:30Z" }),
    /INVALID_RECORD_ID/,
  );
  for (const invalidId of ["alice", "password", "foo123", "INCABC"]) {
    assert.throws(
      () => api.listThreads({ q: invalidId, snapshot_before: "2026-08-04T10:15:30Z" }),
      /INVALID_RECORD_ID/,
    );
  }
  for (const validId of ["INC7445969", "1-23508794022", "1-AWTCH3", "CTASK0001234", "CHG1037245", "PRJTASK0001", "ACTIVITY123", "ESC123", "SR12345"]) {
    assert.doesNotThrow(() => api.listThreads({ q: validId, snapshot_before: "2026-08-04T10:15:30Z" }));
  }
  assert.equal(api.normalizeSnapshot("2026-08-04T10:15:30+00:00"), "2026-08-04T10:15:30.000Z");
  assert.throws(() => api.normalizeSnapshot("not-a-date"), /INVALID_SNAPSHOT/);
});

test("cursors round trip and are bound to their thread and snapshot", () => {
  const { api } = loadBridge();
  const snapshot = "2026-08-04T10:15:30.000Z";
  const cursor = api.encodeCursor({
    version: 1,
    thread_id: "thread-a",
    snapshot_before: snapshot,
    message_index: 2,
    chunk_index: 3,
  });

  assert.deepEqual(api.decodeCursor(cursor, "thread-a", snapshot), {
    version: 1,
    thread_id: "thread-a",
    snapshot_before: snapshot,
    message_index: 2,
    chunk_index: 3,
  });
  assert.match(cursor, /^[A-Za-z0-9_-]+$/);
  assert.throws(() => api.decodeCursor(cursor, "thread-b", snapshot), /INVALID_CURSOR/);
  assert.throws(() => api.decodeCursor(cursor, "thread-a", "2026-08-04T10:15:31.000Z"), /INVALID_CURSOR/);
});

test("read_thread_page filters after-snapshot messages and orders retained messages", () => {
  const snapshot = "2026-08-04T10:15:30.000Z";
  const early = rawMessage({
    id: "early",
    internalDate: "2026-08-04T10:14:00Z",
    body: "early",
    headers: {
      From: "sender@example.com",
      TO: '\"Doe, Jane\" <first@example.com>, second@example.com',
      Cc: "copy@example.com",
      SUBJECT: "Case update",
    },
  });
  const tied = rawMessage({ id: "a-tie", internalDate: "2026-08-04T10:15:00Z", body: "tie" });
  const tiedLaterId = rawMessage({ id: "z-tie", internalDate: "2026-08-04T10:15:00Z", body: "tie" });
  const late = rawMessage({ id: "late", internalDate: "2026-08-04T10:16:00Z", body: "late" });
  const { api, calls } = loadBridge({ threads: { "thread-a": { messages: [late, tiedLaterId, early, tied] } } });

  const response = api.readThreadPage({ thread_id: "thread-a", snapshot_before: snapshot });

  assert.equal(calls.get[0].userId, "me");
  assert.equal(calls.get[0].options.format, "full");
  assert.equal(response.message_count, 3);
  assert.deepEqual(Array.from(response.segments, (segment) => segment.message_id), ["early", "a-tie", "z-tie"]);
  assert.equal(response.complete, true);
  assert.equal(response.messages_completed, 3);
  assert.equal(response.segments[0].from, "sender@example.com");
  assert.deepEqual(Array.from(response.segments[0].to), ['\"Doe, Jane\" <first@example.com>', "second@example.com"]);
  assert.deepEqual(Array.from(response.segments[0].cc), ["copy@example.com"]);
  assert.equal(response.segments[0].subject, "Case update");
});

test("normalization prefers nested text/plain, reads HTML fallback, and excludes attachment payloads", () => {
  const { api } = loadBridge();
  const htmlOnly = rawMessage({
    id: "html-only",
    mimeType: "text/html",
    body: "<div>Hello <b>world</b><br>again &amp; more &#x1F642;</div>",
  });
  const multipart = rawMessage({
    id: "multipart",
    mimeType: "multipart/mixed",
    parts: [
      { mimeType: "text/html", body: { data: webSafe("<p>HTML fallback</p>") } },
      {
        mimeType: "text/plain",
        filename: "notes.txt",
        attachmentId: "attachment-1",
        body: { data: webSafe("attachment text must not become the message body") },
      },
      {
        mimeType: "text/plain",
        body: { attachmentId: "body-attachment-1", data: webSafe("ATTACHED SECRET") },
      },
      {
        mimeType: "text/plain",
        headers: [{ name: "Content-Disposition", value: 'inline; filename="secret.txt"' }],
        body: { data: webSafe("INLINE SECRET") },
      },
      {
        mimeType: "text/plain",
        headers: [{ name: "Content-Disposition", value: "inline; filename*=UTF-8''secret%20extended.txt" }],
        body: { data: webSafe("RFC2231 SECRET") },
      },
      {
        mimeType: "text/plain",
        headers: [{
          name: "Content-Disposition",
          value: "attachment; filename*0*=UTF-8''continuation-; filename*1*=name%2Etxt",
        }],
        body: { data: webSafe("CONTINUATION SECRET") },
      },
      {
        mimeType: "multipart/alternative",
        parts: [{ mimeType: "text/plain", body: { data: webSafe("Plain body") } }],
      },
      {
        mimeType: "application/pdf",
        filename: "evidence.pdf",
        body: { data: webSafe("attachment payload must not be returned") },
      },
    ],
  });

  assert.equal(api.normalizeMessage(htmlOnly).body_chunks.join(""), "Hello world\nagain & more \uD83D\uDE42");
  const normalized = api.normalizeMessage(multipart);
  assert.deepEqual(Array.from(normalized.body_chunks), ["Plain body"]);
  assert.deepEqual(Array.from(normalized.attachment_names), [
    "notes.txt", "secret.txt", "secret extended.txt", "continuation-name.txt", "evidence.pdf",
  ]);
  assert.equal(normalized.body_chunks.join("").includes("attachment payload"), false);
  assert.equal(normalized.body_chunks.join("").includes("attachment text"), false);
  assert.equal(normalized.body_chunks.join("").includes("ATTACHED SECRET"), false);
  assert.equal(normalized.body_chunks.join("").includes("INLINE SECRET"), false);
  assert.equal(normalized.body_chunks.join("").includes("RFC2231 SECRET"), false);
  assert.equal(normalized.body_chunks.join("").includes("CONTINUATION SECRET"), false);
});

test("long Unicode bodies are chunked by UTF-8 byte budget without corrupting code points", () => {
  const { api, calls } = loadBridge();
  const body = "🙂".repeat(30_000) + " fin";
  const chunks = api.splitUtf8(body);

  assert.ok(chunks.length > 1);
  assert.equal(chunks.join(""), body);
  for (const chunk of chunks) {
    assert.ok(Buffer.byteLength(chunk, "utf8") <= 96 * 1024);
  }
  assert.equal(calls.blob, 0);
  const mixed = "\uD83D\uDE42\uD800";
  assert.equal(api.splitUtf8(mixed).join(""), mixed);
  assert.equal(Buffer.byteLength(mixed, "utf8"), 7);
});

test("thread pages advertise stable manifests and complete bodies with bytes and hashes", () => {
  const body = "café 🙂";
  const messages = [
    rawMessage({ id: "one", internalDate: "2026-08-04T10:00:00Z", body }),
    rawMessage({ id: "two", internalDate: "2026-08-04T10:01:00Z", body: "two" }),
  ];
  const { api } = loadBridge({ threads: { "thread-a": { messages } } });
  const snapshot = "2026-08-04T11:00:00Z";
  const first = api.readThreadPage({ thread_id: "thread-a", snapshot_before: snapshot });
  const segment = bodySegment(first);

  assert.equal(first.manifest_sha256, api.sha256Hex("one\ntwo"));
  assert.equal(segment.body_bytes, Buffer.byteLength(body, "utf8"));
  assert.equal(segment.body_sha256, createHash("sha256").update(body, "utf8").digest("hex"));
  const repeat = api.readThreadPage({ thread_id: "thread-a", snapshot_before: snapshot });
  assert.equal(repeat.manifest_sha256, first.manifest_sha256);
});

test("read_thread_page returns at most four segments and advances a server-issued cursor", () => {
  const messages = Array.from({ length: 5 }, (_, index) => rawMessage({
    id: `message-${index}`,
    internalDate: `2026-08-04T10:0${index}:00Z`,
    body: `body-${index}`,
  }));
  const { api } = loadBridge({ threads: { "thread-a": { messages } } });
  const snapshot = "2026-08-04T11:00:00Z";
  const first = api.readThreadPage({ thread_id: "thread-a", snapshot_before: snapshot });
  const second = api.readThreadPage({ thread_id: "thread-a", snapshot_before: snapshot, cursor: first.next_cursor });

  assert.equal(first.segments.length, 4);
  assert.equal(first.messages_completed, 4);
  assert.equal(first.complete, false);
  assert.ok(first.next_cursor);
  assert.equal(second.segments.length, 1);
  assert.equal(second.segments[0].message_id, "message-4");
  assert.equal(second.complete, true);
  assert.equal(second.messages_completed, 5);
  assert.equal(second.next_cursor, null);
});

test("malformed Gmail responses, messages, and MIME data fail closed with sanitized errors", () => {
  const snapshot = "2026-08-04T11:00:00Z";
  const nullThread = loadBridge({ threads: { "thread-null": null } });
  assert.throws(
    () => nullThread.api.readThreadPage({ thread_id: "thread-null", snapshot_before: snapshot }),
    /INVALID_THREAD_RESPONSE/,
  );
  const malformedMessage = loadBridge({
    threads: {
      "thread-malformed": {
        messages: [{ id: "missing-payload", threadId: "thread-malformed", internalDate: "1785841200000" }],
      },
    },
  });
  assert.throws(
    () => malformedMessage.api.readThreadPage({ thread_id: "thread-malformed", snapshot_before: snapshot }),
    /INVALID_MESSAGE/,
  );
  const malformedMessageResponse = JSON.parse(malformedMessage.context.doGet({
    parameter: { action: "read_thread_page", thread_id: "thread-malformed", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(malformedMessageResponse, { success: false, error: "APP_ERROR" });

  const decodeFailure = loadBridge({
    threads: {
      "thread-decode": {
        messages: [{
          id: "bad-body",
          threadId: "thread-decode",
          internalDate: "1785841200000",
          payload: { mimeType: "text/plain", body: { data: "%%%" }, headers: [] },
        }],
      },
    },
  });
  assert.throws(
    () => decodeFailure.api.readThreadPage({ thread_id: "thread-decode", snapshot_before: snapshot }),
    /INVALID_BODY_ENCODING/,
  );
  const decodeResponse = JSON.parse(decodeFailure.context.doGet({
    parameter: { action: "read_thread_page", thread_id: "thread-decode", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(decodeResponse, { success: false, error: "APP_ERROR" });

  const malformedList = loadBridge({ listPages: { first: null } });
  const listResponse = JSON.parse(malformedList.context.doGet({
    parameter: { action: "list_threads", q: "INC7445969", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(listResponse, { success: false, error: "APP_ERROR" });

  const malformedListShape = loadBridge({ listPages: { first: {} } });
  const malformedListShapeResponse = JSON.parse(malformedListShape.context.doGet({
    parameter: { action: "list_threads", q: "INC7445969", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(malformedListShapeResponse, { success: false, error: "APP_ERROR" });

  const malformedParts = loadBridge({
    threads: {
      "thread-parts": {
        messages: [{
          id: "bad-parts",
          threadId: "thread-parts",
          internalDate: "1785841200000",
          payload: { mimeType: "multipart/mixed", parts: { malformed: true }, headers: [] },
        }],
      },
    },
  });
  assert.throws(
    () => malformedParts.api.readThreadPage({ thread_id: "thread-parts", snapshot_before: snapshot }),
    /INVALID_MIME_STRUCTURE/,
  );
  const malformedPartsResponse = JSON.parse(malformedParts.context.doGet({
    parameter: { action: "read_thread_page", thread_id: "thread-parts", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(malformedPartsResponse, { success: false, error: "APP_ERROR" });

  const malformedToken = loadBridge({ listPages: { first: { threads: [], nextPageToken: 42 } } });
  const malformedTokenResponse = JSON.parse(malformedToken.context.doGet({
    parameter: { action: "list_threads", q: "INC7445969", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(malformedTokenResponse, { success: false, error: "APP_ERROR" });

  const oversizedParts = [
    { mimeType: "text/plain", body: { data: webSafe("body") } },
    ...Array.from({ length: 70 }, (_, index) => ({
      mimeType: "application/octet-stream",
      filename: `attachment-${index}-${"x".repeat(100_000)}`,
      body: {},
    })),
  ];
  const oversized = loadBridge({
    threads: {
      "thread-oversized": {
        messages: [rawMessage({ id: "oversized", threadId: "thread-oversized", mimeType: "multipart/mixed", parts: oversizedParts })],
      },
    },
  });
  assert.throws(
    () => oversized.api.readThreadPage({ thread_id: "thread-oversized", snapshot_before: snapshot }),
    /RESPONSE_TOO_LARGE/,
  );
  const oversizedResponse = JSON.parse(oversized.context.doGet({
    parameter: { action: "read_thread_page", thread_id: "thread-oversized", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(oversizedResponse, { success: false, error: "RESPONSE_TOO_LARGE" });
});

test("legacy actions retain their search, read, and send contract", () => {
  const last = legacyMessage({ id: "newer", subject: "Newest", plain: "Newest preview" });
  const first = legacyMessage({ id: "older", subject: "Older" });
  const read = legacyMessage({ id: "readable", html: "<p>Read body</p>", plain: "Read body" });
  const { context, calls } = loadBridge({
    legacyThreads: [{ getId: () => "legacy-thread", getMessages: () => [first, last] }],
    legacyMessages: { readable: read },
  });

  const search = JSON.parse(context.doGet({ parameter: { action: "search", q: "1-23508794022" } }).data);
  const readResponse = JSON.parse(context.doGet({ parameter: { action: "read", id: "readable" } }).data);
  const missing = JSON.parse(context.doGet({ parameter: { action: "read" } }).data);
  const notFound = JSON.parse(context.doGet({ parameter: { action: "read", id: "missing" } }).data);
  const sent = JSON.parse(context.doGet({ parameter: { action: "send", to: "to@example.com", subject: "Subject", body: "Body" } }).data);
  const invalidSend = JSON.parse(context.doGet({ parameter: { action: "send", to: "to@example.com", subject: "", body: "Body" } }).data);

  assert.deepEqual(calls.search, [{ query: "1-23508794022", start: 0, limit: 10 }]);
  assert.equal(search.success, true);
  assert.deepEqual(search.messages, [{
    id: "newer", threadId: "legacy-thread", subject: "Newest", from: "sender@example.com",
    date: "2026-08-04T10:00:00.000Z", snippet: "Newest preview",
  }]);
  assert.equal(readResponse.body, "<p>Read body</p>");
  assert.equal(readResponse.plainBody, "Read body");
  assert.equal(missing.success, false);
  assert.equal(missing.error, "Missing message ID");
  assert.equal(notFound.error, "Message not found");
  assert.equal(sent.success, true);
  assert.equal(invalidSend.error, "Missing required fields");
  assert.deepEqual(calls.sent, [{ to: "to@example.com", subject: "Subject", body: "Body" }]);
});
