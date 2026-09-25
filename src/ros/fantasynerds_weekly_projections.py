"""C5-PROJ-C — Fantasy Nerds weekly projections (keyed).

Fantasy Nerds' API documents two weekly projection endpoints
(https://api.fantasynerds.com/docs/nfl, retrieved 2026-09-25):

* ``GET https://api.fantasynerds.com/v1/nfl/weekly-projections?apikey=…`` —
  "weekly projections with statistical category projections for Weeks
  1 - 18";
* ``GET https://api.fantasynerds.com/v1/nfl/idp-weekly?apikey=…`` —
  "weekly projections for IDP players".

The key is a required ``apikey`` query parameter (the provider documents
no header alternative), so it IS on the wire URL. It never leaves
:func:`src.ros.keyed_weekly_projections.fetch_keyed_json`: the stored URL
is redacted and every error message is scrubbed.

**Ancestry — this is an AGGREGATE, not an independent model.** Fantasy
Nerds states it aggregates "rankings and projections from a number of
sites" into a consensus weighted by each site's measured accuracy
("Nerd Rank", https://www.fantasynerds.com/about/nerd-rank; weekly page
https://www.fantasynerds.com/nfl/weekly-projections). Its named
constituents include RotoWire, Draft Sharks, FootballGuys, Pro Football
Focus, 4for4, Yahoo, NFL.com, CBS Sports and ESPN.com. The census entry
records those constituents so an ensemble never counts Fantasy Nerds AND
one of its constituents (e.g. RotoWire via Sleeper) as independent votes
— see :func:`src.ros.projection_source_census.ancestry_overlaps`.

**The response schema is NOT published.** The docs list endpoints and the
``apikey`` parameter only; no field names, no sample body, and no week
parameter (the feed serves the provider's current week). The public web
page shows the categories per position (QB: CMP / ATT / PASS YDS / PASS TD
/ INT / RUSH YDS / RUSH TD / FMBL; RB/WR/TE add REC / REC YDS / REC TD /
RUSH ATT; K: XP / FG; IDP: TKLS / ASS TKLS / SACKS / PASS DEF / INT), so
:data:`STAT_MAPPING` is keyed on those CATEGORIES with explicit accepted
spellings, marked :data:`SCHEMA_VERIFIED` ``= False``. The parser is built
to fail LOUDLY rather than quietly on a mismatch:

* a row whose fields match no accepted spelling is refused
  ``no_mapped_stats`` and every unrecognised numeric field is reported in
  ``unmapped_provider_fields``, which makes the fetch UNHEALTHY
  (:func:`~src.ros.keyed_weekly_projections.assess_fetch_health`), so
  :func:`source_available` stays False;
* a payload that does not state its season AND week is refused
  ``week_unverifiable`` — the current-week feed is never assumed to be the
  week the caller asked for;
* genuinely ambiguous categories are NOT mapped: a bare ``FMBL`` / ``fumbles``
  might be fumbles or fumbles LOST, a bare IDP ``TKLS`` / ``tackles`` might
  be solo or combined, and a bare kicker ``XP`` / ``FG`` might be made or
  attempted. Those league rules stay uncovered until the first
  credentialed capture proves the meaning.

The first credentialed fetch is therefore also the schema check; see the
census entry's ``responseSchemaStatus``.

Acquisition sits behind the ``fantasynerds_weekly_projections`` flag
(default OFF) AND ``FANTASYNERDS_API_KEY``. **Seasonal intelligence lane
only** — never dynasty value.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from src.api.feature_flags import is_enabled
from src.ros import keyed_weekly_projections as kw
from src.ros.sleeper_weekly_projections import lock_baseline_at_kickoff, to_projection_observation

__all__ = [
    "CENSUS_SOURCE_KEY",
    "CREDENTIAL_ENV_VAR",
    "FEATURE_FLAG",
    "FEEDS",
    "MODEL_COMPANY",
    "SCHEMA_VERIFIED",
    "STAT_MAPPING",
    "STAT_MAPPING_VERSION",
    "build_weekly_observations",
    "fetch_weekly_projection_rows",
    "lock_baseline_at_kickoff",
    "parse_rows",
    "request_for",
    "source_available",
    "to_projection_observation",
]

CENSUS_SOURCE_KEY = "fantasyNerdsWeeklyProjections"
FEATURE_FLAG = "fantasynerds_weekly_projections"
#: Canonical secret. Never committed, never logged; see ``.env.example``.
CREDENTIAL_ENV_VAR = "FANTASYNERDS_API_KEY"
#: The ``model_company`` on every observation: the Nerd Rank CONSENSUS.
MODEL_COMPANY = "fantasynerds_consensus"
API_BASE = "https://api.fantasynerds.com/v1/nfl"
FEEDS: Mapping[str, str] = {"offense": "weekly-projections", "idp": "idp-weekly"}

#: No public response schema exists (module docstring). Flip to True only
#: with a committed capture proving every accepted spelling below.
SCHEMA_VERIFIED = False
STAT_MAPPING_VERSION = "fantasynerds-v1-weekly/2026-09-25.categories-unverified"


def normalize_field(name: str) -> str:
    """Case/separator-insensitive field key: ``pass_yds`` == ``passYds``."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


