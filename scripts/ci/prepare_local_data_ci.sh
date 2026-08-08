#!/usr/bin/env bash
# Read-only local data preparation for the Mac self-hosted data gate.
# Never copies / moves / rewrites source data; only validates and symlinks.
set -euo pipefail

if [ -z "${A_SHARE_DATA_ROOT:-}" ]; then
  echo "A_SHARE_DATA_ROOT is not set (required on self-hosted runner)" >&2
  exit 1
fi

if [ ! -d "$A_SHARE_DATA_ROOT" ]; then
  echo "A_SHARE_DATA_ROOT is not a directory: $A_SHARE_DATA_ROOT" >&2
  exit 1
fi

REQUIRED="$A_SHARE_DATA_ROOT/canonical/daily_bars/snap-2026-07-31-b5f84004de8a.parquet"
if [ ! -f "$REQUIRED" ]; then
  echo "required canonical artifact missing: $REQUIRED" >&2
  exit 1
fi

if [ -e "data" ] && [ ! -L "data" ]; then
  echo "workspace 'data' exists and is not a symlink; refusing to touch" >&2
  exit 1
fi

if [ ! -e "data" ]; then
  ln -s "$A_SHARE_DATA_ROOT" data
fi

echo "data -> $(readlink data) (read-only usage)"
