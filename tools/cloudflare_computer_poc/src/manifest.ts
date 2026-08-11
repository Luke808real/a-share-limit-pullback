/**
 * R0A job manifest contract.
 *
 * A manifest is the immutable, per-task job description. The runner
 * refuses to execute a manifest that is missing a commit SHA, uses an
 * unpinned reference, or requests network egress.
 */

export const KNOWN_COMMANDS = [
  "git:status",
  "git:log-1",
  "read:README.md",
  "read:docs/project-operating-model.md",
] as const;

export type KnownCommand = (typeof KNOWN_COMMANDS)[number];

export interface NetworkPolicy {
  /** The PoC accepts only the fail-closed default. */
  egress: "none";
}

export interface JobManifest {
  task_id: string;
  repo_url: string;
  repo_commit: string;
  created_at: string;
  purpose: string;
  allowed_commands: KnownCommand[];
  network_policy: NetworkPolicy;
  input_files: string[];
  output_files: string[];
}

const FULL_SHA_RE = /^[0-9a-f]{40}$/;

export class ManifestError extends Error {
  constructor(message: string) {
    super(`manifest rejected: ${message}`);
    this.name = "ManifestError";
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function requireString(v: unknown, field: string): string {
  if (typeof v !== "string" || v.length === 0) {
    throw new ManifestError(`${field} must be a non-empty string`);
  }
  return v;
}

function requireStringArray(v: unknown, field: string): string[] {
  if (!Array.isArray(v) || v.some((x) => typeof x !== "string")) {
    throw new ManifestError(`${field} must be an array of strings`);
  }
  return v as string[];
}

export function validateManifest(raw: unknown): JobManifest {
  if (!isRecord(raw)) {
    throw new ManifestError("manifest must be a JSON object");
  }

  const task_id = requireString(raw.task_id, "task_id");
  const repo_url = requireString(raw.repo_url, "repo_url");

  // No floating references: a full 40-hex commit SHA is mandatory.
  const repo_commit = requireString(raw.repo_commit, "repo_commit").toLowerCase();
  if (!FULL_SHA_RE.test(repo_commit)) {
    throw new ManifestError(
      `repo_commit must be a full 40-hex SHA-1 (got "${repo_commit}")`,
    );
  }

  if (!/^https:\/\//.test(repo_url)) {
    throw new ManifestError(
      `repo_url must be an https:// URL (host-side git capability only; got "${repo_url}")`,
    );
  }

  const created_at = requireString(raw.created_at, "created_at");
  const purpose = requireString(raw.purpose, "purpose");

  const allowed = raw.allowed_commands;
  if (!Array.isArray(allowed) || allowed.length === 0) {
    throw new ManifestError("allowed_commands must be a non-empty array");
  }
  for (const c of allowed) {
    if (typeof c !== "string" || !(KNOWN_COMMANDS as readonly string[]).includes(c)) {
      throw new ManifestError(`allowed_commands contains unknown command "${String(c)}"`);
    }
  }

  const policy = raw.network_policy;
  if (!isRecord(policy) || policy.egress !== "none") {
    throw new ManifestError(
      "network_policy.egress must be \"none\"; the PoC refuses direct/http-gateway egress",
    );
  }

  const input_files = requireStringArray(raw.input_files, "input_files");
  const output_files = requireStringArray(raw.output_files, "output_files");

  return {
    task_id,
    repo_url,
    repo_commit,
    created_at,
    purpose,
    allowed_commands: allowed as KnownCommand[],
    network_policy: { egress: "none" },
    input_files,
    output_files,
  };
}
