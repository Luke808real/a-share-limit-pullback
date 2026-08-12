# REF-R0 Baseline Freeze — Evidence V02

Status: round-2 evidence; all round-1 review findings addressed; awaiting three-reader re-review.
Date: 2026-08-13 (Asia/Shanghai)
Supersedes: ref-r0-baseline-v01.md (retired after round-1 review).

Round-1 review corrections incorporated:

- R1-FIX-1: authority-gate citation moved from `CURRENT_PHASE.md` (now a compatibility pointer) to `05_Codex/IMPLEMENTATION_LOG.md` (2026-08-08 entry) and `docs/CURRENT_STATE.md` pointers.
- R1-FIX-2: Runtime evidence table now separates code baseline SHA from the evidence commits; providers dependency count corrected to 4 files by AST analysis; `StrategySignal` field count corrected to 36; generation-lifecycle wording corrected (REJECTED is a constant/documentation state without an executable transition).
- R1-FIX-3: added TEST_HASH, GOLDEN_HASH, full input-closure hashes (daily_bars, limit_up_pool, snapshot manifest, warehouse.duckdb, run artifact), and ASL contract/version facts.
- R1-FIX-4: F1 (missing pytdx declaration) is resolved by re-declaring `pytdx>=1.7,<2` in the `integration` extra and verifying a fresh install; see section 7.
- R1-FIX-5: explicit statement that the full-market run used `--rebuild` without `--verify-replay`, and that the 20-stock frozen replay anchor is recorded from Brain truth but not locally reproduced (frozen code list is not in the changelog).
- R1-FIX-6: "no push performed" corrected: the task branch was pushed after the evidence commit, which is within the authorized scope; no PR, merge, cutover, or activation was performed.
- R1-FIX-7: three-repo status snapshot updated; Brain worktree now has an untracked `uv.lock` created by the R0 environment setup (explained in section 8).

## 1. Repository and branch baselines

| Plane | Repository | Worktree | Branch | Code base ref | Code base SHA |
| --- | --- | --- | --- | --- | --- |
| Runtime | Luke808real/a-share-limit-pullback | `/Users/luke808/AI/V flash-architecture-convergence-v01` | `codex/architecture-convergence-v01` | origin/main | `1cb5fb7a1792edccc18c70207340980377cbd4eb` |
| Brain | Luke808real/a-share-strategy-brain | `/Users/luke808/AI/a-share-strategy-brain-architecture-convergence-v01` | `codex/architecture-convergence-v01` | origin/main | `2b15b44a4d2b586199e3824b817220f9fdfa281f` |
| ASL | rootSunc/ashare-lake (write target: fork Luke808real/ashare-lake) | `/Users/luke808/AI/ashare-lake-architecture-convergence-v01` | `codex/architecture-convergence-v01` | origin/main | `e13a3830d020be555a5c79f3b7f8fc2d4ad9d011` |

- Runtime evidence commits on top of the code base: `6e6e9e8` (R0 evidence v01) and the v02 closure commit (packaging fix + v02 evidence). Evidence commit SHAs are recorded in the commit log and in `state.md`; the frozen code baseline for differential purposes remains `1cb5fb7a…`.
- Remote refs re-verified live on 2026-08-13: Runtime main `1cb5fb7a…`, Brain main `2b15b44a…`, ASL upstream main `e13a3830…`, ASL fork main `07ffe26d…`.
- Pre-existing dirty worktrees (`/Users/luke808/AI/V flash` at `0f08348…`, Brain and ASL working copies) were used read-only for frozen data/manifest lookup and were not modified.

## 2. Frozen truth anchors

