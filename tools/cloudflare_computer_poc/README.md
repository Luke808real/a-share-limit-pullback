# Cloudflare Computer R0A PoC (research only)

Minimal local-development proof of the R0A workspace contract for
`a-share-limit-pullback`:

```text
exact repo commit
→ isolated persistent workspace
→ immutable job manifest
→ bounded git/file inspection
→ deterministic result/report
→ workspace persistence across reconnect
```

This is infrastructure research. It does not touch strategy semantics,
config, snapshots, universes, Forward, or TradePlan, and it performs no
strategy computation.

## Upstream inspection (pinned)

Inspected only the five files below at the pinned upstream commit
`9422fc860494f51a79eb0c525565026abf82aff6` (`cloudflare/computer`),
which corresponds to the published preview package
`@cloudflare/computer@0.1.1`:

```text
README.md
packages/computer/README.md
examples/think/README.md
docs/12_worker_backend.md
docs/13_git_interface.md
```

Confirmed APIs:

- **Workspace**: `Workspace` (or the `withWorkspace` mixin) hosts a
  SQLite-backed virtual filesystem inside a Durable Object.
  `workspace.fs` is a `node:fs/promises`-like surface (`readFile`,
  `writeFile`, `mkdir`, `readdir`, `rm`, `grep`), durable across DO
  restarts. One DO instance per `task_id` via `idFromName(task_id)`.
  ~10 GB per workspace; agent-scale, not a monorepo store.
- **Persistent filesystem**: DO SQLite storage; survives requests and
  local `wrangler dev` restarts (`.wrangler`/`--persist-to` state).
- **Git**: opt-in `createGitClient()` from `@cloudflare/computer/git`;
  isomorphic-git runs against the local VFS. Supported subcommands
  include `clone`, `fetch`, `checkout`, `rev-parse`, `status`, `log`,
  `ls-tree`. Only `https://`, `http://`, `file://` URLs (no SSH).
  `clone({ ref })` accepts "branch, tag, or commit". Network requests
  happen on the host DO, not in any shell isolate
  (`globalOutbound: null` is the documented shell posture).
- **Worker-shell backend**: `WorkerShellBackend` with
  `egress: { mode: "none" | "direct" | "http-gateway" }`; `none` is the
  default and blocks ambient shell networking. Requires a Worker Loader
  binding and the `experimental` compatibility flag. Host-forwarded
  `git` command is a separate host-side capability with its own network
  authority.
- **Local wrangler development**: `wrangler dev --local` with
  `nodejs_compat` and a SQLite Durable Object
  (`migrations: [{ tag, new_sqlite_classes }]`). The worker-shell
  backend additionally needs the Loader binding; the container backend
  needs Docker and a Cloudflare Container.

## PoC design decisions

- **No execution backend.** The R0A contract's "bounded execution" is a
  bounded command allowlist over the typed git/fs surface, not a shell.
  A filesystem-only workspace is explicitly supported upstream, so the
  PoC never enables ambient networking and never needs Docker, a Worker
  Loader, or a Cloudflare account.
- **Runner lives in the DO.** The released package exposes the typed
  git methods (`clone`/`fetch`/`checkout`/`revParse`) on the host-side
  `GitClient`; the RPC stub surface only forwards `git cli(...)` argv.
  The job runner therefore runs inside the Durable Object, which also
  matches the upstream "host owns the workspace" architecture.
- **Fail closed by construction and by check.** Manifests without a
  full 40-hex `repo_commit` are rejected before execution; after
  materialization the runner verifies `rev-parse HEAD == repo_commit`
  and skips all inspection if it does not match; any nonzero bounded
  command exit also yields `FAIL_CLOSED`.

## Layout

```text
tools/cloudflare_computer_poc/
  README.md
  package.json          # pinned deps; nothing added to the repo root
  tsconfig.json         # worker-side typecheck
  wrangler.jsonc        # local dev config (no deploy target)
  src/
    manifest.ts         # job manifest schema + validation
    commands.ts         # bounded command allowlist dispatcher
    result.ts           # result.json builder + report.md writer
    workspace-agent.ts  # DO: workspace + git + job runner
    worker.ts           # HTTP surface: POST /run, /marker, /file
  tests/
    manifest.test.ts    # unit: manifest contract
    result.test.ts      # unit: fail-closed result semantics
    smoke.ts            # e2e: wrangler dev + persistence + negative tests
    tsconfig.smoke.json # node-side typecheck for the smoke driver
  examples/
    job-manifest.smoke.json
```

