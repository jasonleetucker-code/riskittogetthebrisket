"""FPTrack weekly projections — a WEEKLY stat-line source (offense + IDP).

FPTrack (fptrack.com) serves its "Weekly Projection Rankings" page from a
public JSON catalog (:data:`ENDPOINT`): one object per player with a
projected stat line (passing / rushing / receiving / kicking / individual
defense), the opponent, and FPTrack's own ids.  Probed 2026-10-29 (census
record ``docs/projections/WEEKLY_IDP_SOURCE_CENSUS_2026-10-29.md``): 1,105
players for week 8 — 231 DL, 170 LB, 248 DB with stat lines — and an EMPTY
player list for an unpublished week (``week=9`` the same day).  robots.txt
allows ``/`` for ``*``; access is owner-attested (2026-10-29).

What this module owns, and nothing more
---------------------------------------
* acquisition, behind the ``fptrack_weekly_projections`` flag (default OFF);
* the explicit provider-field → Sleeper-stat mapping (:data:`STAT_MAPPING`),
  handed to the shared keyed-lane machinery
  (:func:`src.ros.keyed_weekly_projections.build_mapped_observations`) which
  rescores every line under the CALLER's exact league card;
* an identity resolver over the canonical Sleeper directory index
  (:func:`exact_identity_resolver`) that accepts only an EXACT-rung answer
  corroborated by the player's team — anything else is refused and listed,
  never matched by a guess.

Independence — this is NOT a second vote beside RotoWire
--------------------------------------------------------
Measured on the same morning's captures (583 IDP players joined on name +
team): FPTrack's ``tackles`` tracks RotoWire-via-Sleeper's ``idp_tkl_solo``
with a median difference of 0.04 and 41% identical after rounding to one
decimal; ``assists`` tracks ``idp_tkl_ast`` the same way.  That is shared
data lineage, not two opinions, so the census declares ``rotowire`` as a
constituent family (``modelAncestry.constituentFamilies``) and
:mod:`src.ros.weekly_league_projections` never lets this source vote beside
the Sleeper source.  It is a COVERAGE filler: it prices players RotoWire did
not project, as a single-family passthrough.

Placeholders are not zeros
--------------------------
* ``tacklesForLoss`` was ``0`` on EVERY one of 649 IDP rows.  A field that is
  exactly zero across a whole stat scope of a payload is a placeholder, not a
  projection: :func:`parse_rows` moves it to the row's explicit-null set, so
  the league key it maps to (``idp_tkl_loss``) is reported UNCOVERED for
  every such player instead of scored as 0 (:data:`ZERO_PLACEHOLDER_MIN_ROWS`).
* ``fumbleRecoveries`` / ``safeties`` are ``null`` on IDP rows; nulls stay
  uncovered by the shared machinery.

Semantics of the two tackle fields: ``tackles`` is SOLO (mapped to
``idp_tkl_solo``), ``assists`` is assisted (``idp_tkl_ast``); ``idp_tkl`` is
the linear identity solo + ast.  Evidence: the RotoWire comparison above
(FPTrack ``tackles`` 1.52 mean vs RotoWire solo 1.39 and combined 2.37).

Provider freshness: the payload's ``asOf`` was the epoch placeholder
``1970-01-01T00:00:00.000Z`` and ``generatedAt`` is the response's render
time, so neither is a provider update stamp — ``provider_updated_at`` is
``None`` (fetch time is not data freshness).

**Seasonal intelligence lane only.** Nothing here reads or writes any dynasty
value, rank or vote.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.api.feature_flags import is_enabled
from src.ros import keyed_weekly_projections as kw
from src.ros.sleeper_weekly_projections import WeeklyProjectionError, _utc_iso

__all__ = [
    "CENSUS_SOURCE_KEY",
    "ENDPOINT",
    "FEATURE_FLAG",
    "MODEL_COMPANY",
    "STAT_MAPPING",
    "STAT_MAPPING_VERSION",
    "ZERO_PLACEHOLDER_MIN_ROWS",
    "FPTrackFetchResult",
    "ParsedPayload",
    "build_weekly_observations",
    "exact_identity_resolver",
    "fetch_weekly_projection_payload",
    "parse_rows",
    "projection_url",
]

CENSUS_SOURCE_KEY = "fptrackWeeklyProjections"
FEATURE_FLAG = "fptrack_weekly_projections"
MODEL_COMPANY = "fptrack"
ENDPOINT = "https://fptrack.com/api/sports-v2/projections/football/week"
#: The catalog's own schema version parameter, as the page requests it.
CATALOG_VERSION = 5
HTTP_TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
#: Identifies the repo's weekly-projection collectors, as the Sleeper source does.
_USER_AGENT = "Mozilla/5.0 (compatible; riskit-weekly-projections/1.0)"

STAT_MAPPING_VERSION = "fptrack-v5-week/2026-10-29"

#: Sleeper stat key -> FPTrack field (first present wins).
STAT_MAPPING: Mapping[str, tuple[str, ...]] = {
    # passing
    "pass_att": ("passAttempts",),
    "pass_cmp": ("passCompletions",),
    "pass_yd": ("passYards",),
    "pass_td": ("passTouchdowns",),
    "pass_int": ("interceptions",),
    # rushing / receiving
    "rush_att": ("carries",),
    "rush_yd": ("rushYards",),
    "rush_td": ("rushTouchdowns",),
    "rec_tgt": ("targets",),
    "rec": ("receptions",),
    "rec_yd": ("receivingYards",),
    "rec_td": ("receivingTouchdowns",),
    "fum_lost": ("fumblesLost",),
    # kicking
    "fgm": ("fieldGoalsMade",),
    "fga": ("fieldGoalsAttempted",),
    "xpm": ("extraPointsMade",),
    "xpa": ("extraPointsAttempted",),
    # individual defense (IDP positions only — IDP_ONLY_KEYS)
    "idp_tkl_solo": ("tackles",),
    "idp_tkl_ast": ("assists",),
    "idp_tkl_loss": ("tacklesForLoss",),
    "idp_pass_def": ("passesDefended",),
    "idp_sack": ("sacks",),
    "idp_int": ("defInterceptions",),
    "idp_ff": ("forcedFumbles",),
    "idp_fum_rec": ("fumbleRecoveries",),
    "idp_safe": ("safeties",),
    # ``defensiveTouchdowns`` when published, else the sum of the two TD
    # splits (``_DERIVED_DEF_TD`` — a linear identity of expectations).
    "idp_def_td": ("defensiveTouchdowns", "_derivedDefensiveTouchdowns"),
}

IDP_ONLY_KEYS: frozenset[str] = frozenset(k for k in STAT_MAPPING if k.startswith("idp_"))

DERIVATIONS: tuple[kw.LinearDerivation, ...] = (
    kw.LinearDerivation("pass_inc", (("pass_att", 1.0), ("pass_cmp", -1.0))),
    kw.LinearDerivation("bonus_rec_te", (("rec", 1.0),), frozenset({"TE"})),
    kw.LinearDerivation("fgmiss", (("fga", 1.0), ("fgm", -1.0))),
    kw.LinearDerivation("xpmiss", (("xpa", 1.0), ("xpm", -1.0))),
    kw.LinearDerivation("idp_tkl", (("idp_tkl_solo", 1.0), ("idp_tkl_ast", 1.0))),
)

_DERIVED_DEF_TD = "_derivedDefensiveTouchdowns"
_DEF_TD_SPLITS = ("interceptionTouchdowns", "fumbleRecoveryTouchdowns")

#: Numeric fields that are not scoreable counts, or that are consumed through
#: a derived field.  Everything numeric outside this and STAT_MAPPING is
#: reported as unmapped.
IGNORED_PROVIDER_FIELDS: frozenset[str] = frozenset(
    {
        # team-defense (D/ST) totals; D/ST rows are refused anyway
        "pointsAllowed",
        "yardsAllowed",
        # summed into _derivedDefensiveTouchdowns -> idp_def_td
        "interceptionTouchdowns",
        "fumbleRecoveryTouchdowns",
    }
)

#: A field exactly 0.0 on every row of a stat scope is treated as an
#: unpublished placeholder — but only over a population large enough that
#: "everyone is projected for exactly zero" is not plausible.
ZERO_PLACEHOLDER_MIN_ROWS = 25


# ── Acquisition ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class FPTrackFetchResult:
    """``status`` is ``ok`` | ``feature_disabled`` | ``fetch_failed`` |
    ``bad_payload``.  Only ``ok`` carries a payload."""

    status: str
    season: int
    week: int
    url: str
    observed_at: str | None
    payload: Mapping[str, Any] | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def projection_url(week: int) -> str:
    return ENDPOINT + "?" + urllib.parse.urlencode({"v": CATALOG_VERSION, "week": int(week)})


def _default_http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        body = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
    return body


def fetch_weekly_projection_payload(
    season: int,
    week: int,
    *,
    http_get: Callable[[str, float], bytes] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
    now: Callable[[], datetime] | None = None,
) -> FPTrackFetchResult:
    """One GET.  Makes NO network call while the flag is off.

    The catalog serves the provider's CURRENT season; ``season`` is checked
    against the payload's own ``season`` at parse time, never assumed."""
    url = projection_url(week)
    # Literal flag name: the reachability audit reads literals only.
    if not is_enabled("fptrack_weekly_projections"):
        return FPTrackFetchResult(
            "feature_disabled",
            int(season),
            int(week),
            url,
            None,
            reason=f"feature flag {FEATURE_FLAG!r} is off",
        )
    getter = http_get or _default_http_get
    clock = now or (lambda: datetime.now(timezone.utc))
    try:
        body = getter(url, timeout)
    except Exception as exc:  # noqa: BLE001 — any transport failure is a refusal
        return FPTrackFetchResult(
            "fetch_failed", int(season), int(week), url, None, reason=f"{type(exc).__name__}: {exc}"
        )
    observed_at = _utc_iso(clock())
    try:
        payload = json.loads(body)
    except (TypeError, ValueError) as exc:
        return FPTrackFetchResult(
            "bad_payload", int(season), int(week), url, observed_at, reason=f"not JSON: {exc}"
        )
    if not isinstance(payload, Mapping) or not isinstance(payload.get("players"), list):
        return FPTrackFetchResult(
            "bad_payload",
            int(season),
            int(week),
            url,
            observed_at,
            reason="expected an object with a 'players' list",
        )
    return FPTrackFetchResult("ok", int(season), int(week), url, observed_at, payload=payload)


