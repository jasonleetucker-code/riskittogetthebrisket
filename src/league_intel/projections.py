"""Projection re-scoring + derived categories (LI-6, spec §7).

Turns raw statistical projections into **league-specific** points by
running them through the LI-2 exact scorer, and estimates the categories
this league scores that virtually nobody projects.

Why this module exists
----------------------
The league's scoring has two quirks that make generic "projected fantasy
points" useless here (see ``config/league_intel/`` snapshot):

* **Distance-banded receptions** — ``rec_0_4`` 0.17 … ``rec_40p`` 1.92
  instead of a flat PPR. Two receivers with identical catch totals score
  very differently depending on target depth.
* **Position-keyed first-down bonuses** — ``bonus_fd_qb`` 0.67,
  ``bonus_fd_rb`` / ``bonus_fd_te`` / ``bonus_fd_wr`` 1.0. (The generic
  ``pass_fd`` / ``rush_fd`` / ``rec_fd`` keys are all 0.0 here.)

No audited projection provider supplies either category
(``docs/league-intelligence/DATA_SOURCES.md`` §2), so LI-6 derives them
from realized nflverse play-by-play and labels every estimate with its
provenance tier.

Input reality check
-------------------
**This pipeline is built and tested but currently unfed.** No provider
permits automated access to raw statistical categories, so the only live
input is a human CSV export (``parse_manual_import``). See the boxed
consequence note in DATA_SOURCES.md §4 — do not assume re-scored
projections are flowing into LI-7 until that note says otherwise.

Layering
--------
This module CONSUMES ``src/league_intel/scorer.py`` (LI-2) and never
modifies it. It is pure except for the explicitly-injected PBP row
provider — no network, no clock, no globals.
"""

from __future__ import annotations

import csv
import io
import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .scorer import ScoringBreakdown, score_stat_line

__all__ = [
    "PROVENANCE_TIERS",
    "TIER_CONFIDENCE",
    "DERIVED_CATEGORIES",
    "MANUAL_IMPORT_COLUMNS",
    "CategoryProvenance",
    "PlayerProjection",
    "ScoredProjection",
    "SourceDisagreement",
    "RateProfile",
    "parse_manual_import",
    "build_rate_profiles",
    "derive_categories",
    "score_projection",
    "score_projections",
    "measure_disagreement",
]


# ── Provenance ───────────────────────────────────────────────────────
#: Ordered best → worst. A derived value NEVER outranks a direct one.
PROVENANCE_TIERS: tuple[str, ...] = (
    "direct",  # A — the source projected this category outright
    "derived-player-history",  # B — player's own realized rate × projected volume
    "derived-archetype",  # C — role/archetype cohort rate
    "derived-position",  # D — position-level league average
    "manual",  # E — operator override
)

#: Confidence weight per tier, consumed by LI-7 to scale adjustment
#: strength. Monotonically decreasing A → D; ``manual`` is pinned high
#: because a human asserted it deliberately (and it is audited).
TIER_CONFIDENCE: Mapping[str, float] = {
    "direct": 1.00,
    "derived-player-history": 0.75,
    "derived-archetype": 0.50,
    "derived-position": 0.30,
    "manual": 0.90,
}

#: The Sleeper scoring keys this module can derive when a source omits
#: them. Everything else must arrive directly or not at all — we never
#: invent a volume, only distribute or rate-scale one we were given.
DERIVED_CATEGORIES: tuple[str, ...] = (
    "rec_0_4",
    "rec_5_9",
    "rec_10_19",
    "rec_20_29",
    "rec_30_39",
    "rec_40p",
    "bonus_fd_qb",
    "bonus_fd_rb",
    "bonus_fd_te",
    "bonus_fd_wr",
)

#: Reception distance bands, as (scoring_key, lower_yd, upper_yd).
#: Upper bound is inclusive; ``None`` means open-ended.
_RECEPTION_BANDS: tuple[tuple[str, int, int | None], ...] = (
    ("rec_0_4", 0, 4),
    ("rec_5_9", 5, 9),
    ("rec_10_19", 10, 19),
    ("rec_20_29", 20, 29),
    ("rec_30_39", 30, 39),
    ("rec_40p", 40, None),
)

