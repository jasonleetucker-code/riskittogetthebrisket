"""Unified Manager of the Year — ONE award for competing AND managing.

Owner decision 2026-09-28 (``docs/OWNER_REQUESTED_TODO.md``,
"ONE unified Manager of the Year"), which supersedes the separate
Manager / GM-of-the-Year proposal, the Manager playoff-field and
above-.500 requirement, and the 65/15/20 competition-only proposal.
Methodology record (frozen before any winner was computed):
``docs/awards/MANAGER_OF_THE_YEAR_METHODOLOGY.md``.

    MOTY = 0.40*A + 0.25*T + 0.15*W + 0.10*D + 0.10*P        (each 0-100)

    A  regular-season all-play share          (canonical all-play owner:
                                               ``luck._all_play_week``)
    T  net trade value added                  (production + future value)
    W  net waiver / free-agent value added    (production)
    D  draft value added vs slot expectation  (production)
    P  championship-playoff achievement       (actual bracket)

Before P is final the live score is ``(0.40A+0.25T+0.15W+0.10D)/0.90``,
labelled provisional.  There is NO playoff, record, standings or
rebuild-status gate: every manager is ranked.

The accounting unit for T / W / D production is **replacement-level
surplus** (RLS): for a player-week with an observed score,
``max(0, points - replacement_per_game[position])``, where the replacement
level is the one the canonical VORP board already measured for that
season (``awards._vorp_board_with_levels``).  It is lineup-independent on
purpose (no start/sit credit in best ball; no reliance on any manager's
lineup choices) and symmetric (a neutral swap nets zero in expectation).

The ledger attributes every surplus increment EXACTLY ONCE.  For roster
``r`` and finished regular-season week ``w``:

* ``R`` = the players Sleeper lists on ``r`` for ``w`` (host truth);
* ``M`` = the "no-market world": the franchise's holdings at the start of
  the window (previous season's final roster for the same roster id;
  empty for an inaugural or expansion roster), adjusted by commissioner
  moves, plus every player ``r`` drafted in the window;
* ``p in R - M``  -> credit ``u(p,w)`` to the channel that brought ``p``
  (the latest trade / waiver / FA acquisition of ``p`` by ``r``);
* ``p in M - R``  -> charge ``u(p,w)`` to the channel that took ``p`` away
  (the latest trade or drop of ``p`` by ``r``), with ``u`` observed
  wherever ``p`` is rostered that week;
* D credits each selection holder-independently, ``u(p,w) - e(k)``, where
  ``e`` is the frozen per-week slot expectation; a traded current-draft
  pick moves ``e(k)`` for the window between the trade's two sides (T).

Summed over channels this telescopes to ``u(R) - u(B0) - E(own picks)``:
no increment is counted twice, a round trip nets out by construction,
and churn cannot manufacture value.  A week whose score is unobservable
(the player is unrostered everywhere) is UNKNOWN — excluded and counted,
never zero.

Normalization (predeclared, bounded, monotonic, zero -> 50, no min-max):
``50 + 50*tanh((raw / weeks) / (KAPPA * sigma_week))``, ``sigma_week`` =
SD of the season's official regular-season team-week scores.

Everything that is not measurable for a season is reported as such
(``coverage``); nothing missing is silently 0 or 50.

**T is scored only when BOTH of its halves are measurable (v1.1,
OD-MOTY-7).**  A trade exchanges this season's production for future value
(picks, young players); production-only T scores one side of that exchange
and so penalizes every rebuilding trade.  While the future-value channel
is incomplete for the season, T is UNAVAILABLE: its production half is
published as raw context (``productionScore``) and excluded from every
total.  The row then carries no Manager of the Year score -- only an
``incomplete`` block (the frozen weights applied to the measured
components, out of the points those components can earn; nothing is
reweighted) and a validation rank on it.  This is a VALIDATION TRACK:
``official`` stays False and ``promotion`` is ``not_promoted``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from . import metrics, trade_grading
from .luck import _all_play_week, _season_weekly_scores
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot

# ── Frozen methodology parameters (v1) ───────────────────────────────────
# Every constant below is recorded, with its provenance, in
# docs/awards/MANAGER_OF_THE_YEAR_METHODOLOGY.md §6.  Changing one is a
# methodology change: bump METHOD_VERSION.

METHOD_VERSION = "moty-unified-v1.1-2026-09-29"

#: Owner-proposed award-policy weights (NOT statistically validated).
WEIGHTS: dict[str, float] = {"A": 0.40, "T": 0.25, "W": 0.15, "D": 0.10, "P": 0.10}
#: Weight carried by everything except P — the provisional denominator.
NON_POSTSEASON_WEIGHT = 0.90

#: tanh scale for T/W/D production, in units of the season's weekly
#: team-score standard deviation.  Net value of +KAPPA*sigma per week maps
#: to 50 + 50*tanh(1) = 88.1.
KAPPA = 0.5

#: Future-value (trade) scale: the canonical trade-grade "Clear win" band
#: edge (``trade_grading._GRADE_PCT_CLEAR``), so a value-weighted 25% edge
#: across a manager's trades maps to 88.1.  Reused, not invented.
FV_PCT_SCALE = trade_grading._GRADE_PCT_CLEAR

#: Weight of the production channel inside T when BOTH channels are
#: measurable for the whole season (the 50/50 candidate the directive names).
PRODUCTION_SHARE = 0.5

#: First season whose unified result may be published as the OFFICIAL
#: award.  ``None`` = candidate only everywhere: a completed season keeps
#: its existing (legacy) official winner until the owner promotes the
#: methodology.  Promotion is a deliberate edit here, never automatic.
OFFICIAL_FROM_SEASON: int | None = None

#: Picks per expectation band (one round of a 10-team draft).
DRAFT_BAND_SIZE = 10

#: Frozen per-week replacement-level-surplus expectation per draft band
#: (band 1 = overall picks 1-10, ...; a band past the table's end uses its
#: last entry).  Calibrated ONCE, on 2026-09-28, before any Manager of the
#: Year result was computed, from the league's two completed ANNUAL drafts
#: (2024 supplemental/rookie draft: 100 selections; 2025 rookie draft: 70),
#: holder-independent observed weeks, weighted isotonic (non-increasing)
#: regression.  Raw per-band rates: methodology record §5.4.  In-sample for
#: 2024/2025, out-of-sample for 2026+.
ANNUAL_BAND_EXPECTATION: tuple[float, ...] = (
    5.79, 3.003, 1.802, 1.802, 1.802, 1.802, 1.802, 1.802, 1.802, 1.189,
)  # fmt: skip
#: Same, for the STARTUP draft (one per league chain), calibrated on the
#: league's only startup draft (2024, 240 selections, 24 bands) — in-sample
#: by necessity: no comparable startup history exists.
STARTUP_BAND_EXPECTATION: tuple[float, ...] = (
    12.578, 9.122, 7.681, 7.351, 7.351, 7.351, 6.408, 6.408, 5.656, 5.034, 5.034, 4.899,
    3.845, 3.845, 3.845, 3.845, 3.845, 3.845, 3.845, 3.845, 3.845, 2.424, 2.424, 2.424,
)  # fmt: skip

# Channel tokens.
_T, _W, _D, _C = "T", "W", "D", "C"
_TX_CHANNEL = {"trade": _T, "waiver": _W, "free_agent": _W, "commissioner": _C}

#: Coverage states.
COMPLETE = "complete"
PARTIAL = "partial"
UNAVAILABLE = "unavailable"
NOT_IMPLEMENTED = "not_implemented"
PENDING = "pending"
FINAL = "final"
PROVISIONAL = "provisional"

#: Score bases.  ``full`` -- every component scored, the MOTY score exists.
#: ``incomplete`` -- T is unavailable season-wide: no MOTY score, only the
#: measured points (frozen weights x measured components) and a validation
#: rank.  ``none`` -- nothing rankable.
BASIS_FULL = "full"
BASIS_INCOMPLETE = "incomplete"
BASIS_NONE = "none"

#: Promotion state of this methodology (never automatic; OD-MOTY-1).
NOT_PROMOTED = "not_promoted"
PROMOTED = "promoted"

ValuationFactory = Callable[[Iterable[tuple[dict[str, Any], Any]]], Callable[..., Any]]


# ── Small helpers ────────────────────────────────────────────────────────
def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def normalize_management(raw: float, weeks: int, sigma_week: float) -> float | None:
    """The frozen T/W/D production normalization.  ``None`` when unscalable."""
    if weeks <= 0 or not sigma_week or sigma_week <= 0:
        return None
    return 50.0 + 50.0 * math.tanh((raw / weeks) / (KAPPA * sigma_week))


def normalize_future_value_pct(pct: float) -> float:
    """The frozen trade future-value normalization (value-weighted % edge)."""
    return 50.0 + 50.0 * math.tanh(pct / FV_PCT_SCALE)


def draft_expectation(band: int, kind: str) -> float | None:
    """Frozen per-week surplus expectation for a 1-based band, or ``None``."""
    table = STARTUP_BAND_EXPECTATION if kind == "startup" else ANNUAL_BAND_EXPECTATION
    if not table or band < 1:
        return None
    return table[min(band, len(table)) - 1]


# ── Season inputs ────────────────────────────────────────────────────────
@dataclass
class _SeasonFacts:
    weeks: list[int]
    points: dict[int, dict[str, float]]  # week -> pid -> official player points
    holdings: dict[int, dict[int, set[str]]]  # week -> rid -> players
    sigma_week: float | None
    team_weeks: int


def _season_facts(season: SeasonSnapshot) -> _SeasonFacts:
    weeks = list(metrics.final_regular_season_weeks(season))
    points: dict[int, dict[str, float]] = {}
    holdings: dict[int, dict[int, set[str]]] = {}
    team_scores: list[float] = []
    for wk in weeks:
        wk_points: dict[str, float] = {}
        wk_hold: dict[int, set[str]] = {}
        for entry in season.matchups_by_week.get(wk) or []:
            rid = metrics.roster_id_of(entry)
            if rid is None:
                continue
            if entry.get("points") is not None:
                team_scores.append(metrics.matchup_points(entry))
            wk_hold.setdefault(rid, set()).update(str(p) for p in (entry.get("players") or []) if p)
            pp = entry.get("players_points")
            if isinstance(pp, dict):
                for pid, raw in pp.items():
                    val = _float(raw)
                    if val is not None:
                        wk_points.setdefault(str(pid), val)
        points[wk] = wk_points
        holdings[wk] = wk_hold
    sigma = None
    if len(team_scores) >= 2:
        mean = sum(team_scores) / len(team_scores)
        sigma = math.sqrt(sum((x - mean) ** 2 for x in team_scores) / len(team_scores))
    return _SeasonFacts(weeks, points, holdings, sigma, len(team_scores))


class _Surplus:
    """``u(p, w)`` — replacement-level surplus, or ``None`` when unknown."""

    def __init__(
        self,
        snapshot: PublicLeagueSnapshot,
        facts: _SeasonFacts,
        levels: dict[str, float | None],
    ) -> None:
        self._snapshot = snapshot
        self._facts = facts
        self._levels = levels
        self._pos: dict[str, str] = {}

    def position(self, pid: str) -> str:
        pos = self._pos.get(pid)
        if pos is None:
            pos = self._snapshot.player_position(pid) or ""
            self._pos[pid] = pos
        return pos

    def __call__(self, pid: str, week: int) -> float | None:
        pts = self._facts.points.get(week, {}).get(pid)
        if pts is None:
            return None
        level = self._levels.get(self.position(pid))
        if level is None:
            return None
        return max(0.0, pts - level)


# ── The window ledger ────────────────────────────────────────────────────
@dataclass
class _Event:
    time: int  # chronological sequence number within the window
    leg: int
    channel: str
    adds: dict[str, int]
    drops: dict[str, int]
    tx: dict[str, Any] = field(default_factory=dict)


def _window_transactions(season: SeasonSnapshot) -> list[dict[str, Any]]:
    """Completed trades / waivers / FA / commissioner moves in the window.

    The franchise-management year of season Y runs from the end of Y-1's
    championship to the end of Y's regular season.  Sleeper files every
    offseason move of that year in league Y (leg 1), so the window is
    league Y's completed moves with ``leg < playoff_week_start`` —
    postseason moves belong to no management year.
    """
    out = []
    start = season.playoff_week_start
    for week, txs in season.transactions_by_week.items():
        for tx in txs or []:
            if str(tx.get("status") or "").lower() != "complete":
                continue
            if str(tx.get("type") or "").lower() not in _TX_CHANNEL:
                continue
            leg = _int(tx.get("leg"))
            if leg is None:
                leg = _int(week)
            if leg is None or leg >= start:
                # No placeable week -> not in any window (never "week 0").
                continue
            out.append({**tx, "_leg": leg})
    out.sort(key=_tx_order)
    return out


def _tx_order(tx: dict[str, Any]) -> tuple[int, bool, int, str]:
    """Chronological order: leg, then timestamp (untimed moves first within
    their leg -- a sort position, never a value), then id."""
    created = _int(tx.get("created"))
    return (
        tx["_leg"],
        created is not None,
        created if created is not None else 0,
        str(tx.get("transaction_id") or ""),
    )


def _as_rid_map(raw: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if isinstance(raw, dict):
        for pid, rid in raw.items():
            r = _int(rid)
            if r is not None and pid:
                out[str(pid)] = r
    return out


@dataclass
class _Selection:
    rid: int
    pid: str
    pick_no: int
    band: int
    kind: str  # "annual" | "startup"
    amount: int | None
    draft_id: str


def _startup_draft_id(season: SeasonSnapshot) -> str | None:
    """The league's STARTUP draft: the earliest completed draft with
    selections in the chain's inaugural season (no previous league).

    Structural, not inferred from who was picked: this league's 2024
    second draft and its 2025 draft both mixed rookies with veterans, so a
    rookie-share rule misclassifies them.  Every other draft is an ANNUAL
    (rookie / supplemental) draft.
    """
    prev_id = str(season.league.get("previous_league_id") or "")
    if prev_id and prev_id != "0":
        return None
    candidates = [
        d
        for d in season.drafts or []
        if str(d.get("status") or "").lower() == "complete"
        and any(
            p.get("player_id")
            for p in season.draft_picks_by_draft.get(str(d.get("draft_id") or "")) or []
        )
    ]
    if not candidates:
        return None

    def _start(d: dict[str, Any]) -> tuple[bool, int]:
        st = _int(d.get("start_time"))
        return (st is None, st if st is not None else 0)

    first = min(candidates, key=_start)
    return str(first.get("draft_id") or "")


def _auction_order(p: dict[str, Any]) -> tuple[bool, int, bool, int]:
    """Price rank: most expensive first; an unknown price or pick number
    sorts LAST (a sort position, never a price)."""
    amount = _int((p.get("metadata") or {}).get("amount"))
    pick = _int(p.get("pick_no"))
    return (
        amount is None,
        -amount if amount is not None else 0,
        pick is None,
        pick if pick is not None else 0,
    )


def _window_selections(
    snapshot: PublicLeagueSnapshot, season: SeasonSnapshot
) -> tuple[list[_Selection], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Every completed in-season-year draft selection, with its band.

    Snake / linear drafts band by ``pick_no``.  An auction has no slots:
    a selection's band comes from its price rank (the k-th most expensive
    purchase is treated as overall pick k), and the price is kept.
    Returns ``(selections, per-draft diagnostics, draft meta by id)``.
    """
    selections: list[_Selection] = []
    diag: list[dict[str, Any]] = []
    meta: dict[str, dict[str, Any]] = {}
    startup_id = _startup_draft_id(season)
    for draft in season.drafts or []:
        did = str(draft.get("draft_id") or "")
        if str(draft.get("status") or "").lower() != "complete":
            continue
        picks = [p for p in (season.draft_picks_by_draft.get(did) or []) if p.get("player_id")]
        if not picks:
            diag.append({"draftId": did, "type": draft.get("type"), "selections": 0})
            continue
        kind = "startup" if did == startup_id else "annual"
        is_auction = str(draft.get("type") or "").lower() == "auction"
        if is_auction:
            ranked = sorted(
                picks,
                key=_auction_order,
            )
            rank_of = {id(p): i + 1 for i, p in enumerate(ranked)}
        for p in picks:
            rid = _int(p.get("roster_id"))
            if rid is None:
                continue
            k = rank_of.get(id(p)) if is_auction else _int(p.get("pick_no"))
            if k is None or k <= 0:
                continue
            selections.append(
                _Selection(
                    rid=rid,
                    pid=str(p.get("player_id")),
                    pick_no=k,
                    band=(k - 1) // DRAFT_BAND_SIZE + 1,
                    kind=kind,
                    amount=_int((p.get("metadata") or {}).get("amount")) if is_auction else None,
                    draft_id=did,
                )
            )
        meta[did] = {
            "type": str(draft.get("type") or "").lower(),
            "kind": kind,
            "selections": len(picks),
            "startTime": _int(draft.get("start_time")),
            "teams": _int((draft.get("settings") or {}).get("teams")) or season.num_teams,
            "draftOrder": draft.get("draft_order") or {},
        }
        diag.append(
            {"draftId": did, "type": draft.get("type"), "kind": kind, "selections": len(picks)}
        )
    return selections, diag, meta


