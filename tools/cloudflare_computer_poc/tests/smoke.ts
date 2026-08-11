/**
 * R0A local smoke test.
 *
 * Drives the real local development environment (`wrangler dev --local`)
 * over HTTP and verifies:
 *   1. workspace persistence across a full wrangler restart (marker),
 *   2. exact-SHA git materialization + bounded inspection (SUCCESS),
 *   3. workspace artifacts (result.json / report.md / job-manifest.json),
 *   4. exact-SHA mismatch -> FAIL_CLOSED,
 *   5. missing commit SHA -> rejected before execution.
 *
 * Run: npm run smoke   (requires network for the GitHub clone)
 */

import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const POC_DIR = resolve(fileURLToPath(new URL("..", import.meta.url)));
const WRANGLER = join(POC_DIR, "node_modules", ".bin", "wrangler");
const PORT = 8799;
const BASE = `http://127.0.0.1:${PORT}`;
const REPO_URL = "https://github.com/Luke808real/a-share-limit-pullback.git";
const REPO_COMMIT = "1cb5fb7a1792edccc18c70207340980377cbd4eb";

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
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) {
      throw new Error(`wrangler exited early with code ${proc.exitCode}`);
    }
    try {
      const res = await fetch(BASE, { signal: AbortSignal.timeout(2_000) });
      if (res.status === 200) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error("wrangler dev did not become ready in 90s");
}

async function startWrangler(stateDir: string): Promise<ChildProcess> {
  const out = join(stateDir, "wrangler-out.log");
  const err = join(stateDir, "wrangler-err.log");
  const { open } = await import("node:fs/promises");
  const outFd = await open(out, "w");
  const errFd = await open(err, "w");
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

async function post(path: string, body: unknown, timeoutMs = 420_000): Promise<Response> {
  return fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
}

function smokeManifest(taskId: string, repoCommit: string): Record<string, unknown> {
  return {
    task_id: taskId,
    repo_url: REPO_URL,
    repo_commit: repoCommit,
    created_at: new Date().toISOString(),
    purpose: "R0A smoke fixture: exact-commit pin, bounded inspection (research only)",
    allowed_commands: [
      "git:status",
      "git:log-1",
      "read:README.md",
      "read:docs/project-operating-model.md",
    ],
    network_policy: { egress: "none" },
    input_files: ["README.md", "docs/project-operating-model.md"],
    output_files: ["result.json", "report.md", "job-manifest.json"],
  };
}

/** Re-emit an object with its top-level keys in reverse insertion order. */
function reorderKeys<T extends object>(obj: T): T {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(obj).reverse()) {
    out[k] = (obj as Record<string, unknown>)[k];
  }
  return out as T;
}

