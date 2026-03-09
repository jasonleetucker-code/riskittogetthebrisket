from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MasterPlayer:
    player_id: str
    display_name: str
    normalized_name: str
    position_family: str = ""
    team: str = ""
    sleeper_id: str = ""
    aliases: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["aliases"] = sorted(self.aliases)
        return d


@dataclass
class MasterPick:
    pick_id: str
    label: str
    year: int
    round: int
    slot: str = ""  # 1.01 or EARLY/MID/LATE
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

