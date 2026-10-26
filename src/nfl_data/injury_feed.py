"""ESPN NFL injury feed integration.

Pulls from the undocumented public endpoint:

    https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries

Returns a league-wide list of injury reports with status (Out, Questionable,
Injured Reserve, ...), injury type/detail, return timeline, and the ESPN
athlete id.  Resolving that id to a Sleeper id is a separate step
(``src.nfl_data.injury_identity``) so this module stays free of the Sleeper
directory.

Two payload shapes are read (both verified; see
``tests/nfl_data/fixtures/espn_injuries_2026-10-26.json`` for the current one):

* **old** -- ``athlete.id`` present, team in ``<team block>.team.abbreviation``;
* **current** (observed 2026-10-26) -- NO ``athlete.id``; the id is only in the
  ``athlete.links[].href`` paths (``/nfl/player/_/id/<digits>/<slug>``), the team
  block carries only ``id`` / ``displayName`` and the team abbreviation lives on
  ``athlete.team.abbreviation``.  The entry's own ``id`` is a report/news id
  (often negative) and is NEVER an athlete id -- 0 of 800 entries on the
  2026-10-26 payload matched; it is kept only as ``report_id`` provenance.

The current shape also lists healthy players with recent news as
``status: "Active"`` (525 of 800 on 2026-10-26); those are not injuries and are
counted, not parsed.

Degradation
-----------
* Feature flag ``espn_injury_feed`` OFF -> returns [].
* HTTP error / timeout -> cached None, next retry after TTL.
* Schema drift (unknown response shape, ``payload_shape_error``) -> empty
  list + warning log, NOT cached and reported to the breaker as a failure, so
  a caller that checks the cache (``injury_history.proven_fetch_time``) sees a
  failed fetch rather than an empty report.  A genuine ``{"injuries": []}`` is
  cached like any other report.
* **Silent-empty alarm.**  A body that is injuries-SHAPED but from which the
  parser recovers nothing (or loses more than :data:`MAX_PARSE_LOSS_FRACTION` of
  the rows that carry an injury status) is drift too -- this is exactly how the
  2026-10 id change read as "a fetch with zero injuries" for weeks.

The caller (signal engine) is responsible for fanning out
BUY/SELL transitions across rosters -- this module only fetches +
normalizes.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from src.api import feature_flags
from src.nfl_data import cache as _cache

_LOGGER = logging.getLogger(__name__)

_ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
#: The response-cache key.  Public so a capture can read the cache entry's own
#: ``fetched_at`` (``src.nfl_data.cache.entry_fetched_at``) and tell a fetch
#: that happened from one that failed and returned ``[]``.
#:
#: ``v2`` (2026-10-26): the cached dict gained fields, and -- more importantly --
#: a ``v1`` entry written by the id-blind parser is an EMPTY list for a
#: non-empty body.  Never read that back as a proven empty report.
CACHE_KEY = "espn_injuries:v2"
ENDPOINT_URL = _ESPN_INJURIES_URL
_UA = "riskit-injury-feed/1.0"
_TTL_IN_SEASON = 30 * 60  # 30 min
TTL_IN_SEASON_SECONDS = _TTL_IN_SEASON
_TIMEOUT_SEC = 8.0

#: Share of the rows that carry an injury status that may be lost to structural
#: problems (no athlete, no / malformed / ambiguous id, conflicting duplicates)
#: before the whole fetch is called drift.  Measured 0 of 275 on the 2026-10-26
#: payload.  10% tolerates a handful of odd rows (~27 at league size) while an
#: upstream change that drops or renames the id source (100% loss) or breaks a
#: team's block trips it at once.  Below :data:`MIN_ROWS_FOR_FRACTION` a ratio is
#: noise (one odd row of eight is 12%), so only the zero-parsed rule applies.
MAX_PARSE_LOSS_FRACTION = 0.10
MIN_ROWS_FOR_FRACTION = 20


_ACTIVE_STATUSES = frozenset(
    {
        "OUT",
        "INJURED_RESERVE",
        "IR",
        "PHYSICALLY_UNABLE",
        "PUP",
        "QUESTIONABLE",
        "DOUBTFUL",
        "DAY_TO_DAY",
    }
)

#: Statuses ESPN uses for a listed player who is NOT injured (the current shape
#: lists news-only players as ``Active``).  An expected non-injury, not a loss.
_HEALTHY_STATUSES = frozenset({"ACTIVE", "HEALTHY"})

# Skip-reason vocabulary (stable codes -- logged, recorded in the shadow ledger).
REASON_ENTRY_NOT_OBJECT = "entry_not_object"
REASON_TEAM_BLOCK_MALFORMED = "team_block_malformed"
REASON_ATHLETE_MISSING = "athlete_missing"
REASON_STATUS_MISSING = "status_missing"
REASON_ID_MISSING = "athlete_id_missing"
REASON_ID_MALFORMED = "athlete_id_malformed"
REASON_ID_AMBIGUOUS = "athlete_id_ambiguous"
REASON_DUPLICATE_CONFLICTING = "duplicate_conflicting"
REASON_DUPLICATE_IDENTICAL = "duplicate_identical_collapsed"
REASON_STATUS_ACTIVE = "status_active"
REASON_STATUS_UNTRACKED_PREFIX = "status_untracked:"

#: Reasons that mean a row which carried (or may have carried) an injury status
#: could not be turned into an entry.  These -- and only these -- are "losses".
_STRUCTURAL_LOSS_REASONS = frozenset(
    {
        REASON_ENTRY_NOT_OBJECT,
        REASON_ATHLETE_MISSING,
        REASON_STATUS_MISSING,
        REASON_ID_MISSING,
        REASON_ID_MALFORMED,
        REASON_ID_AMBIGUOUS,
        REASON_DUPLICATE_CONFLICTING,
    }
)

_DIGITS = re.compile(r"^\d+$")
#: ``/nfl/player/_/id/4427728/bam-knight``, ``/nfl/player/stats/_/id/4427728/...``
_ATHLETE_PATH_ID = re.compile(r"^/nfl/player/(?:[a-z]+/)?_/id/(\d+)(?:/|$)")


@dataclass(frozen=True)
class InjuryEntry:
    espn_athlete_id: str
    full_name: str
    position: str
    team_abbrev: str
    status: str  # normalized: OUT | IR | QUESTIONABLE | DOUBTFUL | PUP
    body_part: str
    description: str
    date_reported: str  # ISO-8601 or empty
    returning: str  # best-effort "return timeline" free text
    # ── provenance / detail added 2026-10-26 (all default "" = not stated) ──
    injury_type: str = ""  # details.type, e.g. "Knee"
    injury_detail: str = ""  # details.detail, e.g. "Fracture"
    injury_side: str = ""  # details.side
    source: str = ""  # entry.source.description, e.g. "basic/manual"
    id_source: str = ""  # "athlete.id" | "athlete.links"
    report_id: str = ""  # ESPN's report/news id for this row -- NOT the athlete id
    # Set by ``injury_identity`` after resolution; never by the parser.
    sleeper_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "espnAthleteId": self.espn_athlete_id,
            "fullName": self.full_name,
            "position": self.position,
            "teamAbbrev": self.team_abbrev,
            "status": self.status,
            "bodyPart": self.body_part,
            "description": self.description,
            "dateReported": self.date_reported,
            "returning": self.returning,
            "injuryType": self.injury_type,
            "injuryDetail": self.injury_detail,
            "injurySide": self.injury_side,
            "source": self.source,
            "idSource": self.id_source,
            "reportId": self.report_id,
            "sleeperId": self.sleeper_id,
        }


@dataclass
class ParseReport:
    """What the parser did with every raw row -- nothing is skipped silently."""

    raw_entries: int = 0
    parsed: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def bump(self, reason: str, n: int = 1) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + n

    @property
    def structural_losses(self) -> int:
        return sum(n for r, n in self.skipped.items() if r in _STRUCTURAL_LOSS_REASONS)

    @property
    def candidate_rows(self) -> int:
        """Rows that carried an injury status: the ones we meant to parse."""
        return self.parsed + self.structural_losses

    def to_dict(self) -> dict[str, Any]:
        return {
            "rawEntries": self.raw_entries,
            "parsed": self.parsed,
            "candidateRows": self.candidate_rows,
            "structuralLosses": self.structural_losses,
            "skipped": dict(sorted(self.skipped.items())),
        }


@dataclass
class ParseResult:
    entries: list[InjuryEntry]
    report: ParseReport


def _normalize_status(raw: str) -> str:
    """Map ESPN's many status variants to our 5-bucket system.

    ESPN uses ``status``, ``type.description``, and ``shortComment``
    inconsistently.  Normalize to: OUT | IR | QUESTIONABLE | DOUBTFUL
    | PUP.  Unknown → verbatim uppercased.
    """
    s = str(raw or "").strip().upper().replace(" ", "_").replace("-", "_")
    if s in ("OUT", "SUSPENDED"):
        return "OUT"
    if s in ("IR", "INJURED_RESERVE", "RESERVE_INJURED"):
        return "IR"
    if s in ("QUESTIONABLE", "Q"):
        return "QUESTIONABLE"
    if s in ("DOUBTFUL", "D"):
        return "DOUBTFUL"
    if s in ("PUP", "PHYSICALLY_UNABLE", "PHYSICALLY_UNABLE_TO_PERFORM"):
        return "PUP"
    if s in ("DAY_TO_DAY", "PROBABLE", "P"):
        return "DAY_TO_DAY"
    return s


#: Last fetch's parse diagnostics (a plain dict), for the refresh script's log
#: and shadow ledger.  ``None`` until ``fetch_injuries`` runs a real fetch (a
#: cache hit parses nothing).  Reset with :func:`clear_last_fetch_report`.
_LAST_FETCH_REPORT: dict[str, Any] | None = None


def last_fetch_report() -> dict[str, Any] | None:
    return None if _LAST_FETCH_REPORT is None else dict(_LAST_FETCH_REPORT)


def clear_last_fetch_report() -> None:
    global _LAST_FETCH_REPORT
    _LAST_FETCH_REPORT = None


def _remember_report(report: ParseReport | None, *, error: str | None, outcome: str) -> None:
    global _LAST_FETCH_REPORT
    _LAST_FETCH_REPORT = {
        "outcome": outcome,
        "error": error,
        "parse": report.to_dict() if report is not None else None,
    }


def fetch_injuries(
    *,
    ttl_seconds: float = _TTL_IN_SEASON,
    _url_opener=None,
    cache_dir=None,
) -> list[InjuryEntry]:
    """Return the current league-wide injury list.

    ``_url_opener`` is a test hook.  Production passes None.
    """
    if not feature_flags.is_enabled("espn_injury_feed"):
        return []
    key = CACHE_KEY
    cached = _cache.get(key, ttl_seconds=ttl_seconds, cache_dir=cache_dir)
    if cached is not None:
        return [_from_cached_dict(d) for d in cached]

    # Circuit breaker pre-check — bail out fast if ESPN is tripping.
    bp = None
    try:
        from src.utils import circuit_breaker as _cb

        bp = _cb.get_or_create(
            "espn_injuries",
            failure_threshold=3,
            failure_window_sec=120.0,
            open_duration_sec=180.0,
        )
        if not bp.can_call():
            _LOGGER.warning("espn injuries: breaker OPEN, fast-fail")
            _remember_report(None, error="breaker_open", outcome="breaker_open")
            return []
    except Exception:  # noqa: BLE001
        bp = None

    try:
        req = urllib.request.Request(
            _ESPN_INJURIES_URL,
            headers={"User-Agent": _UA},
        )
        opener = _url_opener or urllib.request.urlopen
        with opener(req, timeout=_TIMEOUT_SEC) as resp:
            body = resp.read()
        raw = json.loads(body)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        _LOGGER.warning("espn injuries: network error: %s", exc)
        _remember_report(None, error=f"network_error:{type(exc).__name__}", outcome="network_error")
        if bp is not None:
            bp.report_failure(exc)
        return []
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("espn injuries: parse error: %s", exc)
        _remember_report(None, error=f"parse_error:{type(exc).__name__}", outcome="parse_error")
        if bp is not None:
            bp.report_failure(exc)
        return []

    result = parse_espn_payload(raw)
    drift = payload_shape_error(raw, parsed=result)
    if drift is not None:
        # A 200 whose body is not the injuries shape is a FAILED fetch, not an
        # empty report: caching ``[]`` here would let a schema change read as
        # "every injured player recovered" downstream.  Nothing is cached.
        _LOGGER.warning(
            "espn injuries: unexpected payload shape (%s); not cached; parse=%s",
            drift,
            result.report.to_dict(),
        )
        _remember_report(result.report, error=drift, outcome="drift")
        if bp is not None:
            bp.report_failure(ValueError(drift))
        return []
    parsed = result.entries
    _LOGGER.info(
        "espn injuries: parsed %d entries; report=%s", len(parsed), result.report.to_dict()
    )
    _remember_report(result.report, error=None, outcome="ok")
    if bp is not None:
        bp.report_success()
    _cache.put(key, [e.to_dict() for e in parsed], cache_dir=cache_dir)
    return parsed


def payload_shape_error(payload: Any, *, parsed: ParseResult | None = None) -> str | None:
    """Why ``payload`` is not a USABLE ESPN injuries response, or None when it is.

    ``{"injuries": []}`` is a VALID (empty) report.  A non-object body, a
    missing / non-list ``injuries`` key, or a non-empty list in which no team
    block carries an ``injuries`` list is shape drift -- the parser would turn
    any of those into ``[]``, indistinguishable from a healthy league.

    Beyond shape, two PARSE-health rules (the 2026-10 id change passed every
    shape check while the parser recovered nothing):

    * ``no_injury_entries_parsed``: raw entries exist but none parsed.  Strict by
      design -- a league-wide report with zero injuries does not occur in season,
      and a false alarm only changes nothing and exits non-zero.
    * ``parse_loss_above_10pct``: more than :data:`MAX_PARSE_LOSS_FRACTION` of
      the rows that carried an injury status were lost to structural problems
      (only judged over :data:`MIN_ROWS_FOR_FRACTION` or more such rows).

    ``parsed`` lets a caller that already parsed avoid doing it twice.
    """
    if not isinstance(payload, dict):
        return f"body_not_an_object:{type(payload).__name__}"
    teams = payload.get("injuries")
    if not isinstance(teams, list):
        return "no_injuries_list"
    if teams and not any(
        isinstance(block, dict) and isinstance(block.get("injuries"), list) for block in teams
    ):
        return "no_team_block_has_an_injuries_list"
    report = (parsed if parsed is not None else parse_espn_payload(payload)).report
    return parse_health_error(report)


def parse_health_error(report: ParseReport) -> str | None:
    if report.raw_entries > 0 and report.parsed == 0:
        return f"no_injury_entries_parsed:raw={report.raw_entries},skipped={_fmt_skips(report)}"
    candidates = report.candidate_rows
    if candidates >= MIN_ROWS_FOR_FRACTION:
        lost = report.structural_losses
        if lost / candidates > MAX_PARSE_LOSS_FRACTION:
            pct = int(MAX_PARSE_LOSS_FRACTION * 100)
            return f"parse_loss_above_{pct}pct:{lost}/{candidates},skipped={_fmt_skips(report)}"
    return None


def _fmt_skips(report: ParseReport) -> str:
    return ",".join(f"{r}:{n}" for r, n in sorted(report.skipped.items())) or "none"


def _s(value: Any) -> str:
    """A stripped string for a scalar; ``""`` for None / containers (never repr)."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _athlete_ids_from_links(links: Any) -> set[str]:
    """Distinct ESPN athlete ids named by the athlete's web links."""
    ids: set[str] = set()
    if not isinstance(links, list):
        return ids
    for link in links:
        href = _obj(link).get("href")
        if not isinstance(href, str):
            continue
        try:
            parts = urllib.parse.urlsplit(href)
        except ValueError:
            continue
        if parts.scheme not in ("http", "https"):
            continue
        m = _ATHLETE_PATH_ID.match(parts.path)
        if m:
            ids.add(m.group(1))
    return ids


