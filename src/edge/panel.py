"""The immutable as-of feature panel Consensus Edge is validated against.

One row is one (as-of date, player) pair: what we would have believed that day,
and what the market subsequently did.  Features are strictly backward-looking;
outcomes are strictly forward-looking; nothing crosses.

──────────────────────────────────────────────────────────────────────
Why the fair-value side is a LEAVE-ONE-OUT consensus
──────────────────────────────────────────────────────────────────────
The canonical ``rankDerivedValue`` blends KTC, IDP Trade Calculator and a dozen
crowd/expert boards.  Comparing it against KTC therefore compares KTC against a
number KTC helped produce — the gap is partly KTC's own noise reflected back,
and a model fitted on it learns to predict mean-reversion in a source's
disagreement with itself.

So the panel rebuilds consensus with the anchor **and its correlated family**
removed.  Two properties make this honest rather than a second ranking engine:

* It reuses production functions and production constants —
  ``player_valuation.percentile_to_value`` with ``HILL_PERCENTILE_C/S``,
  ``data_contract._PERCENTILE_REFERENCE_N``, and
  ``data_contract.count_aware_mean_median_blend``.  Steps 1-3 and 7 of the Final
  Framework, applied to a smaller source set.  Nothing is reimplemented.
* The exclusion is a *family*, not a key.  Dropping ``ktcSfTep`` while leaving
  ``ktc`` in the blend removes the label and keeps the leak.

What this panel consensus is NOT is the live board: it skips the TE-basis
conversion, the hierarchical IDP anchor, the corridor clamp and the pick
tethering, because those need a full contract and this reconstructs from raw
CSVs alone.  It is a backtest instrument for measuring whether an
independent-of-the-anchor value predicts the anchor's future — not a
replacement for ``rankDerivedValue``, and it must never be served to a user.

──────────────────────────────────────────────────────────────────────
What this panel can and cannot support
──────────────────────────────────────────────────────────────────────
Measured, not assumed (see ``history`` for the census):

* OFFENSE is backtestable.  ``ktcSfTep`` has 99 days.
* IDP IS NOT.  ``idpTradeCalc`` has 14 non-adjacent days — enough to build rows,
  never enough to validate a horizon.  ``build_panel`` will emit IDP rows and
  ``coverage_report`` will label them insufficient.  Do not quote an offense
  result as if it covered defenders.
* SHARP FLOW HAS NO HISTORY AT ALL.  The movement ledger is gitignored, holds
  no as-of snapshots, and is empty in any fresh checkout.  There is no way to
  reconstruct what the qualified cohort was doing on a past date, so the Sharp
  Flow component's weight cannot be fitted here — only assumed and disclosed.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.api.data_contract import _PERCENTILE_REFERENCE_N, count_aware_mean_median_blend
from src.canonical.player_valuation import (
    HILL_PERCENTILE_C,
    HILL_PERCENTILE_S,
    IDP_HILL_PERCENTILE_C,
    IDP_HILL_PERCENTILE_S,
    percentile_to_value,
)
from src.edge import history
from src.utils.name_clean import resolve_canonical_name

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
PANEL_DIR = REPO_ROOT / "data" / "edge" / "panel"

#: Schema version of a panel row.  Bump when a field's MEANING changes; a
#: backtest reading rows of two different meanings is worse than no backtest.
PANEL_SCHEMA_VERSION = 1

#: Sources whose numbers ARE the trade market — crowd trade values and trade
#: calculators.  Every one of these is correlated with the anchor by
#: construction, so a "fair value" containing any of them is not independent
#: of the market it is being compared against.
#:
#: Each entry is evidence-backed, not inferred from the name:
#:
#: * ``ktcSfTep`` / ``ktc`` — the anchor itself; one vendor, two boards (SF/TE+
#:   and 1QB) off the same crowd.  ``ktc`` was retired from the production blend
#:   2026-04-28 but still publishes, so it stays listed: dropping the anchor
#:   while keeping its sibling removes the label and none of the correlation.
#: * ``idpTradeCalc`` — ``CLAUDE.md`` records that 475 of KTC's 500 rows also
#:   appear on the IDPTC board at a **median value ratio of 1.000**.  Production
#:   scopes it to ``overall_idp`` so it never votes on offense anyway; this
#:   entry makes that independence explicit rather than incidental.
#: * ``fantasyNavigatorSf`` — ``scripts/fetch_fantasynavigator.py`` states its
#:   rows carry ``ktc_player_id`` and that "FN's values are KTC-derived and
#:   partially correlated with our ktcSfTep vote".
#: * ``fantasyCalc`` — crowd trade values from FantasyCalc's public API.
#: * ``otcffbSf`` — derived from OTCFFB's 354k+ observed league trades.
#: * ``dynastyDaddySf`` — crowd-sourced Superflex trade values.
#:
#: The last three are *different communities* trading, not copies of KTC, so
#: they are less correlated than FN is.  They are still excluded under the
#: strict policy because they measure the same thing the anchor measures — a
#: trade market — and the whole point of the fair-value side is to be something
#: else.
MARKET_DERIVED_SOURCES = frozenset(
    {
        "ktcSfTep",
        "ktc",
        "idpTradeCalc",
        "fantasyNavigatorSf",
        "fantasyCalc",
        "otcffbSf",
        "dynastyDaddySf",
    }
)

#: Same-vendor siblings, excluded under EVERY policy.  Keeping one of these
#: while dropping the other is not a weaker independence claim, it is a void one.
ANCHOR_FAMILIES: dict[str, frozenset[str]] = {
    "ktcSfTep": frozenset({"ktcSfTep", "ktc", "fantasyNavigatorSf"}),
    "ktc": frozenset({"ktcSfTep", "ktc", "fantasyNavigatorSf"}),
    "idpTradeCalc": frozenset({"idpTradeCalc"}),
}

#: How independent the fair value must be from the anchor.
#:
#: ``strict``  — expert/analyst boards only; no trade market anywhere in the
#:               fair value.  The cleanest claim, and the thinnest: measured on
#:               this repository's history only ``flockFantasySf`` (105 days)
#:               and ``draftSharksSf`` (75) run deep, with ``dlfSf`` (23) and
#:               the rest sparse.
#: ``family``  — drop only the anchor's own vendor family.  Retains the other
#:               crowd markets, so it is denser but measures market-vs-market
#:               disagreement as much as mispricing.
#:
#: BOTH are built and BOTH are reported.  Which one predicts better is an
#: empirical question this repository can now answer, and guessing it in
#: advance is exactly the kind of unvalidated choice this work exists to avoid.
INDEPENDENCE_POLICIES = ("strict", "family")

#: Sources excluded from the consensus regardless of anchor.
#:
#: Rookie-only and ROS boards rank a different population than a dynasty board;
#: blending them in would compare a rookie's rank-among-rookies against a
#: full-board percentile and systematically overvalue rookies.
NON_DYNASTY_BOARD_SOURCES = frozenset(
    {
        "dlfRookieSf",
        "dlfRookieIdp",
        "flockFantasySfRookies",
        "draftSharksRosSf",
        "draftSharksRosIdp",
        "fantasyProsRosSf",
        "fantasyProsRosIdp",
        "fantasyProsRosOverall",
        "ffc2qbAdp",
        "footballGuysRosIdp",
    }
)

#: A source contributing fewer than this many rows on a date is ignored for
#: that date: a 20-deep board's rank-15 is not comparable to a 500-deep board's
#: rank-15 once both are pushed through a fixed-N percentile.
MIN_SOURCE_DEPTH = 50

#: A source older than this at the as-of date does not vote. Distinct from
#: ``history.DEFAULT_STALE_AFTER_DAYS``, which only flags: here a month-old
#: board actively misinforms a 30-day-outcome study.
MAX_SOURCE_AGE_DAYS = 14

#: Guards the log ratio near the scale floor, where a 1-point move is a 100%
#: change and would otherwise dominate every cohort statistic.
LOG_GAP_EPSILON = 50.0

#: Rows below this market value are excluded from fitted statistics. Deep-board
#: noise, not signal: at value < 200 the anchor quantises to a handful of
#: distinct numbers and "return" is mostly rounding.
MIN_MARKET_VALUE_FOR_STATS = 200.0

_PICK_PREFIXES = ("2024", "2025", "2026", "2027", "2028", "2029", "2030")


def is_pick_key(key: str) -> bool:
    """Picks share the anchor board but not the player join.

    They are priced by tethering to the rookie pool rather than by a name-joined
    board, so a pick row's "market value" and a player's are not the same kind
    of number. Excluded from the player panel rather than silently mixed in.
    """
    return key.strip().lower().startswith(_PICK_PREFIXES)


@lru_cache(maxsize=1)
def _position_index() -> dict[str, str]:
    """Canonical name -> coarse position, from a map generated BEFORE the panel window.

    ``data/player_map/player_position_map.json`` is stamped 2026-03-22 and the
    panel starts 2026-04-16, so reading it introduces no look-ahead. Using
    today's contract instead would let a player's *current* position label a row
    from four months ago — usually harmless, occasionally not (position changes,
    rookies reclassified), and never necessary given this file exists.
    """
    index: dict[str, str] = {}
    primary = REPO_ROOT / "data" / "player_map" / "player_position_map.json"
    try:
        payload = json.loads(primary.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return index
    for entry in payload.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        key = resolve_canonical_name(entry.get("name"))
        position = str(entry.get("position") or "").strip().upper()
        if key and position:
            index.setdefault(key, position)
    return index


@dataclass
class PanelRow:
    """One as-of observation with its future outcome."""

    schema_version: int
    as_of: str
    player_key: str
    position: str | None
    position_source: str
    asset_class: str

    # ── market side (as of the date, never after) ──
    market_value: float
    market_source: str
    market_age_days: int
    market_is_stale: bool

    # ── independent fair-value side ──
    fair_value: float | None
    fair_value_policy: str
    fair_value_dispersion: float | None
    fair_value_source_count: int
    fair_value_sources: tuple[str, ...]
    excluded_sources: tuple[str, ...]

    # ── derived gap ──
    log_gap: float | None
    pct_gap: float | None

    # ── trailing market movement (BACKWARD-looking, so a legal feature) ──
    #
    # The single most important control in this whole study.  A gap is large
    # partly because the market just moved, and a market that just moved tends
    # to move back.  Without these a mean-reversion effect is indistinguishable
    # from genuine mispricing detection, and the model would be credited for
    # rediscovering that prices are noisy.
    trailing_log_change: dict[str, float | None] = field(default_factory=dict)

    # ── forward outcomes (labels — the ONLY forward-looking fields) ──
    outcomes: dict[str, float | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fair_value_sources"] = list(self.fair_value_sources)
        payload["excluded_sources"] = list(self.excluded_sources)
        return payload


def _hill_constants(asset_class: str) -> tuple[float, float]:
    """IDP rides its own percentile curve in production; match that here."""
    if asset_class == "idp":
        return IDP_HILL_PERCENTILE_C, IDP_HILL_PERCENTILE_S
    return HILL_PERCENTILE_C, HILL_PERCENTILE_S


@lru_cache(maxsize=1)
def _registry_scopes() -> dict[str, str]:
    """CSV stem -> production scope, resolved through the real registry.

    Two indirections matter here and both have already bitten this module:

    * Scope is not decoration.  ``idpTradeCalc`` is ``overall_idp``, so in
      production it never prices an offense player.  An earlier version of this
      panel let it vote on offense and thereby placed a market anchor inside the
      "independent" fair value it was being compared against.
    * The registry key is not the file name.  ``draftSharks`` reads
      ``draftSharksSf.csv``.  Keying on the file stem alone silently drops one
      of the deepest independent expert boards in the repository (75 days)
      because it never matches a registry entry.

    ``_SOURCE_CSV_PATHS`` is the authority for the second, so it is read rather
    than approximated.
    """
    from src.api.data_contract import _RANKING_SOURCES, _SOURCE_CSV_PATHS

    scope_by_key = {
        str(entry.get("key")): str(entry.get("scope") or "")
        for entry in _RANKING_SOURCES
        if entry.get("key")
    }
    out: dict[str, str] = {}
    for key, config in _SOURCE_CSV_PATHS.items():
        path = config.get("path") if isinstance(config, dict) else config
        if not path:
            continue
        scope = scope_by_key.get(key)
        if scope:
            out[Path(str(path)).stem] = scope
    return out


def _votes_in_scope(source: str, asset_class: str) -> bool:
    scope = _registry_scopes().get(source)
    if not scope:
        # Not in the production registry (e.g. retired ``ktc``). Excluded on
        # principle: a source production does not trust to vote is not a source
        # a validation panel should trust either.
        return False
    if asset_class == "idp":
        return scope in {"overall_idp", "position_idp"}
    return scope == "overall_offense"


def _source_percentile_values(
    snapshot: history.SourceSnapshot,
    asset_class: str,
) -> dict[str, float]:
    """Final Framework steps 1-3 for one source, using production functions.

    Ordering comes from the source's NATIVE RANK where it publishes one, and
    only falls back to sorting its values descending where it does not.  That
    ordering matters: this repository has already measured several of these
    boards' value scales as untrustworthy (DynastyDaddy ties its top three at a
    10,200 display ceiling; OTCFFB decays so fast that four in five of its
    value-direct votes were discarded as outliers) and moved them onto the rank
    path in production for that reason.  Re-deriving order from those same
    values here would reintroduce the distortion production already rejected.

    The percentile then runs against the FIXED reference N — production
    behaviour, where ranks past it clamp to the curve's tail — and through the
    production Hill curve.  The source's native scale is discarded on purpose:
    that is what makes a 0-100 board and a 0-9999 board comparable.
    """
    midpoint, slope = _hill_constants(asset_class)
    if snapshot.ranks:
        ordered = sorted(
            ((key, rank) for key, rank in snapshot.ranks.items() if not is_pick_key(key)),
            key=lambda item: item[1],
        )
    else:
        ordered = sorted(
            ((key, -value) for key, value in snapshot.values.items() if not is_pick_key(key)),
            key=lambda item: item[1],
        )
    out: dict[str, float] = {}
    denominator = max(1.0, float(_PERCENTILE_REFERENCE_N - 1))
    for index, (key, _sort_value) in enumerate(ordered):
        rank = index + 1
        percentile = min(1.0, max(0.0, (rank - 1.0) / denominator))
        out[key] = float(percentile_to_value(percentile, midpoint=midpoint, slope=slope))
    return out


def _eligible_sources(
    as_of: date,
    anchor: str,
    *,
    all_sources: Sequence[str],
    policy: str = "strict",
) -> tuple[list[history.SourceSnapshot], list[str]]:
    """Snapshots that may vote on ``as_of``, plus the keys deliberately excluded.

    Scope filtering happens later, per asset class, because one snapshot can be
    eligible for IDP and ineligible for offense.
    """
    if policy not in INDEPENDENCE_POLICIES:
        raise ValueError(f"policy must be one of {INDEPENDENCE_POLICIES}")
    family = ANCHOR_FAMILIES.get(anchor, frozenset({anchor}))
    banned = MARKET_DERIVED_SOURCES if policy == "strict" else family
    snapshots: list[history.SourceSnapshot] = []
    excluded: list[str] = []
    for source in all_sources:
        if source in family:
            excluded.append(f"{source}:anchor_family")
            continue
        if source in banned:
            excluded.append(f"{source}:market_derived")
            continue
        if source in NON_DYNASTY_BOARD_SOURCES:
            excluded.append(f"{source}:not_a_dynasty_board")
            continue
        snapshot = history.snapshot_at(source, as_of)
        if snapshot is None:
            continue
        if snapshot.age_days > MAX_SOURCE_AGE_DAYS:
            excluded.append(f"{source}:stale_{snapshot.age_days}d")
            continue
        depth = max(len(snapshot.values), len(snapshot.ranks))
        if depth < MIN_SOURCE_DEPTH:
            excluded.append(f"{source}:too_shallow_{depth}")
            continue
        snapshots.append(snapshot)
    return snapshots, excluded


def _classify(key: str, offense_keys: set[str], idp_keys: set[str]) -> str:
    """Offense vs IDP from BOARD MEMBERSHIP, which is leak-free.

    Which board carried a player on a date is a fact about that date. Preferred
    over the position map for the coarse split precisely because it needs no
    external file and cannot import a later reclassification.
    """
    in_offense = key in offense_keys
    in_idp = key in idp_keys
    if in_idp and not in_offense:
        return "idp"
    if in_offense and not in_idp:
        return "offense"
    if in_offense and in_idp:
        # Both boards carry him — the offense board is the narrower, more
        # selective population, so treat him as offense and let the position
        # map refine it.
        return "offense"
    return "unknown"


def build_rows(
    as_of: date,
    *,
    anchor: str = history.OFFENSE_MARKET_ANCHOR,
    all_sources: Sequence[str] | None = None,
    policy: str = "strict",
) -> list[PanelRow]:
    """Every panel row for a single as-of date."""
    sources = list(all_sources if all_sources is not None else history.available_sources())
    anchor_snapshot = history.snapshot_at(anchor, as_of)
    if anchor_snapshot is None:
        return []

    offense_snap = history.snapshot_at(history.OFFENSE_MARKET_ANCHOR, as_of)
    idp_snap = history.snapshot_at(history.IDP_MARKET_ANCHOR, as_of)
    offense_keys = set(offense_snap.values) if offense_snap else set()
    idp_keys = set(idp_snap.values) if idp_snap else set()

    voters, excluded = _eligible_sources(as_of, anchor, all_sources=sources, policy=policy)
    positions = _position_index()

    # Percentile-converted votes per source, per asset class. IDP and offense
    # take different curves, so a player is converted under his own class.
    votes_by_class: dict[str, dict[str, dict[str, float]]] = {"offense": {}, "idp": {}}
    for snapshot in voters:
        for asset_class in ("offense", "idp"):
            # Respect the production scope: an offense-scoped board does not get
            # to price a defender, and vice versa.
            if not _votes_in_scope(snapshot.source, asset_class):
                continue
            votes_by_class[asset_class][snapshot.source] = _source_percentile_values(
                snapshot, asset_class
            )

    rows: list[PanelRow] = []
    for key, market_value in anchor_snapshot.values.items():
        if is_pick_key(key) or market_value <= 0:
            continue
        asset_class = _classify(key, offense_keys, idp_keys)
        position = positions.get(key)
        position_source = "pre_window_map" if position else "board_membership"

        per_source = votes_by_class.get(asset_class if asset_class != "unknown" else "offense", {})
        contributions: list[float] = []
        contributing_sources: list[str] = []
        for source, values in per_source.items():
            value = values.get(key)
            if value is None:
                continue
            contributions.append(value)
            contributing_sources.append(source)

        fair_value: float | None = None
        fair_value_dispersion: float | None = None
        if contributions:
            # Production returns (center, MAD). The MAD is kept, not discarded:
            # source disagreement is a first-class confidence input, and a gap
            # built on sources that disagree wildly is not the same evidence as
            # the same gap built on sources that agree.
            center, mad = count_aware_mean_median_blend(contributions)
            fair_value = float(center)
            fair_value_dispersion = float(mad) if mad is not None else None

        log_gap: float | None = None
        pct_gap: float | None = None
        if fair_value is not None and fair_value > 0:
            log_gap = math.log((fair_value + LOG_GAP_EPSILON) / (market_value + LOG_GAP_EPSILON))
            pct_gap = (fair_value - market_value) / market_value

        rows.append(
            PanelRow(
                schema_version=PANEL_SCHEMA_VERSION,
                as_of=as_of.isoformat(),
                player_key=key,
                position=position,
                position_source=position_source,
                asset_class=asset_class,
                market_value=float(market_value),
                market_source=anchor,
                market_age_days=anchor_snapshot.age_days,
                market_is_stale=anchor_snapshot.is_stale,
                fair_value=fair_value,
                fair_value_policy=policy,
                fair_value_dispersion=fair_value_dispersion,
                fair_value_source_count=len(contributing_sources),
                fair_value_sources=tuple(sorted(contributing_sources)),
                excluded_sources=tuple(sorted(excluded)),
                log_gap=log_gap,
                pct_gap=pct_gap,
            )
        )
    return rows


def attach_trailing_change(
    rows: Iterable[PanelRow],
    *,
    anchor: str = history.OFFENSE_MARKET_ANCHOR,
    lookbacks: Sequence[int] = (7, 14, 30),
) -> list[PanelRow]:
    """Stamp BACKWARD market movement — legal as a feature, unlike outcomes.

    Reads only commits at or before ``as_of - lookback``, so nothing here can
    see the future. Kept in its own function from ``attach_outcomes`` precisely
    so the direction of every read is obvious at the call site: this one looks
    back, that one looks forward, and no code path does both.
    """
    materialized = list(rows)
    if not materialized:
        return materialized
    needed: set[date] = set()
    for row in materialized:
        as_of = date.fromisoformat(row.as_of)
        for lookback in lookbacks:
            needed.add(as_of - timedelta(days=lookback))

    past: dict[date, dict[str, float]] = {}
    for day in sorted(needed):
        snapshot = history.snapshot_at(anchor, day)
        if snapshot is not None and snapshot.age_days <= MAX_SOURCE_AGE_DAYS:
            past[day] = snapshot.values

    for row in materialized:
        as_of = date.fromisoformat(row.as_of)
        for lookback in lookbacks:
            key = f"log_change_{lookback}d"
            values = past.get(as_of - timedelta(days=lookback))
            earlier = values.get(row.player_key) if values else None
            if not earlier or earlier <= 0 or row.market_value <= 0:
                row.trailing_log_change[key] = None
                continue
            row.trailing_log_change[key] = math.log(
                (row.market_value + LOG_GAP_EPSILON) / (earlier + LOG_GAP_EPSILON)
            )
    return materialized


def attach_outcomes(
    rows: Iterable[PanelRow],
    *,
    anchor: str = history.OFFENSE_MARKET_ANCHOR,
    horizons: Sequence[int] = (7, 14, 30),
) -> list[PanelRow]:
    """Stamp forward market returns. THE ONLY place the future is read.

    ``None`` where the horizon runs past the end of history or the player left
    the board — an unknown outcome must stay unknown. Filling it with 0.0 would
    teach a model that a delisted player held his value.
    """
    materialized = list(rows)
    if not materialized:
        return materialized
    needed: set[date] = set()
    for row in materialized:
        as_of = date.fromisoformat(row.as_of)
        for horizon in horizons:
            needed.add(as_of + timedelta(days=horizon))

    future: dict[date, dict[str, float]] = {}
    latest_day = history.available_days(anchor)[-1] if history.available_days(anchor) else None
    for day in sorted(needed):
        if latest_day is not None and day > latest_day:
            continue
        snapshot = history.snapshot_at(anchor, day)
        # A snapshot resolved from a much older commit is not an observation of
        # ``day`` — it is the same board we already have, and a "return" against
        # it is structurally zero. Refuse rather than manufacture a null result.
        if snapshot is not None and snapshot.age_days <= MAX_SOURCE_AGE_DAYS:
            future[day] = snapshot.values

    for row in materialized:
        as_of = date.fromisoformat(row.as_of)
        for horizon in horizons:
            target = as_of + timedelta(days=horizon)
            values = future.get(target)
            outcome_key = f"log_return_{horizon}d"
            if not values:
                row.outcomes[outcome_key] = None
                continue
            later = values.get(row.player_key)
            if later is None or later <= 0 or row.market_value <= 0:
                row.outcomes[outcome_key] = None
                continue
            row.outcomes[outcome_key] = math.log(
                (later + LOG_GAP_EPSILON) / (row.market_value + LOG_GAP_EPSILON)
            )
    return materialized


def build_panel(
    *,
    start: date,
    end: date,
    anchor: str = history.OFFENSE_MARKET_ANCHOR,
    horizons: Sequence[int] = (7, 14, 30),
    stride_days: int = 1,
    policy: str = "strict",
) -> list[PanelRow]:
    """The full as-of panel between two dates, inclusive."""
    sources = history.available_sources()
    rows: list[PanelRow] = []
    day = start
    while day <= end:
        rows.extend(build_rows(day, anchor=anchor, all_sources=sources, policy=policy))
        day += timedelta(days=max(1, stride_days))
    rows = attach_trailing_change(rows, anchor=anchor)
    return attach_outcomes(rows, anchor=anchor, horizons=horizons)


def coverage_report(rows: Sequence[PanelRow], *, horizons: Sequence[int] = (7, 14, 30)) -> dict:
    """What the panel can honestly support — stated, not inferred by the reader."""
    by_class: dict[str, int] = {}
    labelled: dict[str, int] = {}
    with_fair_value = 0
    dates: set[str] = set()
    for row in rows:
        by_class[row.asset_class] = by_class.get(row.asset_class, 0) + 1
        dates.add(row.as_of)
        if row.fair_value is not None:
            with_fair_value += 1
        for horizon in horizons:
            key = f"log_return_{horizon}d"
            if row.outcomes.get(key) is not None:
                labelled[key] = labelled.get(key, 0) + 1
    return {
        "schemaVersion": PANEL_SCHEMA_VERSION,
        "rows": len(rows),
        "asOfDates": len(dates),
        "earliest": min(dates) if dates else None,
        "latest": max(dates) if dates else None,
        "byAssetClass": by_class,
        "withFairValue": with_fair_value,
        "labelledByHorizon": labelled,
        "note": (
            "Offense is backtestable; IDP is not (the IDP anchor has 14 days of "
            "history). Sharp Flow has no history at all and cannot be fitted."
        ),
    }


def write_panel(rows: Sequence[PanelRow], path: Path) -> Path:
    """Write JSONL. Immutable by convention: never rewrite an existing panel file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict(), sort_keys=True) + "\n")
    return path
