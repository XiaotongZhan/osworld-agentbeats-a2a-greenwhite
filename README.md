# OSWorld × AgentBeats: Green Judge & White Agents (A2A Integration)

This repository provides:

* **Green Judge (OSWorld-Green):** a service that launches OSWorld desktops (AWS) and evaluates a White agent via a simple action API.
* **White agents:**
  * `white_sim` — a baseline White agent (simple heuristic policy).
  * `white_agent` — our official White agent powered by Qwen3-VL (DashScope) that outputs executable `pyautogui` actions.

The key design is **modularity**:

* Green runs the OSWorld environment and the evaluation loop.
* White only needs to implement a small contract: `/card`, `/reset`, `/act`.
* Any external White agent that speaks the same contract can plug into Green.

---

## 1) Quickstart (Local Repro)

### 1.1 Install

Tested with **Python 3.13**.

```bash
# Create and activate conda env
conda create -n cs294 python=3.13 -y
conda activate cs294

# Install dependencies (poetry uses the conda env python; no extra venv)
pip install -U pip poetry
poetry config virtualenvs.create false --local
poetry install --no-root
````

### 1.2 .env Configuration

> Full AWS setup reference:
[OSWorld AWS Guideline](https://github.com/xlang-ai/OSWorld/blob/main/desktop_env/providers/aws/AWS_GUIDELINE.md)

Copy the template and fill your own values:

```bash
cp .env.example .env
```

Minimum required variables:

```bash
# ---------- AWS / OSWorld ----------
AWS_REGION=us-east-1
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_VPC_ID=...
AWS_SUBNET_ID=...
AWS_SECURITY_GROUP_ID=...
AWS_KEY_NAME=...

# ---------- White LLM (for Qwen3-VL White) ----------
DASHSCOPE_API_KEY=...

# ---------- Optional: Green auth (if you enable it) ----------
GREEN_REQUIRE_AUTH=false
GREEN_AUTH_TOKEN=
GREEN_USE_PATH_TOKEN=false
```

Then load env (idempotent, prints masked signals and runs AMI preflight by default):

```bash
source scripts/setup_env.sh
```

---

## 2) Local End-to-End Testing (Recommended)

You have two local workflows:

* **Workflow A (simple):** background scripts (`scripts/start_*.sh`)
* **Workflow B (debug/foreground):** controller-style `*_ctrl/run.sh` (closer to AgentBeats deployment)

### 2.1 Workflow A — Simple Local Start (baseline White)

Start baseline White + Green (HTTP mode):

```bash
source scripts/setup_env.sh
./scripts/start_white_sim.sh
./scripts/start_green.sh
```

Smoke test (direct Green endpoint):

```bash
./scripts/green_smoke.sh
```

Stop:

```bash
./scripts/stop_green.sh
./scripts/stop_white_sim.sh
```

For full control (slice choice, filters, auth, etc.), see [§8 Local Testing & Dev Tips](#8-local-testing--dev-tips).

### 2.2 Workflow B — Foreground Local Start (Official White + Green) + Runner

This is the exact workflow we use to validate the official White agent (`white_agent`) with the slice runner.

#### Step 0) Ensure OSWorld evaluation examples are available

Some utilities expect `evaluation_examples/` at repo root. If missing, symlink it:

```bash
cd ~/zxt/agentbeats-green-osworld
if [ ! -e evaluation_examples ]; then
  ln -s third_party/osworld/evaluation_examples evaluation_examples
fi
```

#### Step 1) Start the official White agent (Qwen3-VL)

```bash
conda activate cs294
cd ~/zxt/agentbeats-green-osworld
source scripts/setup_env.sh

export AGENT_PORT=18081
export AGENT_ID=local
./white_ctrl/run.sh
```

Check:

```bash
curl -s http://127.0.0.1:18081/card
```

#### Step 2) Start Green in HTTP mode (so the local runner.py can call /act)

```bash
conda activate cs294
cd ~/zxt/agentbeats-green-osworld
source scripts/setup_env.sh

export WHITE_AGENT_URL="http://127.0.0.1:18081"
export AGENT_PORT=18080
export AGENT_ID=local

# IMPORTANT:
# For local runner, Green must expose REST endpoints (/card /reset /act).
# Make sure green_ctrl/run.sh is configured to run green.app:app (HTTP mode) in .env file.
./green_ctrl/run.sh
```

Check:

```bash
curl -s http://127.0.0.1:18080/card | head
curl -s -X POST http://127.0.0.1:18080/reset | head
```

#### Step 3) Run slice evaluation via runner (deterministic)

```bash
conda activate cs294
cd ~/zxt/agentbeats-green-osworld
source scripts/setup_env.sh

python run_modes/runner.py \
  --mode random \
  --slice test_small \
  --k 1 \
  --seed 52 \
  --nogdrive \
  --host 127.0.0.1 \
  --port 18080 \
  --max-steps 30 \
  --max-seconds 900 \
  --no-proxy
