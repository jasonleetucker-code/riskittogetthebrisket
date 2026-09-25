"""Shared plumbing for KEYED weekly projection providers (C5-PROJ-C).

:mod:`src.ros.sleeper_weekly_projections` is the first WEEKLY source and
its rows already arrive in Sleeper's stat vocabulary. Keyed commercial
APIs (Fantasy Nerds, SportsDataIO) do not: each needs a credential, an
explicit provider-stat → Sleeper-stat mapping, and an identity join to a
Sleeper player id. This module owns exactly those three concerns once, so
the provider modules stay thin tables and URL builders:

* **credentials** — :func:`read_credential` reads one canonical env var
  into a :class:`SecretCredential` whose ``repr``/``str`` never show the
  value. A missing or blank variable is ``None``, and every fetch then
  answers ``credential_missing`` — never an empty success, never zero
  points. The value is used only inside :func:`fetch_keyed_json`; it is
  never stored on a result, logged, or placed in an exception message
  (:func:`redact` scrubs both the literal value and any credential-shaped
  query parameter before text leaves this module).
* **capability** — :func:`source_capability` is the single gate a
  consumer asks: flag ON **and** credential present **and** the last
  fetch assessed healthy. Missing evidence of health is ``unknown``,
  which is not available.
* **mapping + scoring** — :func:`build_mapped_observations` turns rows a
  provider module has normalized into :class:`ProviderRow` into the SAME
  :class:`~src.ros.sleeper_weekly_projections.WeeklyProjectionObservation`
  shape the Sleeper source emits, rescored under the caller's exact league
  card by :func:`src.league_intel.scorer.score_stat_line`. Provider stats
  with no mapping are REPORTED (``unmapped_provider_fields``), and league
  scoring keys a row does not cover are listed per player as uncovered —
  never scored as zero.

What mapping may and may not do. A projection is an EXPECTATION, so only
**linear** identities of expectations are derived (``pass_inc = pass_att
− pass_cmp``, ``bonus_rec_te = rec`` for a TE, ``idp_tkl = solo + ast``,
``fgmiss = fga − fgm``, ``xpmiss = xpa − xpm``) — the same identities the
realized-points normalizer (:mod:`src.nfl_data.realized_points`) applies
to box scores. Threshold bonuses (``bonus_pass_yd_300``, tackle
milestones, …) are **never** derived from a projected mean: the indicator
of a mean is not the mean of an indicator. They stay uncovered.

Identity is NOT resolved here. A provider row carries the provider's own
player id; the caller injects ``resolve_player`` (the identity owner,
:mod:`src.identity`, or an exact external-id crosswalk it provides). An
unresolved row is refused and listed in ``unresolved_players`` — never
matched by a guess in this module.

**Seasonal intelligence lane only** — the same boundary as the Sleeper
source: no dynasty value, rank or vote is read or written here.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from types import MappingProxyType
from typing import Any

from src.history.keys import player_asset_key
from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.league_intel.scorer import score_stat_line
from src.ros import projection_source_census as census
from src.ros.sleeper_weekly_projections import (
    POSITIONS,
    WeeklyProjectionBatch,
    WeeklyProjectionError,
    WeeklyProjectionObservation,
    _grammar_applies,
    _is_team_defense_key,
    _league_paid_keys,
    _parse_instant,
    _scoring_map,
    _utc_iso,
)
from src.utils.name_clean import normalize_position

__all__ = [
    "HTTP_TIMEOUT_SECONDS",
    "HttpResponse",
    "KeyedFetchResult",
    "LinearDerivation",
    "MappedWeeklyBatch",
    "ProviderPlayerRef",
    "ProviderRow",
    "SecretCredential",
    "SourceCapability",
    "SourceHealth",
    "assess_fetch_health",
    "build_mapped_observations",
    "fetch_keyed_json",
    "instant_or_none",
    "null_fields",
    "numeric_fields",
    "read_credential",
    "redact",
    "source_capability",
    "team_week_game_id",
    "validate_keyed_census_entry",
]

HTTP_TIMEOUT_SECONDS = 20.0
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
_USER_AGENT = "riskit-weekly-projections/1.0"
# Credentials + redaction have ONE owner: ``src/utils/secret_credentials``
# (shared with the SportsDataIO live game-state provider). Re-exported here so
# existing ``kw.read_credential`` / ``kw.redact`` call sites keep working.
from src.utils.secret_credentials import REDACTED as _REDACTED  # noqa: E402
from src.utils.secret_credentials import SecretCredential, read_credential, redact  # noqa: E402,F401

_IDP_FAMILIES: frozenset[str] = frozenset({"DL", "LB", "DB"})


# ── Transport ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HttpResponse:
    body: bytes
    #: Lower-cased response headers (only the provider-freshness ones are
    #: read: ``last-modified``).
    headers: Mapping[str, str] = field(default_factory=dict)


#: ``(url, headers, timeout) -> HttpResponse``. Injected in every test.
HttpGet = Callable[[str, Mapping[str, str], float], HttpResponse]


def _default_http_get(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read(MAX_RESPONSE_BYTES + 1)
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        # HTTPError carries the request URL on ``.url``/``.filename``; raise
        # a fresh error holding only the status so no caller can reach it.
        raise RuntimeError(f"HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URLError: {type(exc.reason).__name__}") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
    return HttpResponse(body=body, headers=resp_headers)


@dataclass(frozen=True)
class KeyedFetchResult:
    """``status``: ``ok`` | ``feature_disabled`` | ``credential_missing`` |
    ``fetch_failed`` | ``bad_payload``. Only ``ok`` carries a payload; a
    refusal is never an empty-but-green result. Holds no credential: the
    ``url`` is the REDACTED request URL."""

    status: str
    census_source_key: str
    feed: str
    season: int
    week: int
    url: str
    observed_at: str | None
    credential_env_var: str
    payload: Any = None
    #: Provider-side freshness of the whole payload (``Last-Modified``), or
    #: ``None``. Fetch time is not data freshness.
    payload_last_modified: str | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _http_date_to_iso(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None or dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def fetch_keyed_json(
    *,
    census_source_key: str,
    feed: str,
    season: int,
    week: int,
    flag_name: str,
    flag_on: bool,
    credential: SecretCredential | None,
    credential_env_var: str,
    build_request: Callable[[str], tuple[str, Mapping[str, str]]],
    http_get: HttpGet | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
    now: Callable[[], datetime] | None = None,
) -> KeyedFetchResult:
    """One keyed GET. Makes NO network call when the flag is off or the
    credential is absent. ``build_request(secret) -> (url, headers)`` is
    the only place the secret is placed on the wire."""
    base = dict(
        census_source_key=census_source_key,
        feed=feed,
        season=int(season),
        week=int(week),
        credential_env_var=credential_env_var,
    )
    # A URL with the key slot shown as <redacted> — safe to keep and log.
    shown_url = redact(build_request(_REDACTED)[0])
    if not flag_on:
        return KeyedFetchResult(
            status="feature_disabled",
            url=shown_url,
            observed_at=None,
            reason=f"feature flag {flag_name!r} is off",
            **base,
        )
    if credential is None:
        return KeyedFetchResult(
            status="credential_missing",
            url=shown_url,
            observed_at=None,
            reason=(
                f"environment variable {credential_env_var} is not set: the source is "
                "UNAVAILABLE (not zero data)"
            ),
            **base,
        )
    getter = http_get or _default_http_get
    clock = now or (lambda: datetime.now(timezone.utc))
    url, headers = build_request(credential.reveal())
    try:
        response = getter(url, headers, timeout)
    except Exception as exc:  # noqa: BLE001 — any transport failure is a refusal
        return KeyedFetchResult(
            status="fetch_failed",
            url=shown_url,
            observed_at=None,
            reason=redact(f"{type(exc).__name__}: {exc}", [credential]),
            **base,
        )
    observed_at = _utc_iso(clock())
    last_modified = _http_date_to_iso((response.headers or {}).get("last-modified"))
    try:
        payload = json.loads(response.body)
    except (TypeError, ValueError) as exc:
        return KeyedFetchResult(
            status="bad_payload",
            url=shown_url,
            observed_at=observed_at,
            reason=redact(f"not JSON: {exc}", [credential]),
            **base,
        )
    return KeyedFetchResult(
        status="ok",
        url=shown_url,
        observed_at=observed_at,
        payload=payload,
        payload_last_modified=last_modified,
        **base,
    )


# ── Health + capability ──────────────────────────────────────────────


@dataclass(frozen=True)
class SourceHealth:
    """The assessed outcome of one fetch + parse. ``healthy`` is ``True``
    only for an ``ok`` fetch that produced at least one observation and
    whose accepted rows all carried at least one mapped stat."""

    census_source_key: str
    healthy: bool
    checked_at: str | None
    reason: str
    observation_count: int = 0


def assess_fetch_health(
    fetch: KeyedFetchResult, batch: MappedWeeklyBatch | None = None
) -> SourceHealth:
    key = fetch.census_source_key
    if not fetch.ok:
        return SourceHealth(key, False, fetch.observed_at, f"fetch_{fetch.status}: {fetch.reason}")
    if batch is None:
        return SourceHealth(key, False, fetch.observed_at, "not_parsed")
    n = len(batch.batch.observations)
    # Schema drift first: it is the more specific diagnosis when a payload
    # parses to nothing because none of its fields are recognised.
    if batch.batch.refused.get("no_mapped_stats"):
        return SourceHealth(
            key,
            False,
            fetch.observed_at,
            "schema_drift: rows with no mapped stat "
            f"({batch.batch.refused['no_mapped_stats']}); unmapped fields "
            f"{sorted(batch.unmapped_provider_fields)[:12]}",
            n,
        )
    if n == 0:
        return SourceHealth(
            key, False, fetch.observed_at, f"no_observations: refused {dict(batch.batch.refused)}"
        )
    return SourceHealth(key, True, fetch.observed_at, "ok", n)


@dataclass(frozen=True)
class SourceCapability:
    census_source_key: str
    available: bool
    flag_on: bool
    credential_present: bool
    #: ``healthy`` | ``unhealthy`` | ``unknown`` (no fetch assessed yet).
    health_state: str
    reasons: tuple[str, ...]


def source_capability(
    *,
    census_source_key: str,
    flag_name: str,
    flag_on: bool,
    credential_env_var: str,
    credential_present: bool,
    last_health: SourceHealth | None,
) -> SourceCapability:
    """Flag ON **and** credential present **and** last fetch healthy.

    An absent credential makes THIS source unavailable and nothing else:
    it is a per-source answer, so the rest of Game Day proceeds without
    it."""
    reasons = []
    if not flag_on:
        reasons.append(f"feature_disabled:{flag_name}")
    if not credential_present:
        reasons.append(f"credential_missing:{credential_env_var}")
    if last_health is None:
        health_state = "unknown"
        reasons.append("health_unknown:no_fetch_assessed")
    elif last_health.census_source_key != census_source_key:
        health_state = "unknown"
        reasons.append("health_unknown:health_record_is_for_another_source")
    elif last_health.healthy:
        health_state = "healthy"
    else:
        health_state = "unhealthy"
        reasons.append(f"unhealthy:{last_health.reason}")
    return SourceCapability(
        census_source_key=census_source_key,
        available=not reasons,
        flag_on=flag_on,
        credential_present=credential_present,
        health_state=health_state,
        reasons=tuple(reasons),
    )


# ── Census ───────────────────────────────────────────────────────────


def validate_keyed_census_entry(key: str, *, horizon: str = "WEEKLY") -> Mapping[str, Any]:
    entry = census.get_source(key)
    if entry is None:
        raise WeeklyProjectionError(
            f"{key!r} is missing from the C5-PROJ-A census; every projection observation "
            "must be traceable to a censused source"
        )
    if entry.get("horizons") != [horizon]:
        raise WeeklyProjectionError(f"{key!r} census horizons {entry.get('horizons')!r}")
    if entry.get("gameType") != "WEEKLY":
        raise WeeklyProjectionError(f"{key!r} census gameType {entry.get('gameType')!r}")
    return entry


# ── Rows, mapping, scoring ───────────────────────────────────────────


@dataclass(frozen=True)
class ProviderPlayerRef:
    """What a provider says about a player — the identity owner's input."""

    provider_player_id: str
    name: str | None
    team: str | None
    position: str | None


