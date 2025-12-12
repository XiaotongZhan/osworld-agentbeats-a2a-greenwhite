#!/usr/bin/env bash
set -euo pipefail

# Change to project root (current file: green_ctrl/run.sh)
cd "$(dirname "$0")/.." || exit 1

# Load environment (conda + .env)
if [ -f "scripts/setup_env.sh" ]; then
  # shellcheck source=/dev/null
  source scripts/setup_env.sh
fi

# Bind address and port
# AgentBeats controller typically injects:
#   - AGENT_PORT: port assigned to this green instance
#   - HOST: usually 0.0.0.0
PORT="${AGENT_PORT:-18080}"
HOST="${HOST:-0.0.0.0}"

# Safety check: OSWorld HTTP endpoint must not be used
if env | grep -q '^OSWORLD_VM_BASE_URL='; then
  echo "[FATAL] OSWORLD_VM_BASE_URL is set. Unset it (HTTP control is not supported) and retry."
  exit 2
fi

# Ensure OSWorld can be imported
export PYTHONPATH="$(pwd)/third_party/osworld:${PYTHONPATH:-}"

# Dedicated logs for AgentBeats-managed green instances
LOG_DIR="logs/green_agentbeats"
mkdir -p "${LOG_DIR}"

AGENT_ID="${AGENT_ID:-unknown}"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/green_ab_${AGENT_ID}_${TS}.out"
LATEST_LINK="${LOG_DIR}/green_ab.latest.out"

echo "[info] Starting green (A2A) on ${HOST}:${PORT}"
echo "[info] Logging to ${LOG_FILE}"

ln -sf "$(basename "${LOG_FILE}")" "${LATEST_LINK}" 2>/dev/null || true

# Run uvicorn in the foreground and mirror output to both stdout and log file
# Do not background this process; the controller manages its lifecycle.
# uvicorn green.app:app --host "${HOST}" --port "${PORT}" --workers 1 \
#   2>&1 | tee -a "${LOG_FILE}"
uvicorn green.a2a_app:app --host "${HOST}" --port "${PORT}" --workers 1 \
  2>&1 | tee -a "${LOG_FILE}"