"""Trade -> title-odds delta: Analyze Trade's ``titleOdds`` lens (DYN10 #4).

Owner directive 2026-11-21 (intake DYN10, top-10 item #4), authorized by the
2026-11-21 section of ``docs/EXECUTION_PLAN.md``: anything that changes a
recommendation, verdict or served value ships behind a default-OFF flag, and
turning a flag ON is owner-reserved.  This lens changes none of those — it
never votes — but it is a new served block, so it ships behind
``trade_title_odds_lens`` (default OFF, owner-held: ``deploy/verify-deploy.sh``
fails a deploy whose effective flag is ON, ``scripts/verify_owner_held_flags.py``).
OFF, nothing in this module runs and every Analyze Trade payload is byte-identical
to the pre-lens one (``tests/trade/test_title_odds_lens.py``).

What it answers
───────────────
For every team in a team-attributed trade: this season's playoff and
championship probability before and after the trade, a paired interval on the
change, and whether the change is distinguishable from simulation noise
(``significant``).  It is the packet's ``currentSeasonEquity`` dimension, named
UNAVAILABLE (``counterfactual_not_wired``) until this module existed.

Composition only — no new simulator, no second points model
───────────────────────────────────────────────────────────
1. **Roster change -> weekly-mean change** for every team whose ROSTER changes:
   ``src.league_intel.twin.strength_deltas_from_rosters`` (the LI-8 bridge), fed
   the SAME team-strength ``fullRoster`` rows the playoff engine's best-ball
   presim draws from, the league's own starter slots, the served points model,
   and the simulator's own ROS z-scores (``playoff_sim.ros_z_scores``), so each
   delta is in ``_TeamDist.mean`` units under whichever ROS equation is served
   (``playoff_ros_counted_once`` is READ through ``presim_ros_blend``, never set).
2. **Odds before/after**: ONE ``playoff_sim.simulate_trade_impact`` call carrying
   every changed team's delta at once (a trade is simultaneous).  That function
   resolves the league's bracket ONCE (``src.public_league.playoff_structure``)
   and pins both arms to it, on one shared seed and one simulation count.  This
   module never passes its own seeds / byes / reseed rule, so the two arms can
   never be measured on different brackets.
3. **What the bridge says not to feed, is not fed.**  ``twin.py``: the trade's
   change in weekly SPREAD (``sdDelta``) is reported per team but NOT handed to
   ``simulate_trade_impact``, which copies ``sd`` unchanged by design; feeding it
   would mean re-deriving the distributions.  Owners whose roster cannot be
   simulated are never entered as 0.0 — the whole lens is unavailable instead,
   because a partial map would present a one-sided trade.

Never a vote
────────────
The lens is CONTEXT (``votes=False``, direction ``"context"``).  It is built
outside ``analyze_trade`` (which computes nothing) and handed in like the
comparables payload; ``trade_decision.leaning`` / ``decide`` / ``status_quo``
are never passed it, so it cannot move the decision, the leaning, the gap, the
fairness band, the confidence or any value.  Pinned by test.

Unavailable is never zero
─────────────────────────
Every state the lens cannot answer is ``state: "unavailable"`` with a ``reason``
— a league with no recorded playoff rules (``league_not_configured``; today
only ``dynasty_main`` is recorded in ``config/leagues/playoff_rules.json``), a
start/sit league, no league snapshot, no remaining schedule (preseason before a
schedule exists, or the regular season is over), no team-strength rosters, a
roster the trade cannot be applied to, an unresolved counterparty, or any
refusal the playoff engine itself returns (its ``unsimulable`` reason passes
through verbatim).  None of them is a zero-impact trade.  A trade in which no
rostered player moves (picks only) IS measured: both rosters are unchanged, so
the delta is exactly zero and ``significant`` is false — a real answer, not a
default.

Bounded cost
────────────
``TWIN_WEEKS`` paired best-ball weeks per changed roster and ``N_SIMULATIONS``
pinned seasons per arm; both are fixed (never adaptive), so the cost is bounded
by the number of changed rosters.  The roster bridge dominates (its per-week
lineup solve is the full ``optimize_lineup``), then the playoff engine's own
best-ball presim, which ``simulate_trade_impact`` runs once for the base and
once per arm.  Measured 2026-11-22 on a 12-team, 57-man best-ball fixture with
``dynasty_main``'s real 21 starter slots, real presim, bridge and Monte Carlo
(snapshot readers stubbed): a 2-team, 3-player trade took a median 5.5 s
(bridge 2.8 s for the two changed rosters, ``simulate_trade_impact`` 2.5 s);
each further changed roster adds about 1.4 s.  The bridge's own sampling
noise on that trade, across six seeds at 200 weeks, was a standard deviation
of 0.46-0.64 points a week on deltas of 17-20 — disclosed in ``assumptions``
because it is not inside the odds interval.  The async route reports its own
wall time as ``computation.ms``.

Served asynchronously (activation lane, 2026-11-22)
───────────────────────────────────────────────────
``/api/trade/analyze`` never waits for those seconds.  With the flag ON it
computes nothing and hands Analyze Trade the :func:`deferred` envelope
(``state: "unavailable"``, reason ``deferred_async``), so the packet names the
dimension and says where it is served.  The odds come from
``POST /api/trade/title-odds`` (:data:`ASYNC_ROUTE`), which the War Room calls
after the analysis has arrived; that route runs this module in the threadpool
under the route's admission bound (``src/api/compute_admission.py``: a full
route answers ``title_odds_busy``, a caller waits at most its deadline and then
gets ``title_odds_timeout``) and caches per (user, league, board generation,
:func:`trade_signature`) in ``src/api/trade_title_odds_runtime.py``.
``/api/trade/analyze-multi`` computes nothing either: it hands every team
:func:`deferred_for_ledger` (``deferred_async`` for two teams,
``not_computed_multi_team`` for three or more).

The odds are uncalibrated
─────────────────────────
Every payload carries the owner-approved disclosure (``ODR-ODDS-WORDING``,
``docs/owner/OWNER_DECISION_REGISTER.md``), whose one copy for display is
``frontend/lib/odds-disclosure.js::ODDS_EXPERIMENTAL_DISCLOSURE``;
``ODDS_DISCLOSURE`` below is held to it byte for byte by test.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

LOG = logging.getLogger(__name__)

#: The flag (``src/api/feature_flags.py``).  Owner-held OFF.
FLAG = "trade_title_odds_lens"
LENS_VERSION = "trade_title_odds_v1"

#: Pinned season simulations per arm (both arms identical — the paired design).
N_SIMULATIONS = 5000
#: Paired best-ball weeks the roster bridge simulates per changed roster.
TWIN_WEEKS = 200
#: The roster bridge's per-player seed base (``league_intel.sim._draw_week``).
TWIN_SEED = 0
#: The shared season seed (``simulate_trade_impact``'s own default), stamped.
IMPACT_SEED = 20260726

#: Owner-approved wording for every uncalibrated odds surface (owner decision
#: register ``ODR-ODDS-WORDING``).  Display copy is owned by
#: ``frontend/lib/odds-disclosure.js``; this is the backend's copy of the same
#: bytes, pinned to it by ``tests/trade/test_title_odds_lens.py``.
ODDS_DISCLOSURE = (
    "Experimental projection — not yet calibrated against this league's historical outcomes."
)
ODDS_DISCLOSURE_DECISION = "ODR-ODDS-WORDING"
ODDS_DISCLOSURE_OWNER = "frontend/lib/odds-disclosure.js::ODDS_EXPERIMENTAL_DISCLOSURE"

STATE_OK = "ok"
STATE_UNAVAILABLE = "unavailable"

REASON_LEAGUE_NOT_CONFIGURED = "league_not_configured"
REASON_NOT_BEST_BALL = "league_not_best_ball"
REASON_NO_SNAPSHOT = "league_snapshot_unavailable"
REASON_SNAPSHOT_MISMATCH = "league_snapshot_mismatch"
REASON_NO_SCHEDULE = "no_remaining_schedule"
REASON_FULL_ROSTER = "full_roster_unavailable"
REASON_STARTER_SLOTS = "starter_slots_unavailable"
REASON_ROSTER_MISMATCH = "roster_snapshot_mismatch"
REASON_ASSET_UNRESOLVED = "trade_asset_unresolved"
REASON_COUNTERPARTY_UNRESOLVED = "counterparty_unresolved"
REASON_MULTIPLE_COUNTERPARTIES = "multiple_counterparties"
REASON_STRENGTH_DELTA = "strength_delta_unavailable"
REASON_NO_DISTRIBUTIONS = "no_team_distributions"
REASON_TEAM_NOT_SIMULATED = "team_not_in_simulation"
REASON_ERROR = "title_odds_error"
REASON_ASSET_ONLY = "asset_only_mode"
#: Analyze Trade does not compute the odds; :data:`ASYNC_ROUTE` serves them.
REASON_DEFERRED_ASYNC = "deferred_async"
#: The async route's computation did not finish inside its bound.
REASON_TIMEOUT = "title_odds_timeout"
#: The async route was already running as many season simulations as its
#: admission bound allows (``src/api/compute_admission.py``); retryable.
REASON_BUSY = "title_odds_busy"
#: Multi-team analysis (``/api/trade/analyze-multi``) does not compute the odds
#: for a trade of three or more teams; the async route serves 2-team trades.
REASON_NOT_COMPUTED_MULTI_TEAM = "not_computed_multi_team"

#: The private route that serves this lens (``server.py``).
ASYNC_ROUTE = "/api/trade/title-odds"

_DETAIL = {
    REASON_LEAGUE_NOT_CONFIGURED: (
        "this league has no recorded playoff rules (config/leagues/playoff_rules.json), "
        "so its title odds are not simulated for a trade."
    ),
    REASON_NOT_BEST_BALL: (
        "the roster bridge simulates best-ball weeks; this league sets lineups, so a "
        "trade's weekly-scoring change would be measured under the wrong format."
    ),
    REASON_NO_SNAPSHOT: "the league snapshot the playoff engine needs is not available.",
    REASON_SNAPSHOT_MISMATCH: "the available league snapshot belongs to a different league.",
    REASON_NO_SCHEDULE: (
        "no regular-season matchups remain on the posted schedule (preseason before a "
        "schedule exists, or the regular season is over), so there is no season left "
        "for the trade to change."
    ),
    # ``playoff_sim.TEAM_STRENGTH_UNAVAILABLE`` — the playoff engine's own word.
    "team_strength_unavailable": (
        "no team-strength rosters are available for this league, so no roster "
        "change can be simulated."
    ),
    REASON_FULL_ROSTER: (
        "a trade team has no full roster in the team-strength snapshot; a truncated "
        "roster is the wrong input to a best-ball simulation."
    ),
    REASON_STARTER_SLOTS: "this league's starter slots could not be resolved.",
    REASON_ROSTER_MISMATCH: (
        "a moving player is not on the sending team's roster in the team-strength "
        "snapshot (the rosters have moved since it was taken)."
    ),
    REASON_ASSET_UNRESOLVED: "a traded player could not be identified by Sleeper id.",
    REASON_COUNTERPARTY_UNRESOLVED: (
        "the request names no counterparty and no incoming asset has a current holder, "
        "so who receives the outgoing players is unknown."
    ),
    REASON_MULTIPLE_COUNTERPARTIES: (
        "the incoming assets are held by more than one other team; analyse it as a "
        "multi-team trade."
    ),
    REASON_STRENGTH_DELTA: (
        "a changed roster could not be simulated (too few priced players), and a "
        "partial set of changes would present a one-sided trade."
    ),
    REASON_NO_DISTRIBUTIONS: "no team score distributions could be built.",
    REASON_TEAM_NOT_SIMULATED: "this team has no row in the season simulation.",
    REASON_ERROR: "the title-odds computation failed.",
    REASON_ASSET_ONLY: "not included in Asset-Only analysis.",
    REASON_DEFERRED_ASYNC: (
        "computed separately (POST /api/trade/title-odds) so the analysis never waits "
        "for the season simulation."
    ),
    REASON_TIMEOUT: (
        "the season simulation did not finish in time; it keeps running, and asking "
        "again shortly returns its result."
    ),
    REASON_BUSY: (
        "the server is already running as many season simulations as it allows; "
        "asking again in a moment starts this one."
    ),
    REASON_NOT_COMPUTED_MULTI_TEAM: (
        "not computed for a trade of three or more teams (each extra changed roster adds "
        "to a season simulation of several seconds); two-team trades are served by "
        "POST /api/trade/title-odds."
    ),
}

_LENS_ASSUMPTIONS = (
    "The interval and the significant flag cover the season simulation's noise only. "
    "Each team's weekly-mean change is a point estimate from the roster bridge's "
    "paired best-ball weeks; its own Monte Carlo error is not inside the interval.",
    "Player availability is not applied to the roster change: the playoff engine's "
    "presim removes a player in the weeks he is out, the roster bridge draws every "
    "rostered player every week.",
    "Draft picks do not play this season, so a pick moves no weekly score.",
)
COUNTERPARTY_INFERRED_NOTE = (
    "The request names no counterparty: it is inferred as the current holder of the "
    "incoming assets, and it receives every outgoing player."
)


def enabled() -> bool:
    """Whether the lens is computed (``trade_title_odds_lens``, owner-held OFF)."""
    from src.api.feature_flags import is_enabled  # noqa: PLC0415

    return is_enabled("trade_title_odds_lens")


def disclosure() -> dict[str, str]:
    return {
        "text": ODDS_DISCLOSURE,
        "decision": ODDS_DISCLOSURE_DECISION,
        "owner": ODDS_DISCLOSURE_OWNER,
    }


def unavailable(reason: str, detail: str | None = None, **extra: Any) -> dict[str, Any]:
    """The full envelope with ``state: "unavailable"`` — never a zero."""
    out: dict[str, Any] = {
        "version": LENS_VERSION,
        "state": STATE_UNAVAILABLE,
        "reason": str(reason),
        "detail": detail if detail is not None else _DETAIL.get(reason),
        "teams": [],
        "disclosure": disclosure(),
        "role": "context_not_vote",
    }
    out.update(extra)
    return out


ASSET_ONLY_MARKER: dict[str, Any] = {"state": STATE_UNAVAILABLE, "reason": REASON_ASSET_ONLY}


def deferred() -> dict[str, Any]:
    """What ``/api/trade/analyze`` hands Analyze Trade with the flag ON.

    The odds are served by :data:`ASYNC_ROUTE`, so the analysis never waits for
    them; the dimension stays named, ``state: "unavailable"`` with the reason
    ``deferred_async`` — never a zero delta and never silently absent.
    """
    return unavailable(REASON_DEFERRED_ASYNC, route=ASYNC_ROUTE)


def deferred_for_ledger(ledger: Any) -> dict[str, Any]:
    """What ``/api/trade/analyze-multi`` hands every team's analysis with the
    flag ON (its ``title_odds_provider``): nothing is computed there.

    A 2-team ledger gets :func:`deferred` — :data:`ASYNC_ROUTE` serves that
    trade.  Three or more teams get ``not_computed_multi_team``: the async
    route answers 2-team trades only, so pointing there would be untrue.
    Either way the dimension stays named and unavailable, never a zero.
    """
    teams = getattr(ledger, "teams", None) or ()
    if len(teams) == 2:
        return deferred()
    return unavailable(REASON_NOT_COMPUTED_MULTI_TEAM)


def league_configured(league_key: str | None) -> bool:
    """A league whose playoff rules are recorded by their one owner."""
    from src.public_league.playoff_structure import league_playoff_rules  # noqa: PLC0415

    return league_playoff_rules(league_key) is not None


def _league_best_ball(league_key: str) -> bool:
    try:
        from src.api.league_registry import get_league_by_key  # noqa: PLC0415

        cfg = get_league_by_key(league_key)
    except Exception:  # noqa: BLE001 — an unresolvable league is not best ball
        return False
    return bool(cfg is not None and getattr(cfg, "best_ball", False))


# ── Trade moves ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TradeMoves:
    """Every team in the trade and every rostered player that changes team.

    ``player_moves`` are ``(playerId, fromOwnerId, toOwnerId)``.  Picks are not
    listed: they do not play this season.
    """

    teams: tuple[str, ...]
    player_moves: tuple[tuple[str, str, str], ...] = ()
    counterparty_inferred: bool = False
    unavailable_reason: str | None = None


def owner_by_roster_id(contract: Mapping[str, Any] | None) -> dict[int, str]:
    """``rosterId -> ownerId`` from the contract's ``sleeper.teams``."""
    sleeper = contract.get("sleeper") if isinstance(contract, Mapping) else None
    teams = sleeper.get("teams") if isinstance(sleeper, Mapping) else None
    out: dict[int, str] = {}
    for t in teams if isinstance(teams, list) else []:
        if not isinstance(t, Mapping):
            continue
        owner = str(t.get("ownerId") or "").strip()
        for key in ("roster_id", "rosterId"):
            try:
                rid = int(t.get(key))
            except (TypeError, ValueError):
                continue
            if owner and rid not in out:
                out[rid] = owner
            break
    return out


