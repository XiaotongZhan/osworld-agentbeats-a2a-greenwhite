#!/usr/bin/env bash
set -euo pipefail

# ========= 0. Change to project root =========
cd "$(dirname "$0")" || exit 1

# ========= 1. Load existing environment and configuration =========
# Keep using whatever scripts/setup_env.sh does for the green agent,
# e.g. activating conda env, setting OSWORLD-related environment variables, etc.
source scripts/setup_env.sh

# ========= 2. Port & host configuration =========
# Use the environment variables injected by the AgentBeats controller:
#   - AGENT_PORT: port assigned to this agent instance
#   - HOST: usually 0.0.0.0 or 127.0.0.1
PORT="${AGENT_PORT:-18080}"
HOST="${HOST:-0.0.0.0}"

# ========= 3. Safety guard: do not use OSWorld HTTP endpoint =========
if env | grep -q '^OSWORLD_VM_BASE_URL='; then
  echo "[FATAL] OSWORLD_VM_BASE_URL is set. Unset it (we do not use HTTP control) and retry."
  exit 2
fi

# Ensure OSWorld package is importable
export PYTHONPATH="$(pwd)/third_party/osworld:${PYTHONPATH:-}"

# ========= 4. Local log directory for AgentBeats-launched green =========
# We keep this separate from the old logs/green used by scripts/start_green.sh
LOG_DIR="logs/green_agentbeats"
mkdir -p "$LOG_DIR"

# Optional: include AGENT_ID in filename if the controller ever sets it.
# If not set, we just fall back to "unknown".
AGENT_ID="${AGENT_ID:-unknown}"

TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/green_ab_${AGENT_ID}_${TS}.out"
LATEST_LINK="${LOG_DIR}/green_ab.latest.out"

echo "[info] starting green (A2A) on ${HOST}:${PORT}"
echo "[info] logging to ${LOG_FILE}"

# Maintain a 'latest' symlink for quick tailing
ln -sf "$(basename "${LOG_FILE}")" "${LATEST_LINK}" 2>/dev/null || true

# ========= 5. Start uvicorn in the foreground, but also tee output to file =========
# IMPORTANT:
#   - No 'nohup' and no '&' here. The process MUST stay in the foreground
#     so the controller can track it and kill it when needed.
#   - We use 'tee' so that:
#       * stdout/stderr still go to the controller (through tee's stdout)
#       * the same output is written to LOG_FILE locally.
#
# Because of 'set -euo pipefail', if uvicorn exits with a non-zero status,
# the whole script will also return a non-zero exit code, which is what we want.
uvicorn green.app:app --host "${HOST}" --port "${PORT}" --workers 1 \
  2>&1 | tee -a "${LOG_FILE}"