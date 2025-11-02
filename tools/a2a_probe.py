#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations
import argparse, json, os, random, re, sys, time
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import httpx

ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "third_party" / "osworld" / "evaluation_examples"

def _now() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime())

def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(s))[:120]

def _load_json(p: Path) -> Any:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def _load_meta(slice_name: str) -> Tuple[Dict[str, List[str]], str]:
    cands = []
    s = slice_name.lower()
    if s in {"small","test_small"}:
        cands = ["test_small.json","test_all.json","verified_small.json"]
    elif s in {"nodrive","test_nodrive"}:
        cands = ["test_nodrive.json","test_small.json","test_all.json"]
    else:
        cands = [s if s.endswith(".json") else f"{s}.json"]
    for name in cands:
        p = EVAL_ROOT / name
        if p.exists():
            return _load_json(p), name
    raise SystemExit(f"[FATAL] meta not found under {EVAL_ROOT} for '{slice_name}', tried {cands}")

def _load_example(domain: str, ex_id: str) -> Dict[str, Any]:
    p = EVAL_ROOT / "examples" / domain / f"{ex_id}.json"
    if not p.exists():
        raise SystemExit(f"[FATAL] example not found: {p}")
    return _load_json(p)

def _pairs(meta: Dict[str, List[str]]) -> List[Tuple[str,str]]:
    out = []
    for d in sorted(meta.keys()):
        for ex in sorted(meta[d]):
            out.append((d, ex))
    return out

def _requires_gdrive(cfg: Dict[str, Any], domain: str) -> bool:
    dl = str(domain).lower()
    if dl in {"googledrive","google_drive","google-drive","gdrive"}:
        return True
    def _hit(v: Any) -> bool:
        if isinstance(v, str):
            s = v.lower()
            return ("drive.google.com" in s) or ("docs.google.com/drive" in s)
        if isinstance(v, (list, tuple)):
            return any(_hit(x) for x in v)
        if isinstance(v, dict):
            return any(_hit(x) for x in v.values())
        return False
    steps = list(cfg.get("setup", []) or []) + list(cfg.get("config", []) or [])
    for st in steps:
        t = (st.get("type") or "").lower()
        if "googledrive" in t or t in {"gdrive","google_drive"}:
            return True
        if _hit(st.get("parameters", {})):
            return True
    return False

def _build_body(region: str, cfg: Dict[str, Any], domain: str, ex_id: str,
                max_steps: int, max_seconds: int, screen: str, seed: int) -> Dict[str, Any]:
    sw, sh = screen.lower().split("x")
    return {
        "task_id": f"{domain}_{ex_id}",
        "instruction": cfg.get("instruction","Follow the instruction."),
        "seed": seed,
        "limits": {"max_steps": max_steps, "max_seconds": max_seconds},
        "osworld": {
            "provider_name": "aws",
            "os_type": "Ubuntu",
            "region": region,
            "screen_width": int(sw),
            "screen_height": int(sh),
            "task_config": cfg
        }
    }

def _validate_act_result(obj: Dict[str, Any]) -> Tuple[bool, str]:
    """Strict but友好：返回(bool, reason)."""
    req_keys = ["task_id","success","reward","steps","wall_time_sec","details"]
    for k in req_keys:
        if k not in obj:
            return False, f"missing_key:{k}"
    if not isinstance(obj["task_id"], str):
        return False, "task_id_not_str"
    if not isinstance(obj["success"], bool):
        return False, "success_not_bool"
    try:
        float(obj["reward"])
        float(obj["wall_time_sec"])
        int(obj["steps"])
    except Exception:
        return False, "num_cast_error"
    if obj["steps"] < 0 or obj["wall_time_sec"] < 0:
        return False, "negative_value"
    if not isinstance(obj["details"], dict):
        return False, "details_not_dict"
    # Optional but recommended:
    if "limits" not in obj["details"] or "backend" not in obj["details"]:
        return False, "details_missing_limits_or_backend"
    return True, "ok"

def main():
    ap = argparse.ArgumentParser(description="A2A probe (simulate AgentBeats calling Green)")
    ap.add_argument("--host", default=os.getenv("GREEN_AGENT_HOST","127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("GREEN_AGENT_PORT","18080")))
    ap.add_argument("--token", default=os.getenv("GREEN_AUTH_TOKEN","").strip())
    ap.add_argument("--use-path-token", action="store_true", default=os.getenv("GREEN_USE_PATH_TOKEN","false").lower()=="true")
    ap.add_argument("--slice", default=os.getenv("GREEN_TASKSET","test_nodrive"))
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--region", default=os.getenv("AWS_REGION","us-east-1"))
    ap.add_argument("--screen", default=os.getenv("SCREEN_SIZE","1920x1080"))
    ap.add_argument("--seed", type=int, default=int(os.getenv("GREEN_TASK_SEED","42")))
    ap.add_argument("--timeout", type=float, default=float(os.getenv("GREEN_CLIENT_TIMEOUT","600.0")))
    ap.add_argument("--nogdrive", action="store_true", default=True, help="enforce skip gdrive (default on)")
    args = ap.parse_args()

    base = f"http://{args.host}:{args.port}"
    headers = {}
    path_prefix = ""
    if args.token:
        if args.use_path_token:
            path_prefix = f"/t/{args.token}"
        else:
            headers["X-Auth-Token"] = args.token

    client = httpx.Client(timeout=args.timeout)

    # 1) /card
    card_url = f"{base}{path_prefix}/card"
    try:
        r = client.get(card_url, headers=headers)
        if not (200 <= r.status_code < 300):
            print(f"[FATAL] /card HTTP {r.status_code}: {r.text}")
            sys.exit(2)
        card = r.json()
        print(f"[ok] /card -> name={card.get('name')} version={card.get('version')} protocol={card.get('protocol')}")
    except Exception as e:
        print(f"[FATAL] /card error: {e}")
        sys.exit(2)

    # 2) pick K random examples
    meta, meta_name = _load_meta(args.slice)
    pairs = []
    for d in sorted(meta.keys()):
        for ex in sorted(meta[d]):
            cfg = _load_example(d, ex)
            if args.nogdrive and _requires_gdrive(cfg, d):
                continue
            pairs.append((d, ex, cfg))
    if len(pairs) == 0:
        print("[FATAL] no eligible examples in slice after filtering")
        sys.exit(3)
    random.seed(args.seed)
    sample = random.sample(pairs, min(args.k, len(pairs)))
    print(f"[info] slice={meta_name} eligible={len(pairs)} pick={len(sample)}")

    # 3) POST /act for each, assert schema
    ok_cnt = 0
    for i, (domain, ex_id, cfg) in enumerate(sample, 1):
        body = _build_body(args.region, cfg, domain, ex_id, 12, 120, args.screen, args.seed)
        url = f"{base}{path_prefix}/act"
        print(f"[{i}/{len(sample)}] POST {url} -> {domain}/{ex_id}")
        try:
            resp = client.post(url, json=body, headers=headers)
            if not (200 <= resp.status_code < 300):
                print(f"  -> HTTP {resp.status_code}: {resp.text[:240]}")
                continue
            data = resp.json()
            ok, reason = _validate_act_result(data)
            if ok:
                ok_cnt += 1
                print(f"  -> PASS success={data.get('success')} reward={data.get('reward')} steps={data.get('steps')}")
            else:
                print(f"  -> FAIL schema: {reason}")
        except Exception as e:
            print(f"  -> EXC: {e}")

    print(f"[done] A2A probe: pass={ok_cnt} / total={len(sample)}")
    sys.exit(0 if ok_cnt == len(sample) else 5)

if __name__ == "__main__":
    main()