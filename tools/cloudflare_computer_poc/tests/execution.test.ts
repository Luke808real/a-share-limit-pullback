import { describe, expect, it } from "vitest";
import {
  boundArtifacts,
  buildExecutionResult,
  combineResultStatus,
  CONTAINER_EGRESS_ENFORCEMENT_AVAILABLE,
  executionResultFileRaw,
  sha256Utf8,
  utf8ByteLength,
  verifyArtifactHash,
  type ExecutionInput,
} from "../src/execution";

const PROFILE_COMMIT = "dbf411e3f1fabd09aa9def2c2578c57e42fae21e";

function base(): ExecutionInput {
  return {
    task_id: "r0b-unit",
    profile_id: "PYTEST_CONFIG_V01",
    requested_commit: PROFILE_COMMIT,
    actual_commit: PROFILE_COMMIT,
    commit_match: true,
    backend: "container-shell",
    command: "python -m pytest -q tests/test_config.py",
    python_version: "Python 3.12.7",
    pip_version: "pip 24.2 from ...",
    dependency_install_command: "pip install ...",
    dependency_install_exit_code: 0,
    dependency_install_mode: "IMAGE_BUILD",
    repo_state_before: "clean",
    exit_code: 0,
    started_at: "2026-08-12T00:00:00.000Z",
    finished_at: "2026-08-12T00:00:20.000Z",
    duration_ms: 20000,
    timeout: false,
    infra_error: false,
    skip: null,
    egress_unenforced: false,
    artifacts: { stdout: "..... 5 passed", stderr: "", stdout_truncated: false, stderr_truncated: false },
  };
}

describe("buildExecutionResult (fail-closed semantics)", () => {
  it("is SUCCESS when every gate holds", () => {
    const r = buildExecutionResult(base());
    expect(r.execution_status).toBe("EXECUTION_SUCCEEDED");
    expect(r.result_status).toBe("SUCCESS");
  });

  it("is FAIL_CLOSED + SKIPPED_COMMIT_MISMATCH when the commit does not match", () => {
    const r = buildExecutionResult({
      ...base(),
      commit_match: false,
      actual_commit: "112bc94218be6dc530e4803cabec288eede6175d",
      skip: {
        status: "SKIPPED_COMMIT_MISMATCH" as const,
        reason: "actual HEAD does not match requested commit",
      },
      exit_code: null,
    });
    expect(r.execution_status).toBe("SKIPPED_COMMIT_MISMATCH");
    expect(r.result_status).toBe("FAIL_CLOSED");
  });

  it("is FAIL_CLOSED + EXECUTION_FAILED on nonzero pytest exit", () => {
    const r = buildExecutionResult({ ...base(), exit_code: 1 });
    expect(r.execution_status).toBe("EXECUTION_FAILED");
    expect(r.result_status).toBe("FAIL_CLOSED");
  });

  it("is FAIL_CLOSED + EXECUTION_TIMEOUT on timeout", () => {
    const r = buildExecutionResult({ ...base(), timeout: true, exit_code: null });
    expect(r.execution_status).toBe("EXECUTION_TIMEOUT");
    expect(r.result_status).toBe("FAIL_CLOSED");
  });

  it("is FAIL_CLOSED + EXECUTION_INFRA_ERROR on infra failure", () => {
    const r = buildExecutionResult({ ...base(), infra_error: true, exit_code: null });
    expect(r.execution_status).toBe("EXECUTION_INFRA_ERROR");
    expect(r.result_status).toBe("FAIL_CLOSED");
  });

  it("is FAIL_CLOSED + SKIPPED_DIRTY_WORKTREE on a dirty worktree", () => {
    const r = buildExecutionResult({
      ...base(),
      skip: { status: "SKIPPED_DIRTY_WORKTREE", reason: "git status --porcelain is not empty" },
      exit_code: null,
    });
    expect(r.execution_status).toBe("SKIPPED_DIRTY_WORKTREE");
    expect(r.result_status).toBe("FAIL_CLOSED");
  });

  it("is FAIL_CLOSED + EGRESS_ENFORCEMENT_UNAVAILABLE when egress cannot be enforced", () => {
    const r = buildExecutionResult({ ...base(), egress_unenforced: true, exit_code: null });
    expect(r.execution_status).toBe("EGRESS_ENFORCEMENT_UNAVAILABLE");
    expect(r.result_status).toBe("FAIL_CLOSED");
  });

  it("is FAIL_CLOSED when dependency install failed", () => {
    const r = buildExecutionResult({ ...base(), dependency_install_exit_code: 1 });
    expect(r.result_status).toBe("FAIL_CLOSED");
  });

  it("never yields partial success: commit ok but nonzero exit stays FAIL_CLOSED", () => {
    const r = buildExecutionResult({ ...base(), exit_code: 2 });
    expect(r.result_status).toBe("FAIL_CLOSED");
    expect(r.execution_status).toBe("EXECUTION_FAILED");
  });
});

