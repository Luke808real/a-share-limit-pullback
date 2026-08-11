/**
 * R0B real Container-backed smoke.
 *
 * Drives `wrangler dev --local` and runs the frozen PYTEST_CONFIG_V01
 * profile (python -m pytest -q tests/test_config.py) through the
 * Cloudflare Computer Container backend, then verifies artifacts and
 * hashes from OUTSIDE via the bounded /file surface.
 *
 * The first /run triggers the container image build (slow on this
 * network); the HTTP timeout for that call is generous.
 *
 * Run: npm run smoke:r0b
 */

import { spawn, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, rm, open } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const POC_DIR = resolve(fileURLToPath(new URL("..", import.meta.url)));
const WRANGLER = join(POC_DIR, "node_modules", ".bin", "wrangler");
const PORT = 8798;
const BASE = `http://127.0.0.1:${PORT}`;
const REPO_URL = "https://github.com/Luke808real/a-share-limit-pullback.git";
const PROFILE_COMMIT = "dbf411e3f1fabd09aa9def2c2578c57e42fae21e";

const results: string[] = [];

function ok(name: string, detail = ""): void {
  results.push(`PASS ${name}${detail ? ` — ${detail}` : ""}`);
  console.log(`PASS ${name}${detail ? ` — ${detail}` : ""}`);
}

function fail(name: string, detail: string): never {
  results.push(`FAIL ${name} — ${detail}`);
  console.error(`FAIL ${name} — ${detail}`);
  throw new Error(`${name}: ${detail}`);
}

async function waitReady(proc: ChildProcess): Promise<void> {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) throw new Error(`wrangler exited early (${proc.exitCode})`);
    try {
      const res = await fetch(BASE, { signal: AbortSignal.timeout(2_000) });
      if (res.status === 200) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("wrangler dev did not become ready in 120s");
}

async function startWrangler(stateDir: string): Promise<ChildProcess> {
  const outFd = await open(join(stateDir, "wrangler-out.log"), "w");
  const errFd = await open(join(stateDir, "wrangler-err.log"), "w");
  const proc = spawn(WRANGLER, ["dev", "--local", "--port", String(PORT), "--persist-to", stateDir], {
    cwd: POC_DIR,
    env: { ...process.env, CI: "1", WRANGLER_SEND_METRICS: "false" },
    stdio: ["ignore", outFd.fd, errFd.fd],
  });
  proc.on("exit", () => {
    void outFd.close();
    void errFd.close();
  });
  return proc;
}

async function stopWrangler(proc: ChildProcess): Promise<void> {
  if (proc.exitCode !== null) return;
  proc.kill("SIGTERM");
  const deadline = Date.now() + 15_000;
  while (proc.exitCode === null && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 200));
  }
  if (proc.exitCode === null) proc.kill("SIGKILL");
}

async function post(path: string, body: unknown, timeoutMs: number): Promise<Response> {
  return fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
}

function r0bManifest(taskId: string): Record<string, unknown> {
  return {
    task_id: taskId,
    repo_url: REPO_URL,
    repo_commit: PROFILE_COMMIT,
    created_at: new Date().toISOString(),
    purpose: "R0B smoke fixture: frozen PYTEST_CONFIG_V01 container execution (research only)",
    allowed_commands: [
      "git:status",
      "git:log-1",
      "read:README.md",
      "read:docs/project-operating-model.md",
    ],
    network_policy: { egress: "none" },
    input_files: ["README.md", "docs/project-operating-model.md"],
    output_files: [
      "result.json",
      "report.md",
      "job-manifest.json",
      "execution-result.json",
      "execution-stdout.txt",
      "execution-stderr.txt",
    ],
    execution_profile: "PYTEST_CONFIG_V01",
  };
}

function sha256Hex(s: string): string {
  return createHash("sha256").update(s, "utf8").digest("hex");
}

