"""Section: Weekly Recap Newsletter.

Auto-generates an ESPN-style narrative recap for every completed
scored week in the snapshot:

    * Headline — single sentence capturing the week's dominant story.
    * Summary — multi-sentence post-game analysis. Includes standings
      context, MVP, blowout/nail-biter framing, top performers, bad
      beats, and recent activity. Uses a varied phrase bank so two
      consecutive weeks don't read identically.
    * Superlatives — blowout / nailbiter / MVP / bust / bad beat.
    * Per-matchup one-liners with winner, margin, highlight.
    * Trades that were completed during the week's transaction leg.

The recap is pre-computed in one pass per snapshot so the dynamic
``/league/week/[season]/[week]`` route can fetch the public contract
and pick its record out by key in O(1).

Output shape
────────────
``seasonsCovered``  — passthrough.
``weeks``           — list of per-week recap dicts, ordered newest first.
``byKey``           — flat ``{"<season>:<week>": recap}`` map for
                      O(1) lookup from the dynamic route.
"""
from __future__ import annotations

import random
from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _side_entry(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, entry: dict[str, Any]) -> dict[str, Any]:
    rid = metrics.roster_id_of(entry)
    owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
    return {
        "ownerId": owner_id,
        "rosterId": rid,
        "displayName": metrics.display_name_for(snapshot, owner_id) if owner_id else "",
        "teamName": metrics.team_name(snapshot, season.league_id, rid),
        "points": round(metrics.matchup_points(entry), 2),
    }


def _season_sort_key(season: str) -> int:
    try:
        return int(season)
    except (TypeError, ValueError):
        return 0


def _weekly_trades_for(
    season: SeasonSnapshot,
    snapshot: PublicLeagueSnapshot,
    week: int,
) -> list[dict[str, Any]]:
    """Return completed trades whose transaction ``leg`` matches ``week``."""
    out: list[dict[str, Any]] = []
    for tx in season.trades():
        try:
            leg = int(tx.get("_leg") or tx.get("leg") or 0)
        except (TypeError, ValueError):
            leg = 0
        if leg != week:
            continue
        roster_ids = tx.get("roster_ids") or []
        parties = []
        for rid in roster_ids:
            oid = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if oid:
                parties.append({
                    "ownerId": oid,
                    "displayName": metrics.display_name_for(snapshot, oid),
                })
        adds = tx.get("adds")
        assets_moved = len(adds) if isinstance(adds, dict) else 0
        picks_moved = len(tx.get("draft_picks") or [])
        out.append({
            "transactionId": tx.get("transaction_id"),
            "parties": parties,
            "assetsMoved": assets_moved,
            "picksMoved": picks_moved,
        })
    return out


# ── Per-matchup one-liner phrase bank ─────────────────────────────────────
_TIE_PHRASES = (
    "{a} and {b} stalemated at {pts:.1f}, splitting the spoils.",
    "{a} and {b} traded haymakers and stayed deadlocked at {pts:.1f}.",
    "{a} and {b} ended in a {pts:.1f}-all draw — neither side blinked.",
)
_NAILBITER_PHRASES = (
    "{w} edged {l} by {m:.1f} in a coin-flip finish.",
    "{w} survived {l} by {m:.1f} — decided in the final minutes.",
    "{w} held off {l} by a hair, {m:.1f}.",
    "{w} outlasted {l} by {m:.1f} in a back-and-forth slugfest.",
)
_OBLITERATE_PHRASES = (
    "{w} steamrolled {l} by {m:.1f}.",
    "{w} buried {l} by {m:.1f}.",
    "{w} ran the score up on {l}, {m:.1f}.",
    "{w} dropped the hammer on {l} — {m:.1f}-point margin.",
)
_ROLL_PHRASES = (
    "{w} rolled {l} by {m:.1f}.",
    "{w} stayed in cruise control past {l} by {m:.1f}.",
    "{w} dictated terms to {l}, {m:.1f}.",
    "{w} put {l} away comfortably — {m:.1f}-point spread.",
)
_BEAT_PHRASES = (
    "{w} beat {l} by {m:.1f}.",
    "{w} took {l} by {m:.1f}.",
    "{w} got past {l} by {m:.1f}.",
    "{w} handled {l} by {m:.1f}.",
)


