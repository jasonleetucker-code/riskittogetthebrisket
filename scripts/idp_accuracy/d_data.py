"""Lane D data layer: weekly scores, availability and fine positions for the best-ball study.

Research only (``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`` §8 and §13).
Nothing in ``src/`` imports this module and nothing here is served.

Inputs (all public, all cached once under the gitignored ``data/idp_accuracy/cache/`` and
hashed into the evidence file so a re-run can say whether it read the same bytes):

* Sleeper read API: league, rosters, the player directory, and the weekly stat lines for 2026
  weeks 1-6 and (SHAPE ONLY) 2025 weeks 1-18.
* nflverse-data release CSVs: ``rosters/roster_{2026,2025}.csv`` (fine position) and
  ``schedules/games.csv`` (bye weeks).

Scoring is the host-native path Lane A verified against Sleeper's awarded points
(``compute_weekly_points(..., source="sleeper")``, 3,710 / 3,710 within 0.01 on 2026 wk 1-6);
this module scores with the league's own card and never a hand-built one.  Earlier-season stat
lines are scored with the SAME 2026 card, which makes them a rescored SHAPE reference and not a
statement about what those seasons paid.

Week status vocabulary (never collapsed into a score of zero where the zero is not a fact):

``played``  the player appeared (``gp`` > 0, or any snap, or any non-zero points).
``dnp``     the player's team played, the player did not.  Best ball pays this 0.0.
``bye``     the player's team had no game (nflverse schedule).  Excluded, not zero.
``unknown`` the team cannot be established.  Excluded, not zero.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import time
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.nfl_data.realized_points import compute_weekly_points
from src.ros.lineup import lineup_position

REPO = Path(__file__).resolve().parents[2]

LEAGUE_KEY = "dynasty_main"
LEAGUE_ID = "1312006700437352448"
SEASON = 2026
WEEKS = (1, 2, 3, 4, 5, 6)
SHAPE_SEASON = 2025
SHAPE_WEEKS = tuple(range(1, 19))
#: Lane A's pinned scoring fingerprint; a mismatch means the card moved and every number is void.
PINNED_SCORING_FINGERPRINT = "sf1:9e51824690d091f9"
#: Fantasy weeks the remaining-season bye pattern is drawn from (playoffs run weeks 15-17).
REMAINING_FANTASY_WEEKS = tuple(range(7, 18))

SLEEPER = "https://api.sleeper.app/v1"
NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"
CACHE_DIR = REPO / "data/idp_accuracy/cache"
NFLVERSE_DIR = CACHE_DIR / "nflverse"
NFLVERSE_FILES = {
    "roster_2026": "rosters/roster_2026.csv",
    "roster_2025": "rosters/roster_2025.csv",
    "games": "schedules/games.csv",
}

IDP_FAMILIES = ("DL", "LB", "DB")
OFFENSE_POSITIONS = ("QB", "RB", "WR", "TE", "K")
#: nflverse -> Sleeper team abbreviation differences.
TEAM_ALIAS = {"LA": "LAR", "JAC": "JAX", "WSH": "WAS", "OAK": "LV", "SD": "LAC", "STL": "LAR"}

#: Sleeper injury_status / status values that mean "not available to play for the foreseeable future".
UNAVAILABLE_INJURY = frozenset({"out", "ir", "pup", "sus", "na", "dnr", "nfi"})
UNAVAILABLE_STATUS = frozenset(
    {"injured reserve", "inactive", "suspended", "pup", "nfi", "reserve/injured", "retired"}
)

# Fine position vocabulary (nflverse ``depth_chart_position``) -> study fine position.
_FINE = {
    "DE": "DE",
    "DT": "DT",
    "NT": "DT",
    "OLB": "OLB",
    "ILB": "ILB",
    "MLB": "ILB",
    "CB": "CB",
    "FS": "S",
    "SS": "S",
    "S": "S",
}
FINE_POSITIONS = ("DE", "DT", "OLB", "ILB", "CB", "S")


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha256(obj: Any) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


class Fetcher:
    """Cached, throttled GET of public endpoints.  A cached body is REUSED unless it is absent.

    The Sleeper cache key is ``sha256(url)[:24]``, the same scheme the other IDP-accuracy lanes
    use, so a body one lane fetched is a body the others read.  Public, unauthenticated GETs
    only, throttled under 5 requests / second.
    """

    MIN_INTERVAL_S = 0.25

    def __init__(self, *, offline: bool = False) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        NFLVERSE_DIR.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self._last = 0.0
        self.receipts: dict[str, dict[str, Any]] = {}

    def _http(self, url: str) -> bytes:
        if self.offline:
            raise RuntimeError(f"offline and not cached: {url}")
        wait = self.MIN_INTERVAL_S - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(
            url, headers={"User-Agent": "brisket-idp-accuracy-research/1.0"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - public https GET
            blob = resp.read()
        self._last = time.time()
        return blob

    def sleeper(self, path: str) -> Any:
        url = f"{SLEEPER}/{path}"
        cache = CACHE_DIR / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.json"
        if not cache.exists():
            cache.write_bytes(self._http(url))
        blob = cache.read_bytes()
        self.receipts[f"sleeper:{path}"] = {
            "sha256": sha256_bytes(blob),
            "bytes": len(blob),
            "fetchedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cache.stat().st_mtime)),
        }
        return json.loads(blob)

    def nflverse(self, key: str) -> list[dict[str, str]]:
        rel = NFLVERSE_FILES[key]
        cache = NFLVERSE_DIR / rel.replace("/", "__")
        if not cache.exists():
            cache.write_bytes(self._http(f"{NFLVERSE_BASE}/{rel}"))
        blob = cache.read_bytes()
        self.receipts[f"nflverse:{rel}"] = {
            "sha256": sha256_bytes(blob),
            "bytes": len(blob),
            "fetchedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cache.stat().st_mtime)),
        }
        return list(csv.DictReader(io.StringIO(blob.decode("utf-8"))))


# ── fine position and eligibility ────────────────────────────────────────────


def _clean_id(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

#: Sleeper's own ``depth_chart_position`` vocabulary -> study fine position (fallback source only).
_SLEEPER_DEPTH = {
    "LDE": "DE",
    "RDE": "DE",
    "LDT": "DT",
    "RDT": "DT",
    "NT": "DT",
    "LOLB": "OLB",
    "ROLB": "OLB",
    "SLB": "OLB",
    "WLB": "OLB",
    "LILB": "ILB",
    "RILB": "ILB",
    "MLB": "ILB",
    "LCB": "CB",
    "RCB": "CB",
    "NB": "CB",
    "SS": "S",
    "FS": "S",
}


def name_key(name: Any) -> str:
    """Lower-case alphanumeric tokens with generational suffixes removed (join key only)."""
    toks = "".join(ch if ch.isalnum() else " " for ch in str(name or "").lower()).split()
    return " ".join(t for t in toks if t not in _SUFFIXES)


@dataclass(frozen=True)
class FineIndex:
    """nflverse fine-position lookups, with provenance of every join."""

    by_sleeper: dict[str, tuple[str, str]]  # sleeper_id -> (raw depth_chart_position, source file)
    by_gsis: dict[str, tuple[str, str]]
    by_name_team: dict[tuple[str, str], list[tuple[str, str]]]


def build_fine_index(roster_2026: list[dict], roster_2025: list[dict]) -> FineIndex:
    by_s: dict[str, tuple[str, str]] = {}
    by_g: dict[str, tuple[str, str]] = {}
    by_nt: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    # 2025 first so 2026 overwrites: the newest assignment wins.
    for fname, rows in (("roster_2025", roster_2025), ("roster_2026", roster_2026)):
        for r in rows:
            raw = (r.get("depth_chart_position") or r.get("position") or "").strip().upper()
            if not raw:
                continue
            sid = _clean_id(r.get("sleeper_id"))
            gid = _clean_id(r.get("gsis_id"))
            if sid:
                by_s[sid] = (raw, fname)
            if gid:
                by_g[gid] = (raw, fname)
            team = _team(r.get("team"))
            if team and fname == "roster_2026":
                by_nt[(name_key(r.get("full_name")), team)].append((raw, fname))
    return FineIndex(by_s, by_g, dict(by_nt))


def resolve_fine(pid: str, meta: dict[str, Any], idx: FineIndex) -> tuple[str, str]:
    """(fine position, provenance) for an IDP player, or ("UNKNOWN", reason).

    Join order, each tried only if the one before found nothing, provenance naming the key and
    file: ``sleeper_id`` -> ``gsis_id`` -> unique ``name+team`` (2026 rookies are in the nflverse
    roster without a Sleeper id) -> Sleeper's own ``depth_chart_position`` (labelled
    ``sleeper_depth_chart``, a different publisher, used only when nflverse is silent).  A raw
    value outside the six study positions (a generic ``LB`` / ``DB`` / ``DL``) is UNKNOWN: the
    data does not say which kind of linebacker he is, and guessing from his stats would be
    circular.  An ambiguous name+team (two rows) is UNKNOWN, never a coin flip.
    """
    hit = idx.by_sleeper.get(pid)
    how = "sleeper_id"
    if hit is None:
        gid = _clean_id(meta.get("gsis_id"))
        hit = idx.by_gsis.get(gid) if gid else None
        how = "gsis_id"
    if hit is None:
        team = _team(meta.get("team"))
        cands = idx.by_name_team.get((name_key(meta.get("full_name")), team)) if team else None
        if cands and len(cands) == 1:
            hit, how = cands[0], "name_team"
        elif cands:
            return "UNKNOWN", "ambiguous_name_team"
    if hit is not None:
        raw, fname = hit
        fine = _FINE.get(raw)
        if fine is not None:
            return fine, f"{how}:{fname}"
        generic = f"nflverse_generic_position:{raw}"
    else:
        generic = "no_nflverse_roster_match"
    sd = _SLEEPER_DEPTH.get(str(meta.get("depth_chart_position") or "").strip().upper())
    if sd is not None:
        return sd, "sleeper_depth_chart"
    return "UNKNOWN", generic


def archetype_for(fine: str, position_group: str, fantasy_positions: tuple[str, ...]) -> str:
    """The pre-registered archetype label.  Uses provenance fields only, never performance.

    ``EDGE``  = nflverse DE, or an OLB the host also lists at DL (a rusher by the host's own
                eligibility).  ``OLB`` is the remaining outside linebackers.
    ``DT``    = DT / NT.  ``ILB`` = ILB / MLB.  ``CB`` = CB.  ``S`` = FS / SS / S.
    A defender whose fine position cannot be resolved is ``UNK_<family>`` and is reported but
    never merged into a fine archetype.  Offense is labelled by position.
    """
    if position_group in OFFENSE_POSITIONS:
        return position_group
    if fine == "DE":
        return "EDGE"
    if fine == "OLB":
        return "EDGE" if "DL" in fantasy_positions else "OLB"
    if fine in ("DT", "ILB", "CB", "S"):
        return fine
    return f"UNK_{position_group}"


# ── schedule and byes ─────────────────────────────────────────────────────────


def _team(t: str | None) -> str | None:
    if not t:
        return None
    t = t.strip().upper()
    return TEAM_ALIAS.get(t, t)


def schedule_weeks(games: list[dict[str, str]], season: int) -> dict[str, set[int]]:
    """team -> set of REG weeks in which that team plays."""
    played: dict[str, set[int]] = defaultdict(set)
    for g in games:
        if g.get("season") != str(season) or g.get("game_type") != "REG":
            continue
        wk = int(g["week"])
        for side in ("away_team", "home_team"):
            t = _team(g.get(side))
            if t:
                played[t].add(wk)
    return dict(played)


def bye_weeks(play: dict[str, set[int]], max_week: int = 18) -> dict[str, int | None]:
    """team -> its bye week within 1..max_week (None if it plays every week)."""
    out: dict[str, int | None] = {}
    for t, wks in play.items():
        missing = [w for w in range(1, max_week + 1) if w not in wks]
        out[t] = missing[0] if len(missing) == 1 else (None if not missing else missing[0])
    return out


# ── weekly observations ───────────────────────────────────────────────────────

_META_KEYS = {"season", "week", "season_type", "player_id", "gp", "gs", "gms_active"}


@dataclass
class WeekObs:
    status: str  # played | dnp | bye | unknown
    points: float | None  # None unless status == "played" (dnp is 0.0 for best ball, kept separate)
    def_snaps: float | None = None
    team_def_snaps: float | None = None
    off_snaps: float | None = None
    team_off_snaps: float | None = None
    #: raw counts of the priced defensive events (played weeks only)
    events: dict[str, float] | None = None


#: Host stat keys whose weekly COUNTS are the "verified event rates" of the IDP model.
EVENT_KEYS = (
    "idp_tkl_solo",
    "idp_tkl_ast",
    "idp_tkl_loss",
    "idp_sack",
    "idp_qb_hit",
    "idp_pass_def",
    "idp_int",
    "idp_ff",
    "idp_fum_rec",
)


@dataclass
class PlayerSeason:
    pid: str
    weeks: dict[int, WeekObs] = field(default_factory=dict)
    #: awarded points by scoring key over played weeks (event-mix profile)
    key_points: dict[str, float] = field(default_factory=dict)

    def played_points(self) -> list[float]:
        return [
            o.points for o in self.weeks.values() if o.status == "played" and o.points is not None
        ]

    def best_ball_points(self) -> list[float]:
        """Per non-bye week: the points best ball pays (DNP is a real 0.0)."""
        out = []
        for w in sorted(self.weeks):
            o = self.weeks[w]
            if o.status == "played" and o.points is not None:
                out.append(o.points)
            elif o.status == "dnp":
                out.append(0.0)
        return out


def _num(v: Any) -> float:
    if isinstance(v, bool) or v is None:
        return 0.0
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def build_season(
    stats_by_week: dict[int, dict[str, dict]],
    directory: dict[str, dict],
    card: dict[str, float],
    play: dict[str, set[int]],
    season: int,
    weeks: tuple[int, ...],
) -> dict[str, PlayerSeason]:
    """Score every host player's stat lines and classify every (player, week).

    Players enter the result when they have a stat line in any of ``weeks``.  A rostered player
    with no line in any week has no observation at all, which is the honest state: UNKNOWN, not
    a season of zeros.
    """
    out: dict[str, PlayerSeason] = {}
    for w in weeks:
        for pid, line in (stats_by_week.get(w) or {}).items():
            meta = directory.get(pid)
            if meta is None:
                continue
            pos = lineup_position(str(meta.get("position") or ""))
            row = {**line, "player_id": pid, "season": season, "week": w}
            res = compute_weekly_points(row, card, position=pos, source="sleeper")
            if res is None:  # team entry or refused row
                continue
            ps = out.setdefault(pid, PlayerSeason(pid))
            pts = float(res.fantasy_points)
            appeared = (
                _num(line.get("gp")) > 0
                or _num(line.get("def_snp")) > 0
                or _num(line.get("off_snp")) > 0
                or abs(pts) > 1e-9
            )
            team = _team(meta.get("team"))
            team_plays = team is not None and w in play.get(team, set())
            team_bye = team is not None and team in play and w not in play[team]
            if appeared:
                status = "played"
            elif team_bye:
                status = "bye"
            elif (
                team_plays or _num(line.get("gms_active")) > 0 or line.get("tm_def_snp") is not None
            ):
                status = "dnp"
            else:
                status = "unknown"
            ps.weeks[w] = WeekObs(
                status=status,
                points=pts if status == "played" else None,
                def_snaps=line.get("def_snp"),
                team_def_snaps=line.get("tm_def_snp"),
                off_snaps=line.get("off_snp"),
                team_off_snaps=line.get("tm_off_snp"),
                events={k: _num(line.get(k)) for k in EVENT_KEYS} if status == "played" else None,
            )
            if status == "played":
                for comp in res.components or ():
                    key, _raw, _rate, awarded = comp
                    if awarded:
                        ps.key_points[key] = ps.key_points.get(key, 0.0) + float(awarded)
    # A player-week with NO line: classify from the team's schedule.
    for pid, ps in out.items():
        meta = directory.get(pid) or {}
        team = _team(meta.get("team"))
        for w in weeks:
            if w in ps.weeks:
                continue
            if team is None or team not in play:
                ps.weeks[w] = WeekObs("unknown", None)
            elif w not in play[team]:
                ps.weeks[w] = WeekObs("bye", None)
            else:
                ps.weeks[w] = WeekObs("dnp", None)
    return out


# ── everything the analysis needs, in one object ──────────────────────────────


@dataclass
class Inputs:
    league: dict[str, Any]
    card: dict[str, float]
    fingerprint: str | None
    slots: list[str]  # starting slots only (BN removed)
    directory: dict[str, dict]
    rosters: list[list[str]]  # per team, in roster_id order
    season26: dict[str, PlayerSeason]
    season25: dict[str, PlayerSeason]
    fine: dict[str, tuple[str, str]]  # pid -> (fine, provenance)
    play26: dict[str, set[int]]
    bye26: dict[str, int | None]
    receipts: dict[str, dict[str, Any]]
    canonical_rows_sha256: str


def load_inputs(*, offline: bool = False) -> Inputs:
    f = Fetcher(offline=offline)
    league = f.sleeper(f"league/{LEAGUE_ID}")
    rosters = f.sleeper(f"league/{LEAGUE_ID}/rosters")
    directory = f.sleeper("players/nfl")
    card = {str(k): float(v) for k, v in (league.get("scoring_settings") or {}).items()}
    fp = scoring_fingerprint(league.get("scoring_settings"))
    slots = [s for s in league["roster_positions"] if s not in ("BN", "IR", "TAXI")]
    games = f.nflverse("games")
    play26 = schedule_weeks(games, SEASON)
    play25 = schedule_weeks(games, SHAPE_SEASON)
    r26 = f.nflverse("roster_2026")
    r25 = f.nflverse("roster_2025")
    stats26 = {w: f.sleeper(f"stats/nfl/regular/{SEASON}/{w}") for w in WEEKS}
    stats25 = {w: f.sleeper(f"stats/nfl/regular/{SHAPE_SEASON}/{w}") for w in SHAPE_WEEKS}
    s26 = build_season(stats26, directory, card, play26, SEASON, WEEKS)
    s25 = build_season(stats25, directory, card, play25, SHAPE_SEASON, SHAPE_WEEKS)
    idx = build_fine_index(r26, r25)
    fine = {}
    for pid in set(s26) | set(s25):
        meta = directory.get(pid) or {}
        if lineup_position(str(meta.get("position") or "")) in IDP_FAMILIES:
            fine[pid] = resolve_fine(pid, meta, idx)
    rows_hash = canonical_sha256(
        {
            "2026": {
                p: [(w, o.status, o.points) for w, o in sorted(s.weeks.items())]
                for p, s in sorted(s26.items())
            },
        }
    )
    return Inputs(
        league=league,
        card=card,
        fingerprint=fp,
        slots=slots,
        directory=directory,
        rosters=[
            [str(p) for p in (r.get("players") or [])]
            for r in sorted(rosters, key=lambda r: r["roster_id"])
        ],
        season26=s26,
        season25=s25,
        fine=fine,
        play26=play26,
        bye26=bye_weeks(play26),
        receipts=f.receipts,
        canonical_rows_sha256=rows_hash,
    )


def eligibility_tuple(meta: dict[str, Any]) -> tuple[str, ...]:
    """The host's own eligibility: ``fantasy_positions`` widened by ``position``, lineup vocabulary."""
    fp = [lineup_position(str(x)) for x in (meta.get("fantasy_positions") or [])]
    pos = lineup_position(str(meta.get("position") or ""))
    return tuple(sorted({p for p in fp + [pos] if p}))


def is_forward_unavailable(meta: dict[str, Any]) -> bool:
    inj = str(meta.get("injury_status") or "").strip().lower()
    st = str(meta.get("status") or "").strip().lower()
    return inj in UNAVAILABLE_INJURY or st in UNAVAILABLE_STATUS
