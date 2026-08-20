"""``GET /api/gameplan`` — the API surface over the WS-J roster engines.

Everything in ``src/roster_intel/`` merged with no caller.  ``git grep
roster_intel`` outside its own package and tests returned zero matches:
``analyze_roster``, the per-position profiles, the five-state
competitive window, the target engines, the partner model and the
Trade Package Generator were all reachable only from a Python REPL.
This module is the wiring, and the route in ``server.py`` is a thin
shell over it.

What is league-scoped and what is not
─────────────────────────────────────
CLAUDE.md's central rule — *scoring profile controls rankings, league
key controls context* — decides every input here, and getting it
backwards is the architectural error that rule exists to prevent.

Resolved by **leagueKey** (one pipeline per league, never collapsed):

* rosters — ``data/ros/team_strength/<key>.json``'s ``fullRoster``
* starter slots — the registry's per-league ``rosterSettings.starters``
* replacement levels and scarcity — measured from **this league's own
  12 rosters**; the league IS its own replacement market
* the exact lineup solves, the competitive window, partner fit,
  packages
* playoff / championship odds — ``data/ros/sims/<key>_playoff.json``

Resolved by **scoring profile** (shared across same-scoring leagues):

* player ages and market site values, read off the live ``/api/data``
  contract's ``playersArray``.  These are player metadata and rankings,
  so two leagues on one scoring profile share them and neither one
  needs its own copy.

Two scales that must never be mixed
───────────────────────────────────
``rosValue`` (0-100, rest-of-season STRENGTH INDEX) and
``canonicalSiteValues`` (0-9999, dynasty market) are different currencies
with no validated conversion between them.

``rosValue`` is not points, despite the arithmetic downstream of it
looking point-like.  It is ``100·(ln(N+1) − ln(r))/ln(N+1)`` — a
normalized log-rank index — blended across sources by weight
(``src/ros/parse.py::rank_to_score``, ``src/ros/aggregate.py``).  It is
ordinal in origin, so a 10-unit gap does not mean the same thing at the
top of a position as in the tail, and summing it across a lineup yields a
strength total rather than a projected score.  This docstring previously
called it "rest-of-season points"; that was wrong and is corrected here
rather than quietly dropped, because every field name downstream
(``lineupScore``, ``startingLineupScore``) inherits the confusion.

The target engines take a ``market_values`` / ``market_prices`` map and
compute ``(ros_value - price) / price`` against it.  Feeding them the
contract's 0-9999 numbers produces an edge of about -0.99 for every
player alive — a dead signal that still looks computed.  So those
inputs are **deliberately not supplied**, the engines report the edge
as unmeasured, and :func:`_coverage` says so.  ``packages`` is the one
consumer that does take site values, and it is safe because
``value_package`` compares market to market and the engine keeps
lineup points on a separate frontier axis rather than blending them.

Cost, measured not guessed
──────────────────────────
On the real 12-team league (57-man rosters, 21 starter slots), one
core at 2026-07-27::

    measure_endogenous_starters (12 teams)       89 ms
    compute_replacement_levels (reusing it)       2 ms
    compute_scarcity                              1 ms
    optimal_score x12                            52 ms
    analyze_roster x12                        1,195 ms   <- dominant
    assess_partners (11 partners)                 0.5 ms
    rank_target_positions (97 candidates)       277 ms
    rank_target_players (97 candidates)         271 ms
    generate_packages (8x8 assets)              146 ms

``analyze_roster`` re-solves the lineup repeatedly — once per position
for the marginals, once per starter for the absence impacts — so it is
~91 ms per roster and there is no cheap version of it.  A cold
league-wide build is therefore ~1.35 s and a cold team view ~1.9 s,
which is far too slow to run per request on the event loop.

Two caches, both keyed on a **source stamp** rather than a clock:
:data:`_BUNDLE_CACHE` holds the league-wide build, :data:`_TEAM_CACHE`
the per-team derivation.  The stamp is the identity of the inputs
(snapshot mtimes + the contract's scrape timestamp), so a refresh
invalidates immediately and a quiet hour never serves something newer
than it claims.  Warm requests are dictionary lookups.  The route runs
cold builds in a threadpool and stamps ``timing.computeMs`` /
``timing.cacheHit`` on every response, so the cost stays measurable in
production instead of being re-guessed.

Honesty stamps are load-bearing
───────────────────────────────
Several fields exist because an earlier version presented something as
stronger than it was.  This module **passes engine ``to_dict()``
output through unchanged** — it never rebuilds a payload field by
field, because that is how a caveat gets dropped in a refactor.  In
particular:

* ``acceptancePlausibility`` ships with the engine's
  ``acceptanceCaveat`` attached.  It is never renamed to anything
  containing "probability": rejections are never observed, so no
  acceptance rate is identifiable from this data.
* ``winNowWeight`` is ``null`` when candidate ages are missing, and
  :data:`FIELD_POLICY` declares it non-sortable and non-filterable —
  its nulls cluster on positions whose obtainable upgrades happen to
  be un-aged, so ordering by it reorders by data availability.
* Confidence intervals stay ``null`` rather than collapsing to zero
  width; zero width reads as certainty.
* The Pareto frontier is returned wide.  ``value_efficiency`` and
  ``acceptance_plausibility`` are anti-correlated by construction and
  no exchange rate exists between market points, lineup points and
  plausibility, so no blended score is invented to shorten it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.league_intel.cross_market import DEFAULT_GATE_PCT
from src.league_intel.replacement import (
    PositionReplacement,
    ScarcityComponents,
    compute_replacement_levels,
    compute_scarcity,
    measure_endogenous_starters,
    normalize_base_position,
)
from src.roster_intel import packages as _packages
from src.roster_intel import partner as _partner
from src.roster_intel import targets as _targets
from src.roster_intel.engine import RosterIntel, analyze_roster
from src.roster_intel.marginal import optimal_score, to_roster_players
from src.ros.lineup import RosterPlayer, load_league_starter_slots
from src.ros.team_strength import load_team_strength_snapshot

__all__ = [
    "FIELD_POLICY",
    "GAMEPLAN_CONTRACT_VERSION",
    "GameplanUnavailable",
    "TeamNotInLeague",
    "LeagueBundle",
    "LeagueInputs",
    "TeamInput",
    "build_gameplan",
    "build_league_bundle",
    "get_league_bundle",
    "invalidate_cache",
    "load_league_inputs",
]

GAMEPLAN_CONTRACT_VERSION = "2026-07-27.v1"
"""Versioned the way ``/api/data`` is.  Bump on any shape change."""


# ── Caller-side pre-filters ──────────────────────────────────────────
# The engines delegate candidate selection to the caller on purpose
# ("pre-filtering this to genuine surplus is the caller's job and is the
# single biggest lever on both quality and cost").  These are that
# choice, made explicitly and stamped into ``coverage.candidatePolicy``
# rather than left implicit.

MAX_CANDIDATES_PER_POSITION = 12
"""Cap on acquirable candidates offered to the target engines per
position, taken in descending ``rosValue``.

