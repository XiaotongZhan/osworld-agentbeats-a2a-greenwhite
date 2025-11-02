#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1
PORT="${WHITE_PORT:-18081}"
LOG_DIR="logs/white"

if [ -f "$LOG_DIR/white.pid" ]; then
  PID="$(cat "$LOG_DIR/white.pid" || true)"
  [ -n "${PID:-}" ] && ps -p "$PID" >/dev/null 2>&1 && kill "$PID" || true
  rm -f "$LOG_DIR/white.pid"
fi

pids=$(lsof -tn -iTCP:"$PORT" -sTCP:LISTEN || true)
[ -n "${pids:-}" ] && kill -9 $pids || true

echo "[ok] white_sim stopped (if it was running)"