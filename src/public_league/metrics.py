"""Shared metric helpers for the public league sections.

Keeping these helpers in one module means every section shares the
same regular-season / playoff partitioning, the same roster→owner
attribution, and the same pre-week standings reconstruction so
results stay consistent across cards.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .identity import ManagerRegistry
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


# ── Matchup helpers ────────────────────────────────────────────────────────
def matchup_pairs(
    week_entries: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Group a week's matchup rows into (home, away) pairs by matchup_id.

    The ordering within a pair is stable — we sort by ``roster_id`` so
    the two sides are deterministic for every downstream consumer.
    """
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for m in week_entries:
        mid = m.get("matchup_id")
        if mid is None:
            continue
        groups[mid].append(m)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for entries in groups.values():
        if len(entries) != 2:
            continue
        entries.sort(key=lambda e: int(e.get("roster_id") or 0))
        pairs.append((entries[0], entries[1]))
    return pairs


def matchup_margin(a: dict[str, Any], b: dict[str, Any]) -> float:
    return float(a.get("points") or 0.0) - float(b.get("points") or 0.0)


def matchup_points(entry: dict[str, Any]) -> float:
    return float(entry.get("points") or 0.0)


def roster_id_of(entry: dict[str, Any]) -> int | None:
    try:
        return int(entry.get("roster_id"))
    except (TypeError, ValueError):
        return None


def is_scored(entry: dict[str, Any]) -> bool:
    """True if Sleeper has a non-zero score for the roster-week."""
    return matchup_points(entry) > 0


def scored_weeks(matchups_by_week: dict[int, list[dict[str, Any]]]) -> list[int]:
    """Weeks that have at least one real (non-placeholder) scored entry.

    Sleeper pre-generates ``matchup_id`` for the WHOLE season's schedule
    at draft time and stubs ``players_points``/``starters`` for every
    future week too — a frozen echo of the roster's *current* starting
    lineup at ``0.0`` for every rostered player, not just starters, not
    that week's actual (not-yet-decided) lineup.  So ``matchup_id`` or
    ``starters`` presence alone cannot tell a played week from a merely
    scheduled one (confirmed live, 2026-09-15: weeks 2-18 of an
    in-progress week-2 season all carry populated ``matchup_id`` and a
    full ``players_points`` stub, entirely at 0.0).

    What this does NOT tell you is whether a week has FINISHED scoring.
    An earlier version of this docstring claimed "Sleeper scores every
    roster in a league-week simultaneously, so a week is either fully
    real or fully a placeholder".  That is false, and it is measurable:
    on 2026-09-19, mid-week-2 of ``dynasty_main``, the week carried 12
    entries of which 8 had live Thursday-night scores and 4 sat at a
    literal ``0.0`` because those rosters had nobody playing Thursday.
    A per-entry check reads that week as partly real, which is how an
    in-progress week came to be averaged in as a completed game.

    So: this answers "has anything been scored", which is the right
    question for "does this week exist yet".  For AGGREGATION over
    completed weeks — averages, per-game rates, form windows — call
    ``final_regular_season_weeks`` instead.  This remains the ONE
    canonical place deciding the former; do not re-derive it elsewhere.

    Known follow-up: ``awards.py`` builds VORP, starter totals and
    replacement pools on this helper, so those figures still drift
    while a week is in progress.  Tracked separately — changing this
    function's behaviour would move award outputs.
    """
    return sorted(
        wk for wk, entries in matchups_by_week.items() if any(is_scored(e) for e in entries)
    )


