# CLOUDFLARE_COMPUTER_R0A_REPORT

STATUS: COMPLETE — R0A contract verified locally on the isolated review branch.

BRANCH: `research/cloudflare-computer-r0a`

BASE_HEAD: `1cb5fb7a1792edccc18c70207340980377cbd4eb`

HEAD_AFTER: the commit containing this report; resolve from Git metadata after
commit (returned as `REVIEW_COMMIT_SHA` in the task summary).

UPSTREAM_COMPUTER_HEAD: `9422fc860494f51a79eb0c525565026abf82aff6`
(`cloudflare/computer`); published preview package `@cloudflare/computer@0.1.1`
was used for the PoC.

## WHAT_WAS_BUILT

An isolated, research-only Cloudflare Computer PoC under
`tools/cloudflare_computer_poc/`, proving the R0A contract:

```text
exact repo commit
-> isolated persistent workspace
-> immutable job manifest
-> bounded git/file inspection
-> deterministic result/report
-> workspace persistence across reconnect
```

Design:

- A SQLite-backed Durable Object workspace per `task_id`
  (`idFromName(task_id)`), hosting the `@cloudflare/computer` VFS with
  the opt-in `createGitClient()` (isomorphic-git on the VFS).
- A job-manifest contract (`src/manifest.ts`): `task_id`, `repo_url`,
  `repo_commit`, `created_at`, `purpose`, `allowed_commands`,
  `network_policy`, `input_files`, `output_files`. Missing or
  malformed `repo_commit` (must be a full 40-hex SHA-1) is rejected
  with HTTP 400 before any execution; no floating `main` is accepted.
- A bounded inspection surface (`src/commands.ts`): an allowlist of
  `git:status`, `git:log-1`, `read:README.md`,
  `read:docs/project-operating-model.md`, each mapped to a typed
  git/fs call with an 8 KiB output cap. No shell is ever used.
- A deterministic runner (`src/workspace-agent.ts`): persists
  `job-manifest.json`, materializes the repo at the exact SHA (preferred
  `clone({ ref: sha, depth: 1 })`; fallback
  `clone` default + `fetch({ remoteRef: sha })` + `checkout`), verifies
  `rev-parse HEAD == repo_commit`, runs the bounded commands only when
  the commit matches, and writes `result.json` + `report.md`.
- `result.json` includes `task_id`, `requested_commit`, `actual_commit`,
  `commit_match`, `commands_run`, `exit_codes`, `result_status`
  (`SUCCESS` only when `commit_match=true`, no inspection was skipped,
  and every bounded command exited 0; otherwise `FAIL_CLOSED`).
- A thin HTTP surface (`src/worker.ts`): `POST /run`, `POST /marker`
  (persistence probe), `POST /file` (bounded workspace file probe).
- Tests: manifest unit tests, fail-closed result unit tests, and an
  end-to-end smoke test that drives `wrangler dev --local` twice
  (including a full restart) and runs positive, persistence, artifact,
  mismatch-negative, and missing-SHA-negative cases.

No execution backend (container / worker-shell / worker-javascript) is
configured: the filesystem-only workspace is an explicitly supported
upstream configuration, so the PoC has no ambient network surface, no
Docker dependency, no Worker Loader dependency, and no Cloudflare
account requirement.

## FILES_CHANGED

```text
tools/cloudflare_computer_poc/README.md
tools/cloudflare_computer_poc/package.json
tools/cloudflare_computer_poc/package-lock.json
tools/cloudflare_computer_poc/tsconfig.json
tools/cloudflare_computer_poc/wrangler.jsonc
tools/cloudflare_computer_poc/.gitignore
tools/cloudflare_computer_poc/src/manifest.ts
tools/cloudflare_computer_poc/src/commands.ts
tools/cloudflare_computer_poc/src/result.ts
tools/cloudflare_computer_poc/src/workspace-agent.ts
tools/cloudflare_computer_poc/src/worker.ts
tools/cloudflare_computer_poc/tests/manifest.test.ts
tools/cloudflare_computer_poc/tests/result.test.ts
tools/cloudflare_computer_poc/tests/smoke.ts
tools/cloudflare_computer_poc/tests/tsconfig.smoke.json
tools/cloudflare_computer_poc/examples/job-manifest.smoke.json
research/reports/CLOUDFLARE_COMPUTER_R0A_REPORT.md
```

Nothing outside the isolated subtree and this report was modified. The
Python repository root, strategy, config, and data layers are untouched.
`node_modules/` and local wrangler state are gitignored.

## CLOUDFLARE_APIS_USED

Inspected at the pinned upstream commit (only the five listed files):
`README.md`, `packages/computer/README.md`, `examples/think/README.md`,
`docs/12_worker_backend.md`, `docs/13_git_interface.md`.

APIs actually exercised by the PoC (`@cloudflare/computer@0.1.1`):

- `Workspace` constructed with `{ storage, git: createGitClient() }` in
  a Durable Object (`cloudflare:workers`).
- `workspace.fs`: `readFile`, `writeFile`, `rm` (VFS durability across
  DO restarts via DO SQLite).
- `workspace.git` (typed, host-side): `clone` (`url`, `dir`, `ref`,
  `depth`, `singleBranch`, `noTags`), `fetch` (`dir`, `url`,
  `remoteRef`, `singleBranch`, `tags`), `checkout` (`dir`, `ref`),
  `revParse` (`dir`, `ref`), `repoRoot` (`dir`), `cli` (`argv`, `cwd`).
- Durable Object `idFromName(task_id)` for stable per-task workspaces.
- `wrangler dev --local` with `nodejs_compat` and a SQLite DO migration
  (`new_sqlite_classes`) as the supported local development surface.

