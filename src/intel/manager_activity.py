"""Manager Intelligence — recent trades, acquisitions and the activity feed.

Batches B1 + B2 + the unified feed of the Manager Intelligence workstream
(``docs/intel/MANAGER_INTELLIGENCE_WORKSTREAM.md``).  For one Sleeper username
it reads the completed transactions and draft picks of every in-scope league
and publishes three views of the SAME evidence:

* ``trades`` — every completed trade the manager's roster was party to, one
  entry per trade (a three-team trade stays one trade), every side listed;
* ``acquisitions`` — every player that arrived on the manager's roster, with
  its method (TRADE / WAIVER / FREE_AGENT / DRAFT / OTHER);
* ``feed`` — one event per transaction (an add and its paired drop are ONE
  event) plus completed draft picks, deduplicated by ``tx:<transaction_id>`` /
  ``draft:<draft_id>:<pick_no>``.

Nothing here is a second pipeline.  It composes the canonical owners:

* Sleeper HTTP — ``src/public_league/sleeper_client`` classified fetchers (a
  429 is never mistaken for "no transactions");
* transaction / draft-pick → asset movements — ``src/acquisition/events.py``,
  which also applies the recorded mid-season hand-offs of our own leagues
  (``src/public_league/ownership``);
* league type, format and roster slots — ``manager_portfolio`` /
  ``src/sharp/roster_collect`` (the Batch A helpers);
* player value — ``roster_percentage.build_player_index`` over the live
  contract (joined by Sleeper id; unpriced = ``None``, never 0);
* pick value — ``src/api/pick_value_resolution.resolve_pick_value`` at the
  GENERIC grade (season + round): no tier or slot is ever fabricated;
* package-adjusted comparison — ``trade_grading.grade_trade_sides``, which
  routes through ``src/valuation_math/package_model`` and so follows the
  ACTIVE model; ``package_model.receipt()`` is stamped on the payload;
* at-the-time grades — ``trade_history_asof.grade_trades_asof`` over the
  canonical temporal ledger (the resolver factory is injected by the API
  layer; ``None`` → every at-time grade is unavailable, with the reason).

MISSING IS NEVER ZERO: an unpriced asset is ``value: None`` + ``valueReason``
and makes its side total ``None``; an unread league or week is an explicit
coverage state; an undated event stays undated; ``faabBid: None`` means "not
a waiver" while ``0`` is a $0 waiver.  Only ``status == "complete"``
transactions are read — pending, failed and rejected ones never appear.

Attribution (workstream "Rules that bind every batch"):

* a roster is the manager's when they hold it (``owner_id`` or
  ``co_owners``) — unless a recorded hand-off (``ownership.owner_at``) says
  the week belonged to someone else, which decides;
* for waiver / free-agent / drop / commissioner moves with no recorded
  hand-off, a ``creator`` who is neither the roster's owner, a co-owner nor a
  league commissioner marks the move ``previous_owner_possible`` — it stays
  in the feed, flagged, and is EXCLUDED from acquisitions;
* for trades, the counterparty proposing is normal; a trade is flagged
  ``uncertain`` only when the creator is no party's current owner/co-owner
  and no commissioner.

Batch B3 (``src/intel/manager_trade_intel.py``) adds two blocks over the SAME
reads: ``draftCapital`` — picks held per league now, from one
``/league/{id}/traded_picks`` call per league (current season only) folded by
the canonical ``picks.build_pick_ownership``, valued at the generic grade, plus
pick movement from the trade stream — and ``tendencies`` — counts with samples
over the windowed trades.  Coverage gains ``tradedPicks`` per league.

Bounded: one season, at most ``max_leagues`` leagues, a per-request Sleeper
call budget, a small thread pool, and a per-(league, week) memo (short TTL for
the current week, long for completed weeks).  ``budgetExhausted`` /
``truncated`` say when the answer is incomplete.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from src.acquisition import events as acq_events
from src.intel import manager_portfolio as mp
from src.intel import manager_trade_intel as mti
from src.public_league import ownership, sleeper_client
from src.sharp import roster_collect
from src.sharp.roster_percentage import build_player_index

Fetch = Callable[..., tuple[str, Any]]
AsofFactory = Callable[[list[tuple[dict[str, Any], Any]]], Any]

WINDOWS = {"7d": 7, "30d": 30, "90d": 90, "season": None}
DEFAULT_WINDOW = "30d"

#: Sleeper calls one activity request may spend (rosters, users, drafts,
#: draft picks and transaction weeks).  A week answered from the memo is free.
CALL_BUDGET = 900
DEFAULT_WORKERS = 6
#: The last regular + playoff leg Sleeper numbers.
MAX_LEG = 18

WEEK_TTL_CURRENT_SECONDS = 5 * 60
WEEK_TTL_COMPLETED_SECONDS = 6 * 60 * 60
PAYLOAD_TTL_SECONDS = 10 * 60
# Memory bound (prod memory-pressure follow-up, 2026-10-20).  A memo entry is
# one raw Sleeper response (rosters / users / drafts / a transaction week),
# measured ~46 KB on average, so the old 8192 cap allowed ~380 MB of raw
# payloads -- and expiry was LAZY (an entry left only when the SAME key was
# re-read past its TTL, or at the cap), so every week of every league any
# looked-up manager plays in stayed resident until the cap filled.  2048 is
# more than two full-budget requests (CALL_BUDGET = 900 puts at most), so a
# request never evicts its own entries; worst case ~95 MB.
_MEMO_MAX_ENTRIES = 2048
#: Expired entries are swept on a put at most this often (seconds of the
#: caller's clock), or whenever the memo is at its cap.
_MEMO_SWEEP_INTERVAL_SECONDS = 60.0
#: A sweep drops an entry only once it is expired by MORE than this.  The
#: ``now`` a request passes is its START time, so a long request still
#: running (and reading the memo with its older clock) may legitimately see
#: an entry that a newer request already considers expired; the grace keeps
#: a sweep from ever turning such a read into a miss.  Readers keep the exact
#: TTL rule in ``_memo_get``.
_MEMO_SWEEP_GRACE_SECONDS = 30 * 60.0
_PAYLOAD_MAX_ENTRIES = 128

#: Coverage states, one per league x data kind.
COV_COMPLETE = "complete"
COV_PARTIAL = "partial"
COV_NONE = "none"
COV_UNAVAILABLE = "unavailable"
COV_RATE_LIMITED = "rate_limited"

#: A fetch the per-request budget refused (never sent to Sleeper).
FETCH_BUDGET = "budget"

ATTR_OK = "roster_owner"
ATTR_HANDOFF = "recorded_handoff"
ATTR_COMMISSIONER = "commissioner"
ATTR_PREVIOUS_OWNER = "previous_owner_possible"
ATTR_UNCERTAIN = "attribution_uncertain"

_METHOD_LABEL = {
    "TRADE": "TRADE",
    "WAIVER": "WAIVER",
    "FREE_AGENT": "FREE_AGENT",
    "DRAFT": "DRAFT",
    "COMMISSIONER": "OTHER",
}

ANALYTICS_TOP_N = 10


# ── helpers ─────────────────────────────────────────────────────────────


def _int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _ms(v: Any) -> int | None:
    """Sleeper stamps as epoch ms (seconds are scaled); absent/≤0 → ``None``."""
    n = _int(v)
    if n is None or n <= 0:
        return None
    return n * 1000 if n < 10_000_000_000 else n


def _league_key(league_id: str) -> str:
    """Pick-identity league key: the registry slug for our own leagues, else a
    per-Sleeper-league slug.  A ``sleeper-<id>`` pick id is identity WITHIN
    that one league only — it is never a cross-season or registry identity."""
    try:
        from src.api.league_registry import league_key_for_sleeper_id  # noqa: PLC0415

        key = league_key_for_sleeper_id(league_id)
    except Exception:  # noqa: BLE001 — registry unreadable: per-league identity
        key = None
    # Lower-cased: the identity slug grammar is lower-case (real Sleeper ids
    # are digits, so this only matters for non-numeric ids).
    return key or f"sleeper-{league_id}".lower()


class _Budget:
    """Thread-safe count of Sleeper calls this request may still make."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.spent = 0
        self.refused = 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self.spent >= self.limit:
                self.refused += 1
                return False
            self.spent += 1
            return True


