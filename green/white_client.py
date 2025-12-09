# green/white_client.py
import os
from typing import Dict, Any
import httpx

from .a2a_models import Observation, WhiteAgentAction

class WhiteAgentClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def card(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{self.base_url}/card")
            r.raise_for_status()
            return r.json()

    async def reset(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{self.base_url}/reset", json={})
            r.raise_for_status()
            return r.json()

    async def act(self, instruction: str, observation: Observation, step_idx: int) -> WhiteAgentAction:
        payload = {
            "instruction": instruction,
            "observation": observation.model_dump(),
            "tools": ["mouse", "keyboard", "scroll", "wait"],
            "step": step_idx
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(f"{self.base_url}/act", json=payload)
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, dict) or "type" not in data:
            return WhiteAgentAction(type="special", name="DONE", pause=0.5)
        return WhiteAgentAction(**data)