def _is_player(asset: Mapping[str, Any]) -> bool:
    return str(asset.get("pos") or "").upper() != "PICK" and asset.get("assetClass") != "pick"


def _holder_index(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """``playerId -> [ownerId, ...]`` over every team-strength row (full or
    truncated roster), so a holder is found even when its row cannot be
    simulated (that is reported later, as ``full_roster_unavailable``)."""
    from src.ros import playoff_sim  # noqa: PLC0415

    index: dict[str, list[str]] = {}
    plucked = playoff_sim._rosters_from_rows([r for r in rows if isinstance(r, Mapping)])
    for owner in sorted(plucked):
        blob = plucked[owner]
        for p in list(blob.get("starters") or []) + list(blob.get("bench") or []):
            pid = str(p.get("playerId") or "")
            if pid:
                index.setdefault(pid, []).append(owner)
    return index


def moves_from_two_team(
    simulation: Mapping[str, Any],
    team_strength_rows: Iterable[Mapping[str, Any]],
    *,
    owner_by_rid: Mapping[int, str] | None = None,
) -> TradeMoves:
    """The 2-team route's trade as player moves.

    ``/api/trade/analyze`` names the analysed team but no counterparty
    (``trade_simulator``: "the request names no counterparty").  The
    counterparty is therefore the current holder of the incoming players (in
    the team-strength rows this lens simulates) and of any incoming owned pick
    (``ownedPickChecks.incomingPickHolders``); it must be exactly one team, and
    it receives every outgoing player.
    """
    team = simulation.get("team") if isinstance(simulation.get("team"), Mapping) else {}
    me = str(team.get("ownerId") or "").strip()
    if not me:
        return TradeMoves(teams=(), unavailable_reason=REASON_ASSET_UNRESOLVED)
    if simulation.get("unresolvedIn") or simulation.get("unresolvedOut"):
        return TradeMoves(teams=(me,), unavailable_reason=REASON_ASSET_UNRESOLVED)
    sending = [a for a in simulation.get("sending") or [] if isinstance(a, Mapping)]
    receiving = [a for a in simulation.get("receiving") or [] if isinstance(a, Mapping)]
    out_ids: list[str] = []
    in_ids: list[str] = []
    for asset, bucket in [*((a, out_ids) for a in sending), *((a, in_ids) for a in receiving)]:
        if not _is_player(asset):
            continue
        pid = str(asset.get("playerId") or "").strip()
        if not pid:
            return TradeMoves(teams=(me,), unavailable_reason=REASON_ASSET_UNRESOLVED)
        bucket.append(pid)

    holders = _holder_index(team_strength_rows)
    counterparties: set[str] = set()
    for pid in in_ids:
        held_by = holders.get(pid) or []
        if len(held_by) != 1 or held_by[0] == me:
            return TradeMoves(teams=(me,), unavailable_reason=REASON_ROSTER_MISMATCH)
        counterparties.add(held_by[0])
    checks = simulation.get("ownedPickChecks")
    pick_holders = checks.get("incomingPickHolders") if isinstance(checks, Mapping) else None
    for holder in pick_holders if isinstance(pick_holders, list) else []:
        if not isinstance(holder, Mapping) or holder.get("ownershipState") != "owned":
            continue
        try:
            rid = int(holder.get("holderRosterId"))
        except (TypeError, ValueError):
            continue
        owner = (owner_by_rid or {}).get(rid)
        if owner and owner != me:
            counterparties.add(owner)
    for pid in out_ids:
        if me not in (holders.get(pid) or []):
            return TradeMoves(teams=(me,), unavailable_reason=REASON_ROSTER_MISMATCH)

    if len(counterparties) > 1:
        return TradeMoves(teams=(me,), unavailable_reason=REASON_MULTIPLE_COUNTERPARTIES)
    if not counterparties:
        if out_ids:
            # Players leave and nobody identifiable receives them.
            return TradeMoves(teams=(me,), unavailable_reason=REASON_COUNTERPARTY_UNRESOLVED)
        # No rostered player moves at all: every roster is unchanged.
        return TradeMoves(teams=(me,))
    (other,) = sorted(counterparties)
    moves = tuple((pid, me, other) for pid in out_ids) + tuple((pid, other, me) for pid in in_ids)
    return TradeMoves(teams=(me, other), player_moves=moves, counterparty_inferred=True)


def trade_signature(simulation: Mapping[str, Any]) -> str:
    """Canonical identity of a 2-team trade AS THIS LENS READS IT.

    Exactly the simulation fields :func:`moves_from_two_team` consumes: the
    analysed team, each moving asset's kind and Sleeper id (a pick contributes
    only that it is a pick — picks do not play this season), whether anything
    was unresolved, and the incoming owned-pick holders (they can name the
    counterparty).  Asset order does not matter.  Two requests with the same
    signature, league and board are the same lens question; the async route's
    cache keys on it (``src/api/trade_title_odds_runtime.py``).
    """
    team = simulation.get("team") if isinstance(simulation.get("team"), Mapping) else {}

    def _identity(asset: Mapping[str, Any]) -> list[str]:
        if not _is_player(asset):
            return ["pick", ""]
        pid = str(asset.get("playerId") or "").strip()
        # A player without an id is refused by the lens; his name still keeps
        # two such trades apart.
        return ["player", pid] if pid else ["player", "name:" + str(asset.get("name") or "")]

    def _assets(key: str) -> list[list[str]]:
        return sorted(_identity(a) for a in simulation.get(key) or [] if isinstance(a, Mapping))

    checks = simulation.get("ownedPickChecks")
    holders = checks.get("incomingPickHolders") if isinstance(checks, Mapping) else None
    canonical = {
        "version": LENS_VERSION,
        "team": str(team.get("ownerId") or "").strip(),
        "sending": _assets("sending"),
        "receiving": _assets("receiving"),
        "unresolved": bool(simulation.get("unresolvedIn") or simulation.get("unresolvedOut")),
        "incomingPickHolders": sorted(
            [str(h.get("ownershipState") or ""), str(h.get("holderRosterId") or "")]
            for h in (holders if isinstance(holders, list) else [])
            if isinstance(h, Mapping)
        ),
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def moves_from_ledger(ledger: Any, snap: Any) -> TradeMoves:
    """A validated N-team ledger (``src/trade/trade_ledger.py``) as player moves.

    Every leg names its sender and receiver and the ledger already verified
    ownership against the trade's snapshot; only the ``rosterId -> ownerId``
    join is added here.
    """
    from src.trade.trade_ledger import PLAYER_PREFIX  # noqa: PLC0415

    owner_of: dict[int, str] = {}
    for rid in ledger.teams:
        team = snap.teams_by_roster_id.get(int(rid)) or {}
        owner = str(team.get("ownerId") or "").strip()
        if not owner:
            return TradeMoves(teams=(), unavailable_reason=REASON_ASSET_UNRESOLVED)
        owner_of[int(rid)] = owner
    moves: list[tuple[str, str, str]] = []
    for leg in ledger.legs:
        if not str(leg.asset_id).startswith(PLAYER_PREFIX):
            continue
        moves.append(
            (
                str(leg.asset_id)[len(PLAYER_PREFIX) :],
                owner_of[int(leg.from_roster_id)],
                owner_of[int(leg.to_roster_id)],
            )
        )
    return TradeMoves(teams=tuple(owner_of[r] for r in ledger.teams), player_moves=tuple(moves))


# ── The computation ──────────────────────────────────────────────────────


def _full_rosters(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """``ownerId -> fullRoster`` player rows, in the presim's own shape.

    Read through ``playoff_sim._rosters_from_rows`` so the bridge simulates
    exactly the rows the playoff engine's presim draws from; only owners whose
    row carries a ``fullRoster`` are returned (the truncated fallback is not a
    best-ball roster).
    """
    from src.ros import playoff_sim  # noqa: PLC0415

    rows = [r for r in rows if isinstance(r, Mapping)]
    full_owners = {str(r.get("ownerId") or "") for r in rows if r.get("fullRoster")}
    plucked = playoff_sim._rosters_from_rows(rows)
    return {
        owner: list(blob.get("starters") or []) + list(blob.get("bench") or [])
        for owner, blob in plucked.items()
        if owner in full_owners
    }


def _apply_moves(
    rosters: Mapping[str, Sequence[Mapping[str, Any]]],
    moves: TradeMoves,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]] | None:
    """``(before, after)`` for every owner whose roster changes, or ``None``
    when a moving player is not on its sender's roster."""
    changed = sorted({o for _pid, frm, to in moves.player_moves for o in (frm, to)})
    before = {o: [dict(p) for p in rosters[o]] for o in changed}
    after = {o: [dict(p) for p in rosters[o]] for o in changed}
    for pid, frm, to in moves.player_moves:
        idx = next(
            (i for i, p in enumerate(after[frm]) if str(p.get("playerId") or "") == pid),
            None,
        )
        if idx is None:
            return None
        after[to].append(after[frm].pop(idx))
    return before, after


def _odds_row(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    return {k: row.get(k) for k in ("before", "after", "delta", "deltaCi", "significant")}


def _preflight(snapshot: Any, league_key: str | None) -> dict[str, Any] | None:
    """The cheap refusals, in order, before any roster is read or simulated;
    ``None`` when the lens may run."""
    from src.ros import playoff_sim  # noqa: PLC0415
    from src.ros.team_strength import resolve_snapshot_league_key  # noqa: PLC0415

    if not league_key or not league_configured(league_key):
        return unavailable(REASON_LEAGUE_NOT_CONFIGURED)
    if not _league_best_ball(league_key):
        return unavailable(REASON_NOT_BEST_BALL)
    if snapshot is None or not getattr(snapshot, "seasons", None):
        return unavailable(REASON_NO_SNAPSHOT)
    if resolve_snapshot_league_key(snapshot) != league_key:
        return unavailable(REASON_SNAPSHOT_MISMATCH)
    if not playoff_sim.remaining_schedule(snapshot):
        return unavailable(REASON_NO_SCHEDULE)
    return None


def compute_title_odds(
    snapshot: Any,
    *,
    league_key: str | None,
    moves: TradeMoves,
    team_strength_rows: Sequence[Mapping[str, Any]] | None = None,
    n_simulations: int = N_SIMULATIONS,
    twin_weeks: int = TWIN_WEEKS,
) -> dict[str, Any]:
    """The trade-level title-odds payload for ``moves``.

    ``team_strength_rows`` defaults to
    ``team_strength.load_or_compute_team_strength(league_key)`` — the rows the
    playoff engine reads for the same league.
    """
    from src.ros import playoff_sim  # noqa: PLC0415
    from src.ros.team_strength import load_or_compute_team_strength  # noqa: PLC0415

    refused = _preflight(snapshot, league_key)
    if refused is not None:
        return refused

    rows = list(
        team_strength_rows
        if team_strength_rows is not None
        else load_or_compute_team_strength(league_key)
    )
    if not rows:
        return unavailable(playoff_sim.TEAM_STRENGTH_UNAVAILABLE)
    if moves.unavailable_reason:
        return unavailable(moves.unavailable_reason)
    rosters = _full_rosters(rows)
    if any(owner not in rosters for owner in moves.teams):
        return unavailable(REASON_FULL_ROSTER)
    applied = _apply_moves(rosters, moves)
    if applied is None:
        return unavailable(REASON_ROSTER_MISMATCH)
    before, after = applied

    from src.league_intel.sim_calibration import load_points_model  # noqa: PLC0415
    from src.league_intel.twin import strength_deltas_from_rosters  # noqa: PLC0415
    from src.ros.lineup import load_league_starter_slots  # noqa: PLC0415

    model = load_points_model()
    per_owner: dict[str, dict[str, Any]] = {}
    strength_delta: dict[str, float] = {}
    twin_assumptions: list[str] = []
    if before:
        slots = load_league_starter_slots(league_key)
        if not slots:
            return unavailable(REASON_STARTER_SLOTS)
        z_by_owner = playoff_sim.ros_z_scores(playoff_sim._ros_strength_from_rows(rows))
        deltas = strength_deltas_from_rosters(
            before,
            after,
            slots,
            ros_z_by_owner=z_by_owner,
            weeks=int(twin_weeks),
            seed=TWIN_SEED,
            points_model=model,
        )
        twin_assumptions = list(deltas.assumptions)
        per_owner = {d.owner_id: d.to_dict() for d in deltas.per_owner}
        if deltas.unavailable:
            return unavailable(
                REASON_STRENGTH_DELTA,
                strengthDeltas=[per_owner[o] for o in sorted(per_owner)],
            )
        strength_delta = deltas.strength_delta

    impact = playoff_sim.simulate_trade_impact(
        snapshot,
        strength_delta=strength_delta,
        n_simulations=int(n_simulations),
        seed=IMPACT_SEED,
        points_model=model,
    )
    refused = impact.get("unsimulable")
    if isinstance(refused, Mapping):
        return unavailable(
            str(refused.get("reason") or "playoff_simulation_refused"),
            detail=refused.get("detail"),
            methodology=impact.get("methodology"),
        )
    if not impact.get("nSimulations"):
        return unavailable(REASON_NO_DISTRIBUTIONS, methodology=impact.get("methodology"))

    playoff_rows = {r.get("ownerId"): r for r in impact.get("playoff") or []}
    champ_rows = {r.get("ownerId"): r for r in impact.get("championship") or []}
    champ_unavailable = impact.get("championshipUnavailable")
    teams: list[dict[str, Any]] = []
    for owner in moves.teams:
        prow = playoff_rows.get(owner)
        entry: dict[str, Any] = {
            "ownerId": owner,
            "displayName": (prow or {}).get("displayName") or owner,
            "rosterChanged": owner in per_owner,
            # The bridge's own record for a changed roster; an unchanged roster
            # moves nothing, measured (not defaulted).
            "strengthDelta": per_owner.get(owner)
            or {"ownerId": owner, "meanDelta": 0.0, "rosterUnchanged": True},
        }
        if prow is None:
            entry["available"] = False
            entry["unavailableReason"] = REASON_TEAM_NOT_SIMULATED
        else:
            entry["available"] = True
            entry["playoff"] = _odds_row(prow)
            if champ_unavailable:
                entry["championship"] = None
                entry["championshipUnavailable"] = champ_unavailable
            else:
                entry["championship"] = _odds_row(champ_rows.get(owner))
        teams.append(entry)

    assumptions = [*twin_assumptions, *_LENS_ASSUMPTIONS]
    if moves.counterparty_inferred:
        assumptions.append(COUNTERPARTY_INFERRED_NOTE)
    return {
        "version": LENS_VERSION,
        "state": STATE_OK,
        "teams": teams,
        "counterpartyInferred": moves.counterparty_inferred,
        "nSimulations": impact.get("nSimulations"),
        "sharedSeed": impact.get("sharedSeed"),
        "twinWeeks": int(twin_weeks) if before else 0,
        "twinSeed": TWIN_SEED,
        "pointsModelSource": impact.get("pointsModelSource"),
        "rosEvidenceMethod": playoff_sim.ros_evidence_method(),
        "methodology": impact.get("methodology"),
        "assumptions": assumptions,
        "disclosure": disclosure(),
        "role": "context_not_vote",
    }


def guarded(fn, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run a computation; any exception is the lens being unavailable, never a
    broken analysis (the lens is evidence only)."""
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001 — context only; the verdict never depends on it
        LOG.warning("title-odds lens unavailable", exc_info=True)
        return unavailable(REASON_ERROR)


def title_odds_for_two_team(
    simulation: Mapping[str, Any],
    *,
    snapshot: Any,
    league_key: str | None,
    contract: Mapping[str, Any] | None,
    team_strength_rows: Sequence[Mapping[str, Any]] | None = None,
    n_simulations: int = N_SIMULATIONS,
    twin_weeks: int = TWIN_WEEKS,
) -> dict[str, Any]:
    """``/api/trade/analyze``: the lens payload for one 2-team simulation."""
    refused = _preflight(snapshot, league_key)
    if refused is not None:
        return refused
    rows = team_strength_rows
    if rows is None:
        from src.ros.team_strength import load_or_compute_team_strength  # noqa: PLC0415

        rows = load_or_compute_team_strength(league_key)
    moves = moves_from_two_team(simulation, rows or [], owner_by_rid=owner_by_roster_id(contract))
    return compute_title_odds(
        snapshot,
        league_key=league_key,
        moves=moves,
        team_strength_rows=rows,
        n_simulations=n_simulations,
        twin_weeks=twin_weeks,
    )


def title_odds_for_ledger(
    ledger: Any,
    snap: Any,
    *,
    snapshot: Any,
    team_strength_rows: Sequence[Mapping[str, Any]] | None = None,
    n_simulations: int = N_SIMULATIONS,
    twin_weeks: int = TWIN_WEEKS,
) -> dict[str, Any]:
    """The lens payload for one validated N-team ledger.

    Not called by any route today: ``/api/trade/analyze-multi`` hands
    :func:`deferred_for_ledger` instead of waiting for this.  Kept (and
    pinned by ``tests/trade/test_title_odds_lens.py``) as the N-team
    computation an async multi-team path would serve."""
    league_key = getattr(snap, "league_key", None)
    refused = _preflight(snapshot, league_key)
    if refused is not None:
        return refused
    return compute_title_odds(
        snapshot,
        league_key=league_key,
        moves=moves_from_ledger(ledger, snap),
        team_strength_rows=team_strength_rows,
        n_simulations=n_simulations,
        twin_weeks=twin_weeks,
    )


def lens_detail(payload: Mapping[str, Any], perspective_owner_id: str | None) -> dict[str, Any]:
    """``(available, reason, detail)`` material for one team's packet.

    Returns ``{"available": bool, "unavailableReason"?: str, "detail": {...}}``.
    """
    if not isinstance(payload, Mapping):
        return {"available": False, "unavailableReason": "not_computed", "detail": {}}
    if payload.get("state") != STATE_OK:
        reason = str(payload.get("reason") or "not_computed")
        detail: dict[str, Any] = {"note": payload.get("detail") or _DETAIL.get(reason)}
        if payload.get("disclosure"):
            detail["disclosure"] = payload.get("disclosure")
        return {"available": False, "unavailableReason": reason, "detail": detail}
    rows = [r for r in payload.get("teams") or [] if isinstance(r, Mapping)]
    mine = next((r for r in rows if r.get("ownerId") == perspective_owner_id), None)
    if mine is None or not mine.get("available"):
        return {
            "available": False,
            "unavailableReason": REASON_TEAM_NOT_SIMULATED,
            "detail": {"note": _DETAIL[REASON_TEAM_NOT_SIMULATED]},
        }
    return {
        "available": True,
        "detail": {
            "perspectiveOwnerId": perspective_owner_id,
            "playoff": mine.get("playoff"),
            "championship": mine.get("championship"),
            **(
                {"championshipUnavailable": mine["championshipUnavailable"]}
                if mine.get("championshipUnavailable")
                else {}
            ),
            "strengthDelta": mine.get("strengthDelta"),
            "teams": [dict(r) for r in rows],
            "counterpartyInferred": payload.get("counterpartyInferred"),
            "nSimulations": payload.get("nSimulations"),
            "sharedSeed": payload.get("sharedSeed"),
            "twinWeeks": payload.get("twinWeeks"),
            "pointsModelSource": payload.get("pointsModelSource"),
            "rosEvidenceMethod": payload.get("rosEvidenceMethod"),
            "methodology": payload.get("methodology"),
            "assumptions": list(payload.get("assumptions") or []),
            "disclosure": payload.get("disclosure"),
            "version": payload.get("version"),
            "role": "context_not_vote",
            "note": "This season's playoff and title odds before and after the trade. "
            "Context only: never a vote, and it does not change the recommendation.",
        },
    }