def _choose(phrases: tuple[str, ...], seed: int) -> str:
    """Deterministically pick a phrase given an integer seed."""
    return phrases[seed % len(phrases)]


def _matchup_oneliner(home: dict, away: dict, margin: float, seed: int) -> str:
    if home["points"] == away["points"]:
        return _choose(_TIE_PHRASES, seed).format(
            a=home["displayName"], b=away["displayName"], pts=home["points"]
        )
    winner, loser = (home, away) if home["points"] > away["points"] else (away, home)
    if margin < 3:
        bank = _NAILBITER_PHRASES
    elif margin >= 50:
        bank = _OBLITERATE_PHRASES
    elif margin >= 25:
        bank = _ROLL_PHRASES
    else:
        bank = _BEAT_PHRASES
    return _choose(bank, seed).format(
        w=winner["displayName"], l=loser["displayName"], m=margin
    )


# ── Headline phrase banks ─────────────────────────────────────────────────
_BLOWOUT_HEADLINES = (
    "{w} steamrolled {l} {ws:.1f}-{ls:.1f}",
    "{w} buried {l} by {m:.1f}",
    "{w} dismantled {l} {ws:.1f}-{ls:.1f}",
    "{w} ran riot on {l} — {m:.1f}-point margin",
    "{w} torched {l} for a {m:.1f}-point win",
)
_BIG_WIN_HEADLINES = (
    "{w} cruised past {l} by {m:.1f}",
    "{w} put {l} away by {m:.1f}",
    "{w} took control over {l} by {m:.1f}",
)
_NAILBITER_HEADLINES = (
    "{w} survived {l} by {m:.2f}",
    "{w} squeaked past {l} by {m:.2f}",
    "{w} edged {l} in a thriller, {m:.2f}",
    "{w} held on against {l} by {m:.2f}",
)
_MVP_HEADLINES = (
    "{name} torched the league with {pts:.1f}",
    "{name} dropped {pts:.1f} on the slate",
    "{name} led the field at {pts:.1f}",
    "{name} put up a league-best {pts:.1f}",
)
_MVP_AND_BLOWOUT_HEADLINES = (
    "{name} dropped {pts:.1f} in a {m:.1f}-point demolition",
    "{name} powered a {m:.1f}-point statement win, {pts:.1f}",
    "{name}'s {pts:.1f} fueled a {m:.1f}-point rout",
)
_FALLBACK_HEADLINES = (
    "Week in review",
    "Around the league",
    "This week in the league",
)


def _headline(recap: dict[str, Any], seed: int) -> str:
    blowout = recap.get("blowout")
    nailbiter = recap.get("nailBiter")
    mvp = recap.get("mvp")

    # MVP + blowout from the same manager: "stat torched in a blowout".
    if mvp and blowout and mvp.get("ownerId") == blowout["winner"]["ownerId"] and blowout["margin"] >= 25:
        return _choose(_MVP_AND_BLOWOUT_HEADLINES, seed).format(
            name=mvp["displayName"], pts=mvp["points"], m=blowout["margin"]
        )
    if blowout and blowout["margin"] >= 40:
        return _choose(_BLOWOUT_HEADLINES, seed).format(
            w=blowout["winner"]["displayName"],
            l=blowout["loser"]["displayName"],
            ws=blowout["winner"]["points"],
            ls=blowout["loser"]["points"],
            m=blowout["margin"],
        )
    if nailbiter and nailbiter["margin"] < 2:
        return _choose(_NAILBITER_HEADLINES, seed).format(
            w=nailbiter["winner"]["displayName"],
            l=nailbiter["loser"]["displayName"],
            m=nailbiter["margin"],
        )
    if blowout and blowout["margin"] >= 25:
        return _choose(_BIG_WIN_HEADLINES, seed).format(
            w=blowout["winner"]["displayName"],
            l=blowout["loser"]["displayName"],
            m=blowout["margin"],
        )
    if mvp:
        return _choose(_MVP_HEADLINES, seed).format(
            name=mvp["displayName"], pts=mvp["points"]
        )
    return _choose(_FALLBACK_HEADLINES, seed)


