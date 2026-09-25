"""C5-PROJ-C — SportsDataIO weekly projected player game stats (keyed).

SportsDataIO's NFL v3 Projections API publishes a per-player projected
GAME stat line for every week ("Projected Player Game Stats by Week"),
plus a separate IDP feed ("IDP Projected Player Game Stats by Week").
Endpoints and field names are taken from SportsDataIO's published OpenAPI
description of the NFL v3 Projections API
(https://api.apis.guru/v2/specs/sportsdata.io/nfl-v3-projections/1.0/openapi.json,
schema ``PlayerGameProjection``; developer portal
https://sportsdata.io/developers/api-documentation/nfl). SportsDataIO
describes these as its own "proprietary in-house machine learning
models", customized per game by Tuesday 2 pm ET and "updated every 15
minutes until kick off" (https://sportsdata.io/developers/workflow-guide/nfl).
It is therefore its OWN independence family (``sportsDataIo``) — not an
aggregate of other providers. FantasyData is the same company and model;
a FantasyData-branded feed is the same family.

What this module adds on top of :mod:`src.ros.keyed_weekly_projections`:

* the canonical credential env var :data:`CREDENTIAL_ENV_VAR`
  (``SPORTSDATAIO_API_KEY``), sent in the ``Ocp-Apim-Subscription-Key``
  HEADER — SportsDataIO accepts it there, so the key never appears in a
  URL at all;
* the two request builders (offense, IDP);
* :data:`STAT_MAPPING` — the explicit SportsDataIO-field → Sleeper-stat
  table, plus the fields deliberately ignored (metadata, DFS salaries,
  per-attempt ratios, longest-play fields) so everything else is
  reported as UNMAPPED rather than dropped silently;
* identity via the injected ``resolve_player``: SportsDataIO's
  ``PlayerID`` is the FantasyData id, which Sleeper's player directory
  carries as ``fantasy_data_id`` — an exact external-id join the identity
  owner can provide. Unresolved rows are refused, never guessed.

Acquisition sits behind the ``sportsdataio_weekly_projections`` flag
(default OFF) AND the credential: :func:`source_available` is flag ON and
``SPORTSDATAIO_API_KEY`` present and the last fetch assessed healthy.

**Seasonal intelligence lane only** — never dynasty value.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
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
    "IGNORED_PROVIDER_FIELDS",
    "MODEL_COMPANY",
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

CENSUS_SOURCE_KEY = "sportsDataIoWeeklyProjections"
FEATURE_FLAG = "sportsdataio_weekly_projections"
#: Canonical secret. Never committed, never logged; see ``.env.example``.
CREDENTIAL_ENV_VAR = "SPORTSDATAIO_API_KEY"
MODEL_COMPANY = "sportsdataio"
API_BASE = "https://api.sportsdata.io/v3/nfl/projections/json"
#: ``feed -> endpoint name`` (OpenAPI paths
#: ``/{format}/PlayerGameProjectionStatsByWeek/{season}/{week}`` and
#: ``/{format}/IdpPlayerGameProjectionStatsByWeek/{season}/{week}``).
FEEDS: Mapping[str, str] = {
    "offense": "PlayerGameProjectionStatsByWeek",
    "idp": "IdpPlayerGameProjectionStatsByWeek",
}
#: SportsDataIO ``SeasonType``: 1 regular, 2 preseason, 3 postseason.
_SEASON_TYPE_CODES: Mapping[int, str] = {1: "regular", 2: "pre", 3: "post"}
_SEASON_SUFFIX: Mapping[str, str] = {"regular": "REG", "pre": "PRE", "post": "POST"}

STAT_MAPPING_VERSION = "sportsdataio-nfl-v3-PlayerGameProjection/2026-09-25.v1"

#: Sleeper stat key -> SportsDataIO ``PlayerGameProjection`` field(s).
#: Every entry is a LINEAR per-game count/yardage with the same meaning
#: as Sleeper's key.
STAT_MAPPING: Mapping[str, tuple[str, ...]] = {
    # passing
    "pass_att": ("PassingAttempts",),
    "pass_cmp": ("PassingCompletions",),
    "pass_yd": ("PassingYards",),
    "pass_td": ("PassingTouchdowns",),
    "pass_int": ("PassingInterceptions",),
    "pass_sack": ("PassingSacks",),
    "pass_2pt": ("TwoPointConversionPasses",),
    # rushing
    "rush_att": ("RushingAttempts",),
    "rush_yd": ("RushingYards",),
    "rush_td": ("RushingTouchdowns",),
    "rush_2pt": ("TwoPointConversionRuns",),
    # receiving
    "rec": ("Receptions",),
    "rec_tgt": ("ReceivingTargets",),
    "rec_yd": ("ReceivingYards",),
    "rec_td": ("ReceivingTouchdowns",),
    "rec_2pt": ("TwoPointConversionReceptions",),
    # ball security
    "fum": ("Fumbles",),
    "fum_lost": ("FumblesLost",),
    # player special teams (the RB/WR/TE/LB rules; not team D/ST)
    "kr_yd": ("KickReturnYards",),
    "pr_yd": ("PuntReturnYards",),
    "pr": ("PuntReturns",),
    # Sleeper emits the umbrella ``st_td`` AND the split keys for one
    # event (they stack — src.league_intel.scorer); the split key names are
    # the ones src.nfl_data.realized_points scores.
    "st_td": ("SpecialTeamsTouchdowns",),
    "kick_ret_td": ("KickReturnTouchdowns",),
    "punt_ret_td": ("PuntReturnTouchdowns",),
    "st_tkl_solo": ("SpecialTeamsSoloTackles",),
    "st_ff": ("SpecialTeamsFumblesForced",),
    "st_fum_rec": ("SpecialTeamsFumblesRecovered",),
    # kicking
    "fgm": ("FieldGoalsMade",),
    "fga": ("FieldGoalsAttempted",),
    "fgm_0_19": ("FieldGoalsMade0to19",),
    "fgm_20_29": ("FieldGoalsMade20to29",),
    "fgm_30_39": ("FieldGoalsMade30to39",),
    "fgm_40_49": ("FieldGoalsMade40to49",),
    "fgm_50p": ("FieldGoalsMade50Plus",),
    "xpm": ("ExtraPointsMade",),
    "xpa": ("ExtraPointsAttempted",),
    # individual defense (IDP positions only — see IDP_ONLY_KEYS)
    "idp_tkl_solo": ("SoloTackles",),
    "idp_tkl_ast": ("AssistedTackles",),
    "idp_tkl": ("Tackles",),
    "idp_sack": ("Sacks",),
    "idp_sack_yd": ("SackYards",),
    "idp_tkl_loss": ("TacklesForLoss",),
    "idp_qb_hit": ("QuarterbackHits",),
    "idp_pass_def": ("PassesDefended",),
    "idp_ff": ("FumblesForced",),
    "idp_fum_rec": ("FumblesRecovered",),
    "idp_int": ("Interceptions",),
    "idp_int_ret_yd": ("InterceptionReturnYards",),
    "idp_fum_ret_yd": ("FumbleReturnYards",),
    "idp_def_td": ("DefensiveTouchdowns",),
    "idp_safe": ("Safeties",),
    "idp_blk_kick": ("BlockedKicks",),
}

IDP_ONLY_KEYS: frozenset[str] = frozenset(k for k in STAT_MAPPING if k.startswith("idp_"))

#: Linear identities of expectations only (module docstring of
#: :mod:`src.ros.keyed_weekly_projections`). ``idp_tkl`` is derived only
#: when the row did not publish ``Tackles`` itself.
DERIVATIONS: tuple[kw.LinearDerivation, ...] = (
    kw.LinearDerivation("pass_inc", (("pass_att", 1.0), ("pass_cmp", -1.0))),
    kw.LinearDerivation("bonus_rec_te", (("rec", 1.0),), frozenset({"TE"})),
    kw.LinearDerivation("fgmiss", (("fga", 1.0), ("fgm", -1.0))),
    kw.LinearDerivation("xpmiss", (("xpa", 1.0), ("xpm", -1.0))),
    kw.LinearDerivation("idp_tkl", (("idp_tkl_solo", 1.0), ("idp_tkl_ast", 1.0))),
)

#: Numeric ``PlayerGameProjection`` fields that are NOT scoreable stat
#: counts: identity/schedule metadata, snap counts, DFS salaries and the
#: provider's own point totals, weather, and per-attempt ratios / longest
#: plays (not additive; Sleeper's ``*_40p`` bonuses need play-level data).
#: Everything numeric outside this set and :data:`STAT_MAPPING` is reported
#: as unmapped.
IGNORED_PROVIDER_FIELDS: frozenset[str] = frozenset(
    {
        # identity / schedule / status
        "PlayerID", "PlayerGameID", "GameKey", "GlobalGameID", "GlobalOpponentID",
        "GlobalTeamID", "ScoreID", "TeamID", "OpponentID", "Season", "SeasonType",
        "Week", "Number", "Played", "Started", "Activated", "IsGameOver",
        "OpponentRank", "OpponentPositionRank",
        # snaps
        "OffensiveSnapsPlayed", "DefensiveSnapsPlayed", "SpecialTeamsSnapsPlayed",
        "OffensiveTeamSnaps", "DefensiveTeamSnaps", "SpecialTeamsTeamSnaps",
        # provider point totals + DFS
        "FantasyPoints", "FantasyPointsPPR", "FantasyPointsFanDuel",
        "FantasyPointsDraftKings", "FantasyPointsYahoo", "FantasyPointsFantasyDraft",
        "FanDuelSalary", "DraftKingsSalary", "YahooSalary", "FantasyDataSalary",
        "FantasyDraftSalary", "VictivSalary",
        # weather
        "Temperature", "Humidity", "WindSpeed",
        # ratios / longest plays / derived percentages
        "PassingCompletionPercentage", "PassingYardsPerAttempt",
        "PassingYardsPerCompletion", "PassingRating", "PassingLong", "RushingLong",
        "RushingYardsPerAttempt", "ReceivingLong", "ReceivingYardsPerReception",
        "ReceivingYardsPerTarget", "ReceptionPercentage", "KickReturnLong",
        "PuntReturnLong", "KickReturnYardsPerAttempt", "PuntReturnYardsPerAttempt",
        "FieldGoalPercentage", "FieldGoalsLongestMade", "PuntAverage", "PuntNetAverage",
        "PuntLong",
    }
)  # fmt: skip


# ── Acquisition ──────────────────────────────────────────────────────


def request_for(
    feed: str, season: int, week: int, secret: str, *, season_type: str = "regular"
) -> tuple[str, dict[str, str]]:
    """``(url, headers)``. The key travels in the header only."""
    if feed not in FEEDS:
        raise ValueError(f"unknown SportsDataIO feed {feed!r}; expected one of {sorted(FEEDS)}")
    url = f"{API_BASE}/{FEEDS[feed]}/{int(season)}{_SEASON_SUFFIX[season_type]}/{int(week)}"
    return url, {"Ocp-Apim-Subscription-Key": secret}


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
    """Fetch one feed for one week. No network call while the flag is off
    or ``SPORTSDATAIO_API_KEY`` is absent (``credential_missing``). The IDP
    feed is a separate subscription scope; its failure does not affect the
    offense feed."""
    # Literal flag name on purpose: the reachability audit reads literals.
    flag_on = is_enabled("sportsdataio_weekly_projections")
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
        build_request=lambda secret: request_for(feed, season, week, secret),
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
        flag_on=is_enabled("sportsdataio_weekly_projections"),
        credential_env_var=CREDENTIAL_ENV_VAR,
        credential_present=kw.read_credential(CREDENTIAL_ENV_VAR, env) is not None,
        last_health=last_health,
    )


# ── Parse ────────────────────────────────────────────────────────────


def _row(raw: Mapping[str, Any], payload_last_modified: str | None) -> kw.ProviderRow:
    try:
        season_type = _SEASON_TYPE_CODES.get(int(raw.get("SeasonType")), "other")
    except (TypeError, ValueError):
        season_type = None

    def _int(key: str) -> int | None:
        try:
            return int(raw.get(key))
        except (TypeError, ValueError):
            return None

    positions = tuple(p for p in (raw.get("Position"), raw.get("FantasyPosition")) if p)
    ppr = raw.get("FantasyPointsPPR")
    return kw.ProviderRow(
        ref=kw.ProviderPlayerRef(
            provider_player_id=str(raw.get("PlayerID") or "").strip(),
            name=(str(raw["Name"]) if raw.get("Name") else None),
            team=(str(raw["Team"]) if raw.get("Team") else None),
            position=(str(raw["Position"]) if raw.get("Position") else None),
        ),
        positions=positions,
        opponent=(str(raw["Opponent"]) if raw.get("Opponent") else None),
        season=_int("Season"),
        week=_int("Week"),
        season_type=season_type,
        provider_stats=kw.numeric_fields(raw),
        null_provider_fields=kw.null_fields(raw),
        # No per-row stamp in the published schema; ``Updated`` is honoured
        # if the live feed carries one, else the payload's Last-Modified.
        provider_updated_at=kw.instant_or_none(raw.get("Updated")) or payload_last_modified,
        native_points_ppr=(float(ppr) if isinstance(ppr, (int, float)) else None),
    )


def parse_rows(payload: Any, *, payload_last_modified: str | None = None) -> list[kw.ProviderRow]:
    """The documented envelope is a JSON array of ``PlayerGameProjection``."""
    if not isinstance(payload, list):
        raise kw.WeeklyProjectionError(
            f"SportsDataIO projections: expected a JSON array, got {type(payload).__name__}"
        )
    return [_row(r, payload_last_modified) for r in payload if isinstance(r, Mapping)]


def build_weekly_observations(
    payload_or_rows: Any,
    *,
    season: int,
    week: int,
    observed_at: datetime | str,
    scoring_settings: Any,
    resolve_player: Callable[[kw.ProviderPlayerRef], str | None],
    payload_last_modified: str | None = None,
    season_type: str = "regular",
) -> kw.MappedWeeklyBatch:
    """Pure: parse + map + rescore under ``scoring_settings``. Pass the
    offense and IDP payloads concatenated to score both in one batch."""
    rows: Iterable[kw.ProviderRow] = parse_rows(
        payload_or_rows, payload_last_modified=payload_last_modified
    )
    return kw.build_mapped_observations(
        rows,
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
        season_type=season_type,
    )
