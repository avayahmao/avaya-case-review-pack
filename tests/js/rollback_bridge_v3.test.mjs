// Fault-injection tests for the v3 rollback tool. Every case runs the real
// script as a subprocess inside an isolated sandbox that mirrors the release
// layout (no .git), with fixture identity config, shimmed clasp, and fixture
// probe interpreters.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, chmodSync, copyFileSync, writeFileSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const CLOUD_DIR = resolve(here, "../../tools/gmail/cloud");
const SCRIPT = join(CLOUD_DIR, "rollback_bridge_v3.mjs");
const REAL_EDGE_COMMON = resolve(here, "../../tools/gmail/gmail_edge_common.py");
const TEST_SCRIPT_ID = "1TestScriptIdForRollbackTool000000000000";
const IS_WIN = process.platform === "win32";

function productionDeploymentId() {
  const source = readFileSync(REAL_EDGE_COMMON, "utf8");
  const assignment = source.match(/APP_SCRIPT_URL\s*=\s*\(([\s\S]*?)\)/);
  const url = (assignment[1].match(/"([^"]*)"/g) ?? []).map((l) => l.slice(1, -1)).join("");
  return url.match(/\/s\/(AKfycb[A-Za-z0-9_-]+)\//)[1];
}
const PRODUCTION_DEPLOYMENT_ID = productionDeploymentId();

const PROBE_FIXTURES = {
  ok: 'print(\'{"success":true,"bridge_version":3,"thread_ids":[],"next_page_token":"","complete":true}\')',
  v4: 'print(\'{"success":true,"bridge_version":4,"thread_ids":[],"next_page_token":"","complete":true}\')',
  cloudError: 'print(\'{"success":false,"error":"QUOTA"}\')',
  garbage: 'print("not json at all")',
  exit3: 'import sys\nsys.exit(3)\n',
  slow: 'import time\ntime.sleep(10)\n',
};

function buildSandbox({ probeFixture = "ok", shimExtraFile = false, shimClasp = true, tamperSnapshot = false } = {}) {
  const sandbox = mkdtempSync(join(tmpdir(), "rollback-tool-test-"));
  const cloud = join(sandbox, "tools", "gmail", "cloud");
  mkdirSync(cloud, { recursive: true });
  copyFileSync(join(CLOUD_DIR, "rollback_bridge_v3.mjs"), join(cloud, "rollback_bridge_v3.mjs"));
  copyFileSync(join(CLOUD_DIR, "rollback_bridge_v3.txt"), join(cloud, "rollback_bridge_v3.txt"));
  copyFileSync(join(CLOUD_DIR, "rollback_bridge_v3.appsscript.txt"), join(cloud, "rollback_bridge_v3.appsscript.txt"));
  if (tamperSnapshot) {
    writeFileSync(join(cloud, "rollback_bridge_v3.txt"), readFileSync(join(cloud, "rollback_bridge_v3.txt"), "utf8") + "\n// tampered");
  }
  copyFileSync(REAL_EDGE_COMMON, join(sandbox, "tools", "gmail", "gmail_edge_common.py"));
  copyFileSync(resolve(here, "../../tools/gmail/cloud/GmailMcpBridge.gs"), join(sandbox, "remote-fixture-v4.gs"));
  writeFileSync(join(sandbox, "tools", "gmail", "gmail_mcp_server.py"), PROBE_FIXTURES[probeFixture]);
  const claspBridge = join(sandbox, "tmp", "clasp-bridge");
  mkdirSync(claspBridge, { recursive: true });
  writeFileSync(join(claspBridge, ".clasp.json"), JSON.stringify({ scriptId: TEST_SCRIPT_ID, rootDir: "../evil" }));
  const shimDir = join(sandbox, "shims");
  if (shimClasp) {
    mkdirSync(shimDir, { recursive: true });
    const extra = shimExtraFile ? 'echo x > "%CD%\\Extra.gs"\n' : "";
    if (IS_WIN) {
      writeFileSync(join(shimDir, "npx.cmd"), [
        "@echo off",
        "echo %* | findstr /C:\"pull\" >nul",
        "if not errorlevel 1 (",
        "  copy /y \"%CLASP_SHIM_REMOTE%\" \"%CD%\\Code.js\" >nul",
        "  copy /y \"%CLASP_SHIM_MANIFEST%\" \"%CD%\\appsscript.json\" >nul",
        extra ? `  ${extra.trim()}` : "",
        ")",
        "exit /b 0",
        "",
      ].filter(Boolean).join("\r\n"));
    } else {
      const shimPathFile = join(shimDir, "npx");
      writeFileSync(shimPathFile, `#!/bin/sh
case "$*" in
  *pull*)
    cp "$CLASP_SHIM_REMOTE" "$PWD/Code.js"
    cp "$CLASP_SHIM_MANIFEST" "$PWD/appsscript.json"
    ${shimExtraFile ? 'echo x > "$PWD/Extra.gs"' : ":"}
    ;;
esac
exit 0
`);
      chmodSync(shimPathFile, 0o755);
    }
  }
  return sandbox;
}

function snapshotTree(root) {
  const files = new Map();
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      const info = statSync(path);
      if (info.isDirectory()) walk(path);
      else files.set(path.slice(root.length), info.size);
    }
  };
  walk(root);
  return files;
}

