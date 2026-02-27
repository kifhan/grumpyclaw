"""Device check endpoints for testing mic/speaker/camera (server-side)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from grumpyreachy.audio_test import run_robot_mic_test, run_robot_speaker_test

router = APIRouter(prefix="/devices", tags=["devices"])


def _get_mini(request: Request):
    """Get ReachyMini instance from the running robot app, or None."""
    robot = getattr(request.app.state.container, "robot", None)
    if not robot:
        return None
    app = robot.get_app()
    if not app or not getattr(app, "_controller", None):
        return None
    return getattr(app._controller, "_mini", None)


@router.get("/audio/status")
def devices_audio_status(request: Request) -> dict[str, object]:
    """Return whether the robot is connected and has a media API (for speaker/mic tests)."""
    mini = _get_mini(request)
    if mini is None:
        return {"available": False, "message": "Robot app not running or not connected"}
    media = getattr(mini, "media", None)
    if media is None:
        return {"available": False, "message": "Robot has no media API"}
    audio = getattr(media, "audio", None)
    status: dict[str, object] = {
        "available": True,
        "message": "Robot media available for speaker/mic tests",
    }

    if audio is not None:
        raw_input_id = getattr(audio, "_input_device_id", None)
        raw_output_id = getattr(audio, "_output_device_id", None)
        try:
            input_id = int(raw_input_id) if raw_input_id is not None else None
        except (TypeError, ValueError):
            input_id = None
        try:
            output_id = int(raw_output_id) if raw_output_id is not None else None
        except (TypeError, ValueError):
            output_id = None
        status["input_device_id"] = input_id
        status["output_device_id"] = output_id
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            if isinstance(input_id, int) and 0 <= input_id < len(devices):
                status["input_device_name"] = str(devices[input_id]["name"])
            if isinstance(output_id, int) and 0 <= output_id < len(devices):
                status["output_device_name"] = str(devices[output_id]["name"])
        except Exception:
            pass

    robot = getattr(request.app.state.container, "robot", None)
    app = robot.get_app() if robot else None
    if app and hasattr(app, "get_audio_device_status"):
        status["selection"] = app.get_audio_device_status()

    return status


@router.post("/audio/test-speaker")
def devices_audio_test_speaker(request: Request) -> dict[str, bool | str]:
    """Play a short test tone through the Reachy Mini's speaker."""
    mini = _get_mini(request)
    if mini is None:
        return {"ok": False, "error": "Robot app not running or not connected"}
    return run_robot_speaker_test(mini)


@router.post("/audio/test-mic")
def devices_audio_test_mic(request: Request) -> dict[str, bool | str | float]:
    """Record ~1s from the Reachy Mini's microphone and return level."""
    mini = _get_mini(request)
    if mini is None:
        return {"ok": False, "error": "Robot app not running or not connected"}
    return run_robot_mic_test(mini)


@router.get("/camera")
def devices_camera(request: Request) -> dict[str, str | bool]:
    """
    Check if the server-side camera (grumpyreachy CameraWorker) has a frame.
    Useful to verify the machine running the API can capture camera for the conversation app.
    """
    robot = getattr(request.app.state.container, "robot", None)
    app = robot.get_app() if robot else None
    if not app or not getattr(app, "_camera_worker", None):
        return {"ok": False, "message": "Robot app or camera worker not running"}
    worker = app._camera_worker
    frame = worker.get_latest_frame() if hasattr(worker, "get_latest_frame") else None
    if frame is None:
        return {"ok": False, "message": "No frame yet (camera may still be starting or not available)"}
    return {"ok": True, "message": "Camera frame available"}
