#!/usr/bin/env bash
set -euo pipefail

# ========= 0. Change to project root =========
# The parent directory of white_ctrl/ is the project root.
cd "$(dirname "$0")/.." || exit 1

# ========= 1. Load env / conda, etc. =========
source scripts/setup_env.sh

# ========= 2. Port & host =========
# The controller will inject AGENT_PORT; when running manually
# on local machine, default to 18082 (same as start_white_sim default).
PORT="${AGENT_PORT:-18082}"
HOST="${HOST:-0.0.0.0}"

# ========= 3. Log directory =========
LOG_DIR="logs/white_agentbeats"
mkdir -p "${LOG_DIR}"

AGENT_ID="${AGENT_ID:-unknown}"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/white_ab_${AGENT_ID}_${TS}.out"
LATEST_LINK="${LOG_DIR}/white_ab.latest.out"

echo "[info] starting white_sim (A2A) on ${HOST}:${PORT}"
echo "[info] logging to ${LOG_FILE}"

ln -sf "$(basename "${LOG_FILE}")" "${LATEST_LINK}" 2>/dev/null || true

# ========= 4. Start uvicorn in the foreground =========
# Do NOT use nohup / &; it must stay in the foreground
# so the controller can manage its lifecycle.
uvicorn white_sim.server:app --host "${HOST}" --port "${PORT}" --workers 1 \
  2>&1 | tee -a "${LOG_FILE}"