async function readFileFull(taskId: string, path: string): Promise<{ exists: boolean; bytes: number; head: string }> {
  const res = await post("/file", { task_id: taskId, path, max_bytes: 64 * 1024 }, 30_000);
  return (await res.json()) as { exists: boolean; bytes: number; head: string };
}

async function main(): Promise<void> {
  const stateDir = await mkdtemp(join(tmpdir(), "cf-r0b-"));
  let wrangler: ChildProcess | null = null;

  try {
    wrangler = await startWrangler(stateDir);
    await waitReady(wrangler);

    // ---------- 1. positive: real container-backed PYTEST_CONFIG_V01 ----------
    const runTask = `r0b-run-${Date.now()}`;
    // First run includes the container image build: generous timeout.
    const run = await post("/run", r0bManifest(runTask), 60 * 60_000);
    const body = (await run.json()) as Record<string, unknown>;
    if (run.status !== 200) fail("r0b positive http", JSON.stringify(body).slice(0, 2000));
    if (body.result_status !== "SUCCESS") fail("r0b r0a status", JSON.stringify(body).slice(0, 2000));
    const exec = body.execution as Record<string, unknown>;
    if (!exec || exec.result_status !== "SUCCESS") {
      fail("r0b execution status", JSON.stringify(exec).slice(0, 4000));
    }
    if (exec.execution_status !== "EXECUTION_SUCCEEDED") {
      fail("r0b execution_status", JSON.stringify(exec).slice(0, 4000));
    }
    if (exec.commit_match !== true || exec.actual_commit !== PROFILE_COMMIT) {
      fail("r0b commit pin", JSON.stringify(exec).slice(0, 2000));
    }
    if (exec.exit_code !== 0) fail("r0b exit_code", String(exec.exit_code));
    if (exec.profile_id !== "PYTEST_CONFIG_V01") fail("r0b profile", String(exec.profile_id));
    if (exec.backend !== "container-shell") fail("r0b backend", String(exec.backend));
    const pyver = String(exec.python_version);
    if (!/^Python 3\.(11|12)\./.test(pyver)) {
      fail("python version allowed", pyver);
    }
    if (exec.repo_state_before !== "clean") fail("repo state before", String(exec.repo_state_before));
    ok("container-backed PYTEST_CONFIG_V01", `python ${pyver}, exit 0, backend ${String(exec.backend)}`);

    // ---------- 2. artifacts present + independent hash verification ----------
    for (const path of ["/execution-result.json", "/execution-stdout.txt", "/execution-stderr.txt"]) {
      const f = await readFileFull(runTask, path);
      if (!f.exists) fail("execution artifact", `${path} missing`);
      if (f.bytes > 64 * 1024) fail("execution artifact byte cap", `${path} bytes=${f.bytes}`);
    }
    const resultFile = await readFileFull(runTask, "/execution-result.json");
    const recorded = JSON.parse(resultFile.head) as Record<string, unknown>;
    const stdoutFile = await readFileFull(runTask, "/execution-stdout.txt");
    const stderrFile = await readFileFull(runTask, "/execution-stderr.txt");
    if (stdoutFile.head.length !== stdoutFile.bytes || stderrFile.head.length !== stderrFile.bytes) {
      fail("artifact full readback", "bounded file surface did not return full ASCII content");
    }
    const stdoutHash = sha256Hex(stdoutFile.head);
    const stderrHash = sha256Hex(stderrFile.head);
    if (recorded.stdout_sha256 !== stdoutHash || recorded.stderr_sha256 !== stderrHash) {
      fail("artifact hash match", `stdout ${recorded.stdout_sha256} vs ${stdoutHash}; stderr ${recorded.stderr_sha256} vs ${stderrHash}`);
    }
    const selfRaw = JSON.stringify({ ...recorded, execution_result_sha256: undefined }, null, 2);
    if (recorded.execution_result_sha256 !== sha256Hex(selfRaw)) {
      fail("execution-result self hash", "self-hash mismatch on readback");
    }
    ok("artifacts + hashes", "execution-result.json / stdout / stderr present; read-back SHA-256 verified from outside");

    // ---------- 3. A->A replay (idempotent) ----------
    const run2 = await post("/run", r0bManifest(runTask), 10 * 60_000);
    const body2 = (await run2.json()) as Record<string, unknown>;
    const exec2 = body2.execution as Record<string, unknown>;
    if (run2.status !== 200 || exec2?.result_status !== "SUCCESS") {
      fail("r0b A->A replay", JSON.stringify(exec2).slice(0, 2000));
    }
    ok("r0b A -> A replay", "idempotent SUCCESS");

    // ---------- 4. A->B manifest conflict, stored artifacts preserved ----------
    const before = await readFileFull(runTask, "/execution-result.json");
    const manifestB = { ...r0bManifest(runTask), purpose: "DIFFERENT manifest for conflict test" };
    const runB = await post("/run", manifestB, 60_000);
    const bodyB = (await runB.json()) as Record<string, unknown>;
    if (runB.status !== 409 || bodyB.error !== "MANIFEST_CONFLICT") {
      fail("r0b A->B conflict", JSON.stringify({ status: runB.status, body: bodyB }));
    }
    const after = await readFileFull(runTask, "/execution-result.json");
    if (after.bytes !== before.bytes || after.head !== before.head) {
      fail("r0b A->B preserved artifacts", "execution-result.json changed after conflict");
    }
    ok("r0b A -> B MANIFEST_CONFLICT", "409; execution artifacts byte-identical");

    // ---------- 5. unknown profile -> FAIL_CLOSED, no execution ----------
    const badTask = `r0b-bad-profile-${Date.now()}`;
    const bad = r0bManifest(badTask);
    bad.execution_profile = "NOPE_PROFILE";
    const badRes = await post("/run", bad, 60_000);
    const badBody = (await badRes.json()) as Record<string, unknown>;
    if (badRes.status !== 400 || !String(badBody.error).includes("EXECUTION_PROFILE_NOT_ALLOWED")) {
      fail("unknown profile", JSON.stringify({ status: badRes.status, body: badBody }));
    }
    const noArtifact = await readFileFull(badTask, "/execution-result.json");
    if (noArtifact.exists) fail("unknown profile executed", "execution artifact exists");
    ok("unknown profile", "400 EXECUTION_PROFILE_NOT_ALLOWED; no execution artifacts");

    // ---------- 6. wrong repo_commit (differs from frozen profile) ----------
    const wrongTask = `r0b-wrong-commit-${Date.now()}`;
    const wrong = r0bManifest(wrongTask);
    wrong.repo_commit = "112bc94218be6dc530e4803cabec288eede6175d";
    const wrongRes = await post("/run", wrong, 60_000);
    const wrongBody = (await wrongRes.json()) as Record<string, unknown>;
    if (wrongRes.status !== 400 || !String(wrongBody.error).includes("frozen PYTEST_CONFIG_V01 profile commit")) {
      fail("wrong repo_commit", JSON.stringify({ status: wrongRes.status, body: wrongBody }));
    }
    const wrongArtifact = await readFileFull(wrongTask, "/execution-result.json");
    if (wrongArtifact.exists) fail("wrong commit executed", "execution artifact exists");
    ok("wrong repo_commit", "rejected before execution (frozen profile commit)");
  } catch (err) {
    fail("smoke-r0b", String(err));
  } finally {
    if (wrangler) await stopWrangler(wrangler);
    await rm(stateDir, { recursive: true, force: true });
  }

  const failed = results.filter((r) => r.startsWith("FAIL"));
  console.log(`\nR0B SMOKE SUMMARY: ${results.length - failed.length}/${results.length} passed`);
  if (failed.length > 0) process.exit(1);
}

await main();
