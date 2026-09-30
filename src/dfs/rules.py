"""DFS contest rule sets and the platform × sport × format capability matrix.

ONE owner for "what does a legal lineup look like on this platform".  The data
lives in ``config/dfs/rulesets.json``; this module validates it, exposes typed
views, and derives a readiness level per capability.  There is deliberately no
global ``supports_dfs`` flag: readiness is per platform × sport × format × rule
version.

Readiness levels (closed vocabulary):

* ``not_implemented`` — no rule set is encoded; nothing may be built.
* ``research_only``   — a rule set is encoded but NOT verified against official
  evidence.  Builds run and are labelled research-only; exports are labelled
  unverified.  Money-ready optimization fails closed (``RULESET_UNVERIFIED``).
* ``money_ready``     — rule set AND export format verified.

A remembered platform setting is never promoted to ``verified`` by this module;
only a config edit that records official evidence can do that.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
RULESETS_PATH = REPO / "config" / "dfs" / "rulesets.json"

PLATFORMS = ("draftkings", "fanduel")
SPORTS = ("nfl", "nba", "nhl", "mma")
VERIFICATION_STATES = ("verified", "unverified")
READINESS = ("not_implemented", "research_only", "money_ready")


class RulesetError(ValueError):
    """The rule registry itself is malformed — a build-time defect, not user input."""


@dataclass(frozen=True)
class Slot:
    name: str
    eligible: tuple[str, ...]


@dataclass(frozen=True)
class RuleSet:
    id: str
    version: str
    platform: str
    sport: str
    format: str
    label: str
    salary_cap: int
    slots: tuple[Slot, ...]
    max_players_per_team: int | None
    min_teams: int | None
    min_games: int | None
    salary_import: str
    export: dict[str, Any]
    verification: dict[str, Any]

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def verified(self) -> bool:
        return self.verification.get("state") == "verified"

    @property
    def export_verified(self) -> bool:
        return (self.export.get("verification") or {}).get("state") == "verified"

    @property
    def readiness(self) -> str:
        if self.verified and self.export_verified:
            return "money_ready"
        return "research_only"

    @property
    def positions(self) -> frozenset[str]:
        return frozenset(p for s in self.slots for p in s.eligible)

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "key": self.key,
            "platform": self.platform,
            "sport": self.sport,
            "format": self.format,
            "label": self.label,
            "salaryCap": self.salary_cap,
            "slots": [{"name": s.name, "eligible": list(s.eligible)} for s in self.slots],
            "maxPlayersPerTeam": self.max_players_per_team,
            "minTeams": self.min_teams,
            "minGames": self.min_games,
            "readiness": self.readiness,
            "verification": dict(self.verification),
            "export": {
                "format": self.export.get("format"),
                "header": list(self.export.get("header") or []),
                "verification": dict(self.export.get("verification") or {}),
            },
        }


def _positive_int_or_none(raw: Any, field: str, rid: str) -> int | None:
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
        raise RulesetError(f"{rid}: {field} must be a positive integer or null, got {raw!r}")
    return raw


def _parse_ruleset(raw: dict[str, Any]) -> RuleSet:
    rid = str(raw.get("id") or "")
    if not rid or not raw.get("version"):
        raise RulesetError(f"rule set missing id/version: {raw!r}")
    if raw.get("platform") not in PLATFORMS or raw.get("sport") not in SPORTS:
        raise RulesetError(f"{rid}: unknown platform/sport")
    cap = raw.get("salaryCap")
    if not isinstance(cap, int) or cap <= 0:
        raise RulesetError(f"{rid}: salaryCap must be a positive integer")
    slots = tuple(
        Slot(str(s["name"]), tuple(str(p) for p in s["eligible"])) for s in raw.get("slots") or []
    )
    if not slots or any(not s.eligible for s in slots):
        raise RulesetError(f"{rid}: every slot needs at least one eligible position")
    verification = dict(raw.get("verification") or {})
    if verification.get("state") not in VERIFICATION_STATES:
        raise RulesetError(f"{rid}: verification.state must be one of {VERIFICATION_STATES}")
    if verification.get("state") == "verified" and not verification.get("evidence"):
        raise RulesetError(f"{rid}: a verified rule set must cite official evidence")
    export = dict(raw.get("export") or {})
    header = list(export.get("header") or [])
    if header != [s.name for s in slots]:
        raise RulesetError(f"{rid}: export header must list the slots in order")
    ev = dict(export.get("verification") or {})
    if ev.get("state") not in VERIFICATION_STATES:
        raise RulesetError(f"{rid}: export.verification.state must be one of {VERIFICATION_STATES}")
    return RuleSet(
        id=rid,
        version=str(raw["version"]),
        platform=raw["platform"],
        sport=raw["sport"],
        format=str(raw.get("format") or ""),
        label=str(raw.get("label") or rid),
        salary_cap=cap,
        slots=slots,
        max_players_per_team=_positive_int_or_none(
            raw.get("maxPlayersPerTeam"), "maxPlayersPerTeam", rid
        ),
        min_teams=_positive_int_or_none(raw.get("minTeams"), "minTeams", rid),
        min_games=_positive_int_or_none(raw.get("minGames"), "minGames", rid),
        salary_import=str(raw.get("salaryImport") or ""),
        export=export,
        verification=verification,
    )


@lru_cache(maxsize=1)
def _load(path_str: str) -> tuple[dict[str, RuleSet], tuple[dict[str, Any], ...]]:
    data = json.loads(Path(path_str).read_text(encoding="utf-8"))
    rulesets: dict[str, RuleSet] = {}
    for raw in data.get("rulesets") or []:
        rs = _parse_ruleset(raw)
        if rs.id in rulesets:
            raise RulesetError(f"duplicate rule set id {rs.id} (add a new version instead)")
        rulesets[rs.id] = rs
    caps = []
    seen = set()
    for c in data.get("capabilities") or []:
        key = (c.get("platform"), c.get("sport"), c.get("format"))
        if key in seen:
            raise RulesetError(f"duplicate capability {key}")
        seen.add(key)
        if c.get("platform") not in PLATFORMS or c.get("sport") not in SPORTS:
            raise RulesetError(f"capability {key}: unknown platform/sport")
        rid = c.get("ruleset")
        if rid is not None:
            rs = rulesets.get(rid)
            if rs is None:
                raise RulesetError(f"capability {key} names unknown rule set {rid}")
            if (rs.platform, rs.sport, rs.format) != key:
                raise RulesetError(f"capability {key} does not match rule set {rid}")
        elif not c.get("reason"):
            raise RulesetError(f"capability {key} without a rule set must say why")
        caps.append(dict(c))
    return rulesets, tuple(caps)


def load_rulesets(path: Path | None = None) -> dict[str, RuleSet]:
    return _load(str(path or RULESETS_PATH))[0]


def get_ruleset(ruleset_id: str) -> RuleSet | None:
    return load_rulesets().get(ruleset_id)


def capability_matrix(path: Path | None = None) -> list[dict[str, Any]]:
    """Every registered platform × sport × format with its readiness."""
    rulesets, caps = _load(str(path or RULESETS_PATH))
    out = []
    for c in caps:
        rs = rulesets.get(c["ruleset"]) if c.get("ruleset") else None
        out.append(
            {
                "platform": c["platform"],
                "sport": c["sport"],
                "format": c["format"],
                "ruleset": rs.key if rs else None,
                "label": rs.label if rs else None,
                "readiness": rs.readiness if rs else "not_implemented",
                "reason": c.get("reason")
                or (
                    None
                    if rs is None or rs.verified
                    else "Rule set encoded but not verified against official rules."
                ),
            }
        )
    return out
