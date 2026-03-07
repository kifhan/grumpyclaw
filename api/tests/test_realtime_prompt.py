from __future__ import annotations

from api.backend.assistant.manager import _realtime_prompt


def test_realtime_prompt_includes_brevity_persona_motion_and_safety_rules() -> None:
    prompt = _realtime_prompt()

    assert "You are GrumpyClaw, a realtime robot assistant with a unique playful-scout personality" in prompt
    assert "speak naturally in 1-2 sentences" in prompt
    assert "Use robot_action for expression frequently and contextually." in prompt
    assert "always include a valid non-empty action enum value" in prompt
    assert "prefer play_emotion as the primary expressive action" in prompt
    assert "Use dance for celebratory/high-energy moments, not neutral turns." in prompt
    assert "Avoid repeating the exact same motion pattern in consecutive turns" in prompt
    assert "call capture_camera_context before making claims about what you can see" in prompt
    assert "call save_memory" in prompt
    assert "call search_memory" in prompt
    assert "Do not store secrets or credentials in memory." in prompt


def test_realtime_prompt_lists_required_tool_names() -> None:
    prompt = _realtime_prompt()
    for tool_name in (
        "play_emotion",
        "stop_emotion",
        "dance",
        "stop_dance",
        "capture_camera_context",
        "save_memory",
        "search_memory",
    ):
        assert tool_name in prompt


def test_realtime_prompt_includes_curated_and_available_motion_names() -> None:
    prompt = _realtime_prompt(
        {
            "available": True,
            "emotions": ["happy", "curious_mode"],
            "dances": ["celebration"],
        }
    )

    assert "Accepted robot_action.action values:" in prompt
    assert "Curated emotion labels for intent matching: happy, sad, curious, angry, neutral, excited." in prompt
    assert "Installed motion catalog is available at runtime." in prompt
    assert "Installed play_emotion names (exact name values): curious_mode, happy." in prompt
    assert "Installed dance names (exact name values): celebration." in prompt
