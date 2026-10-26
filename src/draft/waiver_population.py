"""Who counts as a free agent for the waiver level — the population, not the level.

LI-5 replacement consolidation, design phase **P2**
(``docs/valuation/LI5_REPLACEMENT_CONSOLIDATION_DESIGN_2026-10-21.md`` §4.4,
owner decisions D1 / D5 / D6, 2026-10-21).  **Wired in phase P3, behind the
default-OFF flag** :data:`FLAG`: the three consumers
(``src.trade.roster_capacity.build_capacity_context``,
``src.draft.context.build_roster_context``,
``src.roster_intel.droppability.team_droppability``) call
:func:`consumer_population` ONLY when :func:`enabled` is true and hand the
result to ``src.draft.displacement``.  With the flag OFF nothing below
:func:`base_free_agent_rows` runs on a served path (that function is the
legacy free-agent selection, folded here so it has one definition), no players
DB or availability context is read, and every payload is byte-identical.

Split of responsibility, so neither half grows a second copy of the other:

* **this module** decides WHO is in the pool, by composing existing owners;
* ``src.league_intel.replacement.waiver_levels`` decides what LEVEL that pool
  has (mean of free-agent ranks 1-3).  Nothing here sorts, bands or averages.

The four steps, each delegated (design §4.4):

1. **rostered** — the caller passes the league-wide rostered key set
   (``src.draft.context.league_rostered_keys``), exactly as every displacement
   function takes it today.
2. **unavailable keys** — per consumer and PRESERVED (D6): capacity passes
   ``()``, Perfect Draft and droppability pass the auction rookies
   (``src.draft.rookie_pool.auction_rookie_keys``).  This module never chooses.
   Steps 1-2 select exactly the rows ``displacement._available_players``
   selects today (``base_rows``; pinned by a parity test).  That selection is
   re-stated here only because the legacy helper returns ``(value, position)``
   tuples and the later steps need the rows; P3 folds the legacy helper onto
   this one so the definition lives in one place.
3. **add-pool eligibility** — ``src.trade.waiver.waiver_candidate_exclusion``
   as-is (position set incl. K/DEF, ``MIN_WAIVER_VALUE``, ``single_source``,
   rookie gate).  ``rookies_eligible`` is resolved once at the request
   boundary and INJECTED, never read from the clock here.
4. **health** — ``src.ros.availability.player_week_states`` for the league's
   OWN current week.  ``available`` and ``uncertain`` stay (uncertain is
   counted); ``unknown`` is excluded; ``unavailable`` is excluded only for the
   injury / designation reasons in :data:`HEALTH_EXCLUDING_REASONS` — a bye
   or an owner override does not remove a replacement candidate (design F4c).

**Unknown stays explicit (D5).**  Health is applied only when the league's
current week is known and placed in its season (:func:`health_applicability`);
otherwise the stamp says ``not_applicable`` and why.  When the players DB is
missing, stale or incomplete the stamp says ``evidence_unavailable`` and the
population stops after step 3 (this reads the design's "legacy population"
row of §4.4 as "no health step": the add-pool gates are an intended
population change under D6 and do not depend on health evidence).  Neither
case treats a player as healthy, available or zero: the served lens is then
:data:`LENS_BANDED_NO_HEALTH`, never lens A's label (design F4).  Inside an applied
health step a player with no metadata is ``unknown`` and excluded — never
assumed available.

Lenses (D1).  ``rows`` is the served population and ``served_lens`` names
it: lens A, *this-season lineup replacement*, when health was applied, else
:data:`LENS_BANDED_NO_HEALTH`.  ``add_pool_rows`` is lens B, *dynasty-asset
opportunity cost*: the same population without the health step.  B is a
named, NON-SERVED shadow lens for the replay; it is never published under
A's label, and A's label is never stamped on a population health did not
filter.

Imports of the trade and ros owners are function-level on purpose:
``src.trade.waiver`` imports ``src.trade.suggestions``, and a module-level
import from the draft layer risks a cycle once displacement imports this
module (design §4.4; pinned by an import-boundary test).

Pure apart from :func:`load_health_evidence`, which reads the persisted
players DB from disk and never touches the network.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

__all__ = [
    "POPULATION_RULE",
    "LENS_THIS_SEASON",
    "LENS_DYNASTY_SHADOW",
    "LENS_BANDED_NO_HEALTH",
    "HEALTH_APPLIED",
    "HEALTH_NOT_APPLICABLE",
    "HEALTH_EVIDENCE_UNAVAILABLE",
    "HEALTH_EXCLUDING_REASONS",
    "HealthEvidence",
    "WaiverPopulation",
    "base_free_agent_rows",
    "health_applicability",
    "load_health_evidence",
    "build_waiver_population",
    "FLAG",
    "RequestInputs",
    "consumer_population",
    "enabled",
    "reset_cache",
    "resolve_request_inputs",
]

POPULATION_RULE = "li5_waiver_tier_v1"

#: The ONE flag that switches the displacement consumers to the LI-5 waiver
#: tier over this population (design §7).  Default OFF and owner-held
#: (``scripts/verify_owner_held_flags.py``).  Banding and health are not two
#: flags: their separate effects are decomposed in the replay
#: (``scripts/li5_replacement_replay.py``), never served in combination.
FLAG = "replacement_level_li5_consolidation"

#: D1 option A — served once P3 lands.
LENS_THIS_SEASON = "this_season_lineup_replacement"
#: D1 option B — a named shadow lens for the replay.  Never served.
LENS_DYNASTY_SHADOW = "dynasty_asset_opportunity_cost_shadow"
#: What is served when the health step could not run (design F4): banded,
#: add-pool eligible, health NOT applied.  Its own label, never lens A's.
LENS_BANDED_NO_HEALTH = "banded_without_health"

HEALTH_APPLIED = "applied"
HEALTH_NOT_APPLICABLE = "not_applicable"
HEALTH_EVIDENCE_UNAVAILABLE = "evidence_unavailable"

#: ``unavailable`` reasons from ``src.ros.availability`` that remove a
#: replacement candidate, enumerated exactly (design F4c): a stated return
#: after this week's game or after the season, and the host's current-week
#: OUT-type designations (the owner's ``_HOST_OUT``: Out, IR, PUP, NA,
#: Suspended, DNR, COVID).  An ALLOWLIST: ``bye`` and ``owner_override`` keep
#: the player, and an unavailable reason the owner adds later (a new host code
#: included) keeps him too until it is reviewed — reported under
#: ``unavailableKept`` rather than silently applied.  A test pins this set
#: against the owner's codes so a new code forces that review.
HEALTH_EXCLUDING_REASONS = frozenset(
    {
        "expected_return_after_game",
        "expected_return_after_season",
        "host_designation_out",
        "host_designation_ir",
        "host_designation_pup",
        "host_designation_na",
        "host_designation_sus",
        "host_designation_dnr",
        "host_designation_cov",
    }
)

_KEY_FIELDS = ("playerId", "legacyRef", "canonicalName", "displayName")


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def base_free_agent_rows(
    contract: Mapping[str, Any] | None,
    rostered_keys: Iterable[str],
    unavailable_keys: Iterable[str] = (),
) -> list[Mapping[str, Any]]:
    """Steps 1-2: every board row nobody can have for free, in board order.

    Selects exactly the rows ``src.draft.displacement._available_players``
    turns into ``(value, position)`` pairs — same pick exclusion, same
    position and positive-value tests, same case-insensitive match on
    ``playerId`` and the three name fields.  The caller's ``unavailable_keys``
    is used as given (D6): ``()`` for capacity, the auction rookies for
    Perfect Draft and droppability.
    """
    if not isinstance(contract, Mapping):
        return []
    rows = contract.get("playersArray")
    if not isinstance(rows, list):
        return []

    taken = {_norm_key(k) for k in rostered_keys if _norm_key(k)}
    taken |= {_norm_key(k) for k in unavailable_keys if _norm_key(k)}

    out: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("assetClass") or "").lower() == "pick":
            continue
        pos = str(row.get("position") or "").strip().upper()
        if not pos or pos == "PICK":
            continue
        value = row.get("rankDerivedValue")
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        keys = {_norm_key(row.get(f)) for f in _KEY_FIELDS}
        keys.discard("")
        if keys & taken:
            continue
        out.append(row)
    return out


@dataclass(frozen=True)
class HealthEvidence:
    """Host player metadata for the health step, or why there is none.

    ``players_meta`` is ``None`` when the evidence is unusable; ``reason``
    then says why.  ``as_of`` is the evidence time when the source exposes
    it, else ``None`` — unknown, never "now".
    """

    players_meta: Mapping[str, Mapping[str, Any]] | None
    as_of: str | None = None
    reason: str | None = None


def load_health_evidence(player_ids: Iterable[str], *, now: float | None = None) -> HealthEvidence:
    """The persisted players DB for ``player_ids``, from disk only.

    Delegates to ``src.ros.game_day_live.persisted_players_meta``, which is
    age-bounded (24 h) and returns ``None`` unless it holds EVERY id asked
    for.  There is deliberately no network fallback (design F5): a request
    must never trigger the multi-MB players fetch.  That owner does not
    return its ``fetchedAt``, so ``as_of`` is ``None`` here.
    """
    from src.ros.game_day_live import persisted_players_meta  # noqa: PLC0415

    ids = {str(p).strip() for p in player_ids if str(p or "").strip()}
    meta = persisted_players_meta(ids, now=now)
    if meta is None:
        return HealthEvidence(None, None, "players_db_missing_stale_or_incomplete")
    return HealthEvidence(meta, None, None)


def health_applicability(ctx: Any, *, as_of: date | None) -> tuple[bool, str | None]:
    """Whether a this-week health filter means anything right now.

    Applies only when the availability context names the LEAGUE's own current
    week (Sleeper ``leg``; no calendar fallback — design F4) and that week is
    one of the season's remaining fantasy weeks.  Two calendar edges are
    checked against the schedule rather than guessed (design F4b):

    * week 1 before the season's first kickoff — ``leg`` can read 1 in the
      off-season, so week 1 needs ``as_of`` and a schedule that places week 1,
      and health starts at the first week-1 kickoff;
    * the final fantasy week after its last game — the season is over and
      ``leg`` is stale.

    Returns ``(applicable, reason_if_not)``.  Every "cannot tell" answer is
    not-applicable: unknown never becomes applicable.
    """
    if ctx is None:
        return False, "no_availability_context"
    current = getattr(ctx, "current_week", None)
    if current is None:
        return False, "no_current_week"
    basis = getattr(ctx, "basis", None) or {}
    if basis.get("currentWeekSource") != "league_leg":
        return False, "current_week_not_from_league"
    weeks = tuple(getattr(ctx, "weeks", ()) or ())
    if current not in weeks:
        return False, "current_week_outside_league_season"

    dates_by_team = getattr(ctx, "team_game_dates", None) or {}
    week_dates = sorted(
        d
        for team_dates in dates_by_team.values()
        for wk, d in (team_dates or {}).items()
        if wk == current and d is not None
    )
    if current == 1:
        if as_of is None or not week_dates:
            return False, "season_start_unverified"
        if as_of < week_dates[0]:
            return False, "before_season_kickoff"
    if current == weeks[-1] and as_of is not None and week_dates and as_of > week_dates[-1]:
        return False, "after_final_fantasy_week"
    return True, None


@dataclass(frozen=True)
class WaiverPopulation:
    """The free-agent population at each step, plus how it was decided.

    ``rows`` — the served population, named by :attr:`served_lens`: lens A
    (steps 1-4) when health was applied, else ``banded_without_health``
    (steps 1-3).
    ``add_pool_rows`` — lens B shadow (no health): steps 1-3.  Not served.
    ``base_rows`` — steps 1-2, the legacy free-agent set.
    """

    base_rows: tuple[Mapping[str, Any], ...]
    add_pool_rows: tuple[Mapping[str, Any], ...]
    rows: tuple[Mapping[str, Any], ...]
    unavailable_keys_count: int
    excluded_by_reason: Mapping[str, int]
    health: Mapping[str, Any]
    health_by_id: Mapping[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def served_lens(self) -> str:
        """Lens A only when the health step actually ran."""
        if self.health.get("state") == HEALTH_APPLIED:
            return LENS_THIS_SEASON
        return LENS_BANDED_NO_HEALTH

    def rows_for_lens(self, lens: str) -> tuple[Mapping[str, Any], ...]:
        """Rows for a named lens.  Asking for lens A when health did not run
        is a ``LookupError`` naming why, never the health-free rows under
        A's label (design F4)."""
        if lens == LENS_DYNASTY_SHADOW:
            return self.add_pool_rows
        if lens in (LENS_THIS_SEASON, LENS_BANDED_NO_HEALTH):
            if lens != self.served_lens:
                raise LookupError(
                    f"lens {lens!r} is not available: health is "
                    f"{self.health.get('state')} ({self.health.get('reason')})"
                )
            return self.rows
        raise ValueError(f"unknown waiver-population lens: {lens!r}")

    def provenance(self) -> dict[str, Any]:
        """The population half of the design's ``replacementPopulation``
        block (§4.6).  The level half (value key, band, positions without a
        level) is added by the P3 consumer that computes the level."""
        return {
            "rule": POPULATION_RULE,
            "lens": self.served_lens,
            "unavailableKeysCount": self.unavailable_keys_count,
            "baseFreeAgents": len(self.base_rows),
            "addPoolEligible": len(self.add_pool_rows),
            "eligibleFreeAgents": len(self.rows),
            "excludedByReason": dict(sorted(self.excluded_by_reason.items())),
            "health": dict(self.health),
        }


