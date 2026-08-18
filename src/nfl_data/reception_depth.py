"""Per-player reception-depth histograms, in Sleeper's exact bands.

Why this exists
───────────────
This league does not pay a flat PPR. It bands receptions by the yardage
gained on the catch, and the spread is enormous — measured live from
Sleeper 2026-07-27, per-catch total (``rec`` + the band key)::

    band       mine   baseline   ratio
    0-4 yd     0.25     0.75     0.33x
    5-9 yd     0.50     0.75     0.67x
    10-19 yd   0.75     0.75     1.00x   <- calibration point
    20-29 yd   1.00     0.75     1.33x
    30-39 yd   1.25     0.75     1.67x
    40+ yd     2.00     0.75     2.67x

An 8x spread from shortest to longest, and the MEAN sits exactly on the
0.75 that every ranking source prices. That is why the mispricing is
invisible in aggregate and total at the extremes: a checkdown back is
worth a third of his market price here, a deep threat nearly 2.7x.

Exploiting it needs each receiver's distribution of catches across those
six bands. Nothing in the weekly stat files can supply it.

The shortcut that does not work
───────────────────────────────
nflverse's unified weekly file carries ``receiving_10``, ``_16``,
``_20`` and ``_40``. They are tempting and they are wrong for this:

* they are CUMULATIVE thresholds, not bands;
* their boundaries (10/16/20/40) do not line up with Sleeper's
  (5/10/20/30/40);
* and critically, **nothing in that set can reconstruct 0-4** — the
  0.33x band, the single most mispriced one.

A histogram derived from them would look plausible and be wrong exactly
where the money is. So the source has to be play-by-play.

Why not ``nflverse_direct.fetch_pbp``
─────────────────────────────────────
It exists, and this module deliberately does not use it. ``fetch_pbp``
buffers the whole response into a string and then materialises every row
as a dict — 2025 is 98 MB over 372 columns and ~50k plays, so that is
hundreds of megabytes of Python dicts to read four fields.

This module streams the same CSV with :mod:`csv.reader`, indexes only
the columns it needs by position, and accumulates counts as it goes.
Peak memory is the histogram, not the season.

What counts as a reception of N yards
─────────────────────────────────────
``complete_pass == 1``, credited to ``receiver_player_id``, bucketed on
``receiving_yards`` where present and ``yards_gained`` otherwise. The
two agree on ordinary plays; they diverge on laterals, where
``yards_gained`` includes yardage the receiver was not credited with, so
the receiving column is preferred.

**A zero-yard reception is in ``rec_0_4``; a NEGATIVE one is in no band
at all.** That was an open judgement call until 2026-08-18, when it was
measured against the host's own weekly dumps for 2025 weeks 1, 3, 5, 8,
11, 14 and 17. Sleeper counts a lost-yardage catch as a reception and
gives it no depth band:

* week 14 — 537 completed passes in play-by-play, host ``rec`` 537.0,
  host band total **523**. The difference is exactly the 14 negative
  receptions that week;
* Aaron Rodgers carries ``rec: 1``, ``rec_yd: -9`` and **no**
  ``rec_0_4`` key; Deebo Samuel caught one for -1 and three others, and
  is credited ``rec: 4`` with ``rec_0_4: 1``;
* with negatives excluded, all six bands then reconcile to the host
  **exactly** — player counts and reception counts, all six bands, all
  seven sampled weeks (42 of 42 cells).

The earlier reading put those catches in ``rec_0_4`` and would have paid
a band that the host does not pay — including to two quarterbacks who
caught their own deflected passes. So :func:`band_for_yards` returns
``None`` for a loss, and a caller that treats ``None`` as a band name
gets a ``KeyError`` rather than a wrong band.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "BAND_KEYS",
    "PBP_URL_TEMPLATE",
    "RECEPTION_DEPTH_SCHEMA_VERSION",
    "band_for_yards",
    "default_depth_dir",
    "depth_path",
    "load_reception_depth",
    "open_pbp",
    "persist_reception_depth",
    "summarise_histogram",
]

RECEPTION_DEPTH_SCHEMA_VERSION = "2026-08-18.v2"

#: Sleeper's reception-distance scoring keys, shortest first. These are
#: the exact key names on the league's ``scoring_settings``, so a
#: consumer can look each one up directly without a translation table.
BAND_KEYS: tuple[str, ...] = (
    "rec_0_4",
    "rec_5_9",
    "rec_10_19",
    "rec_20_29",
    "rec_30_39",
    "rec_40p",
)

#: Lower bound of each band, aligned with :data:`BAND_KEYS`. The last
#: band is open-ended.
_BAND_LOWER: tuple[int, ...] = (0, 5, 10, 20, 30, 40)

#: nflverse's play-by-play release. Public because it is the ONE place
#: this package reaches play-by-play for scoring purposes — see
#: :mod:`src.nfl_data.pbp_weekly`, which streams the same file through
#: :func:`open_pbp` rather than opening a second connection of its own.
PBP_URL_TEMPLATE = (
    "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{year}.csv"
)
_PBP_URL = PBP_URL_TEMPLATE

_HTTP_TIMEOUT_SEC = 180.0
_USER_AGENT = "brisket-reception-depth/1.0"


#: Month in which the NFL regular season starts. Used only to tell an
#: expected pre-season 404 apart from a broken release path —
#: deliberately coarse, because the alternative is fetching a schedule
#: to answer a question about log severity.
_SEASON_START_MONTH: int = 9


def season_has_plausibly_started(season: int, *, now: datetime | None = None) -> bool:
    """Has ``season`` kicked off, as far as the calendar can tell?

    Answers exactly one question: is a 404 from the pbp release expected,
    or does it mean the URL moved?

    Erring toward "started" for any past season means a genuinely stale
    URL is never silenced. Erring toward "not started" only within the
    current year's preseason means the offseason stays quiet.
    """
    now = now or datetime.now(timezone.utc)
    season = int(season)
    if season < now.year:
        return True
    if season > now.year:
        return False
    return now.month >= _SEASON_START_MONTH


def band_for_yards(yards: float) -> str | None:
    """Which Sleeper band a reception of ``yards`` falls in, or ``None``.

    ``None`` means the catch belongs to no band — it lost yardage. That
    is the host's own behaviour, measured over seven 2025 weeks; see the
    module docstring. It is deliberately not ``rec_0_4`` and deliberately
    not an exception: an unbanded reception is a real, countable event,
    it just does not pay a depth rule.
    """
    y = float(yards)
    if y < _BAND_LOWER[0]:
        return None
    band = BAND_KEYS[0]
    for key, lower in zip(BAND_KEYS, _BAND_LOWER):
        if y >= lower:
            band = key
    return band


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_depth_dir() -> Path:
    """Sibling of the weekly actuals, same durability contract."""
    return _repo_root() / "data" / "nfl_data" / "actuals"


def depth_path(season: int, *, depth_dir: Path | None = None) -> Path:
    return (depth_dir or default_depth_dir()) / f"reception_depth_{int(season)}.jsonl"


def open_pbp(season: int, url_template: str = PBP_URL_TEMPLATE):
    """Open the raw play-by-play response for ``season``.

    Returns the live response object; the caller owns closing it and is
    expected to STREAM it. Materialising the whole file is what
    :func:`src.nfl_data.nflverse_direct.fetch_pbp` does and why this
    package does not use it — 2025 is 98 MB over 372 columns.
    """
    url = url_template.format(year=int(season))
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    return urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC)


_open_pbp = open_pbp


def _iter_receptions(
    lines: Iterable[str],
) -> Iterator[tuple[str, str, int, str, float]]:
    """Yield ``(gsis, name, week, season_type, yards)`` per completed pass.

    Takes an iterable of CSV lines rather than a URL so tests can drive
    it from a fixture without any network, and so the caller owns the
    connection lifetime.
    """
    reader = csv.reader(lines)
    try:
        header = next(reader)
    except StopIteration:
        return
    idx = {name: i for i, name in enumerate(header)}

    needed = ("complete_pass", "receiver_player_id", "week", "season_type")
    missing = [c for c in needed if c not in idx]
    if missing:
        # A renamed pbp column must not read as "no receptions this
        # season" — that is precisely how the 2025 weekly-stats rename
        # went unnoticed for a season (#589).
        raise ValueError(f"play-by-play is missing expected columns: {missing}")

    i_complete = idx["complete_pass"]
    i_rid = idx["receiver_player_id"]
    i_name = idx.get("receiver_player_name", -1)
    i_week = idx["week"]
    i_stype = idx["season_type"]
    i_recyd = idx.get("receiving_yards", -1)
    i_gained = idx.get("yards_gained", -1)
    if i_recyd < 0 and i_gained < 0:
        raise ValueError("play-by-play carries neither receiving_yards nor yards_gained")

    for row in reader:
        if len(row) <= i_complete:
            continue
        if row[i_complete] not in ("1", "1.0", "True", "true"):
            continue
        gsis = row[i_rid] if i_rid < len(row) else ""
        if not gsis:
            continue
        raw = ""
        if i_recyd >= 0 and i_recyd < len(row):
            raw = row[i_recyd]
        if raw in ("", "NA") and i_gained >= 0 and i_gained < len(row):
            raw = row[i_gained]
        try:
            yards = float(raw)
        except (TypeError, ValueError):
            continue
        try:
            week = int(float(row[i_week]))
        except (TypeError, ValueError):
            continue
        name = row[i_name] if 0 <= i_name < len(row) else ""
        stype = (row[i_stype] if i_stype < len(row) else "REG") or "REG"
        yield gsis, name, week, stype.upper(), yards


def _accumulate(
    receptions: Iterable[tuple[str, str, int, str, float]],
    *,
    season_types: Sequence[str] | None = ("REG",),
) -> dict[str, dict[str, Any]]:
    wanted = {s.upper() for s in season_types} if season_types else None
    out: dict[str, dict[str, Any]] = {}
    for gsis, name, _week, stype, yards in receptions:
        if wanted is not None and stype not in wanted:
            continue
        rec = out.get(gsis)
        if rec is None:
            rec = {
                "name": name,
                "receptions": 0,
                "receivingYards": 0.0,
                "unbandedReceptions": 0,
                "bands": dict.fromkeys(BAND_KEYS, 0),
            }
            out[gsis] = rec
        if not rec["name"] and name:
            rec["name"] = name
        rec["receptions"] += 1
        rec["receivingYards"] += yards
        band = band_for_yards(yards)
        if band is None:
            # A lost-yardage catch: a reception, and no depth band. Counted
            # separately so ``receptions`` minus the band total is never an
            # unexplained shortfall — the host's own line balances the same
            # way (week 14: rec 537, bands 523, negatives 14).
            rec["unbandedReceptions"] += 1
        else:
            rec["bands"][band] += 1
    return out


def summarise_histogram(bands: Mapping[str, int]) -> dict[str, Any]:
    """Fraction of a player's catches in each band, plus the count.

    Fractions are what a scoring comparison needs — two receivers with
    the same shape and different volume should read as the same *fit*,
    with volume handled separately by whatever prices them.
    """
    counts = {k: int(bands.get(k, 0) or 0) for k in BAND_KEYS}
    total = sum(counts.values())
    if total <= 0:
        return {"receptions": 0, "counts": counts, "shares": dict.fromkeys(BAND_KEYS, 0.0)}
    return {
        "receptions": total,
        "counts": counts,
        "shares": {k: counts[k] / total for k in BAND_KEYS},
    }


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_reception_depth(
    seasons: Sequence[int],
    *,
    depth_dir: Path | None = None,
    season_types: Sequence[str] | None = ("REG",),
    url_template: str = _PBP_URL,
    _line_source=None,
) -> dict[str, Any]:
    """Stream play-by-play and persist per-player band histograms.

    One file per season, one JSONL line per season (the histogram is a
    season aggregate, not weekly — the bands are too sparse per week to
    be useful and a week-grained file would be 20x the size for noise).

    Re-running replaces the season's line. ``_line_source`` is a test
    seam that supplies CSV lines directly; production passes nothing.
    """
    result: dict[str, Any] = {
        "schemaVersion": RECEPTION_DEPTH_SCHEMA_VERSION,
        "seasons": [],
        "players": 0,
        "receptions": 0,
        "paths": [],
    }

    for season in seasons:
        season = int(season)
        try:
            if _line_source is not None:
                histogram = _accumulate(
                    _iter_receptions(_line_source(season)), season_types=season_types
                )
            else:
                resp = _open_pbp(season, url_template)
                try:
                    stream = io.TextIOWrapper(resp, encoding="utf-8", errors="replace")
                    histogram = _accumulate(_iter_receptions(stream), season_types=season_types)
                finally:
                    resp.close()
        except urllib.error.HTTPError as exc:
            if getattr(exc, "code", 0) == 404:
                # A 404 means two completely different things, and they
                # must not share a message. nflverse publishes a
                # season's pbp file only once that season kicks off, so
                # a 404 for the current season in July is EXPECTED and
                # is not an error. A 404 for a season that HAS started
                # means the release path moved.
                #
                # Logging both as "url_stale, update _PBP_URL" would cry
                # wolf every offseason, and once an operator learns to
                # ignore that, a genuinely stale URL reads identically.
                if not season_has_plausibly_started(season):
                    _LOGGER.info(
                        "reception_depth=not_started season=%d — nflverse "
                        "publishes pbp once the season kicks off; nothing to "
                        "fetch yet.",
                        season,
                    )
                else:
                    _LOGGER.error(
                        "reception_depth=url_stale season=%d status=404 — this "
                        "season has started, so the release path no longer "
                        "exists; update _PBP_URL. No rows.",
                        season,
                    )
            else:
                _LOGGER.warning("reception_depth=http season=%d status=%s", season, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("reception_depth=failed season=%d err=%r", season, exc)
            continue

        if not histogram:
            _LOGGER.warning(
                "reception_depth: season %d produced no receptions — either the "
                "season has not started or the pbp schema changed",
                season,
            )
            continue

        total_rec = sum(int(r["receptions"]) for r in histogram.values())
        total_unbanded = sum(int(r["unbandedReceptions"]) for r in histogram.values())
        entry = {
            "schemaVersion": RECEPTION_DEPTH_SCHEMA_VERSION,
            "season": season,
            "seasonTypes": sorted({s.upper() for s in (season_types or ["REG", "POST"])}),
            "capturedAt": _now_utc(),
            "playerCount": len(histogram),
            "receptionCount": total_rec,
            "unbandedReceptionCount": total_unbanded,
            "bandKeys": list(BAND_KEYS),
            "players": {
                gsis: {
                    "name": rec["name"],
                    "receptions": rec["receptions"],
                    "receivingYards": round(float(rec["receivingYards"]), 1),
                    "unbandedReceptions": rec["unbandedReceptions"],
                    "bands": rec["bands"],
                }
                for gsis, rec in sorted(histogram.items())
            },
        }

        path = depth_path(season, depth_dir=depth_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
        tmp.replace(path)

        result["seasons"].append(season)
        result["players"] += len(histogram)
        result["receptions"] += total_rec
        result["paths"].append(str(path))
        _LOGGER.info(
            "reception_depth=written season=%d players=%d receptions=%d path=%s",
            season,
            len(histogram),
            total_rec,
            path,
        )

    return result


def load_reception_depth(season: int, *, depth_dir: Path | None = None) -> dict[str, Any] | None:
    """The persisted histogram for ``season``, or None."""
    path = depth_path(season, depth_dir=depth_dir)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return json.loads(text.splitlines()[0])
    except json.JSONDecodeError:
        _LOGGER.warning("reception_depth: unparseable file at %s", path)
        return None