# ── Summary phrase banks ──────────────────────────────────────────────────
_OPEN_PHRASES = (
    "Week {wk}{playoff} — {n} matchups, {scored:.1f} combined points scored.",
    "Week {wk}{playoff} closed with {n} games on the slate and {scored:.1f} total points.",
    "{n} games, {scored:.1f} combined points: that was the shape of week {wk}{playoff}.",
    "The week {wk}{playoff} books shut at {scored:.1f} total points across {n} matchups.",
)
_MVP_LINES = (
    "{name} led the slate with {pts:.1f} points{ctx}.",
    "Top score went to {name} at {pts:.1f}{ctx}.",
    "{name} paced the league at {pts:.1f}{ctx}.",
    "Nobody touched {name}'s {pts:.1f}{ctx}.",
)
_BLOWOUT_LINES = (
    "{w} ran roughshod over {l}, winning {ws:.1f}-{ls:.1f} — a {m:.1f}-point margin that was effectively over by halftime.",
    "{w} delivered a beatdown of {l}, {ws:.1f}-{ls:.1f}, separating themselves with a {m:.1f}-point cushion.",
    "{w}'s {ws:.1f} buried {l}'s {ls:.1f} — a {m:.1f}-point gap that flatters {l} more than the live look did.",
    "{w} put together one of the cleaner top-to-bottom outings of the week, taking {l} by {m:.1f}.",
)
_LARGE_WIN_LINES = (
    "{w} controlled {l} from the jump, winning by {m:.1f}.",
    "{w} pulled away from {l} for a {m:.1f}-point win — never really threatened.",
    "{w}'s {ws:.1f}-{ls:.1f} win over {l} was decided well before the final scoreboard refresh.",
)
_NAILBITER_LINES = (
    "The closest game went to {w} over {l} by just {m:.2f} — every flex slot mattered.",
    "{w} survived {l} by {m:.2f} in a game that came down to Monday-night decimals.",
    "Tightest finish on the slate: {w} squeaked by {l} by {m:.2f}.",
    "{w} outlasted {l} by {m:.2f} in a back-and-forth thriller.",
)
_TIGHT_PAIR_LINES = (
    "Three games inside ten points underline how compressed this scoring week was.",
    "Multiple matchups went down to the wire — a margin-tight slate top to bottom.",
)
_BAD_BEAT_LINES = (
    "{name} was the bad-beat candidate of the week — {pts:.1f} points and still {ml:.1f} short of the win.",
    "Tough luck for {name}: {pts:.1f} points isn't usually a losing number, but it was on the wrong side of {opp}'s ceiling week.",
    "{name} dropped a {pts:.1f}-point bomb and somehow caught an L — {opp} just had more.",
    "{name} put up {pts:.1f} and lost. That's a season-long bad beat candidate right there.",
)
_BUST_LINES = (
    "{name} bottomed out at {pts:.1f}, the only sub-{floor:.0f} score on the slate.",
    "Cellar of the week was {name} at {pts:.1f} — a get-back-on-the-horse week.",
    "{name}'s {pts:.1f} was the floor of the league this week.",
)
_TRADE_LINES = (
    "{n} {plural} cleared on the wire this week.",
    "Activity report: {n} {plural} got done.",
    "The trade window stayed warm — {n} {plural} processed.",
    "{n} {plural} went through, keeping the front offices busy.",
)
_PLAYOFF_LINES = (
    "Playoff stakes: every point counts toward seeding and survival.",
    "Postseason football — knockout football — and it showed.",
    "Playoffs heighten everything; that was visible across the slate.",
)
_STREAK_LINES = (
    "{name} extended their win streak to {n} straight.",
    "{name}'s losing streak hit {n} games — they need a course correction.",
    "{name} stayed unbeaten over their last {n} games.",
)


