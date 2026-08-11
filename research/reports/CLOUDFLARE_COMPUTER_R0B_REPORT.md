# CLOUDFLARE_COMPUTER_R0B_REPORT

STATUS: NETWORK_RECOVERED_R0B_RESUME_AUTHORIZED (2026-08-11 final
evidence closeout: HTTP 2/2 PASS, APT 2/2 PASS, pinned build PASS,
computerd boot PASS, NETWORK_STABILITY_GATE = PASS — see "R0B.NET
FINAL NETWORK EVIDENCE CLOSEOUT". All prior attempt records are
preserved as history.)

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

## R0B.NET — NETWORK PREREQUISITE RECOVERY

STATUS: NETWORK_PREREQUISITE_BLOCKED

BASE_HEAD: `d1e6ae282db1b84ed344dfea6f4de1c1a15f61ed`

Diagnosis-only task. No R0B implementation, no strategy/production
changes, no upstream Dockerfile or apt-mirror changes, no sudo, no
system proxy changes, no new software, no credentials printed.

### PROXY_PROVENANCE

```text
HOST_PROXY            HTTP_PROXY=http://127.0.0.1:7897
                      HTTPS_PROXY=http://127.0.0.1:7897
                      ALL_PROXY=socks5h://127.0.0.1:7897
                      NO_PROXY=localhost,127.0.0.1,::1
                      (no credentials present)
DOCKER_CLIENT_PROXY   ~/.docker/config.json: no "proxies" key -> CLI injects nothing
CONTAINER_PROXY_ENV   stock debian:stable-slim: NO proxy env vars
DOCKER_DESKTOP_PROXY  docker info: HTTP Proxy http.docker.internal:3128
                      HTTPS Proxy http.docker.internal:3128
                      No Proxy hubproxy.docker.internal, hubproxy.docker.internal:5555
HTTP_PROXY_SOURCE     host shell environment
HTTPS_PROXY_SOURCE    host shell environment
NO_PROXY              localhost,127.0.0.1,::1 (host); hubproxy.docker.internal:5555 (Docker Desktop)
```

Conclusion: the proxy seen by containers is injected by Docker Desktop
at the VM level (`http.docker.internal:3128`, configured with an
upstream proxy auto-detected from the macOS system proxy
127.0.0.1:7897). Docker Desktop's settings file
(`~/Library/Group Containers/group.com.docker/settings-store.json`)
contains no proxy keys; the active proxy configuration lives inside
Docker Desktop's internal settings and was not modified.

### NETWORK_MATRIX

All probes in ephemeral stock containers, `--platform linux/amd64`,
outputs bounded, no config changes:

```text
A baseline apt-get update
   result: PASS this run (Fetched 10.1 MB in 1min 14s, ~137 kB/s);
           previously FAILED 3/3 build attempts with 502 (flaky)
B proxy-disabled env (-e http_proxy= -e https_proxy= -e HTTP_PROXY=
  -e HTTPS_PROXY= -e ALL_PROXY= -e all_proxy=)
   result: FAIL - E: Failed to fetch
           http://deb.debian.org/debian/dists/stable-updates/InRelease
           502 Bad Gateway [IP: 151.101.78.132 80]
   -> clearing env changes nothing: not env injection
C NO_PROXY env (deb.debian.org,security.debian.org,debian.org)
   result: FAIL - E: Failed to fetch
           http://deb.debian.org/debian-security/.../Packages
           502 Bad Gateway [IP: 151.101.78.132 80]
   -> env NO_PROXY does not bypass: proxy is below the container env
D HTTPS-path diagnostic (alpine wget)
   https://deb.debian.org/debian/dists/stable/Release -> 200 OK, saved 135 kB
   http://deb.debian.org/debian/dists/stable/Release  -> HTTP/1.1 502 Bad Gateway
   -> same hostname, same Docker Desktop proxy path:
      HTTPS works, plain HTTP 502s
Host contrast (same local proxy 127.0.0.1:7897)
   https://deb.debian.org -> 200 ; http://deb.debian.org -> 200
   -> the local proxy alone is not the failure
```

Failing Fastly IPs observed: 146.75.46.132 and 151.101.78.132 (both
port 80). No operation was retried more than twice; no large logs were
retained.

### ROOT_CAUSE

