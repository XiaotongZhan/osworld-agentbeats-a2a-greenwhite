import asyncio, os, time, uuid, re, json, random
from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256
from typing import Any, Dict, Tuple, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Request
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
    f"http://127.0.0.1:{os.getenv('WHITE_PORT', '18081')}",
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
        # Symlink failure should not kill the run.
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
def _pick_token_from_headers(x_auth_token: Optional[str], authorization: Optional[str]) -> Optional[str]:
    """Accept X-Auth-Token or Authorization: Bearer <token>."""
    if x_auth_token:
        return x_auth_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _enforce_auth(header_token: Optional[str] = None, path_token: Optional[str] = None) -> None:
    """Enforce auth unless disabled by GREEN_REQUIRE_AUTH=false."""
    if not REQUIRE_AUTH:
        return
    if not GREEN_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="auth-required-but-token-missing")
    supplied = (header_token or path_token or "").strip()
    if supplied != GREEN_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


# ---------------- card & signature helpers ----------------
def _get_agent_url() -> str:
    """
    The `url` field used inside the agent card.

    - When running under AgentBeats controller:
        The controller injects AGENT_URL with the externally visible URL
        (typically http://HOST:PORT/to_agent/<cagent_id>), so we return
        that value unchanged.

    - Local debugging:
        When AGENT_URL is missing, return an empty string. AgentBeats does
        not strictly require this field for local tests.
    """
    return os.getenv("AGENT_URL", "")


def _agent_version() -> str:
    try:
        return CardResponse().version
    except Exception:
        return "0.1.0"


def _card_payload() -> Dict[str, Any]:
    """
    Return the MCP-style agent card that AgentBeats v2 expects.

    This follows the MCP Agent Card schema (protocolVersion 0.3.0)
    and describes this service as an OSWorld Green assessment host.
    """
    return {
        "capabilities": {
            "streaming": False
        },
        "defaultInputModes": [
            "text"
        ],
        "defaultOutputModes": [
            "text"
        ],
        "description": (
            "OSWorld desktop benchmark 'Green' assessor agent. "
            "It hosts the OSWorld GUI environment and evaluates assessee agents "
            "via the A2A protocol."
        ),
        "name": "osworld_green_agent_mcp",
        # "preferredTransport": "JSONRPC",
        "preferredTransport": "HTTP",
        "protocolVersion": "0.3.0",
        "skills": [
            {
                "id": "host_assess_osworld_green",
                "name": "OSWorld-Green assessment hosting",
                "description": (
                    "Host and run OSWorld desktop tasks to evaluate assessee agents' "
                    "GUI control and tool-use capabilities."
                ),
                "tags": [
                    "green agent",
                    "assessment hosting",
                    "osworld",
                    "desktop",
                ],
                "examples": [
                    (
                        "Your task is to instantiate the OSWorld-Green benchmark to "
                        "test the agent located at:\n"
                        "<white_agent_url>\n"
                        "http://localhost:9004/\n"
                        "</white_agent_url>\n\n"
                        "You should use the following environment configuration:\n"
                        "<env_config>\n"
                        "{\n"
                        "  \"task_suite\": \"test_small\"\n"
                        "}\n"
                        "</env_config>\n"
                    )
                ],
            }
        ],
        "url": _get_agent_url(),
        "version": _agent_version(),
    }


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_env_signature(backend_mode: str, region: str, screen_w: int, screen_h: int) -> str:
    """
    Deterministic environment signature so the platform can deduplicate / bucket results.
    Components: backend_mode, region, screen, python_version, agent_version.
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


def _write_artifact_json(
    run_dir: Path,
    task_id: str,
    started_at: float,
    finished_at: float,
) -> str:
    """
    Write artifact.json listing the core artifacts for this run, and
    return its file path as a string.
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


# -------- env_config & white_agent_url parsing --------
def _parse_white_url_from_instruction(instruction: Optional[str]) -> Optional[str]:
    """Extract <white_agent_url>...</white_agent_url> from the instruction, if present."""
    if not instruction:
        return None
    m = re.search(r"<white_agent_url>\\s*(.*?)\\s*</white_agent_url>", instruction, re.DOTALL)
    if not m:
        return None
    url = m.group(1).strip()
    return url or None