A cost guard, and a lossy one: value order is not gain order.  Adding a
higher-valued player at the same position can never yield a *smaller*
lineup gain when the two share slot eligibility — but a hybrid IDP
(``DL`` with ``fantasy_positions=["DL","LB"]``) can out-gain a
higher-valued pure ``DL`` by filling a slot the other cannot.  So the
cap can hide a genuinely better target, and that is reported instead of
being presented as an exhaustive search.
"""

MAX_PACKAGE_ASSETS_PER_SIDE = 8
"""Assets offered to the package generator per side.

Measured on the real league: 6x6 costs 81 ms, 8x8 costs 146 ms, 12x12
costs 513 ms.  Eight keeps a partner view inside a normal request
budget while still reaching stage 2 and 3 expansion.
"""


class GameplanUnavailable(Exception):
    """Raised when the inputs for a league are not on disk.

    Carries a machine-readable ``reason`` so the route can answer with
    the documented ``data_not_ready`` contract instead of a 500.
    """

    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(detail)


class TeamNotInLeague(Exception):
    """The requested owner has no roster in this league.

    A dedicated type rather than ``KeyError``: the route has to turn
    "unknown team" into a 404, and catching ``KeyError`` there would
    also swallow one raised deep inside an engine and report a genuine
    bug as a missing team.
    """

    def __init__(self, owner_id: str):
        self.owner_id = owner_id
        super().__init__(owner_id)


# ── Inputs ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TeamInput:
    """One roster, in both representations the engines need."""

    owner_id: str
    team_name: str
    rows: tuple[Mapping[str, Any], ...]
    pool: tuple[RosterPlayer, ...]


@dataclass(frozen=True)
class LeagueInputs:
    """Everything loaded from disk for one league, before any solving."""

    league_key: str
    scoring_profile: str
    slots: tuple[str, ...]
    teams: tuple[TeamInput, ...]
    #: ``{sleeper_player_id: {"age": float}}`` — scoring-profile scoped.
    player_meta: Mapping[str, Mapping[str, float]]
    #: ``{sleeper_player_id: {site: value}}`` on the 0-9999 dynasty
    #: market — scoring-profile scoped, and NEVER mixed with rosValue.
    site_values: Mapping[str, Mapping[str, float]]
    #: ``simulate_playoff_odds(...)["playoffOdds"]`` rows, or None.
    playoff_odds: tuple[Mapping[str, Any], ...] | None
    source_stamp: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeagueBundle:
    """The expensive, league-wide build.  Cached on the source stamp."""

    inputs: LeagueInputs
    replacement: Mapping[str, PositionReplacement]
    scarcity: Mapping[str, ScarcityComponents]
    lineup_scores: Mapping[str, float]
    intel: Mapping[str, RosterIntel]
    signals: Mapping[str, _partner.RosterSignal]
    compute_ms: float
    notes: tuple[str, ...] = field(default_factory=tuple)

    def team(self, owner_id: str) -> TeamInput | None:
        return next((t for t in self.inputs.teams if t.owner_id == str(owner_id)), None)


# ── Loading ──────────────────────────────────────────────────────────


def _sim_playoff_path(league_key: str) -> Path:
    """Per-league playoff-sim cache path.

    Routes through ``src.ros.scrape._sim_paths`` — the writer — so the
    default league's historical ``latest_playoff.json`` filename and the
    ``<key>_playoff.json`` namespacing stay defined in exactly one
    place.  A second copy of that rule here is how the reader and the
    writer drift apart.
    """
    from src.ros.scrape import _sim_paths  # noqa: PLC0415 — avoids a heavy import at module load

    from src.api.league_registry import default_league_key  # noqa: PLC0415

    playoff, _champ = _sim_paths(league_key, default_league_key())
    return playoff


def _file_stamp(path: Path) -> str:
    try:
        st = path.stat()
    except OSError:
        return f"{path.name}:absent"
    return f"{path.name}:{st.st_mtime_ns}:{st.st_size}"


def _contract_stamp(contract: Mapping[str, Any] | None) -> str:
    if not isinstance(contract, Mapping):
        return "contract:none"
    meta = contract.get("meta") if isinstance(contract.get("meta"), Mapping) else {}
    for key in ("scrapeTimestamp", "generatedAt", "date"):
        val = contract.get(key) or (meta or {}).get(key)
        if val:
            return f"contract:{val}"
    return "contract:unstamped"


def _index_contract_players(
    contract: Mapping[str, Any] | None,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """``playersArray`` → ages and market site values, by Sleeper id.

    Keyed by Sleeper id rather than name because the roster snapshot is
    id-keyed and the identity layer already owns id-grade joins; a
    second name-normalisation here would be a competing source of
    truth.
    """
    ages: dict[str, dict[str, float]] = {}
    sites: dict[str, dict[str, float]] = {}
    if not isinstance(contract, Mapping):
        return ages, sites
    rows = contract.get("playersArray")
    if not isinstance(rows, list):
        return ages, sites
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        pid = str(row.get("playerId") or "").strip()
        if not pid:
            continue
        age = row.get("age")
        if isinstance(age, (int, float)) and age > 0:
            ages[pid] = {"age": float(age)}
        csv = row.get("canonicalSiteValues")
        if isinstance(csv, Mapping):
            priced = {
                str(k): float(v)
                for k, v in csv.items()
                if isinstance(v, (int, float)) and float(v) > 0
            }
            if priced:
                sites[pid] = priced
    return ages, sites


def load_league_inputs(
    league_key: str,
    scoring_profile: str,
    contract: Mapping[str, Any] | None,
) -> LeagueInputs:
    """Read every input for one league off disk.

    Raises :class:`GameplanUnavailable` when the roster snapshot the
    whole surface rests on is missing — that is a
    ``data_not_ready`` condition, not an empty result.
    """
    rows = load_team_strength_snapshot(league_key)
    if not rows:
        raise GameplanUnavailable(
            "roster_snapshot_missing",
            (
                f"No team-strength snapshot for league {league_key!r}. "
                "The gameplan surface reads full rosters from "
                "data/ros/team_strength/; run the ROS refresh for this league."
            ),
        )

    slots = load_league_starter_slots(league_key)
    if not slots:
        raise GameplanUnavailable(
            "starter_slots_missing",
            (
                f"League {league_key!r} has no rosterSettings.starters in the "
                "registry, so there is no lineup to solve."
            ),
        )

    notes: list[str] = []
    teams: list[TeamInput] = []
    for row in rows:
        owner_id = str(row.get("ownerId") or "").strip()
        if not owner_id:
            continue
        # ``fullRoster`` and not ``startingLineup + benchDepth``: the
        # latter is capped at 26 players against real 44-58 man rosters
        # (ADR-011), which understates depth and overstates fragility in
        # a known direction.
        roster = [r for r in (row.get("fullRoster") or []) if isinstance(r, Mapping)]
        if not roster:
            notes.append(
                f"owner {owner_id!r} carries no fullRoster in the snapshot; "
                "excluded from the league build"
            )
            continue
        teams.append(
            TeamInput(
                owner_id=owner_id,
                team_name=str(row.get("teamName") or ""),
                rows=tuple(roster),
                pool=tuple(to_roster_players(roster)),
            )
        )

    if not teams:
        raise GameplanUnavailable(
            "roster_snapshot_empty",
            f"Team-strength snapshot for {league_key!r} contains no rosters.",
        )

    ages, sites = _index_contract_players(contract)
    if not ages:
        notes.append(
            "no player ages reached this build; the competitive window's "
            "trajectory axis will pin at neutral and the target engines' "
            "horizon weight will not apply (winNowWeight null)"
        )

    playoff_odds: tuple[Mapping[str, Any], ...] | None = None
    sim_path = _sim_playoff_path(league_key)
    try:
        if sim_path.exists():
            payload = json.loads(sim_path.read_text())
            raw = payload.get("playoffOdds") if isinstance(payload, Mapping) else None
            if isinstance(raw, list) and raw:
                playoff_odds = tuple(r for r in raw if isinstance(r, Mapping))
    except (OSError, json.JSONDecodeError) as exc:
        notes.append(f"playoff-sim cache unreadable ({exc.__class__.__name__}); odds omitted")

    stamp = hashlib.sha256(
        "|".join(
            [
                league_key,
                scoring_profile,
                _file_stamp(_team_strength_stamp_path(league_key)),
                _file_stamp(sim_path),
                _contract_stamp(contract),
                GAMEPLAN_CONTRACT_VERSION,
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]

    return LeagueInputs(
        league_key=league_key,
        scoring_profile=scoring_profile,
        slots=tuple(slots),
        teams=tuple(teams),
        player_meta=ages,
        site_values=sites,
        playoff_odds=playoff_odds,
        source_stamp=stamp,
        notes=tuple(notes),
    )


def _team_strength_stamp_path(league_key: str) -> Path:
    """Path to the roster snapshot, for stamping only.

    ``load_team_strength_snapshot`` owns reading it; this mirrors its
    private path rule for the cache key.  Kept narrow — if the two ever
    disagree the only consequence is a stale-cache miss, never a wrong
    answer, because the stamp is one input among several.
    """
    from src.ros.team_strength import _team_strength_path  # noqa: PLC0415

    return _team_strength_path(league_key)


# ── The expensive build ──────────────────────────────────────────────


def build_league_bundle(inputs: LeagueInputs) -> LeagueBundle:
    """Solve everything that is league-wide.  ~1.35 s cold on 12 teams.

    Every optional engine input that CAN be supplied IS supplied.  An
    absent one does not error — it produces a constant that looks
    exactly like a broken metric (measured: with no ages the window's
    trajectory axis reads 0.500 for every roster and
    ``productive_struggle`` becomes unreachable league-wide).
    """
    t0 = time.perf_counter()
    slots = list(inputs.slots)
    rep_teams = [{"players": list(t.rows)} for t in inputs.teams]

    # ``measure_endogenous_starters`` is the expensive half of the
    # replacement build; measure once and hand it to both consumers.
    endogenous = measure_endogenous_starters(rep_teams, slots)
    replacement = compute_replacement_levels(rep_teams, slots, endogenous=endogenous)
    scarcity = compute_scarcity(replacement, rep_teams)

    lineup_scores = {t.owner_id: optimal_score(list(t.pool), slots) for t in inputs.teams}

    odds_rows = list(inputs.playoff_odds) if inputs.playoff_odds else None
    intel: dict[str, RosterIntel] = {}
    for t in inputs.teams:
        intel[t.owner_id] = analyze_roster(
            t.owner_id,
            list(t.pool),
            slots,
            replacement=replacement,
            player_meta=inputs.player_meta,
            playoff_odds=odds_rows,
            lineup_scores=lineup_scores,
        )

    starter_levels = {
        pos: lvl for pos, rep in replacement.items() if (lvl := rep.value("starter")) is not None
    }
    signals = {
        oid: _partner.RosterSignal.from_engine(
            oid,
            profile=ri.profile,
            window=ri.window,
            starter_levels=starter_levels,
        )
        for oid, ri in intel.items()
    }

    notes = list(inputs.notes)
    if odds_rows is not None:
        covered = {str(r.get("ownerId")) for r in odds_rows}
        missing = [t.owner_id for t in inputs.teams if t.owner_id not in covered]
        if missing:
            # This is not cosmetic.  ``league_competitiveness`` takes the
            # championship-odds percentile across the rows it was GIVEN,
            # so covered owners are ranked against a pool of
            # len(odds_rows) while uncovered owners fall back to a
            # lineup-score percentile across all teams.  Two different
            # denominators feeding one window axis is a real
            # incomparability, and each roster's
            # ``competitiveWindow.inputs.competitivenessSource`` says
            # which one it got.
            notes.append(
                f"playoff sim covers {len(covered)} of {len(inputs.teams)} rosters; "
                "covered teams take a championship-odds percentile over that "
                "smaller pool while the rest fall back to a lineup-score "
                "percentile over the full league — the two competitiveness "
                "scales are NOT comparable, so do not rank rosters across the "
                "boundary. Check competitiveWindow.inputs.competitivenessSource "
                "per roster"
            )

    return LeagueBundle(
        inputs=inputs,
        replacement=replacement,
        scarcity=scarcity,
        lineup_scores=lineup_scores,
        intel=intel,
        signals=signals,
        compute_ms=(time.perf_counter() - t0) * 1000.0,
        notes=tuple(notes),
    )


# ── Caches ───────────────────────────────────────────────────────────
# Keyed on the source stamp, never on a clock: a refresh invalidates
# immediately and a quiet hour never serves something newer than it
# claims.  One live entry per league — the previous stamp's entry is
# dropped rather than accumulated, matching ``_OVERLAY_RESPONSE_CACHE``
# in server.py.

_CACHE_LOCK = threading.Lock()
_BUNDLE_CACHE: dict[str, tuple[str, LeagueBundle]] = {}
_TEAM_CACHE: "OrderedDict[str, tuple[str, dict[str, Any]]]" = OrderedDict()

_TEAM_CACHE_MAX = 64
"""Bounded so a caller enumerating every (team, partner) pair cannot
grow the process heap without limit: 12 teams x 11 partners is 132
entries at ~90 KB each. Oldest-first eviction, and every entry for a
league is dropped outright when that league's bundle is rebuilt."""


