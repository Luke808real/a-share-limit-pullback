# R0B research PoC container image.
#
# - computerd daemon (pinned upstream 0.1.1) as ENTRYPOINT; it mounts
#   the workspace VFS at /workspace (userspace shim under wrangler dev)
#   and answers exec over capnweb.
# - Python 3.12 (repo contract: >=3.11,<3.13) with the MINIMAL
#   dependency set required by PYTEST_CONFIG_V01
#   (tests/test_config.py import graph: pytest, pydantic, PyYAML,
#   pyarrow via limit_pullback.warehouse.parquet).
# - Dependencies are baked at image build time; the runtime exec has no
#   network (workspace conftest also blocks sockets inside pytest).
# - The whole image is pinned linux/amd64 to match the computerd
#   binary and run under Rosetta emulation.

FROM --platform=linux/amd64 ghcr.io/cloudflare/computer-computerd-linux-x64:0.1.1 AS computerd

FROM --platform=linux/amd64 python:3.12-slim

COPY --from=computerd /usr/local/bin/computerd /usr/local/bin/computerd

RUN pip install --no-cache-dir \
    "pytest>=8.3,<9" \
    "pydantic>=2.10,<3" \
    "PyYAML>=6.0,<7" \
    "pyarrow>=17,<21"

ENTRYPOINT ["/usr/local/bin/computerd"]
