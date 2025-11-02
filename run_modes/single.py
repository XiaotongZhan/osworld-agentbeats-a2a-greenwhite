import os, sys, json, uuid, requests, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GREEN_PORT = int(os.environ.get("GREEN_AGENT_PORT","18080"))

def run_one(domain: str, example_id: str):
    ex_path = ROOT / "third_party" / "osworld" / "evaluation_examples" / "examples" / domain / f"{example_id}.json"
    if not ex_path.is_file():
        raise SystemExit(f"example not found: {ex_path}")
    example = json.loads(ex_path.read_text(encoding="utf-8"))
    req = {
      "task_id": f"single-{uuid.uuid4()}",
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
    ap.add_argument("--domain", required=True)
    ap.add_argument("--example_id", required=True)
    args = ap.parse_args()
    run_one(args.domain, args.example_id)
