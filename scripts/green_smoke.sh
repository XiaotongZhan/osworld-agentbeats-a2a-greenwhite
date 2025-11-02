#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

source scripts/setup_env.sh

HOST="${GREEN_AGENT_HOST:-127.0.0.1}"
PORT="${GREEN_AGENT_PORT:-18080}"
REGION="${AWS_REGION:-us-east-1}"

REQ_DIR="results/requests"
RESP_DIR="results/responses"
RUN_BASE="results/green_runs"
mkdir -p "$REQ_DIR" "$RESP_DIR" "$RUN_BASE"

TS="$(date +%Y%m%d_%H%M%S)"
REQ_PATH="$REQ_DIR/act_${TS}.json"
RESP_PATH="$RESP_DIR/resp_${TS}.json"

# Build a valid /act body using an official OSWorld example JSON,
# while strictly avoiding any example that requires Google Drive.
python - "$REGION" "$REQ_PATH" <<'PY'
import json, os, sys, os.path as p, random

region, out = sys.argv[1], sys.argv[2]
root = "third_party/osworld/evaluation_examples"

meta_order = ("test_nodrive.json", "test_small.json", "test_all.json")

def load_meta():
    for name in meta_order:
        mp = p.join(root, name)
        if p.exists(mp):
            with open(mp, "r", encoding="utf-8") as f:
                return json.load(f), name
    raise SystemExit("No meta json found under evaluation_examples")

def requires_gdrive(cfg, domain):
    dl = str(domain).lower()
    if dl in {"googledrive", "google_drive", "google-drive"}:
        return True
    for step in cfg.get("config", []) or []:
        t = str(step.get("type", "")).lower()
        if "googledrive" in t or t == "gdrive":
            return True
        params = step.get("parameters", {})
        def hit(v):
            if isinstance(v, str):
                s = v.lower()
                return ("drive.google.com" in s) or ("docs.google.com/drive" in s)
            if isinstance(v, (list, tuple)):
                return any(hit(x) for x in v)
            if isinstance(v, dict):
                return any(hit(x) for x in v.values())
            return False
        if hit(params):
            return True
    return False

meta, meta_name = load_meta()
pairs = [(d, e) for d, arr in meta.items() for e in arr]
if not pairs:
    raise SystemExit(f"Meta {meta_name} contains no examples")

candidates = []
for domain, ex in pairs:
    ex_path = p.join(root, "examples", domain, f"{ex}.json")
    try:
        with open(ex_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        continue
    if requires_gdrive(cfg, domain):
        continue
    candidates.append((domain, ex, cfg))

if not candidates:
    raise SystemExit("No non-Google-Drive examples available. Consider using test_nodrive.json.")

domain, ex, cfg = random.choice(candidates)

body = {
  "task_id": f"smoke_{domain}_{ex}",
  "instruction": cfg.get("instruction", "Follow the instruction."),
  "limits": {"max_steps": 12, "max_seconds": 120},
  "osworld": {
    "provider_name": "aws",
    "os_type": "Ubuntu",
    "region": region,
    "task_config": cfg
  }
}

os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(body, f, ensure_ascii=False, indent=2)

print(f"[py] built example from {meta_name}: {domain}/{ex}")
PY

# Build auth header if token present
AUTH_HEADER=()
if [ -n "${GREEN_AUTH_TOKEN:-}" ]; then
  AUTH_HEADER+=(-H "X-Auth-Token: ${GREEN_AUTH_TOKEN}")
fi

echo "[info] POST /act to http://${HOST}:${PORT} ..."
set +e
HTTP_CODE=$(
  curl -sS -w "%{http_code}" -o "$RESP_PATH" -H "Content-Type: application/json" \
       "${AUTH_HEADER[@]}" \
       -X POST "http://${HOST}:${PORT}/act" \
       --data-binary @"$REQ_PATH"
)
CURL_STATUS=$?
set -e

if [ "$CURL_STATUS" -ne 0 ]; then
  echo "[FATAL] curl failed (status=$CURL_STATUS). See $RESP_PATH and green logs."
  exit 3
fi

if [ "$HTTP_CODE" = "401" ]; then
  echo "[FATAL] 401 Unauthorized."
  echo "       • Check that GREEN_AUTH_TOKEN is set in .env and loaded by start_green.sh."
  echo "       • Quick test: curl -i -H 'X-Auth-Token: ${GREEN_AUTH_TOKEN:-<unset>}' http://${HOST}:${PORT}/health"
  exit 4
fi

if command -v jq >/dev/null 2>&1; then
  cat "$RESP_PATH" | jq .
else
  cat "$RESP_PATH"
fi

# Extract logs_dir and mirror 'latest' symlink under results/green_runs
if command -v jq >/dev/null 2>&1; then
  RUN_DIR="$(jq -r '.logs_dir // empty' < "$RESP_PATH")"
  if [ -n "${RUN_DIR:-}" ] && [ -d "$RUN_DIR" ]; then
    ln -sfn "$RUN_DIR" "$RUN_BASE/latest"
    echo "[ok] run artifacts at: $RUN_DIR"
    echo "[ok] latest -> $RUN_DIR"
  else
    echo "[warn] no logs_dir field or directory missing"
  fi
fi

echo "[ok] smoke done. request: $REQ_PATH  response: $RESP_PATH"