# ── per-(league, week) memo ─────────────────────────────────────────────

_memo: dict[tuple[str, ...], tuple[float, float, Any]] = {}
_memo_lock = threading.Lock()
_memo_last_sweep: list[float] = [float("-inf")]


def _memo_get(key: tuple[str, ...], now: float) -> Any | None:
    with _memo_lock:
        hit = _memo.get(key)
        if hit is None:
            return None
        stamp, ttl, payload = hit
        if now - stamp >= ttl:
            _memo.pop(key, None)
            return None
        return payload


def _sweep_memo_locked(now: float) -> None:
    """Drop entries expired by more than the grace.  Lock held.

    Such an entry can never be served to any running request (see
    ``_MEMO_SWEEP_GRACE_SECONDS``), so dropping it changes no answer."""
    grace = _MEMO_SWEEP_GRACE_SECONDS
    for k in [k for k, (stamp, ttl, _) in _memo.items() if now - stamp >= ttl + grace]:
        _memo.pop(k, None)
    _memo_last_sweep[0] = now


def _memo_put(key: tuple[str, ...], payload: Any, ttl: float, now: float) -> None:
    with _memo_lock:
        if (
            len(_memo) >= _MEMO_MAX_ENTRIES
            or now - _memo_last_sweep[0] >= _MEMO_SWEEP_INTERVAL_SECONDS
        ):
            _sweep_memo_locked(now)
        if key not in _memo and len(_memo) >= _MEMO_MAX_ENTRIES:
            oldest = min(_memo, key=lambda k: _memo[k][0])
            _memo.pop(oldest, None)
        _memo[key] = (now, ttl, payload)


def _budgeted(
    fetch: Fetch,
    args: tuple[Any, ...],
    *,
    budget: _Budget,
    memo_key: tuple[str, ...] | None,
    ttl: float,
    now: float,
) -> tuple[str, Any]:
    """One Sleeper read: memo first (free), then the budget, then the call.
    Only ``ok`` answers are memoised — a failure must let the next request
    retry."""
    if memo_key is not None:
        hit = _memo_get(memo_key, now)
        if hit is not None:
            return sleeper_client.FETCH_OK, hit
    if not budget.take():
        return FETCH_BUDGET, None
    kind, payload = fetch(*args)
    if kind == sleeper_client.FETCH_OK and memo_key is not None:
        _memo_put(memo_key, payload, ttl, now)
    return kind, payload


def _coverage_state(kinds: list[str]) -> str:
    """Fold a league's per-call outcomes into one coverage state."""
    if not kinds:
        return COV_NONE
    ok = sum(1 for k in kinds if k == sleeper_client.FETCH_OK)
    if ok == len(kinds):
        return COV_COMPLETE
    if ok:
        return COV_PARTIAL
    if any(k == sleeper_client.FETCH_RATE_LIMITED for k in kinds):
        return COV_RATE_LIMITED
    if all(k == FETCH_BUDGET for k in kinds):
        return COV_NONE
    return COV_UNAVAILABLE


def _failed_state(kind: str) -> str:
    if kind == sleeper_client.FETCH_RATE_LIMITED:
        return COV_RATE_LIMITED
    if kind == FETCH_BUDGET:
        return COV_NONE
    return COV_UNAVAILABLE


# ── league context ──────────────────────────────────────────────────────


class _League:
    """Everything one league contributes, read once per request."""

    def __init__(self, league: dict[str, Any], user_id: str) -> None:
        self.raw = league
        self.league_id = str(league.get("league_id") or "")
        self.name = league.get("name") or None
        self.season = str(league.get("season") or "") or None
        self.format = roster_collect.league_format(league)
        self.key = _league_key(self.league_id)
        self.user_id = user_id
        self.rosters: list[dict[str, Any]] = []
        self.rosters_state = COV_NONE
        self.users: dict[str, dict[str, Any]] = {}
        self.users_read = False
        self.commissioners: set[str] = set()
        self.drafts: list[dict[str, Any]] | None = None
        self.drafts_kind: str = FETCH_BUDGET
        self.draft_pick_kinds: list[str] = []
        self.draft_picks: dict[str, list[dict[str, Any]]] = {}
        self.week_kinds: dict[int, str] = {}
        self.transactions: list[dict[str, Any]] = []
        # Batch B3: the ``/traded_picks`` OBSERVATION (``None`` = not observed)
        # and that fetch's outcome (``None`` = not requested).
        self.traded_picks: list[Any] | None = None
        self.traded_picks_kind: str | None = None
        self._mine: set[int] | None = None

    # roster facts ---------------------------------------------------------
    def roster(self, rid: Any) -> dict[str, Any] | None:
        r = _int(rid)
        for roster in self.rosters:
            if _int(roster.get("roster_id")) == r:
                return roster
        return None

    def current_owner(self, rid: Any) -> str | None:
        roster = self.roster(rid)
        owner = str((roster or {}).get("owner_id") or "").strip()
        return owner or None

    def co_owners(self, rid: Any) -> set[str]:
        roster = self.roster(rid) or {}
        return {str(c) for c in (roster.get("co_owners") or []) if c}

    def owner_by_roster(self) -> dict[int, str]:
        out: dict[int, str] = {}
        for roster in self.rosters:
            rid = _int(roster.get("roster_id"))
            owner = str(roster.get("owner_id") or "").strip()
            if rid is not None and owner:
                out[rid] = owner
        return out

    def manager_roster_ids(self) -> set[int]:
        if self._mine is not None:
            return self._mine
        out: set[int] = set()
        for roster in self.rosters:
            rid = _int(roster.get("roster_id"))
            if rid is None:
                continue
            owner = str(roster.get("owner_id") or "")
            co = {str(c) for c in (roster.get("co_owners") or []) if c}
            if owner == self.user_id or self.user_id in co:
                out.add(rid)
        if self.rosters:
            self._mine = out
        return out

    def display_name(self, user_id: str | None) -> str | None:
        if not user_id:
            return None
        user = self.users.get(str(user_id)) or {}
        return user.get("display_name") or user.get("username") or None

    def handoff_recorded(self, rid: Any) -> bool:
        return bool(ownership.changes_for(self.league_id, rid))

    def responsible(self, rid: Any, week: Any) -> str | None:
        """Who held roster ``rid`` in ``week`` — the recorded hand-off decides
        (``ownership.owner_at``); otherwise today's owner."""
        owner = self.current_owner(rid)
        if owner is None:
            return None
        return ownership.owner_at(self.league_id, rid, owner, week)

    def is_manager_party(self, rid: Any, week: Any) -> bool:
        """Is the searched manager responsible for ``rid`` in ``week``?"""
        if _int(rid) not in self.manager_roster_ids():
            # Not their roster today; a recorded hand-off can still give them
            # an earlier week (they were the outgoing owner).
            return self.responsible(rid, week) == self.user_id
        if self.handoff_recorded(rid):
            return self.responsible(rid, week) == self.user_id
        return True

    def creator_is_rightful(self, rid: Any, creator: str | None) -> bool | None:
        """``True`` when the creator is the roster's owner, a co-owner or a
        commissioner; ``False`` when evidently not; ``None`` when unknowable
        (commissioners unread and the creator is not an owner)."""
        if not creator:
            return True  # Sleeper system move (e.g. processed waiver): no counter-evidence
        if creator == self.current_owner(rid) or creator in self.co_owners(rid):
            return True
        if creator in self.commissioners:
            return True
        if not self.users_read:
            return None
        return False

    def entry(self) -> dict[str, Any]:
        return {
            "leagueId": self.league_id,
            "name": self.name,
            "season": self.season,
            "format": self.format,
        }


# ── asset builders ──────────────────────────────────────────────────────


