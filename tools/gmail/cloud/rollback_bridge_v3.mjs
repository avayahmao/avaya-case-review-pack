#!/usr/bin/env node
// Fail-fast rollback of the Gmail cloud bridge Web App to bridge v3.
//
// Self-contained: the v3 source ships alongside this script as
// rollback_bridge_v3.gs and is accepted only after a first-line + SHA-256 +
// byte-count gate, so no Git history is required (release ZIPs have none).
//
// Runtime prerequisites (see the handoff): Node.js, network access to the npm
// registry or a warm npx cache for the pinned clasp version below, an
// authenticated ~/.clasprc.json, and a clasp work directory whose
// .clasp.json scriptId equals the --script-id argument (controlled ops
// record). --script-id or GMAIL_BRIDGE_SCRIPT_ID is REQUIRED and is verified
// against the work directory before anything is written or pushed.
//
// This is deliberately NOT an atomic transaction, and a non-zero or timed-out
// remote call leaves the remote state UNKNOWN (the server may have accepted
// the request before the connection broke). Failure recovery is always:
// run --diagnose first, read the actual source hash / deployment version /
// live bridge_version, then retry this script or compensate.
//
// Usage:
//   node tools/gmail/cloud/rollback_bridge_v3.mjs --dry-run
//   node tools/gmail/cloud/rollback_bridge_v3.mjs --diagnose
//   node tools/gmail/cloud/rollback_bridge_v3.mjs --script-id=<id> --deployment-id=<id>
//
// --deployment-id (or GMAIL_BRIDGE_DEPLOYMENT_ID) is the deployment ID from
// APP_SCRIPT_URL in tools/gmail/gmail_edge_common.py; updating that
// deployment keeps the production endpoint URL unchanged.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..", "..");
const WORKDIR = resolve(ROOT, "tmp", "clasp-bridge");
const COMPANION = resolve(HERE, "rollback_bridge_v3.gs");
const CLASP = ["--yes", "@google/clasp@3.3.0"]; // pinned: verified in this rollout
const CLASP_TIMEOUT_MS = 300_000;
const V3_SHA256 = "ceecde437612bd3f99427907b7797c37df68b585715ea58c8489d02667bb2119";
const V3_BYTES = 39525;
const V4_SHA256 = "3fae58fc7e18c8329c070cb7b03d53303a8162a04b568a33d179c20db5e31d48";
const PROBE_CASE_ID = "INC0000001"; // syntactically valid, expected zero-result
const ID_PATTERN = /^[A-Za-z0-9_-]+$/;

