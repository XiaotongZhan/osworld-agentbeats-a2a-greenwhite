#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

# Load env (tokens, host/port, region, etc.)
source scripts/setup_env.sh

MODE="${1:-small}"           # small|domain|single|random|indices
ARG2="${2:-}"                # domain | domain/example_id | k | indices (CSV)
HOST="${GREEN_AGENT_HOST:-127.0.0.1}"
PORT="${GREEN_AGENT_PORT:-18080}"
REGION="${AWS_REGION:-us-east-1}"
SCREEN="${SCREEN_SIZE:-1920x1080}"     # allow override via env
SLICE="${GREEN_TASKSET:-test_small}"   # test_small|test_all|verified_small|verified_all|nodrive|<file.json>

# Filters (can be driven by env)
NOGDRIVE_FLAG=""
if [[ "${GREEN_ENFORCE_NOGDRIVE:-false}" == "true" ]]; then
  NOGDRIVE_FLAG="--nogdrive"
fi
NOPROXY_FLAG=""
if [[ "${GREEN_SKIP_PROXY:-false}" == "true" ]]; then
  NOPROXY_FLAG="--no-proxy"
fi

# Auth shaping
TOKEN="${GREEN_AUTH_TOKEN:-}"
USE_PATH_TOKEN="${GREEN_USE_PATH_TOKEN:-false}"

PY="python"
CMD=( "$PY" "run_modes/runner.py"
      --mode "$MODE"
      --slice "$SLICE"
      --host "$HOST"
      --port "$PORT"
      --region "$REGION"
      --screen "$SCREEN"
      $NOGDRIVE_FLAG
      $NOPROXY_FLAG
)

case "$MODE" in
  small)
    ;;
  domain)
    if [[ -z "$ARG2" ]]; then
      echo "[FATAL] usage: run_slice.sh domain <domain_name>"; exit 2
    fi
    CMD+=( --domain "$ARG2" )
    ;;
  single)
    if [[ -z "$ARG2" ]]; then
      echo "[FATAL] usage: run_slice.sh single <domain/example_id>"; exit 2
    fi
    CMD+=( --example "$ARG2" )
    ;;
  random)
    K="${ARG2:-10}"
    CMD+=( --k "$K" )
    ;;
  indices)
    if [[ -z "$ARG2" ]]; then
      echo "[FATAL] usage: run_slice.sh indices <comma_separated_indices>"; exit 2
    fi
    CMD+=( --indices "$ARG2" )
    ;;
  *)
    echo "[FATAL] unknown mode: $MODE"; exit 2;;
esac

# Auth options
if [[ -n "$TOKEN" ]]; then
  CMD+=( --token "$TOKEN" )
fi
if [[ "$USE_PATH_TOKEN" == "true" ]]; then
  CMD+=( --use-path-token )
fi

echo "[info] run: ${CMD[*]}"
exec "${CMD[@]}"