def invalidate_cache(league_key: str | None = None) -> None:
    """Drop cached builds.  ``None`` clears every league."""
    with _CACHE_LOCK:
        if league_key is None:
            _BUNDLE_CACHE.clear()
            _TEAM_CACHE.clear()
            return
        _BUNDLE_CACHE.pop(league_key, None)
        for key in [k for k in _TEAM_CACHE if k.startswith(f"{league_key}\x00")]:
            _TEAM_CACHE.pop(key, None)


def get_league_bundle(
    league_key: str,
    scoring_profile: str,
    contract: Mapping[str, Any] | None,
) -> tuple[LeagueBundle, bool]:
    """Cached :func:`build_league_bundle`.  Returns ``(bundle, cache_hit)``.

    Loading the inputs is cheap (file stats plus one snapshot read) and
    happens on every call so the stamp is always current; only the
    ~1.35 s solve is cached.
    """
    inputs = load_league_inputs(league_key, scoring_profile, contract)
    with _CACHE_LOCK:
        cached = _BUNDLE_CACHE.get(league_key)
        if cached is not None and cached[0] == inputs.source_stamp:
            return cached[1], True

    # The lock is NOT held across the build.  Two concurrent cold
    # requests for the same league will each solve it and the second
    # write wins — a wasted 1.35 s, never a wrong answer, since the
    # build is a pure function of ``inputs``.  Holding the lock instead
    # would serialise every gameplan request in the process, including
    # requests for other leagues, behind one solve.
    bundle = build_league_bundle(inputs)
    with _CACHE_LOCK:
        _BUNDLE_CACHE[league_key] = (inputs.source_stamp, bundle)
        # Team payloads derived from a superseded bundle are stale by
        # construction; drop them with it.
        for key in [k for k in _TEAM_CACHE if k.startswith(f"{league_key}\x00")]:
            _TEAM_CACHE.pop(key, None)
    return bundle, False


