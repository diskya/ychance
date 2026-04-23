from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Mapping


action_schema_version = 1
ALLOWED_SIDES = frozenset({"long", "short", "cash"})


@dataclass(frozen=True)
class Action:
    side: Literal["long", "short", "cash"]
    size_multiplier: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "size_multiplier": self.size_multiplier,
        }


def load_action(body: Mapping[str, Any]) -> Action:
    if not isinstance(body, Mapping):
        raise TypeError("action must be a mapping")
    keys = frozenset({"side", "size_multiplier"})
    extra = set(body.keys()) - keys
    missing = keys - set(body.keys())
    if extra or missing:
        raise ValueError(
            "action must contain exactly ['side', 'size_multiplier']; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    side = body["side"]
    if side not in ALLOWED_SIDES:
        raise ValueError("action.side is not allowed")
    raw_multiplier = body["size_multiplier"]
    if not isinstance(raw_multiplier, (int, float)):
        raise ValueError("action.size_multiplier must be numeric")
    size_multiplier = float(raw_multiplier)
    if not math.isfinite(size_multiplier) or size_multiplier < 0:
        raise ValueError("action.size_multiplier must be finite and >= 0")
    return Action(side=side, size_multiplier=size_multiplier)
