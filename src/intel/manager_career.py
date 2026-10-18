"""Manager Intelligence Batch E — career record and archetypes.

Workstream: ``docs/intel/MANAGER_INTELLIGENCE_WORKSTREAM.md`` → "Batch E".

Career record
    For one Sleeper username, every in-scope league they play in this season
    is walked back through its ``previous_league_id`` chain with the existing
    owner of that walk, ``sleeper_client.walk_league_chain_status`` (bounded:
    :data:`MAX_SEASONS_PER_LEAGUE` seasons per league, one call budget for
    the whole request).  For each season league the manager's roster is
    found by Sleeper user id (``owner_id`` or ``co_owners``) — Sleeper mints a
    new league id AND new roster ownership rows every season, so a season is
    the manager's only when that season's roster names them.  A season where
    they held no roster is ABSENT (listed as ``notHeldSeasons``), never a
    loss.

    Per season: the final regular-season record from the roster's own
    ``settings`` (wins / losses / ties / points — the Batch A
    ``manager_portfolio._record`` reader), the points-for share of the
    league, and the playoff finish from the ``winners_bracket`` through the
    public league's bracket helpers (``public_league.metrics``):
    ``champion`` / ``runner_up`` / ``playoff`` / ``missed``; ``unknown`` when
    the bracket could not be read (never "missed"); ``in_progress`` before
    the league is ``complete``.

    Recorded hand-offs in our own leagues (``public_league.ownership``)
    decide partial seasons: a manager who took a roster over mid-season, or
    left one, is shown for that season but the season is excluded from the
    totals (the roster record cannot be split by week without matchups).

    Totals — seasons, titles, playoff appearances, win %, points-for index —
    each carry the number of seasons they cover; only complete, fully-held
    seasons count.

Archetypes
    :func:`evaluate_archetypes` labels EVIDENCE, never fact.  Each archetype
    is a declared rule over blocks other batches already compute — B3
    ``tendencies`` and ``draftCapital.totals``, B2 acquisitions, the Batch A
    portfolio ``summary`` and the career totals above — with its threshold
    and minimum sample declared below as PRIOR constants (not fitted, not
    validated).  Below the minimum sample the archetype answers
    ``insufficient_sample``; with its source unread it answers
    ``unavailable``.  Any number of archetypes (or none) may be suggested.
    Statements read "evidence suggests …", never an accusation.

Nothing here fetches outside ``sleeper_client``'s classified fetchers, and
nothing here values an asset.  Bounded: ``CAREER_CALL_BUDGET`` Sleeper calls
per request (``budgetExhausted`` says when it ran out), a small thread pool,
and memoised season reads (completed seasons do not change).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from src.intel import manager_activity as ma
from src.intel import manager_portfolio as mp
from src.public_league import metrics as league_metrics
from src.public_league import ownership, sleeper_client
from src.sharp import roster_collect

Fetch = Callable[..., tuple[str, Any]]
Provider = Callable[..., dict[str, Any]]

#: Seasons walked per league (the current one included).  A bound, not a
#: retention window: a longer chain reports ``truncated``.
MAX_SEASONS_PER_LEAGUE = 6
#: Sleeper calls one career request may spend: per season one league object,
#: one roster list and (complete, held seasons only) one winners bracket.
CAREER_CALL_BUDGET = 360
DEFAULT_WORKERS = 6
PAYLOAD_TTL_SECONDS = 15 * 60
COMPLETED_SEASON_TTL_SECONDS = 6 * 60 * 60
_PAYLOAD_MAX_ENTRIES = 128

FINISH_CHAMPION = "champion"
FINISH_RUNNER_UP = "runner_up"
FINISH_PLAYOFF = "playoff"
FINISH_MISSED = "missed"
FINISH_UNKNOWN = "unknown"
FINISH_IN_PROGRESS = "in_progress"
FINISH_LEFT = "left_before_season_end"

HELD_FULL = "full"
HELD_FROM_WEEK = "from_week"
HELD_UNTIL_WEEK = "until_week"

EXCLUDED_IN_PROGRESS = "season_in_progress"
EXCLUDED_HANDOFF = "partial_season_handoff"

# ── archetype PRIORs (declared, not fitted or validated) ────────────────
#: Smallest samples an archetype needs before it is evaluated at all.
ARCHETYPE_MIN_TRADES = 5
ARCHETYPE_MIN_ACQUISITIONS = 8
#: Activity rates are per held league; one league's season is a sample (its
#: count is the evidence), none is not.
ARCHETYPE_MIN_LEAGUES = 1
ARCHETYPE_MIN_OWN_PICKS = 8
ARCHETYPE_MIN_AGE_KNOWN_PLAYERS = 25
ARCHETYPE_MIN_CAREER_SEASONS = 4
#: Thresholds.
ROOKIE_FOCUS_SHARE_MIN = 0.30  # rookies among non-draft player acquisitions
CONSOLIDATOR_SHARE_MIN = 0.50  # trades receiving fewer pieces than sent
DEPTH_BUILDER_SHARE_MIN = 0.50  # trades receiving more pieces than sent
PICK_HOARDER_RATIO_MIN = 1.50  # picks held / the manager's own picks
PICK_SELLER_RATIO_MAX = 0.50
ACTIVE_TRADER_PER_LEAGUE_MIN = 3.0  # trades per held league, season to date
WAIVER_ACTIVE_PER_LEAGUE_MIN = 8.0  # waiver + free-agent adds per held league
WIN_NOW_AGE_MIN = 26.5  # mean current age of the rostered players
WIN_NOW_PICK_RATIO_MAX = 1.0
REBUILD_AGE_MAX = 24.5
REBUILD_PICK_RATIO_MIN = 1.0
PLAYOFF_REGULAR_RATE_MIN = 0.60

STATE_SUGGESTED = "suggested"
STATE_NOT_SUGGESTED = "not_suggested"
STATE_INSUFFICIENT = "insufficient_sample"
STATE_UNAVAILABLE = "unavailable"


# ── season reads ────────────────────────────────────────────────────────


class _Reader:
    """Budgeted, memoised Sleeper reads for one career request."""

    def __init__(
        self,
        *,
        budget: ma._Budget,  # noqa: SLF001
        fetch_league: Fetch,
        fetch_rosters: Fetch,
        fetch_bracket: Fetch,
        known: dict[str, dict[str, Any]],
        now: float,
    ) -> None:
        self.budget = budget
        self._fetch_league = fetch_league
        self._fetch_rosters = fetch_rosters
        self._fetch_bracket = fetch_bracket
        self._known = known
        self.now = now

    def _read(
        self, fetch: Fetch, key: tuple[str, ...] | None, arg: str, ttl_of: Callable[[Any], float]
    ) -> tuple[str, Any]:
        if key is not None:
            hit = ma._memo_get(key, self.now)  # noqa: SLF001
            if hit is not None:
                return sleeper_client.FETCH_OK, hit
        if not self.budget.take():
            return ma.FETCH_BUDGET, None
        kind, payload = fetch(arg)
        if kind == sleeper_client.FETCH_OK and key is not None:
            ttl = ttl_of(payload)
            if ttl > 0:
                ma._memo_put(key, payload, ttl, self.now)  # noqa: SLF001
        return kind, payload

    def league(self, league_id: str) -> tuple[str, Any]:
        # The current season's league object came with the user's league list.
        if league_id in self._known:
            return sleeper_client.FETCH_OK, self._known[league_id]
        return self._read(
            self._fetch_league,
            ("league", league_id),
            league_id,
            lambda lg: COMPLETED_SEASON_TTL_SECONDS
            if isinstance(lg, dict) and lg.get("status") == "complete"
            else ma.WEEK_TTL_CURRENT_SECONDS,
        )

    def rosters(self, league_id: str, complete: bool) -> tuple[str, Any]:
        # Only a completed season's rosters are frozen enough to memoise.
        return self._read(
            self._fetch_rosters,
            ("career_rosters", league_id) if complete else None,
            league_id,
            lambda _p: COMPLETED_SEASON_TTL_SECONDS,
        )

    def bracket(self, league_id: str) -> tuple[str, Any]:
        return self._read(
            self._fetch_bracket,
            ("winners_bracket", league_id),
            league_id,
            lambda _p: COMPLETED_SEASON_TTL_SECONDS,
        )


def _cov(kind: str) -> str:
    return ma.COV_COMPLETE if kind == sleeper_client.FETCH_OK else ma._failed_state(kind)  # noqa: SLF001


def playoff_finish(
    bracket: list[dict[str, Any]] | None, roster_id: int | None
) -> tuple[str, str | None, bool | None]:
    """``(finish, reason, championshipDecided)`` for one roster of a
    COMPLETE season.  ``bracket`` ``None`` = not read → ``unknown``."""
    if bracket is None:
        return FINISH_UNKNOWN, "bracket_unavailable", None
    if not bracket:
        return FINISH_UNKNOWN, "bracket_empty", None
    if roster_id is None:
        return FINISH_UNKNOWN, "roster_unknown", None
    final = league_metrics.final_playoff_matchup(bracket)
    decided = final is not None and ma._int(final.get("w")) is not None  # noqa: SLF001
    placement = league_metrics.playoff_placement(bracket)
    place = placement.get(roster_id)
    if place == 1:
        return FINISH_CHAMPION, None, True
    if place == 2 and decided:
        return FINISH_RUNNER_UP, None, True
    if roster_id in set(league_metrics.playoff_teams(bracket)):
        return FINISH_PLAYOFF, None if decided else "championship_undecided", decided
    return FINISH_MISSED, None, decided


def _points_share(rosters: list[dict[str, Any]], mine: dict[str, Any]) -> tuple[Any, Any]:
    points = [mp._record(r)["pointsFor"] for r in rosters]  # noqa: SLF001
    own = mp._record(mine)["pointsFor"]  # noqa: SLF001
    if own is None or not points or any(p is None for p in points):
        return None, "points_unavailable"
    total = sum(points)
    if total <= 0:
        return None, "no_points_scored"
    return round(own / total, 4), None


def _handoffs_for(league_id: str) -> list[dict[str, Any]]:
    """Recorded hand-offs (``public_league.ownership``) in one season league."""
    return [c for c in ownership.all_changes() if c["leagueId"] == league_id]


def _season_row(
    league: dict[str, Any],
    chain_index: int,
    user_id: str,
    reader: _Reader,
    root_league_id: str,
) -> dict[str, Any] | None:
    """One season of one league, or ``None`` when the manager held no roster
    in it (absent — never a loss).  A failed read returns a row whose
    coverage says so (the season is then unknown, not absent)."""
    league_id = str(league.get("league_id") or "")
    complete = league.get("status") == "complete"
    base: dict[str, Any] = {
        "leagueId": league_id,
        "rootLeagueId": root_league_id,
        "leagueName": league.get("name") or None,
        "season": str(league.get("season") or "") or None,
        "leagueStatus": league.get("status") or None,
        "chainIndex": chain_index,
        "seasonComplete": complete,
        "teams": ma._int(league.get("total_rosters")),  # noqa: SLF001
        "format": roster_collect.league_format(league),
    }
    kind, rosters = reader.rosters(league_id, complete)
    if kind != sleeper_client.FETCH_OK:
        return {
            **base,
            "held": None,
            "coverage": {"rosters": _cov(kind), "bracket": ma.COV_NONE},
            "coverageState": _cov(kind),
            "countsTowardTotals": False,
            "excludedReason": "rosters_unread",
        }
    rosters = [r for r in rosters or [] if isinstance(r, dict)]
    roster, co_owned = mp._roster_for_user(rosters, user_id)  # noqa: SLF001
    changes = _handoffs_for(league_id)
    held = HELD_FULL
    week: int | None = None
    if roster is not None:
        rid = ma._int(roster.get("roster_id"))  # noqa: SLF001
        joined = [c for c in changes if c["rosterId"] == rid and c["toOwnerId"] == user_id]
        if joined:
            held, week = HELD_FROM_WEEK, joined[-1]["effectiveWeek"]
    else:
        left = [c for c in changes if c["fromOwnerId"] == user_id]
        if not left:
            return None
        rid = left[0]["rosterId"]
        held, week = HELD_UNTIL_WEEK, left[0]["effectiveWeek"]
        roster = next((r for r in rosters if ma._int(r.get("roster_id")) == rid), None)  # noqa: SLF001
        if roster is None:
            return None
    share, share_reason = _points_share(rosters, roster)
    row = {
        **base,
        "rosterId": rid,
        "coOwned": co_owned,
        "held": held,
        # First week the manager was responsible / first week they were not.
        "heldFromWeek": week if held == HELD_FROM_WEEK else None,
        "heldUntilWeek": week if held == HELD_UNTIL_WEEK else None,
        "record": mp._record(roster),  # noqa: SLF001
        "pointsForShare": share,
        "pointsForShareReason": share_reason,
        "finish": None,
        "finishReason": None,
        "championshipDecided": None,
    }
    bracket_cov = ma.COV_NONE
    if held == HELD_UNTIL_WEEK:
        row["finish"], row["finishReason"] = None, FINISH_LEFT
    elif not complete:
        row["finish"] = FINISH_IN_PROGRESS
    else:
        bkind, bracket = reader.bracket(league_id)
        bracket_cov = _cov(bkind)
        finish, reason, decided = playoff_finish(
            [m for m in bracket if isinstance(m, dict)]
            if bkind == sleeper_client.FETCH_OK
            else None,
            rid,
        )
        if bkind != sleeper_client.FETCH_OK:
            reason = {
                ma.COV_RATE_LIMITED: "bracket_rate_limited",
                ma.COV_NONE: "bracket_budget_exhausted",
            }.get(bracket_cov, "bracket_unavailable")
        row.update({"finish": finish, "finishReason": reason, "championshipDecided": decided})
    if not complete:
        excluded = EXCLUDED_IN_PROGRESS
    elif held != HELD_FULL:
        excluded = EXCLUDED_HANDOFF
    else:
        excluded = None
    row["countsTowardTotals"] = excluded is None
    row["excludedReason"] = excluded
    row["coverage"] = {"rosters": ma.COV_COMPLETE, "bracket": bracket_cov}
    needs_bracket = complete and held != HELD_UNTIL_WEEK
    row["coverageState"] = (
        ma.COV_COMPLETE if not needs_bracket or bracket_cov == ma.COV_COMPLETE else ma.COV_PARTIAL
    )
    return row


def _league_career(
    league: dict[str, Any], user_id: str, reader: _Reader, max_seasons: int
) -> dict[str, Any]:
    league_id = str(league.get("league_id") or "")
    chain, chain_cov = sleeper_client.walk_league_chain_status(
        league_id, max_seasons, fetch_league_fn=reader.league
    )
    seasons: list[dict[str, Any]] = []
    not_held: list[str | None] = []
    for i, season_league in enumerate(chain):
        row = _season_row(season_league, i, user_id, reader, league_id)
        if row is None:
            not_held.append(str(season_league.get("season") or "") or None)
        else:
            seasons.append(row)
    return {
        "leagueId": league_id,
        "name": league.get("name") or None,
        "scope": mp.league_scope(league),
        "format": roster_collect.league_format(league),
        "chain": chain_cov,
        "seasonsWalked": len(chain),
        "seasons": seasons,
        "seasonsHeld": sum(1 for s in seasons if s.get("held")),
        "notHeldSeasons": not_held,
    }


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def career_totals(seasons: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over the seasons that count (complete, held all season), each
    with the number of seasons it covers.  ``seasons`` are season rows; a row
    whose roster could not be read (``held: None``) is not a season held.
    Pure."""
    rows = [s for s in seasons if s.get("held")]
    counted = [s for s in rows if s.get("countsTowardTotals")]
    finish_known = [
        s
        for s in counted
        if s.get("finish") in (FINISH_CHAMPION, FINISH_RUNNER_UP, FINISH_PLAYOFF, FINISH_MISSED)
    ]
    title_known = [
        s
        for s in finish_known
        if s.get("championshipDecided") or s["finish"] in (FINISH_CHAMPION, FINISH_RUNNER_UP)
    ]
    playoffs = [
        s
        for s in finish_known
        if s["finish"] in (FINISH_CHAMPION, FINISH_RUNNER_UP, FINISH_PLAYOFF)
    ]
    wins = losses = ties = 0
    record_seasons = 0
    for s in counted:
        rec = s.get("record") or {}
        w, lo, t = rec.get("wins"), rec.get("losses"), rec.get("ties")
        # A record missing any of its three counts is not a record.
        if w is None or lo is None or t is None or (w + lo + t) == 0:
            continue
        wins, losses, ties = wins + w, losses + lo, ties + t
        record_seasons += 1
    games = wins + losses + ties
    shares = [
        (s["pointsForShare"], s["teams"])
        for s in counted
        if s.get("pointsForShare") is not None and s.get("teams")
    ]
    excluded: dict[str, int] = {}
    for s in rows:
        if s.get("excludedReason"):
            excluded[s["excludedReason"]] = excluded.get(s["excludedReason"], 0) + 1
    return {
        "seasons": len(rows),
        "countedSeasons": len(counted),
        "distinctYears": len({s["season"] for s in rows if s.get("season")}),
        "leagues": len({s.get("rootLeagueId") for s in rows}),
        "titles": {
            "count": sum(1 for s in title_known if s["finish"] == FINISH_CHAMPION),
            "seasonsCovered": len(title_known),
        },
        "runnerUps": {
            "count": sum(1 for s in title_known if s["finish"] == FINISH_RUNNER_UP),
            "seasonsCovered": len(title_known),
        },
        "playoffAppearances": {
            "count": len(playoffs),
            "seasonsCovered": len(finish_known),
            "rate": _rate(len(playoffs), len(finish_known)),
        },
        "record": {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "games": games,
            "winPct": round((wins + ties * 0.5) / games, 4) if games else None,
            "seasonsCovered": record_seasons,
        },
        # Share of the league's regular-season points; the index scales it by
        # league size so 1.0 is the league average whatever the team count.
        "pointsForShare": {
            "mean": round(sum(sh for sh, _t in shares) / len(shares), 4) if shares else None,
            "seasonsCovered": len(shares),
        },
        "pointsForIndex": {
            "mean": round(sum(sh * t for sh, t in shares) / len(shares), 3) if shares else None,
            "seasonsCovered": len(shares),
            "definition": "points-for share x teams in the league; 1.0 = league average",
        },
        "excluded": excluded,
        "unknownFinishes": sum(1 for s in counted if s.get("finish") == FINISH_UNKNOWN),
    }