# ── Candidate assembly ───────────────────────────────────────────────


def _acquirable_candidates(
    bundle: LeagueBundle, owner_id: str
) -> tuple[dict[str, list[RosterPlayer]], list[RosterPlayer]]:
    """Other rosters' tradeable surplus, as target-engine candidates.

    Surplus and not "every rostered player": ``PositionProfile
    .tradeable_surplus`` is already lineup-derived — priced value that
    does not enter its owner's optimal lineup and clears a share of the
    starter replacement level.  Offering the engines all ~600 other
    rostered players would cost an exact re-solve each and would mostly
    test players their owner will not move.

    Returns ``(by_position, flat)``.
    """
    by_position: dict[str, list[RosterPlayer]] = {}
    for oid, ri in bundle.intel.items():
        if oid == owner_id:
            continue
        team = bundle.team(oid)
        if team is None:
            continue
        by_name = {(p.canonical_name or p.player_id): p for p in team.pool}
        for pos, prof in ri.profile.positions.items():
            for name in prof.surplus_players:
                player = by_name.get(name)
                if player is None:
                    continue
                by_position.setdefault(normalize_base_position(pos) or pos, []).append(player)

    capped: dict[str, list[RosterPlayer]] = {}
    for pos, players in by_position.items():
        players.sort(key=lambda p: (-p.ros_value, p.player_id))
        capped[pos] = players[:MAX_CANDIDATES_PER_POSITION]

    flat = [p for players in capped.values() for p in players]
    return capped, flat


def _trade_assets(
    bundle: LeagueBundle, owner_id: str, *, surplus_only: bool
) -> list[_packages.TradeAsset]:
    """Package-generator assets for one roster, priced on the dynasty market.

    Only players the contract prices are included — ``value_package``
    refuses to total a package it cannot value on one market, so an
    unpriced asset would be generated and then rejected as
    ``unvaluable``, burning search budget to produce noise.
    """
    team = bundle.team(owner_id)
    if team is None:
        return []
    ri = bundle.intel.get(owner_id)
    wanted: set[str] | None = None
    if surplus_only and ri is not None:
        wanted = {name for prof in ri.profile.positions.values() for name in prof.surplus_players}

    out: list[_packages.TradeAsset] = []
    for player in team.pool:
        if wanted is not None and (player.canonical_name or player.player_id) not in wanted:
            continue
        sites = bundle.inputs.site_values.get(player.player_id)
        if not sites:
            continue
        out.append(_packages.TradeAsset.from_player(player, sites))
    out.sort(key=lambda a: (-max(a.row["canonicalSiteValues"].values()), a.asset_id))
    return out


# ── Declared consumer constraints ────────────────────────────────────

