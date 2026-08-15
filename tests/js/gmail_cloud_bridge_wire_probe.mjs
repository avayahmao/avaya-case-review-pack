// Wire probe: drives the REAL doGet endpoint of GmailMcpBridge.gs against
// deterministic fixtures and emits each response page's raw JSON text with a
// length-prefixed framing on stdout, so the Python driver can feed the exact
// transport bytes through the broker's encode_response and assert the
// end-to-end frame contract. No node:test usage, no diagnostics on stdout.
import { loadBridge, rawMessage } from "./gmail_cloud_bridge_harness.mjs";

const MIB = 1024 * 1024;
const SNAPSHOT = "2026-08-04T11:00:00Z";

function writeRecord(name, text) {
  const payload = Buffer.from(text, "utf8");
  process.stdout.write(`${name} ${payload.length}\n`);
  process.stdout.write(payload);
  process.stdout.write("\n");
}

function doGetPage(context, threadId, cursor) {
  const parameter = { action: "read_thread_page", thread_id: threadId, snapshot_before: SNAPSHOT };
  if (cursor) parameter.cursor = cursor;
  const output = context.doGet({ parameter });
  return { text: output.data, parsed: JSON.parse(output.data) };
}

function runThreadFixture(name, context, threadId, maxPages = 64) {
  let cursor = "";
  for (let page = 0; page < maxPages; page += 1) {
    const { text, parsed } = doGetPage(context, threadId, cursor);
    writeRecord(name, text);
    if (!parsed.success) return;
    if (parsed.complete) {
      if (parsed.next_cursor !== null && parsed.next_cursor !== "") {
        throw new Error(`${name}: complete page must not carry a next cursor`);
      }
      return;
    }
    if (!parsed.next_cursor) throw new Error(`${name}: incomplete page must carry a next cursor`);
    cursor = parsed.next_cursor;
  }
  throw new Error(`${name}: cursor chain did not terminate within ${maxPages} pages`);
}

function typicalFixture() {
  const messages = Array.from({ length: 40 }, (_, index) => rawMessage({
    id: `typ-${String(index).padStart(2, "0")}`,
    threadId: "thread-typical",
    internalDate: new Date(Date.parse("2026-08-04T10:00:00Z") + index * 1000).toISOString(),
    body: `typical support email body ${index}`,
  }));
  return loadBridge({ threads: { "thread-typical": { messages } } });
}

function adversarialFixture() {
  const denseBody = '"'.repeat(96 * 1024);
  const messages = Array.from({ length: 100 }, (_, index) => rawMessage({
    id: `adv-${String(index).padStart(3, "0")}`,
    threadId: "thread-wire-adv",
    internalDate: new Date(Date.parse("2026-08-04T10:00:00Z") + index * 1000).toISOString(),
    body: denseBody,
  }));
  return loadBridge({ threads: { "thread-wire-adv": { messages } } });
}

function passDomainFixture() {
  const message = rawMessage({
    id: "pass-domain",
    threadId: "thread-wire-pass",
    internalDate: "2026-08-04T10:00:00Z",
    filename: '"'.repeat(Math.floor(1.6 * MIB)),
    body: "small body",
  });
  return loadBridge({ threads: { "thread-wire-pass": { messages: [message] } } });
}

function oversizedErrorFixture() {
  const message = rawMessage({
    id: "over-budget",
    threadId: "thread-wire-over",
    internalDate: "2026-08-04T10:00:00Z",
    filename: '"'.repeat(Math.floor(2.4 * MIB)),
    body: "small body",
  });
  return { bridge: loadBridge({ threads: { "thread-wire-over": { messages: [message] } } }), message };
}

function projectedFirstSegment(api, message, threadId) {
  const normalized = api.normalizeMessage(message, threadId);
  const sizes = api.segmentWireBytes({
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
  return sizes;
}

const typical = typicalFixture();
runThreadFixture("typical", typical.context, "thread-typical");

const adversarial = adversarialFixture();
runThreadFixture("adversarial", adversarial.context, "thread-wire-adv");

const passDomain = passDomainFixture();
runThreadFixture("pass-domain", passDomain.context, "thread-wire-pass");

const oversized = oversizedErrorFixture();
const projected = projectedFirstSegment(oversized.bridge.api, oversized.message, "thread-wire-over");
writeRecord("oversized-refused", JSON.stringify({
  inner: projected.inner,
  wire: projected.wire,
}));
runThreadFixture("oversized-error", oversized.bridge.context, "thread-wire-over");
