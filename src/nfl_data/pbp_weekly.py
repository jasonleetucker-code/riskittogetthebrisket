"""Per-player-week scoring stats that ONLY play-by-play can supply.

Why this exists
───────────────
``dynasty_main``'s card pays ten rules that the nflverse **weekly** feed
does not publish as columns, so the realized-points engine scored them
at nothing and the site reported a total that was quietly low:

    rec_0_4  rec_5_9  rec_10_19  rec_20_29  rec_30_39  rec_40p
    st_tkl_solo  st_ff  st_fum_rec  pass_int_td

Measured on the league host's own week-14 2025 dump that is 451.53
points in one week — ~7,676 across a regular season, roughly two thirds
of it the six reception bands. ``scoring_coverage`` called them
UNSCORABLE, which was true of the *weekly* feed and false of the world:
every one of them is deterministic from nflverse play-by-play, which is
already a configured source.

This module is the join. It streams one season of play-by-play once and
emits, per (player, week), a stat line in **Sleeper's own vocabulary**,
so :func:`src.nfl_data.realized_points.compute_weekly_points` can merge
it into the normalized weekly line and the canonical scorer's dot
product picks the rules up with no new scoring code.

What it does NOT do
───────────────────
It derives nothing the weekly feed already carries. ``kr_yd``, ``pr_yd``
and ``st_td`` are on that feed and are scored from it; deriving them
here as well would be a second owner for the same number, and the two
would disagree the first time a play was re-charted.

The predicates, and what they were measured against
───────────────────────────────────────────────────
Every rule below was validated against Sleeper's OWN weekly stat dumps
— ``/v1/stats/nfl/regular/2025/{week}`` — for 2025 REG weeks 1, 3, 5, 8,
11, 14 and 17, restricted to player entries. This is the same host-truth
convention ``tests/nfl_data/test_realized_points_host_truth.py`` uses.

**Reception bands** — ``complete_pass``, credited to
``receiver_player_id``, banded on ``receiving_yards`` where present and
``yards_gained`` otherwise (they diverge on laterals, where
``yards_gained`` includes yardage the receiver was not credited with).
Banding is :func:`src.nfl_data.reception_depth.band_for_yards`, which is
the single owner of what a band IS; a negative-yardage catch is a
reception in no band. **All six bands reconcile to the host exactly on
every one of the seven sampled weeks** — 42 of 42 cells, on both player
count and reception count.

**``st_tkl_solo``** — ``special_teams_play``, crediting
``solo_tackle_1/2_player_id`` plus ``tackle_with_assist_1/2_player_id``.
The tackle-with-assist columns are load-bearing: solo-only lands 748 of
759 over the sample, and adding them lands **758 of 759, exact in six of
the seven weeks**. The one residual (week 3, one tackle) is a per-play
charting difference between nflverse and the gamebook Sleeper reads, not
a rule difference — week 1's other candidate, a blocked-field-goal
return that nflverse does not flag as a special-teams play, is charged
by neither side. Scoping by ``play_type`` instead of the flag scores
that play and is measurably WORSE (759 of 759 in total but wrong in both
directions), so the flag is what is used.

**``st_ff``** — ``special_teams_play`` +
``forced_fumble_player_1/2_player_id``. Exact on all seven weeks (10 of
10 events).

**``st_fum_rec``** — ``special_teams_play`` +
``fumble_recovery_N_player_id`` **where the recovering team is not the
fumbling team**. That constraint is the whole rule: counting every
recovery scores 20 events against the host's 8, because recovering your
own muff is not a takeaway. Exact on all seven weeks (8 of 8).

**``pass_int_td``** — the passer's pick-six penalty:
``interception`` + ``return_touchdown`` **and the touchdown scored by a
team other than the offense**, charged to ``passer_player_id``. The last
clause is the whole rule: in week 5 Cam Ward threw an interception that
the defender fumbled back on the return and Tennessee recovered in the
end zone. ``return_touchdown`` is 1, and it is not a pick-six. With the
clause: exact on all seven weeks (12 of 12); without it, week 5 charges
a quarterback -2 points he did not concede.

Missing is not zero
───────────────────
A week that was never streamed and a week in which a player recorded
none of these events are different facts and are represented
differently: :class:`PbpWeeklyStats` returns ``None`` for an uncovered
week and ``{}`` for a covered one. ``compute_weekly_points`` turns the
first into an explicit ``unscored`` list on the result and the second
into real zeroes.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from src.nfl_data.reception_depth import (
    PBP_URL_TEMPLATE,
    band_for_yards,
    open_pbp,
    season_has_plausibly_started,
)
from src.nfl_data.realized_points import PBP_SUPPLEMENT_KEYS, PBP_SUPPLEMENT_ROW_KEY

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "PBP_WEEKLY_SCHEMA_VERSION",
    "PbpWeeklyStats",
    "SeasonPbpIndex",
    "accumulate_weekly",
    "attach_supplement",
    "gsis_of_row",
    "default_pbp_weekly_dir",
    "load_pbp_weekly",
    "persist_pbp_weekly",
    "pbp_weekly_path",
]

PBP_WEEKLY_SCHEMA_VERSION = "2026-08-18.v1"

#: Truthy spellings nflverse uses for its boolean-ish columns.
_TRUE = frozenset({"1", "1.0", "True", "true", "TRUE"})

#: Columns whose absence means the release schema moved under us. A
#: renamed column must never read as "nothing happened this season" —
#: that is how the 2025 weekly-stats rename went unnoticed (#589).
_REQUIRED_COLUMNS: tuple[str, ...] = (
    "week",
    "season_type",
    "complete_pass",
    "receiver_player_id",
    "special_teams_play",
    "solo_tackle_1_player_id",
    "forced_fumble_player_1_player_id",
    "fumble_recovery_1_player_id",
    "interception",
    "return_touchdown",
    "passer_player_id",
    "posteam",
    "td_team",
)

#: Tackler id columns credited to ``st_tkl_solo`` on a special-teams play.
_ST_TACKLE_COLUMNS: tuple[str, ...] = (
    "solo_tackle_1_player_id",
    "solo_tackle_2_player_id",
    "tackle_with_assist_1_player_id",
    "tackle_with_assist_2_player_id",
)

_ST_FORCED_FUMBLE_COLUMNS: tuple[str, ...] = (
    "forced_fumble_player_1_player_id",
    "forced_fumble_player_2_player_id",
)

#: Fumble-recovery slots, as ``(player id, recovering team, fumbling team)``.
_FUMBLE_RECOVERY_SLOTS: tuple[tuple[str, str, str], ...] = (
    ("fumble_recovery_1_player_id", "fumble_recovery_1_team", "fumbled_1_team"),
    ("fumble_recovery_2_player_id", "fumble_recovery_2_team", "fumbled_2_team"),
)


def _cell(row: Sequence[str], i: int) -> str:
    if i < 0 or i >= len(row):
        return ""
    value = row[i].strip()
    return "" if value == "NA" else value


def _iter_plays(lines: Iterable[str]) -> Iterator[tuple[int, str, dict[str, list[str]]]]:
    """Yield ``(week, season_type, {sleeper_key: [gsis, ...]})`` per play.

    A list rather than a count because one play can credit two different
    players with the same key (both special-teams tacklers), and the
    caller needs to know WHO, not how many.
    """
    reader = csv.reader(lines)
    try:
        header = next(reader)
    except StopIteration:
        return
    idx = {name: i for i, name in enumerate(header)}
    missing = [c for c in _REQUIRED_COLUMNS if c not in idx]
    if missing:
        raise ValueError(f"play-by-play is missing expected columns: {missing}")

    i_week = idx["week"]
    i_stype = idx["season_type"]
    i_complete = idx["complete_pass"]
    i_receiver = idx["receiver_player_id"]
    i_recyd = idx.get("receiving_yards", -1)
    i_gained = idx.get("yards_gained", -1)
    if i_recyd < 0 and i_gained < 0:
        raise ValueError("play-by-play carries neither receiving_yards nor yards_gained")
    i_st = idx["special_teams_play"]
    i_tacklers = tuple(idx.get(c, -1) for c in _ST_TACKLE_COLUMNS)
    i_forced = tuple(idx.get(c, -1) for c in _ST_FORCED_FUMBLE_COLUMNS)
    i_recovery = tuple(
        (idx.get(a, -1), idx.get(b, -1), idx.get(c, -1)) for a, b, c in _FUMBLE_RECOVERY_SLOTS
    )
    i_fumbled_1_team = idx.get("fumbled_1_team", -1)
    i_int = idx["interception"]
    i_ret_td = idx["return_touchdown"]
    i_passer = idx["passer_player_id"]
    i_posteam = idx["posteam"]
    i_td_team = idx["td_team"]

    for row in reader:
        try:
            week = int(float(_cell(row, i_week)))
        except (TypeError, ValueError):
            continue
        stype = (_cell(row, i_stype) or "REG").upper()
        events: dict[str, list[str]] = {}

        def _credit(key: str, gsis: str) -> None:
            if gsis:
                events.setdefault(key, []).append(gsis)

        if _cell(row, i_complete) in _TRUE:
            receiver = _cell(row, i_receiver)
            raw = _cell(row, i_recyd) or _cell(row, i_gained)
            if receiver and raw:
                try:
                    band = band_for_yards(float(raw))
                except (TypeError, ValueError):
                    band = None
                if band is not None:
                    _credit(band, receiver)

        if _cell(row, i_st) in _TRUE:
            for i in i_tacklers:
                _credit("st_tkl_solo", _cell(row, i))
            for i in i_forced:
                _credit("st_ff", _cell(row, i))
            for i_player, i_rec_team, i_fum_team in i_recovery:
                player = _cell(row, i_player)
                if not player:
                    continue
                recovering = _cell(row, i_rec_team)
                fumbling = _cell(row, i_fum_team) or _cell(row, i_fumbled_1_team)
                # Recovering your own team's muff is not a takeaway and
                # the host does not pay it.  An unknown fumbling team is
                # NOT treated as an opponent — refusing to credit is the
                # answer that cannot invent points.
                if recovering and fumbling and recovering != fumbling:
                    _credit("st_fum_rec", player)

        if _cell(row, i_int) in _TRUE and _cell(row, i_ret_td) in _TRUE:
            # A returned interception that the OFFENSE ends up scoring on
            # (defender fumbles the return back into the end zone) sets
            # return_touchdown and is not a pick-six.
            if _cell(row, i_td_team) != _cell(row, i_posteam):
                _credit("pass_int_td", _cell(row, i_passer))

        if events:
            yield week, stype, events


def accumulate_weekly(
    lines: Iterable[str],
    *,
    season_types: Sequence[str] | None = ("REG",),
) -> tuple[dict[str, dict[int, dict[str, float]]], set[int]]:
    """Fold plays into ``{gsis: {week: {key: count}}}`` plus the weeks seen.

    The week set is returned separately and deliberately: it is what
    makes an absent player a real zero instead of an unknown, and
    deriving it from the players would lose any week in which nobody
    recorded one of these events.
    """
    wanted = {s.upper() for s in season_types} if season_types else None
    out: dict[str, dict[int, dict[str, float]]] = {}
    weeks: set[int] = set()
    for week, stype, events in _iter_plays(lines):
        if wanted is not None and stype not in wanted:
            continue
        weeks.add(week)
        for key, players in events.items():
            for gsis in players:
                out.setdefault(gsis, {}).setdefault(week, {})
                out[gsis][week][key] = out[gsis][week].get(key, 0.0) + 1.0
    return out, weeks


class PbpWeeklyStats:
    """A season's derived stats, with an explicit answer for "not covered".

    ``stats_for`` returns ``None`` when the week was never streamed and a
    mapping (possibly empty) when it was. Callers must branch on that:
    an empty mapping means the player recorded none of these events,
    which scores zero honestly; ``None`` means we do not know, which must
    not.
    """

    __slots__ = ("season", "_by_player", "_weeks", "provenance")

    def __init__(
        self,
        season: int,
        by_player: Mapping[str, Mapping[int, Mapping[str, float]]],
        weeks_covered: Iterable[int],
        *,
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        self.season = int(season)
        self._by_player = {
            str(k): {int(w): dict(v) for w, v in weeks.items()} for k, weeks in by_player.items()
        }
        self._weeks = {int(w) for w in weeks_covered}
        self.provenance = dict(provenance or {})

    @property
    def weeks_covered(self) -> frozenset[int]:
        return frozenset(self._weeks)

    def covers(self, week: Any) -> bool:
        try:
            return int(week) in self._weeks
        except (TypeError, ValueError):
            return False

    def stats_for(self, gsis: Any, week: Any) -> dict[str, float] | None:
        if not self.covers(week):
            return None
        key = str(gsis or "").strip()
        if not key:
            return None
        return dict(self._by_player.get(key, {}).get(int(week), {}))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "PbpWeeklyStats | None":
        if not payload:
            return None
        players = payload.get("players")
        if not isinstance(players, Mapping):
            return None
        by_player: dict[str, dict[int, dict[str, float]]] = {}
        for gsis, rec in players.items():
            weeks = (rec or {}).get("weeks") if isinstance(rec, Mapping) else None
            if not isinstance(weeks, Mapping):
                continue
            for week, stats in weeks.items():
                if not isinstance(stats, Mapping):
                    continue
                try:
                    wk = int(week)
                except (TypeError, ValueError):
                    continue
                by_player.setdefault(str(gsis), {})[wk] = {
                    str(k): float(v) for k, v in stats.items() if k in PBP_SUPPLEMENT_KEYS
                }
        covered = payload.get("weeksCovered") or []
        return cls(
            int(payload.get("season") or 0),
            by_player,
            covered,
            provenance={
                "schemaVersion": payload.get("schemaVersion"),
                "capturedAt": payload.get("capturedAt"),
                "seasonTypes": payload.get("seasonTypes"),
                "source": payload.get("source"),
            },
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_pbp_weekly_dir() -> Path:
    """Sibling of the weekly actuals and the depth histograms."""
    return _repo_root() / "data" / "nfl_data" / "actuals"


def pbp_weekly_path(season: int, *, out_dir: Path | None = None) -> Path:
    return (out_dir or default_pbp_weekly_dir()) / f"pbp_weekly_{int(season)}.jsonl"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_pbp_weekly(
    seasons: Sequence[int],
    *,
    out_dir: Path | None = None,
    season_types: Sequence[str] | None = ("REG",),
    url_template: str = PBP_URL_TEMPLATE,
    _line_source=None,
) -> dict[str, Any]:
    """Stream play-by-play and persist per-player-week derived stats.

    One file per season, one JSONL line per season. Re-running replaces
    the season's line. ``_line_source`` is a test seam supplying CSV
    lines directly; production passes nothing.
    """
    result: dict[str, Any] = {
        "schemaVersion": PBP_WEEKLY_SCHEMA_VERSION,
        "seasons": [],
        "players": 0,
        "events": 0.0,
        "paths": [],
    }

    for raw_season in seasons:
        season = int(raw_season)
        try:
            if _line_source is not None:
                by_player, weeks = accumulate_weekly(
                    _line_source(season), season_types=season_types
                )
            else:
                resp = open_pbp(season, url_template)
                try:
                    stream = io.TextIOWrapper(resp, encoding="utf-8", errors="replace")
                    by_player, weeks = accumulate_weekly(stream, season_types=season_types)
                finally:
                    resp.close()
        except urllib.error.HTTPError as exc:
            if getattr(exc, "code", 0) == 404 and not season_has_plausibly_started(season):
                _LOGGER.info(
                    "pbp_weekly=not_started season=%d — nflverse publishes pbp "
                    "once the season kicks off; nothing to fetch yet.",
                    season,
                )
            elif getattr(exc, "code", 0) == 404:
                _LOGGER.error(
                    "pbp_weekly=url_stale season=%d status=404 — this season has "
                    "started, so the release path no longer exists. No rows.",
                    season,
                )
            else:
                _LOGGER.warning("pbp_weekly=http season=%d status=%s", season, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("pbp_weekly=failed season=%d err=%r", season, exc)
            continue

        if not weeks:
            _LOGGER.warning(
                "pbp_weekly: season %d produced no plays — either the season has "
                "not started or the pbp schema changed",
                season,
            )
            continue

        events = sum(
            sum(stats.values()) for weeks_map in by_player.values() for stats in weeks_map.values()
        )
        entry = {
            "schemaVersion": PBP_WEEKLY_SCHEMA_VERSION,
            "season": season,
            "seasonTypes": sorted({s.upper() for s in (season_types or ["REG", "POST"])}),
            "capturedAt": _now_utc(),
            "source": url_template.format(year=season),
            "statKeys": sorted(PBP_SUPPLEMENT_KEYS),
            "weeksCovered": sorted(weeks),
            "playerCount": len(by_player),
            "eventCount": events,
            "players": {
                gsis: {
                    "weeks": {
                        str(week): {k: stats[k] for k in sorted(stats)}
                        for week, stats in sorted(weeks_map.items())
                    }
                }
                for gsis, weeks_map in sorted(by_player.items())
            },
        }

        path = pbp_weekly_path(season, out_dir=out_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
        tmp.replace(path)

        result["seasons"].append(season)
        result["players"] += len(by_player)
        result["events"] += events
        result["paths"].append(str(path))
        _LOGGER.info(
            "pbp_weekly=written season=%d players=%d events=%g weeks=%d path=%s",
            season,
            len(by_player),
            events,
            len(weeks),
            path,
        )

    return result


def load_pbp_weekly(season: int, *, out_dir: Path | None = None) -> dict[str, Any] | None:
    """Read one season's derived stats, or ``None`` if never built."""
    path = pbp_weekly_path(season, out_dir=out_dir)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    return json.loads(line)
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("pbp_weekly=unreadable season=%d err=%r", season, exc)
    return None