FIELD_POLICY: dict[str, Any] = {
    "nonSortable": [
        {
            "field": "targetPositions[].winNowWeight",
            "reason": (
                "null whenever the position's obtainable candidates have no known "
                "age, and those nulls are not a random subset — they cluster on "
                "positions whose upgrades happen to be un-aged. Sorting or "
                "filtering on it reorders by data availability, not by win-now "
                "value. It is reported for magnitude context only."
            ),
            "alsoNotComparableAcrossRows": (
                "The field carries two different quantities depending on "
                "viability, and the engine names them the same thing. On a "
                "VIABLE row it is horizon_weight — per-position, keyed to the "
                "age of that position's obtainable upgrades, and the thing that "
                "can reorder a ranking. On every non-viable row it is the GLOBAL "
                "win_now_weight scalar, identical across positions, because "
                "there were no candidates to take a mean age over. So two rows "
                "can differ on this field purely because one was rankable and "
                "the other was not. Compare it only within the viable set."
            ),
        }
    ],
    "nonFilterable": ["targetPositions[].winNowWeight"],
    "nullIsNotZero": [
        {
            "fields": [
                "roster.playoffOddsCi",
                "roster.championshipOddsCi",
                "targetPositions[].winNowWeight",
                "targetPositions[].marketEfficiency",
                "targetPlayers[].marketEdge",
                "needs[].replacementBaseline",
            ],
            "reason": (
                "null means the quantity was not measured. It is never collapsed "
                "to 0, and an interval is never collapsed to zero width, because "
                "a zero-width interval reads as certainty."
            ),
        }
    ],
    "neverRenamed": [
        {
            "field": "packages.frontier[].acceptancePlausibility",
            "reason": (
                "PLAUSIBILITY, never probability. Rejections are never observed — "
                "the league snapshot ingests only completed transactions — so an "
                "acceptance rate is statistically unidentifiable and no rename to "
                "'probability' is admissible. Ships with acceptanceCaveat attached."
            ),
        },
        {
            "field": "partners[].tradeAcceptanceEstimate",
            "reason": (
                "An ESTIMATE from the same uncalibratable model, capped by "
                "acceptanceConfidence. Render limitations.partner alongside it."
            ),
        },
    ],
    "noBlendedFrontierScore": (
        "packages.frontier is a Pareto set, not a ranking. valueEfficiency and "
        "acceptancePlausibility are anti-correlated by construction and no "
        "exchange rate exists between market points, lineup points and "
        "plausibility. bestBy names which axis each member wins; a caller that "
        "collapses the set to one pick is expressing a preference, not computing "
        "an answer."
    ),
}


# ── Payload assembly ─────────────────────────────────────────────────


def _league_summary(bundle: LeagueBundle) -> list[dict[str, Any]]:
    """Small per-team context row.

    A projection of the same ``RosterIntel`` objects the selected team
    returns in full — 12 full payloads is ~115 KB and most of it is
    unread. Any team's complete intel is one ``?team=<ownerId>`` away.
    """
    out: list[dict[str, Any]] = []
    for team in bundle.inputs.teams:
        ri = bundle.intel[team.owner_id]
        window = ri.window.to_dict()
        out.append(
            {
                "ownerId": team.owner_id,
                "teamName": team.team_name,
                "lineupScore": round(ri.lineup_score, 3),
                "filledSlots": ri.filled_slots,
                "totalSlots": ri.total_slots,
                "competitiveWindow": {
                    "mostLikely": window["mostLikely"],
                    "confidence": window["confidence"],
                    "affinities": window["affinities"],
                    # Deprecated alias. These are softmaxed distances to
                    # five hand-placed anchors, normalised to sum to 1.
                    # Summing to 1 does not make them calibrated
                    # probabilities — nothing was fitted to outcomes.
                    "probabilities": window["probabilities"],
                    "inputs": window["inputs"],
                    "stateOrder": window["stateOrder"],
                    "orderingCaveat": window["orderingCaveat"],
                    # Audit finding H: this projection used to DROP notes,
                    # so an API consumer could not see "no state cleared
                    # 30%" or that competitiveness came from the
                    # lineupScoreRank proxy rather than simulated odds.
                    # Those are exactly the caveats a caller needs.
                    "notes": window.get("notes") or [],
                },
                "playoffOdds": ri.playoff_odds,
                "playoffOddsCi": list(ri.playoff_odds_ci) if ri.playoff_odds_ci else None,
                "championshipOdds": ri.championship_odds,
                "championshipOddsCi": (
                    list(ri.championship_odds_ci) if ri.championship_odds_ci else None
                ),
                "oddsSource": ri.odds_source,
            }
        )
    out.sort(key=lambda r: (-r["lineupScore"], r["ownerId"]))
    return out


def _coverage(
    bundle: LeagueBundle,
    owner_id: str,
    candidates: Mapping[str, Sequence[RosterPlayer]],
    target_players: Sequence[_targets.PlayerTarget],
) -> dict[str, Any]:
    """What was measured, what abstained, and why.

    An absent input and a genuinely neutral measurement look identical
    downstream, so the difference is stated here rather than left for a
    reader to infer from a suspiciously round number.
    """
    inputs = bundle.inputs
    rostered = [p for t in inputs.teams for p in t.pool]
    aged = sum(1 for p in rostered if p.player_id in inputs.player_meta)
    priced = sum(1 for p in rostered if p.player_id in inputs.site_values)
    odds_rows = inputs.playoff_odds or ()
    covered = {str(r.get("ownerId")) for r in odds_rows}
    recommended = sum(1 for t in target_players if t.recommended)

    return {
        "rosters": len(inputs.teams),
        "rosteredPlayers": len(rostered),
        "starterSlots": len(inputs.slots),
        "ageCoverage": {
            "withAge": aged,
            "total": len(rostered),
            "source": "live contract playersArray (scoring-profile scoped)",
        },
        "marketPriceCoverage": {
            "priced": priced,
            "total": len(rostered),
            "scale": "canonicalSiteValues, 0-9999 dynasty market",
        },
        "playoffSimCoverage": {
            "owners": len(covered & {t.owner_id for t in inputs.teams}),
            "total": len(inputs.teams),
            "source": "data/ros/sims (league-scoped)",
        },
        "candidatePolicy": {
            "source": "other rosters' tradeable surplus, from PositionProfile.surplusPlayers",
            "maxPerPosition": MAX_CANDIDATES_PER_POSITION,
            "offered": sum(len(v) for v in candidates.values()),
            "byPosition": {k: len(v) for k, v in sorted(candidates.items())},
            "exhaustive": False,
            "note": (
                "Candidates are capped per position in descending rosValue. Value "
                "order is not gain order for hybrid IDPs — a DL/LB can out-gain a "
                "higher-valued pure DL by filling a slot the other cannot — so a "
                "better target can be outside the cap. A position reported "
                "noCandidates means NOT MEASURED, never 'nothing available'."
            ),
        },
        "marketEdgeUnmeasured": {
            "reason": (
                "The target engines compute edge as (rosValue - price) / price. "
                "rosValue is a 0-100 rest-of-season strength index (normalized "
                "log-rank, not points); the only prices this "
                "server holds are canonicalSiteValues on the 0-9999 dynasty "
                "market. No validated conversion exists between them, and feeding "
                "one to the other yields an edge near -1 for every player — a "
                "dead signal that still looks computed. So market_values is not "
                "supplied and marketEdge is null throughout."
            ),
            "wouldUnlock": "a rest-of-season-denominated acquisition price per player",
        },
        "corroborationYield": {
            "recommended": recommended,
            "evaluated": len(target_players),
            "note": (
                "A player is never recommended on our own valuation alone. With "
                "no external role or projection data wired, the only admissible "
                "corroborators are measured lineup fit and positional scarcity, "
                "and every rejection carries its own reason. The yield is a "
                "property of the ROSTER, not a constant: measured on the real "
                "league it is 1 of 71 for the strongest team (nothing on offer "
                "improves it) and 40 of 76 for the weakest. A yield near 100% "
                "would mean a corroborator had been fabricated — supplying a "
                "plausible-looking availability map moves the strongest team "
                "from 1 of 97 to 93 of 97, which is the exact failure this gate "
                "exists to prevent."
            ),
        },
        "ownerId": owner_id,
    }