#: Position → the first-down bonus key this league uses for it.
_FD_BONUS_KEY: Mapping[str, str] = {
    "QB": "bonus_fd_qb",
    "RB": "bonus_fd_rb",
    "TE": "bonus_fd_te",
    "WR": "bonus_fd_wr",
}

#: Position-level fallbacks (tier D). Deliberately conservative
#: league-average shapes derived from realized NFL distributions; they
#: exist so a rookie with no history still scores *something* rather
#: than silently zeroing a category the league pays for.
_POSITION_BAND_SHARES: Mapping[str, Mapping[str, float]] = {
    "WR": {
        "rec_0_4": 0.24,
        "rec_5_9": 0.27,
        "rec_10_19": 0.28,
        "rec_20_29": 0.12,
        "rec_30_39": 0.05,
        "rec_40p": 0.04,
    },
    "TE": {
        "rec_0_4": 0.30,
        "rec_5_9": 0.30,
        "rec_10_19": 0.26,
        "rec_20_29": 0.09,
        "rec_30_39": 0.03,
        "rec_40p": 0.02,
    },
    "RB": {
        "rec_0_4": 0.48,
        "rec_5_9": 0.28,
        "rec_10_19": 0.16,
        "rec_20_29": 0.05,
        "rec_30_39": 0.02,
        "rec_40p": 0.01,
    },
}
#: First downs per opportunity, by position (tier D).
_POSITION_FD_RATE: Mapping[str, float] = {"QB": 0.34, "RB": 0.22, "WR": 0.50, "TE": 0.52}


@dataclass(frozen=True)
class CategoryProvenance:
    """How one category's value for one player was arrived at."""

    category: str
    tier: str
    detail: str = ""

    @property
    def confidence(self) -> float:
        return TIER_CONFIDENCE.get(self.tier, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "tier": self.tier,
            "confidence": self.confidence,
            "detail": self.detail,
        }


@dataclass
class PlayerProjection:
    """A raw-category projection for one player from one source.

    ``stats`` is keyed by **Sleeper scoring keys** (``pass_yd``,
    ``rec``, ``rush_td`` …) — normalization to that vocabulary happens
    at the adapter boundary, never downstream.
    """

    player_name: str
    position: str
    team: str = ""
    source: str = ""
    horizon: str = "ros"  # "ros" | "week"
    week: int | None = None
    stats: dict[str, float] = field(default_factory=dict)
    provenance: dict[str, CategoryProvenance] = field(default_factory=dict)

    def tier_of(self, category: str) -> str:
        p = self.provenance.get(category)
        return p.tier if p else "direct"

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerName": self.player_name,
            "position": self.position,
            "team": self.team,
            "source": self.source,
            "horizon": self.horizon,
            "week": self.week,
            "stats": dict(self.stats),
            "provenance": {k: v.to_dict() for k, v in sorted(self.provenance.items())},
        }


@dataclass
class ScoredProjection:
    """A projection after re-scoring under the league's exact rules."""

    projection: PlayerProjection
    breakdown: ScoringBreakdown
    confidence: float

    @property
    def points(self) -> float:
        return self.breakdown.total_points

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerName": self.projection.player_name,
            "position": self.projection.position,
            "source": self.projection.source,
            "horizon": self.projection.horizon,
            "week": self.projection.week,
            "leaguePoints": round(self.points, 4),
            "confidence": round(self.confidence, 4),
            "breakdown": self.breakdown.to_dict(),
            "provenance": {k: v.to_dict() for k, v in sorted(self.projection.provenance.items())},
        }


# ── Manual-import adapter ────────────────────────────────────────────
#: The import contract. A human exporting from a subscription they hold
#: needs to know exactly what to supply — this IS that specification,
#: and ``docs/league-intelligence/DATA_SOURCES.md`` §6 renders it for
#: operators.
#:
#: Required identity columns, then any subset of Sleeper scoring keys.
#: Unknown columns are reported, never silently dropped.
MANUAL_IMPORT_COLUMNS: Mapping[str, str] = {
    "player_name": "required — display name; resolved via identity ladder downstream",
    "position": "required — QB/RB/WR/TE/K plus IDP positions",
    "team": "optional — NFL team abbreviation, improves identity resolution",
    "week": "optional — integer for weekly rows; omit for ROS",
}


