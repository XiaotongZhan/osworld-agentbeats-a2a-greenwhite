# white_sim/server.py
from __future__ import annotations

import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="White Agent Baseline")

# Counter for the toy baseline policy
_calls = 0


def _get_agent_url() -> str:
    """
    The `url` field used inside the agent card.

    - When running on AgentBeats:
        The controller may inject the real agent URL via the
        environment variable AGENT_URL, so we return that value.

    - Local debugging:
        When AGENT_URL is missing, return an empty string.
        (AgentBeats does not strictly require this field.)
    """
    return os.getenv("AGENT_URL", "")


def _build_agent_card() -> dict:
    """
    MCP / A2A agent card used by AgentBeats for discovery and display.
    """
    return {
        "capabilities": {},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "description": (
            "Baseline OSWorld white agent (scroll-then-wait toy policy)."
        ),
        "name": "osworld_white_baseline",
        "preferredTransport": "JSONRPC",
        # "preferredTransport": "HTTP",
        "protocolVersion": "0.3.0",
        "skills": [
            {
                "id": "osworld_white_actions",
                "name": "OSWorld White Policy",
                "description": (
                    "Receives OSWorld observations (via Green) and outputs "
                    "simple pyautogui-based actions."
                ),
                "tags": ["osworld", "white", "baseline"],
                "examples": [],
            }
        ],
        "url": _get_agent_url(),
        "version": "0.1.0",
    }


@app.get("/.well-known/agent-card.json")
def well_known_agent_card():
    """
    AgentBeats queries this endpoint to discover and describe the white agent.
    """
    return _build_agent_card()


# ---------------- A2A INTERFACE: keep the legacy endpoints /card /reset /act -----------------


@app.get("/card")
def card():
    """
    Legacy lightweight card used by locally run green agents or runner.py.
    """
    return {
        "name": "white-baseline",
        "version": "0.0.1",
        "policy": "baseline-scroll-then-wait",
    }


@app.post("/reset")
def reset():
    """
    Reset internal state before each new interaction round.
    """
    global _calls
    _calls = 0
    return {"reset": "ok"}


@app.post("/act")
def act(payload: dict):
    """
    Minimal baseline policy:

      Step 1: WAIT
      Step 2: SCROLL
      Step 3: WAIT
      Step 4+: DONE

    The green agent will repeatedly call this endpoint,
    passing OSWorld observations in `payload`, but this baseline
    ignores the observation and simply follows the fixed schedule above.
    """
    global _calls
    _calls += 1

    if _calls == 1:
        return JSONResponse(
            content={"type": "special", "name": "WAIT", "pause": 0.8}
        )

    if _calls == 2:
        return JSONResponse(
            content={
                "type": "code",
                "code": "import pyautogui; pyautogui.scroll(-400)",
                "pause": 0.5,
            }
        )

    if _calls == 3:
        return JSONResponse(
            content={"type": "special", "name": "WAIT", "pause": 0.5}
        )

    # Step 4 and onward — signal completion
    return JSONResponse(
        content={"type": "special", "name": "DONE", "pause": 0.0}
    )