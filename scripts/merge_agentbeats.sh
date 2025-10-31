#!/usr/bin/env bash
set -euo pipefail

SRC="third_party/agentbeats/pyproject.toml"
TGT="pyproject.toml"

if [[ ! -f "$SRC" ]]; then
  echo "[error] Not found: $SRC" >&2; exit 2
fi
if [[ ! -f "$TGT" ]]; then
  echo "[error] Not found: $TGT" >&2; exit 3
fi

# 解析 agentbeats 依赖，计算需要新增的包（已存在的自动跳过）
PKGS="$(
python - <<'PY'
import sys, re
from pathlib import Path
try:
    import tomllib  # requires Python 3.11+
except Exception:
    print("", end=""); sys.exit(0)

def parse_list(lst):
    out={}
    for raw in lst or []:
        s=str(raw).strip()
        if not s: continue
        m=re.match(r"^([A-Za-z0-9_.\-]+)(.*)$", s)
        if not m: continue
        name=m.group(1).strip()
        spec=m.group(2).strip()
        key=name.lower().replace("_","-")
        out[key]=name+spec
    return out

src = tomllib.loads(Path("third_party/agentbeats/pyproject.toml").read_text())
tgt = tomllib.loads(Path("pyproject.toml").read_text())

src_deps = parse_list((src.get("project") or {}).get("dependencies", []))
tgt_deps = parse_list((tgt.get("project") or {}).get("dependencies", []))

to_add = [spec for k,spec in src_deps.items() if k not in tgt_deps]
print(" ".join(to_add), end="")
PY
)"

if [[ -z "${PKGS}" ]]; then
  echo "[info] No new dependencies to add."
else
  echo "[info] Adding: ${PKGS}"
  poetry add ${PKGS}
fi

# 写入后锁定（不强更）
poetry lock --no-update
echo "[done] agentbeats deps merged & locked."