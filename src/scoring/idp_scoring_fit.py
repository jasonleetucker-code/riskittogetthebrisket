"""IDP scoring-fit pipeline (Phase 1).

Surfaces a per-row signal — ``idpScoringFitDelta`` — that captures
how much THIS league's scoring rules over- or under-reward an IDP
relative to the 19-source consensus market value.

Pipeline
────────
For each IDP player on the live board:

1. Pull the player's defensive stat history for the trailing 3
   seasons via ``src.nfl_data.fetch_weekly_defensive_stats``.
2. Score those weeks under the active league's
   :class:`ScoringConfig` via ``realized_points.compute_weekly_points``
   — this is the "stacked scoring matters" insight realized in raw
   point data (a 7-yard solo sack credits sack + sack_yards + QB hit
   + TFL + solo tackle simultaneously when each is set).
3. Build a ``PlayerSeasonRow`` per player using a dynasty-weighted
   blend of the trailing 3 seasons (``0.55 * Y1 + 0.30 * Y2 + 0.15 * Y3``).
4. Pass through ``replacement_level.vorp_table`` to get per-player
   VORP and tier.
5. Quantile-map the VORP onto the consensus value scale using the
   existing IDP Hill master curve — not a new fit, just the existing
   ``percentile_to_value`` keyed to ``scope="IDP"``.
6. The signal we ship is ``idpScoringFitDelta`` =
   ``scoringFitValue - rankDerivedValue``.  Positive means the
   league's scoring would rank this player higher than the consensus
   does (buy-low candidate).  Negative means the league's scoring
   ranks them lower (sell-high candidate).

Mid-season ramp (graceful by construction)
──────────────────────────────────────────
The pipeline reads whatever realized weeks exist — it does NOT gate
on a fixed ``years_exp`` threshold.  The confidence label scales with
the realized sample, with the synthetic baseline only applied at zero
realized games:

* **Pre-season rookie** (0 weeks): synthetic tier from the rookie
  archetype baseline (see below), ``confidence = "synthetic"``.
  ``idpScoringFitDelta`` IS computed from the synthetic — flagged
  with ``synthetic=true`` so the lens can show a separate icon.
* **Week 4 rookie** (4 games): realized PPG, ``confidence = "low"``.
* **Week 12 rookie** (12 games): realized PPG, ``confidence = "medium"``.
* **Year 2** (one full Y1 history, 17+ games): realized PPG,
  ``confidence = "high"``.

The transition is automatic.  As soon as any nflverse weekly row
exists for a player, the synthetic is bypassed in favor of realized
production.

Rookie archetype baseline (synthetic)
─────────────────────────────────────
For pre-season rookies (zero realized weeks), Phase 1 substitutes a
**draft-capital-derived synthetic**: "a first-rounder EDGE produces
like the average rookie EDGE drafted in the first round across the
trailing 3 seasons under THIS league's scoring."

Construction:

1. Walk each season in ``weekly_rows_by_season`` (the trailing-3-yr
   corpus we already fetch for veterans).
2. Use the nflverse ``id_map`` (players.csv) to identify which gsis_id
   players were ROOKIES in that season — i.e. ``rookie_season == year``
   AND ``draft_round`` is set.
3. For each historical rookie, score their season under the active
   ``ScoringConfig``, divide by games played → rookie-year PPG.
4. Bucket by ``(position, draft_round)`` and average.

For a current rookie on the live board:

* Cross-walk ``playerId`` (Sleeper) → ``gsis_id`` (via the Sleeper
  ``/v1/players/nfl`` payload, which embeds ``gsis_id`` per player).
* Look up the rookie's ``draft_round`` from nflverse players.csv.
* Look up the cohort baseline at ``(position, draft_round)``.
* If found, stamp a synthetic row.  If not found (UDFA, late-round
  with no cohort data), stamp the rookie sentinel.

What this module does NOT touch
──────────────────────────────
* ``rankDerivedValue`` — the live consensus value is unchanged.
* Buy/Sell signals — the diagnostic surfaces only on a sortable
  rankings lens.
* Trade builder, trade suggestions, trade finder — none consume the
  new fields in Phase 1.

Phase 2 layers ESPN + Clay projections on top of the realized history;
Phase 3 introduces the multiplier stack and the bounded blend that
finally lets ``scoringFitDelta`` influence ``rankDerivedValue``.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from src.canonical.player_valuation import (
    IDP_HILL_PERCENTILE_C,
    IDP_HILL_PERCENTILE_S,
    percentile_to_value,
)
from src.nfl_data import realized_points as _realized
from src.scoring.replacement_level import (
    PlayerSeasonRow,
    starter_slot_counts,
    vorp_table,
)

_LOGGER = logging.getLogger(__name__)

# Dynasty year-weights.  Heavily front-loaded but not collapsed onto
# a single year — accommodates one-year-spike outliers (Anthony Walker
# in 2022, Brandon Graham in 2020) without over-discounting prime
# producers' multi-year track records.
#
# These are intentionally NOT position-specific in Phase 1.  The
# proposal's per-position weights (CB 70/22/8, EDGE 55/30/15, etc.)
# require the multiplier stack; in Phase 1 we use a single weighting
# and let the consensus blend handle position-specific dynasty curves.
_YEAR_WEIGHTS = (0.55, 0.30, 0.15)


@dataclass(frozen=True)
class IdpFitRow:
    """The per-IDP scoring-fit output, ready to stamp on a player row.

    All numeric fields are float-or-None; the API contract serialises
    None → JSON null which the frontend renders as ``—``.
    """
    player_id: str
    position: str
    vorp: float | None
    tier: str
    delta: float | None
    confidence: str
    # Diagnostic — exposed as ``meta`` for debugging.  Not stamped on
    # the contract row.
    weighted_ppg: float | None
    games_used: int
    # When True, the ``vorp`` / ``tier`` / ``delta`` were derived from
    # the rookie archetype baseline (cohort PPG by position +
    # draft_round) rather than from realized stats.  Stamped on the
    # row so the frontend lens can show a "synthetic" badge.
    synthetic: bool = False
    draft_round: int | None = None
    # Top stat categories driving the player's realized PPG across
    # the trailing-3-yr corpus.  Each entry is
    # ``{"label", "stat_total", "points_total", "share"}``.  Empty list
    # for synthetic rows (no realized data) and for rookies (handled
    # via the cohort baseline).  Rendered in the player popup so users
    # see WHY a player is fit-positive — "Sacks: 14 → 56 pts (32%)".
    top_stats: tuple[dict[str, Any], ...] = ()


# ── Tier mapping ──────────────────────────────────────────────────
_TIER_THRESHOLDS = (
    # (label, lower_bound_in_vorp_per_game)
    ("elite", 6.0),
    ("starter_plus", 3.0),
    ("starter", 1.0),
    ("fringe", -2.0),
)


def _tier_for_vorp(vorp_per_game: float) -> str:
    for label, lower in _TIER_THRESHOLDS:
        if vorp_per_game >= lower:
            return label
    return "below_replacement"


# ── Confidence mapping ────────────────────────────────────────────
def _confidence_for_history(seasons_with_data: int, total_games: int) -> str:
    """Confidence label scaled by realized sample size.

    Designed to match the mid-season ramp the proposal expects:

    * ``high``    — Year 2+ (one full season's history, 17+ games)
                    OR 2+ seasons of any duration
    * ``medium``  — 12+ games (near-full season)
    * ``low``     — 4+ games OR 1+ season with any data
    * ``none``    — no realized games (rookie / negligible sample)

    Reading: a Week-4 rookie lands at ``low`` (4 games), a Week-12
    rookie at ``medium`` (12 games), a Year-2 player at ``high``
    (full Y1 history).  The synthetic baseline is applied only when
    this returns ``none``.
    """
    if total_games >= 17 or seasons_with_data >= 2:
        return "high"
    if total_games >= 12:
        return "medium"
    if total_games >= 4 or (seasons_with_data >= 1 and total_games > 0):
        return "low"
    return "none"


# ── Dynasty-weighted realized PPG ─────────────────────────────────
def build_realized_3yr_ppg(
    player_id: str,
    position: str,
    scoring_settings: dict[str, Any],
    *,
    weekly_rows_by_season: dict[int, list[dict[str, Any]]],
) -> tuple[float | None, int, int, float]:
    """Return ``(weighted_ppg, seasons_with_data, total_games,
    total_points)`` for one IDP.

    ``weekly_rows_by_season`` is the trailing-3-year corpus already
    fetched and grouped by season — keyed by season int (e.g. 2024,
    2023, 2022).  The most recent season is weighted highest.

    Returns ``(None, 0, 0, 0.0)`` for a rookie / no-history player so
    the orchestrator can mark them with the rookie sentinel tier.
    """
    # Walk seasons newest → oldest so the year_weights line up with
    # the proposal's `Y1 = last_season, Y2 = prior, Y3 = prior-1`.
    sorted_seasons = sorted(weekly_rows_by_season.keys(), reverse=True)
    # Per-season stat-row count + cumulative points.
    season_ppg: list[tuple[int, float, int]] = []  # (season, ppg, games)
    total_games = 0
    total_points = 0.0
    for idx, season in enumerate(sorted_seasons[:3]):
        weeks = [
            row for row in weekly_rows_by_season.get(season) or []
            if str(row.get("player_id") or row.get("player_id_gsis") or "") == player_id
        ]
        if not weeks:
            continue
        season_points = 0.0
        season_games = 0
        for row in weeks:
            rp = _realized.compute_weekly_points(
                row, scoring_settings, position=position
            )
            if rp is None:
                continue
            # A 0-point week still counts as a game played; threshold
            # `0.0` would drop bye-week zero rows but those don't have
            # a stat row in nflverse anyway.
            season_points += rp.fantasy_points
            season_games += 1
        if season_games == 0:
            continue
        ppg = season_points / season_games
        season_ppg.append((season, ppg, season_games))
        total_games += season_games
        total_points += season_points

    if not season_ppg:
        return None, 0, 0, 0.0

    # Weighted PPG.  When fewer than 3 seasons of data, renormalize
    # the available weights so we don't silently penalise a sophomore
    # for having no Y3 data.
    used_weights = list(_YEAR_WEIGHTS[: len(season_ppg)])
    weight_sum = sum(used_weights) or 1.0
    weighted_ppg = sum(
        ppg * (w / weight_sum)
        for (_season, ppg, _games), w in zip(season_ppg, used_weights)
    )

    return weighted_ppg, len(season_ppg), total_games, total_points


def aggregate_stat_contributions(
    player_id: str,
    position: str,
    scoring_settings: dict[str, Any],
    *,
    weekly_rows_by_season: dict[int, list[dict[str, Any]]],
    top_n: int = 4,
) -> list[dict[str, Any]]:
    """Return the top-N stat categories driving a player's realized
    fantasy points across the trailing-3-yr corpus.

    Each entry: ``{"label", "stat_total", "points_total", "share"}``.
    ``share`` is the fraction of total points this category
    contributed (0.0-1.0).  Sorted by absolute points contribution
    descending — so big negatives surface too.

    Used by the player popup to render WHY a player is fit-positive
    or fit-negative under the league's scoring — so the user sees
    "Sacks: 14 → 56 pts (32% of total)" instead of just
    "+7695 vs market".  The labels match what
    ``compute_weekly_points`` emits ("Sack", "QB Hit", "Solo Tkl",
    "TFL", "PD", "INT", etc.).

    Returns ``[]`` when the player has no realized weeks in the corpus.
    """
    by_label_stat: dict[str, float] = defaultdict(float)
    by_label_points: dict[str, float] = defaultdict(float)
    grand_total = 0.0
    for _season, weekly_rows in (weekly_rows_by_season or {}).items():
        for row in weekly_rows or []:
            row_pid = str(row.get("player_id") or row.get("player_id_gsis") or "")
            if row_pid != player_id:
                continue
            rp = _realized.compute_weekly_points(
                row, scoring_settings, position=position
            )
            if rp is None:
                continue
            for label, stat, contribution in rp.breakdown:
                by_label_stat[str(label)] += float(stat or 0)
                by_label_points[str(label)] += float(contribution or 0)
                grand_total += float(contribution or 0)
    if not by_label_points or grand_total == 0:
        return []
    out: list[dict[str, Any]] = []
    for label, points in by_label_points.items():
        if points == 0:
            continue
        out.append({
            "label": label,
            "stat_total": round(by_label_stat[label], 1),
            "points_total": round(points, 1),
            "share": round(points / grand_total, 3),
        })
    out.sort(key=lambda e: -abs(e["points_total"]))
    return out[:top_n]


# ── Rookie archetype baseline (draft-capital-derived synthetic) ────
def build_rookie_archetype_baseline(
    weekly_rows_by_season: dict[int, list[dict[str, Any]]],
    id_map_rows: list[dict[str, Any]] | None,
    scoring_settings: dict[str, Any],
) -> dict[tuple[str, int], float]:
    """Build the cohort lookup ``(position, draft_round) → avg
    rookie-year PPG`` under the active league's scoring.

    Strategy: walk the trailing-3-yr corpus, identify every
    rookie-season instance (where the player's ``rookie_season`` in
    nflverse players.csv matches the row's season), score that season
    under THIS league's rules, then average per-game PPG by
    (position, draft_round).

    Returns ``{}`` if either the corpus or the id-map is missing —
    callers must treat that as "no synthetic available, fall back to
    sentinel".

    Why average and not median: with ~5 rookies per (position, round)
    bucket per year × 3 years = ~15 samples, the mean is preferable;
    medians collapse onto a single sample's PPG too easily at this
    sample size.
    """
    if not weekly_rows_by_season or not id_map_rows or not scoring_settings:
        return {}

    # Build gsis_id → (position, draft_round, rookie_season) lookup
    # from the id_map.  Only include rows with a resolvable rookie
    # season (rookie_season OR draft_year) AND a draft_round in [1,7]
    # — UDFAs and players with missing draft data are skipped (they
    # fall back to the sentinel).
    id_map: dict[str, tuple[str, int, int]] = {}
    for row in id_map_rows:
        gsis = str(row.get("gsis_id") or "").strip()
        if not gsis:
            continue
        rs_int = _id_map_rookie_season(row)
        draft_round = row.get("draft_round")
        position = str(row.get("position") or "").upper()
        if not position or rs_int is None or draft_round is None:
            continue
        try:
            if isinstance(draft_round, float) and draft_round != draft_round:
                continue
            dr_int = int(draft_round)
        except (TypeError, ValueError):
            continue
        if dr_int < 1 or dr_int > 7:
            continue
        if not _realized._is_idp_position(position):
            continue
        id_map[gsis] = (position, dr_int, rs_int)

    if not id_map:
        return {}

    # Aggregate per-(position, round) PPG samples across all seasons.
    bucket_samples: dict[tuple[str, int], list[float]] = defaultdict(list)
    for season, weekly_rows in weekly_rows_by_season.items():
        # Group rows by gsis_id for this season.
        rows_by_gsis: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in weekly_rows or []:
            gsis = str(row.get("player_id") or row.get("player_id_gsis") or "").strip()
            if not gsis:
                continue
            rows_by_gsis[gsis].append(row)
        # For each player who was a rookie in THIS season, score their
        # weeks and contribute to the (position, round) bucket.
        for gsis, weeks in rows_by_gsis.items():
            mapping = id_map.get(gsis)
            if mapping is None:
                continue
            position, draft_round, rookie_season = mapping
            if int(rookie_season) != int(season):
                continue
            season_points = 0.0
            season_games = 0
            for row in weeks:
                rp = _realized.compute_weekly_points(
                    row, scoring_settings, position=position
                )
                if rp is None:
                    continue
                season_points += rp.fantasy_points
                season_games += 1
            if season_games == 0:
                continue
            bucket_samples[(position, draft_round)].append(
                season_points / season_games
            )

    # Average per bucket.  Buckets with fewer than 2 samples are
    # dropped as too thin to be a useful synthetic.
    out: dict[tuple[str, int], float] = {}
    for key, samples in bucket_samples.items():
        if len(samples) < 2:
            continue
        out[key] = sum(samples) / len(samples)
    return out


def _resolve_rookie_draft_round(
    sleeper_player_id: str,
    sleeper_to_gsis: dict[str, str] | None,
    gsis_to_draft: dict[str, tuple[str, int, int]] | None,
) -> tuple[int | None, int | None]:
    """Return ``(draft_round, rookie_season)`` for a Sleeper player_id
    or ``(None, None)`` if the cross-walk is missing or the player
    isn't a drafted rookie.

    Two-hop lookup:

    1. ``sleeper_to_gsis[sleeper_id]`` → gsis_id (from Sleeper API)
    2. ``gsis_to_draft[gsis_id]`` → (position, draft_round,
       rookie_season) (from nflverse players.csv)
    """
    if not sleeper_player_id or not sleeper_to_gsis or not gsis_to_draft:
        return None, None
    gsis = sleeper_to_gsis.get(str(sleeper_player_id))
    if not gsis:
        return None, None
    mapping = gsis_to_draft.get(str(gsis))
    if mapping is None:
        return None, None
    _pos, draft_round, rookie_season = mapping
    return draft_round, rookie_season


def _id_map_rookie_season(row: dict[str, Any]) -> int | None:
    """Resolve the rookie season for a player from the id_map.

    * ``nflverse_direct`` players.csv has ``rookie_season`` directly.
    * ``nfl_data_py.import_ids()`` has ``draft_year`` instead.  We use
      that as a proxy — for non-redshirt non-holdout players (>99% of
      the population) draft_year IS rookie_season.

    Returns ``None`` when neither field is parseable.
    """
    candidates = (row.get("rookie_season"), row.get("draft_year"))
    for raw in candidates:
        if raw is None:
            continue
        try:
            if isinstance(raw, float) and raw != raw:  # nan
                continue
            iv = int(raw)
            if 2000 <= iv <= 2050:
                return iv
        except (TypeError, ValueError):
            continue
    return None


def _build_gsis_to_draft(
    id_map_rows: list[dict[str, Any]] | None,
) -> dict[str, tuple[str, int, int]]:
    """Build the gsis → (position, draft_round, rookie_season) index
    used for live-rookie lookups.

    Same filter as :func:`build_rookie_archetype_baseline` — UDFAs
    and rows with missing fields are skipped.
    """
    out: dict[str, tuple[str, int, int]] = {}
    for row in id_map_rows or []:
        gsis = str(row.get("gsis_id") or "").strip()
        if not gsis:
            continue
        rs_int = _id_map_rookie_season(row)
        draft_round = row.get("draft_round")
        position = str(row.get("position") or "").upper()
        if not position or rs_int is None or draft_round is None:
            continue
        try:
            if isinstance(draft_round, float) and draft_round != draft_round:
                continue
            dr_int = int(draft_round)
        except (TypeError, ValueError):
            continue
        if dr_int < 1 or dr_int > 7:
            continue
        out[gsis] = (position, dr_int, rs_int)
    return out


def _normalize_player_name(name: str) -> str:
    """Lowercase + strip non-alpha for fuzzy name matching.

    Aligns nflverse ``display_name`` (e.g. "T.J. Watt") with Sleeper
    ``displayName`` (e.g. "TJ Watt") into a common key like ``tjwatt``.
    Handles periods, apostrophes, hyphens, suffixes naturally —
    everything non-alpha is dropped.
    """
    out_chars: list[str] = []
    for ch in str(name or "").lower():
        if ch.isalpha() or ch == " ":
            out_chars.append(ch)
    return " ".join("".join(out_chars).split())


def _id_map_name(row: dict[str, Any]) -> str:
    """Extract the canonical player name from an id_map row.

    The id_map can come from two sources with different schemas:

    * ``nfl_data_py.import_ids()`` — has ``name`` (mixed case),
      ``merge_name`` (lowercase), and direct ``sleeper_id``
    * ``nflverse_direct.fetch_id_map()`` (players.csv) — has
      ``display_name``, ``rookie_season``, but NO sleeper_id

    We prefer ``name`` when present (richer source) and fall back to
    ``display_name``.
    """
    return str(row.get("name") or row.get("display_name") or "").strip()


def _id_map_sleeper_id(row: dict[str, Any]) -> str:
    """Extract the Sleeper id from an id_map row, or empty string.

    Only present in the ``nfl_data_py.import_ids()`` shape.  The
    sleeper_id field is a float in that source (e.g. ``7651.0``);
    we coerce to a clean string.  ``nan`` values are filtered.
    """
    raw = row.get("sleeper_id")
    if raw is None:
        return ""
    # nan check (floats from pandas)
    try:
        if isinstance(raw, float) and raw != raw:  # nan
            return ""
    except Exception:  # noqa: BLE001
        pass
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return ""
    # Strip the trailing ``.0`` produced by pandas float coercion.
    if s.endswith(".0"):
        s = s[:-2]
    return s


def build_sleeper_to_gsis_from_id_map(
    id_map_rows: list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Build sleeper_id → gsis_id directly from the id_map.

    The ``nfl_data_py.import_ids()`` cross-walk has both columns, so
    this gives us a 6,000+ row cross-walk that's strictly bigger than
    what Sleeper's /players/nfl payload produces (~3,900 rows where
    Sleeper has gsis_id stamped per player).

    Returns ``{}`` when the id_map source is the leaner
    ``nflverse_direct`` players.csv (no sleeper_id field) — caller
    should still merge in the Sleeper /players/nfl path then.
    """
    out: dict[str, str] = {}
    for row in id_map_rows or []:
        gsis = str(row.get("gsis_id") or "").strip()
        sid = _id_map_sleeper_id(row)
        if gsis and sid:
            out[sid] = gsis
    return out


def _build_name_to_gsis(
    id_map_rows: list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Build normalised-name → gsis lookup from the id_map.

    Used as the SECOND join path when neither the id_map's direct
    sleeper_id nor the Sleeper /players/nfl payload has a gsis_id for
    a player.  This catches the long-tail of fantasy-relevant IDPs
    that haven't been added to one of the sleeper-id cross-walks yet.

    Position is encoded into the key (``"micah parsons|LB"``) to avoid
    cross-position name collisions (two players named "John Smith"
    at different positions would otherwise collide).
    """
    out: dict[str, str] = {}
    for row in id_map_rows or []:
        gsis = str(row.get("gsis_id") or "").strip()
        nm = _normalize_player_name(_id_map_name(row))
        pos = str(row.get("position") or "").upper()
        if not gsis or not nm or not pos:
            continue
        out[f"{nm}|{pos}"] = gsis
        # Position-agnostic fallback.  When two players share a name
        # at different positions, the position-qualified key still
        # disambiguates; this is for the case where the live row's
        # position differs slightly from the id_map's (e.g. Sleeper
        # classifies a player as "LB" when nflverse has "OLB" — same
        # body, different label conventions).
        if nm not in out:
            out[nm] = gsis
    return out


# ── QuantileMap (the proposal's cross-position normalization) ─────
def quantile_map_to_consensus_scale(
    par_value: float,
    par_distribution: Iterable[float],
) -> float:
    """Map a PAR value to the existing IDP value scale (0-9999).

    Computes the percentile of ``par_value`` within
    ``par_distribution`` (the league's full set of positive-VORP IDP
    PAR values), then runs that percentile through the existing
    ``percentile_to_value`` Hill curve keyed to ``scope="IDP"``.

    This is the proposal's "QuantileMap onto the existing offensive
    trade value scale" — except we use the IDP curve (not offense)
    because the IDP curve is what the rest of the pipeline uses for
    IDP rows.  No new master curve is fit.

    Returns ``0.0`` for non-positive PAR (below replacement).
    """
    if par_value <= 0:
        return 0.0
    # Sort the distribution ascending for percentile lookup.
    sorted_pars = sorted(p for p in par_distribution if p > 0)
    if not sorted_pars:
        return 0.0
    # Position of par_value in sorted list (number of strictly-smaller
    # entries) gives the percentile.
    n = len(sorted_pars)
    # Find the count of values strictly less than par_value.
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_pars[mid] < par_value:
            lo = mid + 1
        else:
            hi = mid
    rank_within = lo  # 0-indexed; 0 = smallest, n-1 = largest
    # Convert to a "rank" the percentile_to_value helper expects:
    # rank-1 / (N-1).  Cap at 99% to avoid the asymptote.
    if n <= 1:
        percentile = 0.5
    else:
        # Higher rank_within = better (more PAR below us) = lower
        # ordinal rank in the rank-based world.
        # Ordinal rank = N - rank_within (1-indexed)
        ordinal_rank = max(1, n - rank_within)
        percentile = max(0.0, min(0.99, (ordinal_rank - 1) / (n - 1)))
    return percentile_to_value(
        percentile, midpoint=IDP_HILL_PERCENTILE_C, slope=IDP_HILL_PERCENTILE_S
    )


# ── Top-level orchestrator ────────────────────────────────────────
def compute_idp_scoring_fit(
    players_array: list[dict],
    scoring_settings: dict[str, Any] | None,
    roster_positions: Iterable[str] | None,
    num_teams: int,
    *,
    weekly_rows_by_season: dict[int, list[dict[str, Any]]] | None = None,
    id_map_rows: list[dict[str, Any]] | None = None,
    sleeper_to_gsis: dict[str, str] | None = None,
) -> dict[str, IdpFitRow]:
    """Compute ``IdpFitRow`` per player keyed by ``displayName``.

    ``weekly_rows_by_season`` is optional — if absent, every IDP
    is marked with the rookie/no-history sentinel.  Production code
    fetches via :func:`src.nfl_data.fetch_weekly_defensive_stats` for
    the trailing 3 years and groups by season key.

    ``id_map_rows`` and ``sleeper_to_gsis`` enable the
    draft-capital-derived synthetic rookie baseline.  When BOTH are
    present, pre-season rookies (zero realized weeks) get a synthetic
    PPG from the cohort baseline at ``(position, draft_round)``.  If
    either is missing, rookies fall back to the no-signal sentinel.

    Returns ``{}`` if scoring-settings are missing — the orchestrator
    should skip the post-pass entirely.
    """
    if not scoring_settings:
        return {}
    weekly_rows_by_season = weekly_rows_by_season or {}

    # Slot counts.  Used as the per-position cutoff for the
    # replacement-level baseline.
    slots = starter_slot_counts(roster_positions, num_teams)

    # Build the rookie archetype baseline + live-rookie lookup index
    # ONCE up front.  Both empty-dict if the inputs are missing.
    rookie_archetype = build_rookie_archetype_baseline(
        weekly_rows_by_season, id_map_rows, scoring_settings
    )
    gsis_to_draft = _build_gsis_to_draft(id_map_rows)
    # Name → gsis fallback for the ~35-50% of active fantasy IDPs whose
    # Sleeper /players/nfl record doesn't have ``gsis_id`` stamped.
    name_to_gsis = _build_name_to_gsis(id_map_rows)

    # Phase A: build per-player season rows.
    season_rows: list[PlayerSeasonRow] = []
    diagnostic_rows: list[dict[str, Any]] = []

    join_stats = {"sleeper_id": 0, "name": 0, "missing": 0}

    for player in players_array:
        pos = str(player.get("position") or "").upper()
        if not _realized._is_idp_position(pos):
            continue
        # Use the Sleeper player_id when stamped on the row.  Rows
        # without a player_id (picks, name-only entries) can't be
        # joined to nflverse weekly data.
        sleeper_id = str(player.get("playerId") or "")
        display_name = str(player.get("displayName") or "")
        # Cross-walk in priority order:
        #   1. Sleeper id → gsis_id via Sleeper's /players/nfl payload
        #   2. Normalised name → gsis via nflverse players.csv (covers
        #      the gap where Sleeper has no gsis_id stamped)
        gsis_id: str | None = None
        if sleeper_id:
            gsis_id = (sleeper_to_gsis or {}).get(sleeper_id) or None
        if gsis_id:
            join_stats["sleeper_id"] += 1
        elif display_name:
            # Try the position-qualified key first (avoids cross-position
            # name collisions), then the position-agnostic fallback.
            nm_norm = _normalize_player_name(display_name)
            gsis_id = name_to_gsis.get(f"{nm_norm}|{pos}")
            if not gsis_id:
                gsis_id = name_to_gsis.get(nm_norm)
            if gsis_id:
                join_stats["name"] += 1
        if not gsis_id:
            join_stats["missing"] += 1
        join_key = str(gsis_id) if gsis_id else (sleeper_id or display_name.lower())
        if not join_key:
            continue

        weighted_ppg, seasons, games, _total_points = build_realized_3yr_ppg(
            join_key, pos, scoring_settings,
            weekly_rows_by_season=weekly_rows_by_season,
        )

        confidence = _confidence_for_history(seasons, games)

        if weighted_ppg is None:
            # Zero realized weeks — try the draft-capital-derived
            # synthetic before falling back to the sentinel.
            draft_round, _rookie_season = _resolve_rookie_draft_round(
                sleeper_id, sleeper_to_gsis, gsis_to_draft
            )
            cohort_ppg = (
                rookie_archetype.get((pos, draft_round))
                if draft_round is not None else None
            )
            if cohort_ppg is not None:
                # Synthetic path: the player gets a PlayerSeasonRow
                # built from the cohort baseline.  ``games=17`` is the
                # full-season notional so the VORP math doesn't
                # under-weight the synthetic.
                season_rows.append(
                    PlayerSeasonRow(
                        player_id=join_key,
                        position=pos,
                        points=cohort_ppg * 17,
                        games=17,
                        player_name=str(player.get("displayName") or ""),
                    )
                )
                diagnostic_rows.append({
                    "displayName": player.get("displayName"),
                    "position": pos,
                    "vorp": None,  # filled in below
                    "tier": None,
                    "weighted_ppg": cohort_ppg,
                    "games": 0,
                    "confidence": "synthetic",
                    "synthetic": True,
                    "draft_round": draft_round,
                })
                continue
            # No realized history AND no draft cohort match.  Stamp
            # the no-signal sentinel.
            diagnostic_rows.append({
                "displayName": player.get("displayName"),
                "position": pos,
                "vorp": None,
                "tier": "rookie",
                "weighted_ppg": None,
                "games": 0,
                "confidence": "none",
                "synthetic": False,
                "draft_round": draft_round,
            })
            continue

        season_rows.append(
            PlayerSeasonRow(
                player_id=join_key,
                position=pos,
                points=weighted_ppg * max(1, min(games, 17)),
                games=max(1, min(games, 17)),
                player_name=str(player.get("displayName") or ""),
            )
        )
        diagnostic_rows.append({
            "displayName": player.get("displayName"),
            "position": pos,
            "vorp": None,  # filled in below
            "tier": None,
            "weighted_ppg": weighted_ppg,
            "games": games,
            "confidence": confidence,
            "synthetic": False,
            "draft_round": None,
        })

    _LOGGER.info(
        "idp_scoring_fit=join_stats sleeper_id=%d name=%d missing=%d",
        join_stats["sleeper_id"], join_stats["name"], join_stats["missing"],
    )

    # Phase B: VORP table.
    vorp_rows = vorp_table(season_rows, slots)
    vorp_by_join_key = {v.player_id: v for v in vorp_rows}

    # Phase C: PAR distribution → quantile map → tier.
    out: dict[str, IdpFitRow] = {}
    for diag in diagnostic_rows:
        display = diag.get("displayName") or ""
        if not display:
            continue
        if diag.get("tier") == "rookie":
            out[display] = IdpFitRow(
                player_id="",
                position=diag["position"],
                vorp=None,
                tier="rookie",
                delta=None,
                confidence="none",
                weighted_ppg=None,
                games_used=0,
                synthetic=False,
                draft_round=diag.get("draft_round"),
            )
            continue
        # Find this player's VORP row.
        join_key = next(
            (s.player_id for s in season_rows
             if str(s.player_name) == str(display)),
            None,
        )
        v = vorp_by_join_key.get(join_key) if join_key else None
        if v is None:
            out[display] = IdpFitRow(
                player_id=join_key or "",
                position=diag["position"],
                vorp=None,
                tier="below_replacement",
                delta=None,
                confidence=diag["confidence"],
                weighted_ppg=diag["weighted_ppg"],
                games_used=diag["games"],
                synthetic=bool(diag.get("synthetic")),
                draft_round=diag.get("draft_round"),
            )
            continue
        vorp_per_game = v.vorp / max(1, v.games)
        tier = _tier_for_vorp(vorp_per_game)
        # Top stat contributions — only computed for non-synthetic
        # rows that have realized data.  Synthetic / sentinel rows
        # have no per-stat breakdown to surface.
        if diag.get("synthetic"):
            top_stats: tuple[dict[str, Any], ...] = ()
        else:
            try:
                top_stats = tuple(aggregate_stat_contributions(
                    join_key, diag["position"], scoring_settings,
                    weekly_rows_by_season=weekly_rows_by_season,
                    top_n=4,
                ))
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "idp_scoring_fit=top_stats_failed name=%r err=%r",
                    display, exc,
                )
                top_stats = ()
        out[display] = IdpFitRow(
            player_id=v.player_id,
            position=v.position,
            vorp=round(v.vorp, 2),
            tier=tier,
            delta=None,  # set in the apply pass once consensus is known
            confidence=diag["confidence"],
            weighted_ppg=round(diag["weighted_ppg"], 2)
                if diag["weighted_ppg"] is not None else None,
            games_used=diag["games"],
            synthetic=bool(diag.get("synthetic")),
            draft_round=diag.get("draft_round"),
            top_stats=top_stats,
        )

    return out


def stamp_delta(
    fit_row: IdpFitRow,
    consensus_value: float,
    par_distribution: Iterable[float],
) -> IdpFitRow:
    """Compute ``idpScoringFitDelta`` for a fit row given the player's
    consensus ``rankDerivedValue`` and the league-wide PAR-per-game
    distribution.

    Returns a new ``IdpFitRow`` with the delta filled in.  Sentinel
    rookie rows (no draft cohort match) pass through unchanged with
    ``delta = None``.  Synthetic rows DO get a delta — the synthetic
    PPG flows through the same VORP → quantile-map pipeline as
    realized rows.
    """
    if fit_row.vorp is None:
        return fit_row
    # Synthetic rows have games_used == 0 but a notional 17-game
    # season was used to build the row, so use that for per-game
    # normalisation when the row is synthetic.
    effective_games = (
        17 if fit_row.synthetic and fit_row.games_used == 0
        else max(1, fit_row.games_used)
    )
    par_per_game = fit_row.vorp / effective_games
    fit_value = quantile_map_to_consensus_scale(par_per_game, par_distribution)
    delta = fit_value - consensus_value
    return IdpFitRow(
        player_id=fit_row.player_id,
        position=fit_row.position,
        vorp=fit_row.vorp,
        tier=fit_row.tier,
        delta=round(delta, 2),
        confidence=fit_row.confidence,
        weighted_ppg=fit_row.weighted_ppg,
        games_used=fit_row.games_used,
        synthetic=fit_row.synthetic,
        draft_round=fit_row.draft_round,
        top_stats=fit_row.top_stats,
    )
