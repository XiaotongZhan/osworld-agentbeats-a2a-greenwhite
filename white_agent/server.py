from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional, List

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from white_agent.policy.qwen3vl_policy import Qwen3VLAgent

app = FastAPI(title="White Agent (Qwen3VL)")

logging.basicConfig(level=os.getenv("WHITE_LOG_LEVEL", "INFO"))
logger = logging.getLogger("white_agent")

_agent: Optional[Qwen3VLAgent] = None


def _get_agent_url() -> str:
    # Controller may inject this (AgentBeats)
    return os.getenv("AGENT_URL", "")


def _build_agent_card() -> dict:
    # model = os.getenv("OSWORLD_VL_MODEL", "qwen3-vl")
    backend = os.getenv("OSWORLD_API_BACKEND", "dashscope")
    return {
        "capabilities": {},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "description": "OSWorld White agent powered by Qwen3-VL (DashScope) that outputs pyautogui actions.",
        "name": "osworld_white_qwen3vl",
        "preferredTransport": "JSONRPC",
        "protocolVersion": "0.3.0",
        "skills": [
            {
                "id": "osworld_white_actions",
                "name": "OSWorld White Policy (Qwen3VL)",
                "description": "Receives OSWorld observations (via Green) and outputs pyautogui-based actions.",
                "tags": ["osworld", "white", "qwen3vl", backend],
                "examples": [],
            }
        ],
        "url": _get_agent_url(),
        "version": "0.1.0",
        # "model": model,
    }


def _ensure_agent() -> Qwen3VLAgent:
    global _agent
    if _agent is None:
        model = os.getenv("OSWORLD_VL_MODEL", "qwen3-vl")
        backend = os.getenv("OSWORLD_API_BACKEND", "dashscope")
        platform = os.getenv("OSWORLD_PLATFORM", "ubuntu")
        coordinate_type = os.getenv("WHITE_COORDINATE_TYPE", "relative")

        _agent = Qwen3VLAgent(
            platform=platform,
            model=model,
            api_backend=backend,
            coordinate_type=coordinate_type,
        )
        _agent.reset(logger)
        logger.info(f"[white] policy init backend={backend} model={model} coord={coordinate_type}")
    return _agent


def _codes_to_action(codes: List[str]) -> Dict[str, Any]:
    up = [(c or "").strip().upper() for c in (codes or []) if isinstance(c, str)]

    # Priority: DONE/FAIL > WAIT > code
    if "DONE" in up:
        return {"type": "special", "name": "DONE", "pause": 0.0}
    if "FAIL" in up:
        return {"type": "special", "name": "FAIL", "pause": 0.0}
    if (not up) or ("WAIT" in up):
        return {
            "type": "special",
            "name": "WAIT",
            "pause": float(os.getenv("WHITE_WAIT_PAUSE", "0.8")),
        }

    lines = [c for c in (codes or []) if isinstance(c, str) and c.strip() and c.strip().upper() not in ("WAIT", "DONE", "FAIL")]
    if not lines:
        return {
            "type": "special",
            "name": "WAIT",
            "pause": float(os.getenv("WHITE_WAIT_PAUSE", "0.8")),
        }

    pause = float(os.getenv("WHITE_ACTION_PAUSE", "0.5"))
    # DesktopEnv expects a python snippet. Keep it robust.
    code = "import pyautogui; " + "; ".join(lines)
    return {"type": "code", "code": code, "pause": pause}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/.well-known/agent-card.json")
def well_known_agent_card():
    return _build_agent_card()


@app.get("/card")
def card():
    # legacy lightweight info for local debugging
    return {
        "name": "white-qwen3vl",
        "version": "0.1.0",
        "backend": os.getenv("OSWORLD_API_BACKEND", "dashscope"),
        "model": os.getenv("OSWORLD_VL_MODEL", "qwen3-vl"),
    }


@app.post("/reset")
def reset():
    agent = _ensure_agent()
    agent.reset(logger)
    return {"reset": "ok"}


@app.post("/act")
def act(payload: dict):
    agent = _ensure_agent()

    instruction = (payload.get("instruction") or "").strip()
    obs = payload.get("observation") or {}

    # Green sends screenshot_b64
    b64 = obs.get("screenshot_b64") or obs.get("screenshot") or None

    # If no instruction or no screenshot, safest fallback is WAIT (won't crash)
    if not instruction or not b64:
        return JSONResponse(content=_codes_to_action(["WAIT"]))

    try:
        screenshot = base64.b64decode(b64)
    except Exception as e:
        logger.warning(f"[white] bad screenshot_b64 decode: {e}")
        return JSONResponse(content=_codes_to_action(["WAIT"]))

    try:
        # Qwen3VLAgent expects {"screenshot": <bytes>}
        _resp, codes = agent.predict(instruction, {"screenshot": screenshot})
        return JSONResponse(content=_codes_to_action(codes))
    except Exception as e:
        logger.exception(f"[white] policy predict error: {e}")
        return JSONResponse(content=_codes_to_action(["WAIT"]))
