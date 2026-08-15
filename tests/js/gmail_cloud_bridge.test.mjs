import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { loadBridge, rawMessage, legacyMessage, webSafe } from "./gmail_cloud_bridge_harness.mjs";

const MIB = 1024 * 1024;
const INNER_BUDGET = 6 * MIB - 4 * 1024;
const WIRE_BUDGET = 8 * MIB - 4 * 1024;
const MAX_SEGMENTS = 32;

function bodySegment(message) {
  return message.segments[0];
}

function collectAllPages(api, threadId, snapshot) {
  const pages = [];
  let cursor = "";
  let guard = 0;
  do {
    guard += 1;
    assert.ok(guard <= 100, "cursor chain must terminate");
    const page = api.readThreadPage({
      thread_id: threadId,
      snapshot_before: snapshot,
      ...(cursor ? { cursor } : {}),
    });
    pages.push(page);
    cursor = page.next_cursor || "";
  } while (cursor);
  return pages;
}

function reassemble(pages) {
  const chunksById = new Map();
  const metaById = new Map();
  for (const page of pages) {
    for (const segment of page.segments) {
      const chunks = chunksById.get(segment.message_id) || [];
      chunks[segment.chunk_index] = segment.body_chunk;
      chunksById.set(segment.message_id, chunks);
      metaById.set(segment.message_id, segment);
    }
  }
  const bodies = new Map();
  for (const [id, chunks] of chunksById) {
    for (let index = 0; index < chunks.length; index += 1) {
      assert.ok(chunks[index] !== undefined, `chunk ${index} of ${id} must be present`);
    }
    bodies.set(id, chunks.join(""));
  }
  return { bodies, metaById };
}

function replayNextFit(orderedSegments) {
  // Mirror of emitPageSegments_ packing: sequential next-fit under the segment
  // count cap and both byte budgets.
  const boundaries = [];
  let count = 0;
  let innerUsed = 0;
  let wireUsed = 0;
  for (const sizes of orderedSegments) {
    if (count === MAX_SEGMENTS || innerUsed + sizes.inner > INNER_BUDGET || wireUsed + sizes.wire > WIRE_BUDGET) {
      boundaries.push(count);
      count = 0;
      innerUsed = 0;
      wireUsed = 0;
    }
    count += 1;
    innerUsed += sizes.inner;
    wireUsed += sizes.wire;
  }
  if (count > 0) boundaries.push(count);
  return boundaries;
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
  const manifest = "a".repeat(64);
  assert.equal(typeof api.bridgeVersion, "number");
  const cursor = api.encodeCursor({
    version: api.bridgeVersion,
    thread_id: "thread-a",
    snapshot_before: snapshot,
    manifest_sha256: manifest,
    message_index: 2,
    chunk_index: 3,
  });

  assert.deepEqual(api.decodeCursor(cursor, "thread-a", snapshot, manifest), {
    version: api.bridgeVersion,
    thread_id: "thread-a",
    snapshot_before: snapshot,
    manifest_sha256: manifest,
    message_index: 2,
    chunk_index: 3,
  });
  assert.match(cursor, /^[A-Za-z0-9_-]+$/);
  assert.throws(() => api.decodeCursor(cursor, "thread-b", snapshot), /INVALID_CURSOR/);
  assert.throws(() => api.decodeCursor(cursor, "thread-a", "2026-08-04T10:15:31.000Z"), /INVALID_CURSOR/);
  assert.throws(() => api.decodeCursor(cursor, "thread-a", snapshot, "b".repeat(64)), /INVALID_CURSOR/);
});

test("read_thread_page uses the same inclusive second bucket as list_threads", () => {
  const snapshot = "2026-08-04T10:15:30.250Z";
  const boundaryMessage = rawMessage({
    id: "same-second",
    threadId: "thread-boundary",
    internalDate: "2026-08-04T10:15:30.500Z",
    body: "within Gmail's second-resolution bucket",
  });
  const { api } = loadBridge({ threads: { "thread-boundary": { messages: [boundaryMessage] } } });

  const response = api.readThreadPage({ thread_id: "thread-boundary", snapshot_before: snapshot });

  assert.equal(api.snapshotCutoffMillis(snapshot), Date.parse("2026-08-04T10:15:30.999Z"));
  assert.equal(response.message_count, 1);
  assert.deepEqual(Array.from(response.segments, (segment) => segment.message_id), ["same-second"]);
});