## Job manifest contract

```jsonc
{
  "task_id": "r0a-smoke-1cb5fb7a",
  "repo_url": "https://github.com/Luke808real/a-share-limit-pullback.git",
  "repo_commit": "1cb5fb7a1792edccc18c70207340980377cbd4eb", // full SHA, mandatory
  "created_at": "2026-08-11T00:00:00.000Z",
  "purpose": "research-only R0A smoke fixture",
  "allowed_commands": ["git:status", "git:log-1", "read:README.md", "read:docs/project-operating-model.md"],
  "network_policy": { "egress": "none" },
  "input_files": ["README.md", "docs/project-operating-model.md"],
  "output_files": ["result.json", "report.md", "job-manifest.json"]
}
```

Rules:

- `repo_commit` must be exactly 40 hex chars; anything else (including
  a missing value or a floating branch name) is rejected with HTTP 400
  before any execution.
- `allowed_commands` must be a subset of the built-in allowlist; the
  dispatcher maps each entry to one typed git/fs call with an 8 KiB
  output cap.
- `network_policy.egress` must be `"none"`; `direct` or `http-gateway`
  are refused.

## HTTP surface (local dev)

```text
POST /run     { manifest }            -> run result.json (200) or 400/500
POST /marker  { task_id, op: write|read, content? }   -> persistence probe
POST /file    { task_id, path, max_bytes? }           -> bounded file probe
```

## Verification

```sh
npm install          # pinned, project-local only
npm run typecheck    # tsc (worker) + tsc (smoke driver)
npm test             # vitest unit tests (manifest + fail-closed semantics)
npm run smoke        # wrangler dev e2e (needs network for the GitHub clone)
```

The smoke test proves:

1. persistence: a marker written into the workspace survives a full
   `wrangler dev` restart (DO SQLite state on disk, not process memory);
2. exact-SHA materialization: clone of the public repo, `rev-parse HEAD`
   equals the requested SHA, `commit_match=true`, `result_status=SUCCESS`;
3. workspace artifacts: `result.json`, `report.md`, `job-manifest.json`
   exist in the VFS;
4. exact-SHA mismatch: a nonexistent SHA yields `commit_match=false`
   and `result_status=FAIL_CLOSED`, with inspection skipped;
5. missing commit SHA: rejected with HTTP 400 before execution.

The repository's own test suite and market data are never run.

## Known type bridges

- `ctx.storage` is cast to the package's `DurableObjectStorageLike`
  (declaration-only mismatch between the released 0.1.1 types and
  `@cloudflare/workers-types`).
- The DO stub is cast to the small `AgentRpc` interface (the Worker's
  typed view of the RPC surface).

Both are marked in code. No runtime behavior is changed.

## Security / egress notes

- `egress = none` by construction: no shell backend is configured, so
  there is no ambient network surface at all. The only outbound
  network is the host-side git capability (isomorphic-git inside the
  DO), which is the documented exception the R0A contract permits.
- No secrets, tokens, or credentials; the fixture uses a public repo.
- Bounded outputs: 8 KiB per command detail, 2 KiB per report block.
- Local development only. Nothing here deploys to Cloudflare.

## Limits (from upstream, preview package)

- `@cloudflare/computer@0.1.1` is PREVIEW ONLY; APIs are unstable.
- No SSH transport; no partial-clone blobs (`paths` is partial checkout
  only); no submodules/worktrees/hooks/gc.
- The git pack cache is unbounded in DO memory.
- The worker-shell and container backends are not exercised here;
  locally they would need a Worker Loader binding / Docker + a
  Cloudflare Container respectively.
- One transient workerd `internal error` was observed during a clone in
  local dev; the runner's fallback path recovered and the final
  `commit_match` check kept semantics fail-closed. Materialization
  method is recorded per run (preferred vs fallback). A bounded single
  retry (one extra attempt) applies only when a materialization attempt
  ends in that observed transient `internal error`; the smoke /run
  ceiling is 420 s to absorb slow GitHub clones over the local proxy.
