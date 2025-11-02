#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

# Load env & defaults
source scripts/setup_env.sh
PORT="${WHITE_PORT:-18081}"
LOG_DIR="logs/white"
mkdir -p "$LOG_DIR"

# Timestamped log filename (local time). Also create a 'latest' symlink.
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/white_${TS}.out"
LATEST_LINK="$LOG_DIR/white.latest.out"

# If port is busy, try to stop the previous white_sim
if lsof -iTCP:"$PORT" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  echo "[info] Port $PORT is busy. Stopping previous white_sim..."
  bash scripts/stop_white_sim.sh || true
  sleep 1
fi

echo "[info] starting white_sim on :$PORT"
nohup uvicorn white_sim.server:app --host 0.0.0.0 --port "$PORT" --workers 1 \
  > "$LOG_FILE" 2>&1 & echo $! > "logs/white/white.pid"

# Maintain a 'latest' symlink for quick tailing
ln -sf "$(basename "$LOG_FILE")" "$LATEST_LINK" 2>/dev/null || true

# Simple port check (white_sim may not expose /health)
sleep 1
if ! lsof -iTCP:"$PORT" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  echo "[FATAL] white_sim failed to bind :$PORT. See $LOG_FILE"
  tail -n 120 "$LOG_FILE" || true
  exit 3
fi

echo "[ok] white_sim is up at :$PORT (pid=$(cat "logs/white/white.pid"))"
echo "[ok] logs: $LOG_FILE (latest -> $LATEST_LINK)"