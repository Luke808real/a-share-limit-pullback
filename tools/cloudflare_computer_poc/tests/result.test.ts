import { describe, expect, it } from "vitest";
import { buildResult } from "../src/result";

const REQUESTED = "1cb5fb7a1792edccc18c70207340980377cbd4eb";

function base() {
  return {
    task_id: "t1",
    requested_commit: REQUESTED,
    materialization: "clone-ref-sha-depth1",
    skipped_reason: null,
    created_at: "2026-08-11T00:00:00.000Z",
  };
}

describe("buildResult fail-closed semantics", () => {
  it("is SUCCESS when commit matches and every bounded command exits 0", () => {
    const r = buildResult({
      ...base(),
      actual_commit: REQUESTED,
      details: [
        { command: "git:status", exit_code: 0, output: "" },
        { command: "read:README.md", exit_code: 0, output: "# hi" },
      ],
    });
    expect(r.commit_match).toBe(true);
    expect(r.result_status).toBe("SUCCESS");
    expect(r.commands_run).toEqual(["git:status", "read:README.md"]);
    expect(r.exit_codes).toEqual([0, 0]);
  });

  it("is FAIL_CLOSED when the commit does not match", () => {
    const r = buildResult({
      ...base(),
      actual_commit: "0000000000000000000000000000000000000000",
      details: [],
      skipped_reason: "mismatch",
    });
    expect(r.commit_match).toBe(false);
    expect(r.result_status).toBe("FAIL_CLOSED");
  });

  it("is FAIL_CLOSED when any bounded command exits nonzero", () => {
    const r = buildResult({
      ...base(),
      actual_commit: REQUESTED,
      details: [
        { command: "git:status", exit_code: 0, output: "" },
        { command: "read:README.md", exit_code: 1, output: "ENOENT" },
      ],
    });
    expect(r.commit_match).toBe(true);
    expect(r.result_status).toBe("FAIL_CLOSED");
  });

  it("is FAIL_CLOSED when inspection was skipped", () => {
    const r = buildResult({
      ...base(),
      actual_commit: REQUESTED,
      details: [],
      skipped_reason: "no commands allowed",
    });
    expect(r.result_status).toBe("FAIL_CLOSED");
  });
});