def _health_classification(state: str, reason: str) -> str:
    """``keep`` / ``keep_uncertain`` / ``keep_unavailable`` / ``exclude``."""
    from src.ros import availability as av  # noqa: PLC0415

    if state == av.AVAILABLE:
        return "keep"
    if state == av.UNCERTAIN:
        return "keep_uncertain"
    if state == av.UNAVAILABLE:
        if reason in HEALTH_EXCLUDING_REASONS:
            return "exclude"
        return "keep_unavailable"
    # UNKNOWN, or a state the owner adds later: not demonstrably usable.
    return "exclude"


def build_waiver_population(
    contract: Mapping[str, Any] | None,
    rostered_keys: Iterable[str],
    unavailable_keys: Iterable[str] = (),
    *,
    rookies_eligible: bool,
    availability: Any = None,
    health_evidence: HealthEvidence | None = None,
    health_loader: Callable[[Iterable[str]], HealthEvidence] | None = None,
    as_of: date | None = None,
    min_value: int | None = None,
) -> WaiverPopulation:
    """Compose steps 1-4 (module docstring).  No level is computed here.

    ``availability`` is a ``src.ros.availability.AvailabilityContext`` (from
    ``load_context`` at the request boundary).  Health evidence is injected
    either as ``health_evidence`` or, preferably, as ``health_loader`` (e.g.
    :func:`load_health_evidence`), which the builder calls ONCE with the
    add-pool player ids — the only ids the health step reads — so a caller
    never has to re-derive step 3 to know what to ask for.  The loader is
    called only when health applies.  Either way the result is a pure
    function of its arguments.
    """
    from src.ros.availability import player_week_states  # noqa: PLC0415
    from src.trade.waiver import (  # noqa: PLC0415
        MIN_WAIVER_VALUE,
        waiver_candidate_exclusion,
        waiver_positions,
    )

    unavailable = list(unavailable_keys)
    base = base_free_agent_rows(contract, rostered_keys, unavailable)

    positions = waiver_positions(include_kicker_def=True)
    floor = MIN_WAIVER_VALUE if min_value is None else min_value
    excluded: dict[str, int] = {}
    add_pool: list[Mapping[str, Any]] = []
    for row in base:
        reason = waiver_candidate_exclusion(
            dict(row), positions=positions, min_value=floor, rookies_eligible=rookies_eligible
        )
        if reason is None:
            add_pool.append(row)
        else:
            excluded[reason] = excluded.get(reason, 0) + 1

    counts = {"available": 0, "uncertain": 0, "unavailableExcluded": 0, "unknownExcluded": 0}
    applicable, why_not = health_applicability(availability, as_of=as_of)
    health: dict[str, Any]
    by_id: dict[str, tuple[str, str]] = {}

    if applicable and health_evidence is None and health_loader is not None:
        health_evidence = health_loader(
            sorted({str(r.get("playerId")).strip() for r in add_pool if r.get("playerId")})
        )

    if not applicable:
        health = {"state": HEALTH_NOT_APPLICABLE, "reason": why_not, "asOf": None}
        kept = add_pool
    elif health_evidence is None or health_evidence.players_meta is None:
        health = {
            "state": HEALTH_EVIDENCE_UNAVAILABLE,
            "reason": (health_evidence.reason if health_evidence else None) or "no_health_evidence",
            "asOf": health_evidence.as_of if health_evidence else None,
        }
        kept = add_pool
    else:
        week = availability.current_week
        meta_by_id = health_evidence.players_meta
        kept = []
        kept_unavailable: dict[str, int] = {}
        excluded_reasons: dict[str, int] = {}
        for row in add_pool:
            pid = str(row.get("playerId") or "").strip()
            if pid:
                st = player_week_states(pid, meta_by_id.get(pid), availability).get(week)
                state, reason = (st.state, st.reason) if st else ("unknown", "no_week_state")
                by_id[pid] = (state, reason)
            else:
                # No id: nothing can be asked of the owner.  Unknown, excluded.
                state, reason = "unknown", "no_player_id"
            verdict = _health_classification(state, reason)
            if verdict == "exclude":
                bucket = "unknownExcluded" if state != "unavailable" else "unavailableExcluded"
                counts[bucket] += 1
                excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
                continue
            if verdict == "keep_uncertain":
                counts["uncertain"] += 1
            elif verdict == "keep_unavailable":
                kept_unavailable[reason] = kept_unavailable.get(reason, 0) + 1
            else:
                counts["available"] += 1
            kept.append(row)
        health = {
            "state": HEALTH_APPLIED,
            "reason": None,
            "asOf": health_evidence.as_of,
            "evaluationWeek": week,
            **counts,
            "unavailableKept": dict(sorted(kept_unavailable.items())),
            "excludedByHealthReason": dict(sorted(excluded_reasons.items())),
        }

    return WaiverPopulation(
        base_rows=tuple(base),
        add_pool_rows=tuple(add_pool),
        rows=tuple(kept),
        unavailable_keys_count=len({_norm_key(k) for k in unavailable if _norm_key(k)}),
        excluded_by_reason=excluded,
        health=health,
        health_by_id=by_id,
    )