def parse_manual_import(
    csv_text: str,
    *,
    source: str,
    horizon: str = "ros",
    scoring_keys: Iterable[str] | None = None,
) -> tuple[list[PlayerProjection], list[str]]:
    """Parse an operator CSV of raw categories into projections.

    This is the unblocked ingestion path: every source in the audit is
    either subscriber-gated or licence-gated, so the file a human
    exports by hand is the input the pipeline is designed around. A
    future licensed feed becomes a thin adapter that emits the same
    ``PlayerProjection`` objects.

    Columns: the identity columns in :data:`MANUAL_IMPORT_COLUMNS`,
    plus any Sleeper scoring keys the export carries. When
    ``scoring_keys`` is supplied (normally the league config's keys),
    columns outside identity ∪ scoring_keys are collected into the
    returned warning list rather than dropped in silence — an
    unrecognized column usually means a mis-mapped export header, and
    silently ignoring it is how a category goes quietly missing.

    Returns ``(projections, warnings)``. Never raises on a bad row: a
    malformed row is skipped with a warning so one bad line can't cost
    an entire import.
    """
    warnings: list[str] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        return [], ["empty CSV: no header row"]

    headers = [h.strip() for h in reader.fieldnames if h and h.strip()]
    identity = set(MANUAL_IMPORT_COLUMNS)
    known = set(scoring_keys) if scoring_keys is not None else None

    stat_columns: list[str] = []
    for h in headers:
        if h in identity:
            continue
        if known is not None and h not in known:
            warnings.append(
                f"column {h!r} is not a league scoring key — ignored "
                "(check the export's header mapping)"
            )
            continue
        stat_columns.append(h)

    if not stat_columns:
        warnings.append("no recognized stat columns — nothing to score")

    out: list[PlayerProjection] = []
    for lineno, raw in enumerate(reader, start=2):
        name = str(raw.get("player_name") or "").strip()
        position = str(raw.get("position") or "").strip().upper()
        if not name or not position:
            warnings.append(f"row {lineno}: missing player_name or position — skipped")
            continue

        week: int | None = None
        raw_week = str(raw.get("week") or "").strip()
        if raw_week:
            try:
                week = int(float(raw_week))
            except ValueError:
                warnings.append(f"row {lineno}: unparseable week {raw_week!r} — treated as ROS")

        stats: dict[str, float] = {}
        provenance: dict[str, CategoryProvenance] = {}
        for col in stat_columns:
            rawval = str(raw.get(col) or "").strip()
            if not rawval:
                continue
            try:
                val = float(rawval)
            except ValueError:
                warnings.append(f"row {lineno}: non-numeric {col}={rawval!r} — skipped")
                continue
            if not math.isfinite(val):
                warnings.append(f"row {lineno}: non-finite {col} — skipped")
                continue
            stats[col] = val
            provenance[col] = CategoryProvenance(col, "direct", f"projected by {source}")

        if not stats:
            warnings.append(f"row {lineno}: no usable stats for {name} — skipped")
            continue

        out.append(
            PlayerProjection(
                player_name=name,
                position=position,
                team=str(raw.get("team") or "").strip().upper(),
                source=source,
                horizon="week" if week is not None else horizon,
                week=week,
                stats=stats,
                provenance=provenance,
            )
        )
    return out, warnings


# ── Derived categories ───────────────────────────────────────────────
@dataclass(frozen=True)
class RateProfile:
    """Realized per-player rates used to derive unprojected categories.

    Built from nflverse play-by-play — the same substrate
    ``src/nfl_data/opportunity_stats.py`` already parses ``first_down``
    out of, so this reuses ingested data rather than adding a feed.
    """

    band_shares: Mapping[str, float] = field(default_factory=dict)
    fd_per_reception: float | None = None
    fd_per_rush: float | None = None
    fd_per_completion: float | None = None
    sample_size: int = 0

    def is_usable(self, *, min_sample: int) -> bool:
        return self.sample_size >= min_sample


