"""Parse the raw nflverse datasets into compact per-player records.

Input schemas (verified against the live assets, 2026-07-25):

contracts (``historical_contracts.csv.gz``)::

    player,position,team,is_active,year_signed,years,value,apy,
    guaranteed,apy_cap_pct,...,draft_year,...

    ``team`` is the franchise nickname ("Packers"), dollars are raw
    ints, ``is_active`` is TRUE/FALSE.  No gsis_id → name+position
    join through the unified mapper.

snap counts (``snap_counts_{season}.csv``)::

    game_id,pfr_game_id,season,game_type,week,player,pfr_player_id,
    position,team,opponent,offense_snaps,offense_pct,defense_snaps,
    defense_pct,st_snaps,st_pct

    One row per player-game; pct columns are 0-1 fractions.  No
    gsis_id → name+team+position join.

depth charts (``depth_charts_{season}.csv``)::

    dt,team,player_name,espn_id,gsis_id,pos_grp_id,pos_grp,pos_id,
    pos_name,pos_abb,pos_slot,pos_rank

    The file appends a full dated snapshot per scrape run; we keep
    only the newest ``dt`` per team.  Carries gsis_id → exact join.

Schema drift in any required column raises
:class:`SchemaRegressionError`, which the refresh CLI maps to exit
code 2 (same convention as ``scripts/fetch_fantasynavigator.py``).
"""

from __future__ import annotations

import csv
import gzip
import io
import logging
from pathlib import Path
from typing import Any, TextIO

from src.identity.unified_mapper import _load_overrides, resolve_player
from src.utils.name_clean import normalize_player_name, normalize_position

log = logging.getLogger(__name__)


class SchemaRegressionError(RuntimeError):
    """A dataset's shape changed out from under us (missing required
    columns, unparseable structure).  CLI exit code 2."""


# ── Required columns (subset check — extra columns are fine) ─────────

CONTRACTS_REQUIRED_COLS: frozenset[str] = frozenset(
    {
        "player",
        "position",
        "team",
        "is_active",
        "year_signed",
        "years",
        "value",
        "apy",
        "guaranteed",
    }
)
SNAPS_REQUIRED_COLS: frozenset[str] = frozenset(
    {
        "season",
        "game_type",
        "week",
        "player",
        "position",
        "team",
        "offense_snaps",
        "offense_pct",
        "defense_snaps",
        "defense_pct",
        "st_snaps",
        "st_pct",
    }
)
DEPTH_REQUIRED_COLS: frozenset[str] = frozenset(
    {
        "dt",
        "team",
        "player_name",
        "gsis_id",
        "espn_id",
        "pos_grp",
        "pos_abb",
        "pos_slot",
        "pos_rank",
    }
)

# ── Team normalization ───────────────────────────────────────────────

# Contracts carry franchise nicknames; Sleeper carries abbreviations.
_TEAM_NICKNAME_TO_ABBR: dict[str, str] = {
    "CARDINALS": "ARI",
    "FALCONS": "ATL",
    "RAVENS": "BAL",
    "BILLS": "BUF",
    "PANTHERS": "CAR",
    "BEARS": "CHI",
    "BENGALS": "CIN",
    "BROWNS": "CLE",
    "COWBOYS": "DAL",
    "BRONCOS": "DEN",
    "LIONS": "DET",
    "PACKERS": "GB",
    "TEXANS": "HOU",
    "COLTS": "IND",
    "JAGUARS": "JAX",
    "CHIEFS": "KC",
    "RAIDERS": "LV",
    "CHARGERS": "LAC",
    "RAMS": "LAR",
    "DOLPHINS": "MIA",
    "VIKINGS": "MIN",
    "PATRIOTS": "NE",
    "SAINTS": "NO",
    "GIANTS": "NYG",
    "JETS": "NYJ",
    "EAGLES": "PHI",
    "STEELERS": "PIT",
    "49ERS": "SF",
    "SEAHAWKS": "SEA",
    "BUCCANEERS": "TB",
    "TITANS": "TEN",
    "COMMANDERS": "WAS",
    # Legacy franchise names that can linger on active rows.
    "REDSKINS": "WAS",
    "FOOTBALL TEAM": "WAS",
    "WASHINGTON": "WAS",
}

