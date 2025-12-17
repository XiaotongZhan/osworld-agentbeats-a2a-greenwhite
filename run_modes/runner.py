#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse, csv, json, os, sys, time, random, re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import httpx

ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "third_party" / "osworld" / "evaluation_examples"
REQ_DIR = ROOT / "results" / "requests"
RESP_DIR = ROOT / "results" / "responses"
SUMMARY_DIR = ROOT / "results" / "summary"
for d in (REQ_DIR, RESP_DIR, SUMMARY_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ------------------------ helpers ------------------------

def _now() -> str:
    # YYYYmmdd_HHMMSS for filenames (UTC)
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime())

def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(s))[:120]

def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _load_meta_file(slice_name: str) -> Tuple[Dict[str, List[str]], str]:
    """
    Load a meta list by 'slice' name with fallbacks.
    Returns (meta_dict, basename_used).
    """
    candidates = []
    s = slice_name.lower()

    # Normalize a few aliases
    if s in {"small", "test_small"}:
        candidates = ["test_small.json", "verified_small.json", "test_all.json"]
    elif s in {"all", "test_all"}:
        candidates = ["test_all.json", "verified_all.json"]
    elif s in {"verified_small"}:
        candidates = ["verified_small.json", "test_small.json", "test_all.json"]
    elif s in {"verified_all"}:
        candidates = ["verified_all.json", "test_all.json"]
    elif s in {"nodrive", "test_nodrive"}:
        candidates = ["test_nodrive.json", "test_small.json", "test_all.json"]
    else:
        # treat as explicit file name
        candidates = [s if s.endswith(".json") else f"{s}.json"]

    for name in candidates:
        p = EVAL_ROOT / name
        if p.exists():
            return _load_json(p), name
    raise SystemExit(f"[FATAL] No meta json found under {EVAL_ROOT} for slice '{slice_name}'. "
                     f"Looked for: {candidates}")

def _load_example(domain: str, ex_id: str) -> Dict[str, Any]:
    fp = EVAL_ROOT / "examples" / domain / f"{ex_id}.json"
    if not fp.exists():
        raise SystemExit(f"[FATAL] Example not found: {fp}")
    return _load_json(fp)

def _pairs_from_meta(meta: Dict[str, List[str]]) -> List[Tuple[str, str]]:
    # Produce a *stable, deterministic* ordering: sort by domain, then example id
    pairs: List[Tuple[str, str]] = []
    for d in sorted(meta.keys()):
        for ex in sorted(meta[d]):
            pairs.append((d, ex))
    return pairs