# ── Parse ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedPayload:
    rows: tuple[kw.ProviderRow, ...]
    #: ``{statScope: sorted fields}`` treated as unpublished placeholders.
    placeholder_zero_fields: Mapping[str, tuple[str, ...]]
    season: int | None
    week: int | None
    phase: str | None


def _int_or_none(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _placeholder_fields(
    players: Iterable[Mapping[str, Any]], min_rows: int
) -> dict[str, frozenset[str]]:
    """``{statScope: fields that are exactly 0 on every row that has them}``."""
    seen: dict[str, dict[str, list[float]]] = {}
    for p in players:
        stats = p.get("stats")
        if not isinstance(stats, Mapping):
            continue
        scope = str(p.get("statScope") or "")
        for key, value in stats.items():
            if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            seen.setdefault(scope, {}).setdefault(str(key), []).append(float(value))
    out: dict[str, frozenset[str]] = {}
    for scope, fields in seen.items():
        zeros = frozenset(
            k for k, vals in fields.items() if len(vals) >= min_rows and all(v == 0.0 for v in vals)
        )
        if zeros:
            out[scope] = zeros
    return out


def parse_rows(
    payload: Mapping[str, Any], *, zero_placeholder_min_rows: int | None = None
) -> ParsedPayload:
    """The catalog envelope -> provider rows (still in FPTrack's vocabulary).

    Season / week / phase come from the payload's own top-level fields; a
    payload that does not state them yields rows the shared mapper refuses
    as ``week_unverifiable`` — never assumed to be the requested week."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("players"), list):
        raise WeeklyProjectionError("FPTrack payload: expected an object with a 'players' list")
    players = [p for p in payload["players"] if isinstance(p, Mapping)]
    season = _int_or_none(payload.get("season"))
    week = _int_or_none(payload.get("week"))
    phase = str(payload.get("phase")) if payload.get("phase") else None
    season_type = "regular" if phase == "regular" else (phase or None)
    min_rows = (
        ZERO_PLACEHOLDER_MIN_ROWS
        if zero_placeholder_min_rows is None
        else zero_placeholder_min_rows
    )
    placeholders = _placeholder_fields(players, min_rows)

    rows = []
    for p in players:
        stats_raw = p.get("stats") if isinstance(p.get("stats"), Mapping) else {}
        scope = str(p.get("statScope") or "")
        zero_fields = placeholders.get(scope, frozenset())
        stats = {k: v for k, v in stats_raw.items() if k not in zero_fields}
        splits = [stats.get(k) for k in _DEF_TD_SPLITS]
        if stats.get("defensiveTouchdowns") is None and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in splits
        ):
            stats[_DERIVED_DEF_TD] = float(sum(splits))
        position = str(p.get("position") or "")
        rows.append(
            kw.ProviderRow(
                ref=kw.ProviderPlayerRef(
                    provider_player_id=str(p.get("fptrackId") or p.get("entityId") or "").strip(),
                    name=(str(p["fullName"]) if p.get("fullName") else None),
                    team=(str(p["team"]) if p.get("team") else None),
                    position=position or None,
                ),
                positions=tuple(x for x in (p.get("positions") or [position]) if x),
                opponent=(str(p["opponent"]) if p.get("opponent") else None),
                season=season,
                week=week,
                season_type=season_type,
                provider_stats=kw.numeric_fields(stats),
                null_provider_fields=kw.null_fields(stats) | zero_fields,
                provider_updated_at=None,
                native_points_ppr=None,
                # A team defense row (position DEF) is a D/ST unit.
                is_team_unit=position.upper() in {"DEF", "DST", "D/ST"},
            )
        )
    return ParsedPayload(
        rows=tuple(rows),
        placeholder_zero_fields={s: tuple(sorted(f)) for s, f in sorted(placeholders.items())},
        season=season,
        week=week,
        phase=phase,
    )


# ── Identity ─────────────────────────────────────────────────────────


def exact_identity_resolver(index: Any) -> Callable[[kw.ProviderPlayerRef], str | None]:
    """A resolver over a :class:`src.identity.resolution.SleeperDirectoryIndex`.

    Accepts only an EXACT-rung CANONICAL_V2 answer (``Resolution.is_exact``,
    never a tie, never fuzzy) whose directory team equals the provider's
    team.  Anything else is ``None`` — refused and listed by the mapper."""
    from src.identity.resolution import resolve_canonical_v2  # noqa: PLC0415

    def resolve(ref: kw.ProviderPlayerRef) -> str | None:
        if index is None or not ref.name:
            return None
        res = resolve_canonical_v2(index, name=ref.name, position=ref.position, team=ref.team)
        if not res.is_exact:
            return None
        if not ref.team or str(res.team or "").upper() != str(ref.team).upper():
            return None
        return res.sleeper_id

    return resolve


# ── Build ────────────────────────────────────────────────────────────


def build_weekly_observations(
    payload: Mapping[str, Any],
    *,
    season: int,
    week: int,
    observed_at: datetime | str,
    scoring_settings: Any,
    resolve_player: Callable[[kw.ProviderPlayerRef], str | None],
    season_type: str = "regular",
    zero_placeholder_min_rows: int | None = None,
) -> tuple[kw.MappedWeeklyBatch, ParsedPayload]:
    """Pure: parse + map + rescore under ``scoring_settings``.

    Identity collisions are refused on BOTH sides: when two FPTrack rows
    resolve to one Sleeper id, neither is trusted (the shared mapper alone
    would keep the first and refuse only the second)."""
    parsed = parse_rows(payload, zero_placeholder_min_rows=zero_placeholder_min_rows)
    claims: dict[str, int] = {}
    resolved: dict[int, str | None] = {}
    for row in parsed.rows:
        if row.is_team_unit:
            continue
        sid = resolve_player(row.ref)
        resolved[id(row.ref)] = sid
        if sid:
            claims[str(sid)] = claims.get(str(sid), 0) + 1
    collided = {sid for sid, n in claims.items() if n > 1}

    def resolve_once(ref: kw.ProviderPlayerRef) -> str | None:
        sid = resolved[id(ref)] if id(ref) in resolved else resolve_player(ref)
        return None if sid is None or str(sid) in collided else sid

    batch = kw.build_mapped_observations(
        parsed.rows,
        census_source_key=CENSUS_SOURCE_KEY,
        model_company=MODEL_COMPANY,
        stat_mapping=STAT_MAPPING,
        stat_mapping_version=STAT_MAPPING_VERSION,
        ignored_provider_fields=IGNORED_PROVIDER_FIELDS,
        season=season,
        week=week,
        observed_at=observed_at,
        scoring_settings=scoring_settings,
        resolve_player=resolve_once,
        idp_only_keys=IDP_ONLY_KEYS,
        derivations=DERIVATIONS,
        season_type=season_type,
    )
    return batch, parsed
