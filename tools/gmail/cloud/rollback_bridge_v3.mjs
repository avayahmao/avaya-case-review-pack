#!/usr/bin/env node
// Fail-fast rollback of the Gmail cloud bridge Web App to bridge v3.
//
// Self-contained inputs: the v3 snapshot ships as rollback_bridge_v3.txt and
// the Apps Script manifest as rollback_bridge_v3.appsscript.txt (deliberately
// non-Apps-Script extensions so they can never be picked up as deployable
// project files). Both pass a SHA-256 + byte-count gate; no Git history is
// required (release ZIPs have none).
//
// Push isolation: clasp runs only from a unique staging directory created by
// mkdtempSync that initially contains just a generated .clasp.json with
// rootDir ".". Before pushing, an isolated `clasp pull` verifies the remote
// project's file inventory is exactly {Code.js, appsscript.json} — any extra
// or missing file aborts the rollback rather than letting `clasp push`
// silently delete remote content. The staging directory then receives only
// the verified Code.js and appsscript.json, so operator rootDir/.claspignore
// settings can never redirect or filter the upload, and staging is always
// removed via try/finally (failures set process.exitCode and fall through to
// the cleanup instead of calling process.exit inside the guarded block).
//
// Project identity: --script-id (or GMAIL_BRIDGE_SCRIPT_ID, controlled ops
// record) must strictly equal the scriptId in tmp/clasp-bridge/.clasp.json
// (read-only reference), and --deployment-id must strictly equal the
// deployment id assembled from APP_SCRIPT_URL (tools/gmail/gmail_edge_common.py).
// All identity gates run before anything is written or pushed.
//
// This is NOT an atomic transaction, and a non-zero or timed-out remote call
// leaves the remote state UNKNOWN (the server may have accepted the request
// before the connection broke). Failure recovery is always: run --diagnose,
// read the actual source hash / deployment list / live bridge_version, then
// retry this script or compensate.
//
// Usage:
//   node tools/gmail/cloud/rollback_bridge_v3.mjs --dry-run
//   node tools/gmail/cloud/rollback_bridge_v3.mjs --diagnose
//   node tools/gmail/cloud/rollback_bridge_v3.mjs --script-id=<id> --deployment-id=<id>
//   (--python=<executable> or PYTHON env overrides the probe interpreter;
//    ROLLBACK_PROBE_TIMEOUT_MS overrides the probe timeout for tests)
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const TMP = resolve(ROOT, "tmp");
const IDENTITY_CONFIG = resolve(ROOT, "tmp", "clasp-bridge", ".clasp.json");
const EDGE_COMMON = resolve(ROOT, "tools", "gmail", "gmail_edge_common.py");
const SOURCE_COMPANION = resolve(HERE, "rollback_bridge_v3.txt");
const MANIFEST_COMPANION = resolve(HERE, "rollback_bridge_v3.appsscript.txt");
const CLASP = ["--yes", "@google/clasp@3.3.0"]; // pinned: verified in this rollout
const CLASP_TIMEOUT_MS = 300_000;
const PROBE_TIMEOUT_MS = Number(process.env.ROLLBACK_PROBE_TIMEOUT_MS) > 0
  ? Number(process.env.ROLLBACK_PROBE_TIMEOUT_MS)
  : 300_000;
const APPROVED_REMOTE_FILES = ["Code.js", "appsscript.json"];
const V3_SHA256 = "ceecde437612bd3f99427907b7797c37df68b585715ea58c8489d02667bb2119";
const V3_BYTES = 39525;
const MANIFEST_SHA256 = "8c9adaf62356fcf49ed573506628ef6de8be5c1b253ecb2c6d53b47f0e7c06c0";
const MANIFEST_BYTES = 339;
const V4_SHA256 = "3fae58fc7e18c8329c070cb7b03d53303a8162a04b568a33d179c20db5e31d48";
const PROBE_CASE_ID = "INC0000001"; // syntactically valid, expected zero-result
const ID_PATTERN = /^[A-Za-z0-9_-]+$/;

class RollbackError extends Error {}
function fail(message) {
  throw new RollbackError(message);
}

