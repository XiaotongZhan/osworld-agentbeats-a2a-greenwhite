#!/usr/bin/env bash
set -euo pipefail

# Change to project root (the directory containing this script's parent)
cd "$(dirname "$0")/.." || exit 1

# ========= 1. Load environment (conda env, OSWorld config, etc.) =========
# Reuse whatever setup_env.sh already does for green.
if [ -f "scripts/setup_env.sh" ]; then
  # shellcheck source=/dev/null
  source scripts/setup_env.sh
fi

# ========= 2. Controller host & port configuration =========
# The controller listens on HOST:PORT on this VM.
# You can override these via environment variables if needed.
CTRL_HOST="${GREEN_CTRL_HOST:-0.0.0.0}"
CTRL_PORT="${GREEN_CTRL_PORT:-20080}"

# This is the *public* host:port that AgentBeats Studio / external callers use.
# IMPORTANT: No "http://" prefix here. The controller will prepend it.
# Default is your current IP:port.
PUBLIC_HOST_PORT="${GREEN_CTRL_PUBLIC_HOST:-107.21.71.139:20080}"

# The controller expects CLOUDRUN_HOST to be "<host>:<port>"
export CLOUDRUN_HOST="${PUBLIC_HOST_PORT}"

# ========= 3. Log & PID configuration =========
LOG_DIR="logs/controller"
mkdir -p "${LOG_DIR}"

TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/controller_${TS}.out"
LATEST_LINK="${LOG_DIR}/controller.latest.out"
PID_FILE="${LOG_DIR}/controller.pid"

# ========= 4. If port is busy, try to stop previous controller =========
if lsof -iTCP:"${CTRL_PORT}" -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  echo "[info] Port ${CTRL_PORT} is already in use. Trying to stop existing controller..."

  if [ -f "${PID_FILE}" ]; then
    OLD_PID="$(cat "${PID_FILE}" || true)"
    if [ -n "${OLD_PID:-}" ] && kill -0 "${OLD_PID}" 2>/dev/null; then
      echo "[info] Stopping previous controller (pid=${OLD_PID})..."
      kill "${OLD_PID}" 2>/dev/null || true
      sleep 2
    else
      echo "[warn] PID file found but process not running (pid=${OLD_PID})."
    fi
  else
    echo "[warn] No PID file found for controller, but port is busy."
  fi
fi

# ========= 5. Start controller in background with nohup =========
echo "[info] Starting AgentBeats controller on ${CTRL_HOST}:${CTRL_PORT} (CLOUDRUN_HOST=${CLOUDRUN_HOST})"

# We explicitly set HOST/PORT for the controller process.
# NOTE: do NOT run in the foreground here; we want background + logs.
nohup env HOST="${CTRL_HOST}" PORT="${CTRL_PORT}" CLOUDRUN_HOST="${CLOUDRUN_HOST}" \
  agentbeats run_ctrl \
  > "${LOG_FILE}" 2>&1 &

CTRL_PID=$!
echo "${CTRL_PID}" > "${PID_FILE}"

# Maintain a 'latest' symlink for quick tailing
ln -sf "$(basename "${LOG_FILE}")" "${LATEST_LINK}" 2>/dev/null || true

echo "[info] controller pid=${CTRL_PID}, logs=${LOG_FILE}"

# ========= 6. Health check: wait for /status =========
STATUS_URL="http://127.0.0.1:${CTRL_PORT}/status"
tries=0
max_tries=30

echo "[info] Waiting for controller /status at ${STATUS_URL} ..."

until curl -fsS "${STATUS_URL}" >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "${tries}" -ge "${max_tries}" ]; then
    echo "[FATAL] Controller failed /status within ${max_tries}s. Tail of logs:"
    echo "------------------------------------------------------------"
    tail -n 120 "${LOG_FILE}" || true
    echo "------------------------------------------------------------"
    exit 3
  fi
  sleep 1
done

echo "[ok] AgentBeats controller is up at ${CTRL_HOST}:${CTRL_PORT}"
echo "[ok] Logs: ${LOG_FILE} (latest -> ${LATEST_LINK})"
echo "[ok] PID:  $(cat "${PID_FILE}")"