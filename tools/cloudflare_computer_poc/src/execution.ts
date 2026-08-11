/**
 * R0B execution artifact semantics: result building, UTF-8 byte caps,
 * and artifact hash verification. Pure functions (unit-testable);
 * the container I/O lives in workspace-agent.ts.
 */

import { truncateUtf8 } from "./result";

export const EXECUTION_STDOUT_CAP_BYTES = 64 * 1024;
export const EXECUTION_STDERR_CAP_BYTES = 64 * 1024;

/**
 * Egress enforcement availability for the Cloudflare Computer
 * Container backend in the PUBLISHED @cloudflare/computer 0.1.1.
 *
 * Evidence (0.1.1 typings/source, read-only):
 * - WorkspaceBackend = { id, type, callable?, connect(host) } — no
 *   egress/network-policy member.
 * - CloudflareContainerBackendOptions has no deny/egress-mode option;
 *   its only network surface is
 *   `interceptOutboundHttp(egressHost, workspace)` — a single-host
 *   allow-list routing hook, not a deny-internet mechanism.
 * - WorkerShellBackendOptions (0.1.1) likewise has no egress option
 *   (docs/12 WorkspaceEgressPolicy describes repo-HEAD code, ahead of
 *   the published package).
 * - @cloudflare/containers is not installed.
 *
 * Therefore container-level deny-internet cannot be set OR proven with
 * 0.1.1. We do NOT fake it (no env vars, no comments, no conftest
 * socket block as primary enforcement, no host firewall changes).
 * While this is false, R0B execution fails closed and the real
 * container smoke is NOT authorized. The repo conftest socket block
 * remains defense-in-depth only.
 */
export const CONTAINER_EGRESS_ENFORCEMENT_AVAILABLE = false;

export type ExecutionStatus =
  | "EXECUTION_SUCCEEDED"
  | "EXECUTION_FAILED"
  | "EXECUTION_TIMEOUT"
  | "EXECUTION_INFRA_ERROR"
  | "SKIPPED_COMMIT_MISMATCH"
  | "SKIPPED_DIRTY_WORKTREE"
  | "EGRESS_ENFORCEMENT_UNAVAILABLE"
  | "ARTIFACT_HASH_MISMATCH";

export type ExecutionSkipStatus = "SKIPPED_COMMIT_MISMATCH" | "SKIPPED_DIRTY_WORKTREE";

export interface ExecutionArtifacts {
  stdout: string;
  stderr: string;
  stdout_truncated: boolean;
  stderr_truncated: boolean;
}

export interface ExecutionInput {
  task_id: string;
  profile_id: string;
  requested_commit: string;
  actual_commit: string;
  commit_match: boolean;
  backend: string;
  command: string;
  python_version: string;
  pip_version: string;
  dependency_install_command: string;
  dependency_install_exit_code: number;
  dependency_install_mode: "IMAGE_BUILD";
  repo_state_before: string;
  exit_code: number | null;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  timeout: boolean;
  infra_error: boolean;
  skip: { status: ExecutionSkipStatus; reason: string } | null;
  egress_unenforced: boolean;
  artifacts: ExecutionArtifacts;
}

export interface ExecutionResult {
  task_id: string;
  profile_id: string;
  requested_commit: string;
  actual_commit: string;
  commit_match: boolean;
  backend: string;
  python_version: string;
  pip_version: string;
  dependency_install_command: string;
  dependency_install_exit_code: number;
  dependency_install_mode: "IMAGE_BUILD";
  repo_state_before: string;
  command: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  exit_code: number | null;
  stdout_sha256: string;
  stderr_sha256: string;
  stdout_truncated: boolean;
  stderr_truncated: boolean;
  /**
   * SHA-256 of the persisted execution-result.json content with this
   * field removed (avoids a self-referential hash). The convention is
   * deterministic: parse the file, delete this key, re-stringify with
   * 2-space indent, hash.
   */
  execution_result_sha256: string;
  execution_status: ExecutionStatus;
  result_status: "SUCCESS" | "FAIL_CLOSED";
}