class _Pricer:
    """Current canonical values for players and picks (never 0 for missing)."""

    def __init__(self, contract: dict[str, Any] | None, directory: dict[str, Any]) -> None:
        self.contract = contract if isinstance(contract, dict) else None
        self.has_board = bool(self.contract and self.contract.get("playersArray"))
        self.board = build_player_index(self.contract) if self.has_board else {}
        self.directory = directory or {}
        self._pick_rows: dict[str, dict[str, Any]] | None = None

    def player(self, player_id: str) -> dict[str, Any]:
        meta = mp._player_meta(player_id, self.board, self.directory)  # noqa: SLF001
        row = self.board.get(player_id)
        if not self.has_board:
            reason = "board_unavailable"
        elif row is None:
            reason = "not_on_board"
        elif meta.get("value") is None:
            reason = "unpriced_by_board"
        else:
            reason = None
        return {
            "kind": "player",
            "playerId": player_id,
            "name": meta.get("name"),
            "position": meta.get("position"),
            "team": meta.get("nflTeam"),
            "isRookie": bool(meta.get("isRookie")),
            # Current age (board, else Sleeper directory) — B3 tendencies.
            "age": meta.get("age"),
            # The calculator resolves players by their board row name.
            "boardName": (row or {}).get("displayName") if row else None,
            "value": meta.get("value"),
            "rank": meta.get("overallRank"),
            "valueReason": reason,
        }

    def pick(self, pick: dict[str, Any], league: _League, pick_id: str | None) -> dict[str, Any]:
        season = _int(pick.get("season"))
        rnd = _int(pick.get("round"))
        out: dict[str, Any] = {
            "kind": "pick",
            "season": season,
            "round": rnd,
            "originRosterId": _int(pick.get("roster_id")),
            "pickId": pick_id,
            "label": f"{season} Round {rnd}" if season and rnd else "Unknown pick",
            "boardRowName": None,
            "value": None,
            "valueBasis": None,
            "valueReason": None,
        }
        if season is None or rnd is None:
            out["valueReason"] = "pick_unparseable"
            return out
        used = _pick_used(season, league)
        if used is True:
            # The pick was spent in that league's draft: what it bought is a
            # player, and today's pick-class value would describe nothing.
            out["valueReason"] = "pick_already_used"
            return out
        if used is None:
            out["valueReason"] = "draft_status_unknown"
            return out
        if not self.has_board:
            out["valueReason"] = "board_unavailable"
            return out
        from src.api.pick_value_resolution import (  # noqa: PLC0415
            _pick_rows_by_name,
            resolve_pick_value,
        )
        from src.identity.picks import MarketPickRef  # noqa: PLC0415

        try:
            ref = MarketPickRef(year=season, round_num=rnd)
        except ValueError:
            out["valueReason"] = "outside_board_grammar"
            return out
        if self._pick_rows is None:
            self._pick_rows = _pick_rows_by_name(self.contract)
        res = resolve_pick_value(self.contract, ref, rows_by_name=self._pick_rows)
        out["value"] = res.value
        out["valueBasis"] = res.basis
        out["boardRowName"] = res.basis_row_name if res.value is not None else None
        out["valueReason"] = res.reason
        return out


def _pick_used(season: int, league: _League) -> bool | None:
    """Was a ``season`` pick of this league already spent?  ``None`` = unknown."""
    league_season = _int(league.season)
    if league_season is not None and season < league_season:
        return True
    if league.drafts is None:
        return None if league_season is not None and season <= league_season else False
    for draft in league.drafts:
        if _int(draft.get("season")) == season:
            return str(draft.get("status") or "") == "complete"
    return False


def _total(assets: list[dict[str, Any]]) -> tuple[int | None, list[dict[str, Any]]]:
    """Sum of current values, or ``None`` when ANY asset is unpriced (with the
    unpriced assets named) — a partial total would read as a smaller-but-real
    number."""
    unpriced = [
        {"kind": a["kind"], "name": a.get("name") or a.get("label"), "reason": a["valueReason"]}
        for a in assets
        if a.get("value") is None
    ]
    if unpriced:
        return None, unpriced
    return sum(int(a["value"]) for a in assets), []


# ── transactions → trades / acquisitions / feed ─────────────────────────


def _tx_parties(tx: dict[str, Any]) -> list[int]:
    seen: list[int] = []

    def _add(v: Any) -> None:
        r = _int(v)
        if r is not None and r not in seen:
            seen.append(r)

    for rid in tx.get("roster_ids") or []:
        _add(rid)
    for mapping in (tx.get("adds"), tx.get("drops")):
        if isinstance(mapping, dict):
            for rid in mapping.values():
                _add(rid)
    for pick in tx.get("draft_picks") or []:
        if isinstance(pick, dict):
            _add(pick.get("owner_id"))
            _add(pick.get("previous_owner_id"))
    for wb in tx.get("waiver_budget") or []:
        if isinstance(wb, dict):
            _add(wb.get("sender"))
            _add(wb.get("receiver"))
    return seen


def _faab_flows(tx: dict[str, Any], rid: int) -> tuple[int | None, int | None]:
    """``(faabIn, faabOut)`` from ``tx.waiver_budget``; ``None`` when this
    roster has no FAAB entry (not "$0 sent")."""
    flows_in: list[int] = []
    flows_out: list[int] = []
    for wb in tx.get("waiver_budget") or []:
        if not isinstance(wb, dict):
            continue
        amount = _int(wb.get("amount"))
        if amount is None:
            continue
        if _int(wb.get("receiver")) == rid:
            flows_in.append(amount)
        if _int(wb.get("sender")) == rid:
            flows_out.append(amount)
    return (sum(flows_in) if flows_in else None, sum(flows_out) if flows_out else None)


def _tx_kind(tx: dict[str, Any], manager_rids: set[int]) -> str:
    ttype = str(tx.get("type") or "")
    if ttype == "trade":
        return "trade"
    if ttype == "commissioner":
        return "commissioner"
    adds = tx.get("adds") if isinstance(tx.get("adds"), dict) else {}
    mine = [p for p, r in adds.items() if _int(r) in manager_rids]
    if not mine:
        return "drop"
    return "waiver" if ttype == "waiver" else "free_agent"


def _tx_order(tx: dict[str, Any]) -> tuple[int, int]:
    """Chronological processing order.  An unstamped transaction sorts first
    explicitly (``(0, 0)``) — an ORDER key, never a published time."""
    stamp = _ms(tx.get("status_updated") or tx.get("created"))
    return (0, 0) if stamp is None else (1, stamp)


def _pick_dicts(tx: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in tx.get("draft_picks") or [] if isinstance(p, dict)]