async function main(): Promise<void> {
  const stateDir = await mkdtemp(join(tmpdir(), "cf-r0a-"));
  let wrangler: ChildProcess | null = null;

  try {
    // ---------- 1. persistence across a full wrangler restart ----------
    wrangler = await startWrangler(stateDir);
    await waitReady(wrangler);

    const persistTask = `smoke-persist-${Date.now()}`;
    const marker = "r0a-persistence-marker-1";
    const w1 = await post("/marker", { task_id: persistTask, op: "write", content: marker });
    const w1b = (await w1.json()) as { ok: boolean };
    if (w1.status !== 200 || w1b.ok !== true) fail("persistence write", JSON.stringify(w1b));
    ok("persistence write", persistTask);

    await stopWrangler(wrangler);
    wrangler = null;
    wrangler = await startWrangler(stateDir);
    await waitReady(wrangler);

    const r1 = await post("/marker", { task_id: persistTask, op: "read" }, 30_000);
    const r1b = (await r1.json()) as { ok: boolean; marker: string | null };
    if (r1.status !== 200 || r1b.ok !== true || r1b.marker !== marker) {
      fail("persistence read after restart", JSON.stringify({ status: r1.status, body: r1b }));
    }
    ok("persistence read after restart", "marker survived wrangler restart (DO SQLite state on disk)");

    // ---------- 2. exact-SHA materialization + bounded inspection ----------
    const runTask = `smoke-run-${Date.now()}`;
    const run = await post("/run", smokeManifest(runTask, REPO_COMMIT));
    const runBody = (await run.json()) as Record<string, unknown>;
    if (run.status !== 200) fail("positive run http", JSON.stringify(runBody));
    if (runBody.result_status !== "SUCCESS") fail("positive run status", JSON.stringify(runBody));
    if (runBody.commit_match !== true) fail("positive run commit_match", JSON.stringify(runBody));
    if (runBody.actual_commit !== REPO_COMMIT) {
      fail("positive run actual_commit", JSON.stringify(runBody));
    }
    const exitCodes = runBody.exit_codes as number[];
    if (exitCodes.length !== 4 || exitCodes.some((c) => c !== 0)) {
      fail("positive run exit_codes", JSON.stringify(runBody));
    }
    ok("exact-SHA materialization", `commit_match=true, ${String(runBody.materialization)}`);
    ok("bounded inspection", `4 commands, exit codes [${exitCodes.join(",")}]`);

    // ---------- 3. workspace artifacts ----------
    for (const path of ["/result.json", "/report.md", "/job-manifest.json"]) {
      const f = await post("/file", { task_id: runTask, path, max_bytes: 500 }, 30_000);
      const fb = (await f.json()) as { exists: boolean };
      if (f.status !== 200 || fb.exists !== true) fail("workspace artifact", `${path} missing`);
    }
    ok("workspace artifacts", "result.json + report.md + job-manifest.json present in VFS");

    // ---------- 4. immutable manifest: A->A replay, A->B conflict ----------
    const conflictTask = `smoke-conflict-${Date.now()}`;
    const manifestA = smokeManifest(conflictTask, REPO_COMMIT);
    const runA = await post("/run", manifestA);
    const runABody = (await runA.json()) as Record<string, unknown>;
    if (runA.status !== 200 || runABody.result_status !== "SUCCESS") {
      fail("conflict A run", JSON.stringify(runABody));
    }
    ok("manifest A first run", "SUCCESS");

    // Replay A with reordered JSON keys: canonical comparison must
    // treat it as the same semantic manifest.
    const reordered = reorderKeys(manifestA);
    const runA2 = await post("/run", reordered);
    const runA2Body = (await runA2.json()) as Record<string, unknown>;
    if (runA2.status !== 200 || runA2Body.result_status !== "SUCCESS") {
      fail("manifest A replay (key order)", JSON.stringify(runA2Body));
    }
    ok("manifest A -> A replay", "idempotent SUCCESS despite key reorder");

    const storedBefore = (await (
      await post("/file", { task_id: conflictTask, path: "/job-manifest.json", max_bytes: 4096 }, 30_000)
    ).json()) as { exists: boolean; bytes: number; head: string };
    if (!storedBefore.exists) fail("conflict stored manifest read", "missing");
    const resultBefore = (await (
      await post("/file", { task_id: conflictTask, path: "/result.json", max_bytes: 8192 }, 30_000)
    ).json()) as { exists: boolean; bytes: number; head: string };
    if (!resultBefore.exists) fail("conflict stored result read", "missing");

    // B differs semantically (purpose), same task_id.
    const manifestB = { ...manifestA, purpose: "DIFFERENT manifest for conflict test" };
    const runB = await post("/run", manifestB, 60_000);
    const runBBody = (await runB.json()) as Record<string, unknown>;
    if (
      runB.status !== 409 ||
      runBBody.error !== "MANIFEST_CONFLICT" ||
      runBBody.result_status !== "FAIL_CLOSED"
    ) {
      fail("manifest A -> B conflict", JSON.stringify({ status: runB.status, body: runBBody }));
    }
    ok("manifest A -> B rejected", "409 MANIFEST_CONFLICT, FAIL_CLOSED");

    const storedAfter = (await (
      await post("/file", { task_id: conflictTask, path: "/job-manifest.json", max_bytes: 4096 }, 30_000)
    ).json()) as { exists: boolean; bytes: number; head: string };
    if (
      !storedAfter.exists ||
      storedAfter.bytes !== storedBefore.bytes ||
      storedAfter.head !== storedBefore.head
    ) {
      fail("A -> B mutated stored manifest", JSON.stringify({ before: storedBefore, after: storedAfter }));
    }
    const resultAfter = (await (
      await post("/file", { task_id: conflictTask, path: "/result.json", max_bytes: 8192 }, 30_000)
    ).json()) as { exists: boolean; bytes: number; head: string };
    if (
      !resultAfter.exists ||
      resultAfter.bytes !== resultBefore.bytes ||
      resultAfter.head !== resultBefore.head
    ) {
      fail(
        "A -> B mutated stored result",
        JSON.stringify({ before: resultBefore, after: resultAfter }),
      );
    }
    ok("A -> B does not mutate stored A", "job-manifest.json and result.json unchanged");

    // ---------- 5. exact-SHA mismatch -> FAIL_CLOSED ----------
    const negTask = `smoke-neg-${Date.now()}`;
    const neg = await post("/run", smokeManifest(negTask, "0000000000000000000000000000000000000000"));
    const negBody = (await neg.json()) as Record<string, unknown>;
    if (neg.status !== 200 || negBody.result_status !== "FAIL_CLOSED" || negBody.commit_match !== false) {
      fail("mismatch negative", JSON.stringify({ status: neg.status, body: negBody }));
    }
    ok("exact-SHA mismatch negative", "result_status=FAIL_CLOSED, commit_match=false");

    // ---------- 6. missing commit SHA rejected ----------
    const missing = smokeManifest(`smoke-missing-${Date.now()}`, REPO_COMMIT);
    delete missing.repo_commit;
    const miss = await post("/run", missing, 30_000);
    const missBody = (await miss.json()) as Record<string, unknown>;
    if (miss.status !== 400 || !String(missBody.error).includes("repo_commit")) {
      fail("missing-SHA rejection", JSON.stringify({ status: miss.status, body: missBody }));
    }
    ok("missing-SHA rejection", "400, manifest rejected before execution");
  } catch (err) {
    fail("smoke", String(err));
  } finally {
    if (wrangler) await stopWrangler(wrangler);
    await rm(stateDir, { recursive: true, force: true });
  }

  const failed = results.filter((r) => r.startsWith("FAIL"));
  console.log(`\nSMOKE SUMMARY: ${results.length - failed.length}/${results.length} passed`);
  if (failed.length > 0) process.exit(1);
}

await main();
