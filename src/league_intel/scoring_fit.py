"""How much this league's scoring rules favour a POSITION over the market's.

The measurement, and the finding that shaped the API
─────────────────────────────────────────────────────
The operator's league and the default-scoring baseline league
(``config/league_comparison.json``) disagree on 95 of 146 scoring keys.
On IDP the disagreements are large and they point in opposite
directions — measured live 2026-07-27::

    idp_pass_def   2.11 -> 5.32   2.52x  UP
    idp_tkl_loss   2.06 -> 4.25   2.06x  UP
    idp_qb_hit     1.08 -> 2.13   1.97x  UP
    idp_sack       4.55 -> 2.92   0.64x  DOWN
    idp_int        6.20 -> 5.32   0.86x  DOWN

Coverage and disruption are paid; finishing plays are discounted. Every
ranking source prices IDP on a generic rate card closer to the baseline,
so there is a real mispricing here.

**The obvious exploit does not survive measurement, and that is why this
module is deliberately position-level and not per-player.**

Scoring all 2025 IDP player-weeks under both rate cards and taking each
player's ``mine / baseline`` ratio, then normalising within the position
cohort, gives a per-player "scoring fit". It looks like signal. It is
not. Measured p90/p10 of the cohort-normalised ratio, by how deep into
the position you go::

    DL   top24 1.109   top36 1.116   top60 1.115   top120 1.132   all 1.215
    LB   top24 1.113   top36 1.095   top60 1.100   top120 1.099   all 1.144
    DB   top24 1.071   top36 1.075   top60 1.083   top120 1.113   all 1.144

Two things to read off that. Among genuinely rosterable players the
spread is only ~±5%, and it **grows monotonically with pool depth** —
deeper players take fewer snaps, so their stat mixes are noisier and
their ratios fan out. That is the signature of small-sample noise, not
of a real player-selection edge. The most "mispriced" players by this
measure were Kemon Hall, Cory Durden and Jack Cochrane: bench bodies
near the scoring floor, not targets.

The **position-level** median, by contrast, is stable across depth, and
that stability is what makes it trustworthy. Within a position, stat
mixes are similar enough that the per-key inversions largely cancel and
move the whole cohort together; they do not separate players inside it.

So the edge is real and it is **positional**. A per-player multiplier
built from the same data would be ±5% of noise wearing the costume of a
measurement, which is the defect class this repo keeps paying for — so
the API does not offer one.

THE DIRECTION, RE-MEASURED 2026-07-27 — AND CORRECTED
─────────────────────────────────────────────────────
This docstring previously recorded ``DL 1.089 / LB 1.043 / DB 1.014``
and concluded "relative to DB, this league pays DL about +7% and LB
about +3%". **That direction was wrong, and it was backwards.**

Re-run through this module's own public entry point on raw nflverse
weekly rows, with both leagues' live ``scoring_settings`` (verified
byte-identical to the values the original measurement recorded — zero
drift on all 8 IDP keys), the mean-normalised multipliers are::

    DB   0.9971     raw 1.1979   n=295   depth drift low
    DL   1.0421     raw 1.2519   n=221   depth drift low
    LB   0.9608     raw 1.1542   n=208   depth drift low

DL highest, LB lowest.

**A correction, and the reason it is recorded here rather than quietly
applied.** An intermediate measurement on 2026-07-27 produced DB 1.0366
/ DL 1.0001 / LB 0.9633 — DB highest — and that number was shipped: it
is what turned this flag on. It was measured on a **partially corrected
scoring card**, and the partial correction is what produced the wrong
ordering.

Sleeper publishes some rules under two key names.  At the time of that
measurement ``idp_pass_def`` had just been aliased to ``idp_pd`` and was
scoring, but ``idp_qb_hit`` -> ``idp_hit`` had not yet been, so QB hits
were still scoring **zero**.  PD is a cornerback stat; QB hits are an
edge-rusher stat.  Correcting one and not the other lifted DB against DL
by exactly the amount the missing DL stat was owed — 6,545 points across
2025.

This is the failure mode ``UNIMPLEMENTED_BACKLOG.md`` §14 names
explicitly: *a partial correction to a relative ranking introduces a
bias that no correction does not*.  This module measures a purely
relative quantity, so it is maximally exposed to it.  Deriving the alias
map from ``sleeper_ingest.KEY_ALIASES`` rather than restating it (commit
``d3212864``) closed the gap, and re-measuring on the complete card
gives the figures above.

The rate card corroborates the corrected ordering:

* ``idp_sack`` is **0.64x DOWN** — the largest single cut, and the
  signature DL stat — but ``idp_tkl_loss`` is **2.06x UP** and
  ``idp_qb_hit`` **1.97x UP**, and those two are also DL-heavy. Once QB
  hits actually score, the disruption bonuses more than offset the sack
  cut, and DL nets **up**.
* ``idp_pass_def`` is **2.52x UP**, the single largest move on the card
  and overwhelmingly a DB stat — but ``idp_int`` is 0.86x down, and the
  net leaves DB essentially flat rather than ahead.
* ``idp_tkl_solo``, the LB volume stat, is 0.92x down against
  ``idp_tkl_ast`` 1.07x up — a net cut on the stat LBs accumulate most,
  which is why LB is lowest under both measurements.

Note that this lands closer to the ORIGINAL #592 record ("DL +7%, LB +3%
relative to DB") on the DL-over-DB ordering, though not on the
magnitudes, and #592's own derivation was never verified.  Agreeing with
an unverified prior is not evidence — the alias mechanism above is.

A second real bug was fixed alongside this, and it is independent of the
alias problem above: ``SAF`` — the nflverse spelling for a safety, 1,468
of the 2025 regular-season rows — was in neither ``POSITION_ALIASES``
nor ``scoring_engine``'s IDP collapse table, so every safety was
silently dropped from the DB cohort, shrinking it from 288 to 188.  Both
defects inflated DB, by different routes: one excluded most of the
cohort, the other credited it with a stat its rivals were not being paid
for.  ``tests/league_comparison/test_position_family_coverage.py`` pins
the position vocabulary against what the feed actually emits.

Scale is meaningless; only the tilt is real
───────────────────────────────────────────
The absolute ratio depends on both rate cards' overall generosity, which
is an artifact of how each commissioner numbered their sheet and says
nothing about player value. Only the *relative* difference between
positions carries information, so the multipliers are normalised to a
mean of 1.0 across the tracked positions. The result re-allocates value
between IDP positions; it never inflates IDP as a whole.

Flagged ON since 2026-07-28
───────────────────────────
``RISKIT_FEATURE_IDP_SCORING_FIT`` defaults to **1**; set it to 0 to roll
back.  Until 2026-07-28 this section still announced the opposite — that
the default was 0 and no operator had asked for the feature — which
stayed behind when the operator did ask and the default flipped in #606.
A stale claim about live behaviour, in the one file a reader would open
to find out.  ``tests/league_intel/test_flag_docs_match_reality.py`` now
compares this paragraph against the registry.

It reaches the OPT-IN league-adjusted lens only, never the default
market board.  Blast radius on the 2026-07-28 board (1,094 rows): 398
IDP rows move — DL n=145 +4.21%, DB n=139 -0.29%, LB n=114 -3.92% — and
zero non-IDP values change.

Two bounds apply to what this can emit.  ``MAX_DEPTH_DRIFT`` rejects a
position whose ratio moves with sample depth (sampling noise), and
``MAX_TILT`` caps the multiplier itself (input corruption).  They catch
disjoint failures and both are needed; see ``MAX_TILT``.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.nfl_data.measurement_provenance import Provenance, scoring_provenance

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "DEPTH_PROBES",
    "MAX_DEPTH_DRIFT",
    "MIN_COHORT_SIZE",
    "PositionFit",
    "ScoringFitMeasurement",
    "measure_positional_scoring_fit",
]

#: Positions this measurement covers. Offence is excluded deliberately:
#: its biggest divergence is the reception-distance banding, which needs
#: a per-player depth histogram from play-by-play and is a separate
#: piece of work. Applying a position-level offence multiplier would
#: paper over that with a number that cannot express it.
TRACKED_POSITIONS: tuple[str, ...] = ("DL", "LB", "DB")

#: Pool depths the stability check probes. A real positional effect is
#: flat across these; a sampling artifact fans out.
DEPTH_PROBES: tuple[int, ...] = (24, 36, 60, 120)

#: Largest spread between the shallowest and deepest probe before a
#: position's multiplier is rejected. Measured drift on 2025 is 0.002
#: (DL), 0.008 (LB), 0.020 (DB); 0.05 is a wide bound that still fails
#: loudly if the cohort ever stops being coherent.
MAX_DEPTH_DRIFT: float = 0.05

#: Below this many scored players a cohort median is not worth trusting.
MIN_COHORT_SIZE: int = 12

#: Hard clamp on the emitted multiplier, mirroring
#: :data:`src.league_intel.reception_fit.MAX_TILT`.
#:
#: **The depth-drift check above does not cover this case, and cannot.**
#: Drift detects a ratio that moves with sample depth — the signature of
#: sampling noise. A corrupted INPUT produces a ratio that is large and
#: perfectly stable, so it sails through: measured with one rate parsed
#: 100x too large, this module returned DL 2.899 / LB 0.050 / DB 0.050,
#: a 57x spread, with all three marked ``trusted`` at drift 0.0000.
#:
#: ``reception_fit`` — written as this module's sibling, and sharing its
#: probe design — already carried exactly this bound, for exactly this
#: reason ("so an upstream data fault cannot express itself as a 3x
#: repricing"). Only one of the two got it. This closes that asymmetry.
#:
#: 0.25 is generous against a measured range of 0.9608-1.0421, so it
#: never engages in normal operation; it exists solely so a data fault
#: cannot reprice every IDP asset on the board by multiples.
MAX_TILT: float = 0.25


@dataclass(frozen=True)
class PositionFit:
    """One position's measured tilt, with the evidence that backs it."""

    position: str
    multiplier: float
    """Mean-normalised across tracked positions. 1.0 means 'no tilt
    relative to the other IDP positions', NOT 'the two rate cards
    agree'."""

    raw_ratio: float
    """Un-normalised median ``mine / baseline``. Diagnostic only — its
    absolute level reflects rate-card generosity, not value."""

    cohort_size: int
    depth_drift: float
    """max-min of the raw ratio across :data:`DEPTH_PROBES`. The
    trustworthiness signal."""

    trusted: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "multiplier": round(self.multiplier, 6),
            "rawRatio": round(self.raw_ratio, 6),
            "cohortSize": self.cohort_size,
            "depthDrift": round(self.depth_drift, 6),
            "trusted": self.trusted,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ScoringFitMeasurement:
    """The whole measurement. Carries its own refusals."""

    positions: dict[str, PositionFit] = field(default_factory=dict)
    season: int | None = None
    measured: bool = False
    reason: str = ""

    provenance: Provenance = field(default_factory=Provenance)
    """What this measurement was computed from.

    Added after the 2026-07-28 correction, in which these multipliers
    shipped with DB and DL inverted because they were measured on a
    scoring card with one alias repaired and a second still unread.
    ``provenance.inputs_complete`` is False in exactly that situation,
    so the number now carries its own warning instead of looking
    identical to a sound one.
    """

    def multiplier_for(self, position: str) -> float:
        """Tilt for ``position``; 1.0 for anything unmeasured or
        untrusted.

        Never raises and never guesses — an unknown position is a no-op,
        because the alternative is applying an IDP tilt to a wide
        receiver.
        """
        fit = self.positions.get(str(position or "").strip().upper())
        if fit is None or not fit.trusted:
            return 1.0
        return fit.multiplier

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "season": self.season,
            "reason": self.reason,
            "positions": {k: v.to_dict() for k, v in sorted(self.positions.items())},
            "provenance": self.provenance.to_dict(),
        }


