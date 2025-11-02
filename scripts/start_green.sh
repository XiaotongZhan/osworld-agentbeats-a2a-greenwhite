#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

# Load env & defaults
source scripts/setup_env.sh
PORT="${GREEN_AGENT_PORT:-18080}"
HOST="${GREEN_AGENT_HOST:-127.0.0.1}"
LOG_DIR="logs/green"
mkdir -p "$LOG_DIR"

# Timestamped log filename (local time). Also create a 'latest' symlink.
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/green_${TS}.out"
LATEST_LINK="$LOG_DIR/green.latest.out"

# Safety guard: we must NOT use OSWorld HTTP endpoint (we use Python API only).
if env | grep -q '^OSWORLD_VM_BASE_URL='; then
  echo "[FATAL] OSWORLD_VM_BASE_URL is set. Unset it (we do not use HTTP control) and retry."
  exit 2
fi

# If port is busy, try to stop the previous green instance
if lsof -iTCP:"$PORT" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  echo "[info] Port $PORT is busy. Trying to stop existing green..."
  bash scripts/stop_green.sh || true
  sleep 1
fi

# Ensure OSWorld package is importable (double insurance; also handled in code)
export PYTHONPATH="$(pwd)/third_party/osworld:${PYTHONPATH:-}"

echo "[info] starting green on :$PORT"
# Start service and write PID (PID file stays stable for stop script)
nohup uvicorn green.app:app --host 0.0.0.0 --port "$PORT" --workers 1 \
  > "$LOG_FILE" 2>&1 & echo $! > "logs/green/green.pid"

# Maintain a 'latest' symlink for quick tailing
ln -sf "$(basename "$LOG_FILE")" "$LATEST_LINK" 2>/dev/null || true

# Wait for /health
tries=0
until curl -fsS "http://${HOST}:${PORT}/health" >/dev/null 2>&1; do
  tries=$((tries+1))
  if [ "$tries" -ge 30 ]; then
    echo "[FATAL] green failed /health within 30s. Tail logs:"
    tail -n 120 "$LOG_FILE" || true
    exit 3
  fi
  sleep 1
done

echo "[ok] green is up at :$PORT (pid=$(cat "logs/green/green.pid"))"
echo "[ok] logs: $LOG_FILE (latest -> $LATEST_LINK)"