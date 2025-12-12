#!/usr/bin/env bash
set -euo pipefail

# Change to project root
cd "$(dirname "$0")/.." || exit 1

LOG_DIR="logs/controller_white"
PID_FILE="${LOG_DIR}/controller.pid"

if [ ! -f "${PID_FILE}" ]; then
  echo "[info] No WHITE controller PID file found at ${PID_FILE}. Nothing to stop."
  exit 0
fi

CTRL_PID="$(cat "${PID_FILE}" || true)"

if [ -z "${CTRL_PID}" ]; then
  echo "[warn] PID file exists but is empty. Removing it."
  rm -f "${PID_FILE}"
  exit 0
fi

if kill -0 "${CTRL_PID}" 2>/dev/null; then
  echo "[info] Stopping AgentBeats WHITE controller (pid=${CTRL_PID})..."
  kill "${CTRL_PID}" 2>/dev/null || true
  sleep 2

  if kill -0 "${CTRL_PID}" 2>/dev/null; then
    echo "[warn] WHITE controller still running, sending SIGKILL..."
    kill -9 "${CTRL_PID}" 2>/dev/null || true
  fi
else
  echo "[info] Process with pid=${CTRL_PID} is not running."
fi

rm -f "${PID_FILE}"
echo "[ok] WHITE controller stopped and PID file removed."