# nflverse / PFR team codes → Sleeper-style codes.
_TEAM_CODE_ALIASES: dict[str, str] = {
    "LA": "LAR",
    "STL": "LAR",
    "SL": "LAR",
    "SD": "LAC",
    "OAK": "LV",
    "LVR": "LV",
    "WSH": "WAS",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
    "JAC": "JAX",
    "GNB": "GB",
    "KAN": "KC",
    "NWE": "NE",
    "NOR": "NO",
    "SFO": "SF",
    "TAM": "TB",
}


def normalize_team_code(team: str | None) -> str:
    t = str(team or "").strip().upper()
    return _TEAM_CODE_ALIASES.get(t, t)


def team_nickname_to_abbr(nickname: str | None) -> str:
    t = str(nickname or "").strip().upper()
    return _TEAM_NICKNAME_TO_ABBR.get(t, "")


# ── Depth-chart position mapping ─────────────────────────────────────

# ESPN depth-chart slot abbreviations → fantasy base position.
# Slots that map to "" (OL, punters, return/long-snap specialists)
# are dropped — they are never in the dynasty pool.
_DEPTH_ABB_TO_BASE: dict[str, str] = {
    "QB": "QB",
    "RB": "RB",
    "FB": "RB",
    "WR": "WR",
    "TE": "TE",
    "PK": "K",
    "LDE": "DL",
    "RDE": "DL",
    "DE": "DL",
    "LDT": "DL",
    "RDT": "DL",
    "DT": "DL",
    "NT": "DL",
    "LILB": "LB",
    "RILB": "LB",
    "ILB": "LB",
    "MLB": "LB",
    "WLB": "LB",
    "SLB": "LB",
    "OLB": "LB",
    "LB": "LB",
    "LCB": "DB",
    "RCB": "DB",
    "CB": "DB",
    "NB": "DB",
    "DB": "DB",
    "FS": "DB",
    "SS": "DB",
    "S": "DB",
}

_GAME_TYPE_ORDER: dict[str, int] = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}


def _to_int(value: Any) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _open_maybe_gzip(path: Path) -> TextIO:
    if path.name.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _check_columns(fieldnames: list[str] | None, required: frozenset[str], dataset: str) -> None:
    have = set(fieldnames or [])
    missing = sorted(required - have)
    if missing:
        raise SchemaRegressionError(
            f"{dataset}: missing required columns {missing} (have {sorted(have)})"
        )


# ── Contracts ────────────────────────────────────────────────────────


def parse_contracts(path: Path) -> list[dict[str, Any]]:
    """Active contracts only, one row per player (latest ``year_signed``
    wins when a player carries several active rows).

    Known upstream caveats (verified against the live asset — these
    are OTC data semantics, not parse bugs; documented for the UI):

    * ``team`` is the SIGNING franchise — a traded contract keeps its
      origin team (e.g. McCaffrey's active row says Panthers).
    * ``endYear`` = year_signed + years - 1 is approximate: OTC's
      ``years`` counts the newly signed years, so an in-contract
      extension's derived endYear can undershoot the real expiry.
    * The asset is rebuilt on OTC's cadence and can lag recent
      extensions by weeks.
    """
    best: dict[str, dict[str, Any]] = {}
    with _open_maybe_gzip(path) as fh:
        reader = csv.DictReader(fh)
        _check_columns(reader.fieldnames, CONTRACTS_REQUIRED_COLS, "contracts")
        for row in reader:
            if str(row.get("is_active") or "").strip().upper() != "TRUE":
                continue
            name = str(row.get("player") or "").strip()
            if not name:
                continue
            year_signed = _to_int(row.get("year_signed"))
            years = _to_int(row.get("years"))
            rec = {
                "name": name,
                "position": str(row.get("position") or "").strip().upper(),
                "team": team_nickname_to_abbr(row.get("team")),
                "apy": _to_int(row.get("apy")),
                "total": _to_int(row.get("value")),
                "guaranteed": _to_int(row.get("guaranteed")),
                "years": years,
                "yearSigned": year_signed,
                "endYear": (year_signed + years - 1)
                if year_signed is not None and years is not None
                else None,
            }
            key = f"{name.lower()}|{rec['position']}"
            prev = best.get(key)
            if prev is None or (rec["yearSigned"] or 0) > (prev["yearSigned"] or 0):
                best[key] = rec
    return list(best.values())


# ── Snap counts ──────────────────────────────────────────────────────