def last_scored_week(season: SeasonSnapshot) -> int | None:
    """Sleeper's own answer to "which week have you finished scoring?".

    Reads ``league.settings.last_scored_leg`` — the host's statement, not
    our inference.  Deliberately tri-state, mirroring
    ``game_day_sim.LeagueRules.median_enabled``:

    * an ``int`` — including ``0``, which is the real answer "nothing is
      final yet", not an absence;
    * ``None`` when the key is missing or unparseable, meaning UNVERIFIED.

    ``None`` must never be read as "nothing is scored".  Callers pair it
    with an independent completeness proof — see
    ``final_regular_season_weeks``.
    """
    settings = season.league.get("settings") or {}
    raw = settings.get("last_scored_leg")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def median_game_enabled(season: SeasonSnapshot) -> bool | None:
    """Whether this league's standings count a league-average ("median")
    game alongside real H2H, per ``settings.league_average_match``.

    Tri-state, same posture as ``last_scored_week``: an explicit ``True`` /
    ``False``, or ``None`` when the setting is absent or unparseable. An
    unknown median-game setting must not read as "off" -- a league that
    runs it would then have its RECORD column silently misexplained as a
    display bug rather than a real second game per scored week.

    Mirrors the primitive check ``game_day_sim.rules_from_league`` already
    performs on this same field for lineup simulation; this is the same
    fact read for display purposes, not a second definition of it.
    """
    settings = season.league.get("settings") or {}
    raw = settings.get("league_average_match")
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return None
    try:
        return bool(int(raw))
    except (TypeError, ValueError):
        return None


def week_is_fully_scored(
    entries: list[dict[str, Any]],
    expected_rosters: int | None = None,
) -> bool:
    """True when the week looks finished on the DATA alone.

    Two conditions, each closing a different way a live week leaks in:

    * **every entry is scored.**  Rejects an in-progress week, whose
      not-yet-played rosters sit at a literal ``0.0``, and equally rejects
      Sleeper's fully-stubbed future weeks (see ``scored_weeks``).
    * **the entry count matches the league's roster count**, when known.
      Rejects a week Sleeper answered only partially — 8 rows of 12 would
      otherwise pass the first test and reinstate divergent denominators.

    Deliberately NOT a pairing check.  A roster can be scored but unpaired
    (bye, odd team count, malformed matchup row) and the week is still
    finished; ``luck.py`` already handles that owner correctly, keeping
    them in the all-play pool while charging them no record.  Requiring
    pairs here would withhold a complete week, and would reject any
    caller whose rows carry no ``matchup_id``.

    The accepted residual: a roster that genuinely scored ``0.0`` in a
    finished week fails this proof, so that week is admitted only by the
    host clock in ``final_regular_season_weeks``.  Withholding a real week
    for one refresh cycle is the safe direction; admitting a live one is
    not.
    """
    if not entries:
        return False
    if expected_rosters and len(entries) != expected_rosters:
        return False
    return all(is_scored(e) for e in entries)


def final_regular_season_weeks(season: SeasonSnapshot) -> list[int]:
    """Regular-season weeks whose scoring is FINISHED.

    This is the unit of aggregation for anything measured per game — PPG,
    recent form, all-play, luck.  An in-progress week must contribute to
    none of them: counting a Thursday-night sliver as a completed game is
    what made one team's average divide by 2 while another's divided by 1
    (PRIOR-A03-F03).

    A week qualifies on EITHER of two independent proofs, because each
    covers the other's failure mode:

    * **host clock** — ``wk <= last_scored_week(season)``.  This is the
      only proof that can admit a week in which a roster genuinely scored
      ``0.0``, since per-entry inspection cannot tell that apart from
      "hasn't played yet" (measured: the four zero rosters in live week 2
      carried a literal ``0.0``, not ``null``).
    * **data completeness** — every roster reporting a real score, in the
      expected number of rows (``week_is_fully_scored``).  This admits a
      genuinely finished week when the host clock lags a refresh cycle.

    An in-progress week fails both, which is the point.  Both failing is
    also why the return is a WITHHOLDING rather than a guess: an
    unverifiable week is simply absent, never assumed complete.
    """
    horizon = last_scored_week(season)
    out: list[int] = []
    for wk in season.regular_season_weeks:
        if horizon is not None and wk <= horizon:
            out.append(wk)
            continue
        if week_is_fully_scored(
            season.matchups_by_week.get(wk) or [],
            expected_rosters=season.num_teams or None,
        ):
            out.append(wk)
    return out


