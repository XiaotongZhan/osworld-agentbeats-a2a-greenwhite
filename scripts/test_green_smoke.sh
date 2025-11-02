#!/usr/bin/env bash
# Exit on error, undefined var, or failed piped command
set -euo pipefail
IFS=$'\n\t'

# ========== Paths ==========
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OSWORLD_DIR="$REPO_ROOT/third_party/osworld"

# ========== Activate conda env ==========
if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate cs294
else
  echo "[error] conda not found"
  exit 1
fi

# ========== Load .env (safe export of key=value lines) ==========
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$REPO_ROOT/.env"
  set +a
fi

# ========== Ensure output dirs exist ==========
mkdir -p "$REPO_ROOT/logs" "$REPO_ROOT/results/smoke"

# ========== Diagnostics ==========
echo "[info] Python      = $(command -v python)"
echo "[info] AWS_REGION  = ${AWS_REGION:-<unset>}"
echo "[info] OSWORLD_API_BACKEND = ${OSWORLD_API_BACKEND:-dashscope}"

# Helper to mask secrets
mask() {
  local v="${1:-}"
  if [ -n "$v" ]; then printf "%s********" "${v:0:8}"; else printf "<unset>"; fi
}

# ========== Backend & model selection ==========
API_BACKEND="${OSWORLD_API_BACKEND:-dashscope}"

if [ "$API_BACKEND" = "dashscope" ]; then
  : "${DASHSCOPE_API_KEY:?DASHSCOPE_API_KEY is required for DashScope backend}"
  MODEL="${OSWORLD_VL_MODEL:-qwen3-vl-235b-a22b-instruct}"
  echo "[info] DASHSCOPE_API_KEY = $(mask "$DASHSCOPE_API_KEY")"
  echo "[info] OSWORLD_VL_MODEL  = $MODEL"
  export DASHSCOPE_API_KEY MODEL
  unset OPENAI_BASE_URL || true
  unset OPENAI_API_KEY || true
else
  : "${OPENAI_BASE_URL:?OPENAI_BASE_URL is required for openai-compatible backend}"
  : "${OPENAI_API_KEY:?OPENAI_API_KEY is required for openai-compatible backend}"
  MODEL="${OSWORLD_VL_MODEL:-qwen/qwen2.5-vl-32b-instruct:free}"
  echo "[info] OPENAI_BASE_URL   = $OPENAI_BASE_URL"
  echo "[info] OPENAI_API_KEY    = $(mask "$OPENAI_API_KEY")"
  echo "[info] OSWORLD_VL_MODEL  = $MODEL"
  export OPENAI_BASE_URL OPENAI_API_KEY MODEL
fi

# ========== Build a single-task meta for libreoffice_writer ==========
EX_DIR="$OSWORLD_DIR/evaluation_examples/examples/libreoffice_writer"
if [ ! -d "$EX_DIR" ]; then
  echo "[error] example dir not found: $EX_DIR"
  exit 1
fi

# Prefer a deterministic first JSON if possible; fall back to any match
shopt -s nullglob
json_candidates=("$EX_DIR"/*.json)
shopt -u nullglob
if [ ${#json_candidates[@]} -eq 0 ]; then
  echo "[error] no json found in: $EX_DIR"
  exit 1
fi
FIRST_JSON_PATH="${json_candidates[0]}"
FIRST_ID="$(basename "$FIRST_JSON_PATH" .json)"

META_PATH="$REPO_ROOT/osworld_meta_single.json"
cat > "$META_PATH" <<EOF
{
  "libreoffice_writer": [
    "$FIRST_ID"
  ]
}
EOF
echo "[info] Use FIRST_JSON=$FIRST_JSON_PATH"
echo "WROTE $META_PATH"

# ========== Run OSWorld ==========
echo
echo "▶️  Running: python $OSWORLD_DIR/run_multienv_qwen25vl.py ..."
(
  cd "$OSWORLD_DIR" && \
  python "$OSWORLD_DIR/run_multienv_qwen25vl.py" \
    --headless \
    --observation_type screenshot \
    --model "$MODEL" \
    --result_dir "$REPO_ROOT/results/smoke" \
    --max_steps 10 \
    --num_envs 1 \
    --provider_name aws \
    --region "${AWS_REGION:-us-east-1}" \
    --test_all_meta_path "$META_PATH" \
    --domain libreoffice_writer \
    --screen_width 1920 --screen_height 1080
)

echo
echo "✅ Smoke done. Results at: $REPO_ROOT/results/smoke"