def build_rate_profiles(
    pbp_rows: Iterable[Mapping[str, Any]],
    *,
    min_sample: int = 20,
) -> dict[str, RateProfile]:
    """Build per-player realized rate profiles from play-by-play.

    Consumes the same row shape ``opportunity_stats.build_opportunity_from_pbp``
    reads (``receiver_player_name``, ``rusher_player_name``,
    ``complete_pass``, ``first_down``, ``yards_gained``), so a caller
    can hand it the rows it already fetched for opportunity stats — no
    second ingestion.

    Keyed by player name; identity resolution to Sleeper/GSIS ids
    happens at the caller boundary via ``src/identity/unified_mapper.py``.
    """
    rec_bands: dict[str, dict[str, int]] = {}
    rec_total: dict[str, int] = {}
    rec_fd: dict[str, int] = {}
    rush_att: dict[str, int] = {}
    rush_fd: dict[str, int] = {}
    cmp_total: dict[str, int] = {}
    cmp_fd: dict[str, int] = {}

    for play in pbp_rows or []:
        first_down = 1 if _num(play.get("first_down")) else 0
        yards = _num(play.get("yards_gained"))

        receiver = _name(play.get("receiver_player_name"))
        if receiver and _num(play.get("complete_pass")):
            rec_total[receiver] = rec_total.get(receiver, 0) + 1
            band = _band_for(yards)
            if band:
                rec_bands.setdefault(receiver, {})
                rec_bands[receiver][band] = rec_bands[receiver].get(band, 0) + 1
            rec_fd[receiver] = rec_fd.get(receiver, 0) + first_down
            # A completion is also a passer event.
            passer = _name(play.get("passer_player_name"))
            if passer:
                cmp_total[passer] = cmp_total.get(passer, 0) + 1
                cmp_fd[passer] = cmp_fd.get(passer, 0) + first_down

        rusher = _name(play.get("rusher_player_name"))
        if rusher:
            rush_att[rusher] = rush_att.get(rusher, 0) + 1
            rush_fd[rusher] = rush_fd.get(rusher, 0) + first_down

    players = set(rec_total) | set(rush_att) | set(cmp_total)
    profiles: dict[str, RateProfile] = {}
    for p in players:
        recs = rec_total.get(p, 0)
        shares: dict[str, float] = {}
        if recs > 0:
            counts = rec_bands.get(p, {})
            for key, _lo, _hi in _RECEPTION_BANDS:
                shares[key] = counts.get(key, 0) / recs
        profiles[p] = RateProfile(
            band_shares=shares,
            fd_per_reception=(rec_fd.get(p, 0) / recs) if recs else None,
            fd_per_rush=(rush_fd.get(p, 0) / rush_att[p]) if rush_att.get(p) else None,
            fd_per_completion=(cmp_fd.get(p, 0) / cmp_total[p]) if cmp_total.get(p) else None,
            sample_size=max(recs, rush_att.get(p, 0), cmp_total.get(p, 0)),
        )
    return profiles


def derive_categories(
    projection: PlayerProjection,
    *,
    profiles: Mapping[str, RateProfile] | None = None,
    archetype_profiles: Mapping[str, RateProfile] | None = None,
    min_sample: int = 20,
    archetype_of: Any = None,
) -> PlayerProjection:
    """Fill in league-scored categories the source didn't project.

    Rules (spec §7 / DATA_SOURCES §3):

    1. **Volume comes from the source, rate comes from history.** If the
       source didn't project ``rec``, we do not synthesize reception
       first downs or bands from nothing — the category stays absent.
    2. A category the source DID project is left alone at tier
       ``direct``; derivation never overwrites a direct value.
    3. Tier ladder per player: own history (B) → archetype cohort (C)
       → position average (D).

    Returns a NEW projection; the input is not mutated.
    """
    stats = dict(projection.stats)
    provenance = dict(projection.provenance)
    pos = (projection.position or "").upper()

    own = (profiles or {}).get(projection.player_name)
    arche = None
    if archetype_of is not None and archetype_profiles:
        try:
            arche = archetype_profiles.get(archetype_of(projection))
        except Exception:  # noqa: BLE001 — a bad classifier must not break scoring
            arche = None

    # ── Reception distance bands ─────────────────────────────────────
    receptions = stats.get("rec")
    bands_present = [k for k, _lo, _hi in _RECEPTION_BANDS if k in stats]
    if receptions and receptions > 0 and not bands_present:
        shares, tier, detail = _pick_band_shares(pos, own, arche, min_sample)
        if shares:
            for key, share in shares.items():
                stats[key] = receptions * share
                provenance[key] = CategoryProvenance(key, tier, detail)

    # ── Position-keyed first-down bonus ──────────────────────────────
    fd_key = _FD_BONUS_KEY.get(pos)
    if fd_key and fd_key not in stats:
        opportunities, rate, tier, detail = _first_down_estimate(pos, stats, own, arche, min_sample)
        if opportunities and rate is not None:
            stats[fd_key] = opportunities * rate
            provenance[fd_key] = CategoryProvenance(fd_key, tier, detail)

    return PlayerProjection(
        player_name=projection.player_name,
        position=projection.position,
        team=projection.team,
        source=projection.source,
        horizon=projection.horizon,
        week=projection.week,
        stats=stats,
        provenance=provenance,
    )


