# OSWorld × AgentBeats: Green Judge & White Agents (A2A Integration)

This project provides:

* a **Green judge (FastAPI)** that runs OSWorld desktops and evaluates agents via an **A2A** contract, and
* baseline **White agents** (e.g., `white_sim`) that implement `/act`.

Any external White agent that speaks the same A2A contract can plug in and operate the OSWorld desktop.

## 1) Quickstart

### 1.1 Install

```bash
# Python 3.11 recommended
conda env create -f environment.yml
conda activate cs294

# Use project Python (no new Poetry venv)
poetry config virtualenvs.create false --local
poetry install --no-root
```

### 1.2 `.env` Configuration

> Full AWS setup reference:
[OSWorld AWS Guideline](https://github.com/xlang-ai/OSWorld/blob/main/desktop_env/providers/aws/AWS_GUIDELINE.md)

Minimal example (fill with your own values):

```bash
# ---------- AWS / OSWorld ----------
# Region used when Green spins up OSWorld desktops
AWS_REGION=us-east-1
AWS_DEFAULT_REGION=us-east-1

# Your AWS credentials (DO NOT COMMIT REAL VALUES)
AWS_ACCESS_KEY_ID=AKIAxxxxxxxxxxxxxxxx
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Networking for EC2 instances (from your AWS account)
AWS_VPC_ID=vpc-xxxxxxxx
AWS_SUBNET_ID=subnet-xxxxxxxx
AWS_SECURITY_GROUP_ID=sg-xxxxxxxx
AWS_KEY_NAME= # your EC2 keypair name

# A2A auth (enable + token). Generate with:
#   python -c "import secrets; print(secrets.token_hex(16))"
GREEN_REQUIRE_AUTH=true
GREEN_AUTH_TOKEN=paste_random_hex_here
GREEN_USE_PATH_TOKEN=false
```

Generate a random token for `GREEN_AUTH_TOKEN`:

```bash
python - <<'PY'
import secrets; print(secrets.token_hex(16))
PY
```

### 1.3 Start & Smoke Test

```bash
# Load env + print masked key vars
chmod +x scripts/*.sh
source scripts/setup_env.sh

# Start a baseline White (replace with your White URL anytime)
./scripts/start_white_sim.sh

# Start Green (port checks, auth, HTTP-backend guard)
./scripts/start_green.sh

# Health (no auth required)
curl -s "http://127.0.0.1:${GREEN_AGENT_PORT}/health" | jq .

# Minimal smoke (auto-injects auth if configured)
./scripts/green_smoke.sh
```

### 1.4 Run Slices (batch)

```bash
# Randomly sample 5 examples
./scripts/run_slice.sh random 5
```

For full control (slice choice, filters, auth, etc.), see [§6.2 Batch slices (offline metrics)](#62-batch-slices-offline-metrics).


Outputs:

```
results/
├─ green_runs/<task_id>-<UTC>/
│  ├─ frames/                 # step PNGs
│  ├─ trace.jsonl             # per-step action/reward/done
│  ├─ result.json             # single-task result (A2A-aligned)
│  ├─ summary.json            # header/footer info (region/provider/screen)
│  └─ artifact.json           # artifact manifest for archiving
└─ summary/
   ├─ summary_<mode>_<slice>_<ts>.csv
   └─ summary_<mode>_<slice>_<ts>.jsonl
```


## 2) Architecture

```
AgentBeats (Platform)
        │
        ▼  A2A (/card, /reset, /act)
Green Server (FastAPI)
        │                 ┌──────── White Agent (any team)
        ├───► /act ───────┤        A2A: /card, /reset, /act
        │                 └──────── Action: {type: code|special, ...}
        ▼
OSWorldAdapter
        ▼
DesktopEnv.reset / step("pyautogui code"|WAIT) / close
        ▲
  reward / done / obs(screenshot+a11y)
```

* **Green**: spins up `DesktopEnv`, loops **observe → ask White → execute → observe**, records traces and metrics, returns a unified result.
* **White**: only implements `/act`; consumes screenshot (base64) + optional a11y; returns next action (pyautogui code or `WAIT/DONE/FAIL`).


## 3) Code Layout

```
cs294-ai-agent/
├─ scripts/
│  ├─ setup_env.sh                 # load .env, activate conda, print masked vars
│  ├─ start_green.sh               # start Green (port guard, logs, backend guard)
│  ├─ stop_green.sh                # stop Green
│  ├─ start_white_sim.sh           # start baseline White
│  ├─ stop_white_sim.sh            # stop baseline White
│  ├─ green_smoke.sh               # one-button smoke /act (curl; auto-auth, direct Green)
│  ├─ test_green_smoke.sh          # dev helper: extra smoke test for Green endpoint
│  ├─ run_slice.sh                 # batch runner (small/domain/single/random/indices)
│  ├─ start_agentbeats_ctrl.sh     # start AgentBeats controller (manages Green for AB)
│  └─ stop_agentbeats_ctrl.sh      # stop AgentBeats controller
|
├─ green/
│  ├─ app.py                       # /card /reset /act; auth (header/path); .well-known
│  ├─ a2a_models.py                # A2A request/response/action/observation schemas
│  ├─ osworld_adapter.py           # thin wrapper of DesktopEnv.reset/step/wait/close
│  ├─ white_client.py              # HTTP client to call White /card /reset /act
│  ├─ result_writer.py             # result.json, trace.jsonl, frames, artifact.json
│  └─ validators.py                # env guards (no HTTP backend, etc.)
│
├─ run_modes/
│  └─ runner.py                    # unified batch runner (slice/filter/auth/CSV+JSONL)
│
└─ third_party/osworld/            # vendored upstream (no changes)
```

## 4) White A2A

**Request** `POST /act` (Green → White)

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

**Response (action: code)**

```json
{ "type": "code", "code": "pyautogui.click(960, 540)", "pause": 0.5 }
```

**Response (control: special)**

```json
{ "type": "special", "name": "WAIT", "pause": 0.5 }
{ "type": "special", "name": "DONE", "pause": 0.0 }
{ "type": "special", "name": "FAIL", "pause": 0.0 }
```

Green runs the loop until `done` or limits reached and returns:

```json
{
  "task_id": "...",
  "success": true,
  "reward": 1.0,
  "steps": 7,
  "wall_time_sec": 85.3,
  "logs_dir": "results/green_runs/<task_id>-<UTC>",
  "details": { "backend": "python-api", "provider": "aws", "limits": {...}, "agent_version": "0.1.0", "env_signature": "..." }
}
```


## 5) AgentBeats Integration Notes

* **Card discovery (registration)**

  * Header auth: `GET /card` with `X-Auth-Token`
  * Path auth: `GET /t/<token>/.well-known/agent-card.json`

* **Battle invocation**

  * `POST /act` (or `/t/<token>/act`): returns the unified result schema above.

* **Offline metrics submission**

  * Upload `results/summary/summary_*.csv` or `jsonl` to the platform’s designated place.

> Browsers may hit `GET /act` or `/favicon.ico` while testing; you’ll see `405`/`404`. Those are expected and harmless.


## 6) Local Testing & Dev Tips

### 6.1 One-shot health & smoke

```bash
source scripts/setup_env.sh
./scripts/start_white_sim.sh
./scripts/start_green.sh
./scripts/green_smoke.sh
```

---

### 6.2 Batch slices (offline metrics)

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


## 7) AgentBeats Controller Integration (Green as Remote Judge)

This section explains how to expose the **OSWorld Green agent** behind an **AgentBeats controller** on your own server, so that it can be registered and used from the AgentBeats web UI.


### 7.1 Start the AgentBeats controller on your server

On **your server**, from the project root, simply run:

```bash
bash scripts/start_agentbeats_ctrl.sh
```

To stop the controller (and the managed Green instance), run:

```bash
bash scripts/stop_agentbeats_ctrl.sh
```

> If you want to run this on a different port or with a different public host,
> edit `scripts/start_agentbeats_ctrl.sh` and adjust `CLOUDRUN_HOST`, `HOST`, and `PORT` accordingly.

### 7.2 Check the controller + Green from the server

The easiest way to confirm that the **AgentBeats controller + Green agent** are working is to open the controller info page in a browser:

* If you are on the **server itself** (SSH with port-forwarding or X11 etc.):

  ```text
  http://127.0.0.1:18080/info
  ```

* If you are checking from **another machine** and your server has a public IP, use that IP instead, for example:

  ```text
  http://107.21.71.139:18080/info
  ```

On that page, verify two things:

1. At the top, the status card shows:

   ```text
   Running Agent / Maintained Agent  1 / 1
   ```

   This means the controller has successfully started exactly one Green agent and is maintaining it.

2. In the **“Agent Instances”** section at the bottom:

   * Expand the single agent card.
   * Open the **“Agent Card”** panel.
   * You should see a JSON MCP card (with fields like `name`, `protocolVersion`, `skills`, etc.), **without** any red error message about local IPs.


---

### 7.3 Register the Green controller on AgentBeats

Once the controller is running and the info page looks good (Section 7.1–7.2):

1. Open the official platform guide:
   [Notes – Using the agentbeats v2 platform – 2025.11](https://docs.google.com/presentation/d/1g6D9a_uUiqudNlRvoRy4L4JmHkdMinFSTBra6bPgayM/edit)

2. In that slide, follow the steps for **registering a agent** on AgentBeats.

3. When the guide asks you to fill in the **Controller URL**, use the Green controller you just started:

   ```text
   http://YOUR_PUBLIC_HOST:18080
   ```

4. Complete the remaining steps exactly as described in the slides.

Once you finish the registration flow in the slides, your OSWorld Green agent (controller at `:18080`) will be available on the AgentBeats platform and can be used in battles/evaluations.