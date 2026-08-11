# CLOUDFLARE_COMPUTER_R0A1_REPORT

STATUS: COMPLETE — R0A1 provenance hardening verified on the isolated review branch.

BASE_HEAD: `9d46ec759009fbf3ccce21b9cf73f48fd8b80f63`

HEAD_AFTER: the commit containing this report; resolve from Git metadata after
commit (returned as `REVIEW_COMMIT_SHA` in the task summary).

## FILES_CHANGED

```text
tools/cloudflare_computer_poc/src/manifest.ts
tools/cloudflare_computer_poc/src/result.ts
tools/cloudflare_computer_poc/src/workspace-agent.ts
tools/cloudflare_computer_poc/src/worker.ts
tools/cloudflare_computer_poc/tests/manifest.test.ts
tools/cloudflare_computer_poc/tests/utf8.test.ts
tools/cloudflare_computer_poc/tests/smoke.ts
tools/cloudflare_computer_poc/README.md
research/reports/CLOUDFLARE_COMPUTER_R0A1_REPORT.md
```

Scope was strictly the PoC subtree, its README, and this report. No
strategy/config/ASL/Snapshot/State/Forward/TradePlan changes; no
Container, no Worker shell, no Python execution.

## IMMUTABLE_MANIFEST

Fixed: `runJob()` no longer overwrites `/job-manifest.json` for an
existing `task_id`.

- First manifest for a `task_id` is persisted (written only when no
  stored manifest exists) and is never overwritten afterwards.
- Same semantic manifest may be replayed idempotently: the job re-runs
  and `result.json`/`report.md` are refreshed.
- Different manifest for the same `task_id` fails closed with an
  explicit `MANIFEST_CONFLICT` (HTTP 409, `result_status:
  FAIL_CLOSED`) before any write, materialization, or inspection.
- Stored manifest/result/report are preserved on conflict (verified
  byte-identical in smoke).
- Canonical comparison (`canonicalManifest`) recursively sorts JSON
  keys, so equality does not depend on key order; field values are
  compared exactly, including `created_at` and `purpose`.
- The conflict outcome crosses the DO RPC boundary as a plain,
  serializable `{ kind: "MANIFEST_CONFLICT", message }` value because
  custom Error classes do not survive Workers RPC intact (observed
  during development; the 500-vs-409 behavior was corrected).

Tests: unit (`checkReplay`: first-write allowed, A->A replay allowed
under key reorder, A->B rejected, corrupt stored manifest rejected;
`canonicalManifest` order-independence) plus smoke (A run SUCCESS,
A replay SUCCESS despite reordered JSON keys, A->B rejected 409, stored
`job-manifest.json` and `result.json` byte-identical before/after the
conflict attempt).

## MANIFEST_CONSISTENCY

Provenance declarations are validated in `validateManifest`, before
materialization:

- every `read:*` command must reference a declared `input_file`
  (exact match on the path after `read:`);
- `output_files` must declare the fixed outputs `result.json`,
  `report.md`, `job-manifest.json`.

Contradictory manifests are rejected with HTTP 400. Unit tests cover
both directions (undeclared input file rejected; declared input file
accepted; each missing required output rejected).

## UTF8_BYTE_CAP

`truncateUtf8` and `readFileBounded` now treat `maxBytes` as true UTF-8
bytes:

- truncation happens on code-point boundaries (never splits a UTF-8
  sequence, never introduces U+FFFD);
- the truncation marker is budgeted, so the encoded result (marker
  included) is always `<= maxBytes` bytes; when the limit is smaller
  than the marker itself, a marker-free UTF-8-safe prefix is returned;
- `readFileBounded` reports the real byte count
  (`TextEncoder().encode(...).byteLength`) instead of code units.

Regression tests include Chinese text, emoji, ASCII, and mixed
samples; every assertion checks encoded output `<=` the configured
byte limit.

## DETERMINISTIC_SEMANTICS

Documented precisely in the README:

```text
DETERMINISTIC_DECISION_SEMANTICS = true
BYTE_IDENTICAL_RUN_ARTIFACT = false
```

`result_status`, `commit_match`, `commands_run`, and `exit_codes` are
pure functions of the manifest plus the verified repository state.
Run artifacts are NOT byte-identical across runs: `created_at`, the
recorded `materialization` path (preferred vs fallback vs reuse), and
report text may legitimately vary. No byte-identical report is
claimed. No attempt/event system was added.

## LOCAL_SECURITY_BOUNDARY

- `/run`, `/file`, and `/marker` are documented as trusted-local PoC
  surfaces: no authentication, authorization, or rate limiting, and
  none added.
- Arbitrary deployment is explicitly NOT authorized; there is no
  deploy configuration and no Cloudflare account usage.
- Host-side git (isomorphic-git in the DO) remains the only allowed
  outbound capability; `egress = none` by construction (no execution
  backend).

## TYPECHECK

PASS — `npm run typecheck` (worker tsc + smoke-driver tsc).

## UNIT_TESTS

PASS — `npm test`: 29/29 (manifest contract incl. replay/consistency,
fail-closed result semantics, UTF-8 byte caps).

## SMOKE_TEST

PASS — `npm run smoke`: 11/11, including the new manifest-conflict
persistence phase:

```text
persistence write / read after restart
exact-SHA materialization (commit_match=true)
bounded inspection (4 commands, exit codes [0,0,0,0])
workspace artifacts present
manifest A first run -> SUCCESS
manifest A -> A replay (reordered keys) -> idempotent SUCCESS
manifest A -> B -> 409 MANIFEST_CONFLICT, FAIL_CLOSED
A -> B does not mutate stored A (job-manifest.json + result.json unchanged)
exact-SHA mismatch -> FAIL_CLOSED
missing commit SHA -> 400
```

`git diff --check` PASS. The A-share test suite and market data jobs
were not run.

## CORRECTNESS_BLOCKER

None for the R0A1 scope. Residual notes: the DO-side conflict check is
authoritative; the Worker returns 409 for the sequential conflict case
proven in smoke. Concurrent conflicting submissions to the same
`task_id` could surface as a 500 fail-closed response rather than 409
(not a correctness hole; out of scope for a trusted-local PoC).

## R0B_RECOMMENDATION

AUTHORIZED — all four R0A defects (immutable manifest, manifest
consistency, true UTF-8 byte caps, determinism wording) are fixed and
verified. R0B (Container -> Python -> one targeted pytest subset) is
NOT implemented; it requires a separate contract and review plus the
container prerequisite.
