// Shared Apps Script bridge harness: loads GmailMcpBridge.gs into a vm context
// with mocked Gmail/Utilities/ContentService services. Pure module — no
// node:test registration, no stdout writes — so the main test suite and the
// wire probe can import it without TAP side effects.
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
export const bridgePath = resolve(here, "../../tools/gmail/cloud/GmailMcpBridge.gs");

export function webSafe(value) {
  return Buffer.from(value, "utf8").toString("base64url");
}

export function rawMessage({
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

export function legacyMessage({
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

export function loadBridge({
  listPages = {},
  threads = {},
  threadGetFailures = {},
  apiMessages = {},
  attachments = {},
  legacyThreads = [],
  legacyMessages = {},
} = {}) {
  const calls = { list: [], get: [], messageGet: [], attachments: [], search: [], sent: [], blob: 0 };
  const Utilities = {
    Charset: { UTF_8: "UTF-8" },
    DigestAlgorithm: { SHA_256: "SHA_256" },
    newBlob(value) {
      calls.blob += 1;
      if (Array.isArray(value) && value.some((byte) => byte > 127 || byte < -128)) {
        throw new Error("Apps Script Byte[] must use signed octets");
      }
      const bytes = Array.isArray(value) || Buffer.isBuffer(value)
        ? Buffer.from(value)
        : Buffer.from(String(value), "utf8");
      return {
        getBytes: () => Array.from(bytes),
        getDataAsString: (charset = "UTF-8") => {
          const normalizedCharset = String(charset).toLowerCase().replace(/[-_]/g, "");
          if (normalizedCharset === "shiftjis" || normalizedCharset === "sjis") {
            return new TextDecoder("shift_jis").decode(bytes);
          }
          return bytes.toString("utf8");
        },
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
            const failureKey = `${threadId}:${options.format}`;
            if (Object.prototype.hasOwnProperty.call(threadGetFailures, failureKey)) {
              throw new Error(threadGetFailures[failureKey]);
            }
            const hasThread = Object.prototype.hasOwnProperty.call(threads, threadId);
            return structuredClone(hasThread ? threads[threadId] : { id: threadId, messages: [] });
          },
        },
        Messages: {
          get(userId, messageId, options) {
            calls.messageGet.push({ userId, messageId, options: { ...options } });
            if (!Object.prototype.hasOwnProperty.call(apiMessages, messageId)) {
              throw new Error("message not found");
            }
            return structuredClone(apiMessages[messageId]);
          },
          Attachments: {
            get(userId, messageId, attachmentId) {
              calls.attachments.push({ userId, messageId, attachmentId });
              const key = `${messageId}:${attachmentId}`;
              if (!Object.prototype.hasOwnProperty.call(attachments, key)) {
                throw new Error("attachment not found");
              }
              return structuredClone(attachments[key]);
            },
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