```

Outputs are written to:

```text
results/
├─ green_runs/<task_id>-<UTC>/
│  ├─ frames/                 # step screenshots
│  ├─ trace.jsonl             # action trace
│  ├─ result.json             # per-task result
│  ├─ summary.json            # environment + run metadata
│  └─ artifact.json           # artifact manifest
└─ summary/
   ├─ summary_<mode>_<slice>_<ts>.csv
   └─ summary_<mode>_<slice>_<ts>.jsonl
```

---

## 3) Architecture

```text
AgentBeats (Platform)
        │
        ▼  A2A (Agent card + /act)
Green (A2A wrapper for platform)
        │
        ▼  internal evaluation loop (OSWorld)
Green Service (HTTP: /reset /act)
        │                 ┌──────── White Agent (HTTP)
        ├───► /act ───────┤        /card /reset /act
        │                 └──────── returns action (pyautogui code or special)
        ▼
OSWorldAdapter
        ▼
DesktopEnv.reset / step("pyautogui code"|WAIT) / close
        ▲
  reward / done / obs(screenshot+a11y)
```

### 3.1 Green responsibilities

* Launch OSWorld desktop (AWS) via `DesktopEnv`.
* Loop: observe → query White → execute → log until done/limits.
* Write artifacts: screenshots, action traces, result summaries.

### 3.2 White responsibilities

At each step, White receives:

* natural language instruction
* screenshot (base64 PNG)
* optional a11y tree and screen metadata
* step index + tool hints

White outputs:

* either executable `pyautogui` code (mouse/keyboard/scroll), or
* a special control action: `WAIT`, `DONE`, `FAIL`

---

## 4) White HTTP Contract

Request `POST /act` (Green → White)

```json
{
  "instruction": "Natural-language task instruction",
  "observation": {
    "screenshot_b64": "<base64 PNG>",
    "a11y_tree": null,
    "width": 1920,
    "height": 1080
  },
  "tools": ["mouse","keyboard","scroll","wait"],
  "step": 3
}
```

Response (action: code)

```json
{ "type": "code", "code": "pyautogui.click(960, 540)", "pause": 0.5 }
```

Response (control: special)

```json
{ "type": "special", "name": "WAIT", "pause": 0.5 }
```

```json
{ "type": "special", "name": "DONE", "pause": 0.0 }
```

```json
{ "type": "special", "name": "FAIL", "pause": 0.0 }
```

---

## 5) Code Layout (High-Level)

```text
agentbeats-green-osworld/
├─ green/                      # Green judge core (OSWorld evaluation loop)
│  ├─ app.py                   # HTTP endpoints (/card /reset /act)
│  ├─ a2a_app.py               # A2A wrapper (platform-facing)
│  ├─ osworld_adapter.py
│  ├─ white_client.py
│  └─ result_writer.py
│
├─ white_sim/                  # Baseline White (heuristic)
│  └─ server.py
│
├─ white_agent/                # Official White (Qwen3-VL / DashScope)
│  ├─ server.py
│  └─ policy/...
│
├─ green_ctrl/                 # controller-style run scripts for Green
│  └─ run.sh
├─ white_ctrl/                 # controller-style run scripts for White
│  └─ run.sh
│
├─ scripts/                    # one-command helpers (start/stop/smoke)
│  ├─ setup_env.sh
│  ├─ start_green.sh / stop_green.sh
│  ├─ start_white_sim.sh / stop_white_sim.sh
│  ├─ start_agentbeats_ctrl_green.sh / stop_agentbeats_ctrl_green.sh
│  └─ start_agentbeats_ctrl_white.sh / stop_agentbeats_ctrl_white.sh
│
└─ run_modes/
   └─ runner.py                # slice runner (random/domain/single/indices)