def _parse_env_config_from_instruction(instruction: Optional[str]) -> Dict[str, Any]:
    """
    Parse an optional <env_config>{...}</env_config> JSON blob from
    the instruction text. Returns {} if not present or invalid.
    """
    if not instruction:
        return {}
    m = re.search(r"<env_config>\\s*(\\{.*?\\})\\s*</env_config>", instruction, re.DOTALL)
    if not m:
        return {}
    raw = m.group(1)
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"[warn] Failed to parse <env_config>: {e}")
        return {}


def _choose_osworld_task(env_cfg: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Map env_config into a single OSWorld task_config.

    Supports:
      1) direct:
         - env_cfg["task_config"] is a dict

      2) random:
         - mode="random"
         - slice="test_all"/"test_small"/...
         - reads OSWorld meta JSON from third_party/osworld/evaluation_examples/<slice>.json

    OSWorld meta file format is typically:
      - dict: { "<domain>": ["<example_id>", ...], ... }
    """
    # ---- direct task_config ----
    direct_cfg = env_cfg.get("task_config")
    if isinstance(direct_cfg, dict):
        tid = env_cfg.get("task_id") or direct_cfg.get("task_id") or "osworld_task"
        return str(tid), direct_cfg

    mode = env_cfg.get("mode", "single")
    if mode != "random":
        raise RuntimeError(
            "env_config must contain either a 'task_config' dict or mode='random'. "
            f"Got mode={mode!r}"
        )

    EVAL_ROOT = ROOT / "third_party" / "osworld" / "evaluation_examples"

    slice_name = env_cfg.get("slice", "test_all")
    meta_path = env_cfg.get("meta_path") or (EVAL_ROOT / f"{slice_name}.json")
    meta_path = Path(meta_path)

    if not meta_path.is_file():
        raise RuntimeError(f"OSWorld meta file not found: {meta_path}")

    with meta_path.open("r", encoding="utf-8") as f:
        meta = json.load(f)

    # ---- build candidates from meta ----
    candidates: list[tuple[str, str]] = []

    if isinstance(meta, dict):
        # OSWorld standard format: domain -> [ids]
        for domain, ids in meta.items():
            if not isinstance(ids, list):
                continue
            for ex_id in ids:
                if isinstance(ex_id, str) and ex_id.strip():
                    candidates.append((str(domain), ex_id.strip()))
    elif isinstance(meta, list):
        # fallback (non-standard) format: list of items containing domain/id or config_path
        # we try to interpret it best-effort
        for item in meta:
            if not isinstance(item, dict):
                continue
            domain = item.get("domain")
            ex_id = item.get("id") or item.get("example_id")
            if isinstance(domain, str) and isinstance(ex_id, str):
                candidates.append((domain.strip(), ex_id.strip()))
    else:
        raise RuntimeError(f"Invalid meta json format (expect dict or list): {meta_path}")

    if not candidates:
        raise RuntimeError(f"Invalid or empty meta file: {meta_path}")

    # ---- optional nogdrive filter (best-effort) ----
    nogdrive = bool(env_cfg.get("nogdrive"))
    if nogdrive:
        # OSWorld examples are not always "gdrive"; keep this lightweight.
        filtered = []
        for domain, ex_id in candidates:
            text = f"{domain}/{ex_id}".lower()
            if "gdrive" in text or "google_drive" in text or "google-drive" in text:
                continue
            filtered.append((domain, ex_id))
        if filtered:
            candidates = filtered

    # ---- sample one ----
    seed = env_cfg.get("seed")
    rng = random.Random(seed)
    domain, ex_id = rng.choice(candidates)

    # ---- load concrete task config ----
    cfg_path = EVAL_ROOT / "examples" / domain / f"{ex_id}.json"
    if not cfg_path.is_file():
        raise RuntimeError(f"Task config JSON not found: {cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as f:
        task_cfg = json.load(f)

    # task id for logging
    task_id = env_cfg.get("task_id") or task_cfg.get("task_id") or f"{domain}__{ex_id}"
    return str(task_id), task_cfg



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

    # Parse optional env_config + white_agent_url from instruction
    instruction = getattr(req, "instruction", "")
    env_cfg = _parse_env_config_from_instruction(instruction)

    white_url = (
        env_cfg.get("white_agent_url")
        or env_cfg.get("white_url")
        or _parse_white_url_from_instruction(instruction)
        or WHITE_AGENT_URL
    )

    # Decide which OSWorld task to run.
    osworld_cfg = getattr(req, "osworld", None)
    task_config = getattr(osworld_cfg, "task_config", None) if osworld_cfg is not None else None
    task_id: str
    if isinstance(task_config, dict):
        # ActRequest already carries a task_config (e.g. from Earthshaker OSWorld plugin).
        task_id = (
            getattr(req, "task_id", None)
            or task_config.get("task_id")
            or task_config.get("name")
            or "osworld_task"
        )
    else:
        # Fall back to env_config-based selection (random or direct task_config)
        if not env_cfg:
            raise HTTPException(
                status_code=400,
                detail="No OSWorld task_config provided and <env_config> is missing.",
            )
        task_id, task_config = _choose_osworld_task(env_cfg)

    assess_id = getattr(req, "task_id", None) or task_id or str(uuid.uuid4())
    run_dir = _make_run_dir(assess_id)
    writer = ResultWriter(run_dir)

    # Basic geometry (used for env + metadata)
    screen_w = getattr(osworld_cfg, "screen_width", 1920) if osworld_cfg is not None else 1920
    screen_h = getattr(osworld_cfg, "screen_height", 1080) if osworld_cfg is not None else 1080

    header = {
        "task_id": assess_id,
        "region": os.getenv("AWS_REGION", "<unset>"),
        "white_agent": white_url,
        "provider": getattr(osworld_cfg, "provider_name", None) if osworld_cfg is not None else None,
        "screen": [screen_w, screen_h],
        "env_config": env_cfg,
    }
    writer.write_summary({"start": header})

    white = WhiteAgentClient(white_url)
    env = None
    steps = 0
    t0 = time.time()
    reward_final = 0.0
    done = False

    region = os.getenv("AWS_REGION", "<unset>")
    agent_ver = _agent_version()
    env_sig = _make_env_signature(mode, region, screen_w, screen_h)
    seed_val = getattr(req, "seed", None)

    try:
        # Optional white reset (best-effort)
        try:
            await white.reset()
        except Exception:
            pass

        # Bring up OSWorld
        env = OSWorldAdapter(
            provider_name=getattr(osworld_cfg, "provider_name", None) if osworld_cfg is not None else None,
            os_type=getattr(osworld_cfg, "os_type", None) if osworld_cfg is not None else None,
            region=getattr(osworld_cfg, "region", None) if osworld_cfg is not None else None,
            screen_size=(screen_w, screen_h),
            client_password=OSWORLD_CLIENT_PASSWORD,
        )

        # Reset in background thread
        obs = await run_in_thread(env.reset, task_config)
        writer.save_frame(steps, obs.get("screenshot_b64"))

        # Limits for this run
        limits = getattr(req, "limits", None)
        max_steps = getattr(limits, "max_steps", 50) if limits is not None else 50
        max_seconds = getattr(limits, "max_seconds", 300.0) if limits is not None else 300.0

        # Main loop
        while steps < max_steps and (time.time() - t0) < max_seconds and not done:
            steps += 1

            observation = Observation(
                screenshot_b64=obs.get("screenshot_b64"),
                a11y_tree=obs.get("a11y_tree"),
                width=obs.get("width"),
                height=obs.get("height"),
            )

            try:
                action = await white.act(instruction, observation, steps)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"White /act error: {e}")

            if action.type == "special":
                name = (action.name or "").upper()
                if name == "WAIT":
                    obs, reward, done, info = await run_in_thread(
                        env.wait, action.pause or 0.5
                    )
                elif name in ("DONE", "FAIL"):
                    done = True
                    reward = 0.0
                    info = {"terminated_by": name}
                else:
                    obs, reward, done, info = await run_in_thread(env.wait, 0.5)
            elif action.type == "code" and action.code:
                obs, reward, done, info = await run_in_thread(
                    env.step, action.code, action.pause or 0.5
                )
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

        # Build ActResult
        result = ActResult(
            task_id=assess_id,
            success=(reward_final > 0.0),
            reward=reward_final,
            steps=steps,
            wall_time_sec=wall,
            logs_dir=str(run_dir),
            details={
                "limits": limits.model_dump() if limits is not None else None,
                "provider": getattr(osworld_cfg, "provider_name", None) if osworld_cfg is not None else None,
                "backend": "python-api",
                "seed": seed_val,
                "agent_version": agent_ver,
                "env_signature": env_sig,
                "env_config": env_cfg,
            },
        )
        writer.write_result(result.model_dump())

        artifact_path = _write_artifact_json(run_dir, assess_id, t0, time.time())
        result.details["artifact_index"] = artifact_path

        writer.write_summary({"start": header, "end": result.model_dump()})
        return JSONResponse(content=result.model_dump())

    except Exception as e:
        wall = max(0.0, time.time() - t0)
        failure_type = _classify_failure(e)

        limits = getattr(req, "limits", None)

        result = ActResult(
            task_id=assess_id,
            success=False,
            reward=0.0,
            steps=steps,
            wall_time_sec=wall,
            logs_dir=str(run_dir),
            details={
                "limits": limits.model_dump() if limits is not None else None,
                "provider": getattr(osworld_cfg, "provider_name", None) if osworld_cfg is not None else None,
                "backend": "python-api",
                "failure_type": failure_type,
                "message": str(e),
                "seed": seed_val,
                "agent_version": _agent_version(),
                "env_signature": _make_env_signature(
                    mode, os.getenv("AWS_REGION", "<unset>"), screen_w, screen_h
                ),
                "env_config": env_cfg,
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
async def card(
    x_auth_token: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _enforce_auth(_pick_token_from_headers(x_auth_token, authorization), None)
    return JSONResponse(content=_card_payload())


@app.post("/reset")
async def reset(
    x_auth_token: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    _enforce_auth(_pick_token_from_headers(x_auth_token, authorization), None)
    return {"reset": "ok"}


@app.post("/act")
async def act(
    req: ActRequest,
    x_auth_token: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
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

@app.post("/", include_in_schema=False)
async def a2a_jsonrpc_root(
    request: Request,
    x_auth_token: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """
    A2A JSON-RPC entrypoint.

    The AgentBeats controller sends JSON-RPC requests to this path:
      - method = "card"  -> query the agent card
      - method = "reset" -> reset the agent runtime state
      - method = "act"   -> ask the Green agent to run one OSWorld evaluation

    This handler simply forwards these JSON-RPC methods to the existing
    HTTP-based handler logic.
    """
    # Apply the same authentication logic as /card, /reset, and /act
    _enforce_auth(_pick_token_from_headers(x_auth_token, authorization), None)

    payload = await request.json()
    method = payload.get("method")
    params = payload.get("params") or {}
    rpc_id = payload.get("id")
    rpc_version = payload.get("jsonrpc", "2.0")

    # ---- 1. card ----
    if method == "card":
        # Reuse the internal agent card payload construction logic
        result_obj = _card_payload()

    # ---- 2. reset ----
    elif method == "reset":
        # Reuse the existing /reset route logic
        # (authentication will be checked again, which is harmless)
        result_obj = await reset(
            x_auth_token=x_auth_token,
            authorization=authorization,
        )

    # ---- 3. act ----
    elif method == "act":
        # `params` may either directly contain ActRequest fields,
        # or be wrapped as {"request": {...}}. Support both formats.
        if isinstance(params, dict) and "request" in params:
            act_payload = params["request"]
        else:
            act_payload = params

        # Validate and construct ActRequest
        act_req = ActRequest.model_validate(act_payload)

        # Invoke the existing core logic (returns a JSONResponse)
        resp: JSONResponse = await _act_core(act_req)

        # Extract the actual JSON content from the JSONResponse
        try:
            result_obj = json.loads(resp.body.decode("utf-8"))
        except Exception:
            # In theory resp.body should always exist; this is a defensive fallback
            rendered = resp.render()
            result_obj = json.loads(rendered.decode("utf-8"))

    else:
        # AgentBeats should only send card/reset/act.
        # This branch is a defensive fallback.
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported JSON-RPC method: {method!r}",
        )

    # Return a JSON-RPC 2.0 compliant response
    return JSONResponse(
        content={
            "jsonrpc": rpc_version,
            "id": rpc_id,
            "result": result_obj,
        }
    )

# ---------- well-known endpoints (PUBLIC for AgentBeats) ----------
@app.get("/.well-known/agent-card.json", include_in_schema=False)
async def well_known_card_public():
    """
    Public agent card endpoint required by AgentBeats controller/platform.
    This MUST NOT require authentication, so the controller can fetch it anonymously.
    """
    return JSONResponse(content=_card_payload())


@app.get("/t/{token}/.well-known/agent-card.json", include_in_schema=False)
async def well_known_card_public_token(token: str):
    """
    Public variant of the well-known card under /t/{token}/.
    Token is kept in the path only for backward compatibility, but no auth is enforced.
    """
    return JSONResponse(content=_card_payload())