# ── Phase P3: the flag and the request boundary ──────────────────────────


def enabled() -> bool:
    """``True`` only when :data:`FLAG` is explicitly ON.  An unreadable
    registry is OFF — the incumbent anchor — never the candidate."""
    try:
        from src.api.feature_flags import is_enabled  # noqa: PLC0415

        # A literal, not ``FLAG``: the reachability audit reads call sites.
        return bool(is_enabled("replacement_level_li5_consolidation"))
    except Exception:  # noqa: BLE001
        return False


@dataclass(frozen=True)
class RequestInputs:
    """What the population needs from the request boundary, resolved ONCE.

    ``rookies_eligible`` is the add-pool owner's rookie window
    (``src.trade.suggestions._rookies_eligible_today``) read here and injected,
    never re-read inside the builder (design §4.4 step 3).  ``availability`` is
    the league's ``src.ros.availability.AvailabilityContext`` or ``None``;
    ``availability_reason`` then names why (no NFL season in progress, no
    league settings, the cache assembly failed) and the health step is
    ``not_applicable`` — never "everyone is healthy".
    """

    rookies_eligible: bool
    availability: Any
    as_of: date
    availability_reason: str | None = None
    #: Identity of the availability inputs, for the population cache.
    cache_key: tuple = ()


#: Short TTLs: both caches only spare one request's repeated contexts (the
#: N-team engine and the finder build one capacity context per team) the same
#: work; a stale health read must not outlive a refresh by much.
_INPUT_TTL_SECONDS = 120.0
_POPULATION_TTL_SECONDS = 120.0
_CACHE_MAX = 8
_lock = threading.Lock()
_input_cache: OrderedDict[tuple, tuple[float, RequestInputs]] = OrderedDict()
#: key -> (stored at, the contract object it was built from, population).  The
#: contract is held so an entry can only answer for the SAME object (``is``),
#: never for a later contract that reused its ``id()``.
_population_cache: OrderedDict[tuple, tuple[float, Any, WaiverPopulation]] = OrderedDict()