const args = process.argv.slice(2);
const MODE_DRY_RUN = args.includes("--dry-run");
const MODE_DIAGNOSE = args.includes("--diagnose");
const flagValue = (name) => {
  const hit = args.find((arg) => arg.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : undefined;
};
const DEPLOYMENT_ID = flagValue("deployment-id") ?? process.env.GMAIL_BRIDGE_DEPLOYMENT_ID;
const SCRIPT_ID = flagValue("script-id") ?? process.env.GMAIL_BRIDGE_SCRIPT_ID;
const PYTHON = flagValue("python") ?? process.env.PYTHON
  ?? (process.platform === "win32" ? "python" : "python3");

function sha256(text) {
  return createHash("sha256").update(text).digest("hex");
}

function readCompanion(path, label) {
  try {
    return readFileSync(path, "utf8").replace(/\r\n/g, "\n");
  } catch (error) {
    console.error(`ROLLBACK_ABORTED: cannot read bundled ${label}: ${error.message}`);
    process.exit(1);
  }
}

// [Gate 1] Bundled v3 snapshot.
const v3Source = readCompanion(SOURCE_COMPANION, "v3 snapshot");
if (!v3Source.startsWith("var GMAIL_BRIDGE_VERSION = 3;")) {
  console.error("ROLLBACK_ABORTED: bundled v3 snapshot is not v3 source");
  process.exit(1);
}
const v3Digest = sha256(v3Source);
if (v3Digest !== V3_SHA256 || Buffer.byteLength(v3Source) !== V3_BYTES) {
  console.error(`ROLLBACK_ABORTED: bundled v3 snapshot failed the hash gate (${v3Digest})`);
  process.exit(1);
}

// [Gate 2] Bundled Apps Script manifest, with the Gmail v1 advanced service.
const v3Manifest = readCompanion(MANIFEST_COMPANION, "appsscript manifest");
if (sha256(v3Manifest) !== MANIFEST_SHA256 || Buffer.byteLength(v3Manifest) !== MANIFEST_BYTES) {
  console.error("ROLLBACK_ABORTED: bundled appsscript manifest failed the hash gate");
  process.exit(1);
}
if (!/"serviceId"\s*:\s*"gmail"/.test(v3Manifest) || !/"version"\s*:\s*"v1"/.test(v3Manifest)) {
  console.error("ROLLBACK_ABORTED: bundled appsscript manifest does not enable the Gmail v1 advanced service");
  process.exit(1);
}

// [Gate 3] Required identifiers.
if (!SCRIPT_ID || !ID_PATTERN.test(SCRIPT_ID)) {
  console.error("ROLLBACK_ABORTED: --script-id / GMAIL_BRIDGE_SCRIPT_ID is required (controlled ops record)");
  process.exit(1);
}
if (!MODE_DIAGNOSE && (!DEPLOYMENT_ID || !ID_PATTERN.test(DEPLOYMENT_ID))) {
  console.error("ROLLBACK_ABORTED: --deployment-id / GMAIL_BRIDGE_DEPLOYMENT_ID is required (APP_SCRIPT_URL in tools/gmail/gmail_edge_common.py)");
  process.exit(1);
}

// [Gate 4] Bind the deployment id to the production endpoint URL so a legal
// id of another deployment on the same project cannot be updated by mistake.
// APP_SCRIPT_URL is built from adjacent string literals, so join them first.
const productionDeploymentId = (() => {
  try {
    const source = readFileSync(EDGE_COMMON, "utf8");
    const assignment = source.match(/APP_SCRIPT_URL\s*=\s*\(([\s\S]*?)\)/);
    if (!assignment) return null;
    const url = (assignment[1].match(/"([^"]*)"/g) ?? [])
      .map((literal) => literal.slice(1, -1))
      .join("");
    const match = url.match(/\/s\/(AKfycb[A-Za-z0-9_-]+)\//);
    return match ? match[1] : null;
  } catch (_) {
    return null;
  }
})();
if (!productionDeploymentId) {
  console.error("ROLLBACK_ABORTED: cannot extract the production deployment id from tools/gmail/gmail_edge_common.py");
  process.exit(1);
}
if (!MODE_DIAGNOSE && DEPLOYMENT_ID !== productionDeploymentId) {
  console.error("ROLLBACK_ABORTED: --deployment-id does not match the deployment id embedded in APP_SCRIPT_URL; refusing to touch another deployment");
  process.exit(1);
}

// [Gate 5] The operator workdir is a read-only identity reference: its
// scriptId must equal the expected --script-id. Nothing from the workdir is
// ever uploaded; push happens from the generated staging directory.
try {
  const identity = JSON.parse(readFileSync(IDENTITY_CONFIG, "utf8"));
  if (identity.scriptId !== SCRIPT_ID) {
    console.error("ROLLBACK_ABORTED: workdir scriptId does not match the expected --script-id; refusing to touch this project");
    process.exit(1);
  }
} catch (error) {
  if (error.code === "ENOENT") {
    console.error(`ROLLBACK_ABORTED: missing ${IDENTITY_CONFIG}; prepare the clasp identity reference first`);
  } else {
    console.error(`ROLLBACK_ABORTED: cannot parse ${IDENTITY_CONFIG} (${error.message})`);
  }
  process.exit(1);
}

console.log(`[1/7] bundled v3 snapshot verified (sha256 ${v3Digest.slice(0, 12)}…, ${Buffer.byteLength(v3Source)} bytes)`);
console.log("[2/7] bundled appsscript manifest verified (Gmail v1 advanced service)");
console.log("[3/7] identifiers present");
console.log("[4/7] deployment id bound to APP_SCRIPT_URL");
console.log("[5/7] clasp workdir project id verified against --script-id");

if (MODE_DRY_RUN) {
  console.log("[dry-run] all gates passed; nothing written, no remote changes");
  process.exit(0);
}

function npxCommand() {
  return process.platform === "win32" ? "npx.cmd" : "npx";
}

// clasp runner with a pinned version, a hard timeout, and timeout-vs-exit
// distinction. Never uploads anything from outside the given directory.
function runClasp(step, claspArgs, cwd) {
  const result = spawnSync(npxCommand(), [...CLASP, ...claspArgs], {
    cwd,
    stdio: "inherit",
    shell: process.platform === "win32",
    timeout: CLASP_TIMEOUT_MS,
  });
  if (result.error?.code === "ETIMEDOUT" || result.signal) {
    fail(`${step} did not complete (timed out after ${CLASP_TIMEOUT_MS}ms); remote state UNKNOWN — run --diagnose`);
  }
  if (result.error) {
    fail(`${step} could not start (${result.error.code}); the request never reached the server — fix the environment and rerun`);
  }
  if (result.status === null) {
    fail(`${step} did not complete; remote state UNKNOWN — run --diagnose`);
  }
  if (result.status !== 0) {
    fail(`${step} exited with status ${result.status}; remote state UNKNOWN — run --diagnose`);
  }
}

// Unique scratch directory under tmp/; never deletes a pre-existing path.
function makeScratch(prefix) {
  mkdirSync(TMP, { recursive: true });
  return mkdtempSync(join(TMP, prefix));
}

// Live version probe with explicit failure classification. Timeouts are
// detected first because spawnSync reports them via error.code ETIMEDOUT
// together with a null status, which must not be reported as tool-missing.
function liveProbe() {
  const probe = spawnSync(
    PYTHON,
    ["tools/gmail/gmail_mcp_server.py", "list-threads", PROBE_CASE_ID, "--max-results=1"],
    { cwd: ROOT, encoding: "utf8", timeout: PROBE_TIMEOUT_MS, maxBuffer: 1024 * 1024 },
  );
  if (probe.error?.code === "ETIMEDOUT" || probe.signal) {
    return { ok: false, kind: "tool-timeout", detail: `probe timed out after ${PROBE_TIMEOUT_MS}ms` };
  }
  if (probe.error) {
    return { ok: false, kind: "tool-missing", detail: `cannot start "${PYTHON}" (${probe.error.code}); override with --python=<executable>` };
  }
  if (probe.status === null) {
    return { ok: false, kind: "tool-timeout", detail: `probe did not complete within ${PROBE_TIMEOUT_MS}ms` };
  }
  if (probe.status !== 0) {
    return { ok: false, kind: "cli-exit", detail: `probe interpreter exited with status ${probe.status}` };
  }
  let document;
  try {
    document = JSON.parse(probe.stdout.trim());
  } catch (error) {
    return { ok: false, kind: "unparsable", detail: `probe output is not JSON: ${error.message}` };
  }
  if (document.success !== true) {
    return { ok: false, kind: "cloud-error", detail: `cloud endpoint error: ${document.error}` };
  }
  if (document.bridge_version !== 3) {
    return { ok: false, kind: "version", detail: `live endpoint reports bridge_version=${document.bridge_version}` };
  }
  return { ok: true, kind: "ok", detail: "bridge_version 3" };
}

if (MODE_DIAGNOSE) {
  let exitCode = 0;
  const scratch = makeScratch("clasp-diagnose-");
  try {
    writeFileSync(join(scratch, ".clasp.json"), JSON.stringify({ scriptId: SCRIPT_ID, rootDir: "." }));
    console.log("[diagnose] pulling current project source (isolated copy)…");
    const pull = spawnSync(
      npxCommand(),
      [...CLASP, "pull"],
      { cwd: scratch, encoding: "utf8", timeout: CLASP_TIMEOUT_MS, maxBuffer: 8 * 1024 * 1024, shell: process.platform === "win32" },
    );
    let remoteClass = "unknown";
    if (pull.status === 0) {
      try {
        const pulled = readFileSync(join(scratch, "Code.js"), "utf8").replace(/\r\n/g, "\n");
        const pulledDigest = sha256(pulled);
        remoteClass = pulledDigest === V3_SHA256 ? "v3" : pulledDigest === V4_SHA256 ? "v4" : `other (${pulledDigest.slice(0, 12)}…)`;
      } catch (_) { /* remoteClass stays unknown */ }
    } else {
      remoteClass = `unavailable (clasp pull status ${pull.status ?? "timeout"})`;
      exitCode = 1;
    }
    console.log(`[diagnose] project source : ${remoteClass}`);
    console.log("[diagnose] deployments    :");
    const listings = spawnSync(
      npxCommand(),
      [...CLASP, "deployments"],
      { cwd: scratch, stdio: "inherit", timeout: CLASP_TIMEOUT_MS, shell: process.platform === "win32" },
    );
    if (listings.status !== 0) {
      console.error("[diagnose] clasp deployments listing failed; check credentials and retry");
      exitCode = 1;
    }
    const probe = liveProbe();
    console.log(`[diagnose] live endpoint  : ${probe.detail}`);
    if (!probe.ok) exitCode = 1;
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
  process.exit(exitCode);
}

let staging = null;
try {
  // [6/7] Staged inventory gate + upload: pull into a unique staging directory
  // and require the remote file set to be exactly the approved pair, so
  // `clasp push` cannot silently delete files added to the project later.
  staging = makeScratch("clasp-staging-rollback-");
  writeFileSync(join(staging, ".clasp.json"), JSON.stringify({ scriptId: SCRIPT_ID, rootDir: "." }));
  runClasp("inventory clasp pull", ["pull"], staging);
  const remoteFiles = readdirSync(staging)
    .filter((name) => name !== ".clasp.json")
    .sort();
  const expected = [...APPROVED_REMOTE_FILES].sort();
  if (remoteFiles.length !== expected.length || remoteFiles.some((name, index) => name !== expected[index])) {
    fail(`remote project file inventory ${JSON.stringify(remoteFiles)} does not match the approved set ${JSON.stringify(expected)}; aborting so clasp push cannot delete unreviewed files — resolve manually`);
  }
  try {
    const pulled = readFileSync(join(staging, "Code.js"), "utf8").replace(/\r\n/g, "\n");
    const pulledDigest = sha256(pulled);
    console.log(`[6/7] remote inventory verified; current remote source is ${pulledDigest === V3_SHA256 ? "v3" : pulledDigest === V4_SHA256 ? "v4" : "unknown content"}`);
  } catch (_) {
    console.log("[6/7] remote inventory verified (source unreadable for classification)");
  }
  writeFileSync(join(staging, "Code.js"), v3Source);
  writeFileSync(join(staging, "appsscript.json"), v3Manifest);

  runClasp("clasp push", ["push"], staging);
  runClasp("clasp deploy", [
    "deploy",
    "--deploymentId", DEPLOYMENT_ID,
    "--description", "rollback-to-v3-ceecde43",
  ], staging);

  const probe = liveProbe();
  if (!probe.ok) {
    fail(`version probe failed (${probe.kind}): ${probe.detail}`);
  }
  console.log("[7/7] live endpoint probe reports bridge_version 3 — rollback verified");
} catch (error) {
  if (error instanceof RollbackError) {
    console.error(`ROLLBACK_ABORTED: ${error.message}`);
    process.exitCode = 1;
  } else {
    process.exitCode = 1;
    console.error(`ROLLBACK_ABORTED: unexpected failure: ${error && error.stack ? error.stack : error}`);
  }
} finally {
  // Runs on every path: failures above set process.exitCode and fall through
  // here instead of exiting inside the guarded block.
  if (staging) rmSync(staging, { recursive: true, force: true });
}
