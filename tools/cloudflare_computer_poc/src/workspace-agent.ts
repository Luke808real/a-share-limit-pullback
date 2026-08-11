import {
  Workspace,
  type DurableObjectStorageLike,
} from "@cloudflare/computer";
import {
  CloudflareContainerBackend,
  withWorkspaceContainer,
} from "@cloudflare/computer/backends/container";
import { createGitClient } from "@cloudflare/computer/git";
import { DurableObject } from "cloudflare:workers";
import { runBoundedCommands, type CommandDetail } from "./commands";
import {
  EXECUTION_RESULT_PATH,
  EXECUTION_STDOUT_PATH,
  EXECUTION_STDERR_PATH,
  boundArtifacts,
  buildExecutionResult,
  combineResultStatus,
  CONTAINER_EGRESS_ENFORCEMENT_AVAILABLE,
  finalizeExecutionArtifacts,
  type ArtifactStore,
  type ExecutionResult,
} from "./execution";
import { checkReplay, ManifestConflictError, type JobManifest, type ManifestConflict } from "./manifest";
import { resolveProfile } from "./profiles";
import {
  buildResult,
  buildWorkspaceReport,
  truncateUtf8,
  type RunResult,
} from "./result";

export interface Env {
  WORKSPACE_AGENT: DurableObjectNamespace;
}

const REPO_DIR = "/repo";
const MANIFEST_PATH = "/job-manifest.json";
const RESULT_PATH = "/result.json";
const REPORT_PATH = "/report.md";
const MARKER_PATH = "/persistence-marker.txt";

/** Frozen dependency-install step baked into the container image (build time). */
const DEPENDENCY_INSTALL_COMMAND =
  'pip install --no-cache-dir "pytest>=8.3,<9" "pydantic>=2.10,<3" "PyYAML>=6.0,<7" "pyarrow>=17,<21"';

/**
 * DEPENDENCY_INSTALL_MODE = IMAGE_BUILD: the pip install is a
 * Dockerfile RUN step executed during image build, NOT a runtime
 * command. The recorded exit code is 0 BY CONSTRUCTION with this exact
 * semantics: the image successfully exists => the build (including the
 * pip install step) completed. It is not a runtime-observed pip exit
 * code.
 */
const DEPENDENCY_INSTALL_EXIT_CODE = 0;

class WorkspaceAgentContainerBase extends withWorkspaceContainer(
  class extends DurableObject<Env> {},
) {}

/**
 * One Durable Object instance per task_id (idFromName(task_id)). The
 * SQLite-backed workspace VFS — and the isomorphic-git store inside it —
 * persists across requests and across local `wrangler dev` restarts,
 * which is the R0A workspace-persistence claim.
 *
 * A Cloudflare Computer Container backend IS configured for R0B (the
 * DO is container-enabled). Runtime execution is currently FAIL-CLOSED
 * before any exec until an enforceable container egress policy is
 * proven (see CONTAINER_EGRESS_ENFORCEMENT_AVAILABLE). The only network
 * capability actually used is the host-side git client (isomorphic-git
 * in the DO); the repo pytest conftest socket block is
 * defense-in-depth only, not primary egress enforcement.
 *
 * The job runner lives here (host side) because the typed git methods
 * (clone / fetch / checkout / revParse) exist on the DO-side
 * `GitClient`, while the RPC stub surface only forwards `git cli(...)`
 * argv.
 */
export class WorkspaceAgent extends WorkspaceAgentContainerBase {
  #workspace: Workspace;

