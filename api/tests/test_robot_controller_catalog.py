from __future__ import annotations

from grumpyreachy.robot_controller import RobotController


class _Catalog:
    def __init__(self, names: list[str]):
        self._names = names

    def list_moves(self) -> list[str]:
        return list(self._names)


def test_robot_controller_get_motion_catalog_returns_names() -> None:
    controller = RobotController(mini=None)
    controller._builtin_motion_catalogs = {
        "emotions": _Catalog(["happy", "curious"]),
        "dances": _Catalog(["celebration"]),
    }
    controller._ensure_builtin_motions_loaded = lambda: True  # type: ignore[method-assign]

    catalog = controller.get_motion_catalog()

    assert catalog["available"] is True
    assert catalog["emotions"] == ["curious", "happy"]
    assert catalog["dances"] == ["celebration"]


def test_robot_controller_get_motion_catalog_returns_empty_when_unavailable() -> None:
    controller = RobotController(mini=None)
    controller._ensure_builtin_motions_loaded = lambda: False  # type: ignore[method-assign]

    assert controller.get_motion_catalog() == {"available": False, "emotions": [], "dances": []}
