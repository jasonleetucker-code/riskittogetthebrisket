"""As-of source snapshots reconstructed from this repository's git history.

Consensus Edge cannot honestly claim predictive value without being tested
against the past, and testing against the past requires knowing what the board
*actually looked like* on a given day — not what today's board says about a
player who has since moved.

This repository already has that record, and it was not obvious: the 2-hourly
``scheduled-refresh`` workflow commits ``CSVs/site_raw/*.csv`` on every run, so
**every commit of those files is a timestamped market observation**.  There is
no separate snapshot store to build; there is a time series to read.

Measured coverage (2026-08-03, after ``git fetch --unshallow`` — the working
clone was shallow at 563 commits and reported only 8 days, which is an artifact
of the clone and not of reality):

    ktc                110 days   2026-04-16 .. 2026-08-03
    dynastyDaddySf     110 days
    flockFantasySf     105 days
    ktcSfTep            99 days   2026-04-27 .. 2026-08-03   <- OFFENSE anchor
    fantasyCalc         83 days
    draftSharks*        75 days
    otcffbSf            75 days
    idpTradeCalc        14 days                              <- IDP anchor
    everything else    <=25 days

The consequence is stated once here and must be carried into every claim the
model makes: **offense is backtestable and IDP is not.**  Fourteen non-adjacent
days of the IDP anchor cannot support a 30-day-outcome study, so any IDP result
is descriptive, never validated.  Do not paper over this by borrowing the
offense result.

──────────────────────────────────────────────────────────────────────
The look-ahead rule, which is the only thing that makes this useful
──────────────────────────────────────────────────────────────────────
An as-of snapshot for date D must be built from the last commit **at or before**
``D 23:59:59Z`` — what was on disk at the end of that day.  Reading the nearest
commit, or the first commit after D, silently leaks the future into a feature
and turns a backtest into a self-fulfilling prophecy.  ``snapshot_at`` is the
only sanctioned reader and it enforces this; nothing else in ``src/edge`` may
shell out to git.

Staleness is preserved rather than hidden.  A source that stopped updating on
D-40 still resolves at D — that is what a consumer would genuinely have seen —
but the snapshot carries ``age_days`` so the panel can down-weight or exclude it.
A stale source must never look current.
"""

from __future__ import annotations

import csv
import io
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from src.utils.name_clean import resolve_canonical_name

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_RAW_DIR = "CSVs/site_raw"

# Sources whose committed CSV is a *value* observation on the site's own scale
# rather than a rank.  Only these can anchor a market price.
VALUE_SOURCES = frozenset({"ktc", "ktcSfTep", "idpTradeCalc", "fantasyCalc"})

# The acquisition-market anchor per asset class.  ``market_anchor_for`` is the
# single place this mapping lives; see ``src/edge/panel.py`` for why picks are
# deliberately absent (their market is the same ktcSfTep board, but pick rows
# are handled by the pick ladder rather than by name join).
OFFENSE_MARKET_ANCHOR = "ktcSfTep"
IDP_MARKET_ANCHOR = "idpTradeCalc"

# A source older than this at a given as-of date is reported but flagged.  Not a
# hard exclusion: the right response to a 10-day-old board differs between a
# feature and a label, so the panel decides, not the reader.
DEFAULT_STALE_AFTER_DAYS = 7


class GitHistoryUnavailable(RuntimeError):
    """The repository cannot answer historical questions.

    Raised rather than returning empty, because an empty panel and a panel that
    could not be built are very different facts and only one of them is safe to
    proceed from.
    """


@dataclass(frozen=True)
class SourceSnapshot:
    """What one source published, as it stood at the end of one day."""

    source: str
    as_of: date
    commit_sha: str
    committed_at: datetime
    values: dict[str, float]
    #: Days between the commit that produced this and the as-of date.  Zero means
    #: the source refreshed that day; large means the panel is looking at a
    #: board nobody updated.
    age_days: int
    raw_row_count: int = 0
    dropped_rows: int = 0
    #: Names that collapsed onto the same canonical key.  Kept rather than
    #: silently deduped: a collision is a real identity defect and hiding it
    #: would let two different players share one price.
    collisions: tuple[str, ...] = field(default_factory=tuple)
    #: Native published rank where the source supplies one. Preferred over
    #: ``values`` for ordering, because several of these boards publish a value
    #: scale this repository has measured and declined to trust (see the Hampel
    #: drop-rate notes in ``data_contract``).
    ranks: dict[str, float] = field(default_factory=dict)

    @property
    def is_stale(self) -> bool:
        return self.age_days > DEFAULT_STALE_AFTER_DAYS

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "asOf": self.as_of.isoformat(),
            "commitSha": self.commit_sha,
            "committedAt": self.committed_at.isoformat(),
            "ageDays": self.age_days,
            "isStale": self.is_stale,
            "rawRowCount": self.raw_row_count,
            "droppedRows": self.dropped_rows,
            "collisionCount": len(self.collisions),
            "valueCount": len(self.values),
            "rankCount": len(self.ranks),
        }