  readonly backend = new CloudflareContainerBackend({
    container: () => this,
    workspace: { binding: "WORKSPACE_AGENT", id: this.ctx.id.toString() },
    // The published 0.1.1 wrapper cannot enforce container-level
    // deny-internet (its start path hardcodes enableInternet: true).
    // Runtime execution is gated fail-closed below; dependencies are
    // baked at image build time; the repo conftest socket block is
    // defense-in-depth only.
  });

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.#workspace = new Workspace({
      // The released 0.1.1 declarations model DO storage with an
      // older `sql.exec` generic shape than the current
      // `@cloudflare/workers-types`; the runtime object is the real
      // DurableObjectStorage, so this is a declaration-only bridge.
      storage: ctx.storage as unknown as DurableObjectStorageLike,
      git: createGitClient(),
      backends: [this.backend],
    });
  }

  async runJob(
    manifest: JobManifest,
  ): Promise<(RunResult & { execution?: ExecutionResult }) | ManifestConflict> {
    const ws = this.#workspace;

    // Immutable manifest: first write wins, semantic replay is
    // idempotent, and a different manifest for the same task_id fails
    // closed BEFORE any write, materialization, or inspection.
    const existing = await this.readFileOrNull(MANIFEST_PATH);
    try {
      checkReplay(existing, manifest);
    } catch (err) {
      if (err instanceof ManifestConflictError) {
        return { kind: "MANIFEST_CONFLICT", message: err.message };
      }
      throw err;
    }
    if (existing === null) {
      await ws.fs.writeFile(MANIFEST_PATH, JSON.stringify(manifest, null, 2));
    }

    const { actualCommit, materialization } = await this.materializeAtCommit(manifest);
    const commitMatch = actualCommit === manifest.repo_commit;

    let details: CommandDetail[] = [];
    let skipped: string | null = null;
    if (!commitMatch) {
      skipped =
        "actual HEAD does not match the requested commit; bounded inspection skipped (fail closed)";
    } else {
      details = await runBoundedCommands(ws, manifest.allowed_commands, REPO_DIR);
    }

    const result = buildResult({
      task_id: manifest.task_id,
      requested_commit: manifest.repo_commit,
      actual_commit: actualCommit,
      materialization,
      details,
      skipped_reason: skipped,
      created_at: new Date().toISOString(),
    });

    if (manifest.execution_profile === undefined) {
      await ws.fs.writeFile(RESULT_PATH, JSON.stringify(result, null, 2));
      await ws.fs.writeFile(REPORT_PATH, buildWorkspaceReport(result, manifest));
      return result;
    }

    const execution = await this.runExecution(manifest, commitMatch, actualCommit);
    // No partial success: the top-level status reflects BOTH the R0A
    // bounded inspection and the R0B execution result, and the same
    // combined status is persisted to result.json and returned in the
    // HTTP response.
    const topLevel = combineResultStatus(result.result_status, execution.result_status);
    const combined = { ...result, result_status: topLevel };
    await ws.fs.writeFile(RESULT_PATH, JSON.stringify(combined, null, 2));
    await ws.fs.writeFile(REPORT_PATH, buildWorkspaceReport(combined, manifest));
    return { ...combined, execution };
  }

  /**
   * R0B container execution for the frozen PYTEST_CONFIG_V01 profile.
   * Runs inside the real Cloudflare Computer Container (computerd),
   * persists bounded artifacts, and verifies hashes by reading the
   * persisted bytes back. Never falls back to host processes.
   */
  private async runExecution(
    manifest: JobManifest,
    commitMatch: boolean,
    actualCommit: string,
  ): Promise<ExecutionResult> {
    const profile = resolveProfile(manifest.execution_profile);
    if (!profile) {
      throw new Error("internal: execution_profile missing after validation");
    }
    const ws = this.#workspace;
    const startedAt = new Date().toISOString();
    const emptyArtifacts = { stdout: "", stderr: "", stdout_truncated: false, stderr_truncated: false };

    const baseInput = {
      task_id: manifest.task_id,
      profile_id: profile.profile_id,
      requested_commit: manifest.repo_commit,
      actual_commit: actualCommit,
      commit_match: commitMatch,
      backend: profile.backend,
      command: profile.command,
      dependency_install_command: DEPENDENCY_INSTALL_COMMAND,
      dependency_install_exit_code: DEPENDENCY_INSTALL_EXIT_CODE,
      dependency_install_mode: "IMAGE_BUILD" as const,
      python_version: "",
      pip_version: "",
      repo_state_before: "",
      exit_code: null,
      started_at: startedAt,
      finished_at: startedAt,
      duration_ms: 0,
      timeout: false,
      infra_error: false,
      skip: null,
      egress_unenforced: false,
      artifacts: emptyArtifacts,
    };

    if (!commitMatch) {
      // Exact-SHA fail closed: container execution never starts.
      const result = buildExecutionResult({
        ...baseInput,
        skip: {
          status: "SKIPPED_COMMIT_MISMATCH",
          reason:
            "actual HEAD does not match requested commit; container execution skipped (fail closed)",
        },
      });
      return this.finalize(result, emptyArtifacts);
    }

    // Clean-worktree gate: the repository must be untouched before any
    // container execution. No auto-clean; fail closed only.
    const repoStateBefore = await this.repoState(REPO_DIR);
    if (repoStateBefore !== "clean") {
      const result = buildExecutionResult({
        ...baseInput,
        repo_state_before: repoStateBefore,
        skip: {
          status: "SKIPPED_DIRTY_WORKTREE",
          reason: `git status --porcelain is not empty (${repoStateBefore.slice(0, 400)}); container execution skipped (fail closed)`,
        },
      });
      return this.finalize(result, emptyArtifacts);
    }

    // Egress enforcement gate: the published 0.1.1 wrapper cannot set
    // or prove container-level deny-internet (see
    // CONTAINER_EGRESS_ENFORCEMENT_AVAILABLE). While unavailable, R0B
    // execution fails closed; the real smoke is not authorized.
    if (!CONTAINER_EGRESS_ENFORCEMENT_AVAILABLE) {
      const result = buildExecutionResult({
        ...baseInput,
        repo_state_before: repoStateBefore,
        egress_unenforced: true,
      });
      return this.finalize(result, emptyArtifacts);
    }

    // RUNTIME PROOF CONTRACT (defined, NOT executed this round): once
    // enforceable egress exists, before PYTEST_CONFIG_V01 the container
    // must prove PUBLIC_EGRESS_PROBE = BLOCKED against
    // PUBLIC_EGRESS_PROBE_TARGET (command PUBLIC_EGRESS_PROBE_COMMAND);
    // an unexpectedly reachable endpoint fails closed via
    // egressProbeGate("UNEXPECTEDLY_REACHABLE") and pytest does not run.

    let pythonVersion = "";
    let pipVersion = "";
    let exitCode: number | null = null;
    let stdout = "";
    let stderr = "";
    let timeout = false;
    let infraError = false;
    const execStartedMs = Date.now();

    try {
      // Internal version probes (no user-supplied commands).
      const pv = await this.execCapture(ws, "python --version", profile, 60_000);
      pythonVersion = pv.stdout.trim();
      const pip = await this.execCapture(ws, "pip --version", profile, 60_000);
      pipVersion = pip.stdout.trim();
    } catch (err) {
      infraError = true;
      stderr = `version probe failed: ${String(err).slice(0, 2000)}`;
    }

    if (!infraError) {
      try {
        using run = await ws.runtime.exec(profile.command, {
          backend: profile.backend,
          cwd: profile.cwd,
          encoding: "utf8",
          timeoutMs: profile.timeout_ms,
          // Keep the repository working tree clean: no __pycache__ or
          // .pytest_cache writes from inside the container.
          env: { PYTHONDONTWRITEBYTECODE: "1", PYTEST_ADDOPTS: "-p no:cacheprovider" },
        });
        const res = await run.result();
        exitCode = res.exitCode;
        stdout = res.stdout ?? "";
        stderr = res.stderr ?? "";
        if (res.status === "cancelled") timeout = true;
      } catch (err) {
        const msg = String(err);
        if (
          /timeout/i.test(msg) ||
          Date.now() - execStartedMs >= profile.timeout_ms
        ) {
          timeout = true;
        } else {
          infraError = true;
          stderr = msg.slice(0, 4000);
        }
      }
    }

    const finishedAt = new Date().toISOString();
    const durationMs = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
    const artifacts = boundArtifacts(stdout, stderr);
    const result = buildExecutionResult({
      ...baseInput,
      python_version: pythonVersion,
      pip_version: pipVersion,
      repo_state_before: repoStateBefore,
      exit_code: exitCode,
      started_at: startedAt,
      finished_at: finishedAt,
      duration_ms: durationMs,
      timeout,
      infra_error: infraError,
      artifacts,
    });
    return this.finalize(result, artifacts);
  }

  /**
   * Unified finalization for EVERY outcome: fill hashes (empty outputs
   * hash SHA-256("")) -> persist -> read-back verify -> return the
   * EXACT persisted result; verification mismatch fails closed with
   * ARTIFACT_HASH_MISMATCH. Never returns an unfinalized result.
   */
  private async finalize(
    result: ExecutionResult,
    artifacts: {
      stdout: string;
      stderr: string;
      stdout_truncated: boolean;
      stderr_truncated: boolean;
    },
  ): Promise<ExecutionResult> {
    const store: ArtifactStore = {
      writeFile: (path, content) => this.#workspace.fs.writeFile(path, content),
      readFile: (path) => this.readFileOrNull(path),
    };
    return finalizeExecutionArtifacts(store, result, artifacts);
  }

  private async execCapture(
    ws: Workspace,
    command: string,
    profile: { backend: string; cwd: string },
    timeoutMs: number,
  ): Promise<{ stdout: string; stderr: string; exitCode: number }> {
    using run = await ws.runtime.exec(command, {
      backend: profile.backend,
      cwd: profile.cwd,
      encoding: "utf8",
      timeoutMs,
      env: { PYTHONDONTWRITEBYTECODE: "1" },
    });
    const res = await run.result();
    return { stdout: res.stdout ?? "", stderr: res.stderr ?? "", exitCode: res.exitCode };
  }

  private async repoState(dir: string): Promise<string> {
    try {
      const r = await this.#workspace.git.cli({
        argv: ["status", "--porcelain"],
        cwd: dir,
      });
      return r.stdout.trim() === "" ? "clean" : truncateUtf8(r.stdout, 1000);
    } catch (err) {
      return `unknown (${String(err).slice(0, 200)})`;
    }
  }

  async writeMarker(content: string): Promise<void> {
    await this.#workspace.fs.writeFile(MARKER_PATH, content);
  }

  async readMarker(): Promise<string | null> {
    return this.readFileOrNull(MARKER_PATH);
  }

  async readFileBounded(
    path: string,
    maxBytes: number,
  ): Promise<{ exists: boolean; bytes: number; head: string }> {
    try {
      const content = await this.#workspace.fs.readFile(path, "utf8");
      const bytes = new TextEncoder().encode(content).byteLength;
      // maxBytes is a UTF-8 byte budget, not a code-unit count.
      return { exists: true, bytes, head: truncateUtf8(content, maxBytes) };
    } catch {
      return { exists: false, bytes: 0, head: "" };
    }
  }

  private async readFileOrNull(path: string): Promise<string | null> {
    try {
      return await this.#workspace.fs.readFile(path, "utf8");
    } catch {
      return null;
    }
  }

  private async materializeAtCommit(
    manifest: JobManifest,
  ): Promise<{ actualCommit: string; materialization: string }> {
    const first = await this.tryMaterialize(manifest);
    // Bounded retry only for the observed transient workerd/internal
    // clone failure. This never weakens the contract: `result_status`
    // still depends on the verified HEAD equality, and retrying is
    // bounded to one extra attempt.
    if (first.actualCommit !== "" || !first.materialization.includes("internal error")) {
      return first;
    }
    const second = await this.tryMaterialize(manifest);
    if (second.actualCommit === "") {
      return {
        actualCommit: "",
        materialization: `${second.materialization} (after 1 bounded retry)`,
      };
    }
    return {
      ...second,
      materialization: `${second.materialization} (after 1 bounded retry)`,
    };
  }

  private async tryMaterialize(
    manifest: JobManifest,
  ): Promise<{ actualCommit: string; materialization: string }> {
    const ws = this.#workspace;

    // Idempotent re-run: reuse an existing materialization for this task.
    try {
      const root = await ws.git.repoRoot({ dir: REPO_DIR });
      if (root) {
        const head = await ws.git.revParse({ dir: REPO_DIR, ref: "HEAD" });
        return { actualCommit: head, materialization: "reuse-existing" };
      }
    } catch {
      // Not materialized yet — fall through.
    }

    // Preferred path: exact-SHA shallow clone through the host-side git
    // capability (isomorphic-git on the DO, https only).
    try {
      await ws.git.clone({
        url: manifest.repo_url,
        dir: REPO_DIR,
        ref: manifest.repo_commit,
        depth: 1,
        singleBranch: true,
        noTags: true,
      });
      const head = await ws.git.revParse({ dir: REPO_DIR, ref: "HEAD" });
      return { actualCommit: head, materialization: "clone-ref-sha-depth1" };
    } catch (firstErr) {
      // Fallback: default-branch shallow clone, deepen to the exact SHA,
      // then check it out.
      try {
        await ws.fs.rm(REPO_DIR, { recursive: true }).catch(() => undefined);
        await ws.git.clone({
          url: manifest.repo_url,
          dir: REPO_DIR,
          depth: 1,
          singleBranch: true,
          noTags: true,
        });
        await ws.git.fetch({
          dir: REPO_DIR,
          url: manifest.repo_url,
          remoteRef: manifest.repo_commit,
          singleBranch: true,
          tags: false,
        });
        await ws.git.checkout({ dir: REPO_DIR, ref: manifest.repo_commit });
        const head = await ws.git.revParse({ dir: REPO_DIR, ref: "HEAD" });
        return { actualCommit: head, materialization: "clone-default+fetch-sha+checkout" };
      } catch (secondErr) {
        return {
          actualCommit: "",
          materialization: `failed (${String(firstErr).slice(0, 500)} | ${String(secondErr).slice(0, 500)})`,
        };
      }
    }
  }
}