def _previous_season(
    snapshot: PublicLeagueSnapshot, season: SeasonSnapshot
) -> SeasonSnapshot | None:
    prev_id = str(season.league.get("previous_league_id") or "")
    if not prev_id or prev_id == "0":
        return None
    return snapshot.season_by_league_id(prev_id)


def _window_baseline(
    snapshot: PublicLeagueSnapshot, season: SeasonSnapshot
) -> tuple[dict[int, set[str]], str]:
    """Each roster's holdings at the start of the window, and the basis.

    ``inaugural`` — the league's first season: every roster starts empty
    (the startup draft is the construction).  ``previous_final_roster`` —
    the same roster id's final roster in the previous league (Sleeper
    carries roster ids through a renewal); a roster id the previous league
    did not have (expansion) starts empty.  ``unavailable`` — a previous
    league exists but is not in the snapshot: the window cannot be
    reconciled and management channels are not computed.
    """
    prev_id = str(season.league.get("previous_league_id") or "")
    if not prev_id or prev_id == "0":
        return {}, "inaugural"
    prev = snapshot.season_by_league_id(prev_id)
    if prev is None:
        return {}, "unavailable"
    out: dict[int, set[str]] = {}
    for roster in prev.rosters or []:
        rid = _int(roster.get("roster_id"))
        if rid is None:
            continue
        out[rid] = {str(p) for p in (roster.get("players") or []) if p}
    return out, "previous_final_roster"


