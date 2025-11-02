# green/app.py
import asyncio, os, time, uuid, re, json
from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .a2a_models import CardResponse, ActRequest, ActResult, Observation
from .validators import ensure_python_backend_only
from .osworld_adapter import OSWorldAdapter
from .white_client import WhiteAgentClient
from .result_writer import ResultWriter

# ---------------- env & constants ----------------
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)

WHITE_AGENT_URL = os.getenv(
    "WHITE_AGENT_URL",
    f"http://127.0.0.1:{os.getenv('WHITE_PORT','18081')}"
)
OSWORLD_CLIENT_PASSWORD = os.getenv("OSWORLD_CLIENT_PASSWORD", "osworld-public-evaluation")

# Auth switches
GREEN_AUTH_TOKEN = (os.getenv("GREEN_AUTH_TOKEN") or "").strip()
REQUIRE_AUTH = os.getenv("GREEN_REQUIRE_AUTH", "true").lower() != "false"

# Run artifacts base
RUN_BASE = Path(os.getenv("GREEN_RUN_DIR") or (ROOT / "results" / "green_runs")).expanduser()
RUN_BASE.mkdir(parents=True, exist_ok=True)

# ---------------- utils ----------------
def _safe_name(s: str) -> str:
    """Return a filesystem-safe short name."""
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", (s or "").strip())
    return s[:120] if len(s) > 120 else s

def _make_run_dir(task_id: str) -> Path:
    """Create a unique run dir and refresh 'latest' symlink."""
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUN_BASE / f"{_safe_name(task_id)}-{ts}"
    (run_dir / "frames").mkdir(parents=True, exist_ok=True)
    latest = RUN_BASE / "latest"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(run_dir, target_is_directory=True)
    except Exception:
        pass
    return run_dir

