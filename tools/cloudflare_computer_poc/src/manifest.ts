import { resolveProfile } from "./profiles";

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
  /** R0B: frozen execution profile id (optional; R0A1 manifests omit it). */
  execution_profile?: string;
}

const FULL_SHA_RE = /^[0-9a-f]{40}$/;

export class ManifestError extends Error {
  constructor(message: string) {
    super(`manifest rejected: ${message}`);
    this.name = "ManifestError";
  }
}

/** Raised when a task_id already owns a different manifest. */
export class ManifestConflictError extends Error {
  constructor(message: string) {
    super(`manifest conflict: ${message}`);
    this.name = "ManifestConflictError";
  }
}

/**
 * Serializable conflict outcome returned across the DO RPC boundary
 * (custom Error classes do not survive Workers RPC intact).
 */
export interface ManifestConflict {
  kind: "MANIFEST_CONFLICT";
  message: string;
}

/** Fixed outputs every manifest must declare. */
export const REQUIRED_OUTPUTS = ["result.json", "report.md", "job-manifest.json"] as const;

/** Additional fixed outputs required when an execution profile is present. */
export const EXECUTION_OUTPUTS = [
  "execution-result.json",
  "execution-stdout.txt",
  "execution-stderr.txt",
] as const;

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

  // R0B: optional frozen execution profile. Only known profile ids are
  // accepted; the profile's pinned repo_commit must match the manifest.
  let execution_profile: string | undefined;
  if (raw.execution_profile !== undefined) {
    execution_profile = requireString(raw.execution_profile, "execution_profile");
    const profile = resolveProfile(execution_profile); // throws if unknown
    if (!profile) {
      throw new ManifestError(`internal: unresolved profile "${execution_profile}"`);
    }
    if (profile.repo_commit !== repo_commit) {
      throw new ManifestError(
        `repo_commit ${repo_commit} does not match the frozen ${profile.profile_id} profile commit ${profile.repo_commit}`,
      );
    }
  }

  // Consistency: every read:* command must reference a declared input_file.
  for (const c of allowed as string[]) {
    if (c.startsWith("read:")) {
      const file = c.slice("read:".length);
      if (!input_files.includes(file)) {
        throw new ManifestError(
          `read command "${c}" must reference a declared input_file (missing "${file}")`,
        );
      }
    }
  }

  // Consistency: required fixed outputs must be declared.
  for (const required of REQUIRED_OUTPUTS) {
    if (!output_files.includes(required)) {
      throw new ManifestError(`output_files must declare "${required}"`);
    }
  }
  if (execution_profile !== undefined) {
    for (const required of EXECUTION_OUTPUTS) {
      if (!output_files.includes(required)) {
        throw new ManifestError(`output_files must declare "${required}"`);
      }
    }
  }

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
    ...(execution_profile !== undefined ? { execution_profile } : {}),
  };
}


/**
 * Canonical serialization for semantic manifest comparison.
 *
 * Keys are sorted recursively, so equality is independent of JSON key
 * order. Values are compared exactly (including created_at), so a
 * replay must be semantically identical.
 */
export function canonicalManifest(manifest: JobManifest): string {
  return JSON.stringify(sortKeys(manifest));
}

function sortKeys(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(sortKeys);
  if (isRecord(v)) {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(v).sort()) out[k] = sortKeys(v[k]);
    return out;
  }
  return v;
}

/**
 * Immutable-manifest replay gate.
 *
 * - no stored manifest: allowed (first write);
 * - stored manifest, semantically identical to incoming: allowed
 *   (idempotent replay);
 * - stored manifest, semantically different: ManifestConflictError,
 *   stored artifacts are preserved.
 */
export function checkReplay(existingRaw: string | null, incoming: JobManifest): void {
  if (existingRaw === null) return;
  let existing: unknown;
  try {
    existing = JSON.parse(existingRaw);
  } catch {
    throw new ManifestConflictError(
      "stored job-manifest.json is not valid JSON; refusing to proceed",
    );
  }
  const existingManifest = validateManifest(existing);
  if (canonicalManifest(existingManifest) !== canonicalManifest(incoming)) {
    throw new ManifestConflictError(
      "task already owns a different manifest; stored manifest/result/report are preserved",
    );
  }
}