describe("sha256 / artifact hashes", () => {
  it("computes the known SHA-256 of the empty string", async () => {
    expect(await sha256Utf8("")).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
  });

  it("verifies matching hashes and rejects mismatches", async () => {
    const h = await sha256Utf8("abc");
    expect(verifyArtifactHash(h, h)).toBe(true);
    expect(verifyArtifactHash(h, await sha256Utf8("abd"))).toBe(false);
    expect(verifyArtifactHash("not-a-hash", h)).toBe(false);
  });
});

describe("boundArtifacts (64 KiB true UTF-8 caps)", () => {
  it("caps stdout and stderr to 64 KiB encoded bytes", () => {
    const big = "x".repeat(100_000);
    const cn = "中文输出".repeat(20_000);
    const b = boundArtifacts(big, `${cn}😀tail`);
    expect(new TextEncoder().encode(b.stdout).byteLength).toBeLessThanOrEqual(64 * 1024);
    expect(new TextEncoder().encode(b.stderr).byteLength).toBeLessThanOrEqual(64 * 1024);
    expect(b.stdout_truncated).toBe(true);
    expect(b.stderr_truncated).toBe(true);
    expect(b.stderr).not.toContain("\uFFFD");
  });

  it("keeps small outputs untruncated", () => {
    const b = boundArtifacts("ok", "");
    expect(b.stdout).toBe("ok");
    expect(b.stdout_truncated).toBe(false);
    expect(b.stderr_truncated).toBe(false);
  });
});

describe("execution-result self-hash convention", () => {
  it("round-trips deterministically with the self field removed", async () => {
    const r = buildExecutionResult(base());
    const raw = executionResultFileRaw(r);
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    expect(parsed.execution_result_sha256).toBeUndefined();
    expect(JSON.stringify(parsed, null, 2)).toBe(raw);
    expect(await sha256Utf8(raw)).toMatch(/^[0-9a-f]{64}$/);
  });
});

describe("top-level status (no partial success)", () => {
  it("is SUCCESS only when both sides are SUCCESS", () => {
    expect(combineResultStatus("SUCCESS", "SUCCESS")).toBe("SUCCESS");
    expect(combineResultStatus("SUCCESS", "FAIL_CLOSED")).toBe("FAIL_CLOSED");
    expect(combineResultStatus("FAIL_CLOSED", "SUCCESS")).toBe("FAIL_CLOSED");
    expect(combineResultStatus("FAIL_CLOSED", "FAIL_CLOSED")).toBe("FAIL_CLOSED");
  });

  it("never allows top-level SUCCESS with a FAIL_CLOSED execution", () => {
    const r = buildExecutionResult({ ...base(), egress_unenforced: true, exit_code: null });
    expect(combineResultStatus("SUCCESS", r.result_status)).toBe("FAIL_CLOSED");
  });
});

describe("utf8ByteLength (true byte length)", () => {
  it("counts UTF-8 bytes, not code units", () => {
    expect(utf8ByteLength("abc")).toBe(3);
    expect(utf8ByteLength("中文")).toBe(6);
    expect(utf8ByteLength("😀")).toBe(4);
    expect(utf8ByteLength("a😀中")).toBe(1 + 4 + 3);
  });
});

describe("egress enforcement availability (evidence-pinned)", () => {
  it("documents that published 0.1.1 cannot enforce container deny-internet", () => {
    // If a future package adds a deny mechanism, this flag is the one
    // place to flip AFTER re-verifying the typings/source.
    expect(CONTAINER_EGRESS_ENFORCEMENT_AVAILABLE).toBe(false);
  });
});