def _athlete_id(athlete: dict[str, Any]) -> tuple[str | None, str, str | None]:
    """``(id, id_source, skip_reason)``.  Never guesses.

    ``athlete.id`` wins when present; the links must then agree with it.  Without
    it the links must name exactly ONE id.  The entry's own ``id`` is not
    consulted (it is a report id).
    """
    attr = _s(athlete.get("id"))
    link_ids = _athlete_ids_from_links(athlete.get("links"))
    if attr:
        if not _DIGITS.match(attr):
            return None, "", REASON_ID_MALFORMED
        if link_ids and link_ids != {attr}:
            return None, "", REASON_ID_AMBIGUOUS
        return attr, "athlete.id", None
    if len(link_ids) == 1:
        return next(iter(link_ids)), "athlete.links", None
    if not link_ids:
        return None, "", REASON_ID_MISSING
    return None, "", REASON_ID_AMBIGUOUS


def _status_of(entry: dict[str, Any]) -> str:
    raw = entry.get("status")
    if not _s(raw):
        raw = _obj(entry.get("type")).get("description")
    return _normalize_status(_s(raw))


def parse_espn_payload(payload: Any) -> ParseResult:
    """Parse ESPN's injuries response (old AND current shape), counting every skip.

    Old shape (as of 2026-04)::

        {"injuries": [{"team": {"abbreviation": "BUF"},
                       "injuries": [{"athlete": {"id": "...", "displayName": "...",
                                                 "position": {"abbreviation": "QB"}},
                                     "status": "...", "details": {...}, "date": "...",
                                     "shortComment": "..."}]}]}

    Current shape (2026-10-26): no ``athlete.id`` (id in ``athlete.links`` hrefs),
    team block = ``{"id", "displayName", "injuries"}``, ``athlete.team`` carries the
    abbreviation, ``source`` / ``type`` / ``details`` describe the report, and
    non-injured players with news appear with ``status: "Active"``.

    Row handling, in order -- each skip is counted by reason, none is guessed:
    non-object row; blank status; healthy (``Active``) status; untracked status
    (e.g. ``Suspension``); missing athlete; missing / non-numeric / conflicting id;
    then a per-id duplicate pass (identical copies collapse to one, conflicting
    copies are ALL dropped -- which copy is current is not knowable).
    """
    report = ParseReport()
    out: list[InjuryEntry] = []
    if not isinstance(payload, dict):
        return ParseResult(out, report)
    teams_list = payload.get("injuries")
    if not isinstance(teams_list, list):
        return ParseResult(out, report)

    candidates: list[InjuryEntry] = []
    for team_block in teams_list:
        if not isinstance(team_block, dict):
            report.bump(REASON_TEAM_BLOCK_MALFORMED)
            continue
        inj_list = team_block.get("injuries")
        if not isinstance(inj_list, list):
            report.bump(REASON_TEAM_BLOCK_MALFORMED)
            continue
        block_team = _s(_obj(team_block.get("team")).get("abbreviation")).upper()
        for entry in inj_list:
            report.raw_entries += 1
            if not isinstance(entry, dict):
                report.bump(REASON_ENTRY_NOT_OBJECT)
                continue
            status_norm = _status_of(entry)
            if not status_norm:
                report.bump(REASON_STATUS_MISSING)
                continue
            if status_norm in _HEALTHY_STATUSES:
                report.bump(REASON_STATUS_ACTIVE)
                continue
            if status_norm not in _ACTIVE_STATUSES:
                report.bump(f"{REASON_STATUS_UNTRACKED_PREFIX}{status_norm[:40]}")
                continue
            athlete = entry.get("athlete")
            if not isinstance(athlete, dict):
                report.bump(REASON_ATHLETE_MISSING)
                continue
            espn_id, id_source, skip = _athlete_id(athlete)
            if espn_id is None:
                report.bump(skip or REASON_ID_MISSING)
                continue
            name = _s(athlete.get("displayName")) or _s(athlete.get("fullName"))
            pos = _s(_obj(athlete.get("position")).get("abbreviation")).upper()
            # The player's own team first; the block's team (old shape) otherwise.
            team = _s(_obj(athlete.get("team")).get("abbreviation")).upper() or block_team
            details = _obj(entry.get("details"))
            candidates.append(
                InjuryEntry(
                    espn_athlete_id=espn_id,
                    full_name=name,
                    position=pos,
                    team_abbrev=team,
                    status=status_norm,
                    body_part=_s(details.get("location")) or _s(details.get("type")),
                    description=_s(entry.get("shortComment")) or _s(entry.get("longComment")),
                    date_reported=_s(entry.get("date")),
                    returning=_s(details.get("returnDate")),
                    injury_type=_s(details.get("type")),
                    injury_detail=_s(details.get("detail")),
                    injury_side=_s(details.get("side")),
                    source=_s(_obj(entry.get("source")).get("description")),
                    id_source=id_source,
                    report_id=_s(entry.get("id")),
                )
            )

    # Duplicate pass, by athlete id.  Order of first appearance is preserved.
    by_id: dict[str, list[InjuryEntry]] = {}
    for e in candidates:
        by_id.setdefault(e.espn_athlete_id, []).append(e)
    for copies in by_id.values():
        first = copies[0]
        if len(copies) == 1:
            out.append(first)
        elif all(_dup_signature(c) == _dup_signature(first) for c in copies):
            out.append(first)
            report.bump(REASON_DUPLICATE_IDENTICAL, len(copies) - 1)
        else:
            report.bump(REASON_DUPLICATE_CONFLICTING, len(copies))
    report.parsed = len(out)
    return ParseResult(out, report)