def _git(*args: str) -> str:
    """Run git in the repo, raising a typed error rather than leaking CalledProcessError."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - env dependent
        raise GitHistoryUnavailable(f"git {' '.join(args)} failed: {exc}") from exc
    if result.returncode != 0:
        raise GitHistoryUnavailable(
            f"git {' '.join(args)} exited {result.returncode}: {result.stderr.strip()[:400]}"
        )
    return result.stdout


def source_path(source: str) -> str:
    return f"{SITE_RAW_DIR}/{source}.csv"


def is_shallow() -> bool:
    """A shallow clone silently truncates history and understates coverage.

    Worth checking explicitly: on a shallow clone this module reports a handful
    of days and every downstream coverage gate fails for a reason that has
    nothing to do with the data. Callers should surface this rather than
    concluding the history does not exist.
    """
    try:
        return _git("rev-parse", "--is-shallow-repository").strip() == "true"
    except GitHistoryUnavailable:  # pragma: no cover - env dependent
        return False


@lru_cache(maxsize=256)
def _commit_log(source: str) -> tuple[tuple[str, datetime], ...]:
    """Every commit touching this source, newest first, as (sha, committed_at)."""
    raw = _git(
        "log",
        "--format=%H %cI",
        "--",
        source_path(source),
    )
    out: list[tuple[str, datetime]] = []
    for line in raw.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            out.append((parts[0], datetime.fromisoformat(parts[1])))
        except ValueError:
            continue
    return tuple(out)


def available_sources() -> list[str]:
    """Sources with a committed CSV in the working tree, sorted."""
    directory = REPO_ROOT / SITE_RAW_DIR
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.csv"))


def available_days(source: str) -> list[date]:
    """Distinct UTC days on which this source was committed, oldest first."""
    days = {stamp.astimezone(timezone.utc).date() for _sha, stamp in _commit_log(source)}
    return sorted(days)


def coverage(sources: Iterable[str] | None = None) -> dict[str, dict]:
    """Per-source history census — the evidence behind any backtest claim."""
    out: dict[str, dict] = {}
    for source in sources if sources is not None else available_sources():
        try:
            days = available_days(source)
        except GitHistoryUnavailable:
            out[source] = {"days": 0, "error": "git history unavailable"}
            continue
        out[source] = {
            "days": len(days),
            "earliest": days[0].isoformat() if days else None,
            "latest": days[-1].isoformat() if days else None,
            "commits": len(_commit_log(source)),
        }
    return out


def _resolve_commit(source: str, as_of: date) -> tuple[str, datetime] | None:
    """The last commit at or before ``as_of`` end-of-day UTC.

    THE look-ahead guard.  Implemented against the cached commit log rather than
    a per-call ``git log --before`` so that a thousand as-of dates cost one git
    invocation per source instead of a thousand.
    """
    cutoff = datetime.combine(as_of, datetime.max.time(), tzinfo=timezone.utc)
    for sha, stamp in _commit_log(source):  # newest first
        if stamp <= cutoff:
            return sha, stamp
    return None


# The site_raw CSVs do NOT share one schema, and assuming they did is a real
# failure mode rather than a hypothetical: a ``name,value``-only reader silently
# returns nothing for every rank-signal board — ``dlfSf``, ``flockFantasySf``,
# ``fantasyProsSf``, ``draftSharks*``, ``idpShow`` — which are exactly the
# expert boards an independent fair value is made of. The panel looked like it
# worked while quietly resting on a single source.
#
# Column names are matched case-insensitively because the same concept is
# spelled ``rank`` in one file and ``Rank`` in the next.
_NAME_COLUMNS = ("name", "player", "canonicalname")
_VALUE_COLUMNS = ("value", "3d value +", "normalizedvalue", "boone_value")
_RANK_COLUMNS = ("rank", "originalrank", "effectiverank")


def _pick_column(fieldnames: Sequence[str], candidates: Sequence[str]) -> str | None:
    lowered = {str(name or "").strip().lower(): name for name in fieldnames}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _parse_csv(
    text: str, source: str
) -> tuple[dict[str, float], dict[str, float], int, int, tuple[str, ...]]:
    """Parse a source CSV into canonical-name -> native value and/or native rank.

    Returns ``(values, ranks, raw_rows, dropped, collisions)``.  A source may
    supply either or both, and the caller chooses: a rank is the honest ordering
    signal for a board whose value scale this repository has already measured as
    untrustworthy (the Hampel drop-rate notes in ``data_contract`` moved several
    sources onto the rank path for exactly that reason), while a native value is
    required to anchor a price.

    Rows that do not parse are counted, never guessed at.  Two display names
    collapsing to one canonical key are recorded as a collision and the FIRST
    row wins deterministically — averaging two players would invent a number for
    both.
    """
    values: dict[str, float] = {}
    ranks: dict[str, float] = {}
    collisions: list[str] = []
    raw_rows = 0
    dropped = 0
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = list(reader.fieldnames or [])
    name_column = _pick_column(fieldnames, _NAME_COLUMNS)
    value_column = _pick_column(fieldnames, _VALUE_COLUMNS)
    rank_column = _pick_column(fieldnames, _RANK_COLUMNS)
    if name_column is None or (value_column is None and rank_column is None):
        log.debug("edge.history: %s has unrecognised columns %s", source, fieldnames)
        return {}, {}, 0, 0, ()

    for row in reader:
        raw_rows += 1
        name = (row.get(name_column) or "").strip()
        if not name:
            dropped += 1
            continue
        key = resolve_canonical_name(name)
        if not key:
            dropped += 1
            continue
        if key in values or key in ranks:
            collisions.append(name)
            continue

        parsed_value: float | None = None
        if value_column is not None:
            try:
                parsed_value = float((row.get(value_column) or "").strip())
            except (TypeError, ValueError):
                parsed_value = None
        parsed_rank: float | None = None
        if rank_column is not None:
            try:
                parsed_rank = float((row.get(rank_column) or "").strip())
            except (TypeError, ValueError):
                parsed_rank = None

        if parsed_value is None and parsed_rank is None:
            dropped += 1
            continue
        if parsed_value is not None:
            values[key] = parsed_value
        if parsed_rank is not None and parsed_rank > 0:
            ranks[key] = parsed_rank
    if collisions:
        log.debug("edge.history: %s had %d canonical-name collisions", source, len(collisions))
    return values, ranks, raw_rows, dropped, tuple(collisions)


@lru_cache(maxsize=4096)
def _blob_at(
    sha: str, source: str
) -> tuple[dict[str, float], dict[str, float], int, int, tuple[str, ...]] | None:
    """Read and parse one committed CSV, cached by (sha, source).

    A sparse source resolves to the SAME commit for every as-of date between its
    updates, so a 99-day panel over ten sources would otherwise re-read and
    re-parse the same blob hundreds of times. Cached on the commit hash rather
    than the date, which is what actually determines the content.
    """
    try:
        text = _git("show", f"{sha}:{source_path(source)}")
    except GitHistoryUnavailable:
        # The file may not have existed at that commit even though the commit
        # touches the path (e.g. the commit that deleted it).
        return None
    return _parse_csv(text, source)


def snapshot_at(source: str, as_of: date) -> SourceSnapshot | None:
    """What ``source`` published as of the end of ``as_of``, or None.

    Returns None when the source had not been committed yet at that date —
    genuinely absent, which the panel must record as missing rather than as a
    zero.  Never reads a commit made after ``as_of``.
    """
    resolved = _resolve_commit(source, as_of)
    if resolved is None:
        return None
    sha, committed_at = resolved
    parsed = _blob_at(sha, source)
    if parsed is None:
        return None
    values, ranks, raw_rows, dropped, collisions = parsed
    if not values and not ranks:
        return None
    age = (as_of - committed_at.astimezone(timezone.utc).date()).days
    return SourceSnapshot(
        source=source,
        as_of=as_of,
        commit_sha=sha,
        committed_at=committed_at,
        values=values,
        ranks=ranks,
        age_days=max(0, age),
        raw_row_count=raw_rows,
        dropped_rows=dropped,
        collisions=collisions,
    )


def market_anchor_for(asset_class: str) -> str:
    """The acquisition-market anchor for an asset class.

    One place, because a silent anchor substitution changes what every gap in
    the system means.  Callers that cannot resolve an anchor must report
    ``No Market Price`` rather than falling back to the other class's board:
    KTC publishes no IDP players at all, so an offense fallback for a defender
    is not a degraded answer, it is a wrong one.
    """
    normalized = (asset_class or "").strip().lower()
    if normalized in {"idp", "dl", "lb", "db"}:
        return IDP_MARKET_ANCHOR
    return OFFENSE_MARKET_ANCHOR


def date_range(start: date, end: date) -> list[date]:
    if end < start:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def common_span(sources: Sequence[str]) -> tuple[date, date] | None:
    """The widest span in which EVERY named source has at least one commit.

    Used to state a backtest window honestly: a panel is only as long as its
    scarcest required input, and quoting the longest source's range while a
    required one covers a fortnight is how a 14-day study gets described as a
    99-day one.
    """
    spans: list[tuple[date, date]] = []
    for source in sources:
        days = available_days(source)
        if not days:
            return None
        spans.append((days[0], days[-1]))
    if not spans:
        return None
    start = max(span[0] for span in spans)
    end = min(span[1] for span in spans)
    if end < start:
        return None
    return start, end
