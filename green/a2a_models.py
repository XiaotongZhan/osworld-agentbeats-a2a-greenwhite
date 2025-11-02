# green/a2a_models.py
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class CardResponse(BaseModel):
    name: str = "OSWorld-Green"
    version: str = "0.1.0"
    protocol: str = "a2a/0.1"
    tools: List[str] = ["mouse", "keyboard", "scroll", "wait"]
    task_sets: List[str] = ["test_small", "test_all", "verified_small", "verified_all"]
    backend: str = "python-api-no-http"  # explicitly not using OSWorld HTTP control

class ActLimits(BaseModel):
    max_steps: int = 100
    max_seconds: int = 300

class OSWorldSpec(BaseModel):
    provider_name: str = "aws"
    os_type: str = "Ubuntu"
    region: str
    screen_width: int = 1920
    screen_height: int = 1080
    task_config: Dict[str, Any]

class ActRequest(BaseModel):
    task_id: str
    instruction: str
    seed: Optional[int] = None
    limits: ActLimits = ActLimits()
    osworld: OSWorldSpec

class Observation(BaseModel):
    screenshot_b64: Optional[str] = None
    a11y_tree: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None

class WhiteAgentAction(BaseModel):
    # "code" -> pyautogui code string
    # "special" -> WAIT | DONE | FAIL
    type: str
    code: Optional[str] = None
    name: Optional[str] = None
    pause: float = 0.5

class ActResult(BaseModel):
    task_id: str
    success: bool
    reward: float
    steps: int
    wall_time_sec: float
    logs_dir: Optional[str] = None
    details: Dict[str, Any] = {}