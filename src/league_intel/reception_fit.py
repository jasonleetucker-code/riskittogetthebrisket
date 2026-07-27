"""Per-player value tilt from this league's reception-distance banding.

Read the magnitude section before quoting this feature
─────────────────────────────────────────────────────
The headline number for this divergence has been "an 8x spread every
source prices as flat 0.75", and ``docs/ORCHESTRATION.md`` calls it "the
largest unexploited edge identified to date". **The 8x is real and the
value impact is not 8x.** Both halves matter and only one of them has
been stated so far.

Per CATCH, measured live 2026-07-27, this league pays::

    0-4 yd 0.25   5-9 0.50   10-19 0.75   20-29 1.00   30-39 1.25   40+ 2.00

against a flat 0.75 baseline — so a checkdown is worth 0.33x and a deep
ball 2.67x, and the raw per-catch ratio across real 2025 receivers runs
from 0.56 (Rachaad White) to 1.23 (Alec Pierce), a 2.2x spread.

But **receptions are a minority of a player's fantasy points.** Measured
share of total baseline points coming from reception keys, 2025::

    RB 0.166    WR 0.304    TE 0.330

So the value multiplier is ``1 + reception_share x (per_catch_ratio - 1)``
and it lands near ±8%, not ±120%::

    composed multiplier, dispersion by pool depth (p90/p10)
    top24 1.072   top36 1.078   top60 1.069   top120 1.087   top200 1.106

That is the number to act on. Anyone reading "8x" and sizing a trade off
it will be wrong by an order of magnitude.

Why it is still worth having, when IDP per-player was not
─────────────────────────────────────────────────────────
±8% is the same order as the IDP *positional* tilt this codebase already
ships, and unlike the IDP *per-player* attempt — which
:mod:`src.league_intel.scoring_fit` refuses — this dispersion is **flat
across pool depth**. Compare:

    IDP per-player   1.109 -> 1.116 -> 1.115 -> 1.132 -> 1.215   fans out
    reception fit    1.072 -> 1.078 -> 1.069 -> 1.087 -> 1.106   flat

A sampling artifact widens as you sample deeper because thinner samples
are noisier. This does not, so it is measuring the thing it names. The
extremes are also coherent rather than random: deep threats at the top
(Pierce, Watson, McLaurin) and checkdown backs and short-area tight ends
at the bottom (White, Gainwell, Ferguson), which is the axis the banding
is built on.

The median sits at ~0.96, so the receiving corps as a whole is priced
slightly high by flat-PPR sources. That is a real level effect and it is
kept rather than normalised away — unlike the IDP case, where the shared
level was an artifact of rate-card generosity. Here both cards are being
applied to the same catches, so a shared shift is a fact about the
scoring, not about how the commissioners numbered their sheets.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.nfl_data.reception_depth import BAND_KEYS, summarise_histogram

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "MAX_TILT",
    "MIN_RECEPTIONS",
    "ReceptionFitMeasurement",
    "measure_reception_depth_fit",
    "reception_scoring_keys",
]

#: Below this many catches a player's band distribution is shape noise.
#: 20 keeps ~200 receivers on a 2025 season, which covers everyone
#: rosterable in a 12-team league several times over.
MIN_RECEPTIONS: int = 20

#: Hard clamp on the composed multiplier. Nothing measured comes close
#: (observed range 0.92-1.09); this exists so an upstream data fault
#: cannot express itself as a 3x repricing.
MAX_TILT: float = 0.25

#: Depth probes and tolerance, mirroring
#: :mod:`src.league_intel.scoring_fit` so the two measurements are
#: judged by the same standard.
_DEPTH_PROBES: tuple[int, ...] = (24, 36, 60, 120)
_MAX_DISPERSION_DRIFT: float = 0.12


def reception_scoring_keys() -> frozenset[str]:
    """Every scoring key that pays for a catch, banded or flat."""
    return frozenset(BAND_KEYS) | {"rec"}


@dataclass(frozen=True)
class ReceptionFitMeasurement:
    """Per-player value multipliers, with the evidence and the refusals."""

    multipliers: dict[str, float] = field(default_factory=dict)
    """Keyed by GSIS id. Absent means unmeasured, which callers must
    treat as 1.0 rather than as zero."""

    per_catch_ratios: dict[str, float] = field(default_factory=dict)
    reception_shares: dict[str, float] = field(default_factory=dict)
    season: int | None = None
    measured: bool = False
    trusted: bool = False
    dispersion_drift: float = 0.0
    median_multiplier: float = 1.0
    sample_size: int = 0
    reason: str = ""

    def multiplier_for(self, player_id_gsis: str) -> float:
        """1.0 for anything unmeasured or untrusted. Never raises."""
        if not self.trusted:
            return 1.0
        return self.multipliers.get(str(player_id_gsis or "").strip(), 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "trusted": self.trusted,
            "season": self.season,
            "sampleSize": self.sample_size,
            "dispersionDrift": round(self.dispersion_drift, 6),
            "medianMultiplier": round(self.median_multiplier, 6),
            "reason": self.reason,
            "playerCount": len(self.multipliers),
        }


def _per_catch_value(shares: Mapping[str, float], scoring: Mapping[str, Any]) -> float:
    """Expected points per reception for a player with this band shape."""
    flat = float(scoring.get("rec") or 0.0)
    return sum(float(shares.get(b, 0.0)) * (flat + float(scoring.get(b) or 0.0)) for b in BAND_KEYS)


def _dispersion(values: Sequence[float]) -> float:
    """p90/p10 of ``values`` normalised by their median."""
    if len(values) < 10:
        return 0.0
    med = statistics.median(values)
    if med <= 0:
        return 0.0
    norm = sorted(v / med for v in values)
    q = statistics.quantiles(norm, n=10)
    if q[0] <= 0:
        return 0.0
    return q[-1] / q[0]


def measure_reception_depth_fit(
    depth_payload: Mapping[str, Any] | None,
    reception_shares: Mapping[str, float] | None,
    my_scoring: Mapping[str, Any] | None,
    baseline_scoring: Mapping[str, Any] | None,
    *,
    season: int | None = None,
    min_receptions: int = MIN_RECEPTIONS,
) -> ReceptionFitMeasurement:
    """Compose band shapes and reception shares into value multipliers.

    ``depth_payload`` is :func:`src.nfl_data.reception_depth.load_reception_depth`
    output. ``reception_shares`` maps GSIS id to the fraction of that
    player's BASELINE fantasy points that came from reception keys — the
    baseline card because that is the one the market prices on.

    Refuses as a whole rather than per player: if the dispersion is not
    stable across pool depth, the measurement is describing sample
    composition and no individual multiplier from it is trustworthy.
    """
    if not depth_payload or not my_scoring or not baseline_scoring:
        return ReceptionFitMeasurement(
            season=season, reason="depth payload and both scoring cards are required"
        )

    players = depth_payload.get("players")
    if not isinstance(players, dict) or not players:
        return ReceptionFitMeasurement(season=season, reason="depth payload has no players")

    shares_in = reception_shares or {}
    multipliers: dict[str, float] = {}
    ratios: dict[str, float] = {}
    shares_out: dict[str, float] = {}
    # (receptions, multiplier) so dispersion can be probed by volume.
    ranked: list[tuple[int, float]] = []

    for gsis, rec in players.items():
        if not isinstance(rec, dict):
            continue
        summary = summarise_histogram(rec.get("bands") or {})
        if summary["receptions"] < min_receptions:
            continue
        base_pc = _per_catch_value(summary["shares"], baseline_scoring)
        if base_pc <= 0:
            continue
        ratio = _per_catch_value(summary["shares"], my_scoring) / base_pc

        share = shares_in.get(gsis)
        if share is None:
            # No scored season for this player: the per-catch ratio is
            # known but its weight is not, and guessing a share would
            # invent the entire magnitude of the adjustment.
            continue
        share = max(0.0, min(1.0, float(share)))

        raw = 1.0 + share * (ratio - 1.0)
        multiplier = max(1.0 - MAX_TILT, min(1.0 + MAX_TILT, raw))
        multipliers[gsis] = multiplier
        ratios[gsis] = ratio
        shares_out[gsis] = share
        ranked.append((summary["receptions"], multiplier))

    if len(multipliers) < 10:
        return ReceptionFitMeasurement(
            season=season,
            measured=bool(multipliers),
            reason=f"only {len(multipliers)} players had both a band shape and a scored season",
        )

    ranked.sort(key=lambda t: -t[0])
    probes = [_dispersion([m for _, m in ranked[:n]]) for n in _DEPTH_PROBES if len(ranked) >= n]
    probes = [p for p in probes if p > 0]
    drift = (max(probes) - min(probes)) if len(probes) >= 2 else 0.0
    trusted = drift <= _MAX_DISPERSION_DRIFT
    median_mult = statistics.median(multipliers.values())

    if not trusted:
        _LOGGER.warning(
            "reception_fit: dispersion drifts %.4f across depths %s (max %.2f); "
            "measurement rejected",
            drift,
            _DEPTH_PROBES,
            _MAX_DISPERSION_DRIFT,
        )

    return ReceptionFitMeasurement(
        multipliers=multipliers,
        per_catch_ratios=ratios,
        reception_shares=shares_out,
        season=season,
        measured=True,
        trusted=trusted,
        dispersion_drift=drift,
        median_multiplier=median_mult,
        sample_size=len(multipliers),
        reason=(
            f"composed over {len(multipliers)} receivers with >={min_receptions} catches; "
            f"dispersion stable to {drift:.4f} across depths {_DEPTH_PROBES}"
            if trusted
            else (
                f"dispersion drifts {drift:.4f} across depths {_DEPTH_PROBES} "
                f"(max {_MAX_DISPERSION_DRIFT}) — sample composition, not scoring; "
                "every multiplier forced to 1.0"
            )
        ),
    )