@dataclass(frozen=True)
class ProviderRow:
    """One provider row after the provider module's envelope parsing, still
    in the PROVIDER's stat vocabulary."""

    ref: ProviderPlayerRef
    #: Raw position labels (``DE``, ``OLB``, ``FS`` …) — normalized here.
    positions: tuple[str, ...]
    opponent: str | None
    season: int | None
    week: int | None
    #: ``"regular"`` | ``"pre"`` | ``"post"`` | ``None`` (unstated).
    season_type: str | None
    #: Every numeric provider field on the row (``None``s already dropped).
    provider_stats: Mapping[str, float]
    provider_updated_at: str | None = None
    native_points_ppr: float | None = None
    #: A row the provider marks as a team unit (D/ST). Refused.
    is_team_unit: bool = False
    #: Provider fields present on the row with an explicit ``null``: the
    #: provider stated it has NO number. Any league key they map to is
    #: uncovered for this player, whatever other rows published.
    null_provider_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class LinearDerivation:
    """``target = Σ coef·source`` over Sleeper keys, clamped at ≥ 0.
    Applied only when the target is absent and EVERY source is present,
    and only for players at ``positions`` (empty = every position)."""

    target: str
    terms: tuple[tuple[str, float], ...]
    positions: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MappedWeeklyBatch:
    """The shared :class:`WeeklyProjectionBatch` plus what a keyed,
    remapped provider can additionally get wrong."""

    batch: WeeklyProjectionBatch
    #: ``{provider field: rows carrying it}`` — numeric provider stats no
    #: mapping consumed. Reported, never scored.
    unmapped_provider_fields: Mapping[str, int]
    #: Rows refused because ``resolve_player`` returned no Sleeper id.
    unresolved_players: tuple[ProviderPlayerRef, ...]
    #: Version string of the provider's mapping table (pinned provenance).
    stat_mapping_version: str


