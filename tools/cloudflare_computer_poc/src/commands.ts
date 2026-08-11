/**
 * Bounded inspection surface. Only commands listed in the manifest's
 * allowed_commands are reachable; each maps to the host-side typed
 * Cloudflare Computer git/fs surface (no shell, no ambient network).
 */

import type { KnownCommand } from "./manifest";
import { truncateUtf8 } from "./result";

export const MAX_COMMAND_OUTPUT_BYTES = 8 * 1024;

export interface WorkspaceFsLike {
  readFile(path: string, encoding: "utf8"): Promise<string>;
}

export interface WorkspaceGitLike {
  cli(args: {
    argv: string[];
    cwd?: string;
    stdin?: string;
  }): Promise<{ stdout: string; stderr: string; exitCode: number }>;
}

export interface WorkspaceLike {
  fs: WorkspaceFsLike;
  git: WorkspaceGitLike;
}

export interface CommandDetail {
  command: string;
  exit_code: number;
  output: string;
}

export async function runBoundedCommands(
  ws: WorkspaceLike,
  commands: readonly KnownCommand[],
  repoDir: string,
): Promise<CommandDetail[]> {
  const out: CommandDetail[] = [];
  for (const command of commands) {
    out.push(await runOne(ws, command, repoDir));
  }
  return out;
}

async function runOne(
  ws: WorkspaceLike,
  command: KnownCommand,
  repoDir: string,
): Promise<CommandDetail> {
  switch (command) {
    case "git:status":
      return cli(ws, command, ["status", "--porcelain=v1"], repoDir);
    case "git:log-1":
      return cli(ws, command, ["log", "-1", "--oneline"], repoDir);
    case "read:README.md":
      return readBounded(ws, command, `${repoDir}/README.md`);
    case "read:docs/project-operating-model.md":
      return readBounded(ws, command, `${repoDir}/docs/project-operating-model.md`);
  }
}

async function cli(
  ws: WorkspaceLike,
  command: string,
  argv: string[],
  cwd: string,
): Promise<CommandDetail> {
  try {
    const r = await ws.git.cli({ argv, cwd });
    const output = truncateUtf8(
      [r.stdout, r.stderr].filter((s) => s.length > 0).join("\n"),
      MAX_COMMAND_OUTPUT_BYTES,
    );
    return { command, exit_code: r.exitCode, output };
  } catch (err) {
    return {
      command,
      exit_code: 1,
      output: truncateUtf8(String(err), MAX_COMMAND_OUTPUT_BYTES),
    };
  }
}

async function readBounded(
  ws: WorkspaceLike,
  command: string,
  path: string,
): Promise<CommandDetail> {
  try {
    const content = await ws.fs.readFile(path, "utf8");
    return {
      command,
      exit_code: 0,
      output: truncateUtf8(content, MAX_COMMAND_OUTPUT_BYTES),
    };
  } catch (err) {
    return {
      command,
      exit_code: 1,
      output: truncateUtf8(String(err), MAX_COMMAND_OUTPUT_BYTES),
    };
  }
}