- Brain frozen strategy: `phase-2d0`; frozen content commit `e865de484e40e45b1d2044ee1c58247c76f3a758`; main integration `2cabcf6ca0885993185453c3384fcf346fa4ddff`; baseline relation `MERGE_EQUIVALENT_TREE`.
- `e865de48…` and performance commit `34a4a13…` are both ancestors of Runtime code base `1cb5fb7a…`.
- Runtime `config/strategy.yaml` SHA-256 `47a0ea2b41952f06f43d1fe3a5e066993bade6ecec45c81103022008c7eae6bf` exactly matches Brain `BASELINE_MANIFEST.yaml` strategy file hash. Runtime `config/trade_plan.yaml` SHA-256 `06fd5dc96989a47015ad89ec543ad41784d7ef3eba074f17b679bd99d73a3c00`.
- Brain file hashes at `2b15b44a`: BASELINE_MANIFEST.yaml `6d13b973e561ec9eb8716e9bf7bc9f096a136eebdff9884dddbcc2a1735a5cb3`; STRATEGY_MASTER.md `6b813026d978709c3e9bf419b4a35d83fbfc6f2e5dd9f5b5215636bec562ffcf`; RULE_CATALOG.md `fe17dea4dc3838e1d22be8ba46271744757741d08af6b89c9f2d283e9c93b16d`; CURRENT_PHASE.md `0475abc71088812d5fc975e50299a536b83a3ca9273c464fea40d24211360433`; LLM_CONTEXT_PACK.md `c1fb72434e382988d73b804386668493896832400405e4109b91369bd14e5cf2`.
- Authority gates per Brain `05_Codex/IMPLEMENTATION_LOG.md` 2026-08-08 entry (lines 3-12): PR #36 + PR #37 merged (`0e37804c…`, `1cb5fb7a…`), main data path `ASL → ashare_lake.query → asl_query_adapter → immutable snapshot → bounded validator → state → strategy`, `asl_adapter.py` is `LEGACY_MIGRATION_FALLBACK`, no production runtime change, `ST_READY=NO`, `PROVENANCE_GAP=OPEN`, `PRODUCTION_CUTOVER=NO_GO`. `05_Codex/CURRENT_PHASE.md` is only a compatibility pointer; live authority also points through `docs/CURRENT_STATE.md`. Merged ASL technical lineage is not production cutover.
- Corrected episodes reference SHA-256 `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093` (Brain truth; not replayed during R0).

## 3. Input-closure and test/golden hashes

Frozen snapshot input closure (files cloned read-only into the isolated data root):

| File | SHA-256 |
| --- | --- |
| canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet | `e7243dee3bafe46e725e2b6ee884b07ac97a01c0705b41df0562d35019593514` |
| canonical/limit_up_pool/snap-2026-07-31-b5f84004de8a.parquet | `45faa1a23583b04acfd6c4faf5ef42311c2575c93a4c702cf5846d0213f31517` |
| manifests/snap-2026-07-31-b5f84004de8a.json (status SCREEN_READY, as_of 2026-07-31, policy phase-2c2a-r1) | `eb1f601faac66f2779ece368ebd7ce56deaf6e35eddcead25a55d63138b4451a` |
| warehouse.duckdb | `bc4b43d10beae44524610b32a8a9437d39c21a66b1c069fd8a6470a1f31171c8` |
| screen/runs/screen-rebuild-2026-07-31-snap-2026-07-0c0793274983.json | `9c37b9b6ee05ba51b0d28c158f874505175fd3d2e38fc4250741c95b1fdc458e` |

- TEST_HASH `9fb950f016ab3436c76e90f8a4a80c5b3070c7e20d062818ea6453a396bb2abd` = SHA-256 of `.goal-task/architecture-convergence-v01/baseline/test-file-hashes.txt` (SHA-256 per test file, 62 files, sorted).
- GOLDEN_HASH `1f215fd416eb8385623d5e4599b7d3873f9edecc9e7d944628a40fb90df977a0` = SHA-256 of `.goal-task/architecture-convergence-v01/baseline/golden-test-file-hashes.txt` (the six golden-relevant default-suite files: test_strategy_engine.py, test_replay.py, test_screen_gates.py, test_state_reader_correctness.py, test_contract_guards.py, test_fixture_contracts.py).
- ASL contract/version: package version `0.6.0`; pyproject.toml SHA-256 `8fa8671099ebd4fd3ddc1c571febc7177184fd3429e0b88160d66b0df2bf8b24`; uv.lock SHA-256 `03c29d660a5b87a2eb7134a3fde389e6b899ef61d17d0ef26491aa52ed6e6f1a`; single shipped config example `configs/ashare-lake.example.toml`.