def parse_snap_counts(
    path: Path,
    *,
    season: int | None = None,
    through_week: int | None = None,
) -> list[dict[str, Any]]:
    """Per-game rows for one season, minimally typed.

    Defaults to the file's newest season and every week in it, which is
    what the live refresh wants and is byte-identical to the behaviour
    this function had before the two parameters existed.

    ``season`` / ``through_week`` make it an AS-OF read, and that is the
    whole point of them.  nflverse publishes ``snap_counts_{season}.csv``
    as one row per player *per game*, carrying ``season``, ``game_type``
    and ``week`` — the history is already in the file.  This function
    used to discard it with a newest-season filter and no week cutoff,
    which is why :mod:`consensus_edge.opportunity`'s ``snapTrend`` axis
    was described everywhere as "production-only and unmeasurable".  It
    is not: reconstructing what the axis would have said at week W is a
    predicate, not a collection problem.

    ``through_week`` is inclusive and applies within the chosen season.
    Postseason rows are ordered after the regular season by
    ``aggregate_snaps``' own sort, so a cutoff of 18 keeps the full REG
    slate and drops the playoffs — which is usually what an as-of replay
    at the end of the regular season means.

    One honest limit this cannot fix: the file is the CURRENT publication
    of that season.  If nflverse restates a past week, a replay sees the
    restatement rather than what was observable at the time.  That is a
    much smaller distortion than the rank-signal leakage
    ``consensus_edge.panel`` guards against, but it is not zero.
    """
    rows: list[dict[str, Any]] = []
    max_season: int | None = None
    with _open_maybe_gzip(path) as fh:
        reader = csv.DictReader(fh)
        _check_columns(reader.fieldnames, SNAPS_REQUIRED_COLS, "snap_counts")
        for row in reader:
            # Deliberately NOT named `season`: that is the as-of
            # parameter, and rebinding it here silently disabled it for
            # every row after the first.
            row_season = _to_int(row.get("season"))
            week = _to_int(row.get("week"))
            name = str(row.get("player") or "").strip()
            if row_season is None or week is None or not name:
                continue
            if max_season is None or row_season > max_season:
                max_season = row_season
            rows.append(
                {
                    "season": row_season,
                    "gameType": str(row.get("game_type") or "").strip().upper(),
                    "week": week,
                    "name": name,
                    "pfrId": str(row.get("pfr_player_id") or "").strip(),
                    "position": str(row.get("position") or "").strip().upper(),
                    "team": normalize_team_code(row.get("team")),
                    "offSnaps": _to_int(row.get("offense_snaps")) or 0,
                    "offPct": _to_float(row.get("offense_pct")) or 0.0,
                    "defSnaps": _to_int(row.get("defense_snaps")) or 0,
                    "defPct": _to_float(row.get("defense_pct")) or 0.0,
                    "stSnaps": _to_int(row.get("st_snaps")) or 0,
                    "stPct": _to_float(row.get("st_pct")) or 0.0,
                }
            )
    target = max_season if season is None else int(season)
    out = [r for r in rows if r["season"] == target]
    if through_week is not None:
        cutoff = int(through_week)
        out = [r for r in out if r["week"] <= cutoff]
    return out


