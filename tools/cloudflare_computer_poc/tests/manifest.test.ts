import { describe, expect, it } from "vitest";
import {
  ManifestConflictError,
  ManifestError,
  canonicalManifest,
  checkReplay,
  validateManifest,
} from "../src/manifest";

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

/** Re-emit an object with its top-level keys in reverse insertion order. */
function reorderKeys<T extends object>(obj: T): T {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(obj).reverse()) {
    out[k] = (obj as Record<string, unknown>)[k];
  }
  return out as T;
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

  it("rejects a read:* command that references an undeclared input_file", () => {
    const raw = validManifest();
    raw.allowed_commands = ["read:README.md"];
    raw.input_files = []; // README.md not declared
    expect(() => validateManifest(raw)).toThrow(/input_file/);
  });

  it("accepts a read:* command that references a declared input_file", () => {
    const raw = validManifest();
    raw.allowed_commands = ["read:README.md"];
    raw.input_files = ["README.md"];
    expect(validateManifest(raw).allowed_commands).toEqual(["read:README.md"]);
  });

  it("rejects missing required fixed outputs", () => {
    for (const missing of ["result.json", "report.md", "job-manifest.json"]) {
      const raw = validManifest();
      raw.output_files = ["result.json", "report.md", "job-manifest.json"].filter(
        (f) => f !== missing,
      );
      expect(() => validateManifest(raw)).toThrow(new RegExp(missing));
    }
  });
});

describe("canonicalManifest", () => {
  it("is independent of JSON key order", () => {
    const a = validateManifest(validManifest());
    const reordered = reorderKeys(a);
    const b = validateManifest(reordered);
    expect(canonicalManifest(a)).toBe(canonicalManifest(b));
  });

  it("differs when any value differs", () => {
    const a = validateManifest(validManifest());
    const b = validateManifest({ ...validManifest(), purpose: "different purpose" });
    expect(canonicalManifest(a)).not.toBe(canonicalManifest(b));
  });
});

describe("checkReplay (immutable manifest)", () => {
  const manifestA = () => validateManifest(validManifest());

  it("allows the first manifest (no stored manifest)", () => {
    expect(() => checkReplay(null, manifestA())).not.toThrow();
  });

  it("allows A -> A replay, independent of JSON key order", () => {
    const stored = JSON.stringify(reorderKeys(manifestA()));
    expect(() => checkReplay(stored, manifestA())).not.toThrow();
  });

  it("allows replay of the exact same manifest (identical bytes)", () => {
    const stored = JSON.stringify(manifestA());
    expect(() => checkReplay(stored, manifestA())).not.toThrow();
  });

  it("rejects replay when created_at differs", () => {
    const stored = JSON.stringify(manifestA());
    const different = validateManifest({ ...validManifest(), created_at: "2026-08-12T00:00:00.000Z" });
    expect(() => checkReplay(stored, different)).toThrow(ManifestConflictError);
  });

  it("rejects A -> B", () => {
    const stored = JSON.stringify(manifestA());
    const different = validateManifest({ ...validManifest(), purpose: "different purpose" });
    expect(() => checkReplay(stored, different)).toThrow(ManifestConflictError);
  });

  it("rejects corrupt stored manifests", () => {
    expect(() => checkReplay("{not json", manifestA())).toThrow(ManifestConflictError);
  });
});

describe("R0B execution profile validation", () => {
  const PROFILE_COMMIT = "dbf411e3f1fabd09aa9def2c2578c57e42fae21e";

  function r0bManifest(): Record<string, unknown> {
    const raw = validManifest();
    return {
      ...raw,
      repo_commit: PROFILE_COMMIT,
      execution_profile: "PYTEST_CONFIG_V01",
      output_files: [
        "result.json",
        "report.md",
        "job-manifest.json",
        "execution-result.json",
        "execution-stdout.txt",
        "execution-stderr.txt",
      ],
    };
  }

  it("accepts a valid R0B manifest with the frozen profile", () => {
    const m = validateManifest(r0bManifest());
    expect(m.execution_profile).toBe("PYTEST_CONFIG_V01");
  });

  it("rejects an unknown profile with EXECUTION_PROFILE_NOT_ALLOWED", () => {
    const raw = r0bManifest();
    raw.execution_profile = "NOPE_PROFILE";
    expect(() => validateManifest(raw)).toThrow(/EXECUTION_PROFILE_NOT_ALLOWED/);
  });

  it("rejects a repo_commit that differs from the frozen profile commit", () => {
    const raw = r0bManifest();
    raw.repo_commit = "112bc94218be6dc530e4803cabec288eede6175d";
    expect(() => validateManifest(raw)).toThrow(/frozen PYTEST_CONFIG_V01 profile commit/);
  });

  it("rejects missing execution outputs when a profile is present", () => {
    const raw = r0bManifest();
    raw.output_files = ["result.json", "report.md", "job-manifest.json"];
    expect(() => validateManifest(raw)).toThrow(/execution-result\.json/);
  });
});