def _dup_signature(e: InjuryEntry) -> tuple[Any, ...]:
    """What makes two rows for one athlete "the same report" (``report_id`` is
    deliberately excluded: ESPN may re-issue the same report under a new id)."""
    d = e.to_dict()
    d.pop("reportId", None)
    return tuple(sorted(d.items()))


def _parse_espn_payload(payload: Any) -> list[InjuryEntry]:
    """The entries only (kept for callers that predate :func:`parse_espn_payload`)."""
    return parse_espn_payload(payload).entries


def entry_from_dict(d: dict[str, Any]) -> InjuryEntry:
    """Inverse of :meth:`InjuryEntry.to_dict`; absent (older) keys read as ``""``."""
    return InjuryEntry(
        espn_athlete_id=_s(d.get("espnAthleteId")),
        full_name=_s(d.get("fullName")),
        position=_s(d.get("position")),
        team_abbrev=_s(d.get("teamAbbrev")),
        status=_s(d.get("status")),
        body_part=_s(d.get("bodyPart")),
        description=_s(d.get("description")),
        date_reported=_s(d.get("dateReported")),
        returning=_s(d.get("returning")),
        injury_type=_s(d.get("injuryType")),
        injury_detail=_s(d.get("injuryDetail")),
        injury_side=_s(d.get("injurySide")),
        source=_s(d.get("source")),
        id_source=_s(d.get("idSource")),
        report_id=_s(d.get("reportId")),
        sleeper_id=_s(d.get("sleeperId")),
    )