class _Ledger:
    """Acquisition / exit history per ``(roster, player)`` for one window."""

    def __init__(self, events: list[_Event]) -> None:
        self.acq: dict[tuple[int, str], list[tuple[int, int, str]]] = defaultdict(list)
        self.exit: dict[tuple[int, str], list[tuple[int, int, str]]] = defaultdict(list)
        self.commissioner: list[_Event] = []
        for ev in events:
            if ev.channel == _C:
                self.commissioner.append(ev)
            for pid, rid in ev.adds.items():
                self.acq[(rid, pid)].append((ev.time, ev.leg, ev.channel))
            for pid, rid in ev.drops.items():
                self.exit[(rid, pid)].append((ev.time, ev.leg, ev.channel))

    @staticmethod
    def _latest(rows: list[tuple[int, int, str]], week: int) -> str | None:
        best: tuple[int, int, str] | None = None
        for row in rows:
            if row[1] > week:
                continue
            if best is None or row[0] >= best[0]:
                best = row
        return best[2] if best else None

    def acquisition_channel(self, rid: int, pid: str, week: int) -> str | None:
        return self._latest(self.acq.get((rid, pid), []), week)

    def exit_channel(self, rid: int, pid: str, week: int) -> str | None:
        return self._latest(self.exit.get((rid, pid), []), week)

    def baseline_at(self, base: dict[int, set[str]], week: int) -> dict[int, set[str]]:
        """``base`` with every commissioner move up to ``week`` applied."""
        out = {rid: set(players) for rid, players in base.items()}
        for ev in self.commissioner:
            if ev.leg > week:
                continue
            for pid, rid in ev.drops.items():
                out.setdefault(rid, set()).discard(pid)
            for pid, rid in ev.adds.items():
                out.setdefault(rid, set()).add(pid)
        return out