def final_weeks(season: SeasonSnapshot) -> list[int]:
    """Every week, regular season AND playoffs, whose scoring is FINISHED.

    For surfaces that narrate or decide a week (recaps, winners, "the books
    shut"), where a playoff week matters as much as a regular one.  Extends
    ``final_regular_season_weeks`` rather than re-deriving it:

    * regular-season weeks: exactly ``final_regular_season_weeks``;
    * playoff weeks: the host clock alone (``wk <= last_scored_week``).  The
      data-completeness proof does not apply, since a playoff week
      legitimately carries fewer rows than the league has rosters;
    * a season the host marks ``complete`` has no week left in progress, so
      every week with matchups is final.  Deliberately NOT
      ``SeasonSnapshot.is_complete``, which also accepts ``post_season``:
      Sleeper's status while the playoffs are being played.

    Anything unproven is withheld, never assumed complete: a live week read
    as final is how a Thursday-night sliver was published as a closed week
    (2026-09-24, "the week 3 books shut at 24.2 total points").
    """
    weeks = sorted(season.matchups_by_week)
    if str(season.league.get("status") or "").lower() == "complete":
        return weeks
    regular = set(final_regular_season_weeks(season))
    horizon = last_scored_week(season)
    return [
        wk
        for wk in weeks
        if wk in regular
        or (wk >= season.playoff_week_start and horizon is not None and wk <= horizon)
    ]


def resolve_owner(
    registry: ManagerRegistry,
    league_id: str,
    roster_id: Any,
) -> str:
    try:
        rid_int = int(roster_id)
    except (TypeError, ValueError):
        return ""
    return registry.roster_to_owner.get((str(league_id or ""), rid_int), "")


# ── Standings ────────────────────────────────────────────────────────────
def regular_season_settings_record(roster: dict[str, Any]) -> dict[str, Any]:
    """Return the wins/losses/ties/PF/PA record stored on the Sleeper roster."""
    settings = roster.get("settings") or {}

    def _num(key: str) -> float:
        val = settings.get(key)
        try:
            return float(val or 0)
        except (TypeError, ValueError):
            return 0.0

    points_for = _num("fpts") + (_num("fpts_decimal") / 100.0)
    points_against = _num("fpts_against") + (_num("fpts_against_decimal") / 100.0)
    return {
        "wins": int(_num("wins")),
        "losses": int(_num("losses")),
        "ties": int(_num("ties")),
        "pointsFor": round(points_for, 2),
        "pointsAgainst": round(points_against, 2),
        "sleeperRank": int(_num("rank")) or None,
    }


def season_standings(season: SeasonSnapshot, registry: ManagerRegistry) -> list[dict[str, Any]]:
    """Final regular-season standings from Sleeper roster settings.

    Tiebreaks: higher win%, higher PF, lower PA, lower sleeperRank if set.
    """
    rows: list[dict[str, Any]] = []
    for roster in season.rosters:
        try:
            rid = int(roster.get("roster_id"))
        except (TypeError, ValueError):
            continue
        owner_id = resolve_owner(registry, season.league_id, rid)
        if not owner_id:
            continue
        rec = regular_season_settings_record(roster)
        games = rec["wins"] + rec["losses"] + rec["ties"]
        win_pct = (rec["wins"] + rec["ties"] * 0.5) / games if games else 0.0
        rows.append(
            {
                "ownerId": owner_id,
                "rosterId": rid,
                "leagueId": season.league_id,
                "season": season.season,
                "wins": rec["wins"],
                "losses": rec["losses"],
                "ties": rec["ties"],
                "pointsFor": rec["pointsFor"],
                "pointsAgainst": rec["pointsAgainst"],
                "winPct": round(win_pct, 4),
                "games": games,
                "sleeperRank": rec["sleeperRank"],
            }
        )
    rows.sort(
        key=lambda r: (
            -r["winPct"],
            -r["pointsFor"],
            r["pointsAgainst"],
            r["sleeperRank"] or 999,
        )
    )
    for i, row in enumerate(rows):
        row["standing"] = i + 1
    return rows


def top_seed(standings: list[dict[str, Any]]) -> dict[str, Any] | None:
    return standings[0] if standings else None


