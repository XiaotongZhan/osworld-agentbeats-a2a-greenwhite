# green/a2a_app.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard
from a2a.utils import new_agent_text_message

# IMPORTANT: import OSWorldSpec too (your schema requires region + task_config)
from .a2a_models import ActRequest, OSWorldSpec
from .app import _card_payload, _act_core, _choose_osworld_task


WHITE_URL_TAG_START = "<white_agent_url>"
WHITE_URL_TAG_END = "</white_agent_url>"

# This matches what you want "default" to mean:
# random sample 1 task from test_all, fixed seed, filter out gdrive.
DEFAULT_ENV_CONFIG: Dict[str, Any] = {
    "mode": "random",
    "slice": "test_all",
    "k": 1,
    "seed": 42,
    "nogdrive": True,
}


def _extract_white_agent_url(instruction: str) -> Optional[str]:
    """Extract <white_agent_url>...</white_agent_url>."""
    if not instruction:
        return None
    start = instruction.find(WHITE_URL_TAG_START)
    if start == -1:
        return None
    start += len(WHITE_URL_TAG_START)
    end = instruction.find(WHITE_URL_TAG_END, start)
    if end == -1:
        return None
    return instruction[start:end].strip() or None


def _safe_json_response_to_dict(resp: Any) -> Dict[str, Any]:
    """Parse fastapi JSONResponse (resp.body) or accept dict directly."""
    if resp is None:
        return {}
    if isinstance(resp, dict):
        return resp
    if hasattr(resp, "model_dump"):  # pydantic v2
        return resp.model_dump()
    if hasattr(resp, "dict"):  # pydantic v1
        return resp.dict()
    if hasattr(resp, "body"):
        try:
            return json.loads(resp.body.decode("utf-8"))
        except Exception:
            return {}
    return {}


class OSWorldGreenAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        A2A entrypoint.

        Fix:
          - ActRequest requires osworld.region + osworld.task_config.
          - We MUST choose a real OSWorld task_config here (via _choose_osworld_task),
            then build OSWorldSpec and ActRequest.
        """
        instruction = context.get_user_input() or ""

        # Parse white agent URL from instruction (platform already provides it)
        white_agent_url = _extract_white_agent_url(instruction)
        if not white_agent_url:
            raise ValueError(
                "Missing <white_agent_url>...</white_agent_url> in instruction. "
                "Please ensure the AgentBeats prompt includes it."
            )

        # Pick AWS region (required by your OSWorldSpec schema)
        region = os.getenv("AWS_REGION")
        if not region:
            raise RuntimeError("AWS_REGION is not set, but OSWorldSpec.region is required.")

        # Build env_cfg for random selection; also include white url so _act_core can use it if needed
        env_cfg = dict(DEFAULT_ENV_CONFIG)
        env_cfg["white_agent_url"] = white_agent_url

        # Choose ONE concrete OSWorld task_config dict
        chosen_task_id, task_config = _choose_osworld_task(env_cfg)

        # Use the assessment/task id from A2A context if available, else use chosen task id
        assess_id = getattr(context, "task_id", None) or chosen_task_id

        osworld = OSWorldSpec(
            region=region,
            task_config=task_config,
            # screen_width/height have defaults in OSWorldSpec, no need to set
            # provider_name/os_type also have defaults
        )

        act_req = ActRequest(
            task_id=str(assess_id),
            instruction=instruction,
            osworld=osworld,
            # limits has default, seed optional
        )

        # Run your original evaluation core
        resp = await _act_core(act_req)
        payload = _safe_json_response_to_dict(resp)

        success = bool(payload.get("success", False))
        reward = float(payload.get("reward", 0.0) or 0.0)
        steps = payload.get("steps")
        wall_time_sec = payload.get("wall_time_sec")

        result_emoji = "✅" if success else "❌"
        summary = (
            "OSWorld Green: assessment finished.\n"
            f"Result: {result_emoji} (reward={reward}).\n"
            f"task_id={payload.get('task_id', act_req.task_id)} steps={steps} wall_time_sec={wall_time_sec}"
        )

        await event_queue.enqueue_event(new_agent_text_message(summary))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


def _build_agent_card() -> AgentCard:
    """
    Reuse _card_payload() but filter to AgentCard-recognized fields.
    """
    raw = _card_payload()
    allowed_keys = {
        "name",
        "description",
        "version",
        "defaultInputModes",
        "defaultOutputModes",
        "capabilities",
        "skills",
        "url",
    }
    card_dict = {k: v for k, v in raw.items() if k in allowed_keys}

    # Ensure url exists: prefer AGENT_URL (injected by controller)
    if not card_dict.get("url"):
        agent_url = os.getenv("AGENT_URL")
        if agent_url:
            card_dict["url"] = agent_url

    return AgentCard(**card_dict)


_request_handler = DefaultRequestHandler(
    agent_executor=OSWorldGreenAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

_a2a_app = A2AStarletteApplication(
    agent_card=_build_agent_card(),
    http_handler=_request_handler,
)

app = _a2a_app.build()