def _pick_band_shares(
    pos: str,
    own: RateProfile | None,
    arche: RateProfile | None,
    min_sample: int,
) -> tuple[Mapping[str, float], str, str]:
    if own and own.band_shares and own.is_usable(min_sample=min_sample):
        return (
            own.band_shares,
            "derived-player-history",
            f"own realized band mix over {own.sample_size} receptions",
        )
    if arche and arche.band_shares:
        return (
            arche.band_shares,
            "derived-archetype",
            f"archetype cohort band mix ({arche.sample_size} receptions)",
        )
    shares = _POSITION_BAND_SHARES.get(pos)
    if shares:
        return shares, "derived-position", f"{pos} league-average band mix"
    return {}, "derived-position", ""


def _first_down_estimate(
    pos: str,
    stats: Mapping[str, float],
    own: RateProfile | None,
    arche: RateProfile | None,
    min_sample: int,
) -> tuple[float, float | None, str, str]:
    """Opportunities × first-down rate for the position's bonus key."""
    if pos == "QB":
        opportunities = float(stats.get("pass_cmp") or 0.0)
        own_rate = own.fd_per_completion if own else None
        arche_rate = arche.fd_per_completion if arche else None
        unit = "completions"
    elif pos == "RB":
        # RBs earn first downs on the ground AND through the air; the
        # league pays one bonus per first down regardless of route.
        rush = float(stats.get("rush_att") or 0.0)
        rec = float(stats.get("rec") or 0.0)
        opportunities = rush + rec
        own_rate = _blend_rate(own, rush, rec) if own else None
        arche_rate = _blend_rate(arche, rush, rec) if arche else None
        unit = "carries + receptions"
    else:  # WR / TE
        opportunities = float(stats.get("rec") or 0.0)
        own_rate = own.fd_per_reception if own else None
        arche_rate = arche.fd_per_reception if arche else None
        unit = "receptions"

    if opportunities <= 0:
        return 0.0, None, "derived-position", ""
    if own_rate is not None and own and own.is_usable(min_sample=min_sample):
        return (
            opportunities,
            own_rate,
            "derived-player-history",
            f"own first-down rate over {own.sample_size} {unit}",
        )
    if arche_rate is not None:
        return (
            opportunities,
            arche_rate,
            "derived-archetype",
            f"archetype first-down rate per {unit}",
        )
    rate = _POSITION_FD_RATE.get(pos)
    return (
        opportunities,
        rate,
        "derived-position",
        f"{pos} league-average first-down rate per {unit}",
    )


def _blend_rate(profile: RateProfile | None, rush: float, rec: float) -> float | None:
    """Opportunity-weighted blend of a back's rush + receiving FD rates."""
    if profile is None:
        return None
    total = rush + rec
    if total <= 0:
        return None
    parts: list[tuple[float, float]] = []
    if rush > 0 and profile.fd_per_rush is not None:
        parts.append((rush, profile.fd_per_rush))
    if rec > 0 and profile.fd_per_reception is not None:
        parts.append((rec, profile.fd_per_reception))
    if not parts:
        return None
    weight = sum(w for w, _ in parts)
    return sum(w * r for w, r in parts) / weight


# ── Re-scoring ───────────────────────────────────────────────────────
def score_projection(projection: PlayerProjection, config: Any) -> ScoredProjection:
    """Re-score one projection under the league's exact rules.

    Confidence is the **volume-weighted** mean of the contributing
    categories' tier confidences: a projection whose points come mostly
    from directly-projected categories scores near 1.0 even if a small
    derived category rides along, while one leaning on tier-D estimates
    is marked down. Weighting by |awarded points| rather than category
    count is what keeps a rounding-error category from dragging an
    otherwise-direct projection down.
    """
    breakdown = score_stat_line(projection.stats, config)
    weighted = 0.0
    total_weight = 0.0
    for comp in breakdown.components:
        weight = abs(comp.awarded_points)
        if weight <= 0:
            continue
        tier = projection.tier_of(comp.scoring_key)
        weighted += weight * TIER_CONFIDENCE.get(tier, 0.0)
        total_weight += weight
    confidence = (weighted / total_weight) if total_weight > 0 else 0.0
    return ScoredProjection(projection=projection, breakdown=breakdown, confidence=confidence)