class _Assembler:
    """Turns the read leagues into trades, acquisitions and feed events."""

    def __init__(self, user_id: str, pricer: _Pricer) -> None:
        self.user_id = user_id
        self.pricer = pricer
        self.trades: list[dict[str, Any]] = []
        self.acquisitions: list[dict[str, Any]] = []
        self.disposals: list[dict[str, Any]] = []
        self.feed: dict[str, dict[str, Any]] = {}
        self.excluded = Counter()

    # ---------------------------------------------------------------------
    def league(self, league: _League) -> None:
        owners = league.owner_by_roster()
        txs = sorted(
            {str(t.get("transaction_id")): t for t in league.transactions}.values(),
            key=_tx_order,
        )
        for tx in txs:
            if str(tx.get("status") or "") != "complete":
                self.excluded["not_complete"] += 1
                continue
            self._transaction(league, tx, owners)
        for draft_id, picks in league.draft_picks.items():
            draft = next((d for d in league.drafts or [] if str(d.get("draft_id")) == draft_id), {})
            self._draft(league, draft, picks, owners)

    # ---------------------------------------------------------------------
    def _transaction(self, league: _League, tx: dict[str, Any], owners: dict[int, str]) -> None:
        tx_id = str(tx.get("transaction_id") or "").strip()
        if not tx_id:
            return
        week = _int(tx.get("leg"))
        parties = _tx_parties(tx)
        mine = [r for r in parties if league.is_manager_party(r, week)]
        if not mine:
            if any(_int(r) in league.manager_roster_ids() for r in parties):
                # Their roster today, but a recorded hand-off gives this week to
                # the previous owner: shown to belong to someone else.
                self.excluded["recorded_previous_owner"] += 1
            return
        evs = acq_events.events_from_transaction(
            tx,
            league_key=league.key,
            sleeper_league_id=league.league_id,
            season=league.season,
            owner_by_roster=owners,
        )
        if not evs and str(tx.get("type") or "") != "trade":
            return  # an unrecognised type, or nothing moved
        creator = str(tx.get("creator") or "").strip() or None
        # The same clock rule the movement events use (completion first).
        occurred = acq_events._normalise_ms(  # noqa: SLF001
            tx.get("status_updated") or tx.get("created")
        )
        # The at-time instant is the proposal stamp, exactly as the public
        # /league grade and /trades read it, so all three agree.
        created = _ms(tx.get("created")) or occurred
        kind = _tx_kind(tx, set(mine))
        attribution = self._attribution(league, tx, kind, parties, mine, creator, week)

        sides = [self._side(league, tx, rid, week) for rid in parties]
        manager_side = next((s for s in sides if s["isManager"]), None)
        base = {
            "leagueId": league.league_id,
            "leagueName": league.name,
            "season": league.season,
            "week": week,
            "occurredAt": occurred,
            "createdAt": created,
            "format": league.format,
            "attribution": attribution,
        }

        if kind == "trade":
            self.trades.append(
                {
                    "id": f"tx:{tx_id}",
                    **base,
                    "status": "complete",
                    "creator": {"userId": creator, "displayName": league.display_name(creator)},
                    "sides": sides,
                    "teamCount": len(sides),
                }
            )

        # Acquisitions / disposals (players on the manager's side).
        acquisitions_ok = attribution["basis"] != ATTR_PREVIOUS_OWNER
        for ev in evs:
            if ev.asset_kind != acq_events.ASSET_PLAYER:
                continue
            pid = ev.asset_id.split(":", 1)[1]
            if ev.after_owner_rid in mine and ev.event_type in _METHOD_LABEL:
                if not acquisitions_ok:
                    self.excluded["previous_owner_possible"] += 1
                    continue
                gave = (
                    [*manager_side["playersOut"], *manager_side["picksOut"]]
                    if manager_side and kind == "trade"
                    else [
                        self.pricer.player(str(p))
                        for p, r in (tx.get("drops") or {}).items()
                        if _int(r) == ev.after_owner_rid
                    ]
                )
                self.acquisitions.append(
                    {
                        "id": f"tx:{tx_id}:{ev.asset_id}",
                        "sourceId": f"tx:{tx_id}",
                        "method": _METHOD_LABEL[ev.event_type],
                        **{k: base[k] for k in ("leagueId", "leagueName", "season", "week")},
                        "occurredAt": occurred,
                        "rosterId": ev.after_owner_rid,
                        "player": self.pricer.player(pid),
                        "faabBid": ev.faab_bid,
                        "draft": None,
                        "gaveUp": gave,
                        "attribution": attribution,
                    }
                )
            if ev.before_owner_rid in mine and ev.event_type in ("TRADE_AWAY", "DROP", "TRADE"):
                if ev.event_type == "TRADE" and ev.after_owner_rid in mine:
                    continue
                self.disposals.append(
                    {
                        "leagueId": league.league_id,
                        "playerId": pid,
                        "rosterId": ev.before_owner_rid,
                        "occurredAt": occurred,
                        "state": "traded_away" if kind == "trade" else "dropped",
                    }
                )

        # Feed: one event per transaction, adds + drops combined.
        adds_m = [
            self.pricer.player(str(p)) for p, r in (tx.get("adds") or {}).items() if _int(r) in mine
        ]
        drops_m = [
            self.pricer.player(str(p))
            for p, r in (tx.get("drops") or {}).items()
            if _int(r) in mine
        ]
        if kind == "trade" and manager_side:
            adds_m = [*manager_side["playersIn"], *manager_side["picksIn"]]
            drops_m = [*manager_side["playersOut"], *manager_side["picksOut"]]
        faab = acq_events._int_or_none(  # noqa: SLF001 — the same parse events use
            (tx.get("settings") or {}).get("waiver_bid")
        )
        self.feed[f"tx:{tx_id}"] = {
            "id": f"tx:{tx_id}",
            "kind": kind,
            **base,
            "added": adds_m,
            "dropped": drops_m,
            "faabBid": faab if str(tx.get("type")) == "waiver" else None,
            "partners": [s["displayName"] for s in sides if not s["isManager"] and s["displayName"]]
            if kind == "trade"
            else [],
        }

    def _side(self, league: _League, tx: dict[str, Any], rid: int, week: int | None) -> dict:
        owner = league.responsible(rid, week)
        adds = tx.get("adds") if isinstance(tx.get("adds"), dict) else {}
        drops = tx.get("drops") if isinstance(tx.get("drops"), dict) else {}
        p_in = [self.pricer.player(str(p)) for p, r in adds.items() if _int(r) == rid]
        p_out = [self.pricer.player(str(p)) for p, r in drops.items() if _int(r) == rid]
        picks_in, picks_out = [], []
        for pick in _pick_dicts(tx):
            pick_id = acq_events._pick_asset_id(league.key, pick)  # noqa: SLF001 — C1-U3 owner
            if _int(pick.get("owner_id")) == rid:
                picks_in.append(self.pricer.pick(pick, league, pick_id))
            if _int(pick.get("previous_owner_id")) == rid:
                picks_out.append(self.pricer.pick(pick, league, pick_id))
        faab_in, faab_out = _faab_flows(tx, rid)
        incoming, unpriced_in = _total([*p_in, *picks_in])
        outgoing, unpriced_out = _total([*p_out, *picks_out])
        return {
            "rosterId": rid,
            "ownerUserId": owner,
            "displayName": league.display_name(owner),
            "isManager": league.is_manager_party(rid, week),
            "playersIn": p_in,
            "playersOut": p_out,
            "picksIn": picks_in,
            "picksOut": picks_out,
            "faabIn": faab_in,
            "faabOut": faab_out,
            "incomingValue": incoming,
            "outgoingValue": outgoing,
            "unpricedAssets": unpriced_in + unpriced_out,
        }

    def _attribution(
        self,
        league: _League,
        tx: dict[str, Any],
        kind: str,
        parties: list[int],
        mine: list[int],
        creator: str | None,
        week: int | None,
    ) -> dict[str, Any]:
        if any(league.handoff_recorded(r) for r in mine):
            return {"basis": ATTR_HANDOFF, "uncertain": False, "reason": None}
        if kind == "trade":
            rightful = [league.creator_is_rightful(r, creator) for r in parties]
            if any(v is True for v in rightful):
                return {"basis": ATTR_OK, "uncertain": False, "reason": None}
            reason = (
                "creator_not_a_current_party"
                if all(v is False for v in rightful)
                else "league_users_unavailable"
            )
            return {"basis": ATTR_UNCERTAIN, "uncertain": True, "reason": reason}
        verdicts = [league.creator_is_rightful(r, creator) for r in mine]
        if all(v is True for v in verdicts):
            basis = (
                ATTR_COMMISSIONER
                if creator
                and creator in league.commissioners
                and all(creator != league.current_owner(r) for r in mine)
                else ATTR_OK
            )
            return {"basis": basis, "uncertain": False, "reason": None}
        reason = (
            "creator_not_owner_or_commissioner"
            if any(v is False for v in verdicts)
            else "league_users_unavailable"
        )
        return {"basis": ATTR_PREVIOUS_OWNER, "uncertain": True, "reason": reason}

    # ---------------------------------------------------------------------
    def _draft(
        self,
        league: _League,
        draft: dict[str, Any],
        picks: list[dict[str, Any]],
        owners: dict[int, str],
    ) -> None:
        draft_id = str(draft.get("draft_id") or "")
        if not draft_id:
            return
        settings = draft.get("settings") if isinstance(draft.get("settings"), dict) else {}
        teams = _int(settings.get("teams"))
        dtype = str(draft.get("type") or "") or None
        evs = acq_events.events_from_draft_picks(
            picks,
            league_key=league.key,
            draft_id=draft_id,
            sleeper_league_id=league.league_id,
            season=draft.get("season") or league.season,
            draft_kind=dtype,
            owner_by_roster=owners,
        )
        by_no = {_int(p.get("pick_no")): p for p in picks if isinstance(p, dict)}
        bound = {
            "notBefore": _ms(draft.get("start_time")),
            "notAfter": _ms(draft.get("last_picked")),
        }
        for ev in evs:
            rid = ev.after_owner_rid
            if rid is None or not league.is_manager_party(rid, 0):
                continue
            raw = by_no.get(_int(ev.source_ref.rsplit(":", 1)[1])) or {}
            pick_no = _int(raw.get("pick_no"))
            picked_by = str(raw.get("picked_by") or "").strip() or None
            if league.handoff_recorded(rid):
                attribution = {"basis": ATTR_HANDOFF, "uncertain": False, "reason": None}
            else:
                verdict = league.creator_is_rightful(rid, picked_by)
                attribution = (
                    {"basis": ATTR_OK, "uncertain": False, "reason": None}
                    if verdict is True
                    else {
                        "basis": ATTR_PREVIOUS_OWNER,
                        "uncertain": True,
                        "reason": "picker_not_owner_or_commissioner"
                        if verdict is False
                        else "league_users_unavailable",
                    }
                )
            auction = dtype == "auction"
            slot = (
                ((pick_no - 1) % teams) + 1
                if (not auction and pick_no is not None and teams)
                else None
            )
            player = self.pricer.player(ev.asset_id.split(":", 1)[1])
            draft_block = {
                "draftId": draft_id,
                "round": None if auction else _int(raw.get("round")),
                "slot": slot,
                "pickNo": pick_no,
                "kind": dtype,
                "auctionAmount": ev.auction_amount,
                "isKeeper": bool(raw.get("is_keeper")),
            }
            occurred = ev.occurred_at_ms
            common = {
                "leagueId": league.league_id,
                "leagueName": league.name,
                "season": ev.season,
                "week": None,
                "occurredAt": occurred,
                "occurredBound": bound if occurred is None else None,
                "attribution": attribution,
            }
            self.feed[ev.source_ref] = {
                "id": ev.source_ref,
                "kind": "draft",
                **common,
                "createdAt": occurred,
                "format": league.format,
                "added": [player],
                "dropped": [],
                "faabBid": None,
                "partners": [],
                "draft": draft_block,
            }
            if attribution["basis"] == ATTR_PREVIOUS_OWNER:
                self.excluded["previous_owner_possible"] += 1
                continue
            self.acquisitions.append(
                {
                    "id": f"{ev.source_ref}:{ev.asset_id}",
                    "sourceId": ev.source_ref,
                    "method": "DRAFT",
                    **common,
                    "rosterId": rid,
                    "player": player,
                    "faabBid": None,
                    "draft": draft_block,
                    "gaveUp": [],
                }
            )


