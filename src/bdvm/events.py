"""Structured event system (master prompt §7).

Replaces arbitrary manual value bumps.  Every event is a typed record
against a CLOSED ontology (``config/bdvm/event_types_v1.json``); an
event updates the relevant MODULE inputs (projection mean, risk
profile, dispersion, hazard, games) and never adds a final-score bonus.

Effective strength::

    scale = confidence · source_reliability · (1 − already_in_projection)
            · 2^(−days_since_effective / half_life_days)

Rules enforced here:

* unknown event types are rejected (closed enum);
* ``already_in_projection`` events are skipped entirely for µ and only
  half-counted for risk channels?  No — simpler and stricter: skipped
  entirely (the projection already carries them; §3.7);
* speculation (confidence < 0.5) may only widen σ — every non-sigma
  channel is suppressed;
* all resulting risk fields are clamped to [0, 1], games to [0, 17].
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.bdvm.engine import PlayerInput

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ONTOLOGY_PATH = REPO_ROOT / "config" / "bdvm" / "event_types_v1.json"
EVENTS_DIR = REPO_ROOT / "data" / "bdvm" / "events"

_SPECULATION_CONFIDENCE = 0.5

_RISK_CHANNELS = {
    "role_security_delta": "role_security",
    "role_uncertainty_delta": "role_uncertainty",
    "contract_security_delta": "contract_security",
    "durability_delta": "durability",
    "scheme_stability_delta": "scheme_stability",
    "designation_risk_delta": "designation_risk",
}


class EventError(ValueError):
    """Raised for malformed events or unknown event types."""


@lru_cache(maxsize=4)
def _load_ontology(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise EventError(f"event ontology missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))["event_types"]


@dataclass(frozen=True)
class PlayerEvent:
    """One structured event.  ``impact`` overrides the type default."""

    event_id: str
    player_key: str  # normalized canonical name
    event_type: str
    effective_date: str  # ISO date
    confidence: float
    source_reliability: float = 0.8
    already_in_projection: bool = False
    impact: Mapping[str, float] | None = None
    half_life_days: int | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise EventError(f"{self.event_id}: confidence must be in [0,1]")
        if not 0.0 <= self.source_reliability <= 1.0:
            raise EventError(f"{self.event_id}: source_reliability must be in [0,1]")


def decay_scale(event: PlayerEvent, as_of: str, *, ontology_path: Path | None = None) -> float:
    """confidence × reliability × (1−reflected) × 2^(−days/half_life)."""
    if event.already_in_projection:
        return 0.0
    onto = _load_ontology(str(ontology_path or DEFAULT_ONTOLOGY_PATH))
    if event.event_type not in onto:
        raise EventError(f"unknown event type {event.event_type!r} (closed ontology)")
    half_life = event.half_life_days or int(onto[event.event_type]["half_life_days"])
    try:
        days = (
            date.fromisoformat(str(as_of)[:10]) - date.fromisoformat(str(event.effective_date)[:10])
        ).days
    except ValueError as exc:
        raise EventError(f"{event.event_id}: bad dates") from exc
    days = max(0, days)
    return event.confidence * event.source_reliability * math.pow(2.0, -days / max(1, half_life))


def effective_impact(
    event: PlayerEvent, as_of: str, *, ontology_path: Path | None = None
) -> dict[str, float]:
    """The scaled per-channel adjustment this event contributes now."""
    onto = _load_ontology(str(ontology_path or DEFAULT_ONTOLOGY_PATH))
    if event.event_type not in onto:
        raise EventError(f"unknown event type {event.event_type!r} (closed ontology)")
    scale = decay_scale(event, as_of, ontology_path=ontology_path)
    if scale <= 0.0:
        return {}
    base = dict(onto[event.event_type].get("impact") or {})
    if event.impact:
        base.update({k: float(v) for k, v in event.impact.items()})
    speculative = event.confidence < _SPECULATION_CONFIDENCE

    out: dict[str, float] = {}
    for channel, raw in base.items():
        value = float(raw)
        if channel == "sigma_mult":
            # multiplicative channel: scale the log-effect
            out[channel] = math.exp(math.log(max(1e-6, value)) * scale)
        elif channel == "hazard_mult":
            if speculative:
                continue
            out[channel] = math.exp(math.log(max(1e-6, value)) * scale)
        else:
            if speculative:
                continue  # speculation may only widen sigma
            out[channel] = value * scale
    return out


def apply_events(
    player: PlayerInput,
    events: Iterable[PlayerEvent],
    *,
    as_of: str,
    ontology_path: Path | None = None,
) -> tuple[PlayerInput, list[dict[str, Any]]]:
    """Return an adjusted copy of ``player`` plus an audit trail.

    Adjustments compose additively per channel (multiplicatively for the
    ``*_mult`` channels), then clamp.  The original ``player`` is never
    mutated.
    """
    mu_pct_total = 0.0
    games_delta_total = 0.0
    sigma_mult_total = 1.0
    hazard_mult_total = 1.0
    risk_deltas: dict[str, float] = {}
    audit: list[dict[str, Any]] = []

    for ev in events:
        # ``events`` must already be filtered to this player (the service
        # groups by player_key); identity is not re-checked here because
        # PlayerInput ids and event keys use different namespaces.
        impact = effective_impact(ev, as_of, ontology_path=ontology_path)
        if not impact:
            audit.append(
                {
                    "eventId": ev.event_id,
                    "type": ev.event_type,
                    "applied": False,
                    "reason": "reflected_in_projection_or_fully_decayed",
                }
            )
            continue
        for channel, val in impact.items():
            if channel == "mu_pct":
                mu_pct_total += val
            elif channel == "games_delta":
                games_delta_total += val
            elif channel == "sigma_mult":
                sigma_mult_total *= val
            elif channel == "hazard_mult":
                hazard_mult_total *= val
            elif channel in _RISK_CHANNELS:
                risk_deltas[channel] = risk_deltas.get(channel, 0.0) + val
            else:
                raise EventError(f"{ev.event_id}: unknown impact channel {channel!r}")
        audit.append(
            {
                "eventId": ev.event_id,
                "type": ev.event_type,
                "applied": True,
                "impact": {k: round(v, 4) for k, v in impact.items()},
            }
        )

    if not audit:
        return player, []

    risk = player.risk
    if risk_deltas:
        fields = {}
        for channel, delta in risk_deltas.items():
            attr = _RISK_CHANNELS[channel]
            fields[attr] = min(1.0, max(0.0, getattr(risk, attr) + delta))
        risk = replace(risk, **fields)

    adjusted = replace(
        player,
        fpg=max(0.0, player.fpg * (1.0 + mu_pct_total)),
        games=min(17.0, max(0.0, player.games + games_delta_total)),
        risk=risk,
        event_sigma_mult=player.event_sigma_mult * sigma_mult_total,
        event_hazard_mult=player.event_hazard_mult * hazard_mult_total,
    )
    return adjusted, audit


# ---------------------------------------------------------------------------
# Event store (data/bdvm/events/<season>.json — human-maintained)
# ---------------------------------------------------------------------------


def load_events_file(season: int, *, base_dir: Path | None = None) -> list[PlayerEvent]:
    path = (base_dir or EVENTS_DIR) / f"{season}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for row in data.get("events", []):
        out.append(
            PlayerEvent(
                event_id=row["eventId"],
                player_key=row["playerKey"],
                event_type=row["eventType"],
                effective_date=row["effectiveDate"],
                confidence=float(row["confidence"]),
                source_reliability=float(row.get("sourceReliability", 0.8)),
                already_in_projection=bool(row.get("alreadyInProjection", False)),
                impact=row.get("impact"),
                half_life_days=row.get("halfLifeDays"),
                notes=str(row.get("notes", "")),
            )
        )
    return out
