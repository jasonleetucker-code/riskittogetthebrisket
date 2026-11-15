"""The dynasty trade database — browse and filter recorded real trades (TC-08).

A searchable view over the canonical underlying-trade ledger
(``market_trade_report``).  Rows pass exactly the TC-07 visibility rules
(``market_trade_reference.visibility``) and are rendered by the same
projection (``market_trade_reference.project_trade``), so the database and
the calculator's "Recent real trades" panel can never disagree about what a
trade is, what format it was in, or whether a viewer may see it.

FILTERS — every one reads a FACT already on the projected row
─────────────────────────────────────────────────────────────
* assets — Sleeper player ids / board pick-row names / owned league-pick ids,
  matched by the TC-07 identity rules (never by name).
* date window — ``since`` / ``until`` (ISO dates), bounded by
  ``MAX_LOOKBACK_DAYS``.
* format — ``superflex``, ``teams``, ``starters``, ``idp``, ``teScoringEdge``
  (the ledger's scoring-card fact), ``ktcTepLevel`` (KTC's own vendor setting,
  never translated into a scoring edge — there is no measured crosswalk).
* ``source`` — one of the three visible ledger lanes.
* ``shape`` — assets per side, largest first ("2x1").
* ``assetMix`` — ``players`` / ``picks`` / ``mixed``.

UNKNOWN IS NOT A MATCH.  A format filter excludes a row whose value for that
field is unknown, and the response counts those exclusions per filter
(``excludedUnknown``) — so "no 12-team trades" and "we do not know the team
count of these trades" never read the same.  ``ktcTepLevel`` is a KTC vendor
setting: a non-KTC row is NOT APPLICABLE to it (``excludedNotApplicable``),
which is a different statement from unknown.

PAGING is a cursor, not an offset: ``(beforeDate, skip)`` names a position in
the ledger's fixed order (date descending, then trade id) — "start at the
rows dated ``beforeDate``, after the first ``skip`` of them".  Each page scans
from its own position, so a page that hit the scan bound hands back a cursor
where it stopped and the next page continues past it; an offset would rescan
from the newest row and could never get beyond the bound.  The cursor holds a
date and a count only — never a trade id.

NOT A FILTER: an approximate package value band.  Valuing a historical trade
needs values AT THE TIME of the trade (Trade History spec — at-the-time grade
uses the closest snapshot at or before the trade); today's values would
filter on how a trade aged.  Stamped on every response as ``notSupported``.

No value is read or computed here; nothing is graded.  Missing is never zero:
no ledger is ``unavailable``; a scan that hit its bound says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.trade import market_trade_format as mtf
from src.trade import market_trade_reference as ref
from src.trade import market_trade_report as report

DEFAULT_LIMIT = 25
MAX_LIMIT = 50
MAX_SKIP = 100_000
#: How far back the database may be browsed.  A display bound only.
MAX_LOOKBACK_DAYS = 3 * 365
DEFAULT_LOOKBACK_DAYS = ref.RECENT_LOOKBACK_DAYS
#: Visible-or-not rows examined per request, newest first.
MAX_SCAN = 5000

SOURCES = (ref.SOURCE_KTC, ref.SOURCE_SHARP, ref.SOURCE_OWN)
ASSET_MIXES = ("players", "picks", "mixed")

NOT_SUPPORTED = {
    "valueBand": (
        "An approximate package value band needs each trade valued at the time it "
        "happened; today's values would filter on how the trade aged."
    ),
}


class FilterError(ValueError):
    """A filter value the database cannot interpret (the route's 400)."""


@dataclass(frozen=True)
class TradeFilters:
    player_ids: Sequence[str] = ()
    pick_names: Sequence[str] = ()
    pick_asset_ids: Sequence[str] = ()
    since: str | None = None
    until: str | None = None
    superflex: bool | None = None
    teams: int | None = None
    starters: int | None = None
    idp: bool | None = None
    te_scoring_edge: bool | None = None
    ktc_tep_level: int | None = None
    source: str | None = None
    shape: tuple[int, ...] | None = None
    asset_mix: str | None = None

    def echo(self) -> dict[str, Any]:
        return {
            "since": self.since,
            "until": self.until,
            "superflex": self.superflex,
            "teams": self.teams,
            "starters": self.starters,
            "idp": self.idp,
            "teScoringEdge": self.te_scoring_edge,
            "ktcTepLevel": self.ktc_tep_level,
            "source": self.source,
            "shape": "x".join(str(n) for n in self.shape) if self.shape else None,
            "assetMix": self.asset_mix,
        }


def parse_shape(raw: str | None) -> tuple[int, ...] | None:
    """``"2x1"`` / ``"1x1x1"`` → sizes, largest first.  ``None`` for empty."""
    text = str(raw or "").strip().lower()
    if not text:
        return None
    try:
        sizes = tuple(sorted((int(p) for p in text.split("x")), reverse=True))
    except ValueError as err:
        raise FilterError("shape must look like 2x1") from err
    if len(sizes) < 2 or any(n < 1 or n > 20 for n in sizes):
        raise FilterError("shape needs at least two sides of 1-20 assets")
    return sizes


def _parse_date(raw: str | None, name: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as err:
        raise FilterError(f"{name} must be an ISO date (YYYY-MM-DD)") from err


def normalize_filters(filters: TradeFilters, today: date) -> tuple[TradeFilters, list[str]]:
    """Validate and bound the window; returns the effective filters and notes.
    With no ``since`` the window reaches ``DEFAULT_LOOKBACK_DAYS`` back from
    ``until`` (or today) — an ``until``-only request is anchored on ``until``."""
    notes: list[str] = []
    floor = (today - timedelta(days=MAX_LOOKBACK_DAYS)).isoformat()
    until = _parse_date(filters.until, "until")
    if until is not None and until < floor:
        raise FilterError(f"until is older than the database reaches back ({floor})")
    anchor = date.fromisoformat(until) if until else today
    since = _parse_date(filters.since, "since") or (
        (anchor - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()
    )
    if since < floor:
        notes.append(f"since_clamped_to_{floor}")
        since = floor
    if until is not None and until < since:
        raise FilterError("until is before since")
    if filters.source is not None and filters.source not in SOURCES:
        raise FilterError(f"source must be one of {', '.join(SOURCES)}")
    if filters.asset_mix is not None and filters.asset_mix not in ASSET_MIXES:
        raise FilterError(f"assetMix must be one of {', '.join(ASSET_MIXES)}")
    if filters.ktc_tep_level is not None and filters.ktc_tep_level not in (0, 1, 2, 3):
        raise FilterError("ktcTepLevel must be 0-3")
    for name, value in (("teams", filters.teams), ("starters", filters.starters)):
        if value is not None and not (1 <= value <= 64):
            raise FilterError(f"{name} must be between 1 and 64")
    return (
        TradeFilters(**{**filters.__dict__, "since": since, "until": until}),
        notes,
    )


#: (filter attribute, formatTags key) for the equality format filters.
_FORMAT_FILTERS = (
    ("superflex", "superflex"),
    ("teams", "teams"),
    ("starters", "starters"),
    ("idp", "idp"),
    ("te_scoring_edge", "teScoringEdge"),
    ("ktc_tep_level", "ktcTepLevel"),
)


def _asset_mix(row: Mapping[str, Any]) -> str | None:
    kinds = {a.get("kind") for side in row["sides"] for a in side}
    picks = "pick" in kinds
    players = bool(kinds & {"player", "unresolved"})
    if picks and players:
        return "mixed"
    if picks:
        return "picks"
    if players:
        return "players"
    return None


def row_passes(
    row: Mapping[str, Any],
    f: TradeFilters,
    excluded_unknown: dict[str, int],
    excluded_na: dict[str, int] | None = None,
) -> bool:
    """Whether a projected row satisfies every filter.  A format filter on an
    unknown field excludes the row and is counted in ``excluded_unknown``; the
    KTC-only filter on a non-KTC row is counted in ``excluded_na``."""
    occurred = str(row.get("occurredDate") or "")[:10]
    if f.until and occurred > f.until:
        return False
    if f.source and f.source not in row["sourceFamilies"]:
        return False
    if f.shape:
        sizes = tuple(sorted((len(s) for s in row["sides"]), reverse=True))
        if sizes != f.shape:
            return False
    if f.asset_mix and _asset_mix(row) != f.asset_mix:
        return False
    tags = row["formatTags"]
    for attr, key in _FORMAT_FILTERS:
        want = getattr(f, attr)
        if want is None:
            continue
        if key == "ktcTepLevel" and tags.get("formatSource") != mtf.SOURCE_KTC:
            if excluded_na is not None:
                excluded_na[key] = excluded_na.get(key, 0) + 1
            return False
        have = tags.get(key)
        if have is None:
            excluded_unknown[key] = excluded_unknown.get(key, 0) + 1
            return False
        if have != want:
            return False
    return True


def browse_trades(
    league_key: str,
    filters: TradeFilters,
    *,
    limit: int = DEFAULT_LIMIT,
    before_date: str | None = None,
    skip: int = 0,
    names: Mapping[str, Mapping[str, Any]] | None = None,
    today: date | None = None,
    root: Path | None = None,
    privacy: Callable[[], ref.PrivacyContext] | None = None,
) -> dict[str, Any]:
    """The response body for ``/api/market/trades/database``.  Raises
    ``FilterError`` on an uninterpretable filter."""
    today = today or date.today()
    limit = max(1, min(int(limit), MAX_LIMIT))
    skip = max(0, min(int(skip), MAX_SKIP))
    f, notes = normalize_filters(filters, today)
    cursor_date = _parse_date(before_date, "beforeDate")
    if cursor_date is None:
        skip = 0
    # The page's upper bound: the cursor's date, never past the filter's.
    bounds = [d for d in (f.until, cursor_date) if d]
    page_until = min(bounds) if bounds else None
    q = ref.build_query(
        league_key,
        player_ids=f.player_ids,
        pick_names=f.pick_names,
        pick_asset_ids=f.pick_asset_ids,
    )
    base: dict[str, Any] = {
        "leagueKey": league_key,
        "filters": f.echo(),
        "query": {**q.accepted, "unresolved": q.unresolved},
        "notes": notes,
        "notSupported": dict(NOT_SUPPORTED),
        "maxLookbackDays": MAX_LOOKBACK_DAYS,
        "samplingBiases": list(report.KNOWN_SAMPLING_BIASES),
        "limit": limit,
        "cursor": {"beforeDate": cursor_date, "skip": skip} if cursor_date else None,
    }
    conn = report.open_canonical_ledger(root)
    if conn is None:
        return {
            **base,
            "state": "unavailable",
            "reason": "trade_ledger_not_built",
            "ledger": None,
            "trades": [],
            "hasMore": False,
            "nextCursor": None,
            "withheld": None,
        }
    asked_assets = any(
        str(v or "").strip() for v in (*f.player_ids, *f.pick_names, *f.pick_asset_ids)
    )
    asset_filtered = not q.empty()
    ctx: ref.PrivacyContext | None = None
    try:
        ledger = ref._ledger_summary(conn, f.since)
        if asked_assets and not asset_filtered:
            # Every asset ref was unresolvable: answer that, never "all trades".
            return {
                **base,
                "state": "no_assets",
                "reason": "asset_filter_unresolved",
                "ledger": ledger,
                "trades": [],
                "hasMore": False,
                "nextCursor": None,
                "withheld": None,
            }
        ctx = (privacy or ref.default_privacy_context)()
        names = names or {}
        rows = (
            report.read_ledger_trades(
                conn, asset_keys=sorted(q.keys()), since_date=f.since, until_date=page_until
            )
            if asset_filtered
            else report.read_ledger_window(conn, since_date=f.since, until_date=page_until)
        )
        withheld: dict[str, int] = {}
        excluded_unknown: dict[str, int] = {}
        excluded_na: dict[str, int] = {}
        page: list[dict[str, Any]] = []
        scanned = 0
        scan_capped = False
        next_cursor: dict[str, Any] | None = None
        cur_date: str | None = None
        on_date = 0
        for rec, full_format in rows:
            occurred = str(rec.get("occurredDate") or "")[:10]
            if occurred != cur_date:
                cur_date, on_date = occurred, 0
            position = {"beforeDate": occurred, "skip": on_date}
            on_date += 1
            if cursor_date and occurred == cursor_date and position["skip"] < skip:
                continue  # already shown by an earlier page
            if scanned >= MAX_SCAN:
                scan_capped = True
                next_cursor = position
                break
            scanned += 1
            visible, reason, own = ref.visibility(rec, league_key, ctx)
            if not visible:
                withheld[reason or "withheld"] = withheld.get(reason or "withheld", 0) + 1
                continue
            row = ref.project_trade(rec, full_format, q, league_key, names, own_this_league=own)
            if asset_filtered and not row["matchedAssets"]:
                continue
            if not row_passes(row, f, excluded_unknown, excluded_na):
                continue
            if len(page) < limit:
                page.append(row)
            else:
                next_cursor = position
                break
    finally:
        conn.close()
        if ctx is not None:
            ctx.close()
    return {
        **base,
        "state": "ok",
        "reason": None,
        "ledger": ledger,
        "trades": page,
        # True when a further page may hold rows: the page filled, or the scan
        # bound stopped this page early (the cursor resumes where it stopped).
        "hasMore": next_cursor is not None,
        "nextCursor": next_cursor,
        "scanned": scanned,
        "scanCapped": scan_capped,
        "withheld": withheld,
        "excludedUnknown": excluded_unknown,
        "excludedNotApplicable": excluded_na,
    }