def build_gameplan(
    bundle: LeagueBundle,
    owner_id: str,
    *,
    partner_owner_id: str | None = None,
    cache_hit: bool = False,
) -> dict[str, Any]:
    """Assemble one team's gameplan payload.

    Engine ``to_dict()`` output is passed through unchanged rather than
    re-projected field by field — a hand-rolled projection is how a
    caveat gets dropped in a refactor.
    """
    t0 = time.perf_counter()
    team = bundle.team(owner_id)
    if team is None:
        raise TeamNotInLeague(owner_id)
    ri = bundle.intel[owner_id]
    slots = list(bundle.inputs.slots)

    # ── partners ─────────────────────────────────────────────────────
    partners = _partner.assess_partners(
        [
            _partner.PartnerInputs(
                owner_id=other.owner_id,
                display_name=other.team_name,
                our_roster=bundle.signals[owner_id],
                their_roster=bundle.signals[other.owner_id],
            )
            for other in bundle.inputs.teams
            if other.owner_id != owner_id
        ]
    )

    # ── targets ──────────────────────────────────────────────────────
    candidates, flat = _acquirable_candidates(bundle, owner_id)
    candidate_ages = {
        p.player_id: float(bundle.inputs.player_meta[p.player_id]["age"])
        for p in flat
        if p.player_id in bundle.inputs.player_meta
    }
    target_positions = _targets.rank_target_positions(
        list(team.pool),
        slots,
        profile=ri.profile,
        candidates=candidates,
        window=ri.window,
        scarcity=bundle.scarcity,
        replacement=bundle.replacement,
        candidate_ages=candidate_ages,
        # market_prices deliberately omitted — see coverage.marketEdgeUnmeasured.
    )
    target_players = _targets.rank_target_players(
        list(team.pool),
        slots,
        flat,
        scarcity=bundle.scarcity,
        # market_values / availability deliberately omitted. Availability
        # would have to be invented, and an invented corroborator defeats
        # the exact gate that makes this engine trustworthy: supplying a
        # plausible-looking one flips the real league from 1 of 97
        # recommended to 93 of 97.
    )

    # ── packages (only against a named counterparty) ─────────────────
    packages_payload: dict[str, Any] | None = None
    if partner_owner_id:
        packages_payload = _build_packages(bundle, owner_id, partner_owner_id)

    payload: dict[str, Any] = {
        "contractVersion": GAMEPLAN_CONTRACT_VERSION,
        "leagueKey": bundle.inputs.league_key,
        "scoringProfile": bundle.inputs.scoring_profile,
        "team": {"ownerId": team.owner_id, "teamName": team.team_name},
        "roster": ri.to_dict(),
        "partners": [p.to_dict() for p in partners],
        "targetPositions": [t.to_dict() for t in target_positions],
        "targetPlayers": [t.to_dict() for t in target_players],
        "packages": packages_payload,
        "league": _league_summary(bundle),
        "coverage": _coverage(bundle, owner_id, candidates, target_players),
        "notes": list(bundle.notes),
        "fieldPolicy": FIELD_POLICY,
        "limitations": {
            "targets": _targets.describe_limitations(),
            "partner": _partner.describe_limitations(),
            "packages": _packages.describe_limitations(),
        },
        "timing": {
            "leagueBuildMs": round(bundle.compute_ms, 1),
            "teamBuildMs": round((time.perf_counter() - t0) * 1000.0, 1),
            "leagueBuildCached": cache_hit,
            "sourceStamp": bundle.inputs.source_stamp,
        },
    }
    if packages_payload is None:
        payload["packagesOmitted"] = {
            "reason": "no partner requested",
            "howTo": (
                "pass ?partner=<ownerId> from the partners list. Packages are "
                "generated against ONE named counterparty because the generator's "
                "quality and cost both hinge on the caller pre-filtering which "
                "assets are in play, and running all partners costs ~1.6 s."
            ),
        }
    return payload


def _build_packages(bundle: LeagueBundle, owner_id: str, partner_owner_id: str) -> dict[str, Any]:
    """Trade Package Generator output against one counterparty."""
    partner_team = bundle.team(partner_owner_id)
    if partner_team is None:
        return {
            "error": "unknown_partner",
            "message": f"No roster for owner {partner_owner_id!r} in this league.",
            "frontier": [],
            "bestBy": {},
        }

    ours = _trade_assets(bundle, owner_id, surplus_only=True)[:MAX_PACKAGE_ASSETS_PER_SIDE]
    theirs = _trade_assets(bundle, partner_owner_id, surplus_only=True)[
        :MAX_PACKAGE_ASSETS_PER_SIDE
    ]
    # Cornerstones must come from their FULL roster: derived from the
    # filtered ask list, every asset looks elite relative to that list
    # and the premium rule refuses almost every package.
    their_full = _trade_assets(bundle, partner_owner_id, surplus_only=False)

    roster_settings = _roster_limit(bundle.inputs.league_key)
    result = _packages.generate_packages(
        list(bundle.team(owner_id).pool),
        list(bundle.inputs.slots),
        our_assets=ours,
        their_assets=theirs,
        their_full_roster=their_full,
        partner_owner_id=partner_owner_id,
        our_signal=bundle.signals[owner_id],
        their_signal=bundle.signals[partner_owner_id],
        roster_limit=roster_settings,
        gate_pct=DEFAULT_GATE_PCT,
    )
    result["partner"] = {
        "ownerId": partner_owner_id,
        "teamName": partner_team.team_name,
    }
    result["assetPolicy"] = {
        "ourAssetsOffered": len(ours),
        "theirAssetsOffered": len(theirs),
        "maxPerSide": MAX_PACKAGE_ASSETS_PER_SIDE,
        "filter": "tradeable surplus that the contract prices on the dynasty market",
        "note": (
            "Unpriced assets are excluded before generation: value_package "
            "refuses to total a package it cannot value on one market, so "
            "including them would spend search budget producing 'unvaluable' "
            "rejections."
        ),
    }
    return result


