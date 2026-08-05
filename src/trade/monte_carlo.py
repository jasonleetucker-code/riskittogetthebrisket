"""Monte Carlo trade simulator — consensus-based win-rate.

Depends on: Phase 4 confidence intervals (``src.canonical.confidence_intervals``).

Semantics
---------
Given side-A and side-B as lists of players, each with a
``valueBand`` (p10, p50, p90), we draw ``n_sims`` samples of total
side value and compute the fraction of draws where side A's sum
exceeds side B's sum.

Output: ``{winProbA, mean, spread, percentileBand, method}``.

Labeled strictly as ``consensus_based_win_rate`` — this is NOT
"there's a 62% chance side A wins the trade in real life."  It's
"across the sources' consensus distribution, side A ends up
ahead 62% of the time."  The UI MUST reflect this.

...with one honest qualification the label used to hide.  Nothing
stamps the Phase 4 ``valueBand`` on live rows — **0 of 1093** on the
pinned 2026-07-30 contract — and the UI synthesizes a flat ±15% band
under that same key, so on the live path the "consensus distribution"
is a constant.  ``bandSources`` in the output reports which it was and
the disclaimer says so when the band is synthetic.  The width itself
is an open modeling question, recorded with measurements as decision
#4 in ``docs/open-modeling-decisions.md`` rather than silently
re-tuned here.

Correlation model
-----------------
Rank-only inputs produce highly independent draws by default.
That's usually wrong — two WR2-archetype guys moving up or down
are often correlated (scheme, depth, injury cascades).  We
support two coarse correlation knobs:

  * ``same_team_rho``: correlation between players on the same
    NFL team.  Default 0.25 — some covariance, not perfect.
  * ``same_pos_group_rho``: correlation across players in the
    same position group (offense vs. IDP).  Default 0.10.

Both are uniform factors applied via a shared latent N(0,1)
draw per (team, pos_group).  Not a full covariance matrix —
good enough for first cut; cheaper than solving for one.

No numpy required — the hot loop uses Python's stdlib ``random``
module and nothing else.  There is no NumPy fast path: this
docstring used to claim one ("acceleration kicks in when
available"), but the module has never imported numpy.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

_DEFAULT_SIMS = 50_000

# Band provenance.  The output of this module is labelled
# ``consensus_based_win_rate`` and its disclaimer says the number comes
# from "the sources' consensus distribution".  On the live path that
# claim is FALSE and nothing could tell you: ``MonteCarloButton.jsx``
# synthesizes a flat +-15% band and posts it under the same
# ``valueBand`` key a real Phase-4 confidence interval would use, so
# the backend cannot distinguish measured source disagreement from a
# constant.  Measured on the pinned 2026-07-30 contract: **0 of 1093**
# rows carry a stamped ``valueBand``, so 100% of live simulations run
# on the synthetic one.
#
# Callers stamp which it was; ``SimResult.to_dict`` reports the tally
# as ``bandSources``.  That is the whole point — it gives the
# "consensus" label something capable of disagreeing with it.
BAND_SOURCE_STAMPED = "stamped_value_band"  # a real Phase-4 CI
BAND_SOURCE_SYNTHETIC = "synthetic_flat_15pct"  # a constant wearing its name
BAND_SOURCE_UNKNOWN = "unknown"  # caller did not say
_BAND_SOURCES = frozenset({BAND_SOURCE_STAMPED, BAND_SOURCE_SYNTHETIC, BAND_SOURCE_UNKNOWN})


@dataclass(frozen=True)
class TradePlayer:
    """Minimal player shape the simulator needs."""

    name: str
    team: str
    position_group: str  # "offense" | "idp" | "pick"
    p10: float
    p50: float
    p90: float
    # Where the band came from.  See ``BAND_SOURCE_*`` below — this is
    # what makes the "consensus_based_win_rate" label checkable instead
    # of merely asserted.
    band_source: str = BAND_SOURCE_UNKNOWN


@dataclass(frozen=True)
class SimResult:
    win_prob_a: float
    mean_delta: float
    std_delta: float
    delta_p10: float
    delta_p50: float
    delta_p90: float
    side_a_mean: float
    side_b_mean: float
    n_sims: int
    method: str  # "consensus_based_win_rate"
    va_adjustment: dict[str, Any] | None = field(default=None)
    # {band_source: count} across both sides — see the BAND_SOURCE_*
    # constants.
    band_sources: dict[str, int] | None = field(default=None)

    def to_dict(self) -> dict[str, Any]:
        sources = dict(self.band_sources or {})
        synthetic = sources.get(BAND_SOURCE_SYNTHETIC, 0)
        return {
            "winProbA": round(self.win_prob_a, 4),
            "winProbB": round(1.0 - self.win_prob_a, 4),
            "meanDelta": round(self.mean_delta, 1),
            "stdDelta": round(self.std_delta, 1),
            "deltaRange": {
                "p10": round(self.delta_p10, 1),
                "p50": round(self.delta_p50, 1),
                "p90": round(self.delta_p90, 1),
            },
            "sideAMean": round(self.side_a_mean, 1),
            "sideBMean": round(self.side_b_mean, 1),
            "nSims": self.n_sims,
            "method": self.method,
            # UI must show this label to prevent misreads:
            "labelHint": "consensus_based_win_rate",
            "disclaimer": (
                "This is the fraction of consensus-band samples "
                "where side A's total exceeds side B's — NOT a "
                "real-world win probability."
            )
            + (
                # Say so when "consensus" is not what happened.  The
                # label above is a contract field the UI is required to
                # render; without this, it asserts a measured
                # distribution on every run while 100% of live runs use
                # a constant.
                f"  {synthetic} of {sum(sources.values())} assets used a "
                "synthesized ±15% band rather than measured source "
                "disagreement, so the spread is an assumption, not a "
                "measurement."
                if synthetic
                else ""
            ),
            "bandSources": sources,
            "vaAdjustment": self.va_adjustment
            or {"side": 0, "value": 0, "effectiveValue": 0, "applied": False},
        }


def _triangular_draw(p10: float, p50: float, p90: float, u: float) -> float:
    """Map a uniform draw u in [0, 1] to the approximate
    distribution with the given quantiles using a piecewise-linear
    interpolation.

    Extended triangular form:
      * 0–0.10 → [p10 - (p50-p10), p10]
      * 0.10–0.50 → [p10, p50]
      * 0.50–0.90 → [p50, p90]
      * 0.90–1.00 → [p90, p90 + (p90-p50)]

    Simple, cheap, and matches the user's mental model: 10th and
    90th percentiles anchor the tails.
    """
    if u <= 0.10:
        # Lower tail extrapolation — match the p10-to-p50 slope.
        slope = p50 - p10
        t = u / 0.10
        return p10 - slope + slope * t  # = p10 - slope * (1-t)
    if u <= 0.50:
        t = (u - 0.10) / 0.40
        return p10 + t * (p50 - p10)
    if u <= 0.90:
        t = (u - 0.50) / 0.40
        return p50 + t * (p90 - p50)
    # Upper tail extrapolation.
    slope = p90 - p50
    t = (u - 0.90) / 0.10
    return p90 + t * slope


def _apply_consolidation_adjustment(
    side_a: list[TradePlayer],
    side_b: list[TradePlayer],
) -> tuple[list[TradePlayer], list[TradePlayer], dict[str, Any]]:
    """Apply KTC consolidation premium to whichever side earns it.

    Uses each player's p50 as the raw value fed to ktc_adjust_package.
    When VA is awarded, the bonus is distributed proportionally (by p50
    share) across the receiving side's players as an additive band shift
    — p10/p50/p90 all move up by the same amount per player, preserving
    the absolute spread (source disagreement is unchanged).

    Returns ``(adjusted_side_a, adjusted_side_b, va_info)`` where
    ``va_info`` is a diagnostic dict with keys ``side`` (0/1/2),
    ``value`` (int), and ``applied`` (bool).  When VA is suppressed
    (1v1, < 3.3% variance, or equal packages) the original lists are
    returned unchanged and ``applied`` is False.
    """
    from src.trade.ktc_va import ktc_adjust_package

    a_p50s = [p.p50 for p in side_a]
    b_p50s = [p.p50 for p in side_b]
    result = ktc_adjust_package(a_p50s, b_p50s)

    applied = result.displayed and result.value > 0
    va_info: dict[str, Any] = {
        "side": result.side,
        "value": result.value,
        "effectiveValue": 0,
        "applied": applied,
    }

    if not applied:
        return side_a, side_b, va_info

    def _shift_side(players: list[TradePlayer], p50s: list[float]) -> tuple[list[TradePlayer], int]:
        """Shift the band for each player proportionally.

        Returns the shifted list and the *actual* total p50 shift after
        clamping — which may be less than ``result.value`` when players
        are already near 9999.  The caller stamps this as
        ``effectiveValue`` so the reported diagnostic matches what the
        simulation actually experienced.
        """
        total = sum(p50s) or 1.0
        out = []
        effective_total = 0.0
        for p, pv in zip(players, p50s):
            shift = result.value * (pv / total)
            # The 9999 cap stays on p50 — it is a VALUE, on the board's
            # scale, and holding the premium to that scale is the
            # deliberate behaviour ``effectiveValue`` exists to report.
            new_p50 = max(0.0, min(9999.0, p.p50 + shift))
            # ...but the band moves by whatever the p50 clamp ALLOWED,
            # not by the requested shift, and the endpoints take no
            # ceiling of their own.  Clamping each endpoint separately
            # contradicted this function's own docstring — "p10/p50/p90
            # all move up by the same amount per player, preserving the
            # absolute spread" — and not marginally.  Worked example: a
            # 9950-valued asset receiving a 5,324 premium had all THREE
            # endpoints clamp to 9999, collapsing a 2,985-wide band to
            # ZERO.  The simulator then treated the single most valuable
            # asset in the trade as a point mass with no uncertainty at
            # all, and ``effectiveValue`` reported the p50 shortfall (49
            # of 5,324) without any hint that the band had vanished.
            applied = new_p50 - p.p50
            effective_total += applied
            out.append(
                TradePlayer(
                    name=p.name,
                    team=p.team,
                    position_group=p.position_group,
                    p10=max(0.0, p.p10 + applied),
                    p50=new_p50,
                    p90=max(0.0, p.p90 + applied),
                    band_source=p.band_source,
                )
            )
        return out, int(round(effective_total))

    if result.side == 1:
        new_a, eff = _shift_side(side_a, a_p50s)
        va_info["effectiveValue"] = eff
        return new_a, side_b, va_info
    new_b, eff = _shift_side(side_b, b_p50s)
    va_info["effectiveValue"] = eff
    return side_a, new_b, va_info


def simulate_trade(
    side_a: list[TradePlayer],
    side_b: list[TradePlayer],
    *,
    n_sims: int = _DEFAULT_SIMS,
    same_team_rho: float = 0.25,
    same_pos_group_rho: float = 0.10,
    seed: int | None = None,
    apply_consolidation_adjustment: bool = False,
) -> SimResult:
    """Run the simulation and return the result.

    Correlation implementation:
      z_team[team] ~ N(0,1) per (team) per sim
      z_pos[group] ~ N(0,1) per (group) per sim
      z_player ~ N(0,1) per player per sim (idiosyncratic)
      u = Phi( sqrt(1-rho_team-rho_pos) * z_player
                + sqrt(rho_team) * z_team[team]
                + sqrt(rho_pos) * z_pos[group] )

    where Phi is the standard normal CDF.  Output u ∈ [0,1] is
    then fed to the triangular draw.  This gives a correlated
    uniform latent; its marginal remains U(0,1) per player so
    the per-player band is preserved on average.
    """
    rng = random.Random(seed)
    va_info: dict[str, Any] = {"side": 0, "value": 0, "effectiveValue": 0, "applied": False}
    if apply_consolidation_adjustment and side_a and side_b:
        side_a, side_b, va_info = _apply_consolidation_adjustment(side_a, side_b)
    players = list(side_a) + list(side_b)
    if not players:
        return SimResult(
            win_prob_a=0.5,
            mean_delta=0.0,
            std_delta=0.0,
            delta_p10=0.0,
            delta_p50=0.0,
            delta_p90=0.0,
            side_a_mean=0.0,
            side_b_mean=0.0,
            n_sims=0,
            method="consensus_based_win_rate",
            va_adjustment={"side": 0, "value": 0, "effectiveValue": 0, "applied": False},
            band_sources={},
        )

    band_sources: dict[str, int] = {}
    for _p in players:
        band_sources[_p.band_source] = band_sources.get(_p.band_source, 0) + 1

    # Sanity clamp on correlation params.
    rho_t = max(0.0, min(0.5, same_team_rho))
    rho_p = max(0.0, min(0.5, same_pos_group_rho))
    if rho_t + rho_p >= 1.0:
        rho_t, rho_p = 0.45, 0.45
    idio_var = 1.0 - rho_t - rho_p
    idio_sd = math.sqrt(max(0.0, idio_var))

    teams = sorted({p.team for p in players if p.team})
    groups = sorted({p.position_group for p in players if p.position_group})

    deltas: list[float] = []
    a_sums: list[float] = []
    b_sums: list[float] = []

    for _ in range(n_sims):
        z_team = {t: rng.gauss(0.0, 1.0) for t in teams}
        z_pos = {g: rng.gauss(0.0, 1.0) for g in groups}

        def _sample(pl: TradePlayer) -> float:
            zt = z_team.get(pl.team, 0.0) if rho_t else 0.0
            zp = z_pos.get(pl.position_group, 0.0) if rho_p else 0.0
            z_play = rng.gauss(0.0, 1.0)
            z_total = idio_sd * z_play + math.sqrt(rho_t) * zt + math.sqrt(rho_p) * zp
            # Convert N(0,1) to U(0,1) via standard-normal CDF.
            u = 0.5 * (1.0 + math.erf(z_total / math.sqrt(2.0)))
            # Clamp to avoid edge artifacts from float error.
            u = max(1e-6, min(1.0 - 1e-6, u))
            return _triangular_draw(pl.p10, pl.p50, pl.p90, u)

        sa = sum(_sample(p) for p in side_a)
        sb = sum(_sample(p) for p in side_b)
        a_sums.append(sa)
        b_sums.append(sb)
        deltas.append(sa - sb)

    deltas.sort()
    a_mean = sum(a_sums) / n_sims
    b_mean = sum(b_sums) / n_sims
    mean_d = sum(deltas) / n_sims
    sd_d = _stdev(deltas)
    # Exact ties split evenly.  ``to_dict`` reports winProbB as
    # ``1 − winProbA``, so counting only ``d > 0`` handed every tie to
    # side B in full — and ties are reachable whenever the bands on both
    # sides are degenerate or integer-valued (a pick swapped for the
    # same pick, two players carrying the identical band).
    wins_a = (sum(1 for d in deltas if d > 0) + 0.5 * sum(1 for d in deltas if d == 0)) / n_sims

    return SimResult(
        win_prob_a=wins_a,
        mean_delta=mean_d,
        std_delta=sd_d,
        delta_p10=deltas[int(0.10 * n_sims)],
        delta_p50=deltas[int(0.50 * n_sims)],
        delta_p90=deltas[int(0.90 * n_sims)],
        side_a_mean=a_mean,
        side_b_mean=b_mean,
        n_sims=n_sims,
        method="consensus_based_win_rate",
        va_adjustment=va_info,
        band_sources=band_sources,
    )


def _stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def build_trade_player(
    row: dict[str, Any],
    *,
    apply_scoring_fit: bool = False,
    scoring_fit_weight: float = 0.30,
) -> TradePlayer | None:
    """Construct a TradePlayer from a canonical-contract player row.

    Prefers the ``valueBand`` dict; falls back to a ±15% band centered
    on ``rankDerivedValue`` when no band is supplied.

    Note which branch actually runs in production: the caller
    (``MonteCarloButton.jsx``) always supplies a ``valueBand``, and
    since no live row carries a stamped one, that band is itself the
    synthesized ±15%.  The fallback below is therefore the *shape* of
    the live behaviour without being the live *code path* — which is
    why ``band_source`` is carried explicitly rather than inferred
    from which branch was taken.

    When ``apply_scoring_fit`` is True and the row carries an
    ``idpScoringFitDelta``, the entire band shifts by
    ``delta × scoring_fit_weight`` so simulation reflects the
    league-aware value rather than the consensus market.  Affects
    only IDP rows; offense + picks pass through unchanged.
    """
    if not isinstance(row, dict):
        return None
    name = str(row.get("name") or row.get("displayName") or "").strip()
    if not name:
        return None
    team = str(row.get("team") or "").strip().upper()
    pos = str(row.get("pos") or row.get("position") or "").upper()
    group = (
        "idp" if pos in ("DL", "LB", "DB", "CB", "S") else ("pick" if pos == "PICK" else "offense")
    )

    # Scoring-fit shift: a single additive offset on the entire band.
    # Computed once here so both the valueBand and fallback paths use
    # the same number.  Clamped so a wide band doesn't spill below 0.
    fit_shift = 0.0
    if apply_scoring_fit and group == "idp":
        delta = row.get("idpScoringFitDelta")
        if isinstance(delta, (int, float)):
            try:
                w = max(0.0, min(1.0, float(scoring_fit_weight)))
            except (TypeError, ValueError):
                w = 0.30
            fit_shift = float(delta) * w

    def _shifted(v: float) -> float:
        # Floor at 0 only.  9999 is where the BOARD's normalization
        # tops out — it is not a ceiling on a quantile, and clamping a
        # band endpoint to it truncates the upper tail of exactly the
        # assets whose value the simulator most needs to get right.
        #
        # Measured on the pinned 2026-07-30 contract, with the UI's
        # own +-15% band: 12 of 812 priced rows had p90 clamped, and
        # because ``_triangular_draw`` is otherwise unbiased
        # (E[X] == p50 for a symmetric band, exactly), the clamp was
        # the ONLY source of bias:
        #
        #     Josh Allen     board 9988 -> E[draw] 9468   (-520, -5.2%)
        #     Brock Bowers   board 9961 -> E[draw] 9451   (-510, -5.1%)
        #     Bijan Robinson board 9699 -> E[draw] 9295   (-404, -4.2%)
        #     ... 9 more, down to -23
        #
        # i.e. every trade involving an elite asset was simulated
        # against the side holding it, and only that side.  The clamp
        # was not enforcing an invariant the module respects anyway:
        # ``_triangular_draw`` extrapolates ABOVE p90 without any
        # ceiling, so draws past 9999 were always reachable.  Clamping
        # the endpoint but not the draw only distorted the shape.
        return max(0.0, float(v) + fit_shift)

    band = row.get("valueBand") or {}
    if isinstance(band, dict) and band.get("p50") is not None:
        # The caller may declare where the band came from.  It matters:
        # ``MonteCarloButton.jsx`` posts a synthesized ±15% band under
        # this exact key, so the presence of ``valueBand`` says nothing
        # about whether any source disagreement was measured.  Absent a
        # declaration we say UNKNOWN rather than assuming the flattering
        # answer.
        declared = row.get("bandSource")
        source = declared if declared in _BAND_SOURCES else BAND_SOURCE_UNKNOWN
        return TradePlayer(
            name=name,
            team=team,
            position_group=group,
            p10=_shifted(band.get("p10") or 0),
            p50=_shifted(band.get("p50") or 0),
            p90=_shifted(band.get("p90") or 0),
            band_source=source,
        )
    # Fallback: synthesize a 15% band around the canonical value.
    cv = float(row.get("rankDerivedValue") or row.get("values", {}).get("full") or 0)
    return TradePlayer(
        name=name,
        team=team,
        position_group=group,
        p10=_shifted(cv * 0.85),
        p50=_shifted(cv),
        p90=_shifted(cv * 1.15),
        band_source=BAND_SOURCE_SYNTHETIC,
    )
