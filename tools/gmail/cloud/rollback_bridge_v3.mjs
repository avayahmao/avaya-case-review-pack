#!/usr/bin/env node
// Fail-fast rollback of the Gmail cloud bridge Web App to bridge v3.
//
// Self-contained inputs: the v3 snapshot ships as rollback_bridge_v3.txt and
// the Apps Script manifest as rollback_bridge_v3.appsscript.txt (deliberately
// non-Apps-Script extensions so they can never be picked up as deployable
// project files). Both pass a SHA-256 + byte-count gate; no Git history is
// required (release ZIPs have none).
//
// Push isolation: clasp runs from a generated staging directory that contains
// ONLY the verified Code.js, the verified appsscript.json, and a generated
// .clasp.json with rootDir ".". Operator workdir rootDir/.claspignore
// settings can therefore never redirect or filter what is uploaded.
//
// Project identity: --script-id (or GMAIL_BRIDGE_SCRIPT_ID, controlled ops
// record) must strictly equal the scriptId in tmp/clasp-bridge/.clasp.json
// (read-only reference), and --deployment-id must strictly equal the
// deployment id embedded in APP_SCRIPT_URL (tools/gmail/gmail_edge_common.py).
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
//   (--python=<executable> or PYTHON env overrides the probe interpreter)
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const IDENTITY_CONFIG = resolve(ROOT, "tmp", "clasp-bridge", ".clasp.json");
const EDGE_COMMON = resolve(ROOT, "tools", "gmail", "gmail_edge_common.py");
const STAGING = resolve(ROOT, "tmp", "clasp-staging-rollback");
const SOURCE_COMPANION = resolve(HERE, "rollback_bridge_v3.txt");
const MANIFEST_COMPANION = resolve(HERE, "rollback_bridge_v3.appsscript.txt");
const CLASP = ["--yes", "@google/clasp@3.3.0"]; // pinned: verified in this rollout
const CLASP_TIMEOUT_MS = 300_000;
const PROBE_TIMEOUT_MS = 300_000;
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

console.log(`[1/6] bundled v3 snapshot verified (sha256 ${v3Digest.slice(0, 12)}…, ${Buffer.byteLength(v3Source)} bytes)`);
console.log("[2/6] bundled appsscript manifest verified (Gmail v1 advanced service)");
console.log("[3/6] identifiers present");
console.log("[4/6] deployment id bound to APP_SCRIPT_URL");
console.log("[5/6] clasp workdir project id verified against --script-id");

if (MODE_DRY_RUN) {
  console.log("[dry-run] all gates passed; nothing written, no remote changes");
  process.exit(0);
}

// clasp runner with a pinned version, a hard timeout, and timeout-vs-exit
// distinction. Never uploads anything from outside the given directory.
function runClasp(step, claspArgs, cwd) {
  const npx = process.platform === "win32" ? "npx.cmd" : "npx";
  const result = spawnSync(npx, [...CLASP, ...claspArgs], {
    cwd,
    stdio: "inherit",
    shell: process.platform === "win32",
    timeout: CLASP_TIMEOUT_MS,
  });
  if (result.error || result.signal) {
    fail(`${step} did not complete (${result.error?.code ?? result.signal ?? "unknown"}; timeout ${CLASP_TIMEOUT_MS}ms); remote state UNKNOWN — run --diagnose`);
  }
  if (result.status !== 0) {
    fail(`${step} exited with status ${result.status}; remote state UNKNOWN — run --diagnose`);
  }
}

// Live version probe with explicit failure classification.
function liveProbe() {
  const probe = spawnSync(
    PYTHON,
    ["tools/gmail/gmail_mcp_server.py", "list-threads", PROBE_CASE_ID, "--max-results=1"],
    { cwd: ROOT, encoding: "utf8", timeout: PROBE_TIMEOUT_MS, maxBuffer: 1024 * 1024 },
  );
  if (probe.error) {
    return { ok: false, kind: "tool-missing", detail: `cannot start "${PYTHON}" (${probe.error.code}); override with --python=<executable>` };
  }
  if (probe.signal || probe.error === undefined && probe.status === null) {
    return { ok: false, kind: "tool-timeout", detail: `probe timed out after ${PROBE_TIMEOUT_MS}ms` };
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

function buildScratch(path) {
  rmSync(path, { recursive: true, force: true });
  mkdirSync(path, { recursive: true });
  writeFileSync(resolve(path, ".clasp.json"), JSON.stringify({ scriptId: SCRIPT_ID, rootDir: "." }));
}

if (MODE_DIAGNOSE) {
  const scratch = resolve(ROOT, "tmp", `clasp-diagnose-${Date.now()}`);
  let exitCode = 0;
  try {
    buildScratch(scratch);
    console.log("[diagnose] pulling current project source (isolated copy)…");
    const pull = spawnSync(
      process.platform === "win32" ? "npx.cmd" : "npx",
      [...CLASP, "pull"],
      { cwd: scratch, encoding: "utf8", timeout: CLASP_TIMEOUT_MS, maxBuffer: 8 * 1024 * 1024, shell: process.platform === "win32" },
    );
    let remoteClass = "unknown";
    if (pull.status === 0) {
      try {
        const pulled = readFileSync(resolve(scratch, "Code.js"), "utf8").replace(/\r\n/g, "\n");
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
      process.platform === "win32" ? "npx.cmd" : "npx",
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

try {
  // [6] Staged push: the staging directory holds only verified content and a
  // generated .clasp.json with rootDir "." — operator rootDir/.claspignore
  // settings cannot redirect or filter the upload. Removed in finally.
  buildScratch(STAGING);
  writeFileSync(resolve(STAGING, "Code.js"), v3Source);
  writeFileSync(resolve(STAGING, "appsscript.json"), v3Manifest);
  console.log("[6/6] staging directory prepared (verified Code.js + appsscript.json + generated .clasp.json)");

  runClasp("clasp push", ["push"], STAGING);
  runClasp("clasp deploy", [
    "deploy",
    "--deploymentId", DEPLOYMENT_ID,
    "--description", "rollback-to-v3-ceecde43",
  ], STAGING);

  const probe = liveProbe();
  if (!probe.ok) {
    fail(`version probe failed (${probe.kind}): ${probe.detail}`);
  }
  console.log("[6/6] live endpoint probe reports bridge_version 3 — rollback verified");
} catch (error) {
  if (error instanceof RollbackError) {
    console.error(`ROLLBACK_ABORTED: ${error.message}`);
    process.exit(1);
  }
  throw error;
} finally {
  rmSync(STAGING, { recursive: true, force: true });
}