#: Sleeper stat key -> accepted provider spellings of the public category.
#: Only UNAMBIGUOUS categories are mapped (module docstring).
STAT_MAPPING: Mapping[str, tuple[str, ...]] = {
    "pass_cmp": ("passing_completions", "pass_cmp", "pass_completions", "completions"),
    "pass_att": ("passing_attempts", "pass_att", "pass_attempts"),
    "pass_yd": ("passing_yards", "pass_yds", "pass_yards"),
    "pass_td": ("passing_touchdowns", "passing_td", "pass_td", "pass_tds"),
    "pass_int": ("passing_interceptions", "pass_int", "interceptions_thrown"),
    "rush_att": ("rushing_attempts", "rush_att", "rush_attempts", "carries"),
    "rush_yd": ("rushing_yards", "rush_yds", "rush_yards"),
    "rush_td": ("rushing_touchdowns", "rushing_td", "rush_td", "rush_tds"),
    "rec": ("receptions", "rec"),
    "rec_yd": ("receiving_yards", "rec_yds", "rec_yards"),
    "rec_td": ("receiving_touchdowns", "receiving_td", "rec_td", "rec_tds"),
    "fum_lost": ("fumbles_lost", "fum_lost"),
    # A bare ``XP`` / ``FG`` (the public column labels) could be made or
    # attempted; only explicit "made" spellings are mapped.
    "xpm": ("extra_points_made", "xpm"),
    "fgm": ("field_goals_made", "fgm"),
    # IDP: solo is only mapped under an explicit "solo" spelling; a bare
    # "tackles" is ambiguous (solo vs combined) and stays unmapped.
    "idp_tkl_solo": ("solo_tackles", "tackles_solo", "solo_tkl"),
    "idp_tkl_ast": ("assisted_tackles", "ass_tkls", "assist_tackles", "tackles_assisted"),
    "idp_sack": ("sacks", "sack"),
    "idp_pass_def": ("passes_defended", "pass_def", "passes_defensed"),
    "idp_int": ("interceptions", "def_int", "defensive_interceptions"),
}

IDP_ONLY_KEYS: frozenset[str] = frozenset(k for k in STAT_MAPPING if k.startswith("idp_"))

#: Linear identities only (see :mod:`src.ros.keyed_weekly_projections`).
DERIVATIONS: tuple[kw.LinearDerivation, ...] = (
    kw.LinearDerivation("pass_inc", (("pass_att", 1.0), ("pass_cmp", -1.0))),
    kw.LinearDerivation("bonus_rec_te", (("rec", 1.0),), frozenset({"TE"})),
    kw.LinearDerivation("idp_tkl", (("idp_tkl_solo", 1.0), ("idp_tkl_ast", 1.0))),
)

#: Row fields that are identity / schedule / provider totals, not stats.
IGNORED_PROVIDER_FIELDS: frozenset[str] = frozenset(
    {
        "playerId", "player_id", "id", "season", "week", "rank", "byeWeek", "bye_week",
        "jersey", "age", "proj_pts", "projected_points", "fantasy_points", "points",
        "pts", "ppr", "half_ppr", "standard", "std",
    }
)  # fmt: skip

_ID_FIELDS = ("playerId", "player_id", "id")
_NAME_FIELDS = ("name", "displayName", "display_name", "player_name")
_TEAM_FIELDS = ("team", "team_abbr", "teamAbbr")
_POSITION_FIELDS = ("position", "pos")
_OPPONENT_FIELDS = ("opponent", "opp")
_UPDATED_FIELDS = ("updated", "last_updated", "lastUpdated")
_ENVELOPE_LIST_KEYS = ("players", "projections", "data")


# ── Acquisition ──────────────────────────────────────────────────────


def request_for(feed: str, secret: str) -> tuple[str, dict[str, str]]:
    """``(url, headers)``. Fantasy Nerds takes the key only as a query
    parameter; callers must never log this URL (use the result's
    redacted ``url``)."""
    if feed not in FEEDS:
        raise ValueError(f"unknown Fantasy Nerds feed {feed!r}; expected one of {sorted(FEEDS)}")
    return f"{API_BASE}/{FEEDS[feed]}?" + urllib.parse.urlencode({"apikey": secret}), {}


def fetch_weekly_projection_rows(
    season: int,
    week: int,
    *,
    feed: str = "offense",
    env: Mapping[str, str] | None = None,
    http_get: kw.HttpGet | None = None,
    timeout: float = kw.HTTP_TIMEOUT_SECONDS,
    now: Callable[[], datetime] | None = None,
) -> kw.KeyedFetchResult:
    """Fetch one feed. ``season``/``week`` are what the caller EXPECTS; the
    provider serves its current week and the parser refuses rows that do
    not state a matching one. No network call while the flag is off or
    ``FANTASYNERDS_API_KEY`` is absent (``credential_missing``)."""
    # Literal flag name on purpose: the reachability audit reads literals.
    flag_on = is_enabled("fantasynerds_weekly_projections")
    credential = kw.read_credential(CREDENTIAL_ENV_VAR, env) if flag_on else None
    return kw.fetch_keyed_json(
        census_source_key=CENSUS_SOURCE_KEY,
        feed=feed,
        season=season,
        week=week,
        flag_name=FEATURE_FLAG,
        flag_on=flag_on,
        credential=credential,
        credential_env_var=CREDENTIAL_ENV_VAR,
        build_request=lambda secret: request_for(feed, secret),
        http_get=http_get,
        timeout=timeout,
        now=now,
    )