# ── Components ───────────────────────────────────────────────────────────
def all_play_component(
    snapshot: PublicLeagueSnapshot, season: SeasonSnapshot
) -> tuple[dict[str, dict[str, Any]], int]:
    """A: ``100 * mean(weekly all-play share)`` over finished regular weeks.

    Reuses the canonical all-play owner (``luck``): official scored totals,
    the full league pool, one observation per finished week, genuine zero
    and negative scores kept, an absent score missing (never zero).  The
    league-median game is a record rule and is NOT added again.
    """
    week_scores = _season_weekly_scores(season, snapshot.managers)
    weeks = sorted(week_scores)
    per_owner: dict[str, list[float]] = defaultdict(list)
    for wk in weeks:
        for oid, ap in _all_play_week(week_scores[wk]).items():
            per_owner[oid].append(float(ap["expectedShare"]))
    out: dict[str, dict[str, Any]] = {}
    for oid, shares in per_owner.items():
        out[oid] = {
            "score": 100.0 * sum(shares) / len(shares) if shares else None,
            "weeksObserved": len(shares),
            "weeksInWindow": len(weeks),
        }
    return out, len(weeks)


def _bracket_finish(season: SeasonSnapshot) -> dict[str, Any]:
    """Championship-path finish per roster from the ACTUAL winners bracket.

    Placement games (``p`` = 3, 5, ...) are ignored: no consolation or
    third-place tie-break.  Teams eliminated in the same round share the
    average of the finish ranks that round occupies; a bye is not a win.
    Resolved only when the final (``p == 1``) has a winner.
    """
    path = [
        m
        for m in season.winners_bracket or []
        if isinstance(m, dict) and (m.get("p") is None or _int(m.get("p")) == 1)
    ]
    entrants = set(metrics.playoff_teams(season.winners_bracket))
    final = next((m for m in path if _int(m.get("p")) == 1), None)
    champion = _int(final.get("w")) if final else None
    if not entrants or champion is None:
        return {"resolved": False, "entrants": sorted(entrants), "finish": {}}
    elim_round: dict[int, int] = {}
    for m in path:
        loser = _int(m.get("l"))
        if loser is None:
            continue
        rnd = _int(m.get("r"))
        if rnd is None:  # an elimination we cannot place in a round
            return {"resolved": False, "entrants": sorted(entrants), "finish": {}}
        elim_round[loser] = max(rnd, elim_round.get(loser, rnd))
    finish: dict[int, float] = {champion: 1.0}
    groups: dict[int, list[int]] = defaultdict(list)
    for rid in entrants:
        if rid == champion:
            continue
        rnd = elim_round.get(rid)
        if rnd is None:
            return {"resolved": False, "entrants": sorted(entrants), "finish": {}}
        groups[rnd].append(rid)
    next_rank = 2
    for rnd in sorted(groups, reverse=True):
        members = groups[rnd]
        avg = next_rank + (len(members) - 1) / 2.0
        for rid in members:
            finish[rid] = avg
        next_rank += len(members)
    return {"resolved": True, "entrants": sorted(entrants), "finish": finish}