```

---

## 6) AgentBeats Integration (Battle-Ready)

### 6.1 Start AgentBeats controller for Green

On your server (make sure port is allowed in the security group):

```bash
# Make sure green_ctrl/run.sh is configured to run green.a2a_app:app mode in .env file.
bash scripts/start_agentbeats_ctrl_green.sh
```

Default controller info page:

```text
http://<YOUR_PUBLIC_HOST>:20080/info
```

### 6.2 Start AgentBeats controller for White

```bash
bash scripts/start_agentbeats_ctrl_white.sh
```

Default controller info page:

```text
http://<YOUR_PUBLIC_HOST>:20081/info
```

### 6.3 Register on AgentBeats and battle

* Register the controller URL for Green and White on the platform UI. Please follow the official platform guide:
   [Notes – Using the agentbeats v2 platform – 2025.11](https://docs.google.com/presentation/d/1g6D9a_uUiqudNlRvoRy4L4JmHkdMinFSTBra6bPgayM/edit)
* Start a battle/assessment; the platform passes the White URL to Green, and Green runs OSWorld + calls White.

Stop controllers:

```bash
bash scripts/stop_agentbeats_ctrl_green.sh
bash scripts/stop_agentbeats_ctrl_white.sh
```

---

## 7) Troubleshooting

### 7.1 Missing proxy config under evaluation_examples/...

If you see errors like missing `evaluation_examples/settings/proxy/...`, either:

* create the symlink (see §2.2 Step 0), or
* run runner with `--no-proxy` (recommended).

### 7.2 DashScope “response has no text content”

This is an upstream API failure mode. Confirm:

* `DASHSCOPE_API_KEY` is set correctly
* network access is stable
* retry behavior is enabled (the policy already retries)

### 7.3 Port already in use

Use:

```bash
lsof -i :<PORT>
```

Stop previous processes or choose another port.

### 7.4 OSWorld AMI preflight fails

`scripts/setup_env.sh` runs an AMI visibility check. Fix AWS region/credentials/VPC/subnet/security-group config in `.env`.

---

## 8) Local Testing & Dev Tips

### 8.1 One-shot health & smoke

```bash
source scripts/setup_env.sh
./scripts/start_white_sim.sh
./scripts/start_green.sh
./scripts/green_smoke.sh
```

---

### 8.2 Batch slices (offline metrics)

You can batch-run OSWorld tasks through the Green A2A endpoint to produce repeatable, platform-friendly metrics.

#### What is a “slice”?

A **slice** is the meta list used to enumerate tasks (files under `third_party/osworld/evaluation_examples/`):

* `test_small` – quick sanity set
* `verified_small` – curated/verified small set
* `test_all` – full set
* `verified_all` – curated/verified full set
* `nodrive` – excludes any Google Drive tasks
* Or any explicit meta file name, e.g. `custom_team_slice.json`

#### Supported modes

* `small` — run the entire chosen slice
* `domain` — run all examples from one domain
* `single` — run exactly one example as `domain/example_id`
* `random` — run a random subset of size `k`
* `indices` — run specific 0-based indices within the slice (deterministic)

> Outputs land in:
>
> * Requests: `results/requests/act_*.json`
> * Responses: `results/responses/resp_*.json`
> * Summary CSV: `results/summary/summary_<mode>_<slice>_<ts>.csv`
> * Index map: `results/summary/indices_<slice>_<ts>.csv`
> * Per-run artifacts (from Green’s `/act`): see `logs_dir` → `result.json`, `summary.json`, `trace.jsonl`, `frames/step_*.png`.

---

#### A) Quick script usage

```bash
# Run the small slice (defaults to `test_small` inside the script)
./scripts/run_slice.sh small

# Run an entire domain from the current script’s default slice
./scripts/run_slice.sh domain chrome

# Randomly sample 10 examples
./scripts/run_slice.sh random 10
```

> Tip: If you need finer control (pick a specific slice, toggle filters, pass auth styles), use the **direct Python** form below.

---

#### B) Direct Python (full control)

Common flags:

* `--slice <name>`: `test_small|verified_small|test_all|verified_all|nodrive|<file.json>`
* `--mode <m>`: `small|domain|single|random|indices`
* `--host/--port`: Green endpoint (default `127.0.0.1:18080`)
* `--region`: AWS region for OSWorld (default `us-east-1`)
* `--max-steps / --max-seconds`: per-episode limits
* `--screen`: desktop resolution, e.g. `1920x1080`
* Filters: `--nogdrive`, `--no-proxy`
* Auth:

  * Header token: `--token "$GREEN_AUTH_TOKEN"`
  * Path token: `--use-path-token --token "$GREEN_AUTH_TOKEN"`

**Run entire slice (`verified_small`)**

```bash
python run_modes/runner.py \
  --mode small \
  --slice verified_small \
  --host 127.0.0.1 --port 18080 \
  --region us-east-1 \
  --screen 1920x1080 \
  --max-steps 30 --max-seconds 300 \
  --nogdrive \
  --token "$GREEN_AUTH_TOKEN"
```

**Run a specific domain from `verified_all`**

```bash
python run_modes/runner.py \
  --mode domain \
  --slice verified_all \
  --domain chrome \
  --nogdrive --no-proxy \
  --token "$GREEN_AUTH_TOKEN"
```

**Run a single example (`domain/example_id`)**

```bash
python run_modes/runner.py \
  --mode single \
  --slice test_all \
  --example libreoffice_writer/001_open_new_document \
  --max-steps 60 --max-seconds 600 \
  --token "$GREEN_AUTH_TOKEN"
```

**Randomly sample 10 (deterministic with seed)**

```bash
python run_modes/runner.py \
  --mode random \
  --slice test_all \
  --k 10 \
  --seed 123 \
  --nogdrive \
  --token "$GREEN_AUTH_TOKEN"
```

**Run by indices from `verified_small` (e.g., #0, #7, #42)**

```bash
python run_modes/runner.py \
  --mode indices \
  --slice verified_small \
  --indices 0,7,42 \
  --token "$GREEN_AUTH_TOKEN"
```

**Call a remote Green with path-token**

```bash
python run_modes/runner.py \
  --mode small \
  --slice verified_small \
  --host A.B.C.D --port 18081 \
  --use-path-token --token "$GREEN_AUTH_TOKEN"
```

**Override desktop size/timeouts**

```bash
python run_modes/runner.py \
  --mode random --slice test_all --k 5 \
  --screen 2560x1440 \
  --max-steps 40 --max-seconds 480 \
  --timeout 1200 \
  --token "$GREEN_AUTH_TOKEN"
```