# ── Pre-week standings reconstruction ─────────────────────────────────────
def pre_week_standings(
    season: SeasonSnapshot,
    registry: ManagerRegistry,
    week: int,
) -> list[dict[str, Any]]:
    """Standings as of the start of ``week`` — only regular-season games
    completed strictly before ``week`` count.

    Returns a list sorted by standings rank with per-owner totals.
    """
    by_owner: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in by_owner:
            by_owner[owner_id] = {
                "ownerId": owner_id,
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "pointsFor": 0.0,
                "pointsAgainst": 0.0,
            }
        return by_owner[owner_id]

    for wk in season.regular_season_weeks:
        if wk >= week:
            break
        for a, b in matchup_pairs(season.matchups_by_week.get(wk) or []):
            if not is_scored(a) and not is_scored(b):
                continue
            pa, pb = matchup_points(a), matchup_points(b)
            oa = resolve_owner(registry, season.league_id, a.get("roster_id"))
            ob = resolve_owner(registry, season.league_id, b.get("roster_id"))
            if oa:
                rec_a = _ensure(oa)
                rec_a["pointsFor"] += pa
                rec_a["pointsAgainst"] += pb
                if pa > pb:
                    rec_a["wins"] += 1
                elif pa < pb:
                    rec_a["losses"] += 1
                else:
                    rec_a["ties"] += 1
            if ob:
                rec_b = _ensure(ob)
                rec_b["pointsFor"] += pb
                rec_b["pointsAgainst"] += pa
                if pb > pa:
                    rec_b["wins"] += 1
                elif pb < pa:
                    rec_b["losses"] += 1
                else:
                    rec_b["ties"] += 1

    rows = list(by_owner.values())
    for r in rows:
        g = r["wins"] + r["losses"] + r["ties"]
        r["games"] = g
        r["winPct"] = round((r["wins"] + r["ties"] * 0.5) / g, 4) if g else 0.0
        r["pointsFor"] = round(r["pointsFor"], 2)
        r["pointsAgainst"] = round(r["pointsAgainst"], 2)
    rows.sort(key=lambda r: (-r["winPct"], -r["pointsFor"], r["pointsAgainst"]))
    for i, r in enumerate(rows):
        r["standing"] = i + 1
    return rows


# ── Playoff helpers ────────────────────────────────────────────────────────
def playoff_placement(bracket: list[dict[str, Any]]) -> dict[int, int]:
    """Return roster_id -> final playoff place (1 = champion).

    Sleeper's winners_bracket only annotates ``p`` (place) on terminal
    matchups.  The loser of a ``p=1`` matchup places 2, the loser of a
    ``p=3`` matchup places 4, etc.
    """
    placement: dict[int, int] = {}
    for m in bracket:
        if not isinstance(m, dict):
            continue
        p = m.get("p")
        if p is None:
            continue
        try:
            place = int(p)
        except (TypeError, ValueError):
            continue
        winner_rid = m.get("w")
        loser_rid = m.get("l")
        if winner_rid is not None:
            try:
                placement.setdefault(int(winner_rid), place)
            except (TypeError, ValueError):
                pass
        if loser_rid is not None:
            try:
                placement.setdefault(int(loser_rid), place + 1)
            except (TypeError, ValueError):
                pass
    return placement


def playoff_teams(bracket: list[dict[str, Any]]) -> list[int]:
    """Every roster_id that appears anywhere in the winners bracket."""
    teams: set[int] = set()
    for m in bracket:
        if not isinstance(m, dict):
            continue
        for key in ("t1", "t2", "w", "l"):
            v = m.get(key)
            if v is None:
                continue
            try:
                teams.add(int(v))
            except (TypeError, ValueError):
                continue
    return sorted(teams)


