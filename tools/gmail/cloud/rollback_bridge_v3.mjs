#!/usr/bin/env node
// Fail-fast rollback of the Gmail cloud bridge Web App to bridge v3.
//
// This is deliberately NOT an atomic transaction: `clasp push` and
// `clasp deploy` are two independent remote changes. Per-stage intermediate
// states and recovery actions:
//
//   stage              failure effect                       recovery
//   -----------------  ----------------------------------  ------------------------
//   extract + gates    none (local read-only)              fix environment, rerun
//   clasp push         project source unchanged, still v4  rerun this script
//   clasp deploy       project source v3, deployment still v4
//                                                       (pinned to its own
//                                                       version, so the live
//                                                       endpoint keeps serving
//                                                       v4)                rerun this script
//   version probe      deployment updated but endpoint     rerun probe; if it
//                      still reports v4                    still fails, treat as
//                                                       a rollback failure and
//                                                       investigate before use
//
// Every rerun is safe: push creates a fresh project version with the same
// verified v3 content and deploy re-points the existing deployment.
//
// Usage:
//   node tools/gmail/cloud/rollback_bridge_v3.mjs --dry-run
//   node tools/gmail/cloud/rollback_bridge_v3.mjs --deployment-id=<id>
//
// --deployment-id (or env GMAIL_BRIDGE_DEPLOYMENT_ID) is the deployment ID
// from APP_SCRIPT_URL in tools/gmail/gmail_edge_common.py; updating that
// deployment keeps the production endpoint URL unchanged. --dry-run performs
// extraction and hash verification only and writes nothing.
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const WORKDIR = resolve(ROOT, "tmp", "clasp-bridge");
const V3_SHA = "8fe39e47a9ae2149a22ede22bf69fcf566a1a872";
const V3_SHA256 = "ceecde437612bd3f99427907b7797c37df68b585715ea58c8489d02667bb2119";
const V3_BYTES = 39525;
const PROBE_CASE_ID = "INC0000001"; // syntactically valid, expected zero-result
const args = process.argv.slice(2);
const DRY_RUN = args.includes("--dry-run");
const deploymentIdArg = args.find((arg) => arg.startsWith("--deployment-id="));
const DEPLOYMENT_ID = deploymentIdArg
  ? deploymentIdArg.slice("--deployment-id=".length)
  : process.env.GMAIL_BRIDGE_DEPLOYMENT_ID;

function fail(message, recovery) {
  console.error(`ROLLBACK_ABORTED: ${message}`);
  if (recovery) console.error(`recovery: ${recovery}`);
  process.exit(1);
}

// [1/5] Extract the pinned v3 source and gate on identity + content hash.
let text;
try {
  const blob = execFileSync(
    "git",
    ["show", `${V3_SHA}:tools/gmail/cloud/GmailMcpBridge.gs`],
    { cwd: ROOT, maxBuffer: 64 * 1024 * 1024 },
  );
  text = blob.toString("utf8").replace(/\r\n/g, "\n");
} catch (error) {
  fail(`git extraction failed: ${error.message}`, "local read-only, fix and rerun");
}
if (!text.startsWith("var GMAIL_BRIDGE_VERSION = 3;")) {
  fail("pinned blob is not v3 source", "local read-only, fix and rerun");
}
const digest = createHash("sha256").update(text).digest("hex");
if (digest !== V3_SHA256 || Buffer.byteLength(text) !== V3_BYTES) {
  fail(`hash gate failed: sha256=${digest} bytes=${Buffer.byteLength(text)}`, "local read-only, fix and rerun");
}
console.log(`[1/5] v3 source extracted and verified (sha256 ${digest.slice(0, 12)}…, ${Buffer.byteLength(text)} bytes)`);

if (DRY_RUN) {
  console.log("[dry-run] extraction and hash gate passed; nothing written, no remote changes");
  process.exit(0);
}

if (!DEPLOYMENT_ID || !/^[A-Za-z0-9_-]+$/.test(DEPLOYMENT_ID)) {
  fail("missing --deployment-id or GMAIL_BRIDGE_DEPLOYMENT_ID (see APP_SCRIPT_URL in tools/gmail/gmail_edge_common.py)");
}
if (DEPLOYMENT_ID.startsWith("AKfycbx")) {
  fail("refusing deployment id from the deprecated @HEAD test deployment; use the production deployment id");
}

writeFileSync(resolve(WORKDIR, "Code.js"), text);
console.log("[2/5] verified v3 source staged in tmp/clasp-bridge/Code.js");

// Space-free arguments only: win32 .cmd spawning requires shell:true, where
// argument quoting cannot be trusted.
function run(step, cliArgs, recovery) {
  const npx = process.platform === "win32" ? "npx.cmd" : "npx";
  const result = spawnSync(npx, ["--yes", "@google/clasp", ...cliArgs], {
    cwd: WORKDIR,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.status !== 0) fail(`${step} exited with status ${result.status}`, recovery);
}

run("[3/5] clasp push", ["push"], "project source may still be v4; rerun this script");

run("[4/5] clasp deploy", [
  "deploy",
  "--deploymentId", DEPLOYMENT_ID,
  "--description", `rollback-to-v3-${V3_SHA.slice(0, 7)}`,
], "project source is v3, live endpoint still serves v4 (deployment pins its version); rerun this script");

// [5/5] Success gate: the live endpoint must actually report v3.
const probe = spawnSync(
  "python",
  [
    "tools/gmail/gmail_mcp_server.py",
    "list-threads", PROBE_CASE_ID,
    "--max-results=1",
  ],
  { cwd: ROOT, encoding: "utf8", timeout: 300_000, maxBuffer: 1024 * 1024 },
);
let bridgeVersion = null;
if (probe.status === 0) {
  try {
    bridgeVersion = JSON.parse(probe.stdout.trim()).bridge_version;
  } catch (_) { /* handled below */ }
}
if (bridgeVersion !== 3) {
  fail(
    `live endpoint still reports bridge_version=${bridgeVersion ?? "unknown"} after deploy`,
    "treat the rollback as incomplete: do not close out until the probe reports 3",
  );
}
console.log("[5/5] live endpoint probe reports bridge_version 3 — rollback verified");
