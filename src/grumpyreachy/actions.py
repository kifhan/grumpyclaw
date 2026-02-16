"""Action definitions executed by the grumpyreachy control worker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ControlAction:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
