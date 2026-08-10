var GMAIL_BRIDGE_VERSION = 3;
var MAX_LIST_RESULTS = 100;
var DEFAULT_LIST_RESULTS = 100;
var DEFAULT_LEGACY_SEARCH_RESULTS = 10;
var BODY_CHUNK_MAX_BYTES = 96 * 1024;
var THREAD_PAGE_MAX_SEGMENTS = 4;
var MAX_RESPONSE_BYTES = 6 * 1024 * 1024;
var SUPPORTED_RECORD_ID_RE = /^(?:INC[0-9]{3,20}|SR#?(?:[0-9]{3,20}|1-[A-Z0-9][A-Z0-9_-]{2,79})|1-[A-Z0-9][A-Z0-9_-]{2,79}|(?:CTASK|SCTASK|TASK|ACT|ACTIVITY|CHG|PRJTASK|PEA|ESC|ESCALATION|PRB|RITM|REQ)[A-Z0-9_-]{2,79}|SWA-INC[0-9]{3,20})$/i;

function doGet(e) {
  try {
    var parameters = (e && e.parameter) || {};
    var action = parameters.action || "search";
    if (action === "search") return jsonOutput_(legacySearch_(parameters));
    if (action === "read") return jsonOutput_(legacyRead_(parameters));
    if (action === "send") return jsonOutput_(legacySend_(parameters));
    if (action === "list_threads") return jsonOutput_(listThreads_(parameters));
    if (action === "read_thread_page") return jsonOutput_(readThreadPage_(parameters));
    return jsonOutput_({ success: false, error: "Unknown action" });
  } catch (error) {
    return jsonOutput_({ success: false, error: sanitizedError_(error) });
  }
}

function jsonOutput_(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}

function legacySearch_(parameters) {
  var query = parameters.q || parameters.query || "";
  // Legacy compatibility remains bounded; exhaustive callers must use list_threads.
  var maxResults = parameters.max_results === undefined || parameters.max_results === null || parameters.max_results === ""
    ? DEFAULT_LEGACY_SEARCH_RESULTS
    : boundedListResults_(parameters.max_results);
  var threads = GmailApp.search(query, 0, maxResults);
  var messages = [];
  for (var index = 0; index < threads.length; index += 1) {
    var thread = threads[index];
    var threadMessages = thread.getMessages();
    if (!threadMessages.length) continue;
    var message = threadMessages[threadMessages.length - 1];
    messages.push({
      id: message.getId(),
      threadId: thread.getId(),
      subject: message.getSubject(),
      from: message.getFrom(),
      date: message.getDate().toISOString(),
      snippet: message.getPlainBody().slice(0, 200),
    });
  }
  return { success: true, messages: messages };
}

function legacyRead_(parameters) {
  var id = parameters.id || parameters.message_id || "";
  if (!id) return { success: false, error: "Missing message ID" };

  var message;
  try {
    message = GmailApp.getMessageById(id);
  } catch (error) {
    return { success: false, error: "Message not found" };
  }
  if (!message) return { success: false, error: "Message not found" };

  return {
    success: true,
    id: message.getId(),
    threadId: message.getThread().getId(),
    subject: message.getSubject(),
    from: message.getFrom(),
    to: message.getTo(),
    cc: message.getCc(),
    date: message.getDate().toISOString(),
    body: message.getBody(),
    plainBody: message.getPlainBody(),
  };
}

function legacySend_(parameters) {
  var to = parameters.to || "";
  var subject = parameters.subject || "";
  var body = parameters.body || "";
  if (!to || !subject || !body) return { success: false, error: "Missing required fields" };
  GmailApp.sendEmail(to, subject, body);
  return { success: true, message: "Email sent" };
}

function requireRecordId_(value) {
  var recordId = typeof value === "string" ? value : "";
  if (recordId.length > 80 || !SUPPORTED_RECORD_ID_RE.test(recordId)) throw new Error("INVALID_RECORD_ID");
  return recordId;
}

function normalizeSnapshot_(value) {
  if (typeof value !== "string" || !value) throw new Error("INVALID_SNAPSHOT");
  var timestamp = new Date(value).getTime();
  if (!isFinite(timestamp)) throw new Error("INVALID_SNAPSHOT");
  return new Date(timestamp).toISOString();
}

function snapshotQuery_(recordId, snapshotBefore) {
  // Gmail search accepts second-resolution Unix timestamps. The query includes
  // the complete second containing snapshotBefore; reads use the same inclusive
  // millisecond cutoff so a listed thread cannot become an empty ghost page.
  var epoch = snapshotEpochSeconds_(snapshotBefore);
  return '"' + recordId + '" before:' + epoch;
}

function snapshotEpochSeconds_(snapshotBefore) {
  return Math.floor(new Date(snapshotBefore).getTime() / 1000) + 1;
}

function snapshotCutoffMillis_(snapshotBefore) {
  return snapshotEpochSeconds_(snapshotBefore) * 1000 - 1;
}

function listThreads_(parameters) {
  var recordId = requireRecordId_(parameters.q);
  var snapshotBefore = normalizeSnapshot_(parameters.snapshot_before || new Date().toISOString());
  var options = {
    q: snapshotQuery_(recordId, snapshotBefore),
    maxResults: boundedListResults_(parameters.max_results),
  };
  if (parameters.page_token) options.pageToken = String(parameters.page_token);

  var response = Gmail.Users.Threads.list("me", options);
  validateListResponse_(response);
  var threads = Array.isArray(response.threads) ? response.threads : [];
  var threadIds = [];
  for (var index = 0; index < threads.length; index += 1) {
    if (!threads[index] || typeof threads[index] !== "object" || !threads[index].id) {
      throw new Error("INVALID_THREAD_RESPONSE");
    }
    threadIds.push(String(threads[index].id));
  }
  var nextPageToken = response.nextPageToken === undefined ? "" : response.nextPageToken;
  var result = {
    success: true,
    bridge_version: GMAIL_BRIDGE_VERSION,
    query: recordId,
    snapshot_before: snapshotBefore,
    thread_ids: threadIds,
    next_page_token: nextPageToken,
    complete: !nextPageToken,
  };
  return result;
}

function validateListResponse_(response) {
  if (!response || typeof response !== "object" || Array.isArray(response)) {
    throw new Error("INVALID_THREAD_RESPONSE");
  }
  if (response.threads === undefined && typeof response.resultSizeEstimate !== "number") {
    throw new Error("INVALID_THREAD_RESPONSE");
  }
  if (response.threads !== undefined && !Array.isArray(response.threads)) {
    throw new Error("INVALID_THREAD_RESPONSE");
  }
  if (response.nextPageToken !== undefined && typeof response.nextPageToken !== "string") {
    throw new Error("INVALID_THREAD_RESPONSE");
  }
}

function boundedListResults_(value) {
  if (value === undefined || value === null || value === "") return DEFAULT_LIST_RESULTS;
  var parsed = Number(value);
  if (!isFinite(parsed)) return DEFAULT_LIST_RESULTS;
  parsed = Math.floor(parsed);
  return Math.max(1, Math.min(MAX_LIST_RESULTS, parsed));
}

function encodeCursor_(cursor) {
  validateCursorShape_(cursor);
  var encoded = Utilities.base64EncodeWebSafe(utf8Bytes_(JSON.stringify(cursor)));
  return encoded.replace(/=+$/, "");
}

function decodeCursor_(cursor, threadId, snapshotBefore, manifest) {
  if (typeof cursor !== "string" || !/^[A-Za-z0-9_-]+$/.test(cursor)) throw new Error("INVALID_CURSOR");
  var decoded;
  try {
    decoded = JSON.parse(utf8FromBytes_(Utilities.base64DecodeWebSafe(cursor)));
  } catch (error) {
    throw new Error("INVALID_CURSOR");
  }
  try {
    validateCursorShape_(decoded);
  } catch (error) {
    throw new Error("INVALID_CURSOR");
  }
  if (decoded.thread_id !== threadId || decoded.snapshot_before !== snapshotBefore ||
      decoded.manifest_sha256 !== manifest) {
    throw new Error("INVALID_CURSOR");
  }
  return decoded;
}

function validateCursorShape_(cursor) {
  if (!cursor || typeof cursor !== "object" || cursor.version !== GMAIL_BRIDGE_VERSION ||
      typeof cursor.thread_id !== "string" || !cursor.thread_id ||
      typeof cursor.snapshot_before !== "string" || !cursor.snapshot_before ||
      typeof cursor.manifest_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(cursor.manifest_sha256) ||
      !isNonNegativeInteger_(cursor.message_index) || !isNonNegativeInteger_(cursor.chunk_index)) {
    throw new Error("INVALID_CURSOR");
  }
}

function isNonNegativeInteger_(value) {
  return typeof value === "number" && isFinite(value) && Math.floor(value) === value && value >= 0;
}

function readThreadPage_(parameters) {
  var threadId = requireThreadId_(parameters.thread_id);
  var snapshotBefore = normalizeSnapshot_(parameters.snapshot_before);
  var snapshotMillis = snapshotCutoffMillis_(snapshotBefore);
  // This endpoint is intentionally stateless. Each cursor page re-fetches and
  // normalizes the full thread; avoiding CacheService prevents stale manifests,
  // cache-size failures, and cross-run cache invalidation hazards.
  var thread = Gmail.Users.Threads.get("me", threadId, { format: "full" });
  validateThreadResponse_(thread);
  var sourceMessages = Array.isArray(thread.messages) ? thread.messages : [];
  var messages = [];
  for (var index = 0; index < sourceMessages.length; index += 1) {
    var source = sourceMessages[index];
    validateMessage_(source);
    if (Number(source.internalDate) <= snapshotMillis) {
      messages.push(normalizeMessage_(source, threadId));
    }
  }
  messages.sort(compareMessages_);

  var manifestIds = [];
  for (var messageIndex = 0; messageIndex < messages.length; messageIndex += 1) {
    manifestIds.push(messages[messageIndex].message_id);
  }
  var manifest = sha256Hex_(manifestIds.join("\n"));
  var position = parameters.cursor
    ? decodeCursor_(parameters.cursor, threadId, snapshotBefore, manifest)
    : { message_index: 0, chunk_index: 0 };
  validateCursorPosition_(position, messages);

  var emitted = emitSegments_(messages, position.message_index, position.chunk_index);
  var nextCursor = emitted.complete ? null : encodeCursor_({
    version: GMAIL_BRIDGE_VERSION,
    thread_id: threadId,
    snapshot_before: snapshotBefore,
    manifest_sha256: manifest,
    message_index: emitted.message_index,
    chunk_index: emitted.chunk_index,
  });
  var result = {
    success: true,
    bridge_version: GMAIL_BRIDGE_VERSION,
    thread_id: threadId,
    snapshot_before: snapshotBefore,
    message_count: messages.length,
    manifest_sha256: manifest,
    segments: emitted.segments,
    messages_completed: emitted.messages_completed,
    next_cursor: nextCursor,
    complete: emitted.complete,
  };
  assertResponseSize_(result);
  return result;
}

function validateThreadResponse_(thread) {
  if (!thread || typeof thread !== "object" || Array.isArray(thread) || !Array.isArray(thread.messages)) {
    throw new Error("INVALID_THREAD_RESPONSE");
  }
}

function requireThreadId_(value) {
  if (typeof value !== "string" || !value) throw new Error("INVALID_THREAD_ID");
  return value;
}

function validateCursorPosition_(position, messages) {
  if (position.message_index > messages.length) throw new Error("INVALID_CURSOR");
  if (position.message_index === messages.length && position.chunk_index !== 0) throw new Error("INVALID_CURSOR");
  if (position.message_index < messages.length &&
      position.chunk_index >= messages[position.message_index].body_chunks.length) {
    throw new Error("INVALID_CURSOR");
  }
}

function compareMessages_(left, right) {
  if (left.internal_date < right.internal_date) return -1;
  if (left.internal_date > right.internal_date) return 1;
  if (left.message_id < right.message_id) return -1;
  if (left.message_id > right.message_id) return 1;
  return 0;
}

function emitSegments_(messages, messageIndex, chunkIndex) {
  var segments = [];
  var messagesCompleted = messageIndex;
  var currentMessage = messageIndex;
  var currentChunk = chunkIndex;
  while (currentMessage < messages.length && segments.length < THREAD_PAGE_MAX_SEGMENTS) {
    var message = messages[currentMessage];
    var chunkCount = message.body_chunks.length;
    segments.push({
      message_id: message.message_id,
      thread_id: message.thread_id,
      internal_date: message.internal_date,
      from: message.from,
      to: message.to,
      cc: message.cc,
      subject: message.subject,
      body_chunk: message.body_chunks[currentChunk],
      chunk_index: currentChunk,
      chunk_count: chunkCount,
      body_bytes: message.body_bytes,
      body_sha256: message.body_sha256,
      attachment_names: message.attachment_names,
    });
    currentChunk += 1;
    if (currentChunk === chunkCount) {
      currentMessage += 1;
      currentChunk = 0;
      messagesCompleted += 1;
    }
  }
  return {
    segments: segments,
    messages_completed: messagesCompleted,
    message_index: currentMessage,
    chunk_index: currentChunk,
    complete: currentMessage === messages.length,
  };
}

function normalizeMessage_(message, fallbackThreadId) {
  validateMessage_(message);
  var payload = message && message.payload ? message.payload : {};
  validateMimeStructure_(payload);
  var headers = lowerCaseHeaders_(payload.headers);
  var body = normalizedBody_(payload, String(message.id || ""));
  var bodyBytes = utf8ByteLength_(body);
  return {
    message_id: String(message.id || ""),
    thread_id: String(message.threadId || fallbackThreadId || ""),
    internal_date: internalDateIso_(message.internalDate),
    from: headerValue_(headers, "from"),
    to: commaSeparated_(headerValue_(headers, "to")),
    cc: commaSeparated_(headerValue_(headers, "cc")),
    subject: headerValue_(headers, "subject"),
    body_bytes: bodyBytes,
    body_sha256: sha256Hex_(body),
    body_chunks: splitUtf8_(body),
    attachment_names: attachmentNames_(payload),
  };
}

function validateMessage_(message) {
  if (!message || typeof message !== "object" || Array.isArray(message) ||
      typeof message.id !== "string" || !message.id ||
      typeof message.threadId !== "string" || !message.threadId ||
      message.internalDate === undefined || message.internalDate === null || message.internalDate === "" ||
      !isFinite(Number(message.internalDate)) ||
      !message.payload || typeof message.payload !== "object" || Array.isArray(message.payload) ||
      typeof message.payload.mimeType !== "string" || !message.payload.mimeType) {
    throw new Error("INVALID_MESSAGE");
  }
}

function validateMimeStructure_(part) {
  if (!part || typeof part !== "object" || Array.isArray(part)) {
    throw new Error("INVALID_MIME_STRUCTURE");
  }
  if (part.parts !== undefined) {
    if (!Array.isArray(part.parts)) throw new Error("INVALID_MIME_STRUCTURE");
    for (var index = 0; index < part.parts.length; index += 1) {
      validateMimeStructure_(part.parts[index]);
    }
  }
}

function internalDateIso_(value) {
  var millis = Number(value);
  if (!isFinite(millis)) throw new Error("INVALID_MESSAGE_DATE");
  return new Date(millis).toISOString();
}

function lowerCaseHeaders_(headers) {
  var output = {};
  var values = Array.isArray(headers) ? headers : [];
  for (var index = 0; index < values.length; index += 1) {
    var header = values[index];
    if (header && header.name) output[String(header.name).toLowerCase()] = String(header.value || "");
  }
  return output;
}

function headerValue_(headers, name) {
  return headers[name] || "";
}

function commaSeparated_(value) {
  if (!value) return [];
  var result = [];
  var current = "";
  var inQuotes = false;
  var escaped = false;
  var source = String(value);
  for (var index = 0; index < source.length; index += 1) {
    var character = source.charAt(index);
    if (escaped) {
      current += character;
      escaped = false;
    } else if (character === "\\" && inQuotes) {
      current += character;
      escaped = true;
    } else if (character === '"') {
      current += character;
      inQuotes = !inQuotes;
    } else if (character === "," && !inQuotes) {
      if (current.trim()) result.push(current.trim());
      current = "";
    } else {
      current += character;
    }
  }
  if (current.trim()) result.push(current.trim());
  return result;
}

function normalizedBody_(payload, messageId) {
  var plainParts = [];
  var htmlParts = [];
  collectTextParts_(payload, plainParts, htmlParts, messageId);
  for (var plainIndex = 0; plainIndex < plainParts.length; plainIndex += 1) {
    if (plainParts[plainIndex]) return plainParts[plainIndex];
  }
  for (var htmlIndex = 0; htmlIndex < htmlParts.length; htmlIndex += 1) {
    if (htmlParts[htmlIndex]) return htmlToText_(htmlParts[htmlIndex]);
  }
  return "";
}

function collectTextParts_(part, plainParts, htmlParts, messageId) {
  if (!part) return;
  if (isAttachmentPart_(part)) return;
  var mimeType = String(part.mimeType || "").toLowerCase();
  var text = partBody_(part, messageId);
  if (text !== null) {
    if (mimeType === "text/plain") plainParts.push(text);
    if (mimeType === "text/html") htmlParts.push(text);
  }
  var children = Array.isArray(part.parts) ? part.parts : [];
  for (var index = 0; index < children.length; index += 1) {
    collectTextParts_(children[index], plainParts, htmlParts, messageId);
  }
}

function partBody_(part, messageId) {
  if (!part.body) return null;
  var bodyData = part.body.data;
  var attachmentId = part.body.attachmentId;
  if (hasBodyData_(bodyData)) {
    return decodePartBodyData_(bodyData);
  }
  if (typeof attachmentId !== "string" || !attachmentId ||
      !isTextMimeType_(part) || isAttachmentPart_(part)) {
    return bodyData === undefined || bodyData === null ? null : decodePartBodyData_(bodyData);
  }
  if (!messageId) throw new Error("INVALID_BODY_ATTACHMENT");
  var attachment;
  try {
    attachment = Gmail.Users.Messages.Attachments.get("me", messageId, attachmentId);
  } catch (error) {
    throw new Error("BODY_ATTACHMENT_UNAVAILABLE");
  }
  if (!attachment || !hasBodyData_(attachment.data)) {
    throw new Error("BODY_ATTACHMENT_UNAVAILABLE");
  }
  return decodePartBodyData_(attachment.data);
}

function hasBodyData_(value) {
  if (typeof value === "string") return value.length > 0;
  return Array.isArray(value) && value.length > 0;
}

function decodePartBodyData_(value) {
  if (Array.isArray(value)) {
    try {
      return utf8FromBytes_(value);
    } catch (error) {
      throw new Error("INVALID_BODY_ENCODING");
    }
  }
  return decodeBodyData_(value);
}

function decodeBodyData_(value) {
  try {
    if (!/^[A-Za-z0-9_-]*={0,2}$/.test(value)) throw new Error("invalid base64");
    var bytes = Utilities.base64DecodeWebSafe(value);
    if (!bytes || typeof bytes.length !== "number") throw new Error("invalid decoded bytes");
    return utf8FromBytes_(bytes);
  } catch (error) {
    throw new Error("INVALID_BODY_ENCODING");
  }
}

function isTextMimeType_(part) {
  var mimeType = String(part && part.mimeType || "").toLowerCase();
  return mimeType === "text/plain" || mimeType === "text/html";
}

function isAttachmentPart_(part) {
  if (!part || typeof part !== "object") return false;
  if (part.filename) return true;
  if (part.attachmentId !== undefined && part.attachmentId !== null && String(part.attachmentId)) return true;
  if (part.body && part.body.attachmentId !== undefined && part.body.attachmentId !== null &&
      String(part.body.attachmentId) &&
      (hasBodyData_(part.body.data) || !isTextMimeType_(part))) return true;
  var headers = Array.isArray(part.headers) ? part.headers : [];
  for (var index = 0; index < headers.length; index += 1) {
    var header = headers[index];
    if (header && String(header.name || "").toLowerCase() === "content-disposition") {
      var disposition = String(header.value || "");
      var parameters = parseDispositionParameters_(disposition);
      if (/\battachment\b/i.test(disposition) || hasFilenameParameter_(parameters)) return true;
    }
  }
  return false;
}

function parseDispositionParameters_(value) {
  var parameters = [];
  var source = String(value || "");
  var index = 0;
  while (index < source.length) {
    while (index < source.length && (source.charAt(index) === ";" || /\s/.test(source.charAt(index)))) index += 1;
    if (index >= source.length) break;
    var nameStart = index;
    while (index < source.length && source.charAt(index) !== "=" && source.charAt(index) !== ";") index += 1;
    var name = source.slice(nameStart, index).trim().toLowerCase();
    while (index < source.length && /\s/.test(source.charAt(index))) index += 1;
    if (!name || source.charAt(index) !== "=") {
      while (index < source.length && source.charAt(index) !== ";") index += 1;
      continue;
    }
    index += 1;
    while (index < source.length && /\s/.test(source.charAt(index))) index += 1;
    var parameterValue = "";
    if (source.charAt(index) === '"') {
      index += 1;
      while (index < source.length) {
        var character = source.charAt(index);
        if (character === "\\" && index + 1 < source.length) {
          parameterValue += source.charAt(index + 1);
          index += 2;
        } else if (character === '"') {
          index += 1;
          break;
        } else {
          parameterValue += character;
          index += 1;
        }
      }
    } else {
      var valueStart = index;
      while (index < source.length && source.charAt(index) !== ";") index += 1;
      parameterValue = source.slice(valueStart, index).trim();
    }
    parameters.push({ name: name, value: parameterValue });
  }
  return parameters;
}

function isFilenameParameterName_(name) {
  return name === "filename" || name === "filename*" || /^filename\*\d+\*?$/i.test(name);
}

function hasFilenameParameter_(parameters) {
  for (var index = 0; index < parameters.length; index += 1) {
    if (isFilenameParameterName_(parameters[index].name)) return true;
  }
  return false;
}

function sanitizedAttachmentName_(value) {
  return String(value || "").replace(/[\u0000\r\n]/g, "").trim();
}

function appendUtf8CodePointBytes_(bytes, codePoint) {
  if (codePoint >= 0xD800 && codePoint <= 0xDFFF) codePoint = 0xFFFD;
  if (codePoint <= 0x7F) {
    bytes.push(codePoint);
  } else if (codePoint <= 0x7FF) {
    bytes.push(0xC0 | (codePoint >> 6), 0x80 | (codePoint & 0x3F));
  } else if (codePoint <= 0xFFFF) {
    bytes.push(0xE0 | (codePoint >> 12), 0x80 | ((codePoint >> 6) & 0x3F), 0x80 | (codePoint & 0x3F));
  } else {
    bytes.push(0xF0 | (codePoint >> 18), 0x80 | ((codePoint >> 12) & 0x3F),
      0x80 | ((codePoint >> 6) & 0x3F), 0x80 | (codePoint & 0x3F));
  }
}

function percentEncodedBytes_(value) {
  var source = String(value || "");
  var bytes = [];
  for (var index = 0; index < source.length;) {
    if (source.charAt(index) === "%" && /^[0-9a-f]{2}$/i.test(source.slice(index + 1, index + 3))) {
      bytes.push(parseInt(source.slice(index + 1, index + 3), 16));
      index += 3;
    } else {
      var codePoint = source.codePointAt(index);
      appendUtf8CodePointBytes_(bytes, codePoint);
      index += codePoint > 0xFFFF ? 2 : 1;
    }
  }
  return bytes;
}

function decodeFilenameBytes_(bytes, charset) {
  var requestedCharset = charset || "UTF-8";
  var signedBytes = signedByteArray_(bytes);
  try {
    return sanitizedAttachmentName_(Utilities.newBlob(signedBytes).getDataAsString(requestedCharset));
  } catch (error) {
    try {
      return sanitizedAttachmentName_(Utilities.newBlob(signedBytes).getDataAsString("UTF-8"));
    } catch (fallbackError) {
      var safe = "";
      for (var index = 0; index < bytes.length; index += 1) safe += bytes[index] < 0x80 ? String.fromCharCode(bytes[index]) : "\uFFFD";
      return sanitizedAttachmentName_(safe);
    }
  }
}

function splitExtendedDispositionValue_(value) {
  var source = String(value || "");
  var charset = "UTF-8";
  var charsetSeparator = source.indexOf("'");
  var languageSeparator = charsetSeparator < 0 ? -1 : source.indexOf("'", charsetSeparator + 1);
  if (languageSeparator >= 0) {
    if (charsetSeparator > 0) charset = source.slice(0, charsetSeparator);
    source = source.slice(languageSeparator + 1);
  }
  return { charset: charset, encoded: source };
}

function decodeDispositionValue_(value, extended, stripCharset) {
  if (!extended) return sanitizedAttachmentName_(value);
  var parsed = stripCharset ? splitExtendedDispositionValue_(value) : { charset: "UTF-8", encoded: value };
  return decodeFilenameBytes_(percentEncodedBytes_(parsed.encoded), parsed.charset);
}

function dispositionFilenames_(value) {
  var parameters = parseDispositionParameters_(value);
  var simpleName = "";
  var extendedName = "";
  var continuation = {};
  var continuationIndexes = [];
  for (var index = 0; index < parameters.length; index += 1) {
    var parameter = parameters[index];
    if (parameter.name === "filename") {
      if (!simpleName) simpleName = decodeDispositionValue_(parameter.value, false, false);
    } else if (parameter.name === "filename*") {
      if (!extendedName) extendedName = decodeDispositionValue_(parameter.value, true, true);
    } else {
      var match = parameter.name.match(/^filename\*(\d+)(\*)?$/i);
      if (match) {
        var segmentIndex = Number(match[1]);
        if (!continuation[segmentIndex]) continuationIndexes.push(segmentIndex);
        continuation[segmentIndex] = {
          value: parameter.value,
          extended: !!match[2],
        };
      }
    }
  }
  var names = [];
  if (continuationIndexes.length) {
    continuationIndexes.sort(function (left, right) { return left - right; });
    var joined = "";
    var expectedIndex = 0;
    for (var segment = 0; segment < continuationIndexes.length; segment += 1) {
      var currentIndex = continuationIndexes[segment];
      if (currentIndex !== expectedIndex) break;
      var current = continuation[currentIndex];
      if (current.extended) {
        var parsed = currentIndex === 0 ? splitExtendedDispositionValue_(current.value) : { charset: "UTF-8", encoded: current.value };
        if (currentIndex === 0) continuation.charset = parsed.charset;
        continuation.extended = true;
        joined += parsed.encoded;
      } else {
        joined += current.value;
      }
      expectedIndex += 1;
    }
    if (expectedIndex > 0) {
      names.push(continuation.extended
        ? decodeFilenameBytes_(percentEncodedBytes_(joined), continuation.charset || "UTF-8")
        : sanitizedAttachmentName_(joined));
    }
  }
  if (!names.length && extendedName) names.push(extendedName);
  if (!names.length && simpleName) names.push(simpleName);
  return names;
}

function attachmentNames_(part) {
  var names = [];
  collectAttachmentNames_(part, names);
  return names;
}

function collectAttachmentNames_(part, names) {
  if (!part) return;
  if (part.filename) addAttachmentName_(names, String(part.filename));
  var headers = Array.isArray(part.headers) ? part.headers : [];
  for (var headerIndex = 0; headerIndex < headers.length; headerIndex += 1) {
    var header = headers[headerIndex];
    if (header && String(header.name || "").toLowerCase() === "content-disposition") {
      var dispositionNames = dispositionFilenames_(header.value);
      for (var nameIndex = 0; nameIndex < dispositionNames.length; nameIndex += 1) {
        addAttachmentName_(names, dispositionNames[nameIndex]);
      }
    }
  }
  var children = Array.isArray(part.parts) ? part.parts : [];
  for (var index = 0; index < children.length; index += 1) {
    collectAttachmentNames_(children[index], names);
  }
}

function addAttachmentName_(names, name) {
  if (!name) return;
  for (var index = 0; index < names.length; index += 1) {
    if (names[index] === name) return;
  }
  names.push(name);
}

function htmlToText_(html) {
  var text = String(html || "")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|tr|h[1-6])\s*>/gi, "\n")
    .replace(/<[^>]+>/g, "");
  text = decodeHtmlEntities_(text);
  var lines = text.split(/\n+/);
  var cleaned = [];
  for (var index = 0; index < lines.length; index += 1) {
    var line = lines[index].replace(/[ \t\f\v]+/g, " ").trim();
    if (line) cleaned.push(line);
  }
  return cleaned.join("\n");
}

