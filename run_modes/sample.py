import os, sys, json, uuid, random, requests, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GREEN_PORT = int(os.environ.get("GREEN_AGENT_PORT","18080"))

def run_sample(k: int):
    base = ROOT / "third_party" / "osworld" / "evaluation_examples"
    test_all = json.loads((base / "test_all.json").read_text(encoding="utf-8"))
    all_paths = []
    for domain, ids in test_all.items():
        for exid in ids:
            p = base / "examples" / domain / f"{exid}.json"
            if p.is_file(): all_paths.append((domain, exid, p))
    if k < len(all_paths):
        all_paths = random.sample(all_paths, k)
    for domain, exid, p in all_paths:
        example = json.loads(p.read_text(encoding="utf-8"))
        req = {
          "task_id": f"sample-{domain}-{exid}",
          "instruction": example.get("instruction",""),
          "limits": {"max_steps": 100, "max_seconds": 300},
          "osworld": {
            "provider_name": os.environ.get("OSWORLD_PROVIDER","aws"),
            "os_type": "Ubuntu",
            "region": os.environ.get("AWS_REGION","us-east-1"),
            "screen_width": int(os.environ.get("SCREEN_WIDTH","1920")),
            "screen_height": int(os.environ.get("SCREEN_HEIGHT","1080")),
            "task_config": example
          }
        }
        url = f"http://127.0.0.1:{GREEN_PORT}/act"
        r = requests.post(url, json=req, timeout=900)
        r.raise_for_status()
        print(json.dumps(r.json(), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, required=True)
    args = ap.parse_args()
    run_sample(args.k)