def _roster_limit(league_key: str) -> int | None:
    """League roster-size cap for the legality rule, or None.

    Delegates to ``src/trade/roster_capacity.league_roster_limit`` — the one
    resolver.  This function and ``src/draft/context._roster_size_for`` both
    read ``rosterSettings.rosterSize`` behind their own try/except until
    2026-08-18, which is two answers to a question that has one.
    """
    from src.trade.roster_capacity import league_roster_limit  # noqa: PLC0415

    return league_roster_limit(league_key)


def get_team_gameplan(
    league_key: str,
    scoring_profile: str,
    contract: Mapping[str, Any] | None,
    owner_id: str,
    *,
    partner_owner_id: str | None = None,
) -> dict[str, Any]:
    """Cached end-to-end build for one team.  Runs off the event loop.

    Package payloads are cached under their own key so asking about a
    second partner does not rebuild the ~550 ms target section.
    """
    bundle, cache_hit = get_league_bundle(league_key, scoring_profile, contract)
    if bundle.team(owner_id) is None:
        raise TeamNotInLeague(owner_id)

    stamp = bundle.inputs.source_stamp
    cache_key = "\x00".join([league_key, stamp, owner_id, partner_owner_id or ""])
    with _CACHE_LOCK:
        cached = _TEAM_CACHE.get(cache_key)
        if cached is not None and cached[0] == stamp:
            _TEAM_CACHE.move_to_end(cache_key)
            payload = dict(cached[1])
            # Both flags describe THIS request, not the request that
            # populated the cache.  Returning the stored payload
            # verbatim replays the cold build's ``leagueBuildCached:
            # false`` forever, which makes the timing block lie in the
            # one direction that matters — it would read as though the
            # 1.35 s solve ran on every request.
            payload["timing"] = {
                **payload["timing"],
                "teamBuildCached": True,
                "leagueBuildCached": cache_hit,
            }
            return payload

    payload = build_gameplan(
        bundle, owner_id, partner_owner_id=partner_owner_id, cache_hit=cache_hit
    )
    payload["timing"]["teamBuildCached"] = False
    with _CACHE_LOCK:
        _TEAM_CACHE[cache_key] = (stamp, payload)
        _TEAM_CACHE.move_to_end(cache_key)
        while len(_TEAM_CACHE) > _TEAM_CACHE_MAX:
            _TEAM_CACHE.popitem(last=False)
    return payload


# ── Tier 2: IDP positional scoring fit ───────────────────────────────

_LOGGER = logging.getLogger(__name__)

_SCORING_FIT_CACHE: dict[str, Any] = {}


def invalidate_scoring_fit_cache() -> None:
    """Drop the memoised measurement.  Tests and a scoring change."""
    _SCORING_FIT_CACHE.clear()


_RECEPTION_FIT_CACHE: dict[str, Any] = {}


def invalidate_reception_fit_cache() -> None:
    _RECEPTION_FIT_CACHE.clear()


def _resolve_reception_fit(league_key: str) -> dict[str, float] | None:
    """Per-player reception-depth multipliers, keyed by canonical NAME.

    The measurement is keyed by GSIS id; contract rows are keyed by
    display name. The join happens here rather than in the adjustment
    model because this is where both identifiers are in scope — the
    weekly stat rows carry ``player_id`` (GSIS) and
    ``player_display_name`` together, so the mapping is free.

    Returns None — an ABSENT axis — when the flag is off, the inputs are
    missing, or the measurement refuses itself. Never raises.
    """
    from src.api import feature_flags  # noqa: PLC0415

    if not feature_flags.is_enabled("reception_scoring_fit"):
        return None
    if league_key in _RECEPTION_FIT_CACHE:
        return _RECEPTION_FIT_CACHE[league_key]

    by_name: dict[str, float] | None = None
    try:
        from src.league_comparison.scoring_engine import (  # noqa: PLC0415
            compute_player_season_scores,
        )
        from src.league_comparison.service import _load_config  # noqa: PLC0415
        from src.league_comparison.sleeper_scoring import (  # noqa: PLC0415
            fetch_league_scoring,
        )
        from src.league_intel.reception_fit import (  # noqa: PLC0415
            measure_reception_depth_fit,
            reception_scoring_keys,
        )
        from src.nfl_data.ingest import fetch_weekly_stats  # noqa: PLC0415
        from src.nfl_data.pbp_weekly import SeasonPbpIndex  # noqa: PLC0415
        from src.nfl_data.reception_depth import load_reception_depth  # noqa: PLC0415
        from src.utils.name_clean import resolve_canonical_name  # noqa: PLC0415

        cfg = _load_config()
        mine_id = str((cfg.get("my_league") or {}).get("id") or "")
        base_id = str((cfg.get("baseline_league") or {}).get("id") or "")
        seasons = [int(s) for s in (cfg.get("seasons") or []) if str(s).isdigit()]
        season = max(seasons) if seasons else None
        depth = load_reception_depth(season) if season else None

        if mine_id and base_id and season and depth:
            mine = fetch_league_scoring(mine_id).scoring_settings
            baseline = fetch_league_scoring(base_id).scoring_settings
            rows = fetch_weekly_stats([season])
            if mine and baseline and rows:
                # Reception share is measured under the BASELINE card:
                # that is the card the market prices on, so it is the
                # right denominator for "how much of this player's
                # market value is reception-driven".
                stripped = {k: v for k, v in baseline.items() if k not in reception_scoring_keys()}
                # The supplement corrects the DENOMINATOR here, not the
                # numerator, and it is worth being precise about which:
                # this share is measured under the BASELINE card, which
                # pays 0.0 for every reception band, so joining it moves a
                # pure receiver's share by exactly nothing.  What it does
                # move is a player who also plays special teams — the
                # baseline card pays st_tkl_solo 1.25 and st_ff 4.0, and
                # those points belong in his total.  Measured over 17
                # weeks at 6 catches / 80 yards a week: 36.00% with no ST
                # production either way, 36.00% -> 32.73% at one ST tackle
                # a week, 36.00% -> 27.69% at three.
                #
                # Overstating this was tempting and would have been wrong:
                # the large effect is in league_intel/scoring_fit.py, where
                # BOTH cards are scored and only one of them bands.
                pbp_for_season = SeasonPbpIndex().for_season
                full = {
                    s.player_id: s
                    for s in compute_player_season_scores(
                        rows, baseline, season=season, pbp_for_season=pbp_for_season
                    )
                }
                norec = {
                    s.player_id: s
                    for s in compute_player_season_scores(
                        rows, stripped, season=season, pbp_for_season=pbp_for_season
                    )
                }
                shares = {
                    pid: (s.total_points - (norec[pid].total_points if pid in norec else 0.0))
                    / s.total_points
                    for pid, s in full.items()
                    if s.total_points > 0
                }
                measurement = measure_reception_depth_fit(
                    depth, shares, mine, baseline, season=season
                )
                if measurement.trusted:
                    names = {s.player_id: s.player_name for s in full.values() if s.player_name}
                    by_name = {}
                    for gsis, mult in measurement.multipliers.items():
                        key = resolve_canonical_name(names.get(gsis, ""))
                        if key:
                            by_name[key] = mult
                    if not by_name:
                        # Every id failed to resolve to a name. An empty
                        # map and "the feature is off" are different
                        # states and must not read the same.
                        _LOGGER.warning(
                            "reception fit measured %d players but none resolved to a "
                            "name; serving no overlay",
                            len(measurement.multipliers),
                        )
                        by_name = None
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("reception fit unavailable for %s: %r", league_key, exc)
        by_name = None

    _RECEPTION_FIT_CACHE[league_key] = by_name
    return by_name


