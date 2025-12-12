#!/usr/bin/env bash
set -euo pipefail

# Change to project root
cd "$(dirname "$0")/.." || exit 1

# Load environment (conda + .env)
if [ -f "scripts/setup_env.sh" ]; then
  # shellcheck source=/dev/null
  source scripts/setup_env.sh
fi

# Controller bind address and port
CTRL_HOST="${WHITE_CTRL_HOST:-0.0.0.0}"
CTRL_PORT="${WHITE_CTRL_PORT:-20081}"

# Public endpoint exposed to AgentBeats Studio (host:port only)
PUBLIC_HOST_PORT="${WHITE_CTRL_PUBLIC_HOST:-107.21.71.139:20081}"
export CLOUDRUN_HOST="${PUBLIC_HOST_PORT}"

# Logging and PID files
LOG_DIR="logs/controller_white"
mkdir -p "${LOG_DIR}"

TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/controller_${TS}.out"
LATEST_LINK="${LOG_DIR}/controller.latest.out"
PID_FILE="${LOG_DIR}/controller.pid"

# If the port is already in use, attempt to stop an existing controller instance
if lsof -iTCP:"${CTRL_PORT}" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  echo "[info] Port ${CTRL_PORT} is in use. Attempting to terminate existing WHITE controller..."

  if [ -f "${PID_FILE}" ]; then
    OLD_PID="$(cat "${PID_FILE}" || true)"
    if [ -n "${OLD_PID:-}" ] && kill -0 "${OLD_PID}" 2>/dev/null; then
      echo "[info] Stopping previous WHITE controller (pid=${OLD_PID})..."
      kill "${OLD_PID}" 2>/dev/null || true
      sleep 2
    else
      echo "[warn] PID file exists but corresponding process is not running (pid=${OLD_PID})."
    fi
  else
    echo "[warn] Port busy but no PID file found."
  fi
fi

# Start controller in the background (working directory: white_ctrl/)
echo "[info] Starting AgentBeats WHITE controller on ${CTRL_HOST}:${CTRL_PORT} (CLOUDRUN_HOST=${CLOUDRUN_HOST})"

if [ ! -d "white_ctrl" ]; then
  echo "[FATAL] white_ctrl directory not found. Expected white_ctrl/run.sh."
  exit 1
fi

(
  cd white_ctrl
  nohup env HOST="${CTRL_HOST}" PORT="${CTRL_PORT}" CLOUDRUN_HOST="${CLOUDRUN_HOST}" \
    agentbeats run_ctrl \
    > "../${LOG_FILE}" 2>&1 &
  echo $! > "../${PID_FILE}"
)

ln -sf "$(basename "${LOG_FILE}")" "${LATEST_LINK}" 2>/dev/null || true

CTRL_PID="$(cat "${PID_FILE}" || true)"
echo "[info] WHITE controller pid=${CTRL_PID}, logs=${LOG_FILE}"

# Health check for /status
STATUS_URL="http://127.0.0.1:${CTRL_PORT}/status"
tries=0
max_tries=30

echo "[info] Waiting for WHITE controller at ${STATUS_URL} ..."

until curl -fsS "${STATUS_URL}" >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "${tries}" -ge "${max_tries}" ]; then
    echo "[FATAL] WHITE controller did not pass /status check within ${max_tries}s. Recent logs:"
    echo "------------------------------------------------------------"
    tail -n 120 "${LOG_FILE}" || true
    echo "------------------------------------------------------------"
    exit 3
  fi
  sleep 1
done

echo "[ok] WHITE controller is running at ${CTRL_HOST}:${CTRL_PORT}"
echo "[ok] Logs: ${LOG_FILE} (latest -> ${LATEST_LINK})"
echo "[ok] PID : ${CTRL_PID}"