function stagingLeftovers(sandbox) {
  const tmp = join(sandbox, "tmp");
  if (!statSync(tmp, { throwIfNoEntry: false })) return [];
  return readdirSync(tmp).filter((name) => name.startsWith("clasp-staging-rollback-"));
}

function run(sandbox, scriptArgs, env) {
  const script = join(sandbox, "tools", "gmail", "cloud", "rollback_bridge_v3.mjs");
  return spawnSync(process.execPath, [script, ...scriptArgs], {
    cwd: sandbox,
    encoding: "utf8",
    timeout: 120_000,
    env: {
      ...process.env,
      CLASP_SHIM_REMOTE: join(sandbox, "remote-fixture-v4.gs"),
      CLASP_SHIM_MANIFEST: join(sandbox, "tools", "gmail", "cloud", "rollback_bridge_v3.appsscript.txt"),
      ...env,
    },
  });
}

const shimPath = (sandbox) => join(sandbox, "shims") + (IS_WIN ? "" : "");

function shimEnv(sandbox) {
  const delimiter = IS_WIN ? ";" : ":";
  return { PATH: shimPath(sandbox) + delimiter + process.env.PATH };
}

const noNpxEnv = () => {
  // Keep only system directories so npx/python cannot be found.
  const systemPath = IS_WIN ? "C:\\Windows\\System32;C:\\Windows" : "/usr/bin:/bin";
  return { PATH: systemPath };
};

const GOOD_ARGS = ["--script-id=" + TEST_SCRIPT_ID, "--deployment-id=" + PRODUCTION_DEPLOYMENT_ID];

test("dry-run passes every gate, writes nothing, and needs no clasp", () => {
  const sandbox = buildSandbox();
  const before = snapshotTree(sandbox);
  const result = run(sandbox, ["--dry-run", ...GOOD_ARGS]);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /all gates passed; nothing written/);
  assert.deepEqual(snapshotTree(sandbox), before);
  rmSync(sandbox, { recursive: true, force: true });
});

test("dry-run rejects a mismatched workdir scriptId with zero writes", () => {
  const sandbox = buildSandbox();
  const before = snapshotTree(sandbox);
  const result = run(sandbox, ["--dry-run", "--script-id=1AnotherProject0000000000000000000000", "--deployment-id=" + PRODUCTION_DEPLOYMENT_ID]);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /workdir scriptId does not match/);
  assert.deepEqual(snapshotTree(sandbox), before);
  rmSync(sandbox, { recursive: true, force: true });
});

test("dry-run rejects a deployment id that is not the production endpoint", () => {
  const sandbox = buildSandbox();
  const result = run(sandbox, ["--dry-run", "--script-id=" + TEST_SCRIPT_ID, "--deployment-id=AKfycbzQpdrDsBLQhUU951LcZ4DwGxEzsgwH_cuKJKDe7zY"]);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /does not match the deployment id embedded in APP_SCRIPT_URL/);
  rmSync(sandbox, { recursive: true, force: true });
});

test("missing identity reference fails safely without Git history", () => {
  const sandbox = buildSandbox();
  rmSync(join(sandbox, "tmp"), { recursive: true, force: true });
  const result = run(sandbox, ["--dry-run", ...GOOD_ARGS]);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /prepare the clasp identity reference first/);
  assert.equal(statSync(join(sandbox, "tmp"), { throwIfNoEntry: false }), undefined);
  rmSync(sandbox, { recursive: true, force: true });
});

test("a tampered v3 snapshot fails the hash gate", () => {
  const sandbox = buildSandbox({ tamperSnapshot: true });
  const result = run(sandbox, ["--dry-run", ...GOOD_ARGS]);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /hash gate/);
  rmSync(sandbox, { recursive: true, force: true });
});