def _resolve_scoring_fit(league_key: str) -> Any | None:
    """This league's IDP positional scoring tilt, or None.

    Returns None — meaning an ABSENT axis, arithmetically inert —
    whenever the flag is off, the stat rows are unavailable, or the
    measurement refuses itself. Never raises: an optional lens must not
    be able to take down the board it decorates.

    Memoised per league. The measurement scores ~19k player-weeks under
    two rate cards, which is far too expensive for a per-request path,
    and its inputs (a completed season's stats, two rate cards) change
    on the order of weeks.
    """
    from src.api import feature_flags  # noqa: PLC0415

    if not feature_flags.is_enabled("idp_scoring_fit"):
        return None
    if league_key in _SCORING_FIT_CACHE:
        return _SCORING_FIT_CACHE[league_key]

    measurement = None
    try:
        from src.league_comparison.service import _load_config  # noqa: PLC0415
        from src.league_comparison.sleeper_scoring import (  # noqa: PLC0415
            fetch_league_scoring,
        )
        from src.league_intel.scoring_fit import (  # noqa: PLC0415
            measure_positional_scoring_fit,
        )
        from src.nfl_data.ingest import fetch_weekly_defensive_stats  # noqa: PLC0415

        cfg = _load_config()
        mine_id = str((cfg.get("my_league") or {}).get("id") or "")
        base_id = str((cfg.get("baseline_league") or {}).get("id") or "")
        seasons = [int(s) for s in (cfg.get("seasons") or []) if str(s).isdigit()]
        season = max(seasons) if seasons else None
        if mine_id and base_id and season:
            mine = fetch_league_scoring(mine_id).scoring_settings
            baseline = fetch_league_scoring(base_id).scoring_settings
            rows = fetch_weekly_defensive_stats([season])
            if mine and baseline and rows:
                measurement = measure_positional_scoring_fit(rows, mine, baseline, season=season)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("scoring fit unavailable for %s: %r", league_key, exc)
        measurement = None

    _SCORING_FIT_CACHE[league_key] = measurement
    return measurement


# ── LI-9: league-adjusted values ─────────────────────────────────────


def get_league_adjusted_values(
    league_key: str,
    scoring_profile: str,
    contract: Mapping[str, Any] | None,
    *,
    include_explanations: bool = False,
) -> dict[str, Any]:
    """This league's league-adjusted board, as a client-side overlay.

    Reuses the cached :func:`get_league_bundle` solve purely for its
    ``scarcity`` — the ~1.35 s replacement build is already paid for by
    ``/api/gameplan``, so this endpoint is near-free on a warm league
    and never triggers a second solve.

    LEAGUE-SCOPED by necessity, not convention: ``lineupScarcity`` is
    measured from this league's twelve rosters, so two leagues sharing
    a scoring profile get genuinely different values here.  That is why
    the result is an overlay rather than contract fields — see
    :mod:`src.league_intel.publish`.
    """
    from src.league_intel.publish import build_league_adjusted_payload  # noqa: PLC0415

    bundle, cache_hit = get_league_bundle(league_key, scoring_profile, contract)

    config_version: int | None = None
    try:
        from src.league_intel.config import load_canonical_config  # noqa: PLC0415

        config_version = load_canonical_config().config_version
    except Exception:  # noqa: BLE001
        # A missing canonical snapshot must not deny the whole board.
        # The stamp goes out as null and the payload says so, which is
        # honest; refusing to serve would be worse than serving values
        # whose config version we cannot name.
        config_version = None

    rows = (contract or {}).get("playersArray") or []
    payload = build_league_adjusted_payload(
        rows,
        bundle.scarcity,
        league_key=league_key,
        scoring_fit=_resolve_scoring_fit(league_key),
        reception_fit=_resolve_reception_fit(league_key),
        config_version=config_version,
        data_through=(contract or {}).get("date"),
        # Version pin: the client refuses to apply an overlay whose
        # contract build does not match the base it fetched, rather than
        # applying board B's ranks to board A's values.
        contract_version=(contract or {}).get("contractVersion"),
        scrape_timestamp=(contract or {}).get("scrapeTimestamp"),
        include_explanations=include_explanations,
    )
    payload["cacheHit"] = cache_hit
    return payload
