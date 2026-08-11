import {
  Workspace,
  type DurableObjectStorageLike,
} from "@cloudflare/computer";
import { createGitClient } from "@cloudflare/computer/git";
import { DurableObject } from "cloudflare:workers";
import { runBoundedCommands, type CommandDetail } from "./commands";
import {
  checkReplay,
  ManifestConflictError,
  type JobManifest,
  type ManifestConflict,
} from "./manifest";
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

/**
 * One Durable Object instance per task_id (idFromName(task_id)). The
 * SQLite-backed workspace VFS — and the isomorphic-git store inside it —
 * persists across requests and across local `wrangler dev` restarts,
 * which is the R0A workspace-persistence claim.
 *
 * No execution backend is configured: there is no shell isolate and no
 * ambient network surface. The only network capability is the host-side
 * git client (isomorphic-git running in the DO), which is exactly the
 * host capability the R0A contract permits for git materialization.
 *
 * The job runner lives here (host side) because the typed git methods
 * (clone / fetch / checkout / revParse) exist on the DO-side
 * `GitClient`, while the RPC stub surface only forwards `git cli(...)`
 * argv.
 */
export class WorkspaceAgent extends DurableObject<Env> {
  #workspace: Workspace;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.#workspace = new Workspace({
      // The released 0.1.1 declarations model DO storage with an
      // older `sql.exec` generic shape than the current
      // `@cloudflare/workers-types`; the runtime object is the real
      // DurableObjectStorage, so this is a declaration-only bridge.
      storage: ctx.storage as unknown as DurableObjectStorageLike,
      git: createGitClient(),
    });
  }

  async runJob(manifest: JobManifest): Promise<RunResult | ManifestConflict> {
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

    await ws.fs.writeFile(RESULT_PATH, JSON.stringify(result, null, 2));
    await ws.fs.writeFile(REPORT_PATH, buildWorkspaceReport(result, manifest));

    return result;
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