def score_projections(
    projections: Iterable[PlayerProjection], config: Any
) -> list[ScoredProjection]:
    """Re-score many projections, preserving input order."""
    return [score_projection(p, config) for p in projections]


# ── Source disagreement ──────────────────────────────────────────────
@dataclass(frozen=True)
class SourceDisagreement:
    """Cross-source spread for one player, in league points.

    Consumed by LI-7 to scale adjustment strength: wide disagreement
    means the projection signal is weak evidence and the adjustment
    should shrink toward the consensus anchor.

    ``agreement`` is the headline scalar — 1.0 = perfect agreement,
    falling toward 0 as the coefficient of variation grows. LI-7 can
    multiply an adjustment by it directly.
    """

    player_name: str
    position: str
    source_count: int
    mean_points: float
    median_points: float
    stdev_points: float
    spread_points: float
    coefficient_of_variation: float
    agreement: float
    confidence: float
    per_source: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerName": self.player_name,
            "position": self.position,
            "sourceCount": self.source_count,
            "meanPoints": round(self.mean_points, 4),
            "medianPoints": round(self.median_points, 4),
            "stdevPoints": round(self.stdev_points, 4),
            "spreadPoints": round(self.spread_points, 4),
            "coefficientOfVariation": round(self.coefficient_of_variation, 4),
            "agreement": round(self.agreement, 4),
            "confidence": round(self.confidence, 4),
            "perSource": {k: round(v, 4) for k, v in sorted(self.per_source.items())},
        }


def measure_disagreement(
    scored: Sequence[ScoredProjection],
) -> list[SourceDisagreement]:
    """Measure per-player cross-source spread over re-scored points.

    Only meaningful with 2+ sources for a player; single-source players
    are emitted with ``source_count=1``, zero spread, and
    ``agreement=0.0`` — **not** 1.0. One source agreeing with itself is
    an absence of evidence, not consensus, and LI-7 must not read it as
    a licence to adjust hard.

    Sorted by descending spread: the most contested players first, which
    is the order a human reviewing the signal wants.
    """
    by_player: dict[tuple[str, str], dict[str, float]] = {}
    for s in scored:
        key = (s.projection.player_name, (s.projection.position or "").upper())
        by_player.setdefault(key, {})[s.projection.source or "unknown"] = s.points

    out: list[SourceDisagreement] = []
    for (name, pos), per_source in by_player.items():
        values = list(per_source.values())
        n = len(values)
        mean = statistics.fmean(values)
        median = statistics.median(values)
        stdev = statistics.pstdev(values) if n > 1 else 0.0
        spread = (max(values) - min(values)) if n > 1 else 0.0
        cv = (stdev / abs(mean)) if mean else 0.0
        if n < 2:
            agreement = 0.0
        else:
            # 1 / (1 + cv) decays smoothly and never goes negative;
            # cv = 0 → 1.0, cv = 1 (stdev equals the mean) → 0.5.
            agreement = 1.0 / (1.0 + cv)
        out.append(
            SourceDisagreement(
                player_name=name,
                position=pos,
                source_count=n,
                mean_points=mean,
                median_points=median,
                stdev_points=stdev,
                spread_points=spread,
                coefficient_of_variation=cv,
                agreement=agreement,
                confidence=agreement if n >= 2 else 0.0,
                per_source=per_source,
            )
        )
    out.sort(key=lambda d: (-d.spread_points, d.player_name))
    return out


# ── helpers ──────────────────────────────────────────────────────────
def _num(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def _name(value: Any) -> str:
    return str(value or "").strip()


def _band_for(yards: float) -> str | None:
    for key, lo, hi in _RECEPTION_BANDS:
        if yards >= lo and (hi is None or yards <= hi):
            return key
    # Negative-yardage receptions fall into the shortest band — the
    # league pays the 0-4 rate for them.
    return "rec_0_4" if yards < 0 else None