test("clasp launch failure still cleans the staging directory", () => {
  const sandbox = buildSandbox();
  const result = run(sandbox, GOOD_ARGS, noNpxEnv());
  assert.equal(result.status, 1, result.stderr);
  assert.match(result.stderr, /ROLLBACK_ABORTED/);
  assert.deepEqual(stagingLeftovers(sandbox), [], "staging must be removed on failure");
  rmSync(sandbox, { recursive: true, force: true });
});

test("remote inventory with an extra file aborts before push and cleans staging", () => {
  const sandbox = buildSandbox({ shimExtraFile: true });
  const result = run(sandbox, GOOD_ARGS, shimEnv(sandbox));
  assert.equal(result.status, 1, result.stderr);
  assert.match(result.stderr, /does not match the approved set/);
  assert.match(result.stderr, /Extra\.gs/);
  assert.deepEqual(stagingLeftovers(sandbox), [], "staging must be removed after inventory abort");
  rmSync(sandbox, { recursive: true, force: true });
});

test("full success path verifies the probe and leaves no staging behind", () => {
  const sandbox = buildSandbox({ probeFixture: "ok" });
  const identityBefore = readFileSync(join(sandbox, "tmp", "clasp-bridge", ".clasp.json"), "utf8");
  const result = run(sandbox, GOOD_ARGS, shimEnv(sandbox));
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /remote inventory verified; current remote source is v4/);
  assert.match(result.stdout, /rollback verified/);
  assert.deepEqual(stagingLeftovers(sandbox), []);
  assert.equal(readFileSync(join(sandbox, "tmp", "clasp-bridge", ".clasp.json"), "utf8"), identityBefore);
  rmSync(sandbox, { recursive: true, force: true });
});

test("probe failure: missing interpreter is reported as tool-missing", () => {
  const sandbox = buildSandbox({ probeFixture: "ok" });
  const result = run(sandbox, [...GOOD_ARGS, "--python=definitely-missing-interpreter"], shimEnv(sandbox));
  assert.equal(result.status, 1);
  assert.match(result.stderr, /tool-missing/);
  assert.match(result.stderr, /--python=<executable>/);
  assert.deepEqual(stagingLeftovers(sandbox), []);
  rmSync(sandbox, { recursive: true, force: true });
});

test("probe failure: non-zero interpreter exit is reported as cli-exit", () => {
  const sandbox = buildSandbox({ probeFixture: "exit3" });
  const result = run(sandbox, GOOD_ARGS, shimEnv(sandbox));
  assert.equal(result.status, 1);
  assert.match(result.stderr, /cli-exit/);
  rmSync(sandbox, { recursive: true, force: true });
});

test("probe failure: cloud error field is reported as cloud-error", () => {
  const sandbox = buildSandbox({ probeFixture: "cloudError" });
  const result = run(sandbox, GOOD_ARGS, shimEnv(sandbox));
  assert.equal(result.status, 1);
  assert.match(result.stderr, /\(cloud-error\): cloud endpoint error: QUOTA/);
  rmSync(sandbox, { recursive: true, force: true });
});

test("probe failure: wrong live version is reported as version", () => {
  const sandbox = buildSandbox({ probeFixture: "v4" });
  const result = run(sandbox, GOOD_ARGS, shimEnv(sandbox));
  assert.equal(result.status, 1);
  assert.match(result.stderr, /\(version\): live endpoint reports bridge_version=4/);
  rmSync(sandbox, { recursive: true, force: true });
});

test("probe failure: garbage output is reported as unparsable", () => {
  const sandbox = buildSandbox({ probeFixture: "garbage" });
  const result = run(sandbox, GOOD_ARGS, shimEnv(sandbox));
  assert.equal(result.status, 1);
  assert.match(result.stderr, /unparsable/);
  rmSync(sandbox, { recursive: true, force: true });
});

test("probe failure: slow interpreter is reported as tool-timeout, not tool-missing", () => {
  const sandbox = buildSandbox({ probeFixture: "slow" });
  const result = run(sandbox, GOOD_ARGS, { ...shimEnv(sandbox), ROLLBACK_PROBE_TIMEOUT_MS: "1500" });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /tool-timeout/);
  assert.doesNotMatch(result.stderr, /tool-missing/);
  rmSync(sandbox, { recursive: true, force: true });
});