# ── package comparison / at-time ────────────────────────────────────────


def _package(trades: list[dict[str, Any]]) -> None:
    """Stamp each trade's package-adjusted comparison under the ACTIVE model.

    Only when every asset of the trade is priced: ``grade_trade_sides`` drops
    non-positive values, so an unpriced asset would silently shrink a side.
    For three or more teams the model (a two-package calibration) is applied
    per side to that side's received-vs-sent packages — the same per-side
    extension the /trades and /league grades use, so one trade grades the
    same everywhere — and the response labels it as such.
    """
    from src.public_league.trade_grading import grade_trade_sides  # noqa: PLC0415
    from src.valuation_math import package_model  # noqa: PLC0415

    model = package_model.receipt()
    for trade in trades:
        sides = trade["sides"]
        if any(s["incomingValue"] is None or s["outgoingValue"] is None for s in sides):
            trade["packageComparison"] = {
                "available": False,
                "reason": "unpriced_assets",
                "model": model["id"],
            }
            continue
        graded = grade_trade_sides(
            [
                (
                    [a["value"] for a in (*s["playersIn"], *s["picksIn"])],
                    [a["value"] for a in (*s["playersOut"], *s["picksOut"])],
                )
                for s in sides
            ]
        )
        per_side = []
        for side, g in zip(sides, graded, strict=True):
            per_side.append(
                {
                    "rosterId": side["rosterId"],
                    "rawNet": int(round(g["netValue"])),
                    "adjustment": int(round(g["vaNet"])),
                    "adjustedNet": int(round(g["netAdjusted"])),
                    "pctGap": round(g["pctGap"], 2),
                    "grade": g["grade"]["grade"],
                    "label": g["grade"]["label"],
                }
            )
        manager = next((p for p, s in zip(per_side, sides, strict=True) if s["isManager"]), None)
        trade["packageComparison"] = {
            "available": True,
            "model": model["id"],
            "basis": "two_package" if len(sides) == 2 else "per_side_received_vs_sent",
            "note": None
            if len(sides) == 2
            else (
                "The package model is calibrated on two-package pairings; for a "
                f"{len(sides)}-team trade it is applied per side to that side's "
                "received vs sent assets."
            ),
            "manager": manager,
            "sides": per_side,
        }


def _asof_asset(asset: dict[str, Any]) -> dict[str, Any]:
    if asset["kind"] == "player":
        return {
            "kind": "player",
            "playerId": asset["playerId"],
            "playerName": asset.get("name"),
            "position": asset.get("position"),
        }
    return {
        "kind": "pick",
        "season": asset.get("season"),
        "round": asset.get("round"),
        "label": asset.get("label"),
    }


def _at_time(trades: list[dict[str, Any]], asof_factory: AsofFactory | None) -> None:
    """At-the-time grade per side (same ledger resolver + model as /trades
    and /league), and aging = current adjusted net − at-time adjusted net,
    only when both exist."""
    from src.api import trade_history_asof  # noqa: PLC0415

    if not trades:
        return
    requests_trades = [
        {
            "id": t["id"],
            "createdAt": t["createdAt"],
            "sides": [
                {
                    "receivedAssets": [_asof_asset(a) for a in (*s["playersIn"], *s["picksIn"])],
                    "sentAssets": [_asof_asset(a) for a in (*s["playersOut"], *s["picksOut"])],
                }
                for s in t["sides"]
            ],
        }
        for t in trades
    ]
    resolve = None
    reason = "history_ledger_missing"
    if asof_factory is not None:
        try:
            resolve = asof_factory(trade_history_asof.asof_requests(requests_trades))
        except Exception:  # noqa: BLE001 — a broken ledger is "unavailable", not a 500
            resolve = None
            reason = "history_ledger_unreadable"
    if resolve is None:
        graded = [
            {"asOf": None, "sides": [{"available": False, "reason": reason} for _ in t["sides"]]}
            for t in requests_trades
        ]
    else:
        graded = trade_history_asof.grade_trades_asof(requests_trades, resolve)
    for trade, g in zip(trades, graded, strict=True):
        sides_out = []
        aging = []
        current = trade.get("packageComparison") or {}
        current_by_rid = {s["rosterId"]: s for s in current.get("sides") or []}
        for side, at in zip(trade["sides"], g["sides"], strict=True):
            if at.get("available"):
                entry = {
                    "rosterId": side["rosterId"],
                    "available": True,
                    "rawNet": int(round(at["netValue"])),
                    "adjustedNet": int(round(at["netAdjusted"])),
                    "pctGap": round(at["pctGap"], 2),
                    "grade": at["grade"]["grade"],
                    "label": at["grade"]["label"],
                }
            else:
                entry = {
                    "rosterId": side["rosterId"],
                    "available": False,
                    "reason": at.get("reason"),
                    "missingAssets": at.get("missingAssets") or [],
                }
            sides_out.append(entry)
            cur = current_by_rid.get(side["rosterId"])
            if entry["available"] and cur is not None:
                aging.append(
                    {
                        "rosterId": side["rosterId"],
                        "available": True,
                        "delta": cur["adjustedNet"] - entry["adjustedNet"],
                    }
                )
            else:
                aging.append(
                    {
                        "rosterId": side["rosterId"],
                        "available": False,
                        "reason": "current_comparison_unavailable"
                        if entry["available"]
                        else "at_time_unavailable",
                    }
                )
        manager_rid = next((s["rosterId"] for s in trade["sides"] if s["isManager"]), None)
        trade["atTime"] = {
            "asOf": g.get("asOf"),
            "sides": sides_out,
            "manager": next((s for s in sides_out if s["rosterId"] == manager_rid), None),
        }
        trade["aging"] = {
            "sides": aging,
            "manager": next((a for a in aging if a["rosterId"] == manager_rid), None),
        }