#: Where a weekly stat row carries its GSIS id, most-specific first.
#: The same ladder :data:`src.nfl_data.actuals_store._ID_COLUMNS` uses —
#: nflverse's unified weekly release keys on ``player_id``, and the
#: repo's own normalized rows carry the explicit spellings.
GSIS_COLUMNS: tuple[str, ...] = ("player_id", "player_id_gsis", "gsis_id")


def gsis_of_row(row: Mapping[str, Any]) -> str:
    for column in GSIS_COLUMNS:
        value = str(row.get(column) or "").strip()
        if value:
            return value
    return ""


def attach_supplement(row: Mapping[str, Any], stats: "PbpWeeklyStats | None") -> dict[str, Any]:
    """Copy ``row`` with the play-by-play supplement attached, when known.

    Leaves the row untouched — no supplement key at all — whenever the
    answer is unknown: no producer for the season, a week the producer
    never streamed, or a row with no GSIS id to join on. That absence is
    what makes ``compute_weekly_points`` report the affected rules as
    ``unscored`` instead of scoring them at zero.

    Returns a copy rather than mutating, because callers iterate rows
    they do not own (a cached nflverse frame, a shared fixture) and a
    stat row that quietly grew a key is exactly the kind of shared-global
    mutation the contract build had to be repaired for.
    """
    out = dict(row)
    if stats is None:
        return out
    gsis = gsis_of_row(row)
    if not gsis:
        return out
    supplement = stats.stats_for(gsis, row.get("week"))
    if supplement is None:
        return out
    out[PBP_SUPPLEMENT_ROW_KEY] = supplement
    return out


class SeasonPbpIndex:
    """Lazily load one :class:`PbpWeeklyStats` per season, and cache it.

    A season that has no artifact caches as ``None`` and is reported by
    :attr:`seasons_missing`, so "we never built it" stays visible instead
    of degrading into a quiet re-read on every row.
    """

    __slots__ = ("_loader", "_cache", "_out_dir")

    def __init__(self, *, out_dir: Path | None = None, loader=None) -> None:
        self._loader = loader or load_pbp_weekly
        self._out_dir = out_dir
        self._cache: dict[int, PbpWeeklyStats | None] = {}

    def for_season(self, season: Any) -> PbpWeeklyStats | None:
        try:
            key = int(season)
        except (TypeError, ValueError):
            return None
        if key not in self._cache:
            payload = self._loader(key, out_dir=self._out_dir)
            self._cache[key] = PbpWeeklyStats.from_payload(payload)
        return self._cache[key]

    def attach(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return attach_supplement(row, self.for_season(row.get("season")))

    @property
    def seasons_missing(self) -> tuple[int, ...]:
        return tuple(sorted(k for k, v in self._cache.items() if v is None))