# ── archetypes ──────────────────────────────────────────────────────────


def _prior(name: str, value: Any) -> dict[str, Any]:
    return {"name": name, "value": value, "basis": "PRIOR"}


def _archetype(
    key: str,
    label: str,
    *,
    rule: str,
    source: str,
    threshold: dict[str, Any],
    min_sample: dict[str, Any],
    sample: int | None,
    evidence: dict[str, Any] | None,
    met: bool | None,
    suggests: str,
    not_met: str,
    sample_unit: str,
    unavailable_reason: str | None = None,
    evidence_complete: bool = True,
) -> dict[str, Any]:
    if unavailable_reason is not None:
        state, statement = STATE_UNAVAILABLE, f"Not evaluated: {unavailable_reason}."
    elif sample is None or sample < min_sample["value"]:
        state = STATE_INSUFFICIENT
        statement = (
            f"Insufficient sample: {sample or 0} {sample_unit} "
            f"(needs at least {min_sample['value']})."
        )
    elif met:
        state, statement = STATE_SUGGESTED, f"Evidence suggests {suggests}."
    else:
        state, statement = STATE_NOT_SUGGESTED, f"Not indicated: {not_met}."
    return {
        "key": key,
        "label": label,
        "state": state,
        "statement": statement,
        "rule": rule,
        "source": source,
        "threshold": threshold,
        "minSample": min_sample,
        "sampleSize": sample,
        "sampleUnit": sample_unit,
        "evidence": evidence,
        "evidenceComplete": evidence_complete,
        "unavailableReason": unavailable_reason,
    }


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{round(x * 100)}%"