# ── subsequent state / analytics ────────────────────────────────────────


def _sort_key(item: dict[str, Any]) -> tuple[int, int]:
    """Newest first; an undated event sorts by its bound (if any), else last."""
    occurred = item.get("occurredAt")
    if occurred is not None:
        return (1, int(occurred))
    bound = (item.get("occurredBound") or {}).get("notAfter")
    return (0, int(bound)) if bound is not None else (0, 0)


def _stamp_subsequent(
    acquisitions: list[dict[str, Any]],
    disposals: list[dict[str, Any]],
    leagues: dict[str, _League],
) -> None:
    for acq in acquisitions:
        league = leagues[acq["leagueId"]]
        pid = acq["player"]["playerId"]
        roster = league.roster(acq["rosterId"]) or {}
        slots = dict(mp._slot_assets(roster)) if roster else None  # noqa: SLF001
        acq["stillRostered"] = None if slots is None else pid in slots
        acq["currentSlot"] = slots.get(pid) if slots else None
        t0 = acq.get("occurredAt")
        later = [
            d
            for d in disposals
            if d["leagueId"] == acq["leagueId"]
            and d["playerId"] == pid
            and d["rosterId"] == acq["rosterId"]
            and (t0 is None or (d["occurredAt"] is not None and d["occurredAt"] > t0))
        ]
        if later and t0 is not None:
            first = min(later, key=lambda d: d["occurredAt"])
            acq["subsequent"] = {"state": first["state"], "at": first["occurredAt"]}
        elif acq["stillRostered"] is True:
            acq["subsequent"] = {"state": "still_rostered", "at": None}
        else:
            acq["subsequent"] = {"state": "unknown", "at": None}


def _analytics(
    acquisitions: list[dict[str, Any]], feed: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_player: dict[str, dict[str, Any]] = {}
    for acq in acquisitions:
        p = acq["player"]
        entry = by_player.setdefault(
            p["playerId"],
            {
                "playerId": p["playerId"],
                "name": p.get("name"),
                "position": p.get("position"),
                "team": p.get("team"),
                "value": p.get("value"),
                "rank": p.get("rank"),
                "isRookie": p.get("isRookie"),
                "timesAcquired": 0,
                "leagues": [],
                "methods": Counter(),
                "latestAt": None,
            },
        )
        entry["timesAcquired"] += 1
        if acq["leagueId"] not in entry["leagues"]:
            entry["leagues"].append(acq["leagueId"])
        entry["methods"][acq["method"]] += 1
        if acq.get("occurredAt") is not None and (
            entry["latestAt"] is None or acq["occurredAt"] > entry["latestAt"]
        ):
            entry["latestAt"] = acq["occurredAt"]
    summary = []
    for entry in by_player.values():
        entry["methods"] = dict(entry["methods"])
        entry["leagueCount"] = len(entry["leagues"])
        summary.append(entry)
    summary.sort(
        key=lambda e: (
            -e["timesAcquired"],
            -(e["value"] if e["value"] is not None else -1),
            e["name"] or "",
        )
    )

    priced = [a for a in acquisitions if a["player"].get("value") is not None]
    priced.sort(key=lambda a: -a["player"]["value"])
    drops = sum(len(f["dropped"]) for f in feed if f["kind"] in ("waiver", "free_agent", "drop"))
    traded_away = sum(len(f["dropped"]) for f in feed if f["kind"] == "trade")
    analytics = {
        "acquisitionCount": len(acquisitions),
        "pricedAcquisitions": len(priced),
        "mostValuable": [
            {
                "id": a["id"],
                "playerId": a["player"]["playerId"],
                "name": a["player"].get("name"),
                "position": a["player"].get("position"),
                "value": a["player"]["value"],
                "method": a["method"],
                "leagueName": a["leagueName"],
            }
            for a in priced[:ANALYTICS_TOP_N]
        ],
        "byPosition": dict(
            sorted(Counter(a["player"].get("position") or "UNKNOWN" for a in acquisitions).items())
        ),
        "byMethod": dict(sorted(Counter(a["method"] for a in acquisitions).items())),
        "addsVsDrops": {
            "adds": len(acquisitions),
            "drops": drops,
            "tradedAway": traded_away,
        },
        "repeatTargets": [
            {
                "playerId": e["playerId"],
                "name": e["name"],
                "timesAcquired": e["timesAcquired"],
                "leagueCount": e["leagueCount"],
            }
            for e in summary
            if e["timesAcquired"] >= 2 or e["leagueCount"] >= 2
        ],
        "rookies": {
            "count": sum(1 for a in acquisitions if a["player"].get("isRookie")),
            "players": sorted(
                {
                    a["player"].get("name") or a["player"]["playerId"]
                    for a in acquisitions
                    if a["player"].get("isRookie")
                }
            ),
        },
        "idp": {
            "count": sum(
                1 for a in acquisitions if (a["player"].get("position") or "") in mp.IDP_POSITIONS
            )
        },
        "subsequentlyTradedOrDropped": [
            {
                "id": a["id"],
                "name": a["player"].get("name"),
                "state": a["subsequent"]["state"],
                "leagueName": a["leagueName"],
            }
            for a in acquisitions
            if a["subsequent"]["state"] in ("traded_away", "dropped")
        ],
    }
    return summary, analytics


# ── retrieval ───────────────────────────────────────────────────────────


def _legs(state: dict[str, Any] | None, season: str, current_season: str) -> tuple[list[int], int]:
    """Which legs to read and which one is "current" (short memo TTL).

    An earlier season reads every leg (all completed).  The current season
    reads legs 0..current; in the offseason (or with no week reported)
    Sleeper files trades under legs 0-1.
    """
    if season != current_season:
        return list(range(0, MAX_LEG + 1)), -1
    st = state or {}
    season_type = str(st.get("season_type") or "")
    leg = _int(st.get("leg"))
    if leg is None:
        leg = _int(st.get("week"))
    if season_type in ("off", "pre") or not leg:
        return [0, 1], 1
    leg = min(max(leg, 1), MAX_LEG)
    return list(range(0, leg + 1)), leg


def _read_league_base(
    league: _League,
    *,
    budget: _Budget,
    fetch_rosters: Fetch,
    fetch_users: Fetch,
    fetch_drafts: Fetch,
    now: float,
    fetch_traded_picks: Fetch | None = None,
) -> None:
    kind, rosters = _budgeted(
        fetch_rosters, (league.league_id,), budget=budget, memo_key=None, ttl=0, now=now
    )
    if kind != sleeper_client.FETCH_OK:
        league.rosters_state = _failed_state(kind)
        return
    league.rosters = [r for r in rosters or [] if isinstance(r, dict)]
    league.rosters_state = COV_COMPLETE
    kind, users = _budgeted(
        fetch_users, (league.league_id,), budget=budget, memo_key=None, ttl=0, now=now
    )
    if kind == sleeper_client.FETCH_OK:
        league.users_read = True
        for u in users or []:
            if isinstance(u, dict) and u.get("user_id"):
                league.users[str(u["user_id"])] = u
                if u.get("is_owner"):
                    league.commissioners.add(str(u["user_id"]))
    kind, drafts = _budgeted(
        fetch_drafts,
        (league.league_id,),
        budget=budget,
        memo_key=("drafts", league.league_id),
        ttl=WEEK_TTL_CURRENT_SECONDS,
        now=now,
    )
    league.drafts_kind = kind
    if kind == sleeper_client.FETCH_OK:
        league.drafts = [d for d in drafts or [] if isinstance(d, dict)]
    if fetch_traded_picks is None or not league.manager_roster_ids():
        return
    # Batch B3 draft capital: one call per league, current season only.
    from src.identity.picks import traded_picks_observation  # noqa: PLC0415

    kind, body = _budgeted(
        fetch_traded_picks,
        (league.league_id,),
        budget=budget,
        memo_key=("traded_picks", league.league_id),
        ttl=WEEK_TTL_CURRENT_SECONDS,
        now=now,
    )
    observed = traded_picks_observation(body) if kind == sleeper_client.FETCH_OK else None
    if kind == sleeper_client.FETCH_OK and observed is None:
        kind = sleeper_client.FETCH_ERROR  # a non-list body proves nothing
    league.traded_picks_kind = kind
    league.traded_picks = observed


def _traded_picks_state(league: _League, want_picks: bool) -> str:
    """Coverage of the B3 ``/traded_picks`` read for one league."""
    if league.rosters_state != COV_COMPLETE:
        return league.rosters_state if want_picks else COV_NONE
    if not want_picks or not league.manager_roster_ids():
        return COV_NONE
    kind = league.traded_picks_kind
    if kind == sleeper_client.FETCH_OK:
        return COV_COMPLETE
    return _failed_state(kind or FETCH_BUDGET)


def _draft_capital(
    ctx: list[_League],
    pricer: _Pricer,
    trades: list[dict[str, Any]],
    *,
    want_picks: bool,
    now_s: float,
) -> dict[str, Any]:
    """Batch B3: picks held per league, pick movement and totals."""
    value_note = (
        "Pick values are the canonical board's (a Superflex / TE-premium board) at the "
        "generic season + round grade — no tier or slot is assumed. Totals add priced "
        "picks only; unpriced picks are counted beside them."
    )
    if not want_picks:
        return {
            "available": False,
            "reason": mti.DC_REASON_EARLIER_SEASON,
            "leagues": [],
            "totals": None,
            "movements": mti.pick_movements(trades, {}),
            "valueNote": value_note,
        }
    calendar_year = time.gmtime(now_s).tm_year
    observed_at = mti.observed_at_iso(now_s)
    entries: list[dict[str, Any]] = []
    for lg in ctx:
        state = _traded_picks_state(lg, True)
        if lg.rosters_state != COV_COMPLETE:
            entries.append(
                mti.unread_league_entry(lg, mti.DC_REASON_ROSTERS_UNAVAILABLE, lg.rosters_state)
            )
            continue
        if not lg.manager_roster_ids():
            continue  # holds no roster here: nothing to own
        entries.append(
            mti.league_draft_capital(
                lg,
                pricer,
                traded_picks=lg.traded_picks,
                coverage=state,
                calendar_year=calendar_year,
                observed_at=observed_at,
                pick_used=_pick_used,
            )
        )
    by_league = {e["leagueId"]: e for e in entries}
    return {
        "available": True,
        "reason": None,
        "leagues": entries,
        "totals": mti.draft_capital_totals(entries),
        "movements": mti.pick_movements(trades, by_league),
        "valueNote": value_note,
    }


def _read_league_activity(
    readable: list[_League],
    legs: list[int],
    current_leg: int,
    *,
    budget: _Budget,
    fetch_transactions: Fetch,
    fetch_draft_picks: Fetch,
    now: float,
    workers: int,
) -> None:
    """Read every requested transaction leg and every live/complete draft's
    picks of ``readable`` leagues — through the per-(league, week) memo and
    the request's call budget.  Shared by the manager activity lookup and the
    league scouting view (Batch C), so both spend the same memo."""
    jobs: list[tuple[str, _League, Any]] = []
    for lg in readable:
        for leg in legs:
            jobs.append(("week", lg, leg))
        for draft in lg.drafts or []:
            if str(draft.get("status") or "") in ("complete", "drafting", "paused"):
                jobs.append(("draft", lg, draft))

    def _run(job: tuple[str, _League, Any]) -> None:
        what, lg, arg = job
        if what == "week":
            ttl = WEEK_TTL_CURRENT_SECONDS if arg == current_leg else WEEK_TTL_COMPLETED_SECONDS
            k, txs = _budgeted(
                fetch_transactions,
                (lg.league_id, arg),
                budget=budget,
                memo_key=("tx", lg.league_id, str(arg)),
                ttl=ttl,
                now=now,
            )
            lg.week_kinds[arg] = k
            if k == sleeper_client.FETCH_OK:
                lg.transactions.extend(t for t in txs or [] if isinstance(t, dict))
            return
        draft_id = str(arg.get("draft_id") or "")
        complete = str(arg.get("status") or "") == "complete"
        k, picks = _budgeted(
            fetch_draft_picks,
            (draft_id,),
            budget=budget,
            memo_key=("draftpicks", draft_id),
            ttl=WEEK_TTL_COMPLETED_SECONDS if complete else WEEK_TTL_CURRENT_SECONDS,
            now=now,
        )
        lg.draft_pick_kinds.append(k)
        if k == sleeper_client.FETCH_OK:
            lg.draft_picks[draft_id] = [p for p in picks or [] if isinstance(p, dict)]

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(_run, jobs))