`B = DOCKER_DESKTOP_PROXY_PATH`

Evidence:

1. `docker info` shows Docker Desktop's own proxy
   (`http.docker.internal:3128`) — the injection layer is Docker
   Desktop, not the CLI and not the host env.
2. Containers carry no proxy env; clearing env (B) and setting NO_PROXY
   (C) have no effect.
3. HTTPS through the same Docker Desktop proxy path succeeds while
   plain HTTP 502s (D) — the failure is inside the Docker Desktop
   proxy path's handling of plain-HTTP upstream fetches (intermittent;
   one baseline run passed slowly).
4. The host through 127.0.0.1:7897 succeeds for both schemes, so the
   local proxy alone is not the root cause.

### CHANGE_APPLIED

None. The injection layer is Docker Desktop's own proxy configuration,
which this task must not edit directly (its private settings/VM
storage). `~/.docker/config.json` was not modified (it has no proxy
keys), and no workaround (mirror change, upstream Dockerfile change,
host-network bypass) was applied.

### REVERSIBILITY

Not applicable — no change was applied. The only candidate fix would
be a reversible, GUI-level Docker Desktop proxy setting (see below).

### MANUAL_DOCKER_DESKTOP_PROXY_CHANGE_REQUIRED

Docker Desktop -> Settings -> Resources -> Proxies. Minimal change
(either):

```text
1. Unset/disable the "Web Server (HTTP) proxy" and "Secure Web Server
   (HTTPS) proxy" entries (containers then egress direct), or
2. Add to the proxy bypass ("Bypass proxy settings for these hosts"):
   deb.debian.org, security.debian.org, debian.org
```

After the user applies either change, re-run the stock-container
acceptance probe (`docker run --rm --platform linux/amd64
debian:stable-slim apt-get update`) before any further R0B gate.

### STOCK_DEBIAN_APT_RESULT

After the fix: PASS — `docker run --rm --platform linux/amd64
debian:stable-slim apt-get update` fetched 10.1 MB in 5 min 28 s
(~30.9 kB/s), no 502s, no errors (direct egress is slow but works).

### PINNED_BUILD_RESULT

After the fix: PASS — single `docker build --platform linux/amd64` of
the pinned upstream `examples/container/Dockerfile` completed
(`computerd-probe:0.1.1`, ~20 min at the slow direct-egress rate).

### CLOUDFLARE_BOOT_GATE

After the fix: PASS — `docker run` of the built image stayed
`running=true` (exit=0) and logged:

```text
[info] FUSE_MOUNT=auto resolved to backend=shim
computerd listening on 0.0.0.0:8080 mount=/workspace backend=shim
```

CLOUDFLARE_CONTAINER_BOOT_CAPABLE = TRUE.

### CHANGE_APPLIED / REVERSIBILITY

Applied by the user in the Docker Desktop GUI (2026-08-11), per the
manual-action contract:

```text
Settings -> Resources -> Proxies
Docker Desktop proxy : No proxy (was already selected; unchanged)
Containers proxy     : Same as host proxy -> No proxy   (THE change)
```

This Docker Desktop 4.86 UI exposes only proxy-mode radios (no
host-bypass field), so the agreed fallback was used. The change is
fully reversible in the same GUI: restore `Containers proxy =
Same as host proxy`. No config file was edited by this recovery:
`~/.docker/config.json`, daemon.json, and Docker's private
settings-store were untouched (settings-store hash still
`064c950d...`). Whether to keep the temporary mode or restore is the
user's decision.

### CORRECTNESS_BLOCKER

None for the network prerequisite: stock apt PASS, pinned upstream
build PASS, computerd boot PASS with `Containers proxy = No proxy`.
Residual notes: direct container egress is slow (~30 kB/s); the proxy
mode is temporary and restoring `Same as host proxy` would re-apply
the 502 path; R0B implementation itself has not started.

### R0B_RECOMMENDATION

NETWORK_RECOVERED_R0B_RESUME_AUTHORIZED — the environment gate now
passes end-to-end (engine healthy, amd64 execution, apt, pinned
upstream build, computerd boot). R0B implementation may resume as the
next task; it is NOT part of this task and was not started.

## R0B.NET FINAL NETWORK EVIDENCE CLOSEOUT

STATUS: NETWORK_RECOVERED_R0B_RESUME_AUTHORIZED

