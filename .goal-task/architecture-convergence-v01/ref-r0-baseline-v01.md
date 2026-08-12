# REF-R0 Baseline Freeze — Evidence V01

Status: evidence collected, awaiting three-reader review.
Date: 2026-08-13 (Asia/Shanghai)
Scope: read-only characterization plus isolated-environment setup; no production code, test, config, or frozen artifact changed.

## 1. Repository and branch baselines

| Plane | Repository | Worktree | Branch | Base ref | HEAD SHA |
| --- | --- | --- | --- | --- | --- |
| Runtime | Luke808real/a-share-limit-pullback | `/Users/luke808/AI/V flash-architecture-convergence-v01` | `codex/architecture-convergence-v01` | origin/main | `1cb5fb7a1792edccc18c70207340980377cbd4eb` |
| Brain | Luke808real/a-share-strategy-brain | `/Users/luke808/AI/a-share-strategy-brain-architecture-convergence-v01` | `codex/architecture-convergence-v01` | origin/main | `2b15b44a4d2b586199e3824b817220f9fdfa281f` |
| ASL | rootSunc/ashare-lake (write target: fork Luke808real/ashare-lake) | `/Users/luke808/AI/ashare-lake-architecture-convergence-v01` | `codex/architecture-convergence-v01` | origin/main | `e13a3830d020be555a5c79f3b7f8fc2d4ad9d011` |

- Remote refs re-verified live on 2026-08-13: Runtime main `1cb5fb7a…`, Brain main `2b15b44a…`, ASL upstream main `e13a3830…`, ASL fork main `07ffe26d…`.
- All three worktrees clean at freeze time. Runtime has only the untracked `.goal-task/` task file set.
- Pre-existing dirty worktrees (`/Users/luke808/AI/V flash` at `0f08348…`, Brain and ASL working copies) were used read-only for frozen data/manifest lookup and were not modified.

## 2. Frozen truth anchors

- Brain frozen strategy: `phase-2d0`; frozen content commit `e865de484e40e45b1d2044ee1c58247c76f3a758`; main integration `2cabcf6ca0885993185453c3384fcf346fa4ddff`; baseline relation `MERGE_EQUIVALENT_TREE`.
- `e865de48…` and performance commit `34a4a13…` are both ancestors of Runtime HEAD `1cb5fb7a…`.
- Runtime `config/strategy.yaml` SHA-256 `47a0ea2b41952f06f43d1fe3a5e066993bade6ecec45c81103022008c7eae6bf` exactly matches Brain `BASELINE_MANIFEST.yaml` strategy file hash. Runtime `config/trade_plan.yaml` SHA-256 `06fd5dc96989a47015ad89ec543ad41784d7ef3eba074f17b679bd99d73a3c00`.
- Brain file hashes at `2b15b44a`: BASELINE_MANIFEST.yaml `6d13b973e561ec9eb8716e9bf7bc9f096a136eebdff9884dddbcc2a1735a5cb3`; STRATEGY_MASTER.md `6b813026d978709c3e9bf419b4a35d83fbfc6f2e5dd9f5b5215636bec562ffcf`; RULE_CATALOG.md `fe17dea4dc3838e1d22be8ba46271744757741d08af6b89c9f2d283e9c93b16d`; CURRENT_PHASE.md `0475abc71088812d5fc975e50299a536b83a3ca9273c464fea40d24211360433`; LLM_CONTEXT_PACK.md `c1fb72434e382988d73b804386668493896832400405e4109b91369bd14e5cf2`.
- Frozen reference snapshot: `snap-2026-07-31-b5f84004de8a`; as_of `2026-07-31`; manifest status `SCREEN_READY`; reconciliation policy `phase-2c2a-r1`. daily_bars parquet SHA-256 prefix `e7243dee3bafe46e725e2b6e` (full hash in manifest file hashes); source cloned read-only into the isolated data root.
- Corrected episodes reference SHA-256 `66d5943ffd4c83d8348d7b559ef9aa8ab9c041525471108a2f724fbedd84b093` (recorded in Brain truth; not replayed during R0).
- Authority gates per Brain CURRENT_PHASE (2026-08-08): `ST_READY=NO` (ST_DATA_NOT_READY), `PROVENANCE_GAP=OPEN`, `PRODUCTION_CUTOVER=NO_GO`. Merged ASL technical lineage is not production cutover.

