# CLOUDFLARE_COMPUTER_R0B_REPORT

STATUS: BLOCKED_CONTAINER_PREREQUISITE

The R0B hard gate (section 0 of the task) failed during pre-flight. No
R0B implementation was attempted; the Cloudflare Computer Container
backend cannot be exercised in the supported local environment.

BRANCH: `research/cloudflare-computer-r0b`

BASE_HEAD: `dbf411e3f1fabd09aa9def2c2578c57e42fae21e`

HEAD_AFTER: the commit containing this report; resolve from Git metadata after
commit (returned as `REVIEW_COMMIT_SHA` in the task summary).

UPSTREAM_COMPUTER_VERSION: `cloudflare/computer` pinned at
`9422fc860494f51a79eb0c525565026abf82aff6`; published preview package
`@cloudflare/computer@0.1.1` (as used by R0A / R0A1).

## FILES_CHANGED

```text
research/reports/CLOUDFLARE_COMPUTER_R0B_REPORT.md
```

Only this report. No PoC source, tests, configuration, strategy, or
data files were modified.

## CONTAINER_PREREQUISITE

Checklist on this machine (2026-08-11):

```text
docker    MISSING (no docker CLI / daemon)
podman    MISSING
colima    MISSING
orb/orbctl MISSING
node      OK      (v24.16.0)
npm       OK      (11.13.0)
wrangler  OK      (project-local devDependency in tools/cloudflare_computer_poc)
```

Exact missing prerequisite: **Docker (or any equivalent local container
runtime)**. Upstream evidence at the pinned revision:

- `examples/container/README.md` ("Run it locally"): "Requires Docker.
  The Dockerfile pulls [the computerd binary] from the public GitHub
  Container Registry on first build".
- `examples/container/Dockerfile`: builds a Debian image staging the
  `computerd` daemon (FUSE mount + exec runner + capnweb RPC, per
  `docs/07_injected_service.md`); under `wrangler dev` this image is
  built and run through Docker.
- `docs/05_runtime_interface.md` confirms the intended surface is
  `workspace.runtime.exec(source, { backend: "container-shell", cwd,
  encoding, timeoutMs, ... })` — the backend cannot be reached without
  the container image/runtime.

Per the task's hard gate, no substitute was used: no local
child_process, no Docker-exec-outside-Cloudflare-Computer, no
Worker-shell backend, and no Python execution outside the Container.

## R0A1_REGRESSION

Not applicable to code: no PoC code changed, so R0A1 contracts
(immutable manifest / MANIFEST_CONFLICT, UTF-8 byte caps, exact-SHA
fail-closed) are untouched. R0A1 verification was green at BASE_HEAD:
typecheck PASS, 29/29 unit tests, 11/11 smoke (recorded in the R0A1
report at `dbf411e`).

## EXECUTION_PROFILE

Not implemented (gate). The intended profile for a later attempt:

```text
profile_id: PYTEST_CONFIG_V01
command:    python -m pytest -q tests/test_config.py
```

## PYTHON_VERSION

Not executed. Repository contract verified at BASE_HEAD:
`pyproject.toml` declares `requires-python = ">=3.11,<3.13"` (prefer
3.12/3.11 in the container image) and a pytest dev extra
(`pytest>=8.3,<9`). `tests/test_config.py` exists at BASE_HEAD and is
config-only (no market data).

## DEPENDENCY_INSTALL

Not executed (gate).

## EXACT_COMMIT_PIN

Not executed. The R0A1 exact-SHA materialization contract was intended
to be reused for `repo_commit = dbf411e3f1fabd09aa9def2c2578c57e42fae21e`.

## CONTAINER_BACKEND_PROOF

false — the Cloudflare Computer Container backend was NOT exercised:
the required Docker runtime is absent (see CONTAINER_PREREQUISITE).

## PYTEST_TARGET

`python -m pytest -q tests/test_config.py` — NOT run (gate).

## PYTEST_RESULT

NOT RUN.

## ARTIFACTS

None created (`/execution-result.json`, `/execution-stdout.txt`,
`/execution-stderr.txt` were not written).

## ARTIFACT_HASHES

None computed.

## NEGATIVE_TESTS

None added (no code changes; the gate forbids implementation).

## NETWORK / EGRESS

Unchanged from R0A1: no execution backend configured; host-side git is
the only outbound capability; `network_policy.egress = "none"`.

## RESOURCE_USAGE

```text
duration:          n/a (no container run)
workspace size:    n/a
stdout/stderr bytes: n/a
```

## CORRECTNESS_BLOCKER

`BLOCKED_CONTAINER_PREREQUISITE`: Docker (or an equivalent local
container runtime such as podman/colima/orbstack) is required to build
and run the Cloudflare Computer `computerd` container image under
`wrangler dev` (upstream `examples/container` README/Dockerfile), and
no container runtime is installed on this machine. R0B must not be
faked via child_process, Docker exec outside Cloudflare Computer, or
the Worker-shell backend.

## R0C_RECOMMENDATION

NOT_AUTHORIZED — R0B did not pass (no real Container-backed Python
smoke ran). R0C (bounded research job manifest -> selected research
script -> bounded fixture/data input -> Python execution -> research
artifact -> provenance/hash package) is not part of this task and is
not authorized.
