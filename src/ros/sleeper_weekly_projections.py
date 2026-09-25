"""C5-PROJ-C — first WEEKLY-horizon projection source: Sleeper weekly projections.

Sleeper's web client reads per-player weekly projections from an
undocumented public endpoint (:data:`ENDPOINT_TEMPLATE`). Every row carries
a projected stat line in **Sleeper's own stat-key vocabulary** — the same
vocabulary the league host scores — plus the scheduled ``game_id``,
``opponent``, the model that produced it (``company``; measured as
``"rotowire"`` on every row of a full week-3 capture) and the provider's
``updated_at`` / ``last_modified`` stamps.

What this module owns, and nothing more:

* acquisition, behind the ``sleeper_weekly_projections`` feature flag
  (default OFF in code; activation ships with the Game Day collector and
  payload units — access is owner-attested, see the census entry
  ``sleeperWeeklyProjections``);
* turning captured rows into :class:`WeeklyProjectionObservation`, each
  rescored under the CALLER's league card by the canonical exact scorer
  :func:`src.league_intel.scorer.score_stat_line` (never a native
  PPR total, never a hardcoded league);
* reporting, per player, the league-paid scoring keys the provider does
  NOT project (:attr:`WeeklyProjectionObservation.uncovered_scoring_keys`)
  so a gap is visible rather than a silent zero;
* :func:`lock_baseline_at_kickoff` — the provider baseline for a player is
  the last observation fetched at or before his game's kickoff, so an
  in-game provider update can never drift the pregame baseline.

**Seasonal intelligence lane only.** A weekly projection is redraft-style,
current-week evidence (census ``gameType: WEEKLY``). Nothing here reads or
writes ``rankDerivedValue`` or any dynasty value/rank, and nothing here may
feed the dynasty valuation pool — the repo-wide guard
``tests/api/test_canonical_ownership_protections.py`` already scans every
module under ``src/ros/``, including this one.

**Missing is never zero.** Sleeper ships a placeholder row for players it
does not project (only ``adp_dd_ppr``, no ``game_id``). Those rows are
REFUSED and counted (``refused['placeholder_no_projection']``) — they
never become a 0-point projection.

**Not built here (C5-PROJ-C remainder, recorded in the unit handoff):** a
multi-family weekly ensemble. The existing ensemble owner
(:mod:`src.ros.projection_ensemble`) already accepts a ``WEEKLY`` horizon
through :func:`combine_ensemble`, and :func:`to_projection_observation`
adapts an observation to its contract, but with one weekly family live it
can only ever produce ``single_family_passthrough``. Its
``build_ros_full_season_ensemble`` default source set is deliberately
untouched, so season / ROS outputs are byte-identical.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from types import MappingProxyType
from typing import Any

from src.api.feature_flags import is_enabled
from src.history.keys import player_asset_key
from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.league_intel.scorer import ScoringComponent, score_stat_line
from src.ros import projection_source_census as census
from src.ros.projection_observations import ProjectionObservation, ProjectionObservationError
from src.utils.name_clean import normalize_position

__all__ = [
    "CENSUS_SOURCE_KEY",
    "ENDPOINT_TEMPLATE",
    "FEATURE_FLAG",
    "HORIZON",
    "POSITIONS",
    "BaselineEntry",
    "BaselineLock",
    "FetchResult",
    "WeeklyProjectionBatch",
    "WeeklyProjectionObservation",
    "build_weekly_observations",
    "fetch_weekly_projection_rows",
    "lock_baseline_at_kickoff",
    "projection_url",
    "to_projection_observation",
]

CENSUS_SOURCE_KEY = "sleeperWeeklyProjections"
FEATURE_FLAG = "sleeper_weekly_projections"
HORIZON = "WEEKLY"
GAME_TYPE = "WEEKLY"

#: Undocumented — see the census entry's ``accessPosture``.
ENDPOINT_TEMPLATE = "https://api.sleeper.app/projections/nfl/{season}/{week}"
#: Sleeper fantasy positions requested. K and every IDP group included.
POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")
HTTP_TIMEOUT_SECONDS = 20.0
#: A full week measured 4.75 MB; refuse anything absurdly larger rather
#: than buffering an unbounded body.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
_USER_AGENT = "riskit-weekly-projections/1.0"

#: Stat-line keys that are provider metadata or the provider's own point
#: totals, not projected football events. A row carrying nothing else is
#: not a projection. ``pts_*`` are kept on the stat line as a DIAGNOSTIC
#: (``native_points_ppr``) and are never scored — no league card pays a
#: ``pts_*`` key, and the exact scorer ignores keys the card lacks.
_NON_EVENT_PREFIXES: tuple[str, ...] = ("adp_", "pos_adp_", "pts_")
_NON_EVENT_KEYS: frozenset[str] = frozenset({"gp", "cmp_pct"})

# ── Position-applicability grammar for the UNCOVERED report ──────────
#
# A league key the provider never publishes for a player's position is
# only a *gap* if a player at that position can earn it at all. These
# rules are read off Sleeper's own key grammar, not tuned: ``idp_*`` keys
# are individual-defender events, the kicking family is the kicker's, and
# a ``bonus_*_<pos>`` key names its position in its suffix. Everything
# else is treated as APPLICABLE (over-inclusive on purpose — a noisy gap
# report is recoverable, a hidden gap is not). Team-defense keys are
# resolved through the canonical classifier in
# ``src.nfl_data.scoring_coverage`` rather than a second table here.
_IDP_POSITIONS: frozenset[str] = frozenset({"DL", "LB", "DB"})
_KICKER_PREFIXES: tuple[str, ...] = ("fgm", "fgmiss", "fga", "xpm", "xpmiss", "xpa")
_BONUS_POSITION_SUFFIX = re.compile(r"^bonus_.+_(qb|rb|wr|te)$")


# ── Observation contract ─────────────────────────────────────────────


@dataclass(frozen=True)
class WeeklyProjectionObservation:
    """One provider projection for one player, one week, one fetch.

    Deliberately NOT a dynasty value or ranking of any kind.
    """

    census_source_key: str
    provider_family: str
    #: The per-row ``company`` field — the model that produced the line.
    model_company: str
    horizon: str
    game_type: str

    sleeper_player_id: str
    #: ``player:<sleeperId>`` via the temporal-history key owner.
    player_key: str
    #: Canonical position of the player's PRIMARY Sleeper fantasy position.
    position: str
    #: Every canonical fantasy position Sleeper lists for the player.
    fantasy_positions: tuple[str, ...]
    team: str | None
    opponent: str | None
    game_id: str

    season: int
    week: int
    season_type: str

    #: The provider's raw projected stat line, Sleeper stat keys, numeric
    #: values only (read-only view).
    stat_line: Mapping[str, float]

    #: Projected points under the CALLER's exact league card — the number
    #: every consumer must read.
    league_scored_points: float
    #: ``scoring_fingerprint`` of the card that produced
    #: ``league_scored_points`` (pinned-input provenance).
    scoring_fingerprint: str
    scoring_components: tuple[ScoringComponent, ...]
    scoring_warnings: tuple[str, ...]

    #: League-paid keys (nonzero rate) this provider does not project for
    #: the player's position(s). Their contribution is UNKNOWN, not zero.
    uncovered_scoring_keys: tuple[str, ...]

    #: DIAGNOSTIC ONLY — Sleeper's own PPR total for the line. Never blend.
    native_points_ppr: float | None

    #: When WE fetched the row (UTC ISO-8601).
    observed_at: str
    #: When the PROVIDER last changed the row (UTC ISO-8601), or ``None``
    #: when the row carries no stamp. Fetch time is not data freshness.
    provider_updated_at: str | None


@dataclass(frozen=True)
class WeeklyProjectionBatch:
    """Every observation from one fetch, plus what was refused and why."""

    season: int
    week: int
    observed_at: str
    scoring_fingerprint: str
    observations: tuple[WeeklyProjectionObservation, ...]
    #: ``{reason: count}`` — ``placeholder_no_projection``, ``no_game_id``,
    #: ``model_company_mismatch``, ``season_mismatch``, ``week_mismatch``,
    #: ``season_type_mismatch``, ``missing_player_id``, ``not_a_mapping``,
    #: ``unrecognized_position``, ``duplicate_player_id``.
    refused: Mapping[str, int]
    #: ``{canonical position: sorted stat keys the provider published}``
    #: measured over this batch's accepted rows.
    provider_vocabulary: Mapping[str, tuple[str, ...]]

    def by_player_id(self) -> dict[str, WeeklyProjectionObservation]:
        return {o.sleeper_player_id: o for o in self.observations}


class WeeklyProjectionError(ValueError):
    """Structural misuse: an unusable scoring card, a naive timestamp, or
    a census entry that no longer matches this module."""


# ── Helpers ──────────────────────────────────────────────────────────


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise WeeklyProjectionError(f"timestamp {value!r} is naive; pass a timezone-aware UTC time")
    return value.astimezone(timezone.utc).isoformat()


def _parse_instant(value: datetime | str, *, what: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise WeeklyProjectionError(f"{what} {value!r} is not ISO-8601") from exc
    if dt.tzinfo is None:
        raise WeeklyProjectionError(f"{what} {value!r} is naive; timezone-aware required")
    return dt.astimezone(timezone.utc)


def _ms_to_iso(raw: Any) -> str | None:
    try:
        ms = float(raw)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _is_event_key(key: str) -> bool:
    return key not in _NON_EVENT_KEYS and not key.startswith(_NON_EVENT_PREFIXES)


def _numeric_stat_line(raw: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(raw, Mapping):
        return out
    for key, value in raw.items():
        if value is None or isinstance(value, bool):
            continue
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _scoring_map(scoring_settings: Any) -> Mapping[str, Any]:
    settings = getattr(scoring_settings, "scoring_settings", None)
    if isinstance(settings, Mapping):
        return settings
    if isinstance(scoring_settings, Mapping):
        return scoring_settings
    raise WeeklyProjectionError(
        "scoring_settings must be a league scoring card mapping or a LeagueIntelConfig, "
        f"got {type(scoring_settings).__name__}"
    )


def _league_paid_keys(scoring: Mapping[str, Any]) -> list[str]:
    paid = []
    for key, raw in scoring.items():
        try:
            rate = float(raw)
        except (TypeError, ValueError):
            continue
        if rate != 0.0:
            paid.append(str(key))
    return sorted(paid)


@lru_cache(maxsize=512)
def _is_team_defense_key(key: str) -> bool:
    """Canonical classification: a key for an asset class no individual
    player earns (team D/ST). Delegated, never re-tabled here."""
    from src.nfl_data.scoring_coverage import Coverage, classify

    return classify(key) is Coverage.NOT_APPLICABLE


def _grammar_applies(key: str, positions: frozenset[str]) -> bool:
    if key.startswith("idp_"):
        return bool(positions & _IDP_POSITIONS)
    if key.startswith(_KICKER_PREFIXES):
        return "K" in positions
    match = _BONUS_POSITION_SUFFIX.match(key)
    if match:
        return match.group(1).upper() in positions
    return True


def _uncovered_for(
    positions: frozenset[str],
    league_paid: Sequence[str],
    vocabulary: Mapping[str, frozenset[str]],
    provider_all: frozenset[str],
) -> tuple[str, ...]:
    covered: set[str] = set()
    for pos in positions:
        covered |= vocabulary.get(pos, frozenset())
    out = []
    for key in league_paid:
        if key in covered:
            continue
        if key in provider_all:
            # The provider projects this category, but only for other
            # positions — its own statement that the event is not
            # expected here. Not a coverage gap for this player.
            continue
        if not _grammar_applies(key, positions):
            continue
        if _is_team_defense_key(key):
            continue
        out.append(key)
    return tuple(out)


def _census_entry() -> Mapping[str, Any]:
    entry = census.get_source(CENSUS_SOURCE_KEY)
    if entry is None:
        raise WeeklyProjectionError(
            f"{CENSUS_SOURCE_KEY!r} is missing from the C5-PROJ-A census; every projection "
            "observation must be traceable to a censused source"
        )
    if entry.get("horizons") != [HORIZON]:
        raise WeeklyProjectionError(
            f"{CENSUS_SOURCE_KEY!r} census horizons {entry.get('horizons')!r} != [{HORIZON!r}]"
        )
    if entry.get("gameType") != GAME_TYPE:
        raise WeeklyProjectionError(
            f"{CENSUS_SOURCE_KEY!r} census gameType {entry.get('gameType')!r} != {GAME_TYPE!r}"
        )
    return entry


# ── Acquisition (flag-gated) ─────────────────────────────────────────


@dataclass(frozen=True)
class FetchResult:
    """``status`` is ``ok`` | ``feature_disabled`` | ``fetch_failed`` |
    ``bad_payload``. Only ``ok`` carries rows; a refusal is never an
    empty-but-green list."""

    status: str
    season: int
    week: int
    url: str
    observed_at: str | None
    rows: tuple[Mapping[str, Any], ...] = ()
    reason: str = ""


def projection_url(season: int, week: int, *, season_type: str = "regular") -> str:
    query = [("season_type", season_type)] + [("position[]", p) for p in POSITIONS]
    return ENDPOINT_TEMPLATE.format(season=int(season), week=int(week)) + (
        "?" + urllib.parse.urlencode(query)
    )


def _default_http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        body = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
    return body


def fetch_weekly_projection_rows(
    season: int,
    week: int,
    *,
    http_get: Callable[[str, float], bytes] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
    now: Callable[[], datetime] | None = None,
) -> FetchResult:
    """Fetch one week's raw rows. Makes NO network call while the
    ``sleeper_weekly_projections`` flag is off.

    ``observed_at`` is stamped immediately after the body arrives, so it
    is an upper bound on when the provider's numbers were true — the
    property :func:`lock_baseline_at_kickoff` relies on.
    """
    url = projection_url(season, week)
    # Literal flag name on purpose: the reachability audit
    # (tests/api/test_feature_flag_reachability.py) reads literals only.
    if not is_enabled("sleeper_weekly_projections"):
        return FetchResult(
            status="feature_disabled",
            season=int(season),
            week=int(week),
            url=url,
            observed_at=None,
            reason=f"feature flag {FEATURE_FLAG!r} is off",
        )
    getter = http_get or _default_http_get
    clock = now or (lambda: datetime.now(timezone.utc))
    try:
        body = getter(url, timeout)
    except Exception as exc:  # noqa: BLE001 — any transport failure is a refusal
        return FetchResult(
            status="fetch_failed",
            season=int(season),
            week=int(week),
            url=url,
            observed_at=None,
            reason=f"{type(exc).__name__}: {exc}",
        )
    observed_at = _utc_iso(clock())
    try:
        payload = json.loads(body)
    except (TypeError, ValueError) as exc:
        return FetchResult(
            status="bad_payload",
            season=int(season),
            week=int(week),
            url=url,
            observed_at=observed_at,
            reason=f"not JSON: {exc}",
        )
    if not isinstance(payload, list):
        return FetchResult(
            status="bad_payload",
            season=int(season),
            week=int(week),
            url=url,
            observed_at=observed_at,
            reason=f"expected a JSON list, got {type(payload).__name__}",
        )
    return FetchResult(
        status="ok",
        season=int(season),
        week=int(week),
        url=url,
        observed_at=observed_at,
        rows=tuple(r for r in payload if isinstance(r, Mapping)),
    )


# ── Parse + exact-league rescoring ───────────────────────────────────


def build_weekly_observations(
    rows: Iterable[Any],
    *,
    season: int,
    week: int,
    observed_at: datetime | str,
    scoring_settings: Any,
    season_type: str = "regular",
) -> WeeklyProjectionBatch:
    """Turn one fetch's rows into observations scored under
    ``scoring_settings`` (a Sleeper ``scoring_settings`` mapping or a
    ``LeagueIntelConfig``).

    Pure: no I/O, no clock, no flag read — captured rows replay
    deterministically. Raises :class:`WeeklyProjectionError` when the card
    is unusable (``scoring_fingerprint`` is ``None``): scoring under an
    unverifiable card would publish numbers nobody can attribute.
    """
    entry = _census_entry()
    expected_company = str((entry.get("modelAncestry") or {}).get("model") or "")
    scoring = _scoring_map(scoring_settings)
    fingerprint = scoring_fingerprint(scoring)
    if fingerprint is None:
        raise WeeklyProjectionError("scoring card is missing, empty or unusable")
    observed_iso = _parse_instant(observed_at, what="observed_at").isoformat()

    refused: dict[str, int] = {}

    def refuse(reason: str) -> None:
        refused[reason] = refused.get(reason, 0) + 1

    accepted: list[tuple[Mapping[str, Any], dict[str, float], tuple[str, ...]]] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            refuse("not_a_mapping")
            continue
        pid = str(row.get("player_id") or "").strip()
        if not pid:
            refuse("missing_player_id")
            continue
        if str(row.get("season") or "") != str(season):
            refuse("season_mismatch")
            continue
        try:
            row_week = int(row.get("week"))
        except (TypeError, ValueError):
            row_week = None
        if row_week != int(week):
            refuse("week_mismatch")
            continue
        if str(row.get("season_type") or "") != season_type:
            refuse("season_type_mismatch")
            continue
        stats = _numeric_stat_line(row.get("stats"))
        if not any(_is_event_key(k) for k in stats):
            refuse("placeholder_no_projection")
            continue
        if not str(row.get("game_id") or "").strip():
            refuse("no_game_id")
            continue
        company = str(row.get("company") or "")
        if company != expected_company:
            # A different model would be a different independence family;
            # relabelling it as the censused one would double-count or
            # misattribute evidence.
            refuse("model_company_mismatch")
            continue
        player = row.get("player") if isinstance(row.get("player"), Mapping) else {}
        raw_positions = player.get("fantasy_positions") or [player.get("position")]
        positions = tuple(
            dict.fromkeys(
                p for p in (normalize_position(x) for x in raw_positions) if p in POSITIONS
            )
        )
        if not positions:
            refuse("unrecognized_position")
            continue
        if pid in seen_ids:
            refuse("duplicate_player_id")
            continue
        seen_ids.add(pid)
        accepted.append((row, stats, positions))

    vocab_sets: dict[str, set[str]] = {}
    for _row, stats, positions in accepted:
        for pos in positions:
            vocab_sets.setdefault(pos, set()).update(stats)
    vocabulary = {pos: frozenset(keys) for pos, keys in vocab_sets.items()}
    provider_all = frozenset().union(*vocabulary.values()) if vocabulary else frozenset()
    league_paid = _league_paid_keys(scoring)

    observations = []
    for row, stats, positions in accepted:
        player = row.get("player") if isinstance(row.get("player"), Mapping) else {}
        pid = str(row["player_id"]).strip()
        breakdown = score_stat_line(stats, scoring)
        native = stats.get("pts_ppr")
        observations.append(
            WeeklyProjectionObservation(
                census_source_key=CENSUS_SOURCE_KEY,
                provider_family=str(entry["providerFamily"]),
                model_company=str(row.get("company")),
                horizon=HORIZON,
                game_type=GAME_TYPE,
                sleeper_player_id=pid,
                player_key=str(player_asset_key(pid, None, None)),
                position=positions[0],
                fantasy_positions=positions,
                team=(str(row.get("team")) if row.get("team") else None),
                opponent=(str(row.get("opponent")) if row.get("opponent") else None),
                game_id=str(row.get("game_id")),
                season=int(season),
                week=int(week),
                season_type=season_type,
                stat_line=MappingProxyType(dict(sorted(stats.items()))),
                league_scored_points=breakdown.total_points,
                scoring_fingerprint=fingerprint,
                scoring_components=tuple(breakdown.components),
                scoring_warnings=tuple(breakdown.warnings),
                uncovered_scoring_keys=_uncovered_for(
                    frozenset(positions), league_paid, vocabulary, provider_all
                ),
                native_points_ppr=native,
                observed_at=observed_iso,
                provider_updated_at=_ms_to_iso(row.get("updated_at") or row.get("last_modified")),
            )
        )
    observations.sort(key=lambda o: o.sleeper_player_id)

    return WeeklyProjectionBatch(
        season=int(season),
        week=int(week),
        observed_at=observed_iso,
        scoring_fingerprint=fingerprint,
        observations=tuple(observations),
        refused=MappingProxyType(dict(sorted(refused.items()))),
        provider_vocabulary=MappingProxyType(
            {pos: tuple(sorted(keys)) for pos, keys in sorted(vocabulary.items())}
        ),
    )


# ── Kickoff baseline lock ────────────────────────────────────────────


@dataclass(frozen=True)
class BaselineEntry:
    observation: WeeklyProjectionObservation
    kickoff_at: str
    #: ``True`` once ``now`` is at/after kickoff (the baseline can no
    #: longer change), ``False`` before it, ``None`` when no ``now`` was
    #: supplied — unknown is not "unlocked".
    locked: bool | None


@dataclass(frozen=True)
class BaselineLock:
    baselines: Mapping[str, BaselineEntry]
    #: Players observed only AFTER their kickoff: no provider baseline
    #: exists. Never back-filled with an in-game observation.
    no_pre_kickoff_observation: tuple[str, ...]
    #: Players none of whose observations name a game with a known
    #: kickoff. Unknown kickoff is not "already locked".
    unknown_kickoff: tuple[str, ...]
    #: Observations discarded because they were fetched after kickoff.
    post_kickoff_observations_ignored: int = field(default=0)


def lock_baseline_at_kickoff(
    observations: Iterable[WeeklyProjectionObservation],
    kickoffs: Mapping[str, datetime | str],
    *,
    now: datetime | str | None = None,
) -> BaselineLock:
    """Per player, the LAST observation fetched at or before that
    observation's game kickoff (``kickoffs`` is keyed by ``game_id``).

    Uses ``observed_at`` — when we held the number — not the provider's
    ``updated_at``: a row fetched after kickoff may carry an older stamp
    yet still be a post-kickoff read, and a missing stamp must not make a
    row eligible. Ties on ``observed_at`` break on ``provider_updated_at``
    then input order, deterministically.
    """
    kickoff_at = {
        str(gid): _parse_instant(ts, what=f"kickoff for {gid}") for gid, ts in kickoffs.items()
    }
    now_dt = _parse_instant(now, what="now") if now is not None else None

    best: dict[str, tuple[tuple[datetime, str, int], WeeklyProjectionObservation]] = {}
    seen_with_kickoff: set[str] = set()
    seen: set[str] = set()
    ignored = 0
    for idx, obs in enumerate(observations):
        pid = obs.sleeper_player_id
        seen.add(pid)
        kick = kickoff_at.get(obs.game_id)
        if kick is None:
            continue
        seen_with_kickoff.add(pid)
        fetched = _parse_instant(obs.observed_at, what="observed_at")
        if fetched > kick:
            ignored += 1
            continue
        key = (fetched, obs.provider_updated_at or "", idx)
        current = best.get(pid)
        if current is None or key > current[0]:
            best[pid] = (key, obs)

    baselines = {}
    for pid in sorted(best):
        obs = best[pid][1]
        kick = kickoff_at[obs.game_id]
        locked = None if now_dt is None else now_dt >= kick
        baselines[pid] = BaselineEntry(observation=obs, kickoff_at=kick.isoformat(), locked=locked)

    return BaselineLock(
        baselines=MappingProxyType(baselines),
        no_pre_kickoff_observation=tuple(sorted(seen_with_kickoff - set(best))),
        unknown_kickoff=tuple(sorted(seen - seen_with_kickoff)),
        post_kickoff_observations_ignored=ignored,
    )


# ── Ensemble adapter ─────────────────────────────────────────────────


def to_projection_observation(obs: WeeklyProjectionObservation) -> ProjectionObservation:
    """Adapt to the C5-PROJ-B contract so :func:`combine_ensemble` can take
    it as a WEEKLY-horizon member (``games = 1``, points = the week's
    projection). ``as_of`` is the PROVIDER stamp; a row without one is
    refused rather than dated by our fetch time.
    """
    if obs.provider_updated_at is None:
        raise ProjectionObservationError(
            f"{obs.sleeper_player_id!r}: no provider updated_at; fetch time is not data "
            "freshness, so this observation cannot be dated for the ensemble"
        )
    entry = _census_entry()
    return ProjectionObservation(
        census_source_key=obs.census_source_key,
        provider_family=obs.provider_family,
        evidence_class=str(entry["evidenceClass"]),
        horizon=obs.horizon,
        access_posture=str(entry["accessPosture"]),
        player_key=obs.player_key,
        position=obs.position,
        season=obs.season,
        as_of=obs.provider_updated_at,
        games=1.0,
        league_scored_fpg=obs.league_scored_points,
        league_scored_is_native=False,
        native_fpg=obs.native_points_ppr,
        native_is_scoring_native=False,
        stat_line_available=True,
        proj_high=None,
        proj_low=None,
        is_proxy=False,
    )