def team_week_game_id(season: int, week: int, team: str) -> str:
    """Provider-neutral game key: one NFL team plays at most one game per
    week, so kickoffs for every keyed provider are supplied under this key
    to :func:`~src.ros.sleeper_weekly_projections.lock_baseline_at_kickoff`."""
    return f"nflteamweek:{int(season)}:{int(week)}:{str(team).strip().upper()}"


def _mapped_line(
    stats: Mapping[str, float],
    mapping: Mapping[str, tuple[str, ...]],
    idp_only_keys: frozenset[str],
    derivations: Sequence[LinearDerivation],
    positions: frozenset[str],
    field_normalizer: Callable[[str], str],
) -> tuple[dict[str, float], set[str]]:
    by_norm: dict[str, tuple[str, float]] = {}
    for raw_key, value in stats.items():
        by_norm.setdefault(field_normalizer(raw_key), (raw_key, value))
    line: dict[str, float] = {}
    consumed: set[str] = set()
    is_idp = bool(positions & _IDP_FAMILIES)
    for sleeper_key, candidates in mapping.items():
        if sleeper_key in idp_only_keys and not is_idp:
            # Sleeper's IDP rules are not applied to offensive players
            # (same scoping as src.nfl_data.realized_points). Nothing is
            # consumed, so an offensive row's field of that name is
            # reported as unmapped rather than silently absorbed.
            continue
        # Every present candidate spelling is consumed (so none reads as
        # "unmapped"); the first present wins.
        hit = None
        for cand in candidates:
            found = by_norm.get(field_normalizer(cand))
            if found is not None:
                consumed.add(found[0])
                if hit is None:
                    hit = found[1]
        if hit is None:
            continue
        line[sleeper_key] = float(hit)
    for d in derivations:
        if d.target in line:
            continue
        if d.positions and not (positions & d.positions):
            continue
        if not all(src in line for src, _ in d.terms):
            continue
        line[d.target] = max(0.0, sum(coef * line[src] for src, coef in d.terms))
    return line, consumed