test("read_thread_page filters after-snapshot messages and orders retained messages", () => {
  const snapshot = "2026-08-04T10:15:30.000Z";
  const early = rawMessage({
    id: "early",
    threadId: "thread-a",
    internalDate: "2026-08-04T10:14:00Z",
    body: "early",
    headers: {
      From: "sender@example.com",
      TO: '\"Doe, Jane\" <first@example.com>, second@example.com',
      Cc: "copy@example.com",
      SUBJECT: "Case update",
    },
  });
  const tied = rawMessage({ id: "a-tie", threadId: "thread-a", internalDate: "2026-08-04T10:15:00Z", body: "tie" });
  const tiedLaterId = rawMessage({ id: "z-tie", threadId: "thread-a", internalDate: "2026-08-04T10:15:00Z", body: "tie" });
  const late = rawMessage({ id: "late", threadId: "thread-a", internalDate: "2026-08-04T10:16:00Z", body: "late" });
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
        mimeType: "text/plain",
        headers: [{
          name: "Content-Disposition",
          value: "attachment; filename*0*=UTF-8''caf%C3; filename*1*=%A9.txt",
        }],
        body: { data: webSafe("SPLIT UTF8 SECRET") },
      },
      {
        mimeType: "text/plain",
        headers: [{
          name: "Content-Disposition",
          value: "attachment; filename*=Shift_JIS''%83%65%83%58%83%67.txt",
        }],
        body: { data: webSafe("SHIFT SECRET") },
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
    "notes.txt", "secret.txt", "secret extended.txt", "continuation-name.txt", "café.txt", "テスト.txt", "evidence.pdf",
  ]);
  assert.equal(normalized.body_chunks.join("").includes("attachment payload"), false);
  assert.equal(normalized.body_chunks.join("").includes("attachment text"), false);
  assert.equal(normalized.body_chunks.join("").includes("ATTACHED SECRET"), false);
  assert.equal(normalized.body_chunks.join("").includes("INLINE SECRET"), false);
  assert.equal(normalized.body_chunks.join("").includes("RFC2231 SECRET"), false);
  assert.equal(normalized.body_chunks.join("").includes("CONTINUATION SECRET"), false);
  assert.equal(normalized.body_chunks.join("").includes("SPLIT UTF8 SECRET"), false);
  assert.equal(normalized.body_chunks.join("").includes("SHIFT SECRET"), false);
});

test("normalization retrieves externalized text MIME bodies without including attachments", () => {
  const message = rawMessage({
    id: "externalized-message",
    mimeType: "multipart/alternative",
    parts: [],
  });
  message.payload.parts = [
    { mimeType: "text/plain", body: { attachmentId: "body-part" } },
    { mimeType: "image/png", filename: "inline.png", body: { attachmentId: "image-part" } },
  ];
  const { api, calls } = loadBridge({
    attachments: {
      "externalized-message:body-part": { data: webSafe("Externalized message body") },
      "externalized-message:image-part": { data: webSafe("image bytes") },
    },
  });

  const normalized = api.normalizeMessage(message, "thread-1");

  assert.deepEqual(Array.from(normalized.body_chunks), ["Externalized message body"]);
  assert.equal(normalized.body_bytes, Buffer.byteLength("Externalized message body", "utf8"));
  assert.deepEqual(Array.from(normalized.attachment_names), ["inline.png"]);
  assert.deepEqual(calls.attachments, [{
    userId: "me",
    messageId: "externalized-message",
    attachmentId: "body-part",
  }]);
});