def postseason_component(
    snapshot: PublicLeagueSnapshot, season: SeasonSnapshot
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """P: ``100 * (K + 1 - avg_finish) / K`` for entrants, 0 for non-entrants.

    Pending (``score: None``) until the final has a winner — never 0.
    """
    bracket = _bracket_finish(season)
    k = len(bracket["entrants"])
    out: dict[str, dict[str, Any]] = {}
    for roster in season.rosters or []:
        rid = _int(roster.get("roster_id"))
        oid = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
        if not oid:
            continue
        if not bracket["resolved"]:
            out[oid] = {"score": None, "status": PENDING, "finishRank": None}
        elif rid in bracket["finish"]:
            rank = bracket["finish"][rid]
            out[oid] = {
                "score": 100.0 * (k + 1 - rank) / k,
                "status": FINAL,
                "finishRank": rank,
                "madePlayoffs": True,
            }
        else:
            out[oid] = {"score": 0.0, "status": FINAL, "finishRank": None, "madePlayoffs": False}
    meta = {"status": FINAL if bracket["resolved"] else PENDING, "entrants": k}
    return out, meta


@dataclass
class _ChannelTally:
    credit: float = 0.0
    charge: float = 0.0
    pick_expectation: float = 0.0
    unknown_credit_weeks: int = 0
    unknown_charge_weeks: int = 0

    @property
    def net(self) -> float:
        return self.credit - self.charge + self.pick_expectation


def management_ledger(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    levels: dict[str, float | None],
    facts: _SeasonFacts | None = None,
) -> dict[str, Any]:
    """T / W / D production for every roster in one window (see module doc)."""
    facts = facts or _season_facts(season)
    u = _Surplus(snapshot, facts, levels)
    base0, basis = _window_baseline(snapshot, season)
    txs = _window_transactions(season)
    events = [
        _Event(
            # Position in the window's chronological order (_tx_order).
            time=seq,
            leg=tx["_leg"],
            channel=_TX_CHANNEL[str(tx.get("type")).lower()],
            adds=_as_rid_map(tx.get("adds")),
            drops=_as_rid_map(tx.get("drops")),
            tx=tx,
        )
        for seq, tx in enumerate(txs)
    ]
    ledger = _Ledger(events)
    selections, draft_diag, draft_meta = _window_selections(snapshot, season)
    drafted: dict[int, set[str]] = defaultdict(set)
    for sel in selections:
        drafted[sel.rid].add(sel.pid)

    rosters = sorted(
        {r for r in (_int(x.get("roster_id")) for x in season.rosters or []) if r is not None}
    )
    tally: dict[int, dict[str, _ChannelTally]] = {
        rid: {_T: _ChannelTally(), _W: _ChannelTally(), _D: _ChannelTally()} for rid in rosters
    }
    recon = {"unexplainedHeld": 0, "unexplainedMissing": 0, "missingRosterWeeks": 0}
    if basis == "unavailable":
        return {
            "basis": basis,
            "tally": tally,
            "reconciliation": recon,
            "drafts": draft_diag,
            "selections": [],
            "counts": {},
            "facts": facts,
        }

    for wk in facts.weeks:
        baseline = ledger.baseline_at(base0, wk)
        for rid in rosters:
            held = facts.holdings.get(wk, {}).get(rid)
            if held is None:
                recon["missingRosterWeeks"] += 1
                continue
            world = baseline.get(rid, set()) | drafted.get(rid, set())
            for pid in held - world:
                ch = ledger.acquisition_channel(rid, pid, wk)
                if ch not in (_T, _W):
                    recon["unexplainedHeld"] += 1
                    continue
                val = u(pid, wk)
                t = tally[rid][ch]
                if val is None:
                    t.unknown_credit_weeks += 1
                else:
                    t.credit += val
            for pid in world - held:
                ch = ledger.exit_channel(rid, pid, wk)
                if ch not in (_T, _W):
                    recon["unexplainedMissing"] += 1
                    continue
                val = u(pid, wk)
                t = tally[rid][ch]
                if val is None:
                    t.unknown_charge_weeks += 1
                else:
                    t.charge += val

    # D: each selection, holder-independent, against its frozen expectation.
    sel_rows = []
    for sel in selections:
        exp = draft_expectation(sel.band, sel.kind)
        observed = 0
        surplus = 0.0
        for wk in facts.weeks:
            val = u(sel.pid, wk)
            if val is None:
                continue
            observed += 1
            surplus += val
        d = tally.get(sel.rid, {}).get(_D)
        if d is None:
            continue
        if exp is None:
            d.unknown_credit_weeks += len(facts.weeks)
            continue
        d.credit += surplus
        d.charge += exp * observed
        d.unknown_credit_weeks += len(facts.weeks) - observed
        sel_rows.append(
            {
                "rosterId": sel.rid,
                "playerId": sel.pid,
                "pick": sel.pick_no,
                "band": sel.band,
                "kind": sel.kind,
                "surplus": surplus,
                "expected": exp * observed,
                "observedWeeks": observed,
            }
        )

    # T: a traded pick of THIS season's annual draft carries e(k) x weeks.
    # Sleeper cannot trade a pick after it is used, so every such pick was
    # live when it moved -- including picks traded during a slow draft.
    n_weeks = len(facts.weeks)
    moved_current = 0
    moved_future = 0
    unpriced_current = 0
    annual = [m for m in draft_meta.values() if m.get("kind") == "annual" and m.get("selections")]
    draft = max(annual, key=lambda m: m["selections"]) if annual else None
    owner_user = {
        _int(r.get("roster_id")): str(r.get("owner_id") or "") for r in season.rosters or []
    }
    for ev in events:
        if ev.channel != _T:
            continue
        for pk in ev.tx.get("draft_picks") or []:
            if str(pk.get("season") or "") != str(season.season):
                moved_future += 1
                continue
            receiver, sender = _int(pk.get("owner_id")), _int(pk.get("previous_owner_id"))
            origin, rnd = _int(pk.get("roster_id")), _int(pk.get("round"))
            if draft is None or rnd is None or origin is None:
                unpriced_current += 1
                continue
            teams = draft["teams"] if draft["teams"] else season.num_teams
            if not teams:
                unpriced_current += 1
                continue
            slot = _int((draft.get("draftOrder") or {}).get(owner_user.get(origin, "")))
            if slot is None:
                slot = (teams + 1) // 2
            if draft.get("type") == "snake" and rnd % 2 == 0:
                slot = teams + 1 - slot
            k = (rnd - 1) * teams + slot
            exp = draft_expectation((k - 1) // DRAFT_BAND_SIZE + 1, "annual")
            if exp is None:
                unpriced_current += 1
                continue
            moved_current += 1
            value = exp * n_weeks
            if receiver in tally:
                tally[receiver][_T].pick_expectation += value
            if sender in tally:
                tally[sender][_T].pick_expectation -= value

    return {
        "basis": basis,
        "tally": tally,
        "reconciliation": recon,
        "drafts": draft_diag,
        "selections": sel_rows,
        "counts": {
            "trades": sum(1 for ev in events if ev.channel == _T),
            "waiverMoves": sum(1 for ev in events if ev.channel == _W),
            "commissionerMoves": sum(1 for ev in events if ev.channel == _C),
            "currentDraftPicksTraded": moved_current,
            "currentDraftPicksUnpriced": unpriced_current,
            "futurePicksTraded": moved_future,
        },
        "events": events,
        "facts": facts,
    }


def _faab_by_roster(season: SeasonSnapshot) -> tuple[dict[int, float], dict[int, float]]:
    """FAAB spent on completed in-window waiver claims, and FAAB net traded."""
    spent: dict[int, float] = defaultdict(float)
    traded: dict[int, float] = defaultdict(float)
    for tx in _window_transactions(season):
        ttype = str(tx.get("type") or "").lower()
        if ttype == "waiver":
            bid = _float((tx.get("settings") or {}).get("waiver_bid"))
            for rid in {r for r in _as_rid_map(tx.get("adds")).values()}:
                if bid is not None:
                    spent[rid] += bid
        elif ttype == "trade":
            for move in tx.get("waiver_budget") or []:
                amount = _float(move.get("amount"))
                if amount is None:  # unknown amount: reported nowhere, never 0
                    continue
                rec, snd = _int(move.get("receiver")), _int(move.get("sender"))
                if rec is not None:
                    traded[rec] += amount
                if snd is not None:
                    traded[snd] -= amount
    return spent, traded


def _moves_faab(tx: dict[str, Any]) -> bool:
    """Does this trade move FAAB (any nonzero or unknown amount)?"""
    for move in tx.get("waiver_budget") or []:
        amount = _float((move or {}).get("amount"))
        if amount is None or amount != 0:
            return True
    return False


def trade_future_value(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    valuation_factory: ValuationFactory | None,
) -> dict[str, Any]:
    """T's future-value channel: acquisition-time package value, per manager.

    Reuses the public activity feed's canonical machinery verbatim: the
    trade normalizer, the as-of resolver (the temporal ledger AT the
    trade's own instant — never today's board) and ``trade_grading``'s
    VA-inclusive per-side net.  A trade with any unresolved asset has no
    value; the channel is scoreable for a season only when EVERY in-window
    trade resolved.  Raw values never leave this function.
    """
    from src.api.public_activity_valuation import trade_instant_from_created_at

    from .activity import _normalize_trade

    trades = [tx for tx in _window_transactions(season) if str(tx.get("type")).lower() == "trade"]
    if not trades:
        # Nothing was exchanged, so no side is unmeasured: complete by
        # construction, whether or not a valuation source is supplied.
        return {
            "status": COMPLETE,
            "reason": "no_trades",
            "trades": 0,
            "valuedTrades": 0,
            "byOwner": {},
        }
    if valuation_factory is None:
        return {
            "status": UNAVAILABLE,
            "reason": "valuation_source_not_supplied",
            "trades": len(trades),
            "valuedTrades": 0,
        }
    normalized = []
    requests = []
    for tx in trades:
        if _moves_faab(tx):
            # FAAB is one side of this exchange and has no approved value
            # basis (OD-MOTY-2): the trade cannot be valued, never "valued
            # without its FAAB half".
            continue
        norm = _normalize_trade(snapshot, season, tx)
        if not norm:
            continue
        instant = trade_instant_from_created_at(norm.get("createdAt") or tx.get("created"))
        normalized.append((norm, instant))
        for side in norm.get("sides") or []:
            for asset in (side.get("receivedAssets") or []) + (side.get("sentAssets") or []):
                requests.append((asset, instant))
    resolve = valuation_factory(requests)
    valued = 0
    by_owner: dict[str, dict[str, float]] = defaultdict(lambda: {"net": 0.0, "scale": 0.0})
    for norm, instant in normalized:
        sides = []
        ok = True
        for side in norm.get("sides") or []:
            got, gave = [], []
            for bucket, dest in (("receivedAssets", got), ("sentAssets", gave)):
                for asset in side.get(bucket) or []:
                    val = None
                    try:
                        val = resolve(asset, instant)
                    except (TypeError, ValueError):
                        val = None
                    if val is None:
                        ok = False
                        break
                    dest.append(val)
                if not ok:
                    break
            if not ok:
                break
            sides.append((str(side.get("ownerId") or ""), got, gave))
        if not ok:
            continue
        valued += 1
        grades = trade_grading.grade_trade_sides([(g, v) for _o, g, v in sides])
        for (owner, _g, _v), grade in zip(sides, grades):
            if not owner:
                continue
            scale = max(
                grade["gotValue"] + max(0.0, grade["vaNet"]),
                grade["gaveValue"] + max(0.0, -grade["vaNet"]),
                1.0,
            )
            by_owner[owner]["net"] += grade["netAdjusted"]
            by_owner[owner]["scale"] += scale
    status = COMPLETE if valued == len(trades) else (PARTIAL if valued else UNAVAILABLE)
    return {
        "status": status,
        "reason": None if status == COMPLETE else "decision_time_valuation_missing",
        "trades": len(trades),
        "valuedTrades": valued,
        "byOwner": dict(by_owner) if status == COMPLETE else {},
    }


# ── Assembly ─────────────────────────────────────────────────────────────
def _explain(row: dict[str, Any]) -> str:
    """Plain-English summary of a row's backend components (display only)."""
    comp = row["components"]
    parts = []
    a = comp["A"]["score"]
    if a is not None:
        if a >= 65:
            parts.append("Strong weekly performance")
        elif a >= 55:
            parts.append("Solid weekly performance")
        elif a >= 45:
            parts.append("Average weekly performance")
        else:
            parts.append("Below-average weekly performance")
    t = comp["T"]
    if t["score"] is None and t.get("coverage") == UNAVAILABLE:
        if t["raw"]["trades"] == 0 and not t["raw"].get("draftPickExpectationNet"):
            parts.append("no trades")
        else:
            parts.append("trades not scored (their future-value side can't be measured)")
    elif t["score"] is not None:
        if t["raw"]["trades"] == 0:
            parts.append("no trades")
        elif t["score"] >= 70:
            parts.append("excellent trade returns")
        elif t["score"] > 55:
            parts.append("positive trade returns")
        elif t["score"] >= 45:
            parts.append("roughly neutral trading")
        else:
            parts.append("trades that cost value")
    w = comp["W"]
    if w["score"] is not None:
        cheap = w["raw"].get("lowCost")
        if w["score"] >= 70:
            parts.append("productive " + ("low-cost " if cheap else "") + "pickups")
        elif w["score"] > 55:
            parts.append("useful " + ("low-cost " if cheap else "") + "pickups")
        elif w["score"] >= 45:
            parts.append("little net waiver impact")
        else:
            parts.append("roster moves that cost value")
    d = comp["D"]
    if d["score"] is not None:
        if d["raw"]["selections"] == 0:
            parts.append("no draft selections")
        elif d["score"] > 55:
            parts.append("above-expectation drafting")
        elif d["score"] >= 45:
            parts.append("drafting near expectation")
        else:
            parts.append("below-expectation drafting")
    p = comp["P"]
    if p["status"] == FINAL:
        rank = p.get("finishRank")
        if rank == 1:
            parts.append("won the championship")
        elif rank == 2:
            parts.append("reached the final")
        elif p.get("madePlayoffs"):
            parts.append("made the playoffs")
        else:
            parts.append("missed the playoffs")
    if not parts:
        return ""
    if len(parts) == 1:
        text = parts[0]
    else:
        text = ", ".join(parts[:-1]) + ", and " + parts[-1]
    return text[0].upper() + text[1:] + "."


def _channel_score(
    production: float | None, future: float | None, fv_complete: bool
) -> tuple[float | None, str]:
    """W / D: production is the scored measure; their future-value halves
    are not implemented (labelled ``partial``, methodology §5.6-§5.7)."""
    if production is None:
        return None, UNAVAILABLE
    if fv_complete and future is not None:
        return PRODUCTION_SHARE * production + (1 - PRODUCTION_SHARE) * future, COMPLETE
    return production, PARTIAL


def _trade_score(
    production: float | None, future: float | None, fv_complete: bool
) -> tuple[float | None, str]:
    """T: scored ONLY when both halves are measurable (v1.1, OD-MOTY-7).

    A trade's future-value side is the counter-consideration for the
    production it gives up, so a production-only T is not a partial trade
    score -- it is a one-sided one.  Without a complete future-value
    channel T is UNAVAILABLE (never the production half standing in).
    """
    if production is None or not fv_complete or future is None:
        return None, UNAVAILABLE
    return PRODUCTION_SHARE * production + (1 - PRODUCTION_SHARE) * future, COMPLETE


def _rank_value(r: dict[str, Any]) -> float | None:
    """The number a row is ranked on: the MOTY score on a ``full`` basis,
    the measured points on an ``incomplete`` one (never mixed: T
    availability is season-wide)."""
    if r.get("score") is not None:
        return r["score"]
    inc = r.get("incomplete")
    return inc.get("measuredPoints") if isinstance(inc, dict) else None


def rank_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rank scored rows at full precision; return ``(scored, unscored)``.

    Exact ties break on (1) the combined management contribution (T+W+D on
    a ``full`` basis; W+D on an ``incomplete`` one -- an unscored T never
    breaks a tie), then (2) A; a tie on all three is an honest shared rank
    (``tied: True``).
    Never owner id, name or input order -- the sort key contains none of
    them, and rows still equal on it share one rank number.
    """
    scored = [r for r in rows if _rank_value(r) is not None]
    unscored = [r for r in rows if _rank_value(r) is None]

    def _key(r: dict[str, Any]) -> tuple[float, float, float]:
        return (_rank_value(r), r["management"], r["components"]["A"]["score"])

    scored.sort(key=lambda r: tuple(-x for x in _key(r)))
    prev = None
    for i, r in enumerate(scored):
        r.pop("tied", None)
        if prev is not None and _key(r) == _key(prev):
            r["rank"] = prev["rank"]
            r["tied"] = True
            prev["tied"] = True
        else:
            r["rank"] = i + 1
        prev = r
    for r in unscored:
        r["rank"] = None
    return scored, unscored


def build_season(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    levels: dict[str, float | None],
    *,
    valuation_factory: ValuationFactory | None = None,
) -> dict[str, Any]:
    """The full unified evaluation for one season (every manager, ranked)."""
    facts = _season_facts(season)
    a_rows, a_weeks = all_play_component(snapshot, season)
    p_rows, p_meta = postseason_component(snapshot, season)
    ledger = management_ledger(snapshot, season, levels, facts)
    fv = trade_future_value(snapshot, season, valuation_factory)
    fv_complete = fv["status"] == COMPLETE
    spent, faab_traded = _faab_by_roster(season)
    budget = _float((season.league.get("settings") or {}).get("waiver_budget"))
    n_weeks = len(facts.weeks)
    sigma = facts.sigma_week
    management_ok = ledger["basis"] != "unavailable" and n_weeks > 0 and bool(sigma)

    spent_pcts = sorted(
        100.0 * spent.get(rid, 0.0) / budget for rid in ledger["tally"] if budget and budget > 0
    )
    median_spent = spent_pcts[len(spent_pcts) // 2] if spent_pcts else None

    rows: list[dict[str, Any]] = []
    for rid, chans in ledger["tally"].items():
        oid = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
        if not oid:
            continue
        a = a_rows.get(oid, {"score": None, "weeksObserved": 0, "weeksInWindow": a_weeks})
        p = p_rows.get(oid, {"score": None, "status": PENDING, "finishRank": None})
        trades = sum(
            1
            for ev in ledger.get("events", [])
            if ev.channel == _T and rid in ev.tx.get("roster_ids", [])
        )
        comp: dict[str, Any] = {}
        # T
        t = chans[_T]
        t_prod = normalize_management(t.net, n_weeks, sigma) if management_ok else None
        fv_owner = (fv.get("byOwner") or {}).get(oid)
        fv_pct = (
            100.0 * fv_owner["net"] / fv_owner["scale"]
            if fv_owner and fv_owner["scale"] > 0
            else (0.0 if fv_complete else None)
        )
        t_fv = normalize_future_value_pct(fv_pct) if (fv_complete and fv_pct is not None) else None
        t_score, t_cov = _trade_score(t_prod, t_fv, fv_complete)
        comp["T"] = {
            "score": t_score,
            "coverage": t_cov,
            # Context only when T is unavailable: the measured production
            # half, never a stand-in for the trade score.
            "productionScore": t_prod,
            "futureValueScore": t_fv,
            "unscoredReason": (
                None
                if t_score is not None
                else (
                    "production_unmeasurable"
                    if t_prod is None
                    else f"trade_future_value_{fv['status']}"
                )
            ),
            "raw": {
                "netSurplus": t.net,
                "acquiredSurplus": t.credit,
                "surrenderedSurplus": t.charge,
                "draftPickExpectationNet": t.pick_expectation,
                "netSurplusPerWeek": t.net / n_weeks if n_weeks else None,
                "trades": trades,
                "faabTradedNet": faab_traded.get(rid, 0.0),
                "unobservedWeeks": t.unknown_credit_weeks + t.unknown_charge_weeks,
            },
        }
        # W
        w = chans[_W]
        w_prod = normalize_management(w.net, n_weeks, sigma) if management_ok else None
        w_score, w_cov = _channel_score(w_prod, None, False)
        spent_pct = 100.0 * spent.get(rid, 0.0) / budget if budget and budget > 0 else None
        comp["W"] = {
            "score": w_score,
            "coverage": w_cov,
            "productionScore": w_prod,
            "futureValueScore": None,
            "raw": {
                "netSurplus": w.net,
                "acquiredSurplus": w.credit,
                "surrenderedSurplus": w.charge,
                "netSurplusPerWeek": w.net / n_weeks if n_weeks else None,
                "faabSpent": spent.get(rid, 0.0),
                "faabBudget": budget,
                "faabSpentPct": spent_pct,
                "lowCost": (
                    spent_pct is not None and median_spent is not None and spent_pct <= median_spent
                ),
                "unobservedWeeks": w.unknown_credit_weeks + w.unknown_charge_weeks,
            },
        }
        # D
        d = chans[_D]
        n_sel = sum(1 for s in ledger["selections"] if s["rosterId"] == rid)
        d_prod = normalize_management(d.net, n_weeks, sigma) if management_ok else None
        d_score, d_cov = _channel_score(d_prod, None, False)
        comp["D"] = {
            "score": d_score,
            "coverage": d_cov,
            "productionScore": d_prod,
            "futureValueScore": None,
            "raw": {
                "netSurplusVsExpectation": d.net,
                "selectionSurplus": d.credit,
                "slotExpectation": d.charge,
                "netPerWeek": d.net / n_weeks if n_weeks else None,
                "selections": n_sel,
                "unobservedWeeks": d.unknown_credit_weeks,
            },
        }
        comp["A"] = {
            "score": a["score"],
            "coverage": COMPLETE if a["weeksObserved"] == a_weeks and a_weeks else PARTIAL,
            "raw": {"weeksObserved": a["weeksObserved"], "weeksInWindow": a_weeks},
        }
        comp["P"] = {
            "score": p["score"],
            "status": p["status"],
            "finishRank": p.get("finishRank"),
            "madePlayoffs": p.get("madePlayoffs"),
            "raw": {"entrants": p_meta["entrants"]},
        }
        rows.append({"ownerId": oid, "rosterId": rid, "components": comp})

    postseason_final = p_meta["status"] == FINAL
    for row in rows:
        comp = row["components"]
        vals = {k: comp[k]["score"] for k in ("A", "T", "W", "D")}
        row["incomplete"] = None
        if any(vals[k] is None for k in ("A", "W", "D")) or (
            vals["T"] is None and comp["T"]["productionScore"] is None
        ):
            row.update(score=None, earnedOf90=None, contributions=None, management=None)
            continue
        p_score = comp["P"]["score"] if postseason_final else None
        if vals["T"] is None:
            # T unavailable: no MOTY score.  The frozen weights applied to
            # what WAS measured, out of what those components can earn --
            # T's 25 points are missing, not redistributed.
            contrib = {k: (None if k == "T" else WEIGHTS[k] * vals[k]) for k in vals}
            contrib["P"] = WEIGHTS["P"] * p_score if p_score is not None else None
            measured = [k for k in ("A", "T", "W", "D", "P") if contrib[k] is not None]
            row.update(score=None, earnedOf90=None, contributions=contrib)
            row["management"] = contrib["W"] + contrib["D"]
            row["incomplete"] = {
                "measuredPoints": sum(contrib[k] for k in measured),
                "measurablePoints": 100.0 * sum(WEIGHTS[k] for k in measured),
                "measuredComponents": measured,
                "unscoredComponents": [k for k in ("A", "T", "W", "D", "P") if k not in measured],
            }
            continue
        contrib = {k: WEIGHTS[k] * vals[k] for k in vals}
        earned = sum(contrib.values())
        row["earnedOf90"] = earned
        row["management"] = contrib["T"] + contrib["W"] + contrib["D"]
        if p_score is not None:
            contrib["P"] = WEIGHTS["P"] * p_score
            row["score"] = earned + contrib["P"]
        else:
            contrib["P"] = None
            row["score"] = earned / NON_POSTSEASON_WEIGHT
        row["contributions"] = contrib

    scored, unscored = rank_rows(rows)
    for r in scored + unscored:
        r["displayName"] = metrics.display_name_for(snapshot, r["ownerId"])
        r["explanation"] = _explain(r)
    reasons = []
    if not fv_complete:
        reasons.append(f"trade_future_value_{fv['status']}")
    if any(r["components"]["T"]["score"] is None for r in rows):
        reasons.append("trade_component_unscored")
    reasons.append("waiver_future_value_not_implemented")
    reasons.append("draft_future_value_not_implemented")
    if ledger["basis"] == "unavailable":
        reasons.append("window_baseline_unavailable")
    recon = ledger["reconciliation"]
    if recon["unexplainedHeld"] or recon["unexplainedMissing"] or recon["missingRosterWeeks"]:
        reasons.append("ledger_reconciliation_gaps")
    coverage_status = PARTIAL if reasons else COMPLETE
    try:
        season_year = int(season.season)
    except (TypeError, ValueError):
        season_year = None
    official = bool(
        OFFICIAL_FROM_SEASON is not None
        and season_year is not None
        and season_year >= OFFICIAL_FROM_SEASON
        and postseason_final
        and coverage_status == COMPLETE
    )
    if any(r.get("score") is not None for r in scored):
        basis = BASIS_FULL
    elif scored:
        basis = BASIS_INCOMPLETE
    else:
        basis = BASIS_NONE
    # On an incomplete basis the unscored T (worth up to 100*WEIGHTS["T"])
    # could reorder anyone within that many measured points of the leader:
    # say who, instead of implying the evidence decided the order.
    unscored_range = None
    if basis == BASIS_INCOMPLETE:
        t_max = 100.0 * WEIGHTS["T"]
        top = _rank_value(scored[0])
        # <=: a manager exactly t_max behind can tie and win the tie-break.
        could_lead = [r["ownerId"] for r in scored if top - _rank_value(r) <= t_max]
        unscored_range = {
            "tMaxPoints": t_max,
            "couldLeadUnderSomeT": could_lead,
            "leaderDetermined": len(could_lead) == 1,
        }
    return _published(
        {
            "methodVersion": METHOD_VERSION,
            "season": season.season,
            "status": FINAL if postseason_final else PROVISIONAL,
            "official": official,
            # Validation track until the owner promotes it (OD-MOTY-1); an
            # incomplete basis can never be official (coverage != complete).
            "promotion": PROMOTED if official else NOT_PROMOTED,
            "scoreBasis": basis,
            "unscoredTradeRange": unscored_range,
            "asOfWeek": max(facts.weeks) if facts.weeks else 0,
            "weeksInWindow": n_weeks,
            "weights": dict(WEIGHTS),
            "rows": scored + unscored,
            "coverage": {
                "status": coverage_status,
                "reasons": reasons,
                "baseline": ledger["basis"],
                "tradeFutureValue": {
                    k: v
                    for k, v in fv.items()
                    if k in ("status", "reason", "trades", "valuedTrades")
                },
                "reconciliation": recon,
                "counts": ledger.get("counts", {}),
                "drafts": ledger["drafts"],
                "postseason": p_meta["status"],
            },
            "parameters": {
                "kappa": KAPPA,
                "sigmaWeek": sigma,
                "futureValuePctScale": FV_PCT_SCALE,
                "productionShare": PRODUCTION_SHARE,
                "draftBandSize": DRAFT_BAND_SIZE,
            },
        }
    )


#: Decimal places published.  Ranking already happened at full precision
#: (``rank_rows``); the payload carries the rank, so rounding what is
#: DISPLAYED cannot reorder anyone.  1e-4 on a 0-100 scale.
PUBLISHED_DECIMALS = 4


def _published(obj: Any) -> Any:
    if isinstance(obj, float):
        return round(obj, PUBLISHED_DECIMALS)
    if isinstance(obj, dict):
        return {k: _published(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_published(v) for v in obj]
    return obj
