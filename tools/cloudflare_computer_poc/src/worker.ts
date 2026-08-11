import {
  validateManifest,
  type JobManifest,
} from "./manifest";
import type { RunResult } from "./result";
import { WorkspaceAgent, type Env } from "./workspace-agent";

export { WorkspaceAgent };

/**
 * RPC surface the Worker dispatches to. The job runner itself lives in
 * the DO (host side), where the typed git/fs surfaces are available.
 */
interface AgentRpc {
  runJob(manifest: JobManifest): Promise<RunResult | { kind: "MANIFEST_CONFLICT"; message: string }>;
  writeMarker(content: string): Promise<void>;
  readMarker(): Promise<string | null>;
  readFileBounded(
    path: string,
    maxBytes: number,
  ): Promise<{ exists: boolean; bytes: number; head: string }>;
}

function agent(env: Env, taskId: string): AgentRpc {
  return env.WORKSPACE_AGENT.get(env.WORKSPACE_AGENT.idFromName(taskId)) as unknown as AgentRpc;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "POST") {
      return new Response(
        "cloudflare-computer-r0a PoC: POST /run, /marker, or /file",
        { status: 200 },
      );
    }
    const url = new URL(request.url);
    if (url.pathname === "/run") return handleRun(request, env);
    if (url.pathname === "/marker") return handleMarker(request, env);
    if (url.pathname === "/file") return handleFile(request, env);
    return new Response("not found", { status: 404 });
  },
} satisfies ExportedHandler<Env>;

async function handleRun(request: Request, env: Env): Promise<Response> {
  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return json({ error: "invalid JSON body", result_status: "FAIL_CLOSED" }, 400);
  }

  let manifest: JobManifest;
  try {
    manifest = validateManifest(raw);
  } catch (err) {
    // Invalid manifests are rejected before any execution (fail closed).
    return json(
      { error: (err as Error).message, result_status: "FAIL_CLOSED" },
      400,
    );
  }

  try {
    const outcome = await agent(env, manifest.task_id).runJob(manifest);
    if ("kind" in outcome && outcome.kind === "MANIFEST_CONFLICT") {
      // Explicit conflict: stored artifacts are preserved (no writes).
      return json(
        {
          error: "MANIFEST_CONFLICT",
          result_status: "FAIL_CLOSED",
          message: outcome.message,
        },
        409,
      );
    }
    return json(outcome, 200);
  } catch (err) {
    return json({ error: String(err), result_status: "FAIL_CLOSED" }, 500);
  }
}

async function handleMarker(request: Request, env: Env): Promise<Response> {
  const body = (await request.json()) as {
    task_id?: string;
    op?: string;
    content?: string;
  };
  if (typeof body.task_id !== "string" || body.task_id.length === 0) {
    return json({ error: "task_id required" }, 400);
  }

  if (body.op === "write") {
    const content = typeof body.content === "string" ? body.content : "";
    await agent(env, body.task_id).writeMarker(content);
    return json({ ok: true, marker: content }, 200);
  }
  if (body.op === "read") {
    const marker = await agent(env, body.task_id).readMarker();
    if (marker !== null) {
      return json({ ok: true, marker }, 200);
    }
    return json({ ok: false, marker: null }, 404);
  }
  return json({ error: "op must be write|read" }, 400);
}

async function handleFile(request: Request, env: Env): Promise<Response> {
  const body = (await request.json()) as {
    task_id?: string;
    path?: string;
    max_bytes?: number;
  };
  if (typeof body.task_id !== "string" || typeof body.path !== "string") {
    return json({ error: "task_id and path required" }, 400);
  }
  const max = Math.min(Math.max(body.max_bytes ?? 2048, 1), 64 * 1024);
  const info = await agent(env, body.task_id).readFileBounded(body.path, max);
  return json(info, info.exists ? 200 : 404);
}

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json" },
  });
}