def _step_list(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Some examples declare steps in either 'setup' or 'config'
    return list(cfg.get("setup", []) or []) + list(cfg.get("config", []) or [])

def _has_proxy_step(cfg: Dict[str, Any]) -> bool:
    for st in _step_list(cfg):
        t = (st.get("type") or "").lower()
        if "proxy" in t:
            return True
    return False

def _requires_gdrive(cfg: Dict[str, Any], domain: str) -> bool:
    # 0) domain name hints
    dl = str(domain).lower()
    if dl in {"googledrive", "google_drive", "google-drive", "gdrive"}:
        return True

    def _hit(val: Any) -> bool:
        if isinstance(val, str):
            s = val.lower()
            if ("drive.google.com" in s) or ("docs.google.com/drive" in s):
                return True
        elif isinstance(val, (list, tuple)):
            return any(_hit(x) for x in val)
        elif isinstance(val, dict):
            return any(_hit(v) for v in val.values())
        return False

    for st in _step_list(cfg):
        t = (st.get("type") or "").lower()
        if "googledrive" in t or t in {"gdrive", "google_drive"}:
            return True
        if _hit(st.get("parameters", {})):
            return True
    return False

def _should_skip(cfg: Dict[str, Any], domain: str, *, skip_gdrive: bool, skip_proxy: bool) -> Tuple[bool, str]:
    if skip_gdrive and _requires_gdrive(cfg, domain):
        return True, "skip:googledrive"
    if skip_proxy and _has_proxy_step(cfg):
        return True, "skip:proxy"
    return False, ""

def _build_act_body(region: str, cfg: Dict[str, Any], domain: str, ex_id: str,
                    max_steps: int, max_seconds: int, screen_w: int, screen_h: int,
                    seed: int) -> Dict[str, Any]:
    return {
        "task_id": f"{domain}_{ex_id}",
        "instruction": cfg.get("instruction", "Follow the instruction."),
        "seed": seed,
        "limits": {"max_steps": max_steps, "max_seconds": max_seconds},
        "osworld": {
            "provider_name": "aws",
            "os_type": "Ubuntu",
            "region": region,
            "screen_width": screen_w,
            "screen_height": screen_h,
            "task_config": cfg
        }
    }

def _fetch_agent_card(client: httpx.Client, base_url: str, path_prefix: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """
    Try to get green /card (or /t/<tok>/card) to read agent version.
    Fallbacks to env or default if unreachable.
    """
    url = f"{base_url}{path_prefix}/card"
    try:
        r = client.get(url, headers=headers, timeout=5.0)
        if 200 <= r.status_code < 300:
            return r.json()
    except Exception:
        pass
    return {}

# ------------------------ main ------------------------

def main():
    p = argparse.ArgumentParser(description="Run OSWorld slices via Green A2A (deterministic & filterable)")
    # Selection semantics
    p.add_argument("--mode", choices=["small", "domain", "single", "random", "indices"], required=True)
    p.add_argument("--slice", default=os.getenv("GREEN_TASKSET", "test_small"),
                   help="Meta slice name: test_small|test_all|verified_small|verified_all|nodrive or a file name under evaluation_examples")
    p.add_argument("--domain", default="", help="For mode=domain")
    p.add_argument("--example", default="", help="For mode=single (domain/example_id)")
    p.add_argument("--k", type=int, default=10, help="For mode=random: sample size")
    p.add_argument("--indices", default="", help="For mode=indices: comma-separated list of global indices (0-based) from the slice")
    p.add_argument("--seed", type=int, default=int(os.getenv("GREEN_TASK_SEED", "42")))

    # Filters
    p.add_argument("--nogdrive", action="store_true", default=os.getenv("GREEN_ENFORCE_NOGDRIVE", "false").lower()=="true")
    p.add_argument("--no-proxy", action="store_true", default=os.getenv("GREEN_SKIP_PROXY", "false").lower()=="true")

    # Limits & envs
    p.add_argument("--host", default=os.getenv("GREEN_AGENT_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("GREEN_AGENT_PORT", "18080")))
    p.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    p.add_argument("--max-steps", type=int, default=30)
    p.add_argument("--max-seconds", type=int, default=300)
    p.add_argument("--screen", default=os.getenv("SCREEN_SIZE", "1920x1080"))
    p.add_argument("--timeout", type=float, default=float(os.getenv("GREEN_CLIENT_TIMEOUT", "600.0")))

    # Auth & URL shaping
    p.add_argument("--use-path-token", action="store_true", default=os.getenv("GREEN_USE_PATH_TOKEN", "false").lower()=="true",
                   help="Call green with /t/<token>/... path-style auth instead of header")
    p.add_argument("--token", default=os.getenv("GREEN_AUTH_TOKEN", "").strip(),
                   help="Override token (else read from env)")
    # Optional override if fetching /card fails
    p.add_argument("--agent-version", default=os.getenv("GREEN_AGENT_VERSION", "").strip(),
                   help="Override agent version if auto-detection fails")

    args = p.parse_args()

    # Parse screen
    sw, sh = args.screen.lower().split("x")
    screen_w, screen_h = int(sw), int(sh)

    # Load slice (meta)
    meta, meta_name = _load_meta_file(args.slice)
    all_pairs = _pairs_from_meta(meta)  # deterministic

    # Decide selection
    if args.mode == "small":
        pairs = all_pairs
    elif args.mode == "domain":
        if not args.domain:
            raise SystemExit("[FATAL] --domain is required for mode=domain")
        pairs = [(d, ex) for (d, ex) in all_pairs if d == args.domain]
        if not pairs:
            raise SystemExit(f"[FATAL] Domain '{args.domain}' not found in slice '{meta_name}'")
    elif args.mode == "single":
        if not args.example or "/" not in args.example:
            raise SystemExit("[FATAL] --example must be 'domain/example_id' for mode=single")
        d, ex = args.example.split("/", 1)
        pairs = [(d, ex)]
    elif args.mode == "random":
        if args.k <= 0:
            raise SystemExit("[FATAL] --k must be positive for mode=random")
        random.seed(args.seed)

        # IMPORTANT:
        # We want k *runnable* tasks. If filters (nogdrive/no-proxy) skip a sampled task,
        # we keep sampling until we collect k runnable ones (or exhaust the slice).
        shuffled = list(all_pairs)
        random.shuffle(shuffled)

        pairs = []
        for (d, ex) in shuffled:
            cfg = _load_example(d, ex)
            skip, _reason = _should_skip(cfg, d, skip_gdrive=args.nogdrive, skip_proxy=args.no_proxy)
            if skip:
                continue
            pairs.append((d, ex))
            if len(pairs) >= args.k:
                break

        if not pairs:
            raise SystemExit("[FATAL] After applying filters, no runnable tasks remain in this slice.")
    elif args.mode == "indices":
        if not args.indices:
            raise SystemExit("[FATAL] --indices is required for mode=indices")
        try:
            idx_list = [int(x.strip()) for x in args.indices.split(",") if x.strip()!=""]
        except Exception:
            raise SystemExit("[FATAL] --indices must be comma-separated integers")
        pairs = []
        for idx in idx_list:
            if not (0 <= idx < len(all_pairs)):
                raise SystemExit(f"[FATAL] index {idx} out of range 0..{len(all_pairs)-1}")
            pairs.append(all_pairs[idx])
    else:
        raise SystemExit(f"[FATAL] Unknown mode: {args.mode}")

    # Prepare URL & headers
    base_url = f"http://{args.host}:{args.port}"
    path_prefix = ""
    headers: Dict[str, str] = {}
    if args.token:
        if args.use_path_token:
            path_prefix = f"/t/{args.token}"
        else:
            headers["X-Auth-Token"] = args.token

    # HTTP client
    client = httpx.Client(timeout=args.timeout)

    # Try to fetch card for agent_version
    card = _fetch_agent_card(client, base_url, path_prefix, headers)
    agent_version = (card.get("version") if isinstance(card, dict) else None) or args.agent_version or "0.1.0"

    print(
        f"[info] mode={args.mode} slice={meta_name} total={len(pairs)} "
        f"url={base_url}{path_prefix or ''} filters: nogdrive={args.nogdrive} no_proxy={args.no_proxy} "
        f"agent_version={agent_version}"
    )

    ts = _now()
    summary_csv = SUMMARY_DIR / f"summary_{_safe(args.mode)}_{_safe(meta_name)}_{ts}.csv"
    summary_jsonl = SUMMARY_DIR / f"summary_{_safe(args.mode)}_{_safe(meta_name)}_{ts}.jsonl"

    out_rows: List[Dict[str, Any]] = []

    # Also dump a mapping file for indices->(domain,ex_id) for reproducibility
    map_path = SUMMARY_DIR / f"indices_{_safe(meta_name)}_{ts}.csv"
    with open(map_path, "w", newline="", encoding="utf-8") as mf:
        mw = csv.writer(mf)
        mw.writerow(["index", "domain", "example_id"])
        for idx, (d, ex) in enumerate(all_pairs):
            mw.writerow([idx, d, ex])
    print(f"[info] wrote index map: {map_path}")

    env_signature = {
        "region": args.region,
        "screen": args.screen,
        "host": args.host,
        "port": args.port,
        "slice": meta_name,
        "auth": "path-token" if args.use_path_token else ("header-token" if args.token else "none"),
        "filters": {"nogdrive": args.nogdrive, "no_proxy": args.no_proxy},
    }

    # Open JSONL
    jlf = open(summary_jsonl, "a", encoding="utf-8")

    # Iterate
    for i, (domain, ex_id) in enumerate(pairs, 1):
        cfg = _load_example(domain, ex_id)

        skip, reason = _should_skip(cfg, domain, skip_gdrive=args.nogdrive, skip_proxy=args.no_proxy)
        if skip:
            row = {
                "task_id": f"{domain}_{ex_id}",
                "domain": domain, "example_id": ex_id, "index": all_pairs.index((domain, ex_id)),
                "skip_reason": reason, "success": None, "reward": None, "steps": None,
                "wall_time_sec": None, "failure_type": None, "status": "skipped",
                "seed": args.seed, "agent_version": agent_version, "env_signature": env_signature,
                "logs_dir": None, "artifact_index": None,
            }
            out_rows.append(row)
            jlf.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[skip] {domain}/{ex_id} ({reason})")
            continue

        body = _build_act_body(args.region, cfg, domain, ex_id, args.max_steps, args.max_seconds, screen_w, screen_h, args.seed)

        req_name = f"act_{_safe(domain)}_{_safe(ex_id)}_{_now()}.json"
        req_fp = REQ_DIR / req_name
        with open(req_fp, "w", encoding="utf-8") as f:
            json.dump(body, f, indent=2)

        url = f"{base_url}{path_prefix}/act"
        print(f"[{i}/{len(pairs)}] POST {url} -> {domain}/{ex_id}")

        try:
            r = client.post(url, json=body, headers=headers)
            ok = (200 <= r.status_code < 300)
            resp_json = r.json() if ok else {"error": r.text, "status_code": r.status_code}
        except Exception as e:
            ok = False
            resp_json = {"error": str(e), "status_code": -1}

        resp_name = f"resp_{_safe(domain)}_{_safe(ex_id)}_{_now()}.json"
        with open(RESP_DIR / resp_name, "w", encoding="utf-8") as f:
            json.dump(resp_json, f, indent=2)

        # Extract standardized fields (robust to missing keys)
        if ok:
            task_id = resp_json.get("task_id") or f"{domain}_{ex_id}"
            failure_type = None
            details = resp_json.get("details") or {}
            if isinstance(details, dict):
                failure_type = details.get("failure_type")
            row = {
                "task_id": task_id,
                "domain": domain,
                "example_id": ex_id,
                "index": all_pairs.index((domain, ex_id)),
                "skip_reason": "",
                "success": bool(resp_json.get("success", False)),
                "reward": float(resp_json.get("reward", 0.0) or 0.0),
                "steps": int(resp_json.get("steps", 0) or 0),
                "wall_time_sec": float(resp_json.get("wall_time_sec", 0.0) or 0.0),
                "failure_type": failure_type,
                "status": "ok",
                "seed": args.seed,
                "agent_version": agent_version,
                "env_signature": env_signature,
                "logs_dir": resp_json.get("logs_dir"),
                "artifact_index": (details.get("artifact_index") if isinstance(details, dict) else None),
            }
            out_rows.append(row)
            jlf.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"  -> success={row['success']} reward={row['reward']} steps={row['steps']}")
        else:
            status_code = resp_json.get("status_code")
            if status_code == 401:
                print("\n[FATAL] 401 Unauthorized from Green.")
                print("        • Ensure GREEN_AUTH_TOKEN matches Green's token;")
                print("        • If using path-token, pass --use-path-token and --token;")
                print("        • Quick test:")
                print(f"          curl -i -H 'X-Auth-Token: {args.token or '<unset>'} {base_url}/health'\n")
                jlf.close()
                sys.exit(4)

            row = {
                "task_id": f"{domain}_{ex_id}",
                "domain": domain, "example_id": ex_id,
                "index": all_pairs.index((domain, ex_id)),
                "skip_reason": "",
                "success": None, "reward": None, "steps": None, "wall_time_sec": None,
                "failure_type": f"error:{status_code}",
                "status": f"error:{status_code}",
                "seed": args.seed, "agent_version": agent_version, "env_signature": env_signature,
                "logs_dir": None, "artifact_index": None,
            }
            out_rows.append(row)
            jlf.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"  -> ERROR {status_code}")

    # write CSV
    with open(summary_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "task_id","domain","example_id","index","skip_reason",
                "success","reward","steps","wall_time_sec","failure_type",
                "status","seed","agent_version","env_signature","logs_dir","artifact_index"
            ]
        )
        w.writeheader()
        for row in out_rows:
            w.writerow(row)

    jlf.close()

    ok_cnt = sum(1 for r in out_rows if r.get("status")=="ok")
    print(f"[done] wrote CSV: {summary_csv}")
    print(f"[done] wrote JSONL: {summary_jsonl}   ok={ok_cnt} / total={len(out_rows)}")

if __name__ == "__main__":
    main()
