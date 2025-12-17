#!/usr/bin/env bash
set -euo pipefail

# project root
cd "$(dirname "$0")/.." || exit 1

# Load environment (conda + .env)
if [ -f "scripts/setup_env.sh" ]; then
  # shellcheck source=/dev/null
  source scripts/setup_env.sh
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-18082}"

echo "[info] starting white_sim (A2A) on ${HOST}:${PORT}"
exec uvicorn white_sim.server:app --host "${HOST}" --port "${PORT}" --workers 1