def aggregate_snaps(rows: list[dict[str, Any]], *, recent_games: int = 3) -> list[dict[str, Any]]:
    """Collapse per-game rows into one summary per player.

    ``pct`` / ``recentPct`` are 0-100 with one decimal; ``trend`` is
    recent-minus-season (positive = usage climbing late).  ``side`` is
    whichever unit the player actually plays (more snaps wins):
    ``"offense"`` / ``"defense"``, or ``"st"`` for pure special-teamers
    (kickers — retained in the pool as K — live entirely in
    ``st_snaps``/``st_pct``; without this they'd publish a misleading
    "offense 0%" block).

    Aggregation identity: ``pfr_player_id`` when present.  The ID-less
    fallback is normalized name + position family WITHOUT team — a
    traded player's stints must aggregate into one season line, not
    split per team (both stints would resolve to the same Sleeper
    record and the last one would silently overwrite the block).  If
    two DISTINCT ID-less players collide on that key they betray
    themselves by playing the same week twice; such ambiguous groups
    are dropped with a warning rather than merged (same
    drop-don't-guess convention as the identity pipeline).
    """
    by_player: dict[str, list[dict[str, Any]]] = {}
    fallback_keys: set[str] = set()
    for r in rows:
        key = r["pfrId"]
        if not key:
            key = f"{normalize_player_name(r['name'])}|{normalize_position(r['position'])}"
            fallback_keys.add(key)
        by_player.setdefault(key, []).append(r)

    out: list[dict[str, Any]] = []
    for key, games in by_player.items():
        if key in fallback_keys:
            game_slots = [(g["gameType"], g["week"]) for g in games]
            if len(set(game_slots)) != len(game_slots):
                # Two rows in the same week can't be one human — this
                # ID-less key covers distinct players.  Merging would
                # publish a chimera; drop instead.
                log.warning(
                    "playerctx: dropping ambiguous ID-less snap aggregate %r "
                    "(%d rows, duplicate week entries)",
                    games[0]["name"],
                    len(games),
                )
                continue
        games.sort(key=lambda g: (_GAME_TYPE_ORDER.get(g["gameType"], 9), g["week"]))
        totals = {
            "defense": sum(g["defSnaps"] for g in games),
            "offense": sum(g["offSnaps"] for g in games),
            "st": sum(g["stSnaps"] for g in games),
        }
        # The unit with the MOST snaps wins — all three compared, so a
        # kicker with one trick-play offensive snap still classifies
        # "st", not "offense at ~0%".  Tie precedence (rare, equal
        # totals): defense > offense > st — ``max`` keeps the first of
        # the iteration order.  Degenerate all-zero rows keep the
        # legacy "offense" label.
        if any(totals.values()):
            side = max(("defense", "offense", "st"), key=lambda s: totals[s])
        else:
            side = "offense"
        pct_key = {"defense": "defPct", "offense": "offPct", "st": "stPct"}[side]
        pcts = [g[pct_key] * 100.0 for g in games]
        season_mean = sum(pcts) / len(pcts)
        recent = pcts[-recent_games:]
        recent_mean = sum(recent) / len(recent)
        last = games[-1]
        out.append(
            {
                "name": last["name"],
                "team": last["team"],
                "position": last["position"],
                "season": last["season"],
                "games": len(games),
                "side": side,
                "pct": round(season_mean, 1),
                "recentPct": round(recent_mean, 1),
                "trend": round(recent_mean - season_mean, 1),
            }
        )
    return out


# ── Depth charts ─────────────────────────────────────────────────────


def parse_depth_charts(path: Path, *, as_of: str | None = None) -> list[dict[str, Any]]:
    """Rows of the newest snapshot (``dt``) per team, fantasy slots only.

    Streaming single pass: the seasonal file replays every dated
    snapshot (35-55 MB); we keep only rows carrying each team's newest
    ``dt``.  ISO-8601 timestamps compare correctly as strings.

    ``as_of`` narrows "newest" to "newest at or before this timestamp",
    making the read reproducible for a past date.  Default None is
    unbounded and byte-identical to the behaviour before the parameter
    existed.

    Same observation as :func:`parse_snap_counts`: the file already
    contains the history — it appends a full dated snapshot per upstream
    scrape — and this function was the thing discarding it.

    The bound is matched against the same-length PREFIX of ``dt``, not
    the whole string.  ``dt`` is published as a full timestamp
    (``2026-07-25T08:57:25Z``), so a plain ``dt > as_of`` would make the
    natural bound ``"2026-07-25"`` drop that whole day rather than keep
    it — an off-by-one-day that reads as working code.  With a prefix
    comparison an ISO-8601 prefix at any granularity means what it looks
    like: ``"2026-07-25"`` selects through the end of that day,
    ``"2026-07-25T08"`` through the end of that hour.
    """
    latest: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    bound = str(as_of).strip() if as_of else None
    with _open_maybe_gzip(path) as fh:
        reader = csv.DictReader(fh)
        _check_columns(reader.fieldnames, DEPTH_REQUIRED_COLS, "depth_charts")
        for row in reader:
            dt = str(row.get("dt") or "").strip()
            team = normalize_team_code(row.get("team"))
            if not dt or not team:
                continue
            if bound is not None and dt[: len(bound)] > bound:
                continue
            base = _DEPTH_ABB_TO_BASE.get(str(row.get("pos_abb") or "").strip().upper(), "")
            if not base:
                continue  # OL / specialists — never in the dynasty pool
            name = str(row.get("player_name") or "").strip()
            if not name:
                continue
            rec = {
                "team": team,
                "name": name,
                "gsisId": str(row.get("gsis_id") or "").strip(),
                "espnId": str(row.get("espn_id") or "").strip(),
                "position": base,
                "depthPosition": str(row.get("pos_abb") or "").strip().upper(),
                "slot": _to_int(row.get("pos_slot")) or 0,
                "slotRank": _to_int(row.get("pos_rank")) or 0,
            }
            cur = latest.get(team)
            if cur is None or dt > cur[0]:
                latest[team] = (dt, [rec])
            elif dt == cur[0]:
                cur[1].append(rec)
    out: list[dict[str, Any]] = []
    for _, (_, recs) in sorted(latest.items()):
        out.extend(recs)
    return out