def _median_ratio(pairs: Sequence[tuple[float, float]], top_n: int | None) -> float | None:
    """Median ``mine / baseline`` over the ``top_n`` players by baseline
    points. ``top_n=None`` uses the whole cohort."""
    if not pairs:
        return None
    ranked = sorted(pairs, key=lambda p: -p[1])
    if top_n is not None:
        ranked = ranked[:top_n]
    ratios = [mine / base for mine, base in ranked if base > 0]
    if not ratios:
        return None
    return float(statistics.median(ratios))


def measure_positional_scoring_fit(
    weekly_rows: Iterable[Mapping[str, Any]],
    my_scoring: Mapping[str, Any] | None,
    baseline_scoring: Mapping[str, Any] | None,
    *,
    season: int | None = None,
    min_baseline_points: float = 20.0,
) -> ScoringFitMeasurement:
    """Measure how this league's scoring tilts value between IDP positions.

    Scores every weekly row under BOTH rate cards via the existing
    :mod:`src.league_comparison.scoring_engine` — the golden-validated
    scorer, not a second implementation of Sleeper scoring — then takes
    each position's median ratio and normalises to a mean of 1.0.

    Refuses rather than guesses. A position whose ratio drifts more than
    :data:`MAX_DEPTH_DRIFT` across :data:`DEPTH_PROBES` is marked
    untrusted and contributes a 1.0 multiplier, because a ratio that
    depends on how deep you sample is measuring sample size, not
    scoring.
    """
    if not my_scoring or not baseline_scoring:
        return ScoringFitMeasurement(
            measured=False, reason="both leagues' scoring_settings are required"
        )

    from src.league_comparison.scoring_engine import (  # noqa: PLC0415 - heavy import
        compute_player_season_scores,
    )
    from src.nfl_data.pbp_weekly import SeasonPbpIndex  # noqa: PLC0415

    rows = list(weekly_rows or [])
    if not rows:
        return ScoringFitMeasurement(measured=False, reason="no weekly rows supplied")

    # Both cards are scored with the play-by-play supplement or neither is.
    # This measures how differently two cards price the same production, and
    # the six reception bands are where they differ most — leaving them at
    # zero on both sides does not cancel, it deletes the signal.
    pbp_for_season = SeasonPbpIndex().for_season
    mine = {
        s.player_id: s
        for s in compute_player_season_scores(
            rows, dict(my_scoring), season=season, pbp_for_season=pbp_for_season
        )
    }
    base = {
        s.player_id: s
        for s in compute_player_season_scores(
            rows, dict(baseline_scoring), season=season, pbp_for_season=pbp_for_season
        )
    }

    cohorts: dict[str, list[tuple[float, float]]] = {p: [] for p in TRACKED_POSITIONS}
    for pid, m in mine.items():
        b = base.get(pid)
        if b is None or m.position not in cohorts:
            continue
        if b.total_points < min_baseline_points:
            continue
        cohorts[m.position].append((float(m.total_points), float(b.total_points)))

    raw: dict[str, tuple[float, float, int]] = {}
    for pos, pairs in cohorts.items():
        full = _median_ratio(pairs, None)
        if full is None or len(pairs) < MIN_COHORT_SIZE:
            continue
        probes = [r for r in (_median_ratio(pairs, n) for n in DEPTH_PROBES) if r is not None]
        drift = (max(probes) - min(probes)) if len(probes) >= 2 else 0.0
        # Anchor on the shallowest usable probe rather than the whole
        # pool: the rosterable players are the ones whose valuation this
        # multiplier will move, and the deep tail is the noisy part.
        anchor = probes[0] if probes else full
        raw[pos] = (anchor, drift, len(pairs))

    if not raw:
        return ScoringFitMeasurement(
            measured=False,
            season=season,
            reason=f"no IDP cohort reached {MIN_COHORT_SIZE} scored players",
        )

    # Normalise to mean 1.0. Only the tilt between positions carries
    # information; the shared level is an artifact of how generously
    # each commissioner numbered their sheet.
    trusted_ratios = [r for r, drift, _ in raw.values() if drift <= MAX_DEPTH_DRIFT]
    mean_ratio = (
        statistics.fmean(trusted_ratios)
        if trusted_ratios
        else statistics.fmean([r for r, _, _ in raw.values()])
    )
    if mean_ratio <= 0:
        return ScoringFitMeasurement(measured=False, season=season, reason="degenerate mean ratio")

    positions: dict[str, PositionFit] = {}
    for pos, (ratio, drift, n) in sorted(raw.items()):
        ok = drift <= MAX_DEPTH_DRIFT
        normalised = (ratio / mean_ratio) if ok else 1.0
        clamped = max(1.0 - MAX_TILT, min(1.0 + MAX_TILT, normalised))
        if clamped != normalised:
            # Only reachable from a corrupted input — see MAX_TILT.  Loud
            # because the clamp keeps the board sane while leaving the
            # underlying fault in place, and a silently-clamped number
            # looks exactly like a measured one.
            _LOGGER.error(
                "scoring_fit multiplier for %s clamped %.4f -> %.4f (bound %.2f). "
                "A tilt this large is not a scoring difference, it is an input "
                "fault; the depth-drift check cannot catch it because a corrupt "
                "rate produces a STABLE ratio. Check the scoring card.",
                pos,
                normalised,
                clamped,
                MAX_TILT,
            )
        positions[pos] = PositionFit(
            position=pos,
            multiplier=clamped,
            raw_ratio=ratio,
            cohort_size=n,
            depth_drift=drift,
            trusted=ok,
            reason=(
                f"median mine/baseline over the top {DEPTH_PROBES[0]} by baseline points; "
                f"stable to {drift:.4f} across depths {DEPTH_PROBES}"
                if ok
                else (
                    f"ratio drifts {drift:.4f} across depths {DEPTH_PROBES} "
                    f"(max {MAX_DEPTH_DRIFT}) — sampling artifact, not a scoring tilt; "
                    "multiplier forced to 1.0"
                )
            ),
        )
        if not ok:
            _LOGGER.warning(
                "scoring_fit: %s rejected, depth drift %.4f > %.4f",
                pos,
                drift,
                MAX_DEPTH_DRIFT,
            )

    prov = scoring_provenance(
        my_scoring,
        baseline_scoring,
        rows_scored=len(rows),
        notes="mean-normalised median ratio, per IDP position family",
    )
    if not prov.inputs_complete:
        # Loud on purpose.  This is the exact condition that produced an
        # inverted DB-vs-DL tilt and shipped it: a scoring rule the
        # engine could read and did not, biasing one position group
        # against another.  A relative measurement cannot absorb an
        # asymmetric input gap.
        _LOGGER.warning(
            "scoring_fit measured on INCOMPLETE inputs: %s unread scoring "
            "rule(s) %s — the multipliers below may be biased between "
            "positions, not merely imprecise",
            len(prov.input_gaps),
            list(prov.input_gaps),
        )

    return ScoringFitMeasurement(
        positions=positions,
        season=season,
        measured=True,
        reason=f"measured over {sum(n for _, _, n in raw.values())} IDP player-seasons",
        provenance=prov,
    )
