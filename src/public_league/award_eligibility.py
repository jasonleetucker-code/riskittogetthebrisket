"""Owner season-scoped award eligibility — the ONE place it is decided.

An owner competition rule can make a manager ineligible to WIN one award in
one season of one league (the first: 2026 Waiver King — Joel and Blaine).
The rule lives in ``config/leagues/award_eligibility_overrides.json`` with
its provenance; this module only reads and answers it.

Three properties are load-bearing:

* **Eligibility is not measurement.**  Nothing here touches a metric.  The
  award's canonical rows are computed exactly as before; this module only
  decides who may hold an AWARD rank.  An ineligible manager keeps their
  metric rank and value in the published standings.
* **Season-scoped, not date-scoped.**  A rule matches a season label AND
  that season's Sleeper league id.  2027 is a new season (and a new league
  id), so it starts with no rule and nothing has to be cleaned up; viewing
  2026 in 2028 still applies the 2026 rule, because it is keyed on the
  season being evaluated, never on today's date.
* **One award.**  A rule names exactly one award key.  No other award,
  statistic, standing or data consumer asks this module anything about a
  key it was not given.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

OWNER_SEASON_OVERRIDE = "owner_season_eligibility_override"

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "leagues" / "award_eligibility_overrides.json"
)


@dataclass(frozen=True)
class Ineligibility:
    """Why one owner may not win one award in one season."""

    reason: str
    override_id: str
    label: str

    def to_payload(self) -> dict[str, Any]:
        return {"ineligibleReason": self.reason, "ineligibleLabel": self.label}


@dataclass(frozen=True)
class _Override:
    override_id: str
    season: str
    league_id: str
    award: str
    owner_ids: frozenset[str]
    reason: str
    label: str


def _parse(raw: Any) -> tuple[_Override, ...]:
    """Strict parse.  A malformed rule raises rather than silently matching
    nobody — a dropped rule would quietly crown an ineligible manager."""
    if not isinstance(raw, dict) or not isinstance(raw.get("overrides"), list):
        raise ValueError("award eligibility overrides: expected {'overrides': [...]}")
    out: list[_Override] = []
    for i, item in enumerate(raw["overrides"]):
        if not isinstance(item, dict):
            raise ValueError(f"award eligibility override #{i}: not an object")
        fields = {}
        for key in ("id", "season", "leagueId", "award", "type", "publicLabel"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"award eligibility override #{i}: '{key}' must be a string")
            fields[key] = value.strip()
        owners = item.get("ineligibleOwnerIds")
        if (
            not isinstance(owners, list)
            or not owners
            or not all(isinstance(o, str) and o.strip() for o in owners)
        ):
            raise ValueError(
                f"award eligibility override #{i}: 'ineligibleOwnerIds' must be a non-empty list of ids"
            )
        if fields["type"] != OWNER_SEASON_OVERRIDE:
            raise ValueError(f"award eligibility override #{i}: unknown type {fields['type']!r}")
        out.append(
            _Override(
                override_id=fields["id"],
                season=fields["season"],
                league_id=fields["leagueId"],
                award=fields["award"],
                owner_ids=frozenset(o.strip() for o in owners),
                reason=fields["type"],
                label=fields["publicLabel"],
            )
        )
    return tuple(out)


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[_Override, ...]:
    with open(path, encoding="utf-8") as fh:
        return _parse(json.load(fh))


def load_overrides(path: Path | None = None) -> tuple[_Override, ...]:
    return _load(str(path or _CONFIG_PATH))


def ineligibility(
    *,
    season: str,
    league_id: str,
    award: str,
    owner_id: str,
    overrides: tuple[_Override, ...] | None = None,
) -> Ineligibility | None:
    """The rule that makes ``owner_id`` ineligible for ``award`` in this
    season of this league, or ``None`` (eligible)."""
    if not owner_id:
        return None
    rules = load_overrides() if overrides is None else overrides
    for rule in rules:
        if (
            rule.award == award
            and rule.season == str(season)
            and rule.league_id == str(league_id)
            and owner_id in rule.owner_ids
        ):
            return Ineligibility(reason=rule.reason, override_id=rule.override_id, label=rule.label)
    return None


def season_rules(
    *,
    season: str,
    league_id: str,
    overrides: tuple[_Override, ...] | None = None,
) -> dict[str, frozenset[str]]:
    """``{award: ineligible owner ids}`` for one season — what applies there."""
    rules = load_overrides() if overrides is None else overrides
    out: dict[str, set[str]] = {}
    for rule in rules:
        if rule.season == str(season) and rule.league_id == str(league_id):
            out.setdefault(rule.award, set()).update(rule.owner_ids)
    return {k: frozenset(v) for k, v in out.items()}
