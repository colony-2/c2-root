#!/usr/bin/env bash
# Read-only configured catalog/CLI and documentation checks; no live JobDB needed.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export PYTHONDONTWRITEBYTECODE=1
exec python3 scripts/catalog.py "${1:-all}"