def source_available(
    last_health: kw.SourceHealth | None, *, env: Mapping[str, str] | None = None
) -> kw.SourceCapability:
    return kw.source_capability(
        census_source_key=CENSUS_SOURCE_KEY,
        flag_name=FEATURE_FLAG,
        flag_on=is_enabled("fantasynerds_weekly_projections"),
        credential_env_var=CREDENTIAL_ENV_VAR,
        credential_present=kw.read_credential(CREDENTIAL_ENV_VAR, env) is not None,
        last_health=last_health,
    )


# ── Parse ────────────────────────────────────────────────────────────


def _first(raw: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = raw.get(name)
        if value not in (None, ""):
            return value
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flatten(payload: Any) -> tuple[list[tuple[Mapping[str, Any], str | None]], Any, Any]:
    """``([(row, position-from-envelope)], season, week)``. Accepts a bare
    list, ``{…, players|projections|data: [...]}``, or a position-keyed
    ``{"QB": [...], …}`` map (optionally nested under one of those keys).
    Anything else raises."""
    season = week = None
    body = payload
    if isinstance(payload, Mapping):
        season = payload.get("season")
        week = payload.get("week")
        for key in _ENVELOPE_LIST_KEYS:
            if key in payload:
                body = payload[key]
                break
    out: list[tuple[Mapping[str, Any], str | None]] = []
    if isinstance(body, list):
        out = [(r, None) for r in body if isinstance(r, Mapping)]
    elif isinstance(body, Mapping):
        for pos, rows in body.items():
            if isinstance(rows, list):
                out.extend((r, str(pos)) for r in rows if isinstance(r, Mapping))
    if not out:
        raise kw.WeeklyProjectionError(
            "Fantasy Nerds weekly projections: unrecognised envelope "
            f"({type(payload).__name__}); no player rows found"
        )
    return out, season, week


def parse_rows(payload: Any, *, payload_last_modified: str | None = None) -> list[kw.ProviderRow]:
    rows, env_season, env_week = _flatten(payload)
    out = []
    for raw, env_pos in rows:
        stats_src: Mapping[str, Any] = raw
        nested = raw.get("stats") or raw.get("projections")
        if isinstance(nested, Mapping):
            stats_src = {**{k: v for k, v in raw.items() if k not in ("stats", "projections")}}
            stats_src.update(nested)
        position = _first(raw, _POSITION_FIELDS) or env_pos
        team = _first(raw, _TEAM_FIELDS)
        pid = _first(raw, _ID_FIELDS)
        out.append(
            kw.ProviderRow(
                ref=kw.ProviderPlayerRef(
                    provider_player_id=str(pid or "").strip(),
                    name=(str(_first(raw, _NAME_FIELDS)) if _first(raw, _NAME_FIELDS) else None),
                    team=(str(team) if team else None),
                    position=(str(position) if position else None),
                ),
                positions=((str(position),) if position else ()),
                opponent=(
                    str(_first(raw, _OPPONENT_FIELDS)) if _first(raw, _OPPONENT_FIELDS) else None
                ),
                season=_int_or_none(raw.get("season", env_season)),
                week=_int_or_none(raw.get("week", env_week)),
                season_type=None,
                provider_stats=kw.numeric_fields(stats_src),
                null_provider_fields=kw.null_fields(stats_src),
                provider_updated_at=(
                    kw.instant_or_none(_first(raw, _UPDATED_FIELDS)) or payload_last_modified
                ),
                is_team_unit=str(position or "").upper() in {"DEF", "DST", "D/ST"},
            )
        )
    return out


def build_weekly_observations(
    payload: Any,
    *,
    season: int,
    week: int,
    observed_at: datetime | str,
    scoring_settings: Any,
    resolve_player: Callable[[kw.ProviderPlayerRef], str | None],
    payload_last_modified: str | None = None,
) -> kw.MappedWeeklyBatch:
    """Pure: parse + map + rescore under ``scoring_settings``."""
    return kw.build_mapped_observations(
        parse_rows(payload, payload_last_modified=payload_last_modified),
        census_source_key=CENSUS_SOURCE_KEY,
        model_company=MODEL_COMPANY,
        stat_mapping=STAT_MAPPING,
        stat_mapping_version=STAT_MAPPING_VERSION,
        ignored_provider_fields=IGNORED_PROVIDER_FIELDS,
        season=season,
        week=week,
        observed_at=observed_at,
        scoring_settings=scoring_settings,
        resolve_player=resolve_player,
        idp_only_keys=IDP_ONLY_KEYS,
        derivations=DERIVATIONS,
        field_normalizer=normalize_field,
    )
