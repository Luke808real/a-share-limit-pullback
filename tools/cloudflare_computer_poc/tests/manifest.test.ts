import { describe, expect, it } from "vitest";
import { ManifestError, validateManifest } from "../src/manifest";

const REPO_COMMIT = "1cb5fb7a1792edccc18c70207340980377cbd4eb";

function validManifest(): Record<string, unknown> {
  return {
    task_id: "unit-test-1",
    repo_url: "https://github.com/Luke808real/a-share-limit-pullback.git",
    repo_commit: REPO_COMMIT,
    created_at: "2026-08-11T00:00:00.000Z",
    purpose: "unit test fixture",
    allowed_commands: ["git:status", "git:log-1"],
    network_policy: { egress: "none" },
    input_files: ["README.md"],
    output_files: ["result.json", "report.md", "job-manifest.json"],
  };
}

describe("validateManifest", () => {
  it("accepts a valid pinned manifest", () => {
    const m = validateManifest(validManifest());
    expect(m.repo_commit).toBe(REPO_COMMIT);
    expect(m.network_policy.egress).toBe("none");
  });

  it("rejects a missing commit SHA", () => {
    const raw = validManifest();
    delete raw.repo_commit;
    expect(() => validateManifest(raw)).toThrow(ManifestError);
    expect(() => validateManifest(raw)).toThrow(/repo_commit/);
  });

  it("rejects a short or non-hex commit SHA", () => {
    for (const bad of ["1cb5fb7a", "not-a-sha", "1cb5fb7a1792edccc18c70207340980377cbd4eZ"]) {
      const raw = validManifest();
      raw.repo_commit = bad;
      expect(() => validateManifest(raw)).toThrow(/repo_commit/);
    }
  });

  it("normalizes uppercase hex to lowercase", () => {
    const raw = validManifest();
    raw.repo_commit = REPO_COMMIT.toUpperCase();
    expect(validateManifest(raw).repo_commit).toBe(REPO_COMMIT);
  });

  it("rejects a missing task_id", () => {
    const raw = validManifest();
    delete raw.task_id;
    expect(() => validateManifest(raw)).toThrow(/task_id/);
  });

  it("rejects any egress other than none", () => {
    for (const egress of ["direct", "http-gateway"]) {
      const raw = validManifest();
      raw.network_policy = { egress };
      expect(() => validateManifest(raw)).toThrow(/egress/);
    }
  });

  it("rejects unknown allowed commands", () => {
    const raw = validManifest();
    raw.allowed_commands = ["rm:everything"];
    expect(() => validateManifest(raw)).toThrow(/allowed_commands/);
  });

  it("rejects a non-https repo URL", () => {
    const raw = validManifest();
    raw.repo_url = "ssh://git@github.com/Luke808real/a-share-limit-pullback.git";
    expect(() => validateManifest(raw)).toThrow(/repo_url/);
  });
});