def _league_coverage(lg: _League, legs: list[int], want_picks: bool) -> dict[str, Any]:
    """One league's coverage row (rosters / transactions / drafts / traded
    picks / users) plus whether it is incomplete for the searched roster(s)."""
    if lg.rosters_state != COV_COMPLETE:
        tx_state = drafts_state = lg.rosters_state
        weeks_ok = weeks_failed = 0
    elif not lg.manager_roster_ids():
        tx_state = drafts_state = COV_NONE
        weeks_ok = weeks_failed = 0
    else:
        kinds = [lg.week_kinds.get(leg, FETCH_BUDGET) for leg in legs]
        tx_state = _coverage_state(kinds)
        weeks_ok = sum(1 for k in kinds if k == sleeper_client.FETCH_OK)
        weeks_failed = len(kinds) - weeks_ok
        if lg.drafts_kind != sleeper_client.FETCH_OK:
            drafts_state = _failed_state(lg.drafts_kind)
        elif not lg.draft_pick_kinds:
            drafts_state = COV_COMPLETE
        else:
            drafts_state = _coverage_state(lg.draft_pick_kinds)
    picks_state = _traded_picks_state(lg, want_picks)
    held = bool(lg.manager_roster_ids()) if lg.rosters_state == COV_COMPLETE else None
    incomplete = held is not False and (
        tx_state != COV_COMPLETE
        or drafts_state != COV_COMPLETE
        or (want_picks and picks_state != COV_COMPLETE)
    )
    return {
        **lg.entry(),
        "rosterHeld": held,
        "rosters": lg.rosters_state,
        "transactions": tx_state,
        "drafts": drafts_state,
        "tradedPicks": picks_state,
        "weeksFetched": weeks_ok,
        "weeksFailed": weeks_failed,
        "leagueUsers": "complete" if lg.users_read else "unavailable",
        "incomplete": incomplete,
    }


def _status_payload(status: str, username: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "query": username, **extra}