## 3. Validation baselines (offline, no provider network)

| Repo | Interpreter | Command | Result |
| --- | --- | --- | --- |
| Runtime | CPython 3.11.15, venv, editable install + extras test/warehouse/integration + `pytdx==1.72` | `pytest -q` (default: integration excluded) | 547 passed, 11 skipped, 25 deselected in 235.54s |
| Brain | CPython 3.12.13, venv, pytest 9.1.1 | `pytest -q` | 47 collected, all passed, exit 0 |
| ASL | CPython 3.12.13, `uv sync --frozen --group dev` | `pytest tests/unit -q` | 1473 passed, 18 deselected (network), 1 warning in 25.61s |
| ASL | same env | `pytest -q` (full, network excluded) | 1479 passed, 18 deselected, 1 warning in 26.72s |

- Runtime extra gates: `python -m compileall -q src tests` OK; `git diff --check` OK.
- ASL runs must unset local proxy variables (`HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`, socks5h://127.0.0.1:7897): with the local proxy env present, httpx raises `ValueError: Unknown scheme for proxy URL` and 42 unit tests fail. This is an environment-isolation requirement, not an upstream code defect.
- Environment fingerprint (Runtime `hardware-profile`): arm64 native, no Rosetta, 10 logical CPUs, 16384 MB total memory.

## 4. Reference generation and performance baseline

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

## 5. Baseline characterization (targets for later phases)

Static inventory at `1cb5fb7a`:

- Layer sizes: models 2107 LOC, strategy 2586, screen 3504, providers 1251, warehouse 11112.
- Provider/warehouse dependency surface: models 0 files, strategy 0 files, screen 6 files, providers 5 files, warehouse 20 files, and top-level `cli.py`, `execution_reality.py`, `inspect.py`, `outcome.py`, `prc_audit.py`, `replay.py`, `trade_plan.py`, `universe.py`.
- `StrategySignal` carries 34 fields mixing frozen snapshots, setup stage, scoring, entry room and event flags in one model (candidate for Domain/State/Selection separation in REF-R2/R4/R5/R6).
- Reusable evidence machinery exists: generation lifecycle `STAGED -> VERIFIED -> ACTIVE / REJECTED` with hash and pointer verification in `screen/generation.py`.
- No `.github/workflows` found in the Runtime repository at this SHA (CI evidence gap; local tests are not CI).

Baseline findings recorded for later phases (not fixed in R0):

- F1 packaging gap: `pyproject.toml` at `1cb5fb7a` no longer declares `pytdx` in any extra, but the default test suite imports it via `providers/tdx_daily.py`; the clean environment needed an explicit `pytdx==1.72` pin to reach the green baseline.
- F2 chunked-path validation: `screen --rebuild` without `--start` reaches `run_chunked_screen` and fails with `AttributeError: 'NoneType' object has no attribute 'isoformat'` instead of the clear validation error that `run_screen` raises.
- F3 artifact shape: one full-market run JSON embeds all 1,844,543 rows and is 4.27 GB; the 16 chunk spools are merged into the single run artifact. Evidence artifact sizing is a candidate for REF-R7/E evidence work.

## 6. Non-goals confirmed untouched

- No strategy factor, threshold, coefficient, rule, or setup semantic changed.
- No frozen snapshot, generation, episode, outcome, receipt, hash, or forward epoch rewritten; the only full-market output is a new run artifact in the isolated worktree data dir, identified by a new run_id.
- No push, PR, merge, production cutover, Forward/OOS, Live, or TradePlan activation performed.
