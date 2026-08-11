# CLOUDFLARE_COMPUTER_R0B_REPORT

STATUS: NETWORK_PREREQUISITE_BLOCKED (2026-08-11 resumed environment
gate: the container runtime blocker is RESOLVED, but image builds are
blocked by container-network 502s; see "RESUMED ATTEMPT 3". All prior
attempt records are preserved as history.)

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

Re-checked on resume (2026-08-11): still unavailable — see the
"RESUMED ATTEMPT" section for the exact re-gate evidence.

## RESUMED ATTEMPT — PREREQUISITE RE-GATE (2026-08-11)

Re-opened R0B per the R0B_RESUME contract. Section 0 re-gate executed
exactly as specified; the smallest Cloudflare Computer container
availability probe was NOT reached because the Docker CLI itself is
absent.

```text
$ which docker
docker not found

$ docker --version
zsh:1: command not found: docker

$ docker info
zsh:1: command not found: docker

$ docker run --rm hello-world
zsh:1: command not found: docker
```

Alternative runtimes re-checked:

```text
podman  MISSING
colima  MISSING
orb     MISSING
orbctl  MISSING
lima    MISSING
limactl MISSING
```

Re-gate verdict:

```text
DOCKER_CLI = UNAVAILABLE
DOCKER_RUNTIME = NOT_CHECKED (daemon unreachable: no CLI)
TEST_CONTAINER = FAIL (not run: no CLI)
CLOUDFLARE_CONTAINER_BOOT_CAPABLE = FALSE
```

Any failed item requires `STATUS = BLOCKED_CONTAINER_PREREQUISITE`;
therefore R0B was NOT resumed. Nothing was implemented, and no PoC
source, tests, or configuration were modified by this attempt. The
only change is this report.

## RESUMED ATTEMPT 2 — FINAL CONTAINER GATE (2026-08-11)

Trigger: the user reported that a local container runtime had been
installed. The final gate was therefore re-run. The report's own
resume condition says this attempt is authorized only on that
confirmation; the evidence below shows the confirmed runtime is not
present on this machine.

Gate commands:

```text
$ which docker
docker not found

$ docker --version
zsh:1: command not found: docker

$ docker info
zsh:1: command not found: docker

$ docker run --rm hello-world
zsh:1: command not found: docker
```

Full-machine sweep (performed because the runtime was reported
installed but is not on PATH):

```text
/usr/local/bin/docker, /opt/homebrew/bin/docker, /usr/bin/docker: absent
/Applications/Docker.app, OrbStack.app, Rancher Desktop.app, UTM.app: absent
~/Applications/Docker.app: absent
brew formulae/casks matching docker|podman|colima|lima|orb|containerd: NONE
~/.docker, ~/.colima, ~/.orbstack, ~/.lima: absent
/var/run/docker.sock: absent
launchd container services: none (only macOS containermanagerd, unrelated)
podman, colima, orb, orbctl, lima, limactl, nerdctl, finch: all MISSING
```

Final gate verdict:

```text
DOCKER_CLI = UNAVAILABLE
DOCKER_RUNTIME = NOT_CHECKED (no CLI/daemon/socket anywhere)
TEST_CONTAINER = FAIL (not run)
CLOUDFLARE_CONTAINER_BOOT_CAPABLE = FALSE
```

`STATUS = BLOCKED_CONTAINER_PREREQUISITE`. R0B was not resumed; nothing
was implemented. The Cloudflare Computer container boot probe was not
reached. This is the final gate record for this state; no further
repeated gate-history commits will be made without a state change.

## RESUMED ATTEMPT 3 — ENVIRONMENT GATE (2026-08-11)

Trigger: Docker Desktop 4.86.0 was installed and validated on this
machine (arm64 host; engine 29.7.2; linux/amd64 execution working; the
pinned computerd image pulls successfully). R0B was therefore resumed
up to the environment gate.

Git state confirmed before any change:

```text
branch = research/cloudflare-computer-r0b
HEAD   = b1ed5614cabf3619e6a0ff35955a03e3e915bd37
worktree clean
```

Docker gate (passed):

```text
docker --version                     -> Docker version 29.7.2
docker info                          -> Server 29.7.2 / linux/aarch64
docker run --rm hello-world          -> PASS
docker run --rm --platform linux/amd64 debian:stable-slim uname -m -> x86_64

DOCKER_ENGINE = HEALTHY
HELLO_WORLD = PASS
AMD64_CONTAINER_BOOT = PASS
AMD64_UNAME = x86_64
```

Cloudflare Computer boot probe (pinned contract: computerd
`ghcr.io/cloudflare/computer-computerd-linux-x64:0.1.1`):

1. Raw image boot attempt (scratch image, entrypoint
   `/usr/local/bin/computerd`): FAILS with
   `rosetta error: failed to open elf at /lib64/ld-linux-x86-64.so.2`
   (exit 133). Expected: the scratch image ships only the SEA binary;
   the pinned upstream recipe (`examples/container/Dockerfile`) copies
   it into a debian base that supplies glibc. The boot probe therefore
   used the upstream recipe, exactly as the pinned example requires.
2. `docker build --platform linux/amd64` of the pinned upstream
   `examples/container/Dockerfile`: FAILED on all 3 attempts
   (initial + 2 bounded retries) at the debian apt step with:

   ```text
   E: Failed to fetch http://deb.debian.org/.../libkeyutils1_..._amd64.deb  502  Bad Gateway [IP: 146.75.46.132 80]
   E: Failed to fetch http://deb.debian.org/.../libpsl5t64_..._amd64.deb  502  Bad Gateway
   E: Failed to fetch http://deb.debian.org/.../libp11-kit0_..._amd64.deb  502  Bad Gateway
   E: Failed to fetch http://deb.debian.org/.../libcurl4t64_..._amd64.deb  502  Bad Gateway
   E: Failed to fetch http://deb.debian.org/debian-security/dists/stable-security/InRelease  502  Bad Gateway
   -> apt-get exit code 100, build failed
   ```

3. Reproduction in a stock container (environment-level, not a
   Dockerfile issue):

   ```text
   docker run --rm --platform linux/amd64 debian:stable-slim apt-get update
   -> E: Failed to fetch http://deb.debian.org/debian-security/.../InRelease  502  Bad Gateway [IP: 146.75.46.132 80]
   ```

4. Host-side probes (through the same local proxy 127.0.0.1:7897):

   ```text
   https://deb.debian.org/debian/  -> 200
   http://deb.debian.org/debian/dists/stable/Release -> 200
   https://pypi.org/simple/        -> 200
   ```

   The host HTTP(S) path works; plain-HTTP fetches from inside Docker
   containers to deb.debian.org (Fastly 146.75.46.132) return 502
   through the local proxy. Registry pulls (HTTPS) succeed.

Gate verdict:

```text
DOCKER_CLI = AVAILABLE
DOCKER_ENGINE = HEALTHY
HELLO_WORLD = PASS
AMD64_CONTAINER_BOOT = PASS
AMD64_UNAME = x86_64
CLOUDFLARE_CONTAINER_BOOT_CAPABLE = NOT_REACHABLE (image build blocked)

NETWORK_RETRY_COUNT = 2 (per the bounded-retry rule; same apt operation)
CLASSIFICATION = NETWORK_PREREQUISITE_BLOCKED
```

Per the resume contract, R0B implementation was NOT started: no PoC
source, tests, or configuration were modified, no Dockerfile was
written, and no workaround for the network failure was implemented.
The only change in this commit is this report.

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
