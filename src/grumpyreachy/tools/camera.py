"""Capture the latest camera frame for vision analysis."""

from __future__ import annotations

import base64
from typing import Any

from grumpyreachy.tools.core_tools import Tool, ToolDependencies


class CameraTool(Tool):
    name = "camera"
    description = "Capture the latest camera frame and get a description (vision). Use when you need to see the environment."
    parameters_schema = {"type": "object", "properties": {}}

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        worker = deps.camera_worker
        if not worker or not hasattr(worker, "get_latest_frame"):
            return {"ok": False, "error": "Camera not available."}
        frame = worker.get_latest_frame()
        if frame is None:
            return {"ok": False, "error": "No frame captured yet."}
        # Return a simple description placeholder; Realtime API can receive image in session if configured
        if isinstance(frame, bytes):
            b64 = base64.standard_b64encode(frame).decode("ascii")
            return {"ok": True, "message": "Frame captured.", "image_base64": b64}
        return {"ok": True, "message": "Frame captured.", "description": str(frame)}