BASE_HEAD: `c4b1ccc7f22ded8bf511ee1d6216503062583006`

Validation/report-only task. No R0B implementation, no re-run of the
pinned build or computerd boot, no Docker Desktop / host proxy change,
no config.json / daemon.json / Dockerfile / mirror changes.

PROXY_MODE: unchanged from the previous acceptance state —
`Containers proxy = No proxy` (Docker Desktop proxy = No proxy),
applied by the user in the Docker Desktop GUI. Verified behaviorally
by the 2/2 HTTP and 2/2 APT runs below (any proxy-path regression would
have surfaced as 502).

HTTP_RUN_1: PASS — `docker run --rm --platform linux/amd64
alpine:latest wget http://deb.debian.org/debian/dists/stable/Release`
-> `HTTP/1.1 200 OK`, saved (ephemeral container #1).

HTTP_RUN_2: PASS — same URL, independent ephemeral container #2 ->
`HTTP/1.1 200 OK`, saved.

APT_RUN_1: PASS — existing evidence, NOT re-run:
`apt-get update` fetched 10.1 MB in 5 min 28 s, no 502, exit 0
(recorded at c4b1ccc).

APT_RUN_2: PASS — new independent run:
`docker run --rm --platform linux/amd64 debian:stable-slim apt-get update`
fetched 10.1 MB in 11 min 1 s (~15.3 kB/s), exit code 0, no 502.

PINNED_BUILD_RESULT: PASS — `computerd-probe:0.1.1` (single build of
the pinned upstream `examples/container/Dockerfile`), NOT re-run.

CLOUDFLARE_BOOT_GATE: PASS — computerd container stayed
`running=true` and logged `computerd listening on 0.0.0.0:8080
mount=/workspace backend=shim`; CLOUDFLARE_CONTAINER_BOOT_CAPABLE =
TRUE. NOT re-run.

REUSED_FROM_COMMIT: `c4b1ccc7f22ded8bf511ee1d6216503062583006`
(APT_RUN_1, PINNED_BUILD_RESULT, CLOUDFLARE_BOOT_GATE are cited from
that commit's verified results; they are not claimed as re-runs).

NETWORK_STABILITY_GATE: PASS

CORRECTNESS_BLOCKER: none for the network prerequisite. Residual
notes: (1) direct container egress is slow (~15-31 kB/s) and the
`Containers proxy = No proxy` mode is temporary by design — restoring
`Same as host proxy` re-applies the 502 path; (2) Docker Desktop
rewrote its own settings-store on the GUI change/restart
(settings-store.json hash now `30077ff8...`; previously `064c950d...`
at c4b1ccc) — the rewrite was performed by Docker Desktop itself, not
by this task (no config files were edited by us).

R0B_RECOMMENDATION: RESUME_AUTHORIZED — the network prerequisite gate
is formally closed (HTTP 2/2, APT 2/2, pinned build, computerd boot).
RESUME_AUTHORIZED != R0B_PASS; R0B implementation was not started and
must not start automatically.

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

false — the Cloudflare Computer Container backend was NOT exercised.
[Fact update 2026-08-11: the Docker runtime blocker is RESOLVED —
Docker Desktop 4.86.0 / engine 29.7.2 is installed and healthy on this
machine; the current blocker is network (see "RESUMED ATTEMPT 3" and
"R0B.NET" sections). The backend still has not run because the pinned
upstream container image cannot be built while container-network apt
fetches return 502.]

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

`NETWORK_PREREQUISITE_BLOCKED`: Docker is installed and healthy
(engine 29.7.2, hello-world PASS, linux/amd64 execution PASS), but
plain-HTTP apt fetches from inside Docker containers to
deb.debian.org (Fastly 146.75.46.132:80) return `502 Bad Gateway`
through the local proxy, blocking the pinned upstream container image
build (see "RESUMED ATTEMPT 3"). R0B must not be faked via
child_process, Docker exec outside Cloudflare Computer, or the
Worker-shell backend.

## R0C_RECOMMENDATION

NOT_AUTHORIZED — R0B did not pass (no real Container-backed Python
smoke ran). R0C (bounded research job manifest -> selected research
script -> bounded fixture/data input -> Python execution -> research
artifact -> provenance/hash package) is not part of this task and is
not authorized.
