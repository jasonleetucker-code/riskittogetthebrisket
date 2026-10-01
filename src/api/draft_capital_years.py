"""Per-season views of a ``/api/draft-capital`` board (owner request 2026-10-01).

The Draft Capital tab on ``/league`` gains a year selector ("All Years | 2027 |
2028 ...").  The selector changes WHICH picks are included, never HOW they are
valued, so this module computes nothing new about any pick.  It takes a board
that one of the two existing builders already produced —

* the default league's workbook path (``server._fetch_draft_capital``), and
* the Sleeper-derived fallback (``src/api/draft_capital_fallback.py``) —

and partitions the per-team capital those builders already computed by the
season each pick belongs to.

**No per-year renormalization.**  Both builders spread ONE fixed budget
(``totalBudget``, $1200) across every priced pick they emit.  A season's view
is the SUM of those same per-pick dollars; it is never re-spread so that the
season alone totals $1200.  So the per-season numbers add back up to each
team's existing ``auctionDollars`` (pinned by tests), and a season the
builders give a small share of the pool reads small rather than being
inflated to look like a full draft.

**A partially priced season ranks on its PRICED dollars.**  Unpriced picks
(``dollarValue: null``) are excluded from a season's sum exactly as the
builders already exclude them from ``auctionDollars``, and counted in
``unpricedPickCountByYear`` so the row can say so.  Dollars are non-negative,
so a team's priced sum is a floor on what a fully priced season would show;
its rank is a rank of priced capital, not of all capital.

**Available years are DATA, not a list.**  ``availableYears`` is the set of
seasons the builder's pick inventory actually contains.  Which seasons those
are is decided upstream by the existing retirement policy of each path — the
workbook path bumps past a completed rookie draft
(``current_draft_complete``), the fallback starts at the league's first
non-retired class (``draft_class_evidence.active_seasons_for_league``, #1414)
— so a completed class disappears and a newly generated one appears without
this module knowing any year.

**Missing is never zero.**  A pick the builder could not price
(``dollarValue: None`` / ``isUnpriced: True``) contributes no dollars and is
COUNTED.  A team whose picks in a season are all unpriced gets ``None`` for
that season's capital — not 0, which is reserved for "owns no picks in that
season" — and sinks below every priced team in that season's ranking.

Everything emitted here is derived from fields the public payload already
carries (team names, per-pick ``season`` / ``currentOwner`` / ``dollarValue``)
— no rookie-board field is read — so the public/private boundary is
unchanged: ``_redact_draft_capital_for_public`` rebuilds only ``picks`` and
shares these blocks by reference, and nothing here is ever written after the
payload is cached.
"""

from __future__ import annotations

from typing import Any, Mapping

#: The basis each builder's per-season capital is computed on.  Published so
#: a reader can tell the two apart; they differ because the two builders form
#: their team totals differently (see ``attach_year_views``).
BASIS_PER_PICK_SUM = "sum_of_per_pick_dollars"
BASIS_SINGLE_SEASON_TOTAL = "single_season_team_total"


def _pick_season(pick: Mapping[str, Any], board_season: Any) -> int | None:
    raw = pick.get("season", board_season)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _is_unpriced(pick: Mapping[str, Any]) -> bool:
    if pick.get("isUnpriced") is True:
        return True
    value = pick.get("dollarValue")
    return not isinstance(value, (int, float)) or isinstance(value, bool)


