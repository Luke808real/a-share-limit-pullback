# Final Completion-Condition Evidence Table (2026-08-13)

Authoritative per-condition evidence for the 10 completion gates. Statuses:
DONE / PARTIAL / WAITING-EXTERNAL. Evidence paths are relative to the Runtime
task worktree unless noted.

| # | Condition | Status | Evidence |
| --- | --- | --- | --- |
| 1 | One canonical data boundary; zero direct provider/ASL-internal deps in strategy/runtime code | DONE (with recorded exemption) | `tests/test_data_ports.py`, `tests/test_screen_data_boundary.py`, `tests/test_architecture_constitution.py`; screen + five read-side tools zero warehouse imports; data layer owns canonical/pool-quality; `cli.py` acquisition commands exempt and recorded in `ref-r8-legacy-inventory.md` |
| 2 | Feature/Policy and State/Ranking separation; one lifecycle/state engine | DONE | `src/limit_pullback/features`, `src/limit_pullback/state`, `src/limit_pullback/selection` boundary tests; eligibility/presentation mapping registered; R5 three-reader ACCEPT |
| 3 | R9 consumes candidate context only | DONE (producer surface, from git history) | read-only audit of `research/second_launch/walk_forward_v01/r9_prospective_factor_producer_v01.py` at branch `048b2c8a…` (state.md); ledger accumulator = evidence writer |
| 4 | Replay/Daily share one Domain Core, field-identical | DONE | `runtime/common.evaluate_day`; `tests/test_runtime_common.py` orchestration parity (603221/603580 real pool, transitions exercised) |
| 5 | state/signal/artifact diff=0 on frozen reference + PIT/UNKNOWN/Transition/Contract/Golden/fail-closed | DONE | `evidence/verification/frozen_differential.py`; baseline `frozen-rebuild-summary-v01.json`; rebuild `a9e617fd38aa` output_hash `9abb16e4…`; 598 passed suite incl. PIT/transition/golden tests |
| 6 | Formal runs have hashable manifest + fingerprint + receipt + resolvable lineage | PARTIAL (receipt both paths; lineage pending) | `evidence/verification/fingerprint.py`, `receipt.py`, `wire.py`; receipts emitted on chunked (`e1fbe066e6c2`) and non-chunked (`73fbeedf9c7b`) paths; `predecessor_generation_id` null (P6.3 blocked: pointer resolver absent from merged main) |
| 7 | Repo-native validation + performance ≤1.15×/≤1.10× | DONE | Runtime 598 passed/11 skipped/25 deselected; Brain 47 passed; ASL 1479 passed (3.12, no proxy); P4 re-test 266.99s / 2.387GB RSS / 4.27GB artifact = 0.989×/1.0005×/1.000× |
| 8 | Three independent reviewers, no unresolved high-severity findings | DONE | Every phase ACCEPTed by CODE/DATA/ADVERSARIAL readers; final verdict ALL_IN_REPO_DONE |
| 9 | Legacy deletion proofs + explicit human approval | WAITING-EXTERNAL | Approval granted ("全部批准"); fresh inventory shows no retirement set at zero deps (acquisition still live); deletions wait on ST/PROVENANCE/CUTOVER closure via ASL PR #21 + production ST backfill |
| 10 | Exact SHAs + Draft PRs per repo; no cutover claims | DONE/WAITING-EXTERNAL | Runtime main merge `8e7affc…`, Brain merges `13ec156…` + `aa92ade…`; ASL PRs #19 (docs) and #21 (ST series) OPEN awaiting rootSunc maintainer; task branch `f202a9d…` |

Outstanding external chain (verified, not guessed):

1. rootSunc maintainer merges ASL PR #19 and #21 (upstream main unchanged at
   `e13a3830…`).
2. Production ST backfill per the existing resume-ledger operational procedure
   (isolated worktree has no production config/data root; blind runs forbidden).
3. Gates flip ST_READY → PROVENANCE_GAP → PRODUCTION_CUTOVER with real evidence.
4. R8 retirement sets then become provable; per-set deletion with rollback
   evidence and approval.
5. P6.3 implementation once the generation-pointer machinery lands in main.