def build_mapped_observations(
    rows: Iterable[ProviderRow],
    *,
    census_source_key: str,
    model_company: str,
    stat_mapping: Mapping[str, tuple[str, ...]],
    stat_mapping_version: str,
    ignored_provider_fields: frozenset[str],
    season: int,
    week: int,
    observed_at: datetime | str,
    scoring_settings: Any,
    resolve_player: Callable[[ProviderPlayerRef], str | None],
    idp_only_keys: frozenset[str] = frozenset(),
    derivations: Sequence[LinearDerivation] = (),
    field_normalizer: Callable[[str], str] = lambda k: k,
    season_type: str = "regular",
) -> MappedWeeklyBatch:
    """Pure: no I/O, no clock, no flag read. Rows are refused (and counted
    in ``refused``) for: ``team_unit``, ``missing_player_id``,
    ``season_mismatch`` / ``week_mismatch`` / ``season_type_mismatch``
    (a row that does not STATE its week is ``week_unverifiable`` — never
    assumed to be the requested one), ``unrecognized_position``,
    ``no_team``, ``no_mapped_stats``, ``unresolved_identity``,
    ``duplicate_player_id``."""
    entry = validate_keyed_census_entry(census_source_key)
    scoring = _scoring_map(scoring_settings)
    fingerprint = scoring_fingerprint(scoring)
    if fingerprint is None:
        raise WeeklyProjectionError("scoring card is missing, empty or unusable")
    observed_iso = _parse_instant(observed_at, what="observed_at").isoformat()

    refused: dict[str, int] = {}
    unmapped: dict[str, int] = {}
    unresolved: list[ProviderPlayerRef] = []

    def refuse(reason: str) -> None:
        refused[reason] = refused.get(reason, 0) + 1

    accepted: list[tuple[ProviderRow, str, tuple[str, ...], dict[str, float], frozenset[str]]] = []
    seen: set[str] = set()
    for row in rows:
        if row.is_team_unit:
            refuse("team_unit")
            continue
        if not str(row.ref.provider_player_id or "").strip():
            refuse("missing_player_id")
            continue
        if row.season is None or row.week is None:
            refuse("week_unverifiable")
            continue
        if int(row.season) != int(season):
            refuse("season_mismatch")
            continue
        if int(row.week) != int(week):
            refuse("week_mismatch")
            continue
        if row.season_type is not None and row.season_type != season_type:
            refuse("season_type_mismatch")
            continue
        positions = tuple(
            dict.fromkeys(
                p for p in (normalize_position(x) for x in row.positions) if p in POSITIONS
            )
        )
        if not positions:
            refuse("unrecognized_position")
            continue
        if not str(row.ref.team or "").strip():
            refuse("no_team")
            continue
        line, consumed = _mapped_line(
            row.provider_stats,
            stat_mapping,
            idp_only_keys,
            derivations,
            frozenset(positions),
            field_normalizer,
        )
        ignored_norm = {field_normalizer(f) for f in ignored_provider_fields}
        for raw_key in row.provider_stats:
            if raw_key in consumed or field_normalizer(raw_key) in ignored_norm:
                continue
            unmapped[raw_key] = unmapped.get(raw_key, 0) + 1
        null_norm = {field_normalizer(f) for f in row.null_provider_fields}
        null_keys = frozenset(
            k
            for k, cands in stat_mapping.items()
            if k not in line
            and not (k in idp_only_keys and not (frozenset(positions) & _IDP_FAMILIES))
            and any(field_normalizer(c) in null_norm for c in cands)
        )
        if not line:
            refuse("no_mapped_stats")
            continue
        sleeper_id = resolve_player(row.ref)
        if not sleeper_id:
            refuse("unresolved_identity")
            unresolved.append(row.ref)
            continue
        sleeper_id = str(sleeper_id)
        if sleeper_id in seen:
            refuse("duplicate_player_id")
            continue
        seen.add(sleeper_id)
        accepted.append((row, sleeper_id, positions, line, null_keys))

    vocab: dict[str, set[str]] = {}
    for _row, _sid, positions, line, _nulls in accepted:
        for pos in positions:
            vocab.setdefault(pos, set()).update(line)
    provider_all = frozenset().union(*vocab.values()) if vocab else frozenset()
    league_paid = _league_paid_keys(scoring)

    observations = []
    for row, sleeper_id, positions, line, null_keys in accepted:
        pos_set = frozenset(positions)
        position_vocab: set[str] = set()
        for pos in positions:
            position_vocab |= vocab.get(pos, set())
        uncovered = []
        for key in league_paid:
            if key in line:
                continue
            # The provider projects the key, but only for other positions:
            # its statement that the event is not expected here — unless
            # THIS row carried the field as an explicit null.
            if key in provider_all and key not in position_vocab and key not in null_keys:
                continue
            if not _grammar_applies(key, pos_set) or _is_team_defense_key(key):
                continue
            uncovered.append(key)
        breakdown = score_stat_line(line, scoring)
        team = str(row.ref.team).strip().upper()
        observations.append(
            WeeklyProjectionObservation(
                census_source_key=census_source_key,
                provider_family=str(entry["providerFamily"]),
                model_company=model_company,
                horizon="WEEKLY",
                game_type="WEEKLY",
                sleeper_player_id=sleeper_id,
                player_key=str(player_asset_key(sleeper_id, None, None)),
                position=positions[0],
                fantasy_positions=positions,
                team=team,
                opponent=(str(row.opponent).strip().upper() if row.opponent else None),
                game_id=team_week_game_id(season, week, team),
                season=int(season),
                week=int(week),
                season_type=season_type,
                stat_line=MappingProxyType(dict(sorted(line.items()))),
                league_scored_points=breakdown.total_points,
                scoring_fingerprint=fingerprint,
                scoring_components=tuple(breakdown.components),
                scoring_warnings=tuple(breakdown.warnings),
                uncovered_scoring_keys=tuple(uncovered),
                native_points_ppr=row.native_points_ppr,
                observed_at=observed_iso,
                provider_updated_at=row.provider_updated_at,
            )
        )
    observations.sort(key=lambda o: o.sleeper_player_id)

    batch = WeeklyProjectionBatch(
        season=int(season),
        week=int(week),
        observed_at=observed_iso,
        scoring_fingerprint=fingerprint,
        observations=tuple(observations),
        refused=MappingProxyType(dict(sorted(refused.items()))),
        provider_vocabulary=MappingProxyType(
            {pos: tuple(sorted(keys)) for pos, keys in sorted(vocab.items())}
        ),
    )
    return MappedWeeklyBatch(
        batch=batch,
        unmapped_provider_fields=MappingProxyType(dict(sorted(unmapped.items()))),
        unresolved_players=tuple(unresolved),
        stat_mapping_version=stat_mapping_version,
    )


def null_fields(raw: Mapping[str, Any]) -> frozenset[str]:
    """Fields a provider row carries with an explicit ``null``."""
    return frozenset(str(k) for k, v in raw.items() if v is None)


def numeric_fields(raw: Mapping[str, Any], skip: frozenset[str] = frozenset()) -> dict[str, float]:
    """Numeric fields of a provider row; ``None``/bool/non-numeric dropped
    (absent, never zero)."""
    out: dict[str, float] = {}
    for key, value in raw.items():
        if key in skip or value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[str(key)] = float(value)
            continue
        if isinstance(value, str):
            try:
                out[str(key)] = float(value)
            except ValueError:
                continue
    return out


def instant_or_none(raw: Any) -> str | None:
    """A provider timestamp as UTC ISO-8601, or ``None`` when absent,
    unparseable or naive (a naive stamp's zone is unknown — never guessed)."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()