def attach_year_views(
    result: dict[str, Any],
    *,
    capital_by_team_year: Mapping[str, Mapping[int, float | int | None]] | None = None,
) -> dict[str, Any]:
    """Stamp the per-season views onto a freshly built board, in place.

    Must run BEFORE the board is cached — it writes to ``result``.

    ``capital_by_team_year`` lets a builder hand over the per-season capital
    it computed itself.  The workbook path needs this: its team totals are the
    sheet's per-owner Q-column decimals rounded to the budget, NOT a sum of
    the per-pick L-column dollars the rows display, so re-summing the rows
    would publish a number that disagrees with ``auctionDollars``.  It carries
    one season by construction, so it passes that season's existing total.
    When omitted, a season's capital is the sum of the priced per-pick
    ``dollarValue`` the team currently owns in it — exactly how the fallback
    forms ``auctionDollars``, so the seasons add back up to it.

    Adds:

    * ``availableYears`` — sorted seasons present in ``picks``;
    * per ``teamTotals`` row: ``draftCapitalByYear`` / ``pickCountByYear`` /
      ``unpricedPickCountByYear`` (string season keys), plus all-season
      ``pickCount`` / ``unpricedPickCount``;
    * ``teamTotalsByYear`` — season → rows ranked on that season's capital,
      same units as ``auctionDollars``;
    * ``yearSummaries`` — season → league totals for that season;
    * ``yearViewBasis`` — which basis produced the numbers.
    """
    if not isinstance(result, dict) or result.get("error"):
        return result
    picks = result.get("picks")
    picks = picks if isinstance(picks, list) else []
    team_rows = result.get("teamTotals")
    team_rows = team_rows if isinstance(team_rows, list) else []
    board_season = result.get("season")

    years: set[int] = set()
    # (team, season) → [pickCount, unpricedCount, pricedDollars]
    cells: dict[tuple[str, int], list[float]] = {}
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        season = _pick_season(pick, board_season)
        owner = pick.get("currentOwner")
        if season is None or not isinstance(owner, str):
            continue
        years.add(season)
        cell = cells.setdefault((owner, season), [0, 0, 0.0])
        cell[0] += 1
        if _is_unpriced(pick):
            cell[1] += 1
        else:
            cell[2] += float(pick["dollarValue"])

    available = sorted(years)

    # Every team the board lists, plus any owner that only appears on a pick
    # (neither builder produces one today; never drop it if one does).
    team_order: list[str] = [
        str(r.get("team")) for r in team_rows if isinstance(r, dict) and r.get("team") is not None
    ]
    known = set(team_order)
    for owner, _season in cells:
        if owner not in known:
            known.add(owner)
            team_order.append(owner)

    def _capital(team: str, season: int) -> float | int | None:
        count, unpriced, dollars = cells.get((team, season), [0, 0, 0.0])
        if capital_by_team_year is not None:
            by_year = capital_by_team_year.get(team) or {}
            explicit = by_year.get(season)
            if explicit is not None:
                return explicit
            if count == 0:
                return 0
            # Fall through: the builder named no figure for a season this
            # team holds picks in — derive it the same way as the default.
        if count == 0:
            return 0
        if unpriced == count:
            return None  # holds picks, none of them priced — UNKNOWN, not 0
        return int(dollars) if float(dollars).is_integer() else round(dollars, 2)

    per_team: dict[str, dict[str, Any]] = {}
    for team in team_order:
        cap_by_year: dict[str, Any] = {}
        count_by_year: dict[str, int] = {}
        unpriced_by_year: dict[str, int] = {}
        for season in available:
            count, unpriced, _d = cells.get((team, season), [0, 0, 0.0])
            cap_by_year[str(season)] = _capital(team, season)
            count_by_year[str(season)] = int(count)
            unpriced_by_year[str(season)] = int(unpriced)
        per_team[team] = {
            "draftCapitalByYear": cap_by_year,
            "pickCountByYear": count_by_year,
            "unpricedPickCountByYear": unpriced_by_year,
            "pickCount": sum(count_by_year.values()),
            "unpricedPickCount": sum(unpriced_by_year.values()),
        }

    for row in team_rows:
        if isinstance(row, dict) and row.get("team") is not None:
            row.update(per_team.get(str(row["team"]), {}))

    by_year: dict[str, list[dict[str, Any]]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for season in available:
        key = str(season)
        rows = [
            {
                "team": team,
                "auctionDollars": per_team[team]["draftCapitalByYear"][key],
                "pickCount": per_team[team]["pickCountByYear"][key],
                "unpricedPickCount": per_team[team]["unpricedPickCountByYear"][key],
            }
            for team in team_order
        ]
        # Priced capital descending; a team whose capital is unknown sinks
        # below every known figure (including a true zero).  Name breaks ties
        # so the order is deterministic.
        known = sorted(
            (r for r in rows if r["auctionDollars"] is not None),
            key=lambda r: (-r["auctionDollars"], r["team"].casefold()),
        )
        unknown = sorted(
            (r for r in rows if r["auctionDollars"] is None), key=lambda r: r["team"].casefold()
        )
        rows = known + unknown
        for i, r in enumerate(rows, start=1):
            r["rank"] = i if r["auctionDollars"] is not None else None
        by_year[key] = rows
        season_picks = sum(r["pickCount"] for r in rows)
        season_unpriced = sum(r["unpricedPickCount"] for r in rows)
        total = sum(r["auctionDollars"] for r in rows if r["auctionDollars"] is not None)
        summaries[key] = {
            "totalDollars": int(total) if float(total).is_integer() else round(total, 2),
            "pickCount": season_picks,
            "pricedPickCount": season_picks - season_unpriced,
            "unpricedPickCount": season_unpriced,
            "teamsWithPicks": sum(1 for r in rows if r["pickCount"] > 0),
        }

    result["availableYears"] = available
    result["teamTotalsByYear"] = by_year
    result["yearSummaries"] = summaries
    result["yearViewBasis"] = (
        BASIS_SINGLE_SEASON_TOTAL if capital_by_team_year is not None else BASIS_PER_PICK_SUM
    )
    return result
