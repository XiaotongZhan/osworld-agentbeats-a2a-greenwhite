#!/usr/bin/env bash
set -euo pipefail

# Change to project root
cd "$(dirname "$0")/.." || exit 1

# Load environment (conda env, .env, etc.)
if [ -f "scripts/setup_env.sh" ]; then
  # shellcheck source=/dev/null
  source scripts/setup_env.sh
fi

# Controller bind address and port
CTRL_HOST="${GREEN_CTRL_HOST:-0.0.0.0}"
CTRL_PORT="${GREEN_CTRL_PORT:-20080}"

# Public endpoint for AgentBeats Studio (host:port, without http://)
PUBLIC_HOST_PORT="${GREEN_CTRL_PUBLIC_HOST:-107.21.71.139:20080}"

# CLOUDRUN_HOST must be of the form "<host>:<port>"
export CLOUDRUN_HOST="${PUBLIC_HOST_PORT}"

# Logging and PID files
LOG_DIR="logs/controller_green"
mkdir -p "${LOG_DIR}"

TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/controller_${TS}.out"
LATEST_LINK="${LOG_DIR}/controller.latest.out"
PID_FILE="${LOG_DIR}/controller.pid"

# If the port is already in use, attempt to stop the previous controller
if lsof -iTCP:"${CTRL_PORT}" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  echo "[info] Port ${CTRL_PORT} is already in use. Trying to stop existing GREEN controller..."

  if [ -f "${PID_FILE}" ]; then
    OLD_PID="$(cat "${PID_FILE}" || true)"
    if [ -n "${OLD_PID:-}" ] && kill -0 "${OLD_PID}" 2>/dev/null; then
      echo "[info] Stopping previous GREEN controller (pid=${OLD_PID})..."
      kill "${OLD_PID}" 2>/dev/null || true
      sleep 2
    else
      echo "[warn] PID file found but process not running (pid=${OLD_PID})."
    fi
  else
    echo "[warn] No PID file found for GREEN controller, but port is busy."
  fi
fi

# Start green controller in the background (working directory: green_ctrl/)
echo "[info] Starting AgentBeats GREEN controller on ${CTRL_HOST}:${CTRL_PORT} (CLOUDRUN_HOST=${CLOUDRUN_HOST})"

if [ ! -d "green_ctrl" ]; then
  echo "[FATAL] green_ctrl directory not found. Expected green_ctrl/run.sh to exist."
  exit 1
fi

(
  cd green_ctrl
  nohup env HOST="${CTRL_HOST}" PORT="${CTRL_PORT}" CLOUDRUN_HOST="${CLOUDRUN_HOST}" \
    agentbeats run_ctrl \
    > "../${LOG_FILE}" 2>&1 &
  echo $! > "../${PID_FILE}"
)

CTRL_PID="$(cat "${PID_FILE}" || true)"

# Maintain latest symlink for convenient tailing
ln -sf "$(basename "${LOG_FILE}")" "${LATEST_LINK}" 2>/dev/null || true

echo "[info] GREEN controller pid=${CTRL_PID}, logs=${LOG_FILE}"

# Health check: wait for /status
STATUS_URL="http://127.0.0.1:${CTRL_PORT}/status"
tries=0
max_tries=30

echo "[info] Waiting for GREEN controller /status at ${STATUS_URL} ..."

until curl -fsS "${STATUS_URL}" >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "${tries}" -ge "${max_tries}" ]; then
    echo "[FATAL] GREEN controller failed /status within ${max_tries}s. Tail of logs:"
    echo "------------------------------------------------------------"
    tail -n 120 "${LOG_FILE}" || true
    echo "------------------------------------------------------------"
    exit 3
  fi
  sleep 1
done

echo "[ok] AgentBeats GREEN controller is up at ${CTRL_HOST}:${CTRL_PORT}"
echo "[ok] Logs: ${LOG_FILE} (latest -> ${LATEST_LINK})"
echo "[ok] PID:  ${CTRL_PID}"