def reset_cache() -> None:
    """Test / replay hook: forget every cached input and population."""
    with _lock:
        _input_cache.clear()
        _population_cache.clear()


def _store(cache: OrderedDict, key: tuple, value: tuple) -> None:
    with _lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > _CACHE_MAX:
            cache.popitem(last=False)


def _digest(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _league_settings(contract: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    sleeper = contract.get("sleeper") if isinstance(contract, Mapping) else None
    settings = sleeper.get("leagueSettings") if isinstance(sleeper, Mapping) else None
    return settings if isinstance(settings, Mapping) else None


def resolve_request_inputs(
    contract: Mapping[str, Any] | None,
    *,
    today: date | None = None,
    rookies_eligible: bool | None = None,
) -> RequestInputs:
    """Resolve the rookie window and the availability context once.

    The availability context is the owner's own request-path assembly
    (``src.ros.availability.load_context``: box caches only, never a network
    call) for the CURRENT NFL season (``src.bdvm.actuals.current_nfl_season``)
    under the contract's own ``sleeper.leagueSettings`` — the same inputs
    ``/api/trade/simulate``'s roster-utility read uses.  Any missing input is
    a named reason and a ``None`` context, so health is ``not_applicable``.

    ``today`` / ``rookies_eligible`` are injectable for the replay and tests.
    """
    as_of = today or datetime.now(timezone.utc).date()
    if rookies_eligible is None:
        from src.trade.suggestions import _rookies_eligible_today  # noqa: PLC0415

        rookies_eligible = bool(_rookies_eligible_today())
    from src.bdvm.actuals import current_nfl_season  # noqa: PLC0415

    season = current_nfl_season(as_of)
    settings = _league_settings(contract)
    if season is None:
        return RequestInputs(rookies_eligible, None, as_of, "no_current_nfl_season", ("none",))
    if settings is None:
        return RequestInputs(rookies_eligible, None, as_of, "no_league_settings", ("none",))
    key = (int(season), _digest(dict(settings)), as_of.isoformat())
    now = time.monotonic()
    with _lock:
        hit = _input_cache.get(key)
    if hit is not None and now - hit[0] <= _INPUT_TTL_SECONDS:
        ctx = hit[1].availability
        reason = hit[1].availability_reason
    else:
        try:
            from src.ros.availability import load_context  # noqa: PLC0415

            ctx = load_context(season=int(season), league_settings=settings)
            reason = None
        except Exception as exc:  # noqa: BLE001 — degraded input, named
            ctx, reason = None, f"availability_context_unavailable:{type(exc).__name__}"
        _store(_input_cache, key, (now, RequestInputs(True, ctx, as_of, reason, key)))
    return RequestInputs(rookies_eligible, ctx, as_of, reason, key)


def _contract_stamp(contract: Mapping[str, Any] | None) -> tuple:
    if not isinstance(contract, Mapping):
        return (0, None, None, 0)
    rows = contract.get("playersArray")
    return (
        id(contract),
        contract.get("generatedAt"),
        contract.get("scrapeTimestamp"),
        len(rows) if isinstance(rows, list) else 0,
    )


def consumer_population(
    contract: Mapping[str, Any] | None,
    rostered_keys: Iterable[str],
    unavailable_keys: Iterable[str] = (),
    *,
    inputs: RequestInputs | None = None,
    health_loader: Callable[[Iterable[str]], HealthEvidence] | None = None,
) -> WaiverPopulation:
    """One consumer's served population, built at its request boundary.

    The consumer passes its OWN rostered and unavailable keys (D6: capacity
    ``()``, Perfect Draft and droppability the auction rookies); this function
    never chooses them.  Health evidence is the disk-only players DB
    (:func:`load_health_evidence`, no network — design F5).  A population is
    cached for :data:`_POPULATION_TTL_SECONDS` per (contract object, key sets,
    request inputs) so several contexts of one request share ONE computation
    (design §8 item 10); an injected ``health_loader`` is never cached.

    Call this only when :func:`enabled` — with the flag OFF no consumer
    reaches it.
    """
    inputs = inputs if inputs is not None else resolve_request_inputs(contract)
    rostered = sorted({_norm_key(k) for k in rostered_keys if _norm_key(k)})
    unavailable = sorted({_norm_key(k) for k in unavailable_keys if _norm_key(k)})
    cacheable = health_loader is None
    key = (
        *_contract_stamp(contract),
        _digest(rostered),
        _digest(unavailable),
        bool(inputs.rookies_eligible),
        inputs.as_of.isoformat(),
        inputs.cache_key,
    )
    now = time.monotonic()
    if cacheable:
        with _lock:
            hit = _population_cache.get(key)
        if hit is not None and hit[1] is contract and now - hit[0] <= _POPULATION_TTL_SECONDS:
            return hit[2]

    population = build_waiver_population(
        contract,
        rostered,
        unavailable,
        rookies_eligible=inputs.rookies_eligible,
        availability=inputs.availability,
        health_loader=health_loader or load_health_evidence,
        as_of=inputs.as_of,
    )
    if inputs.availability is None and inputs.availability_reason:
        # Keep the boundary's specific reason beside the builder's generic one.
        population = WaiverPopulation(
            base_rows=population.base_rows,
            add_pool_rows=population.add_pool_rows,
            rows=population.rows,
            unavailable_keys_count=population.unavailable_keys_count,
            excluded_by_reason=population.excluded_by_reason,
            health={**population.health, "availabilityReason": inputs.availability_reason},
            health_by_id=population.health_by_id,
        )
    if cacheable:
        _store(_population_cache, key, (now, contract, population))
    return population