def compute_depth_ranks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stamp ``rank`` — the player's 1-based standing among his team's
    players at the same base position.

    Ordering is (slotRank asc, slot asc): all the pos_rank-1 starters
    across slots (LWR/RWR/SWR, LDE/RDE, ...) outrank every backup.  A
    player listed in several slots (e.g. LCB + NB) keeps his best one.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault((r["team"], r["position"]), []).append(r)

    out: list[dict[str, Any]] = []
    for members in grouped.values():
        members.sort(key=lambda r: (r["slotRank"], r["slot"]))
        seen: set[str] = set()
        rank = 0
        for r in members:
            ident = r["gsisId"] or r["espnId"] or r["name"].lower()
            if ident in seen:
                continue
            seen.add(ident)
            rank += 1
            rec = dict(r)
            rec["rank"] = rank
            out.append(rec)
    return out


# ── Join to the Sleeper pool ─────────────────────────────────────────

_RELEVANT_FAMILIES: frozenset[str] = frozenset({"QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"})


def build_sleeper_pool(players_dump: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Filter Sleeper's full ``/v1/players/nfl`` dump to the fantasy-
    relevant pool and canonicalize positions to family level so the
    unified mapper's name+position rungs compare like against like.
    """
    pool: dict[str, dict[str, Any]] = {}
    if not isinstance(players_dump, dict):
        return pool
    for pid, rec in players_dump.items():
        if not isinstance(rec, dict):
            continue
        if rec.get("active") is not True:
            continue
        fam = normalize_position(rec.get("position"))
        if fam not in _RELEVANT_FAMILIES:
            continue
        full = str(rec.get("full_name") or "").strip()
        if not full:
            first = str(rec.get("first_name") or "").strip()
            last = str(rec.get("last_name") or "").strip()
            full = f"{first} {last}".strip()
        pool[str(pid)] = {
            "player_id": str(pid),
            "full_name": full,
            "position": fam,
            "team": normalize_team_code(rec.get("team")),
            "gsis_id": str(rec.get("gsis_id") or "").strip(),
            "espn_id": str(rec.get("espn_id") or "").strip(),
        }
    return pool


def build_player_context(
    *,
    contracts: list[dict[str, Any]],
    snaps: list[dict[str, Any]],
    depth: list[dict[str, Any]],
    players_dir: dict[str, dict[str, Any]],
    min_confidence: float = 0.90,
    overrides_path: Path | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Join the three datasets to the Sleeper pool.

    Returns ``(records, stats)``.  Records are keyed by ``gsis_id``;
    when neither Sleeper nor the source row knows a player's gsis_id
    (Sleeper's gsis coverage is sparse — roughly a third of the active
    fantasy pool) the key falls back to ``"sleeper:<sleeper_id>"`` so
    a successful join is never thrown away.  ``sleeperIndex`` in the
    snapshot maps sleeper_id → record key either way, which is the
    lookup the profile UI actually uses.

    Depth-chart rows join by exact gsis/espn ID against the pool.
    Contracts and snap counts (which carry no gsis) join by the same
    deterministic name ladder the unified mapper implements
    (name+team+pos → name+pos → unique name, built here as O(1)
    indexes because ``resolve_player`` re-indexes the pool on every
    call).

    Manual overrides (``config/identity/id_overrides.json``, same file
    and loader as the unified mapper — ``overrides_path`` overrides the
    location for tests) genuinely get the last word: the override
    entries are reverse-indexed by normalized full_name / gsis_id /
    espn_id → sleeper_id and consulted after the deterministic rungs
    miss but BEFORE the fuzzy fallback, so an operator-pinned mapping
    beats a fuzzy guess and a source row that depends on an override is
    never dropped.  (``resolve_player`` alone can't do this for source
    rows — its override rung only fires when a ``sleeper_id`` is
    supplied, which external datasets never have.)  Residual misses
    still fall through to
    :func:`src.identity.unified_mapper.resolve_player` for its fuzzy
    layer.  Rows that still don't map to the Sleeper pool are dropped
    and counted.
    """
    overrides = _load_overrides(overrides_path)
    alias_by_name: dict[str, str] = {}
    alias_by_gsis: dict[str, str] = {}
    alias_by_espn: dict[str, str] = {}
    for sid, ov in overrides.items():
        if not isinstance(ov, dict):
            continue
        ov_name = normalize_player_name(str(ov.get("full_name") or ""))
        if ov_name:
            alias_by_name.setdefault(ov_name, str(sid))
        ov_gsis = str(ov.get("gsis_id") or "").strip()
        if ov_gsis:
            alias_by_gsis.setdefault(ov_gsis, str(sid))
        ov_espn = str(ov.get("espn_id") or "").strip()
        if ov_espn:
            alias_by_espn.setdefault(ov_espn, str(sid))

    by_gsis: dict[str, dict[str, Any]] = {}
    by_espn: dict[str, dict[str, Any]] = {}
    by_name_team_pos: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    by_name_pos: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for p in players_dir.values():
        if p.get("gsis_id"):
            by_gsis[p["gsis_id"]] = p
        if p.get("espn_id"):
            by_espn[p["espn_id"]] = p
        norm_name = normalize_player_name(p.get("full_name"))
        if not norm_name:
            continue
        pos = str(p.get("position") or "").upper()
        team = str(p.get("team") or "").upper()
        by_name_team_pos.setdefault((norm_name, team, pos), []).append(p)
        by_name_pos.setdefault((norm_name, pos), []).append(p)
        by_name.setdefault(norm_name, []).append(p)

    # Per-team sub-pools for the fuzzy tail: when a source row names a
    # team, fuzzy matching is scoped to that team's players only.
    pool_by_team: dict[str, dict[str, dict[str, Any]]] = {}
    for sid, p in players_dir.items():
        team = str(p.get("team") or "").upper()
        if team:
            pool_by_team.setdefault(team, {})[sid] = p

    resolve_cache: dict[tuple[str, str, str], dict[str, Any] | None] = {}

    def _sole(cands: list[dict[str, Any]] | None) -> tuple[dict[str, Any] | None, bool]:
        """(candidate, ambiguous): the candidate only when it is
        UNIQUE; ambiguous=True when the key covers several players."""
        if not cands:
            return None, False
        if len(cands) == 1:
            return cands[0], False
        return None, True

    def _resolve_by_name(name: str, team: str, position: str) -> dict[str, Any] | None:
        fam = normalize_position(position)
        team_u = (team or "").upper()
        key = (name.lower(), team_u, fam)
        if key in resolve_cache:
            return resolve_cache[key]
        norm_name = normalize_player_name(name)
        # Deterministic rungs accept only a UNIQUE candidate.  Two
        # active players sharing a normalized name + position family
        # are a real case (and a contract row can carry the SIGNING
        # team post-trade, so a team mismatch must not fall back to
        # "first one indexed" — that attaches data to the wrong
        # player).  Team match that narrows to exactly one wins;
        # otherwise ambiguity is only resolvable by a manual override,
        # never by guessing.
        #
        # The team rung is consulted ONLY when the source actually
        # supplied a team: with team_u == "" the key would pair the
        # name with pool players whose team is empty (free agents) — a
        # pseudo-match that would accept a lone FA before the
        # ambiguity check ever saw the rostered candidates.
        hit, ambiguous = (None, False)
        if team_u:
            hit, ambiguous = _sole(by_name_team_pos.get((norm_name, team_u, fam)))
        if hit is None and not ambiguous:
            hit, ambiguous = _sole(by_name_pos.get((norm_name, fam)))
        if hit is None and not ambiguous:
            hit, ambiguous = _sole(by_name.get(norm_name))
        if hit is None and norm_name in alias_by_name:
            # Manual override (id_overrides.json) — an operator-pinned
            # source-name → sleeper_id mapping settles ambiguity and
            # beats the fuzzy guess below.  ``resolve_player`` can't
            # reach its own override rung for source rows (it requires
            # a sleeper_id input), so the alias index is what makes
            # overrides effective here.
            hit = players_dir.get(alias_by_name[norm_name])
        if hit is None and not ambiguous:
            # Tail cases only: the mapper's fuzzy layer.  Too slow for
            # the hot path (it re-indexes the pool per call) but right
            # for the residue.  Never consulted for AMBIGUOUS names —
            # its candidate walk is first-match-wins, i.e. exactly the
            # arbitrary pick this rung refuses; without an override an
            # ambiguous row is dropped (drop-don't-guess).
            #
            # Team is DECISIVE here: ``resolve_player``'s fuzzy walk
            # ignores its team argument, so a closer-spelled player on
            # another team could steal the row.  When the source names
            # a team, fuzzy runs against that team's sub-pool only — a
            # team-matching candidate wins even at a lower score, and
            # if no same-team candidate clears min_confidence the row
            # drops rather than crossing teams.
            scope = pool_by_team.get(team_u, {}) if team_u else players_dir
            if scope:
                got = resolve_player(
                    scope,
                    name=name,
                    team=team_u or None,
                    position=fam or None,
                    min_confidence=min_confidence,
                )
                hit = scope.get(got.sleeper_id) if got else None
        resolve_cache[key] = hit
        return hit

    records: dict[str, dict[str, Any]] = {}
    stats = {
        "contracts": {"parsed": len(contracts), "matched": 0},
        "snapCounts": {"parsed": len(snaps), "matched": 0},
        "depthCharts": {"parsed": len(depth), "matched": 0},
        "noGsisFallback": 0,
    }

    key_by_sleeper: dict[str, str] = {}

    def _record_for(pool_rec: dict[str, Any], source_gsis: str = "") -> dict[str, Any]:
        # Key preference: Sleeper's gsis → the source row's gsis
        # (depth charts carry an authoritative one) → sleeper fallback.
        # ``key_by_sleeper`` pins one key per player so a depth pass
        # that learned a gsis and a later contract pass that didn't
        # can never split the same player into two records.
        sleeper_id = pool_rec["player_id"]
        key = key_by_sleeper.get(sleeper_id)
        if key is None:
            gsis = pool_rec.get("gsis_id") or source_gsis
            key = gsis or f"sleeper:{sleeper_id}"
            key_by_sleeper[sleeper_id] = key
            if not gsis:
                stats["noGsisFallback"] += 1
            records[key] = {
                "gsisId": gsis,
                "sleeperId": sleeper_id,
                "name": pool_rec["full_name"],
                "team": pool_rec["team"],
                "position": pool_rec["position"],
            }
        return records[key]

    for d in compute_depth_ranks(depth):
        pool_rec = by_gsis.get(d["gsisId"]) or by_espn.get(d["espnId"])
        if pool_rec is None and d["gsisId"] in alias_by_gsis:
            pool_rec = players_dir.get(alias_by_gsis[d["gsisId"]])
        if pool_rec is None and d["espnId"] in alias_by_espn:
            pool_rec = players_dir.get(alias_by_espn[d["espnId"]])
        if pool_rec is None:
            pool_rec = _resolve_by_name(d["name"], d["team"], d["position"])
        if pool_rec is None:
            continue
        rec = _record_for(pool_rec, source_gsis=d["gsisId"])
        stats["depthCharts"]["matched"] += 1
        rec["depth"] = {
            "position": d["position"],
            "rank": d["rank"],
            "depthPosition": d["depthPosition"],
            "team": d["team"],
        }

    for s in snaps:
        pool_rec = _resolve_by_name(s["name"], s["team"], s["position"])
        if pool_rec is None:
            continue
        rec = _record_for(pool_rec)
        stats["snapCounts"]["matched"] += 1
        rec["snaps"] = {
            "season": s["season"],
            "games": s["games"],
            "side": s["side"],
            "pct": s["pct"],
            "recentPct": s["recentPct"],
            "trend": s["trend"],
        }

    for c in contracts:
        pool_rec = _resolve_by_name(c["name"], c["team"], c["position"])
        if pool_rec is None:
            continue
        rec = _record_for(pool_rec)
        stats["contracts"]["matched"] += 1
        rec["contract"] = {
            "apy": c["apy"],
            "total": c["total"],
            "guaranteed": c["guaranteed"],
            "years": c["years"],
            "yearSigned": c["yearSigned"],
            "endYear": c["endYear"],
            "team": c["team"],
        }

    stats["players"] = len(records)
    return records, stats