export async function sha256Utf8(s: string): Promise<string> {
  const bytes = new TextEncoder().encode(s);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Pure result semantics. SUCCESS only when every gate holds:
 * commit match, no skip, no timeout, no infra error, exit 0, and
 * non-empty bounded stdout/stderr files. Otherwise FAIL_CLOSED.
 */
export function buildExecutionResult(input: ExecutionInput): ExecutionResult {
  let status: ExecutionStatus;
  let resultStatus: "SUCCESS" | "FAIL_CLOSED";

  if (input.egress_unenforced) {
    status = "EGRESS_ENFORCEMENT_UNAVAILABLE";
    resultStatus = "FAIL_CLOSED";
  } else if (input.skip !== null) {
    status = input.skip.status;
    resultStatus = "FAIL_CLOSED";
  } else if (input.timeout) {
    status = "EXECUTION_TIMEOUT";
    resultStatus = "FAIL_CLOSED";
  } else if (input.infra_error) {
    status = "EXECUTION_INFRA_ERROR";
    resultStatus = "FAIL_CLOSED";
  } else if (input.exit_code !== 0) {
    status = "EXECUTION_FAILED";
    resultStatus = "FAIL_CLOSED";
  } else {
    status = "EXECUTION_SUCCEEDED";
    resultStatus =
      input.commit_match && input.dependency_install_exit_code === 0
        ? "SUCCESS"
        : "FAIL_CLOSED";
  }

  return {
    task_id: input.task_id,
    profile_id: input.profile_id,
    requested_commit: input.requested_commit,
    actual_commit: input.actual_commit,
    commit_match: input.commit_match,
    backend: input.backend,
    python_version: input.python_version,
    pip_version: input.pip_version,
    dependency_install_command: input.dependency_install_command,
    dependency_install_exit_code: input.dependency_install_exit_code,
    dependency_install_mode: input.dependency_install_mode,
    repo_state_before: input.repo_state_before,
    command: input.command,
    started_at: input.started_at,
    finished_at: input.finished_at,
    duration_ms: input.duration_ms,
    exit_code: input.exit_code,
    stdout_sha256: "",
    stderr_sha256: "",
    execution_result_sha256: "",
    stdout_truncated: input.artifacts.stdout_truncated,
    stderr_truncated: input.artifacts.stderr_truncated,
    execution_status: status,
    result_status: resultStatus,
  };
}

/** Hash placeholders are filled in by the caller once artifacts are persisted. */
export async function fillArtifactHashes(
  result: ExecutionResult,
  artifacts: ExecutionArtifacts,
): Promise<ExecutionResult> {
  return {
    ...result,
    stdout_sha256: await sha256Utf8(artifacts.stdout),
    stderr_sha256: await sha256Utf8(artifacts.stderr),
  };
}

export function boundArtifacts(stdout: string, stderr: string): ExecutionArtifacts {
  const boundedStdout = truncateUtf8(stdout, EXECUTION_STDOUT_CAP_BYTES);
  const boundedStderr = truncateUtf8(stderr, EXECUTION_STDERR_CAP_BYTES);
  return {
    stdout: boundedStdout,
    stderr: boundedStderr,
    stdout_truncated: boundedStdout !== stdout,
    stderr_truncated: boundedStderr !== stderr,
  };
}

export function verifyArtifactHash(expected: string, actual: string): boolean {
  return expected === actual && /^[0-9a-f]{64}$/.test(expected);
}

/** Canonical file content for the self-hash convention. */
export function executionResultFileRaw(result: ExecutionResult): string {
  return JSON.stringify({ ...result, execution_result_sha256: undefined }, null, 2);
}

/**
 * Top-level result for profile jobs: reflects BOTH the R0A bounded
 * inspection result AND the R0B execution result. No partial success:
 * either side FAIL_CLOSED => top-level FAIL_CLOSED.
 */
export function combineResultStatus(
  r0a: "SUCCESS" | "FAIL_CLOSED",
  execution: "SUCCESS" | "FAIL_CLOSED",
): "SUCCESS" | "FAIL_CLOSED" {
  return r0a === "SUCCESS" && execution === "SUCCESS" ? "SUCCESS" : "FAIL_CLOSED";
}

/** True UTF-8 byte length (not string code units). */
export function utf8ByteLength(s: string): number {
  return new TextEncoder().encode(s).byteLength;
}
