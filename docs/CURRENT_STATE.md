# Current State Compatibility Pointer

<!-- CURRENT_STATE_POINTER=true -->

Last remote verification: **2026-08-11 (Asia/Shanghai)**.

This repository does not own project current truth. The canonical overwrite-style
state is:

```text
repository: Luke808real/a-share-strategy-brain
path: 00_Project/CURRENT_STATE.md
handoff: 00_Project/AGENT_HANDOFF.md
verified_remote_main: 2b15b44a4d2b586199e3824b817220f9fdfa281f
```

The verified Project OS assigns runtime implementation and artifacts to V Flash,
data facts and lineage to the validated ASL project SHA, and project execution
status to the brain repository. This file is only a compatibility pointer for
older V Flash entry links; it must not acquire an independent phase, Gate,
blocker, roadmap, snapshot, state, or authorization table.

## Resolution protocol

1. Re-check the brain repository's remote `main` SHA.
2. Read `00_Project/AGENT_HANDOFF.md`, then `00_Project/CURRENT_STATE.md` at that
   exact SHA.
3. Follow its authority pointers to the exact V Flash or ASL evidence required
   by the task.
4. If the remote SHA changed, this verification receipt is stale. Re-read the
   canonical files; do not copy their content into this pointer.

If the canonical state is unavailable, stale, contradictory, or lacks an exact
authorization receipt, fail closed: do not generate state, start R9/OOS, run
Forward or TradePlan, promote Production, change frozen strategy semantics, or
infer that missing output means zero candidates or normal market state.

The local sibling brain checkout may be dirty or behind remote `main`; local
branch names and cached `origin/main` refs are not substitutes for the verified
remote authority.
