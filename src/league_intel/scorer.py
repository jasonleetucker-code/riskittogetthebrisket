"""Deterministic exact scorer over Sleeper stat keys (ADR-005).

Empirically validated model of how Sleeper awards fantasy points
(see docs/league-intelligence/SCORING_VALIDATION.md): a **pure dot
product** over the keys shared between a player's weekly stat line and
the league's ``scoring_settings`` —

    points = Σ  stat_line[k] × scoring_settings[k]
           k ∈ stat_line ∩ scoring_settings

No exclusions, no de-duplication, no special-casing.  Every stacking
question ("does a pick-six charge both ``pass_int`` and
``pass_int_td``?") reduces to "which keys does Sleeper put in the stat
payload together" — and the host emits every applicable key, so they
all stack.  This reproduced Sleeper's own ``players_points`` exactly
(|Δ| ≤ 0.011) for 1,415 of 1,415 rostered player-weeks across three
2025 league weeks, and both audited team totals.

Determinism / float policy: stats and rates are IEEE-754 floats as
served by Sleeper (e.g. ``pass_yd`` rate 0.0333… = 1/30).  Components
are accumulated in sorted-key order so the same inputs always produce
bit-identical totals.  No rounding is applied internally — Sleeper's
displayed scores are rounded to 2 decimals at the UI layer, so
comparisons against host-awarded points must use a 0.01 tolerance
(golden tests pin this).

Pure function: no I/O, no globals, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = ["ScoringComponent", "ScoringBreakdown", "score_stat_line"]


@dataclass(frozen=True)
class ScoringComponent:
    """One (stat, rate) contribution to a weekly score."""

    scoring_key: str
    raw_stat: float
    rate: float
    awarded_points: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "scoringKey": self.scoring_key,
            "rawStat": self.raw_stat,
            "rate": self.rate,
            "awardedPoints": self.awarded_points,
        }


@dataclass
class ScoringBreakdown:
    """Full explainable result of scoring one stat line."""

    total_points: float
    components: list[ScoringComponent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalPoints": self.total_points,
            "components": [c.to_dict() for c in self.components],
            "warnings": list(self.warnings),
        }


def _scoring_settings_of(config: Any) -> Mapping[str, float]:
    """Accept a LeagueIntelConfig-like object or a plain scoring map."""
    settings = getattr(config, "scoring_settings", None)
    if isinstance(settings, Mapping):
        return settings
    if isinstance(config, Mapping):
        return config
    raise TypeError(
        "config must be a LeagueIntelConfig or a scoring-settings mapping, "
        f"got {type(config).__name__}"
    )


def score_stat_line(stat_line: Mapping[str, Any], config: Any) -> ScoringBreakdown:
    """Score one Sleeper-keyed weekly stat line under a league config.

    Component rules (explainability contract):

    * every key present in BOTH the stat line and ``scoring_settings``
      with a nonzero rate produces a scoring component;
    * zero-rate keys present in both are tracked as zero-point
      components when the raw stat is nonzero (so "your league does
      not score ``rec_fd``" is visible, without drowning the breakdown
      in the dozens of zero-valued bookkeeping stats Sleeper ships);
    * stat-line keys absent from ``scoring_settings`` (``gp``,
      ``fgm_pct``, ``off_snp`` …) are ignored — they are metadata, not
      scorable events;
    * non-numeric values for scorable keys are skipped with a warning.

    Deterministic: components are emitted in sorted key order.
    """
    scoring = _scoring_settings_of(config)
    components: list[ScoringComponent] = []
    warnings: list[str] = []
    total = 0.0

    for key in sorted(stat_line):
        if key not in scoring:
            continue
        raw = stat_line[key]
        if raw is None:
            continue
        try:
            stat = float(raw)
        except (TypeError, ValueError):
            warnings.append(f"non-numeric stat value for {key!r}: {raw!r}")
            continue
        try:
            rate = float(scoring[key])
        except (TypeError, ValueError):
            warnings.append(f"non-numeric scoring rate for {key!r}: {scoring[key]!r}")
            continue
        if rate == 0.0:
            if stat != 0.0:
                components.append(
                    ScoringComponent(scoring_key=key, raw_stat=stat, rate=0.0, awarded_points=0.0)
                )
            continue
        awarded = stat * rate
        total += awarded
        components.append(
            ScoringComponent(scoring_key=key, raw_stat=stat, rate=rate, awarded_points=awarded)
        )

    return ScoringBreakdown(total_points=total, components=components, warnings=warnings)