function decodeHtmlEntities_(value) {
  var named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
  return value.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, function (match, entity) {
    var lower = String(entity).toLowerCase();
    if (named[lower] !== undefined) return named[lower];
    if (lower.indexOf("#x") === 0) return codePointString_(parseInt(lower.slice(2), 16), match);
    if (lower.indexOf("#") === 0) return codePointString_(parseInt(lower.slice(1), 10), match);
    return match;
  });
}

function codePointString_(codePoint, fallback) {
  if (!isFinite(codePoint) || codePoint < 0 || codePoint > 0x10FFFF ||
      (codePoint >= 0xD800 && codePoint <= 0xDFFF)) return fallback;
  if (codePoint <= 0xFFFF) return String.fromCharCode(codePoint);
  var adjusted = codePoint - 0x10000;
  return String.fromCharCode(0xD800 + (adjusted >> 10), 0xDC00 + (adjusted & 0x3FF));
}

function utf8Bytes_(value) {
  return Utilities.newBlob(String(value)).getBytes();
}

function signedByteArray_(bytes) {
  var signed = [];
  for (var index = 0; index < bytes.length; index += 1) {
    var byte = Number(bytes[index]);
    if (byte > 127) byte -= 256;
    signed.push(byte);
  }
  return signed;
}

function utf8FromBytes_(bytes) {
  return Utilities.newBlob(signedByteArray_(bytes)).getDataAsString("UTF-8");
}