const args = process.argv.slice(2);
const MODE_DRY_RUN = args.includes("--dry-run");
const MODE_DIAGNOSE = args.includes("--diagnose");
const flagValue = (name) => {
  const hit = args.find((arg) => arg.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : undefined;
};
const DEPLOYMENT_ID = flagValue("deployment-id") ?? process.env.GMAIL_BRIDGE_DEPLOYMENT_ID;
const SCRIPT_ID = flagValue("script-id") ?? process.env.GMAIL_BRIDGE_SCRIPT_ID;

function fail(message) {
  console.error(`ROLLBACK_ABORTED: ${message}`);
  console.error("remote state after a failed push/deploy is UNKNOWN; run --diagnose before retrying");
  process.exit(1);
}

function sha256(text) {
  return createHash("sha256").update(text).digest("hex");
}

// [Gates] Load and verify the bundled v3 source (no Git required).
let v3Source;
try {
  v3Source = readFileSync(COMPANION, "utf8").replace(/\r\n/g, "\n");
} catch (error) {
  console.error(`ROLLBACK_ABORTED: cannot read bundled v3 source: ${error.message}`);
  process.exit(1);
}
if (!v3Source.startsWith("var GMAIL_BRIDGE_VERSION = 3;")) {
  console.error("ROLLBACK_ABORTED: bundled source is not v3");
  process.exit(1);
}
const v3Digest = sha256(v3Source);
if (v3Digest !== V3_SHA256 || Buffer.byteLength(v3Source) !== V3_BYTES) {
  console.error(`ROLLBACK_ABORTED: bundled v3 source failed the hash gate (${v3Digest})`);
  process.exit(1);
}

function requireIds(needDeployment = true) {
  const missing = [];
  if (!SCRIPT_ID || !ID_PATTERN.test(SCRIPT_ID)) missing.push("--script-id / GMAIL_BRIDGE_SCRIPT_ID (controlled ops record)");
  if (needDeployment && (!DEPLOYMENT_ID || !ID_PATTERN.test(DEPLOYMENT_ID))) missing.push("--deployment-id / GMAIL_BRIDGE_DEPLOYMENT_ID (APP_SCRIPT_URL in tools/gmail/gmail_edge_common.py)");
  if (missing.length) {
    console.error(`ROLLBACK_ABORTED: ${missing.join("; ")}`);
    process.exit(1);
  }
  if (needDeployment && DEPLOYMENT_ID.startsWith("AKfycbx")) {
    console.error("ROLLBACK_ABORTED: refusing the deprecated @HEAD test deployment id; use the production deployment id");
    process.exit(1);
  }
}

// [Project-identity gate] The work directory must point at the expected Apps
// Script project. Checked BEFORE any write or push; mismatch exits with zero
// writes so a wrong .clasp.json can never receive the v3 source.
function verifyWorkdirProject() {
  let config;
  try {
    config = JSON.parse(readFileSync(resolve(WORKDIR, ".clasp.json"), "utf8"));
  } catch (error) {
    console.error(`ROLLBACK_ABORTED: cannot read ${WORKDIR}/.clasp.json (${error.message}); prepare the clasp workdir first`);
    process.exit(1);
  }
  if (config.scriptId !== SCRIPT_ID) {
    console.error(
      "ROLLBACK_ABORTED: workdir scriptId does not match the expected --script-id; refusing to touch this project",
    );
    process.exit(1);
  }
}

// clasp runner with a pinned version, a hard timeout, and timeout-vs-exit
// distinction. Returns true on success.
function runClasp(step, claspArgs, cwd) {
  const npx = process.platform === "win32" ? "npx.cmd" : "npx";
  const result = spawnSync(npx, [...CLASP, ...claspArgs], {
    cwd: cwd ?? WORKDIR,
    stdio: "inherit",
    shell: process.platform === "win32",
    timeout: CLASP_TIMEOUT_MS,
  });
  if (result.error || result.signal) {
    fail(`${step} did not complete (${result.error?.code ?? result.signal ?? "unknown"}; timeout ${CLASP_TIMEOUT_MS}ms)`);
  }
  if (result.status !== 0) fail(`${step} exited with status ${result.status}`);
  return true;
}

function liveProbe() {
  const probe = spawnSync(
    "python",
    ["tools/gmail/gmail_mcp_server.py", "list-threads", PROBE_CASE_ID, "--max-results=1"],
    { cwd: ROOT, encoding: "utf8", timeout: 300_000, maxBuffer: 1024 * 1024 },
  );
  if (probe.status !== 0) return { ok: false, bridgeVersion: null, reason: `probe exited ${probe.status}` };
  try {
    const document = JSON.parse(probe.stdout.trim());
    if (document.success !== true) return { ok: false, bridgeVersion: null, reason: `cloud error: ${document.error}` };
    return { ok: document.bridge_version === 3, bridgeVersion: document.bridge_version, reason: null };
  } catch (error) {
    return { ok: false, bridgeVersion: null, reason: `unparsable probe output: ${error.message}` };
  }
}

if (MODE_DIAGNOSE) {
  requireIds(false);
  verifyWorkdirProject();
  const scratch = resolve(ROOT, "tmp", `clasp-diagnose-${Date.now()}`);
  mkdirSync(scratch, { recursive: true });
  copyFileSync(resolve(WORKDIR, ".clasp.json"), resolve(scratch, ".clasp.json"));
  console.log("[diagnose] pulling current project source (isolated copy; workdir untouched)…");
  runClasp("[diagnose] clasp pull", ["pull"], scratch);
  let remoteClass = "unknown";
  try {
    const pulled = readFileSync(resolve(scratch, "Code.js"), "utf8").replace(/\r\n/g, "\n");
    const pulledDigest = sha256(pulled);
    remoteClass = pulledDigest === V3_SHA256 ? "v3" : pulledDigest === V4_SHA256 ? "v4" : `other (${pulledDigest.slice(0, 12)}…)`;
  } catch (_) { /* remoteClass stays unknown */ }
  rmSync(scratch, { recursive: true, force: true });
  console.log(`[diagnose] project source : ${remoteClass}`);
  console.log("[diagnose] deployments    :");
  runClasp("[diagnose] clasp deployments", ["deployments"]);
  const probe = liveProbe();
  console.log(`[diagnose] live endpoint  : bridge_version=${probe.bridgeVersion ?? "unknown"} (${probe.ok ? "v3 ✓" : probe.reason})`);
  process.exit(0);
}

console.log(`[1/6] bundled v3 source verified (sha256 ${v3Digest.slice(0, 12)}…, ${Buffer.byteLength(v3Source)} bytes)`);
requireIds();
verifyWorkdirProject();
console.log(`[2/6] clasp workdir project id verified against --script-id`);

if (MODE_DRY_RUN) {
  console.log("[dry-run] source and project-identity gates passed; nothing written, no remote changes");
  process.exit(0);
}

writeFileSync(resolve(WORKDIR, "Code.js"), v3Source);
console.log("[3/6] verified v3 source staged in tmp/clasp-bridge/Code.js");

runClasp("[4/6] clasp push", ["push"]);
runClasp("[5/6] clasp deploy", [
  "deploy",
  "--deploymentId", DEPLOYMENT_ID,
  "--description", `rollback-to-v3-ceecde43`,
]);

const probe = liveProbe();
if (!probe.ok) {
  fail(`live endpoint reports bridge_version=${probe.bridgeVersion ?? "unknown"} after deploy`);
}
console.log("[6/6] live endpoint probe reports bridge_version 3 — rollback verified");
