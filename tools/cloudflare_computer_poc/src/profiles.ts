/**
 * R0B frozen execution profiles.
 *
 * Exactly ONE profile exists. A manifest may select a profile by id;
 * the argv/backend/cwd/timeout resolve INTERNALLY here. Arbitrary
 * shell strings from the manifest are never accepted.
 */

export const PROFILE_ID_PYTEST_CONFIG_V01 = "PYTEST_CONFIG_V01" as const;

export interface ExecutionProfile {
  profile_id: string;
  /** Exact argv-equivalent command executed in the container. */
  command: string;
  /** Container backend selector for workspace.runtime.exec(). */
  backend: string;
  /** Working directory inside the container (workspace VFS mount). */
  cwd: string;
  /** Hard exec timeout. */
  timeout_ms: number;
  /** Frozen repository commit for this profile. */
  repo_commit: string;
}

export const EXECUTION_PROFILES: Record<string, ExecutionProfile> = {
  [PROFILE_ID_PYTEST_CONFIG_V01]: {
    profile_id: PROFILE_ID_PYTEST_CONFIG_V01,
    command: "python -m pytest -q tests/test_config.py",
    backend: "container-shell",
    cwd: "/workspace/repo",
    timeout_ms: 180_000,
    repo_commit: "dbf411e3f1fabd09aa9def2c2578c57e42fae21e",
  },
};

export class ExecutionProfileNotAllowedError extends Error {
  constructor(profileId: string) {
    super(
      `EXECUTION_PROFILE_NOT_ALLOWED: execution_profile "${profileId}" is not a known profile`,
    );
    this.name = "ExecutionProfileNotAllowedError";
  }
}

export function resolveProfile(profileId: string | undefined): ExecutionProfile | null {
  if (profileId === undefined) return null;
  const profile = EXECUTION_PROFILES[profileId];
  if (!profile) throw new ExecutionProfileNotAllowedError(profileId);
  return profile;
}
