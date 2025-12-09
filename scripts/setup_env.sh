#!/bin/bash
# =========================================================
# Activate the cs294 env and load .env/.env.local (idempotent)
# Usage: source scripts/setup_env.sh
# =========================================================
set -e

# ---------- move to repo root, robust for 'source' ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# ---------- 1) Conda hook ----------
if command -v conda >/dev/null 2>&1; then
  __conda_setup="$('conda' 'shell.bash' 'hook' 2>/dev/null)" || true
  if [ -n "$__conda_setup" ]; then
    eval "$__conda_setup"
  fi
fi

# Fallback
if ! command -v conda >/dev/null 2>&1 || [ -z "${CONDA_EXE:-}" ]; then
  for CAND in \
    "$HOME/miniconda3/etc/profile.d/conda.sh" \
    "$HOME/anaconda3/etc/profile.d/conda.sh" \
    "/opt/conda/etc/profile.d/conda.sh"
  do
    if [ -f "$CAND" ]; then
      # shellcheck source=/dev/null
      . "$CAND"
      break
    fi
  done
fi

# ---------- 2) Activate env ----------
ENV_NAME="${VENV_NAME:-cs294}"
if command -v conda >/dev/null 2>&1; then
  conda activate "$ENV_NAME"
elif [ -d "./$ENV_NAME/bin" ]; then
  # shellcheck source=/dev/null
  source "./$ENV_NAME/bin/activate"
else
  echo "Cannot activate environment '$ENV_NAME'." >&2
  exit 1
fi

echo "Active env: ${CONDA_DEFAULT_ENV:-$(basename "${VIRTUAL_ENV:-}" 2>/dev/null)}"
python -V || true
which python || true

# ---------- 3) Load .env + .env.local ----------
load_env_file () {
  local f="$1"
  [ -f "$f" ] || return 0
  set -a
  # shellcheck source=/dev/null
  . "$f"
  set +a
  echo "Loaded environment variables from $(basename "$f")"
}

load_env_file ".env"
load_env_file ".env.local"

# ---------- 4) Key signals (masked) ----------
mask() { local v="$1"; [ -n "$v" ] && printf "%s********\n" "${v:0:8}" || printf "<unset>\n"; }

echo "AWS_REGION=${AWS_REGION:-<unset>}"
# echo -n "OPENAI_API_KEY=";       mask "${OPENAI_API_KEY:-}"
# echo -n "ANTHROPIC_API_KEY=";    mask "${ANTHROPIC_API_KEY:-}"
# echo -n "DASHSCOPE_API_KEY=";    mask "${DASHSCOPE_API_KEY:-}"
# echo -n "AZURE_OPENAI_API_KEY="; mask "${AZURE_OPENAI_API_KEY:-}"
echo "Environment setup complete!"

# ========= 2.5 OSWorld AMI preflight check =========
if [ "${GREEN_CHECK_AMI:-true}" != "false" ]; then
  bash scripts/check_osworld_ami.sh
fi