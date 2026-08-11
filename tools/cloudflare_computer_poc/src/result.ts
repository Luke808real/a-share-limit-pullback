/**
 * Deterministic run result for the R0A contract, plus the bounded
 * workspace report writer.
 */

import type { JobManifest } from "./manifest";

export type ResultStatus = "SUCCESS" | "FAIL_CLOSED";

export interface CommandDetail {
  command: string;
  exit_code: number;
  output: string;
}

export interface RunResult {
  task_id: string;
  requested_commit: string;
  actual_commit: string;
  commit_match: boolean;
  commands_run: string[];
  exit_codes: number[];
  command_details: CommandDetail[];
  result_status: ResultStatus;
  materialization: string;
  commands_skipped_reason: string | null;
  created_at: string;
}

export interface BuildResultInput {
  task_id: string;
  requested_commit: string;
  actual_commit: string;
  materialization: string;
  details: CommandDetail[];
  skipped_reason: string | null;
  created_at: string;
}

export function buildResult(input: BuildResultInput): RunResult {
  const commit_match = input.actual_commit === input.requested_commit;
  const all_commands_ok =
    input.details.length > 0 && input.details.every((d) => d.exit_code === 0);
  // Fail closed on: commit mismatch, skipped inspection, or any nonzero
  // exit code from the bounded command surface.
  const result_status: ResultStatus =
    commit_match && all_commands_ok && input.skipped_reason === null
      ? "SUCCESS"
      : "FAIL_CLOSED";

  return {
    task_id: input.task_id,
    requested_commit: input.requested_commit,
    actual_commit: input.actual_commit,
    commit_match,
    commands_run: input.details.map((d) => d.command),
    exit_codes: input.details.map((d) => d.exit_code),
    command_details: input.details,
    result_status,
    materialization: input.materialization,
    commands_skipped_reason: input.skipped_reason,
    created_at: input.created_at,
  };
}

const REPORT_MAX_BYTES = 2 * 1024;
const TRUNCATION_MARKER = "\n... [truncated]";

export function buildWorkspaceReport(result: RunResult, manifest: JobManifest): string {
  const lines: string[] = [];
  lines.push("# Cloudflare Computer R0A — workspace run report");
  lines.push("");
  lines.push(`- task_id: ${result.task_id}`);
  lines.push(`- purpose: ${manifest.purpose}`);
  lines.push(`- repo_url: ${manifest.repo_url}`);
  lines.push(`- requested_commit: ${result.requested_commit}`);
  lines.push(`- actual_commit: ${result.actual_commit}`);
  lines.push(`- commit_match: ${String(result.commit_match)}`);
  lines.push(`- result_status: ${result.result_status}`);
  lines.push(`- materialization: ${result.materialization}`);
  lines.push(`- network_policy.egress: ${manifest.network_policy.egress}`);
  lines.push(`- created_at: ${result.created_at}`);
  if (result.commands_skipped_reason !== null) {
    lines.push(`- commands_skipped: ${result.commands_skipped_reason}`);
  }
  lines.push("");
  lines.push("## Bounded inspection");
  for (const d of result.command_details) {
    lines.push("");
    lines.push(`### ${d.command} (exit ${d.exit_code})`);
    lines.push("");
    lines.push("```");
    lines.push(truncateUtf8(d.output, REPORT_MAX_BYTES));
    lines.push("```");
  }
  lines.push("");
  return lines.join("\n");
}

export function truncateUtf8(s: string, maxBytes: number): string {
  const encoder = new TextEncoder();
  const bytes = encoder.encode(s);
  if (bytes.byteLength <= maxBytes) return s;

  // Reserve room for the marker so the ENCODED result (marker included)
  // is <= maxBytes UTF-8 bytes.
  const markerBytes = encoder.encode(TRUNCATION_MARKER).byteLength;
  if (maxBytes < markerBytes) {
    // The marker cannot fit; return a UTF-8-safe prefix without it.
    let end = maxBytes;
    while (end > 0 && (bytes[end] & 0xc0) === 0x80) end -= 1;
    return new TextDecoder().decode(bytes.subarray(0, end));
  }
  const budget = Math.max(0, maxBytes - markerBytes);
  let end = Math.min(budget, bytes.byteLength);

  // Never split a code point: if the byte at `end` is a UTF-8
  // continuation byte (10xxxxxx), back up to its sequence start.
  while (end > 0 && (bytes[end] & 0xc0) === 0x80) end -= 1;

  const prefix = new TextDecoder().decode(bytes.subarray(0, end));
  return `${prefix}${TRUNCATION_MARKER}`;
}