_from_cached_dict = entry_from_dict


def diff_for_signals(
    prior: list[InjuryEntry],
    current: list[InjuryEntry],
) -> list[dict[str, Any]]:
    """Return new / changed injury transitions for the signal engine.

    Emits a signal dict when:
      * A player newly appears in the injury list (was healthy → injured).
      * A player's status worsens (Q → Out, DOUBTFUL → IR, etc.).

    Does NOT emit when:
      * Player recovers (Out → active / off-list) — buying a returning
        player is a different signal class (covered in a future idea).
      * Repeat report of same status.
    """
    prior_by_id = {e.espn_athlete_id: e for e in prior}
    severity = {"DAY_TO_DAY": 1, "QUESTIONABLE": 2, "DOUBTFUL": 3, "OUT": 4, "PUP": 4, "IR": 5}
    signals: list[dict[str, Any]] = []
    for curr in current:
        prev = prior_by_id.get(curr.espn_athlete_id)
        if prev is None:
            # New injury.
            signals.append(
                {
                    "espnAthleteId": curr.espn_athlete_id,
                    "sleeperId": curr.sleeper_id or None,
                    "name": curr.full_name,
                    "position": curr.position,
                    "team": curr.team_abbrev,
                    "transition": "healthy_to_injured",
                    "newStatus": curr.status,
                    "priorStatus": None,
                    # ``injury_type`` ("Knee") is the specific part in the current
                    # shape; ``body_part`` ("Leg") is its broad location.
                    "reason": f"New injury — {curr.status}"
                    + (
                        f" ({curr.injury_type or curr.body_part})"
                        if (curr.injury_type or curr.body_part)
                        else ""
                    ),
                }
            )
            continue
        prev_sev = severity.get(prev.status, 0)
        new_sev = severity.get(curr.status, 0)
        if new_sev > prev_sev:
            signals.append(
                {
                    "espnAthleteId": curr.espn_athlete_id,
                    "sleeperId": curr.sleeper_id or None,
                    "name": curr.full_name,
                    "position": curr.position,
                    "team": curr.team_abbrev,
                    "transition": "injury_worsened",
                    "newStatus": curr.status,
                    "priorStatus": prev.status,
                    "reason": f"Status worsened: {prev.status} → {curr.status}",
                }
            )
    return signals