## 4. Validation baselines (offline, no provider network)

| Repo | Interpreter | Command | Result |
| --- | --- | --- | --- |
| Runtime | CPython 3.11.15, venv, editable install + extras test/warehouse/integration | `pytest -q` (default: integration excluded) | 547 passed, 11 skipped, 25 deselected in 235.54s |
| Brain | CPython 3.12.13, venv, pytest 9.1.1 | `pytest -q` | 47 collected, all passed, exit 0 |
| ASL | CPython 3.12.13, `uv sync --frozen --group dev` | `pytest tests/unit -q` | 1473 passed, 18 deselected (network), 1 warning in 25.61s |
| ASL | same env | `pytest -q` (full, network excluded) | 1479 passed, 18 deselected, 1 warning in 26.72s |
| ASL | same env | `ruff check .` and `ruff format --check .` | all checks passed; 337 files formatted |

- Runtime extra gates: `python -m compileall -q src tests` OK; `git diff --check` OK.
- ASL runs must unset local proxy variables (`HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` pointing at socks5h://127.0.0.1:7897): with the local proxy env present, httpx raises `ValueError: Unknown scheme for proxy URL` and 42 unit tests fail. This is an environment-isolation requirement, not an upstream code defect.
- CI: ASL has GitHub Actions (python 3.10/3.12 matrix, `pytest --cov`, ruff). Runtime and Brain have no workflow files at these SHAs; local validation must not be presented as CI or review approval.
- Environment fingerprint (Runtime `hardware-profile`): arm64 native, no Rosetta, 10 logical CPUs, 16384 MB total memory.

## 5. Reference generation and performance baseline

Command: `limit_pullback screen --as-of 2026-07-31 --snapshot-id snap-2026-07-31-b5f84004de8a --start 2024-01-01 --rebuild --data-root data` (auto-routed to the process-isolated chunked path; 16 chunks x 200 codes).

| Metric | Value |
| --- | --- |
| run_id | `screen-rebuild-2026-07-31-snap-2026-07-0c0793274983` |
| output_hash | `9abb16e4a5720503e4ffea5462067dc1b476d8022f0593a657c328f9836920ec` |
| frozen reference match | YES: equals Brain-recorded `FULL_MARKET_HASH` (`9abb16e4…`) |
| rows_count | 1,844,543 |
| universe_size | 3191 |
| status_counts | B1_READY 17689, B2_CONFIRMED 4433, B2_READY 39949, INVALID 67646, NEW_ANCHOR 22393, NORMAL 1681515, WATCH_PULLBACK 10918 |
| active_setup_count | 219 |
| strategy_commit | `1cb5fb7a1792edccc18c70207340980377cbd4eb` |
| wall time | 269.84s |
| max resident set size | 2,386,182,144 bytes (max child; parent peak 158,449,664 bytes) |
| run JSON artifact size | 4,274,032,081 bytes |
| verify_replay | NOT executed; artifact `verify_replay_matched=null` |

Evidence strength and limits:

- `output_hash` is the SHA-256 over the ordered complete-row JSON output (per `screen/chunk_contract.py` row-spool hashing). Equality with the frozen reference is a strong byte-level row anchor, but it does not by itself prove independent state/signal semantic projection, schema decoding, or lineage/manifest equivalence; those stay explicit later-phase gates.
- The frozen 20-stock rebuild replay anchor exists in Brain `01_Strategy/CHANGELOG.md` (2026-08-01 phase-2c2b entry): 11,378 rows, field-identical, hash `6c2ffc2235fabd9e32c3aff227fc27d9aac622cb68a1fa6c9ba99a8d1d18b418`. It is recorded here as frozen reference truth; local reproduction is not possible from the changelog alone because the frozen 20-code list is not recorded there. Reproducing it (with the exact frozen code list and input closure) is a REF-R1/R7 anchor task, not silently assumed done.
- The full-market run proves screen-output reproducibility at the frozen snapshot; it does not prove PIT replay parity (`verify_replay_matched=null`).

## 6. Baseline characterization (targets for later phases)

Static inventory at `1cb5fb7a`:

- Layer sizes: models 2107 LOC, strategy 2586, screen 3504, providers 1251, warehouse 11112.
- Provider/warehouse dependency surface (AST import analysis): models 0 files, strategy 0 files, screen 6 files, providers 4 files (`akshare_limit_pool.py`, `baostock_daily.py`, `tdx_daily.py`, `tencent_daily.py`; `__init__` re-exports are not counted as imports), warehouse 20 files, and top-level `cli.py`, `execution_reality.py`, `inspect.py`, `outcome.py`, `prc_audit.py`, `replay.py`, `trade_plan.py`, `universe.py`.
- `StrategySignal` declares 36 fields at `src/limit_pullback/models/signal.py`, mixing frozen snapshots, setup stage, scoring, entry room and event flags in one model (candidate for Domain/State/Selection separation in REF-R2/R4/R5/R6).
- Generation machinery: `screen/generation.py` defines `STAGED -> VERIFIED -> ACTIVE` executable transitions and a `REJECTED` constant with documentation-only semantics (no executable transition to REJECTED was found). Wording above reflects the implemented path, not the documented constant.
- Per Brain `IMPLEMENTATION_LOG.md`, main data path at `1cb5fb7a` already routes ASL query adapter → immutable snapshot → validator → state → strategy, with the legacy `asl_adapter.py` as migration fallback; REF-R3 will formalize the canonical port and legacy shadow/retirement gates.

Baseline findings:

- F1 RESOLVED: at `1cb5fb7a` the `integration` extra no longer declared `pytdx`, while default tests import it. Fixed by re-declaring `pytdx>=1.7,<2` in the `integration` extra (separate focused commit); verified by uninstalling pytdx, reinstalling from the declared extras, and re-running `tests/test_adr008_data_correctness.py` (20 passed).
- F2 OPEN: `screen --rebuild` without `--start` reaches the auto-chunked path and fails with `AttributeError: 'NoneType' object has no attribute 'isoformat'` instead of the clear validation error that `run_screen` raises. No behavior impact on the valid invocation; fix is scheduled as a REF-R7 CLI/contract prerequisite, not part of R0.
- F3 OPEN: one full-market run JSON embeds all 1,844,543 rows (4.27 GB) and chunk spools are deleted at merge time. A streamed row-level diff plus a chunk hash/index retention policy must be decided before behavioral refactoring so later differential parity stays localizable and re-runnable.

## 7. Later-phase hard prerequisites (recorded now, not claimed)

- Replay(D) = Daily(D) has no pre-refactor baseline run; REF-R7 must prove field-for-field parity against the frozen reference, and must not treat "new path self-consistency" as "existing semantics preserved".
- ASL-vs-Legacy equivalence has no baseline; current authority is `ST_READY=NO`, `PROVENANCE_GAP=OPEN`, `PRODUCTION_CUTOVER=NO_GO`. REF-R3 cannot complete until ST readiness, provenance closure, and an equivalence gate are evidenced.
- The 20-stock frozen replay (11,378 rows / `6c2ffc22…`) should be reproduced with the exact frozen input closure once its code list is recovered from frozen records; until then it is frozen-reference-only.
- Runtime and Brain lack CI workflows at these SHAs; all completion claims are local-validation-scoped unless CI is added.

## 8. External state and non-goals

- The Runtime task branch was committed and pushed (`6e6e9e8`, then the v02 closure commit); pushing the task branch is within the authorized scope. No PR created yet, no merge, no protected-branch write, no production cutover, no data publication, no Forward/OOS/Live/TradePlan activation.
- Brain worktree status after R0 environment setup: `?? uv.lock` (untracked lock generated by the `uv sync` environment bootstrap). It is an environment artifact; it is recorded here, kept for reproducible local runs, and excluded from all commits. Runtime worktree: modified `pyproject.toml` plus `.goal-task/` task files only; ASL worktree clean.
- No strategy factor, threshold, coefficient, rule, or setup semantic changed. No frozen snapshot, generation, episode, outcome, receipt, hash, or forward epoch rewritten; the full-market run produced a new artifact with a new run_id in the isolated worktree data dir only.
