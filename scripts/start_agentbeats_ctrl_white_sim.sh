#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

if [ -f "scripts/setup_env.sh" ]; then
  # shellcheck source=/dev/null
  source scripts/setup_env.sh
fi

CTRL_HOST="${WHITE_SIM_CTRL_HOST:-0.0.0.0}"
CTRL_PORT="${WHITE_SIM_CTRL_PORT:-20082}"
CLOUDRUN_HOST="${CLOUDRUN_HOST:-}"

LOG_DIR="logs/controller_white_sim"
mkdir -p "${LOG_DIR}"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/controller_${TS}.out"
LATEST_LINK="${LOG_DIR}/controller.latest.out"
PID_FILE="${LOG_DIR}/controller.pid"

if [ -f "${PID_FILE}" ]; then
  old_pid="$(cat "${PID_FILE}" || true)"
  if [ -n "${old_pid}" ] && kill -0 "${old_pid}" 2>/dev/null; then
    echo "[warn] WHITE_SIM controller already running (pid=${old_pid})."
    echo "[info] Logs: ${LATEST_LINK}"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

if [ ! -d "white_sim_ctrl" ]; then
  echo "[FATAL] white_sim_ctrl directory not found. Expected white_sim_ctrl/run.sh."
  exit 1
fi

echo "[info] Starting AgentBeats WHITE_SIM controller on ${CTRL_HOST}:${CTRL_PORT} (CLOUDRUN_HOST=${CLOUDRUN_HOST})"

(
  cd white_sim_ctrl
  nohup env HOST="${CTRL_HOST}" PORT="${CTRL_PORT}" CLOUDRUN_HOST="${CLOUDRUN_HOST}" \
    agentbeats run_ctrl \
    > "../${LOG_FILE}" 2>&1 &
  echo $! > "../${PID_FILE}"
)

ln -sf "$(basename "${LOG_FILE}")" "${LATEST_LINK}" 2>/dev/null || true

CTRL_PID="$(cat "${PID_FILE}" || true)"
echo "[info] WHITE_SIM controller pid=${CTRL_PID}, logs=${LOG_FILE}"

STATUS_URL="http://127.0.0.1:${CTRL_PORT}/status"
tries=0
max_tries=30

echo "[info] Waiting for WHITE_SIM controller at ${STATUS_URL} ..."

until curl -fsS "${STATUS_URL}" >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "${tries}" -ge "${max_tries}" ]; then
    echo "[FATAL] WHITE_SIM controller did not pass /status check within ${max_tries}s. Recent logs:"
    echo "------------------------------------------------------------"
    tail -n 120 "${LOG_FILE}" || true
    echo "------------------------------------------------------------"
    exit 3
  fi
  sleep 1
done

echo "[ok] WHITE_SIM controller is running at ${CTRL_HOST}:${CTRL_PORT}"
echo "[ok] Logs: ${LOG_FILE} (latest -> ${LATEST_LINK})"
echo "[ok] PID : ${CTRL_PID}"
