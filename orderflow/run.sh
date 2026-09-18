#!/usr/bin/env bash
# OrderFlow Pro launcher — runs tests then starts the server.
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "test" ]]; then
  exec python3 -m unittest discover -s tests -v
fi

echo "Running tests…"
python3 -m unittest discover -s tests >/dev/null 2>&1 && echo "  tests OK" || echo "  tests skipped/failed"

PORT="${ORDERFLOW_PORT:-8787}"
echo "Starting OrderFlow Pro on http://localhost:${PORT}"
exec python3 server.py
