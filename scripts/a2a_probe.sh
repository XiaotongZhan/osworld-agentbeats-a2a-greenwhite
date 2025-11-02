#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

source scripts/setup_env.sh

K="${1:-5}"
HOST="${GREEN_AGENT_HOST:-127.0.0.1}"
PORT="${GREEN_AGENT_PORT:-18080}"
SLICE="${GREEN_TASKSET:-test_nodrive}"

EXTRA=()
if [ -n "${GREEN_AUTH_TOKEN:-}" ]; then
  if [ "${GREEN_USE_PATH_TOKEN:-false}" = "true" ]; then
    EXTRA+=(--use-path-token --token "$GREEN_AUTH_TOKEN")
  else
    EXTRA+=(--token "$GREEN_AUTH_TOKEN")
  fi
fi

echo "[info] probe: host=$HOST port=$PORT slice=$SLICE k=$K"
python tools/a2a_probe.py \
  --host "$HOST" --port "$PORT" --k "$K" --slice "$SLICE" \
  "${EXTRA[@]}"