def evaluate_archetypes(
    *,
    profile: dict[str, Any] | None,
    activity: dict[str, Any] | None,
    career: dict[str, Any] | None,
) -> dict[str, Any]:
    """Archetypes as labelled evidence over existing blocks (see module doc).

    ``profile`` is the Batch A payload, ``activity`` the B1-B3 payload read
    with ``window="season"``, ``career`` :func:`career_totals` output.  Any
    of them may be ``None`` (not read), which makes the archetypes that need
    it ``unavailable``.  Pure.
    """
    act_ok = bool(activity) and activity.get("status") in (mp.STATUS_OK, mp.STATUS_PARTIAL)
    prof_ok = bool(profile) and profile.get("status") in (mp.STATUS_OK, mp.STATUS_PARTIAL)
    act_complete = act_ok and activity.get("status") == mp.STATUS_OK
    prof_complete = prof_ok and profile.get("status") == mp.STATUS_OK
    no_act = None if act_ok else "the season's activity could not be read"
    no_prof = None if prof_ok else "the portfolio could not be read"
    items: list[dict[str, Any]] = []

    tend = (activity or {}).get("tendencies") or {} if act_ok else {}
    trades_n = tend.get("tradeCount") if act_ok else None
    pieces = ((tend.get("pieces") or {}).get("counts")) or {}

    # Rookie-focused: rookies among non-draft player acquisitions.
    acqs = (activity or {}).get("acquisitions") or [] if act_ok else []
    non_draft = [a for a in acqs if a.get("method") in ("TRADE", "WAIVER", "FREE_AGENT")]
    rookies = sum(1 for a in non_draft if (a.get("player") or {}).get("isRookie"))
    share = _rate(rookies, len(non_draft))
    items.append(
        _archetype(
            "rookie_focused",
            "Rookie-focused",
            rule="rookies / non-draft player acquisitions this season ≥ threshold",
            source="acquisitions (trade, waiver, free agent; season window)",
            threshold=_prior("ROOKIE_FOCUS_SHARE_MIN", ROOKIE_FOCUS_SHARE_MIN),
            min_sample=_prior("ARCHETYPE_MIN_ACQUISITIONS", ARCHETYPE_MIN_ACQUISITIONS),
            sample=len(non_draft) if act_ok else None,
            evidence={"rookies": rookies, "nonDraftAcquisitions": len(non_draft), "share": share},
            met=share is not None and share >= ROOKIE_FOCUS_SHARE_MIN,
            suggests=(
                f"a rookie focus: {rookies} of {len(non_draft)} players acquired outside "
                f"the draft this season were rookies ({_pct(share)})"
            ),
            not_met=(
                f"{rookies} of {len(non_draft)} non-draft acquisitions were rookies ({_pct(share)})"
            ),
            sample_unit="non-draft acquisitions",
            unavailable_reason=no_act,
            evidence_complete=act_complete,
        )
    )

    # Consolidator / depth builder: trade shape by pieces.
    for key, label, count_key, name, thr, verb in (
        (
            "consolidator",
            "Consolidator",
            "consolidation",
            "CONSOLIDATOR_SHARE_MIN",
            CONSOLIDATOR_SHARE_MIN,
            "fewer",
        ),
        (
            "depth_builder",
            "Depth builder",
            "depth",
            "DEPTH_BUILDER_SHARE_MIN",
            DEPTH_BUILDER_SHARE_MIN,
            "more",
        ),
    ):
        n_hit = int(pieces.get(count_key) or 0)
        sh = _rate(n_hit, trades_n or 0)
        items.append(
            _archetype(
                key,
                label,
                rule=f"trades receiving {verb} pieces than sent / trades this season ≥ threshold",
                source="tendencies.pieces (season window)",
                threshold=_prior(name, thr),
                min_sample=_prior("ARCHETYPE_MIN_TRADES", ARCHETYPE_MIN_TRADES),
                sample=trades_n,
                evidence={"matching": n_hit, "trades": trades_n, "share": sh},
                met=sh is not None and sh >= thr,
                suggests=(
                    f"a {label.lower()}: {n_hit} of {trades_n} trades this season brought "
                    f"back {verb} pieces than were sent ({_pct(sh)})"
                ),
                not_met=f"{n_hit} of {trades_n} trades brought back {verb} pieces ({_pct(sh)})",
                sample_unit="trades",
                unavailable_reason=no_act,
                evidence_complete=act_complete,
            )
        )

    # Pick hoarder / seller: picks held against the manager's own picks.
    dc = (activity or {}).get("draftCapital") or {} if act_ok else {}
    totals = dc.get("totals") if dc.get("available") else None
    dc_unavailable = no_act or (
        None if totals is not None else "draft capital is only read for the current season"
    )
    held = (totals or {}).get("picksHeld")
    own = None
    ratio = None
    if totals is not None:
        own = (totals["picksHeld"] - totals["acquiredHeld"]) + totals["ownTradedAway"]
        ratio = round(held / own, 3) if own else None
    pick_evidence = {
        "picksHeld": held,
        "acquiredHeld": (totals or {}).get("acquiredHeld"),
        "ownTradedAway": (totals or {}).get("ownTradedAway"),
        "ownPicks": own,
        "ratio": ratio,
        "leaguesObserved": (totals or {}).get("leaguesObserved"),
        "leaguesUnavailable": (totals or {}).get("leaguesUnavailable"),
    }
    dc_complete = act_complete and not (totals or {}).get("leaguesUnavailable")
    items.append(
        _archetype(
            "pick_hoarder",
            "Pick hoarder",
            rule="picks held / own picks (held + traded away) ≥ threshold",
            source="draftCapital.totals (picks held now)",
            threshold=_prior("PICK_HOARDER_RATIO_MIN", PICK_HOARDER_RATIO_MIN),
            min_sample=_prior("ARCHETYPE_MIN_OWN_PICKS", ARCHETYPE_MIN_OWN_PICKS),
            sample=own,
            evidence=pick_evidence,
            met=ratio is not None and ratio >= PICK_HOARDER_RATIO_MIN,
            suggests=(
                f"pick accumulation: {held} picks held against {own} of their own "
                f"(ratio {ratio})"
            ),
            not_met=f"{held} picks held against {own} of their own (ratio {ratio})",
            sample_unit="own picks",
            unavailable_reason=dc_unavailable,
            evidence_complete=dc_complete,
        )
    )
    items.append(
        _archetype(
            "pick_seller",
            "Pick seller",
            rule="picks held / own picks (held + traded away) ≤ threshold",
            source="draftCapital.totals (picks held now)",
            threshold=_prior("PICK_SELLER_RATIO_MAX", PICK_SELLER_RATIO_MAX),
            min_sample=_prior("ARCHETYPE_MIN_OWN_PICKS", ARCHETYPE_MIN_OWN_PICKS),
            sample=own,
            evidence=pick_evidence,
            met=ratio is not None and ratio <= PICK_SELLER_RATIO_MAX,
            suggests=(
                f"picks are traded away: {held} picks held against {own} of their own "
                f"(ratio {ratio})"
            ),
            not_met=f"{held} picks held against {own} of their own (ratio {ratio})",
            sample_unit="own picks",
            unavailable_reason=dc_unavailable,
            evidence_complete=dc_complete,
        )
    )

    # Activity per held league (season to date).
    cov_leagues = ((activity or {}).get("coverage") or {}).get("leagues") or [] if act_ok else []
    held_leagues = sum(1 for c in cov_leagues if c.get("rosterHeld"))
    per_trades = round(trades_n / held_leagues, 2) if act_ok and held_leagues else None
    items.append(
        _archetype(
            "active_trader",
            "Active trader",
            rule="completed trades per held league this season ≥ threshold",
            source="tendencies.tradeCount + coverage (season window)",
            threshold=_prior("ACTIVE_TRADER_PER_LEAGUE_MIN", ACTIVE_TRADER_PER_LEAGUE_MIN),
            min_sample=_prior("ARCHETYPE_MIN_LEAGUES", ARCHETYPE_MIN_LEAGUES),
            sample=held_leagues if act_ok else None,
            evidence={"trades": trades_n, "leagues": held_leagues, "perLeague": per_trades},
            met=per_trades is not None and per_trades >= ACTIVE_TRADER_PER_LEAGUE_MIN,
            suggests=(
                f"an active trader: {trades_n} trades across {held_leagues} leagues this "
                f"season ({per_trades} per league)"
            ),
            not_met=f"{trades_n} trades across {held_leagues} leagues ({per_trades} per league)",
            sample_unit="leagues",
            unavailable_reason=no_act,
            evidence_complete=act_complete,
        )
    )
    by_method = ((activity or {}).get("analytics") or {}).get("byMethod") or {} if act_ok else {}
    adds = int(by_method.get("WAIVER") or 0) + int(by_method.get("FREE_AGENT") or 0)
    per_adds = round(adds / held_leagues, 2) if act_ok and held_leagues else None
    items.append(
        _archetype(
            "waiver_active",
            "Waiver-active",
            rule="waiver + free-agent adds per held league this season ≥ threshold",
            source="analytics.byMethod + coverage (season window)",
            threshold=_prior("WAIVER_ACTIVE_PER_LEAGUE_MIN", WAIVER_ACTIVE_PER_LEAGUE_MIN),
            min_sample=_prior("ARCHETYPE_MIN_LEAGUES", ARCHETYPE_MIN_LEAGUES),
            sample=held_leagues if act_ok else None,
            evidence={"adds": adds, "leagues": held_leagues, "perLeague": per_adds},
            met=per_adds is not None and per_adds >= WAIVER_ACTIVE_PER_LEAGUE_MIN,
            suggests=(
                f"heavy waiver use: {adds} waiver and free-agent adds across {held_leagues} "
                f"leagues this season ({per_adds} per league)"
            ),
            not_met=f"{adds} waiver and free-agent adds across {held_leagues} leagues",
            sample_unit="leagues",
            unavailable_reason=no_act,
            evidence_complete=act_complete,
        )
    )

    # Win-now / rebuilding: roster age AND pick holdings.
    summary = (profile or {}).get("summary") or {} if prof_ok else {}
    age_mean = summary.get("ageMean")
    age_n = summary.get("ageKnownPlayers") if prof_ok else None
    phase_unavailable = no_prof or (
        dc_unavailable and f"pick holdings unavailable ({dc_unavailable})"
    )
    phase_evidence = {
        "ageMean": age_mean,
        "ageKnownPlayers": age_n,
        "pickRatio": ratio,
        "ownPicks": own,
    }
    phase_sample = age_n if own is not None and own >= ARCHETYPE_MIN_OWN_PICKS else None
    items.append(
        _archetype(
            "win_now",
            "Win-now",
            rule="mean roster age ≥ age threshold AND picks held / own picks ≤ ratio threshold",
            source="portfolio summary (ageMean) + draftCapital.totals",
            threshold={
                **_prior("WIN_NOW_AGE_MIN", WIN_NOW_AGE_MIN),
                "and": _prior("WIN_NOW_PICK_RATIO_MAX", WIN_NOW_PICK_RATIO_MAX),
            },
            min_sample=_prior("ARCHETYPE_MIN_AGE_KNOWN_PLAYERS", ARCHETYPE_MIN_AGE_KNOWN_PLAYERS),
            sample=phase_sample,
            evidence=phase_evidence,
            met=age_mean is not None
            and ratio is not None
            and age_mean >= WIN_NOW_AGE_MIN
            and ratio <= WIN_NOW_PICK_RATIO_MAX,
            suggests=(
                f"a win-now posture: rostered players average {age_mean} years and "
                f"{held} picks are held against {own} of their own"
            ),
            not_met=f"mean roster age {age_mean}; pick ratio {ratio}",
            sample_unit="players with a known age (and own picks ≥ " f"{ARCHETYPE_MIN_OWN_PICKS})",
            unavailable_reason=phase_unavailable,
            evidence_complete=prof_complete and dc_complete,
        )
    )
    items.append(
        _archetype(
            "rebuilding",
            "Rebuilding",
            rule="mean roster age ≤ age threshold AND picks held / own picks ≥ ratio threshold",
            source="portfolio summary (ageMean) + draftCapital.totals",
            threshold={
                **_prior("REBUILD_AGE_MAX", REBUILD_AGE_MAX),
                "and": _prior("REBUILD_PICK_RATIO_MIN", REBUILD_PICK_RATIO_MIN),
            },
            min_sample=_prior("ARCHETYPE_MIN_AGE_KNOWN_PLAYERS", ARCHETYPE_MIN_AGE_KNOWN_PLAYERS),
            sample=phase_sample,
            evidence=phase_evidence,
            met=age_mean is not None
            and ratio is not None
            and age_mean <= REBUILD_AGE_MAX
            and ratio >= REBUILD_PICK_RATIO_MIN,
            suggests=(
                f"a rebuilding posture: rostered players average {age_mean} years and "
                f"{held} picks are held against {own} of their own"
            ),
            not_met=f"mean roster age {age_mean}; pick ratio {ratio}",
            sample_unit="players with a known age (and own picks ≥ " f"{ARCHETYPE_MIN_OWN_PICKS})",
            unavailable_reason=phase_unavailable,
            evidence_complete=prof_complete and dc_complete,
        )
    )

    # Playoff regular: career playoff rate.
    po = (career or {}).get("playoffAppearances") or {}
    covered = po.get("seasonsCovered") if career is not None else None
    rate = po.get("rate")
    items.append(
        _archetype(
            "playoff_regular",
            "Playoff regular",
            rule="playoff appearances / complete seasons with a known finish ≥ threshold",
            source="career totals",
            threshold=_prior("PLAYOFF_REGULAR_RATE_MIN", PLAYOFF_REGULAR_RATE_MIN),
            min_sample=_prior("ARCHETYPE_MIN_CAREER_SEASONS", ARCHETYPE_MIN_CAREER_SEASONS),
            sample=covered,
            evidence={"playoffAppearances": po.get("count"), "seasons": covered, "rate": rate},
            met=rate is not None and rate >= PLAYOFF_REGULAR_RATE_MIN,
            suggests=(
                f"a regular contender: playoffs in {po.get('count')} of {covered} complete "
                f"seasons ({_pct(rate)})"
            ),
            not_met=f"playoffs in {po.get('count')} of {covered} complete seasons ({_pct(rate)})",
            sample_unit="complete seasons",
            unavailable_reason=None if career is not None else "the career could not be read",
        )
    )

    return {
        "basis": (
            "Labelled evidence, not fact: each archetype is a declared rule over counts "
            "this page already shows, with its threshold and minimum sample declared as a "
            "PRIOR (not fitted or validated). Below the minimum sample nothing is suggested."
        ),
        "window": "season",
        "items": items,
        "suggested": [i["key"] for i in items if i["state"] == STATE_SUGGESTED],
        "sources": {
            "activity": (activity or {}).get("status") if activity else None,
            "profile": (profile or {}).get("status") if profile else None,
            "career": career is not None,
        },
    }