def _summary(recap: dict[str, Any], seed: int) -> str:
    """Compose 3-5 sentences of varied analysis."""
    parts: list[str] = []
    rng = random.Random(seed)

    matchups = recap.get("matchups") or []
    n_games = len(matchups)
    scored_total = sum((m["home"]["points"] + m["away"]["points"]) for m in matchups)
    is_playoff = recap.get("isPlayoff")

    parts.append(
        _choose(_OPEN_PHRASES, seed).format(
            wk=recap["week"],
            n=n_games,
            scored=scored_total,
            playoff=" (playoffs)" if is_playoff else "",
        )
    )

    mvp = recap.get("mvp")
    bust = recap.get("bust")
    bad_beat = recap.get("badBeat")
    blowout = recap.get("blowout")
    nailbiter = recap.get("nailBiter")

    # MVP narrative — anchor a context tag so it doesn't read identical
    # week to week.
    if mvp:
        ctx_options = [
            "",
            f", {mvp['points'] - (bust['points'] if bust else 0):.1f} clear of the cellar",
        ]
        if blowout and mvp.get("ownerId") == blowout["winner"]["ownerId"]:
            ctx_options.append(
                f" while leading {blowout['loser']['displayName']} by {blowout['margin']:.1f}"
            )
        ctx = rng.choice(ctx_options)
        parts.append(
            _choose(_MVP_LINES, seed + 1).format(
                name=mvp["displayName"], pts=mvp["points"], ctx=ctx
            )
        )

    # Game-shape line.  Prefer a true blowout, else a nail-biter, else a
    # large-margin runner-up framing.
    if blowout and blowout["margin"] >= 40:
        parts.append(
            _choose(_BLOWOUT_LINES, seed + 2).format(
                w=blowout["winner"]["displayName"],
                l=blowout["loser"]["displayName"],
                ws=blowout["winner"]["points"],
                ls=blowout["loser"]["points"],
                m=blowout["margin"],
            )
        )
    elif blowout and blowout["margin"] >= 25:
        parts.append(
            _choose(_LARGE_WIN_LINES, seed + 2).format(
                w=blowout["winner"]["displayName"],
                l=blowout["loser"]["displayName"],
                ws=blowout["winner"]["points"],
                ls=blowout["loser"]["points"],
                m=blowout["margin"],
            )
        )
    if nailbiter and nailbiter["margin"] < 5 and (
        not blowout or nailbiter["margin"] != blowout["margin"]
    ):
        parts.append(
            _choose(_NAILBITER_LINES, seed + 3).format(
                w=nailbiter["winner"]["displayName"],
                l=nailbiter["loser"]["displayName"],
                m=nailbiter["margin"],
            )
        )

    # Tight-slate observation when 3+ games were inside 10 points.
    tight_count = sum(1 for m in matchups if m["margin"] <= 10.0)
    if tight_count >= 3:
        parts.append(_choose(_TIGHT_PAIR_LINES, seed + 4))

    # Bad beat OR bust framing — never both, to keep the recap punchy.
    if bad_beat and (not mvp or bad_beat["points"] > mvp["points"] - 10):
        parts.append(
            _choose(_BAD_BEAT_LINES, seed + 5).format(
                name=bad_beat["displayName"],
                pts=bad_beat["points"],
                ml=bad_beat["marginOfLoss"],
                opp=bad_beat.get("winnerDisplayName") or "their opponent",
            )
        )
    elif bust and bust["points"] > 0:
        floor = max(60.0, bust["points"] + 10.0)
        parts.append(
            _choose(_BUST_LINES, seed + 5).format(
                name=bust["displayName"], pts=bust["points"], floor=floor
            )
        )

    if is_playoff:
        parts.append(_choose(_PLAYOFF_LINES, seed + 6))

    trades_count = len(recap.get("trades") or [])
    if trades_count:
        plural = "trade" if trades_count == 1 else "trades"
        parts.append(
            _choose(_TRADE_LINES, seed + 7).format(n=trades_count, plural=plural)
        )

    return " ".join(parts)


