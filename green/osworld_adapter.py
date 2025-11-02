# green/osworld_adapter.py
import sys
from pathlib import Path

# Ensure OSWorld is importable
_ROOT = Path(__file__).resolve().parents[1]
_OSWORLD_PATH = _ROOT / "third_party" / "osworld"
if str(_OSWORLD_PATH) not in sys.path:
    sys.path.insert(0, str(_OSWORLD_PATH))

import base64, io, os
from typing import Any, Dict, Optional, Tuple

from PIL import Image
try:
    import numpy as np  # optional
except Exception:
    np = None

from desktop_env.desktop_env import DesktopEnv


class OSWorldAdapter:
    """
    Thin wrapper over DesktopEnv that:
      - normalizes observations (screenshot -> base64, a11y_tree passthrough),
      - provides a stable API: reset(), step(), wait(), close().
    """

    def __init__(
        self,
        provider_name: str,
        os_type: str,
        region: str,
        client_password: str,
        screen_size: Tuple[int, int] = (1920, 1080),
    ):
        # Base kwargs passed to DesktopEnv
        kw = dict(
            provider_name=provider_name,
            os_type=os_type,
            action_space="pyautogui",
            headless=True,
            region=region,
            screen_size=screen_size,
            client_password=client_password,
            enable_proxy=False,        # hard-disable proxy to avoid proxy setup
            require_a11y_tree=False,   # screenshot-only by default
        )

        # Optional: resolve AWS snapshot/AMI from IMAGE_ID_MAP
        if provider_name.lower() == "aws":
            try:
                from desktop_env.providers.aws.manager import IMAGE_ID_MAP
                ami = IMAGE_ID_MAP[region].get(screen_size, IMAGE_ID_MAP[region].get((1920, 1080)))
                if ami:
                    kw["snapshot_name"] = ami
            except Exception:
                # Non-fatal; fall back to provider defaults
                pass

        self.env = DesktopEnv(**kw)

    # -------- public API --------
    def reset(self, task_config: Dict[str, Any]) -> Dict[str, Any]:
        obs = self.env.reset(task_config=task_config)
        if not obs:
            # fallback: attempt a short wait to obtain first frame
            obs, _, _, _ = self._wait(0.3)
        return self._encode_obs(obs)

    def step(self, action_code: str, pause: float = 0.5) -> Tuple[Dict[str, Any], float, bool, Dict[str, Any]]:
        """
        Execute a pyautogui code string in DesktopEnv and return encoded obs.
        """
        obs, reward, done, info = self.env.step(action_code, pause=pause)
        return self._encode_obs(obs), float(reward or 0.0), bool(done), info or {}

    # Backward-compatible alias if other code uses step_code()
    def step_code(self, action_code: str, pause: float = 0.5) -> Tuple[Dict[str, Any], float, bool, Dict[str, Any]]:
        return self.step(action_code, pause=pause)

    def wait(self, pause: float = 0.5) -> Tuple[Dict[str, Any], float, bool, Dict[str, Any]]:
        return self._wait(pause)

    def close(self) -> None:
        try:
            self.env.close()
        except Exception:
            pass

    # -------- helpers --------
    def _wait(self, pause: float) -> Tuple[Dict[str, Any], float, bool, Dict[str, Any]]:
        obs, reward, done, info = self.env.step("WAIT", pause=pause)
        return self._encode_obs(obs), float(reward or 0.0), bool(done), info or {}

    def _encode_obs(self, obs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(obs, dict):
            return {"screenshot_b64": None, "a11y_tree": None, "width": None, "height": None}

        a11y_tree = obs.get("a11y_tree") or obs.get("a11y") or None
        width = obs.get("width") or None
        height = obs.get("height") or None
        screenshot_b64 = self._b64_from_obs_image(obs)
        return {
            "screenshot_b64": screenshot_b64,
            "a11y_tree": a11y_tree,
            "width": width,
            "height": height,
        }

    def _b64_from_obs_image(self, obs: Dict[str, Any]) -> Optional[str]:
        # Try common keys in OSWorld observations
        for key in ("screenshot", "image", "frame", "rgb"):
            if key not in obs:
                continue
            img = obs[key]
            # Already bytes
            if isinstance(img, (bytes, bytearray)):
                return base64.b64encode(img).decode("ascii")
            # File path
            if isinstance(img, str) and os.path.isfile(img):
                with open(img, "rb") as f:
                    return base64.b64encode(f.read()).decode("ascii")
            # PIL.Image
            if isinstance(img, Image.Image):
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode("ascii")
            # numpy array
            if np is not None and isinstance(img, np.ndarray):
                pil = Image.fromarray(img)
                buf = io.BytesIO()
                pil.save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode("ascii")
        return None