def build_manager_activity(
    username: str,
    *,
    contract: dict[str, Any] | None,
    window: str = DEFAULT_WINDOW,
    season: str | None = None,
    league_id: str | None = None,
    scope: str = mp.SCOPE_DYNASTY,
    max_leagues: int = mp.DEFAULT_MAX_LEAGUES,
    workers: int = DEFAULT_WORKERS,
    call_budget: int = CALL_BUDGET,
    asof_factory: AsofFactory | None = None,
    fetch_user: Fetch = sleeper_client.fetch_user_classified,
    fetch_leagues: Fetch = sleeper_client.fetch_user_leagues_classified,
    fetch_rosters: Fetch = sleeper_client.fetch_rosters_classified,
    fetch_users: Fetch = sleeper_client.fetch_league_users_classified,
    fetch_transactions: Fetch = sleeper_client.fetch_transactions_classified,
    fetch_drafts: Fetch = sleeper_client.fetch_drafts_classified,
    fetch_draft_picks: Fetch = sleeper_client.fetch_draft_picks_classified,
    fetch_traded_picks: Fetch = sleeper_client.fetch_traded_picks_classified,
    fetch_state: Callable[[], Any] = sleeper_client.fetch_nfl_state,
    fetch_directory: Callable[[], Any] = sleeper_client.fetch_nfl_players,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """The Manager Intelligence activity payload for one username.

    ``status``: ``ok`` / ``partial`` (some league x data kind not fully read)
    / ``not_found`` / ``rate_limited`` / ``upstream_unavailable``.  Never
    raises for an upstream failure; never fabricates an unread week.
    """
    if scope not in mp.SCOPES:
        scope = mp.SCOPE_DYNASTY
    if window not in WINDOWS:
        window = DEFAULT_WINDOW
    t_now = now()
    kind, user = fetch_user(username)
    if kind != sleeper_client.FETCH_OK:
        return _status_payload(
            {
                sleeper_client.FETCH_NOT_FOUND: mp.STATUS_NOT_FOUND,
                sleeper_client.FETCH_RATE_LIMITED: mp.STATUS_RATE_LIMITED,
            }.get(kind, mp.STATUS_UPSTREAM_UNAVAILABLE),
            username,
        )
    user_id = str(user["user_id"])
    manager = {
        "userId": user_id,
        "username": user.get("username") or None,
        "displayName": user.get("display_name") or user.get("username") or None,
    }
    state = fetch_state() or {}
    current_season = str(
        state.get("league_season") or state.get("season") or time.gmtime(t_now).tm_year
    )
    season = str(season or current_season)
    kind, leagues = fetch_leagues(user_id, season)
    if kind != sleeper_client.FETCH_OK:
        return _status_payload(
            mp.STATUS_RATE_LIMITED
            if kind == sleeper_client.FETCH_RATE_LIMITED
            else mp.STATUS_UPSTREAM_UNAVAILABLE,
            username,
            manager=manager,
            season=season,
        )
    leagues = [lg for lg in leagues or [] if isinstance(lg, dict) and lg.get("league_id")]
    in_scope = [lg for lg in leagues if mp.league_scope(lg) == scope]
    league_filter_unmatched = False
    if league_id:
        in_scope = [lg for lg in in_scope if str(lg.get("league_id")) == str(league_id)]
        league_filter_unmatched = not in_scope
    in_scope.sort(key=lambda lg: str(lg.get("name") or ""))
    truncated = len(in_scope) > max_leagues
    in_scope = in_scope[:max_leagues]

    budget = _Budget(call_budget)
    # Draft capital is "what is held NOW": read for the current season only.
    want_picks = season == current_season
    ctx = [_League(lg, user_id) for lg in in_scope]
    pool_size = max(1, min(workers, max(1, len(ctx))))
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        list(
            pool.map(
                lambda lg: _read_league_base(
                    lg,
                    budget=budget,
                    fetch_rosters=fetch_rosters,
                    fetch_users=fetch_users,
                    fetch_drafts=fetch_drafts,
                    now=t_now,
                    fetch_traded_picks=fetch_traded_picks if want_picks else None,
                ),
                ctx,
            )
        )

    legs, current_leg = _legs(state, season, current_season)
    readable = [lg for lg in ctx if lg.rosters_state == COV_COMPLETE and lg.manager_roster_ids()]
    _read_league_activity(
        readable,
        legs,
        current_leg,
        budget=budget,
        fetch_transactions=fetch_transactions,
        fetch_draft_picks=fetch_draft_picks,
        now=t_now,
        workers=pool_size,
    )

    directory = fetch_directory() or {}
    pricer = _Pricer(contract, directory)
    asm = _Assembler(user_id, pricer)
    for lg in readable:
        asm.league(lg)

    # Window (after subsequent-state, which reads the whole season read).
    days = WINDOWS[window]
    window_applied = window
    if season != current_season:
        days = None
        window_applied = "season"
    start = (t_now - days * 86400) * 1000 if days is not None else None

    def _in_window(item: dict[str, Any]) -> bool:
        if start is None:
            return True
        occurred = item.get("occurredAt")
        if occurred is not None:
            return occurred >= start
        bound = (item.get("occurredBound") or {}).get("notAfter")
        # Undated: kept only when its known bound says it may fall inside.
        return bound is not None and bound >= start

    by_id = {lg.league_id: lg for lg in ctx}
    _stamp_subsequent(asm.acquisitions, asm.disposals, by_id)
    trades = sorted((t for t in asm.trades if _in_window(t)), key=_sort_key, reverse=True)
    acquisitions = sorted(
        (a for a in asm.acquisitions if _in_window(a)), key=_sort_key, reverse=True
    )
    feed = sorted((f for f in asm.feed.values() if _in_window(f)), key=_sort_key, reverse=True)
    _package(trades)
    _at_time(trades, asof_factory)
    summary, analytics = _analytics(acquisitions, feed)
    draft_capital = _draft_capital(ctx, pricer, trades, want_picks=want_picks, now_s=t_now)
    tendencies = mti.trade_tendencies(trades, window=window_applied, season=season)

    coverage = []
    any_incomplete = False
    for lg in ctx:
        row = _league_coverage(lg, legs, want_picks)
        any_incomplete = any_incomplete or row.pop("incomplete")
        coverage.append(row)

    from src.valuation_math import package_model  # noqa: PLC0415

    return {
        "status": mp.STATUS_PARTIAL if any_incomplete else mp.STATUS_OK,
        "query": username,
        "manager": manager,
        "season": season,
        "currentSeason": current_season,
        "window": window,
        "windowApplied": window_applied,
        "windowStart": int(start) if start is not None else None,
        "scope": scope,
        "leagueFilter": str(league_id) if league_id else None,
        "leagueFilterUnmatched": league_filter_unmatched,
        "packageModel": package_model.receipt(),
        "hasBoard": pricer.has_board,
        "coverage": {
            "leagues": coverage,
            "legsRequested": legs,
            "budgetExhausted": budget.refused > 0,
            "callsSpent": budget.spent,
            "callBudget": budget.limit,
            "truncated": truncated,
            "maxLeagues": max_leagues,
            "excluded": dict(asm.excluded),
        },
        "leagues": [lg.entry() for lg in ctx],
        "trades": trades,
        "acquisitions": acquisitions,
        "feed": feed,
        "playerSummary": summary,
        "analytics": analytics,
        "draftCapital": draft_capital,
        "tendencies": tendencies,
        "valueBasis": {
            "field": "rankDerivedValue",
            "board": "canonical Superflex / TE-premium board",
            "note": (
                "Current values are the canonical board's (a Superflex / TE-premium "
                "board) whatever the league's own format. Picks are valued at their "
                "generic season + round grade; a pick already spent in its draft has "
                "no current value."
            ),
        },
        "fetchedAt": int(t_now * 1000),
    }


# ── per-process payload memo ────────────────────────────────────────────

_payload_cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
_payload_lock = threading.Lock()


def cached_manager_activity(
    username: str,
    *,
    contract: dict[str, Any] | None,
    window: str = DEFAULT_WINDOW,
    season: str | None = None,
    league_id: str | None = None,
    scope: str = mp.SCOPE_DYNASTY,
    now: Callable[[], float] = time.time,
    **kwargs: Any,
) -> dict[str, Any]:
    """:func:`build_manager_activity` memoised for ``PAYLOAD_TTL_SECONDS``.

    Only ``ok`` answers are memoised (a partial or failed answer must let the
    next request retry).  Keyed by the case-folded username (Sleeper usernames
    are unique under case-folding), window, season, league and scope.
    """
    key = (
        str(username).strip().lower(),
        window,
        str(season or ""),
        str(league_id or ""),
        scope,
    )
    t = now()
    with _payload_lock:
        hit = _payload_cache.get(key)
        if hit and t - hit[0] < PAYLOAD_TTL_SECONDS:
            return {**hit[1], "cached": True}
    payload = build_manager_activity(
        username,
        contract=contract,
        window=window,
        season=season,
        league_id=league_id,
        scope=scope,
        now=now,
        **kwargs,
    )
    if payload.get("status") == mp.STATUS_OK:
        with _payload_lock:
            mp.drop_expired_payloads_locked(_payload_cache, t, PAYLOAD_TTL_SECONDS)
            if len(_payload_cache) >= _PAYLOAD_MAX_ENTRIES:
                oldest = min(_payload_cache, key=lambda k: _payload_cache[k][0])
                _payload_cache.pop(oldest, None)
            _payload_cache[key] = (t, payload)
    return {**payload, "cached": False}


def reset_caches() -> None:
    with _memo_lock:
        _memo.clear()
        _memo_last_sweep[0] = float("-inf")
    with _payload_lock:
        _payload_cache.clear()


__all__ = [
    "CALL_BUDGET",
    "WINDOWS",
    "build_manager_activity",
    "cached_manager_activity",
    "reset_caches",
]