function utf8CodePointByteLength_(codePoint) {
  if (codePoint <= 0x7F) return 1;
  if (codePoint <= 0x7FF) return 2;
  if (codePoint <= 0xFFFF) return 3;
  return 4;
}

function utf8ByteLength_(value) {
  var source = String(value || "");
  var length = 0;
  for (var index = 0; index < source.length;) {
    var codePoint = source.codePointAt(index);
    length += utf8CodePointByteLength_(codePoint);
    index += codePoint > 0xFFFF ? 2 : 1;
  }
  return length;
}

function stringForCodePoint_(codePoint) {
  if (codePoint <= 0xFFFF) return String.fromCharCode(codePoint);
  var adjusted = codePoint - 0x10000;
  return String.fromCharCode(0xD800 + (adjusted >> 10), 0xDC00 + (adjusted & 0x3FF));
}

function splitUtf8_(text, maximumBytes) {
  var limit = maximumBytes || BODY_CHUNK_MAX_BYTES;
  var source = String(text || "");
  if (!source) return [""];
  var chunks = [];
  var current = "";
  var currentBytes = 0;
  for (var index = 0; index < source.length;) {
    var codePoint = source.codePointAt(index);
    var character = stringForCodePoint_(codePoint);
    var characterBytes = utf8CodePointByteLength_(codePoint);
    if (current && currentBytes + characterBytes > limit) {
      chunks.push(current);
      current = "";
      currentBytes = 0;
    }
    current += character;
    currentBytes += characterBytes;
    index += character.length;
  }
  if (current || !chunks.length) chunks.push(current);
  return chunks;
}