def _build_week_recap(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    week: int,
) -> dict[str, Any] | None:
    entries = season.matchups_by_week.get(week) or []
    pairs = metrics.matchup_pairs(entries)
    if not pairs:
        return None
    scored_pairs = [
        (a, b) for a, b in pairs
        if metrics.is_scored(a) or metrics.is_scored(b)
    ]
    if not scored_pairs:
        return None

    is_playoff = week >= season.playoff_week_start
    matchup_rows: list[dict[str, Any]] = []
    highest: dict[str, Any] | None = None
    lowest: dict[str, Any] | None = None
    biggest: dict[str, Any] | None = None
    closest: dict[str, Any] | None = None
    bad_beat: dict[str, Any] | None = None

    # Per-recap deterministic seed so phrase choice varies across weeks.
    try:
        seed = int(season.season) * 100 + week
    except (TypeError, ValueError):
        seed = week

    for i, (a, b) in enumerate(scored_pairs):
        home = _side_entry(snapshot, season, a)
        away = _side_entry(snapshot, season, b)
        if home["points"] == 0 and away["points"] == 0:
            continue
        margin = round(abs(home["points"] - away["points"]), 2)
        if home["points"] > away["points"]:
            winner, loser = home, away
        elif away["points"] > home["points"]:
            winner, loser = away, home
        else:
            winner = None
            loser = None

        row = {
            "matchupId": a.get("matchup_id"),
            "home": home,
            "away": away,
            "margin": margin,
            "winner": winner,
            "loser": loser,
            "oneliner": _matchup_oneliner(home, away, margin, seed + i),
        }
        matchup_rows.append(row)

        for side in (home, away):
            if highest is None or side["points"] > highest["points"]:
                highest = side
            if lowest is None or side["points"] < lowest["points"]:
                lowest = side
        if winner and (biggest is None or margin > biggest["margin"]):
            biggest = {
                "winner": winner,
                "loser": loser,
                "margin": margin,
                "oneliner": row["oneliner"],
            }
        if winner and (closest is None or margin < closest["margin"]):
            closest = {
                "winner": winner,
                "loser": loser,
                "margin": margin,
                "oneliner": row["oneliner"],
            }
        if loser:
            candidate = {
                "ownerId": loser["ownerId"],
                "displayName": loser["displayName"],
                "teamName": loser["teamName"],
                "points": loser["points"],
                "marginOfLoss": margin,
                "winnerOwnerId": winner["ownerId"],
                "winnerDisplayName": winner["displayName"],
            }
            if bad_beat is None or candidate["points"] > bad_beat["points"]:
                bad_beat = candidate

    if not matchup_rows:
        return None

    trades = _weekly_trades_for(season, snapshot, week)

    recap: dict[str, Any] = {
        "season": season.season,
        "leagueId": season.league_id,
        "week": week,
        "isPlayoff": is_playoff,
        "matchups": matchup_rows,
        "blowout": biggest,
        "nailBiter": closest,
        "mvp": highest,
        "bust": lowest,
        "badBeat": bad_beat,
        "trades": trades,
    }
    recap["headline"] = _headline(recap, seed)
    recap["summary"] = _summary(recap, seed)
    return recap


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    seasons_sorted = sorted(
        snapshot.seasons, key=lambda s: _season_sort_key(s.season)
    )

    weeks_out: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}

    for season in seasons_sorted:
        for wk in sorted(season.matchups_by_week.keys()):
            recap = _build_week_recap(snapshot, season, wk)
            if not recap:
                continue
            weeks_out.append(recap)
            by_key[f"{season.season}:{wk}"] = recap

    weeks_out.sort(
        key=lambda r: (_season_sort_key(r["season"]), r["week"]),
        reverse=True,
    )

    return {
        "seasonsCovered": [s.season for s in snapshot.seasons],
        "weeks": weeks_out,
        "byKey": by_key,
        "latest": weeks_out[0] if weeks_out else None,
    }
