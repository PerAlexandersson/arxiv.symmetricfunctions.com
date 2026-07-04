#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v node >/dev/null 2>&1; then
  echo "node not found; skipping JavaScript syntax check"
  exit 0
fi

find "$ROOT_DIR/src/static" -maxdepth 1 -type f -name '*.js' -print0 \
  | sort -z \
  | xargs -0 -r -n 1 node --check
