# green/result_writer.py
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, List, TextIO


def _iso_utc(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


class ResultWriter:
    """
    Utilities for writing a single run's artifacts:
      - frames/step_XXX.png
      - trace.jsonl  (append-only event stream)
      - result.json  (final structured result)
      - summary.json (lightweight header+tail info)
      - artifact.json (index of key outputs; optional via artifact())

    Backward compatible with previous usage.
    """

    def __init__(self, root: Path):
        self.root: Path = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

        self.frames: Path = self.root / "frames"
        self.frames.mkdir(exist_ok=True)

        self.trace_path: Path = self.root / "trace.jsonl"
        self._trace: TextIO = open(self.trace_path, "a", encoding="utf-8")

        # Book-keeping
        self._frames: List[Path] = []
        self.result_path: Path = self.root / "result.json"
        self.summary_path: Path = self.root / "summary.json"
        self.artifact_path: Path = self.root / "artifact.json"

        # Optional context fields; caller may set later
        self.task_id: Optional[str] = None
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None

    # ----------- frame / trace -----------

    def save_frame(self, step_idx: int, screenshot_b64: Optional[str]) -> Optional[Path]:
        """
        Save a PNG frame from base64 string; returns the saved path or None.
        """
        if not screenshot_b64:
            return None
        p = self.frames / f"step_{step_idx:03d}.png"
        try:
            raw = base64.b64decode(screenshot_b64)
            with open(p, "wb") as f:
                f.write(raw)
            self._frames.append(p)
            return p
        except Exception:
            return None

    def log_step(self, t: int, action: Dict[str, Any], result: Dict[str, Any]) -> None:
        """
        Append a single step record into trace.jsonl.
        """
        rec = {"t": t, "action": action, "result": result, "timestamp": time.time()}
        self._trace.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._trace.flush()

    # ----------- structured outputs -----------

    def write_result(self, payload: Dict[str, Any]) -> Path:
        """
        Write final result.json (overwrites); returns the path.
        """
        with open(self.result_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return self.result_path

    def write_summary(self, summary: Dict[str, Any]) -> Path:
        """
        Write summary.json (overwrites); returns the path.
        """
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        return self.summary_path

    # ----------- artifact index (AgentBeats-friendly) -----------

    def artifact(
        self,
        *,
        task_id: Optional[str] = None,
        started_at: Optional[float] = None,
        finished_at: Optional[float] = None,
    ) -> Path:
        """
        Generate artifact.json that indexes the run outputs.
        Safe to call multiple times (idempotent overwrite).
        Returns the artifact.json path.

        Fields:
          - task_id, run_dir
          - result_json, trace_jsonl
          - frames: [list of PNG paths]
          - started_at, finished_at (ISO8601 UTC)
        """
        # Prefer explicitly passed values; else fall back to stored ones; else now.
        tid = task_id or self.task_id or ""
        start_ts = started_at if started_at is not None else (self.started_at or time.time())
        end_ts = finished_at if finished_at is not None else (self.finished_at or time.time())

        # If frames list is empty (e.g., writer reloaded), glob as fallback.
        frames = self._frames
        if not frames:
            frames = sorted(self.frames.glob("*.png"))

        payload = {
            "task_id": tid,
            "run_dir": str(self.root),
            "result_json": str(self.result_path),
            "trace_jsonl": str(self.trace_path),
            "frames": [str(p) for p in frames],
            "started_at": _iso_utc(start_ts),
            "finished_at": _iso_utc(end_ts),
        }
        with open(self.artifact_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return self.artifact_path

    # ----------- lifecycle -----------

    def close(self) -> None:
        try:
            self._trace.close()
        except Exception:
            pass

    # Optional context manager support
    def __enter__(self) -> "ResultWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()