# ── payload ─────────────────────────────────────────────────────────────


def _status_payload(status: str, username: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "query": username, **extra}


def _safe(provider: Provider | None, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
    if provider is None:
        return None
    try:
        return provider(*args, **kwargs)
    except Exception:  # noqa: BLE001 — an unread source makes its archetypes unavailable
        return None


def build_manager_career(
    username: str,
    *,
    contract: dict[str, Any] | None = None,
    scope: str = mp.SCOPE_DYNASTY,
    max_leagues: int = mp.DEFAULT_MAX_LEAGUES,
    max_seasons: int = MAX_SEASONS_PER_LEAGUE,
    call_budget: int = CAREER_CALL_BUDGET,
    workers: int = DEFAULT_WORKERS,
    include_archetypes: bool = True,
    profile_payload: dict[str, Any] | None = None,
    activity_payload: dict[str, Any] | None = None,
    profile_provider: Provider | None = None,
    activity_provider: Provider | None = None,
    fetch_user: Fetch = sleeper_client.fetch_user_classified,
    fetch_leagues: Fetch = sleeper_client.fetch_user_leagues_classified,
    fetch_league: Fetch = sleeper_client.fetch_league_classified,
    fetch_rosters: Fetch = sleeper_client.fetch_rosters_classified,
    fetch_bracket: Fetch = sleeper_client.fetch_winners_bracket_classified,
    fetch_state: Callable[[], Any] = sleeper_client.fetch_nfl_state,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """The career payload for one username (see the module docstring).

    ``status``: ``ok`` / ``partial`` (some league x season not fully read,
    a chain not walked to its start, or the budget ran out) / ``not_found``
    / ``rate_limited`` / ``upstream_unavailable``.  Never raises for an
    upstream failure.  ``profile_payload`` / ``activity_payload`` reuse
    payloads the caller already holds (the comparison view); otherwise the
    providers (``None`` = archetypes from that source unavailable) are asked.
    """
    if scope not in mp.SCOPES:
        scope = mp.SCOPE_DYNASTY
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
    season = str(state.get("league_season") or state.get("season") or time.gmtime(t_now).tm_year)
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
    in_scope = sorted(
        (lg for lg in leagues if mp.league_scope(lg) == scope),
        key=lambda lg: str(lg.get("name") or ""),
    )
    truncated = len(in_scope) > max_leagues
    in_scope = in_scope[:max_leagues]

    budget = ma._Budget(call_budget)  # noqa: SLF001
    reader = _Reader(
        budget=budget,
        fetch_league=fetch_league,
        fetch_rosters=fetch_rosters,
        fetch_bracket=fetch_bracket,
        known={str(lg["league_id"]): lg for lg in in_scope},
        now=t_now,
    )
    pool_size = max(1, min(workers, max(1, len(in_scope))))
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        per_league = list(
            pool.map(lambda lg: _league_career(lg, user_id, reader, max_seasons), in_scope)
        )

    seasons = sorted(
        (s for lg in per_league for s in lg.pop("seasons")),
        key=lambda s: (-(ma._int(s.get("season")) or 0), s.get("leagueName") or ""),  # noqa: SLF001
    )
    totals = career_totals(seasons)
    coverage_rows = [
        {
            "leagueId": s["leagueId"],
            "leagueName": s.get("leagueName"),
            "season": s.get("season"),
            "state": s["coverageState"],
            "rosters": s["coverage"]["rosters"],
            "bracket": s["coverage"]["bracket"],
        }
        for s in seasons
    ]
    chain_incomplete = [
        lg["leagueId"]
        for lg in per_league
        if lg["chain"]["state"] == sleeper_client.CHAIN_UNVERIFIED
    ]
    # The season bound is by design: reported, not a failure.
    chain_truncated = [
        lg["leagueId"]
        for lg in per_league
        if lg["chain"]["state"] == sleeper_client.CHAIN_TRUNCATED
    ]
    incomplete = (
        budget.refused > 0
        or bool(chain_incomplete)
        or any(r["state"] != ma.COV_COMPLETE for r in coverage_rows)
    )

    archetypes = None
    if include_archetypes:
        profile = profile_payload or _safe(
            profile_provider, username, contract=contract, scope=scope
        )
        activity = activity_payload or _safe(
            activity_provider, username, contract=contract, window="season", scope=scope
        )
        archetypes = evaluate_archetypes(profile=profile, activity=activity, career=totals)

    return {
        "status": mp.STATUS_PARTIAL if incomplete else mp.STATUS_OK,
        "query": username,
        "manager": manager,
        "season": season,
        "scope": scope,
        "leagues": per_league,
        "seasons": seasons,
        "totals": totals,
        "archetypes": archetypes,
        "coverage": {
            "seasons": coverage_rows,
            "chainsIncomplete": chain_incomplete,
            "chainsTruncated": chain_truncated,
            "budgetExhausted": budget.refused > 0,
            "callsSpent": budget.spent,
            "callBudget": budget.limit,
            "maxSeasonsPerLeague": max_seasons,
            "truncated": truncated,
            "maxLeagues": max_leagues,
            "leaguesInScope": len(in_scope),
        },
        "basis": {
            "record": "regular-season record from each season's roster settings",
            "finish": "playoff finish from that season's winners bracket; unknown when unread",
            "attribution": (
                "a season counts only when that season's roster names this Sleeper user "
                "(owner or co-owner); a season without one is absent, not a loss; a "
                "recorded mid-season hand-off shows the season but leaves it out of totals"
            ),
            "totals": "complete seasons held all season only",
        },
        "fetchedAt": int(t_now * 1000),
    }


# ── per-process payload memo ────────────────────────────────────────────

_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def cached_manager_career(
    username: str,
    *,
    contract: dict[str, Any] | None = None,
    scope: str = mp.SCOPE_DYNASTY,
    now: Callable[[], float] = time.time,
    **kwargs: Any,
) -> dict[str, Any]:
    """:func:`build_manager_career` memoised for ``PAYLOAD_TTL_SECONDS``;
    only ``ok`` answers are memoised so a partial or failed one retries."""
    key = (str(username).strip().lower(), scope)
    t = now()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and t - hit[0] < PAYLOAD_TTL_SECONDS:
            return {**hit[1], "cached": True}
    kwargs.setdefault("profile_provider", mp.cached_manager_profile)
    kwargs.setdefault("activity_provider", ma.cached_manager_activity)
    payload = build_manager_career(username, contract=contract, scope=scope, now=now, **kwargs)
    if payload.get("status") == mp.STATUS_OK:
        with _cache_lock:
            if len(_cache) >= _PAYLOAD_MAX_ENTRIES:
                oldest = min(_cache, key=lambda k: _cache[k][0])
                _cache.pop(oldest, None)
            _cache[key] = (t, payload)
    return {**payload, "cached": False}


def reset_cache() -> None:
    with _cache_lock:
        _cache.clear()


__all__ = [
    "CAREER_CALL_BUDGET",
    "MAX_SEASONS_PER_LEAGUE",
    "build_manager_career",
    "cached_manager_career",
    "career_totals",
    "evaluate_archetypes",
    "playoff_finish",
    "reset_cache",
]