Confirmed but NOT exercised (documented for R0B): the three execution
backends and their requirements - Container (Docker + Cloudflare
Container + `computerd`), Worker shell (Worker Loader binding +
`experimental` flag; `egress: { mode: "none" }` default blocks ambient
shell networking), Worker JavaScript (Loader + `experimental`). The
host-forwarded `git` command is a separate host-side capability with its
own network authority; ambient shell egress and host git are
independent by design (docs/12, docs/13).

## POC_RESULT

- exact_commit_pin: TRUE - manifest requires a full 40-hex SHA;
  smoke fixture `1cb5fb7a1792edccc18c70207340980377cbd4eb`; verified
  `rev-parse HEAD` equals the requested SHA before any inspection.
- workspace_persistence: TRUE - marker written via `POST /marker`
  survived a full `wrangler dev` restart (DO SQLite state on disk;
  `--persist-to`), read back on a second invocation with the same
  `task_id`. Not process-global memory.
- git_materialization: TRUE - both paths observed working:
  `clone-ref-sha-depth1` (exact-SHA shallow clone) and the fallback
  `clone-default+fetch-sha+checkout`; the runner records which path was
  used, and `result_status` depends only on the verified HEAD equality.
- bounded_exec: TRUE - only allowlisted commands run, via the typed
  git/fs surface, 8 KiB output cap, zero shell, zero ambient network.
- fail_closed_mismatch: TRUE - nonexistent SHA yields
  `commit_match=false` and `result_status=FAIL_CLOSED` with inspection
  skipped; missing `repo_commit` rejected with HTTP 400 before
  execution.

## TEST_RESULTS

```text
npm run typecheck  -> PASS (worker tsc + smoke-driver tsc)
npm test           -> PASS 12/12 (manifest contract; fail-closed result semantics)
npm run smoke      -> PASS 7/7
```

Smoke assertions: persistence write; persistence read after restart;
exact-SHA materialization (`commit_match=true`, `actual_commit` equals
requested); bounded inspection (4 commands, exit codes `[0,0,0,0]`);
workspace artifacts present (`result.json`, `report.md`,
`job-manifest.json`); exact-SHA mismatch negative
(`FAIL_CLOSED`, `commit_match=false`); missing-SHA rejection (400).

The A-share test suite and market data jobs were not run.

## RESOURCE / ARCHITECTURE LIMITS

- `@cloudflare/computer@0.1.1` is PREVIEW ONLY; APIs unstable and
  subject to change; not suitable for production.
- ~10 GB per workspace (shared with the DO); agent-scale workspaces
  only, not full monorepos.
- Git surface: `https://`/`http://`/`file://` only (no SSH); no
  partial-clone blobs (`paths` is partial checkout only); no
  submodules, worktrees, hooks, or gc; the pack cache is unbounded in
  DO memory.
- Local dev runtime per `/run` was ~45-90 s, dominated by the GitHub
  clone over the machine's HTTP proxy.
- One transient workerd `internal error` was observed during a clone in
  local dev; the fallback path recovered and the final `commit_match`
  check kept semantics fail-closed. Materialization method is recorded
  per run. A bounded single retry (one extra attempt) applies only when
  a materialization attempt ends in that observed transient `internal
  error`; the smoke `/run` ceiling is 420 s to absorb slow GitHub clones
  over the local proxy.
- The worker-shell / container backends were deliberately not
  exercised; enabling them locally would require a Worker Loader
  binding and/or Docker plus a Cloudflare Container.

## SECURITY / EGRESS NOTES

- `network_policy.egress = "none"` is enforced at the manifest layer
  (any other value is refused) and by construction: no execution
  backend is configured, so there is no shell and no ambient network
  surface. The only outbound network is the host-side git capability
  (isomorphic-git in the DO), which is the documented exception the
  R0A contract permits ("Git materialization may use only the host-side
  Git capability explicitly supported by Cloudflare Computer").
- No secrets, tokens, or credentials; public repository only; no
  deployment, no Cloudflare account.
- Outputs are bounded (8 KiB per command detail; 2 KiB per report
  block); report content is deterministic per manifest.
- Type-level bridges are marked in code: `ctx.storage` cast to the
  package's `DurableObjectStorageLike` (declaration mismatch with
  `@cloudflare/workers-types`) and the DO stub cast to the small
  `AgentRpc` interface (the Worker's typed view of the RPC surface).

## FIT_FOR_A_SHARE_PROJECT

- useful: exact-commit, per-task isolated workspaces with immutable
  manifests and deterministic, fail-closed results; the
  verify-before-inspect ordering matches the project's evidence
  standards; no strategy/data involvement; research-only and locally
  verifiable.
- not useful (as-is): preview API instability; no SSH / private-repo
  auth path tested; worker-shell and container backends are not
  available locally without a Worker Loader / Docker + Cloudflare
  Container; unbounded git pack cache; not production material.
- recommended next phase: R0B - evaluate Cloudflare Container ->
  Python environment -> one targeted pytest subset -> immutable research
  artifact - only after upstream stabilization and only with the
  container prerequisite available; keep the R0A manifest + workspace
  harness as the job shell.

## CORRECTNESS_BLOCKER

None for the R0A scope. Residual risks: upstream preview API churn;
transient clone failures in local dev are possible and surface as
`FAIL_CLOSED` with the recorded error (never as a false SUCCESS); the
materialization method can vary between the preferred and fallback
paths, but `result_status` is a pure function of the verified HEAD
equality and bounded-command exit codes.

## R0B_RECOMMENDATION

AUTHORIZED - the R0A contract passes (exact pin, persistence,
materialization, bounded exec, fail-closed mismatch, verification
suite) on the isolated review branch. R0B is NOT implemented here; any
R0B work requires a separate contract and review, and the container
prerequisite.