async def run_in_thread(func, *args, **kwargs):
    """Run a blocking function in a background thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

def _classify_failure(exc: Exception) -> str:
    """Classify failure type for structured result metadata."""
    msg = str(exc).lower()
    if "setup step" in msg or "setup failed" in msg:
        return "env_setup"
    if "white /act error" in msg or "white agent" in msg:
        return "white_error"
    if "unauthorized" in msg:
        return "unauthorized"
    return "runtime_error"

# ---------------- auth helpers ----------------
def _pick_token_from_headers(x_auth_token: str | None, authorization: str | None) -> str | None:
    """Accept X-Auth-Token or Authorization: Bearer <token>."""
    if x_auth_token:
        return x_auth_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None

def _enforce_auth(header_token: str | None = None, path_token: str | None = None) -> None:
    """Enforce auth unless disabled by GREEN_REQUIRE_AUTH=false."""
    if not REQUIRE_AUTH:
        return
    if not GREEN_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="auth-required-but-token-missing")
    supplied = (header_token or path_token or "").strip()
    if supplied != GREEN_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")

# ---------------- card & signature helpers ----------------
def _card_payload() -> dict:
    """Return the static agent capability card plus a backend hint."""
    payload = CardResponse().model_dump()
    payload["backend"] = "python-api-no-http"
    return payload

def _agent_version() -> str:
    try:
        return CardResponse().version
    except Exception:
        return "0.1.0"

def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _make_env_signature(backend_mode: str, region: str, screen_w: int, screen_h: int) -> str:
    """
    Deterministic environment signature so平台能做结果去重/分桶。
    组成：backend_mode, region, screen, python_version, agent_version
    """
    items = {
        "backend": backend_mode,
        "region": region or "<unset>",
        "screen": f"{screen_w}x{screen_h}",
        "python": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
        "agent_version": _agent_version(),
    }
    blob = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return sha256(blob.encode("utf-8")).hexdigest()

def _write_artifact_json(run_dir: Path,
                         task_id: str,
                         started_at: float,
                         finished_at: float) -> str:
    """
    写入 artifact.json，列出本次 run 的核心产物，返回其文件路径（str）。
    """
    frames_dir = run_dir / "frames"
    frames = sorted([str(p) for p in frames_dir.glob("*.png")])
    artifact = {
        "task_id": task_id,
        "run_dir": str(run_dir),
        "result_json": str(run_dir / "result.json"),
        "trace_jsonl": str(run_dir / "trace.jsonl"),
        "frames": frames,
        "started_at": _iso_utc(started_at),
        "finished_at": _iso_utc(finished_at),
    }
    out = run_dir / "artifact.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2)
    return str(out)

# ---------------- FastAPI app ----------------
app = FastAPI(title="OSWorld Green Agent", version="0.1.0")

# CORS for browser-origin GET/POST (AgentBeats web)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://agentbeats.org", "https://www.agentbeats.org", "*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    ok, mode = ensure_python_backend_only()
    auth_mode = "off" if not REQUIRE_AUTH else "on (header|path)"
    return {
        "ok": ok,
        "backend": mode,
        "region": os.getenv("AWS_REGION", "<unset>"),
        "white_url": WHITE_AGENT_URL,
        "auth": auth_mode,
    }

# ---------- shared /act core ----------
async def _act_core(req: ActRequest) -> JSONResponse:
    # Backend guard (must be python API, not HTTP controller)
    ok, mode = ensure_python_backend_only()
    if not ok:
        raise HTTPException(status_code=500, detail=mode)

    assess_id = req.task_id or str(uuid.uuid4())
    run_dir = _make_run_dir(assess_id)
    writer = ResultWriter(run_dir)

    screen_w = getattr(req.osworld, "screen_width", 1920)
    screen_h = getattr(req.osworld, "screen_height", 1080)

    header = {
        "task_id": assess_id,
        "region": os.getenv("AWS_REGION", "<unset>"),
        "white_agent": WHITE_AGENT_URL,
        "provider": req.osworld.provider_name,
        "screen": [screen_w, screen_h],
    }
    writer.write_summary({"start": header})

    white = WhiteAgentClient(WHITE_AGENT_URL)
    env = None
    steps = 0
    t0 = time.time()
    reward_final = 0.0
    done = False

    # 统一的对齐字段（先准备好）
    region = os.getenv("AWS_REGION", "<unset>")
    agent_ver = _agent_version()
    env_sig = _make_env_signature(mode, region, screen_w, screen_h)
    seed_val = getattr(req, "seed", None)

    try:
        # Optional white reset
        try:
            await white.reset()
        except Exception:
            pass

        # Bring up OSWorld
        env = OSWorldAdapter(
            provider_name=req.osworld.provider_name,
            os_type=req.osworld.os_type,
            region=req.osworld.region,
            screen_size=(screen_w, screen_h),
            client_password=OSWORLD_CLIENT_PASSWORD,
        )

        # Reset in background thread
        obs = await run_in_thread(env.reset, req.osworld.task_config)
        writer.save_frame(steps, obs.get("screenshot_b64"))

        # Main loop
        while (steps < req.limits.max_steps) and ((time.time() - t0) < req.limits.max_seconds) and not done:
            steps += 1

            observation = Observation(
                screenshot_b64=obs.get("screenshot_b64"),
                a11y_tree=obs.get("a11y_tree"),
                width=obs.get("width"),
                height=obs.get("height"),
            )

            try:
                action = await white.act(req.instruction, observation, steps)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"White /act error: {e}")

            if action.type == "special":
                name = (action.name or "").upper()
                if name == "WAIT":
                    obs, reward, done, info = await run_in_thread(env.wait, action.pause or 0.5)
                elif name in ("DONE", "FAIL"):
                    done = True
                    reward = 0.0
                    info = {"terminated_by": name}
                else:
                    obs, reward, done, info = await run_in_thread(env.wait, 0.5)
            elif action.type == "code" and action.code:
                obs, reward, done, info = await run_in_thread(env.step, action.code, action.pause or 0.5)
            else:
                obs, reward, done, info = await run_in_thread(env.wait, 0.5)

            writer.save_frame(steps, obs.get("screenshot_b64"))
            writer.log_step(
                steps,
                action={
                    "type": action.type,
                    "name": action.name,
                    "pause": action.pause,
                    "code": (action.code[:160] if action.code else None),
                },
                result={"reward": reward, "done": done},
            )

            if done:
                reward_final = reward

        wall = time.time() - t0

        # 先写 result.json，再生成 artifact.json，随后把路径写回 details
        result = ActResult(
            task_id=assess_id,
            success=(reward_final > 0.0),
            reward=reward_final,
            steps=steps,
            wall_time_sec=wall,
            logs_dir=str(run_dir),
            details={
                "limits": req.limits.model_dump(),
                "provider": req.osworld.provider_name,
                "backend": "python-api",
                "seed": seed_val,
                "agent_version": agent_ver,
                "env_signature": env_sig,
            },
        )
        writer.write_result(result.model_dump())

        artifact_path = _write_artifact_json(run_dir, assess_id, t0, time.time())
        # 把 artifact 索引补回 details
        result.details["artifact_index"] = artifact_path

        writer.write_summary({"start": header, "end": result.model_dump()})
        return JSONResponse(content=result.model_dump())

    except Exception as e:
        wall = max(0.0, time.time() - t0)
        failure_type = _classify_failure(e)

        # 即便失败也生成 artifact.json（此时 result.json 也会被写入，包含 failure_type）
        result = ActResult(
            task_id=assess_id,
            success=False,
            reward=0.0,
            steps=steps,
            wall_time_sec=wall,
            logs_dir=str(run_dir),
            details={
                "limits": req.limits.model_dump(),
                "provider": req.osworld.provider_name,
                "backend": "python-api",
                "failure_type": failure_type,
                "message": str(e),
                "seed": seed_val,
                "agent_version": _agent_version(),
                "env_signature": _make_env_signature(mode, os.getenv("AWS_REGION", "<unset>"), screen_w, screen_h),
            },
        )
        writer.write_result(result.model_dump())

        artifact_path = _write_artifact_json(run_dir, assess_id, t0, time.time())
        result.details["artifact_index"] = artifact_path

        writer.write_summary({"start": header, "end": result.model_dump()})
        return JSONResponse(content=result.model_dump())

    finally:
        try:
            if env is not None:
                await run_in_thread(env.close)
        except Exception:
            pass
        writer.close()

# ---------- header-auth endpoints (keep existing URLs) ----------
@app.get("/card")
async def card(x_auth_token: str | None = Header(default=None),
               authorization: str | None = Header(default=None)):
    _enforce_auth(_pick_token_from_headers(x_auth_token, authorization), None)
    return JSONResponse(content=_card_payload())

@app.post("/reset")
async def reset(x_auth_token: str | None = Header(default=None),
                authorization: str | None = Header(default=None)):
    _enforce_auth(_pick_token_from_headers(x_auth_token, authorization), None)
    return {"reset": "ok"}

@app.post("/act")
async def act(req: ActRequest,
              x_auth_token: str | None = Header(default=None),
              authorization: str | None = Header(default=None)):
    _enforce_auth(_pick_token_from_headers(x_auth_token, authorization), None)
    return await _act_core(req)

# ---------- path-token endpoints: /t/{token}/... ----------
@app.get("/t/{token}/card")
async def card_t(token: str):
    _enforce_auth(None, token)
    return JSONResponse(content=_card_payload())

@app.post("/t/{token}/reset")
async def reset_t(token: str):
    _enforce_auth(None, token)
    return {"reset": "ok"}

@app.post("/t/{token}/act")
async def act_t(token: str, req: ActRequest):
    _enforce_auth(None, token)
    return await _act_core(req)

# ---------- well-known endpoints (both header & path auth) ----------
@app.get("/.well-known/agent-card.json")
async def well_known_card_header(x_auth_token: str | None = Header(default=None),
                                 authorization: str | None = Header(default=None)):
    _enforce_auth(_pick_token_from_headers(x_auth_token, authorization), None)
    return JSONResponse(content=_card_payload())

@app.get("/t/{token}/.well-known/agent-card.json")
async def well_known_card_token(token: str):
    _enforce_auth(None, token)
    return JSONResponse(content=_card_payload())