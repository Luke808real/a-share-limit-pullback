# CI — Cloud + Mac Data Gate

## CLOUD CI（自动）

- Workflow: `.github/workflows/ci.yml`
- Trigger: `push` / `pull_request`（不使用 `pull_request_target`）
- Runner: GitHub-hosted `ubuntu-latest`；Python 3.12
- 运行内容（**不依赖任何本地市场数据库**）：
  - `python -m compileall -q src research/second_launch/factors_v01`
  - `pytest tests/test_r5a_benchmark_contract_v01.py tests/test_r5b_benchmark_execution_v01.py -m "cloud_ci and not local_data"`
- 权限：`contents: read`
- 依赖：仅 `[project.optional-dependencies].ci`（pytest / numpy / pandas）。
  不安装 provider / warehouse 栈；不读取 `data/` 本地数据；不下载行情。

## DATA CI（手动）

- Workflow: `.github/workflows/data-ci.yml`
- Trigger: 仅 `workflow_dispatch`（手动；无 push/PR/schedule）
- Runner: `[self-hosted, macOS, asl-data]`
- 运行内容：R5A/R5B **全部** targeted tests（含 `local_data`）+ frozen SHA/binding gate
- 结束检查：`git status --porcelain` 必须 clean，否则 FAIL（fail closed）
- 只读：不下载、不调用 provider、不改源库、不上传任何数据 artifact

### 准备（Mac self-hosted runner 环境）

1. 注册 runner 前，在 runner 环境设置变量：
   `A_SHARE_DATA_ROOT=<本地冻结数据根目录>`（例如包含
   `canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet` 的目录）。
2. Workflow 通过 `scripts/ci/prepare_local_data_ci.sh` 校验路径与必需 artifact，
   并在工作区创建 `data` 符号链接（只读用法）。

## Mac runner labels

```text
self-hosted
macOS
asl-data
```

## 安全约束（必须遵守）

```text
DO NOT enable arbitrary fork PR execution
DO NOT put runner registration token in the repo
DO NOT put tokens in committed .env files
DO NOT expose home directory broadly
DO NOT upload market database / canonical snapshot / feature-outcome datasets
DO NOT auto-register the runner from this repository
```

## 状态

```text
SELF_HOSTED_RUNNER_STATUS = PREPARED_NOT_REGISTERED
```

用户后续只需按 GitHub Settings → Actions → Runners 手动完成一次注册，
并在 runner 环境配置 `A_SHARE_DATA_ROOT` 后，手动触发 `mac-data-ci`。