def final_playoff_matchup(bracket: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the matchup with ``p=1`` (the championship game) if any."""
    for m in bracket:
        if isinstance(m, dict) and m.get("p") == 1:
            return m
    return None


def season_champion(season: SeasonSnapshot) -> int | None:
    """The roster that WON this season's title, or ``None`` if none has.

    Only a DECIDED championship names a champion:

    * primary — the winner of the ``p=1`` matchup;
    * fallback — a roster the bracket places FIRST (``playoff_placement``
      also accepts a string ``p``).  Place 1 only: the old fallback took
      the *minimum* placement, so a decided 3rd-place game in a bracket
      whose final was still unplayed crowned the 3rd-place winner;
    * last resort — ``league.metadata.latest_league_winner_roster_id``,
      and ONLY when the host marks the season ``complete`` (the same strict
      status ``final_weeks`` uses — ``post_season`` means the playoffs are
      still being played) and the bracket decided nothing.

    Why the metadata is gated: Sleeper carries that field forward onto the
    NEXT season's league object.  On an in-progress season it therefore
    names LAST season's champion — measured 2026-09-26, the 2026 league
    (bracket unplayed) reported roster 2, the 2025 champion, which the
    awards page published as the 2026 Champion and a franchise shelf
    counted as a second title.  Unknown is ``None``, never a stale answer.
    """
    final = final_playoff_matchup(season.winners_bracket)
    if final is not None:
        w = final.get("w")
        if w is not None:
            try:
                return int(w)
            except (TypeError, ValueError):
                pass
    placement = playoff_placement(season.winners_bracket)
    firsts = [rid for rid, place in placement.items() if place == 1]
    if firsts:
        return firsts[0]
    if str(season.league.get("status") or "").lower() != "complete":
        return None
    metadata = season.league.get("metadata") or {}
    explicit = metadata.get("latest_league_winner_roster_id") or season.league.get(
        "last_league_winner_roster_id"
    )
    try:
        return int(explicit) if explicit is not None else None
    except (TypeError, ValueError):
        return None


def season_runner_up(season: SeasonSnapshot) -> int | None:
    placement = playoff_placement(season.winners_bracket)
    candidates = [rid for rid, p in placement.items() if p == 2]
    if candidates:
        return candidates[0]
    # Fallback: loser of the final matchup.
    final = final_playoff_matchup(season.winners_bracket)
    if final is not None:
        loser_rid = final.get("l")
        try:
            return int(loser_rid) if loser_rid is not None else None
        except (TypeError, ValueError):
            return None
    return None


# ── Iteration helpers ────────────────────────────────────────────────────
def walk_weekly_scores(
    snapshot: PublicLeagueSnapshot,
    include_playoffs: bool = True,
) -> Iterable[tuple[SeasonSnapshot, int, dict[str, Any]]]:
    """Yield (season, week, entry) for every scored roster-week."""
    for season in snapshot.seasons:
        weeks = season.all_weeks if include_playoffs else season.regular_season_weeks
        for wk in sorted(weeks):
            for entry in season.matchups_by_week.get(wk) or []:
                if is_scored(entry):
                    yield season, wk, entry


def walk_matchup_pairs(
    snapshot: PublicLeagueSnapshot,
    include_playoffs: bool = True,
) -> Iterable[tuple[SeasonSnapshot, int, dict[str, Any], dict[str, Any], bool]]:
    """Yield (season, week, a, b, is_playoff) for every scored pair.

    Multi-week championship matchups (e.g. a 2-week final spanning
    weeks 16 and 17) are detected and yielded as a single combined
    entry: points are summed across both weeks, the yielded week is
    the earlier of the two, and each side carries a
    ``_combinedWeeks`` marker listing the spanned weeks so downstream
    consumers can surface the combined nature in UI labels.

    Detection rule, deliberately narrow to avoid fusing the semifinal
    with the final when the same rosters happen to appear in both:
    the *last two playoff weeks* of the season must be contiguous
    (wk_last == wk_penultimate + 1) AND the same pair of roster_ids
    must appear in both.  Earlier playoff weeks (semis, quarters) are
    emitted individually even when a repeat pairing exists.

    This matches how Sleeper's ``championship_week_length = 2``
    leagues surface their final: the last two scheduled weeks carry
    the same finalists and the winner is decided by combined score.
    """
    for season in snapshot.seasons:
        weeks_sorted = sorted(season.matchups_by_week.keys())
        # Pre-compute pairs per week so lookahead into wk+1 is cheap.
        pairs_by_week: dict[int, list[tuple[dict[str, Any], dict[str, Any]]]] = {
            wk: matchup_pairs(season.matchups_by_week[wk]) for wk in weeks_sorted
        }
        # Index each week's pairs by the frozenset of the two roster ids
        # so the lookahead step can probe in O(1).
        index_by_week: dict[int, dict[frozenset[int], tuple[dict[str, Any], dict[str, Any]]]] = {}
        for wk in weeks_sorted:
            idx: dict[frozenset[int], tuple[dict[str, Any], dict[str, Any]]] = {}
            for a, b in pairs_by_week[wk]:
                rid_a = roster_id_of(a)
                rid_b = roster_id_of(b)
                if rid_a is None or rid_b is None:
                    continue
                idx[frozenset({rid_a, rid_b})] = (a, b)
            index_by_week[wk] = idx

        # Build per-pair combine plan.  Sleeper snapshots frequently
        # include trailing "week 18" roster rows with ``matchup_id ==
        # None`` that look like playoffs by week number but carry no
        # real pairings — so a naive "last two playoff weeks" rule
        # misses the real championship.  Instead, for each pair that
        # actually yields a matchup pair in the playoff window, find
        # the *latest* run of consecutive playoff weeks it appears in.
        # If the run has length >= 2, the last two weeks of that run
        # are the multi-week final and should be fused.  Runs are
        # per-pair, so a 3-week semi+final same-rosters scenario
        # combines only the last two (championship) weeks and leaves
        # the earlier semifinal emit intact.
        playoff_week_start = season.playoff_week_start
        pair_playoff_weeks: dict[frozenset[int], list[int]] = {}
        for wk in weeks_sorted:
            if wk < playoff_week_start:
                continue
            for key in index_by_week[wk].keys():
                pair_playoff_weeks.setdefault(key, []).append(wk)

        # pair -> (combine_from_wk, combine_to_wk) for 2-week finals.
        combine_plan: dict[frozenset[int], tuple[int, int]] = {}
        for pair_key, pwks in pair_playoff_weeks.items():
            pwks_sorted = sorted(pwks)
            # Walk the list and keep the latest consecutive pair.
            latest: tuple[int, int] | None = None
            for i in range(len(pwks_sorted) - 1):
                if pwks_sorted[i + 1] == pwks_sorted[i] + 1:
                    latest = (pwks_sorted[i], pwks_sorted[i + 1])
            if latest is not None:
                combine_plan[pair_key] = latest

        # Track (week, pair_key) consumed as the second half of a
        # combined matchup so we don't emit the same pair twice.
        consumed: set[tuple[int, frozenset[int]]] = set()

        for wk in weeks_sorted:
            is_playoff = wk >= playoff_week_start
            if is_playoff and not include_playoffs:
                continue
            for a, b in pairs_by_week[wk]:
                rid_a = roster_id_of(a)
                rid_b = roster_id_of(b)
                if rid_a is None or rid_b is None:
                    continue
                pair_key = frozenset({rid_a, rid_b})

                if (wk, pair_key) in consumed:
                    continue

                emit_a, emit_b = a, b
                # Combine only when this week is the first half of
                # the planned 2-week final for *this* pair.
                plan = combine_plan.get(pair_key)
                if plan is not None and plan[0] == wk:
                    combine_to_wk = plan[1]
                    next_pair = index_by_week.get(combine_to_wk, {}).get(pair_key)
                    if next_pair is not None:
                        a2, b2 = next_pair
                        rid_a2 = roster_id_of(a2)
                        # Align the two sides so emit_a tracks rid_a
                        # and emit_b tracks rid_b across both weeks.
                        side_a2, side_b2 = (a2, b2) if rid_a2 == rid_a else (b2, a2)
                        combined_weeks = [wk, combine_to_wk]
                        emit_a = {
                            **a,
                            "points": matchup_points(a) + matchup_points(side_a2),
                            "_combinedWeeks": combined_weeks,
                        }
                        emit_b = {
                            **b,
                            "points": matchup_points(b) + matchup_points(side_b2),
                            "_combinedWeeks": combined_weeks,
                        }
                        consumed.add((combine_to_wk, pair_key))

                if not is_scored(emit_a) and not is_scored(emit_b):
                    continue
                yield season, wk, emit_a, emit_b, is_playoff


# ── Shared team-name resolver ────────────────────────────────────────────
def team_name(snapshot: PublicLeagueSnapshot, league_id: str, roster_id: int | None) -> str:
    """Historical team name for a roster in a league."""
    if roster_id is None:
        return ""
    owner_id = resolve_owner(snapshot.managers, league_id, roster_id)
    manager = snapshot.managers.by_owner_id.get(owner_id) if owner_id else None
    if not manager:
        return f"Team {roster_id}"
    for alias in manager.aliases:
        if alias.league_id == league_id and alias.roster_id == roster_id:
            return alias.team_name
    return manager.current_team_name or manager.display_name or f"Team {roster_id}"


def display_name_for(snapshot: PublicLeagueSnapshot, owner_id: str) -> str:
    mgr = snapshot.managers.by_owner_id.get(owner_id) if owner_id else None
    if not mgr:
        return owner_id or ""
    return mgr.display_name or mgr.current_team_name or owner_id