test("normalization retrieves text MIME bodies with empty inline data and an attachment id", () => {
  const message = rawMessage({
    id: "externalized-empty-data",
    mimeType: "multipart/alternative",
    parts: [],
  });
  message.payload.parts = [
    { mimeType: "text/plain", body: { data: "", attachmentId: "body-part" } },
  ];
  const { api, calls } = loadBridge({
    attachments: {
      "externalized-empty-data:body-part": { data: webSafe("Body stored behind attachment id") },
    },
  });

  const normalized = api.normalizeMessage(message, "thread-1");

  assert.deepEqual(Array.from(normalized.body_chunks), ["Body stored behind attachment id"]);
  assert.equal(normalized.body_bytes, Buffer.byteLength("Body stored behind attachment id", "utf8"));
  assert.deepEqual(calls.attachments, [{
    userId: "me",
    messageId: "externalized-empty-data",
    attachmentId: "body-part",
  }]);
});

test("normalization accepts Apps Script byte-array MIME body data", () => {
  const message = rawMessage({
    id: "byte-array-body",
    mimeType: "text/html",
    body: "ignored",
  });
  message.payload.body = { data: Array.from(Buffer.from("<p>Byte array body</p>", "utf8")) };

  const { api } = loadBridge();
  const normalized = api.normalizeMessage(message, "thread-1");

  assert.deepEqual(Array.from(normalized.body_chunks), ["Byte array body"]);
  assert.equal(normalized.body_bytes, Buffer.byteLength("Byte array body", "utf8"));
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

test("segment wire estimation counts serialized bytes plus quote and backslash surcharge", () => {
  const { api } = loadBridge();
  const adversarial = 'quote " and \\ backslash \n newline é 🙂 end';
  const piece = JSON.stringify({ body_chunk: adversarial });
  const manualInner = Buffer.byteLength(piece, "utf8");
  const manualSurcharge = (piece.match(/["\\]/g) || []).length;

  const sizes = api.segmentWireBytes({ body_chunk: adversarial });

  assert.equal(sizes.inner, manualInner);
  assert.equal(sizes.wire, manualInner + manualSurcharge);
  assert.ok(sizes.wire > sizes.inner);
  const allQuotes = '"'.repeat(1000);
  const quoteSizes = api.segmentWireBytes({ body_chunk: allQuotes });
  const quotePiece = JSON.stringify({ body_chunk: allQuotes });
  assert.equal(quoteSizes.inner, Buffer.byteLength(quotePiece, "utf8"));
  assert.equal(quoteSizes.wire, Buffer.byteLength(quotePiece, "utf8") + (quotePiece.match(/["\\]/g) || []).length);
  assert.ok(quoteSizes.wire > quoteSizes.inner * 1.9, "all-quote content must approach the 2x bound");
});

test("thread pages advertise stable manifests and complete bodies with bytes and hashes", () => {
  const body = "café 🙂";
  const messages = [
    rawMessage({ id: "one", threadId: "thread-a", internalDate: "2026-08-04T10:00:00Z", body }),
    rawMessage({ id: "two", threadId: "thread-a", internalDate: "2026-08-04T10:01:00Z", body: "two" }),
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

test("read_thread_page emits every segment of a small thread on one page", () => {
  const messages = Array.from({ length: 5 }, (_, index) => rawMessage({
    id: `message-${index}`,
    threadId: "thread-a",
    internalDate: `2026-08-04T10:0${index}:00Z`,
    body: `body-${index}`,
  }));
  const { api } = loadBridge({ threads: { "thread-a": { messages } } });
  const snapshot = "2026-08-04T11:00:00Z";
  const first = api.readThreadPage({ thread_id: "thread-a", snapshot_before: snapshot });

  assert.equal(first.segments.length, 5);
  assert.equal(first.messages_completed, 5);
  assert.equal(first.complete, true);
  assert.equal(first.next_cursor, null);
  assert.deepEqual(Array.from(first.segments, (segment) => segment.message_id), [
    "message-0", "message-1", "message-2", "message-3", "message-4",
  ]);
});

test("read_thread_page stops at the 32-segment page capacity and resumes via cursor", () => {
  const messages = Array.from({ length: 40 }, (_, index) => rawMessage({
    id: `cap-${String(index).padStart(2, "0")}`,
    threadId: "thread-cap",
    internalDate: new Date(Date.parse("2026-08-04T10:00:00Z") + index * 1000).toISOString(),
    body: `body-${index}`,
  }));
  const { api } = loadBridge({ threads: { "thread-cap": { messages } } });
  const snapshot = "2026-08-04T11:00:00Z";

  const first = api.readThreadPage({ thread_id: "thread-cap", snapshot_before: snapshot });
  assert.equal(first.segments.length, 32);
  assert.equal(first.messages_completed, 32);
  assert.equal(first.complete, false);
  assert.ok(first.next_cursor);

  const second = api.readThreadPage({
    thread_id: "thread-cap",
    snapshot_before: snapshot,
    cursor: first.next_cursor,
  });
  assert.equal(second.segments.length, 8);
  assert.equal(second.messages_completed, 40);
  assert.equal(second.complete, true);
  assert.equal(second.next_cursor, null);
  assert.equal(second.manifest_sha256, first.manifest_sha256);
  assert.equal(second.message_count, first.message_count);
  assert.equal(second.segments[0].message_id, "cap-32");
});

test("read_thread_page resumes inside a multi-chunk message cut at the page boundary", () => {
  const hugeBody = "x".repeat(Math.floor(2.5 * 96 * 1024));
  const messages = [
    ...Array.from({ length: 30 }, (_, index) => rawMessage({
      id: `small-${String(index).padStart(2, "0")}`,
      threadId: "thread-resume",
      internalDate: new Date(Date.parse("2026-08-04T10:00:00Z") + index * 1000).toISOString(),
      body: `small-${index}`,
    })),
    rawMessage({
      id: "huge",
      threadId: "thread-resume",
      internalDate: "2026-08-04T10:30:00Z",
      body: hugeBody,
    }),
  ];
  const { api } = loadBridge({ threads: { "thread-resume": { messages } } });
  const snapshot = "2026-08-04T11:00:00Z";

  const first = api.readThreadPage({ thread_id: "thread-resume", snapshot_before: snapshot });
  assert.equal(first.segments.length, 32);
  assert.equal(first.messages_completed, 30);
  assert.equal(first.complete, false);
  const hugeSegments = first.segments.filter((segment) => segment.message_id === "huge");
  assert.equal(hugeSegments.length, 2);
  assert.equal(hugeSegments[1].chunk_index, 1);
  assert.equal(hugeSegments[0].chunk_count, 3);

  const pages = collectAllPages(api, "thread-resume", snapshot);
  assert.deepEqual(pages.map((page) => page.segments.length), [32, 1]);
  const { bodies, metaById } = reassemble(pages);
  assert.equal(bodies.size, 31);
  assert.equal(bodies.get("huge"), hugeBody);
  const hugeMeta = metaById.get("huge");
  assert.equal(hugeMeta.body_bytes, Buffer.byteLength(hugeBody, "utf8"));
  assert.equal(hugeMeta.body_sha256, createHash("sha256").update(hugeBody, "utf8").digest("hex"));
});

test("quote-dense threads paginate by the wire budget and reassemble byte-exact", () => {
  const denseBody = '"'.repeat(96 * 1024);
  const messages = Array.from({ length: 100 }, (_, index) => rawMessage({
    id: `adv-${String(index).padStart(3, "0")}`,
    threadId: "thread-adv",
    internalDate: new Date(Date.parse("2026-08-04T10:00:00Z") + index * 1000).toISOString(),
    body: denseBody,
  }));
  const { api } = loadBridge({ threads: { "thread-adv": { messages } } });
  const snapshot = "2026-08-04T11:00:00Z";

  const pages = collectAllPages(api, "thread-adv", snapshot);
  assert.ok(pages.length >= 4, `wire-bound paging expected, got ${pages.length} pages`);
  for (const page of pages) {
    assert.ok(page.segments.length <= 32);
    let innerUsed = 0;
    let wireUsed = 0;
    for (const segment of page.segments) {
      const sizes = api.segmentWireBytes(segment);
      innerUsed += sizes.inner;
      wireUsed += sizes.wire;
    }
    assert.ok(innerUsed <= INNER_BUDGET, `inner ${innerUsed} exceeds budget`);
    assert.ok(wireUsed <= WIRE_BUDGET, `wire ${wireUsed} exceeds budget`);
  }
  const firstPage = pages[0];
  assert.ok(firstPage.segments.length < 32, "first page must be wire-bound, not count-bound");

  const orderedSizes = pages.flatMap((page) => page.segments.map((segment) => api.segmentWireBytes(segment)));
  assert.deepEqual(replayNextFit(orderedSizes), pages.map((page) => page.segments.length));

  const { bodies } = reassemble(pages);
  assert.equal(bodies.size, 100);
  for (const body of bodies.values()) {
    assert.equal(body, denseBody);
  }
});

test("a segment between both budgets is emitted (v3 pass-domain regression)", () => {
  // Unbounded metadata (payload.filename) of nearly-all quotes: raw length L
  // serializes to inner ≈ 2L and wire ≈ 4L. L ≈ 1.6 MiB lands the segment at
  // inner ≈ 3.2 MiB / wire ≈ 6.4 MiB: above the 6 MiB wire mark rev 3 would
  // have rejected, yet below both actual limits, so v3 collected it and v4
  // must keep collecting it.
  const quoteName = '"'.repeat(Math.floor(1.6 * MIB));
  const message = rawMessage({
    id: "pass-domain",
    threadId: "thread-pass",
    internalDate: "2026-08-04T10:00:00Z",
    filename: quoteName,
    body: "small body",
  });
  const { api } = loadBridge({ threads: { "thread-pass": { messages: [message] } } });
  const snapshot = "2026-08-04T11:00:00Z";

  const page = api.readThreadPage({ thread_id: "thread-pass", snapshot_before: snapshot });

  assert.equal(page.segments.length, 1);
  assert.equal(page.complete, true);
  const sizes = api.segmentWireBytes(page.segments[0]);
  assert.ok(sizes.inner > 3.0 * MIB && sizes.inner < 3.5 * MIB, `inner ${sizes.inner} out of range`);
  assert.ok(sizes.wire > 6.0 * MIB && sizes.wire < 7.0 * MIB, `wire ${sizes.wire} out of range`);
});

test("a first segment over either real budget fails with RESPONSE_TOO_LARGE", () => {
  // Same construction scaled so the serialized segment sits at inner ≈ 4.8 MiB
  // (within the inner track) but wire ≈ 9.6 MiB (over the wire track).
  const quoteName = '"'.repeat(Math.floor(2.4 * MIB));
  const message = rawMessage({
    id: "over-budget",
    threadId: "thread-over",
    internalDate: "2026-08-04T10:00:00Z",
    filename: quoteName,
    body: "small body",
  });
  const { api, context } = loadBridge({ threads: { "thread-over": { messages: [message] } } });
  const snapshot = "2026-08-04T11:00:00Z";

  const normalized = api.normalizeMessage(message, "thread-over");
  const projected = api.segmentWireBytes({
    message_id: normalized.message_id,
    thread_id: normalized.thread_id,
    internal_date: normalized.internal_date,
    from: normalized.from,
    to: normalized.to,
    cc: normalized.cc,
    subject: normalized.subject,
    body_chunk: normalized.body_chunks[0],
    chunk_index: 0,
    chunk_count: normalized.body_chunks.length,
    body_bytes: normalized.body_bytes,
    body_sha256: normalized.body_sha256,
    attachment_names: normalized.attachment_names,
  });
  assert.ok(projected.inner <= INNER_BUDGET, "rejection must come from the wire track, not inner");
  assert.ok(projected.wire > WIRE_BUDGET, "wire must exceed the effective budget");

  assert.throws(
    () => api.readThreadPage({ thread_id: "thread-over", snapshot_before: snapshot }),
    /RESPONSE_TOO_LARGE/,
  );
  const errorResponse = JSON.parse(context.doGet({
    parameter: { action: "read_thread_page", thread_id: "thread-over", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(errorResponse, { success: false, error: "RESPONSE_TOO_LARGE" });
});

test("unknown helper failures keep their sanitized wrapper codes, never APP_ERROR", () => {
  const snapshot = "2026-08-04T11:00:00Z";
  const messages = [
    rawMessage({ id: "m1", threadId: "thread-a", internalDate: "2026-08-04T10:00:00Z", body: "one" }),
    rawMessage({ id: "m2", threadId: "thread-a", internalDate: "2026-08-04T10:01:00Z", body: "two" }),
  ];

  const manifestFailure = loadBridge({ threads: { "thread-a": { messages } } });
  manifestFailure.context.sha256Hex_ = () => {
    throw new Error("digest exploded");
  };
  assert.throws(
    () => manifestFailure.api.readThreadPage({ thread_id: "thread-a", snapshot_before: snapshot }),
    /MANIFEST_BUILD_FAILED/,
  );

  const emissionFailure = loadBridge({ threads: { "thread-a": { messages } } });
  emissionFailure.context.segmentWireBytes_ = () => {
    throw new Error("sizing exploded");
  };
  assert.throws(
    () => emissionFailure.api.readThreadPage({ thread_id: "thread-a", snapshot_before: snapshot }),
    /SEGMENT_EMISSION_FAILED/,
  );

  const sortFailure = loadBridge({ threads: { "thread-a": { messages } } });
  sortFailure.context.compareMessageStubs_ = () => {
    throw new Error("sort exploded");
  };
  assert.throws(
    () => sortFailure.api.readThreadPage({ thread_id: "thread-a", snapshot_before: snapshot }),
    /THREAD_SORT_FAILED/,
  );

  const lazySortFailure = loadBridge({
    threads: {
      "thread-lazy": {
        messages: messages.map((message) => ({
          id: message.id,
          threadId: "thread-lazy",
          internalDate: message.internalDate,
        })),
      },
    },
    threadGetFailures: { "thread-lazy:full": "response too large" },
    apiMessages: Object.fromEntries(
      messages.map((message) => [message.id, { ...message, threadId: "thread-lazy" }]),
    ),
  });
  lazySortFailure.context.compareMessageStubs_ = () => {
    throw new Error("sort exploded");
  };
  assert.throws(
    () => lazySortFailure.api.readThreadPage({ thread_id: "thread-lazy", snapshot_before: snapshot }),
    /THREAD_SORT_FAILED/,
  );
});

test("read_thread_page falls back to per-message full fetch when a full thread fetch fails", () => {
  const snapshot = "2026-08-04T11:00:00Z";
  const message = rawMessage({
    id: "large-message",
    threadId: "thread-large",
    body: "Recovered from per-message fetch",
  });
  const { api, calls } = loadBridge({
    threads: {
      "thread-large": {
        id: "thread-large",
        messages: [{
          id: "large-message",
          threadId: "thread-large",
          internalDate: message.internalDate,
        }],
      },
    },
    threadGetFailures: { "thread-large:full": "response too large" },
    apiMessages: { "large-message": message },
  });

  const page = api.readThreadPage({ thread_id: "thread-large", snapshot_before: snapshot });

  assert.equal(page.complete, true);
  assert.equal(page.message_count, 1);
  assert.equal(page.segments[0].body_chunk, "Recovered from per-message fetch");
  assert.deepEqual(calls.get, [
    { userId: "me", threadId: "thread-large", options: { format: "full" } },
    { userId: "me", threadId: "thread-large", options: { format: "minimal" } },
  ]);
  assert.deepEqual(calls.messageGet, [
    { userId: "me", messageId: "large-message", options: { format: "full" } },
  ]);
});

test("large-thread fallback fetches only messages required by each cursor page", () => {
  const snapshot = "2026-08-04T11:00:00Z";
  const messages = Array.from({ length: 34 }, (_, index) => rawMessage({
    id: `lazy-${String(index).padStart(2, "0")}`,
    threadId: "thread-lazy",
    internalDate: index === 33 ? "2026-08-04T12:00:00.000Z" : new Date(Date.parse("2026-08-04T10:00:00Z") + index * 1000).toISOString(),
    body: `lazy body ${index}`,
  }));
  const apiMessages = Object.fromEntries(messages.map((message) => [message.id, message]));
  const { api, calls } = loadBridge({
    threads: {
      "thread-lazy": {
        id: "thread-lazy",
        messages: messages.map((message) => ({
          id: message.id,
          threadId: message.threadId,
          internalDate: message.internalDate,
        })),
      },
    },
    threadGetFailures: { "thread-lazy:full": "response too large" },
    apiMessages,
  });

  const first = api.readThreadPage({ thread_id: "thread-lazy", snapshot_before: snapshot });
  assert.equal(first.message_count, 33);
  assert.equal(first.segments.length, 32);
  assert.equal(first.messages_completed, 32);
  assert.equal(first.complete, false);
  assert.deepEqual(
    calls.messageGet.map((call) => call.messageId),
    Array.from({ length: 32 }, (_, index) => `lazy-${String(index).padStart(2, "0")}`),
  );

  const second = api.readThreadPage({
    thread_id: "thread-lazy",
    snapshot_before: snapshot,
    cursor: first.next_cursor,
  });
  assert.equal(second.manifest_sha256, first.manifest_sha256);
  assert.equal(second.message_count, 33);
  assert.equal(second.segments.length, 1);
  assert.equal(second.messages_completed, 33);
  assert.equal(second.complete, true);
  assert.deepEqual(calls.messageGet.map((call) => call.messageId), [
    ...Array.from({ length: 32 }, (_, index) => `lazy-${String(index).padStart(2, "0")}`),
    "lazy-32",
  ]);
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
  assert.deepEqual(malformedMessageResponse, { success: false, error: "INVALID_MESSAGE" });

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
  assert.deepEqual(decodeResponse, { success: false, error: "INVALID_BODY_ENCODING" });

  const malformedList = loadBridge({ listPages: { first: null } });
  const listResponse = JSON.parse(malformedList.context.doGet({
    parameter: { action: "list_threads", q: "INC7445969", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(listResponse, { success: false, error: "INVALID_THREAD_RESPONSE" });

  const malformedListShape = loadBridge({ listPages: { first: {} } });
  const malformedListShapeResponse = JSON.parse(malformedListShape.context.doGet({
    parameter: { action: "list_threads", q: "INC7445969", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(malformedListShapeResponse, { success: false, error: "INVALID_THREAD_RESPONSE" });

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
  assert.deepEqual(malformedPartsResponse, { success: false, error: "INVALID_MIME_STRUCTURE" });

  const malformedToken = loadBridge({ listPages: { first: { threads: [], nextPageToken: 42 } } });
  const malformedTokenResponse = JSON.parse(malformedToken.context.doGet({
    parameter: { action: "list_threads", q: "INC7445969", snapshot_before: snapshot },
  }).data);
  assert.deepEqual(malformedTokenResponse, { success: false, error: "INVALID_THREAD_RESPONSE" });

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
  JSON.parse(context.doGet({ parameter: { action: "search", q: "1-23508794022", max_results: "3" } }).data);
  const readResponse = JSON.parse(context.doGet({ parameter: { action: "read", id: "readable" } }).data);
  const missing = JSON.parse(context.doGet({ parameter: { action: "read" } }).data);
  const notFound = JSON.parse(context.doGet({ parameter: { action: "read", id: "missing" } }).data);
  const sent = JSON.parse(context.doGet({ parameter: { action: "send", to: "to@example.com", subject: "Subject", body: "Body" } }).data);
  const invalidSend = JSON.parse(context.doGet({ parameter: { action: "send", to: "to@example.com", subject: "", body: "Body" } }).data);

  assert.deepEqual(calls.search, [
    { query: "1-23508794022", start: 0, limit: 10 },
    { query: "1-23508794022", start: 0, limit: 3 },
  ]);
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
