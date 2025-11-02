#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1
PORT="${GREEN_AGENT_PORT:-18080}"
LOG_DIR="logs/green"

if [ -f "$LOG_DIR/green.pid" ]; then
  PID="$(cat "$LOG_DIR/green.pid" || true)"
  [ -n "${PID:-}" ] && ps -p "$PID" >/dev/null 2>&1 && kill "$PID" || true
  rm -f "$LOG_DIR/green.pid"
fi

pids=$(lsof -tn -iTCP:"$PORT" -sTCP:LISTEN || true)
[ -n "${pids:-}" ] && kill -9 $pids || true

# fallback by port
if lsof -iTCP:"$PORT" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  PID2="$(lsof -t -iTCP:"$PORT" -sTCP:LISTEN -Pn | head -n1 || true)"
  [ -n "${PID2:-}" ] && kill "$PID2" || true
fi
echo "[ok] green stopped (if it was running)"