function sha256Hex_(value) {
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, String(value), Utilities.Charset.UTF_8);
  var hex = "";
  for (var index = 0; index < digest.length; index += 1) {
    var byte = (digest[index] + 256) % 256;
    hex += (byte < 16 ? "0" : "") + byte.toString(16);
  }
  return hex;
}

function assertResponseSize_(value) {
  var serialized = JSON.stringify(value);
  if (utf8ByteLength_(serialized) > MAX_RESPONSE_BYTES) throw new Error("RESPONSE_TOO_LARGE");
}

function sanitizedError_(error) {
  var code = error && error.message ? String(error.message) : "";
  var allowed = {
    INVALID_RECORD_ID: true,
    INVALID_SNAPSHOT: true,
    INVALID_CURSOR: true,
    INVALID_THREAD_ID: true,
    RESPONSE_TOO_LARGE: true,
    INVALID_BODY_ATTACHMENT: true,
    BODY_ATTACHMENT_UNAVAILABLE: true,
  };
  return allowed[code] ? code : "APP_ERROR";
}

var GmailBridgeTestExports = {
  decodeCursor: decodeCursor_,
  encodeCursor: encodeCursor_,
  listThreads: listThreads_,
  normalizeMessage: normalizeMessage_,
  normalizeSnapshot: normalizeSnapshot_,
  readThreadPage: readThreadPage_,
  sha256Hex: sha256Hex_,
  splitUtf8: splitUtf8_,
  snapshotQuery: snapshotQuery_,
  snapshotCutoffMillis: snapshotCutoffMillis_,
};
