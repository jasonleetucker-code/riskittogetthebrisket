"""Game Day per-player weekly baselines — which projection each player uses, and why.

One question, one owner: for this league-week, what is each rostered
player's PROVIDER weekly baseline (the pregame number our rest-of-game
forecast is scaled from), where did it come from, and what does it not
cover?  :mod:`src.ros.game_day_week` consumes the answer; it never picks a
source itself.

Bases, never blended across horizons
------------------------------------
* ``weekly:<source>`` — a WEEKLY-horizon provider projection, rescored under
  THIS league's card by the exact scorer and LOCKED at the player's kickoff:
  the last observation fetched at or before kickoff.  An in-game provider
  update can never drift the baseline; a player first seen after kickoff has
  no weekly baseline.  Today exactly one weekly source is wired —
  ``sleeperWeeklyProjections`` (RotoWire via Sleeper,
  :mod:`src.ros.sleeper_weekly_projections`; flag
  ``sleeper_weekly_projections``, default OFF in code; access is
  owner-attested per its census entry).
* ``weekly:ensemble`` — reserved for a player priced by MORE THAN ONE
  independent weekly provider family (see below).
* ``preseason_full_season_fallback`` — the per-game average from the
  full-season ROS ensemble (``PRESEASON_FULL_SEASON`` horizon).  Used only
  when no locked weekly baseline exists.  It is a FALLBACK and NOT a
  current-week forecast; :data:`BASIS_LABELS` carries that wording so no
  consumer can present it as the weekly projection.

More weekly sources, without double counting
--------------------------------------------
:data:`WEEKLY_SOURCE_ADAPTERS` is the seam: one adapter per census source
key, each turning that source's fetches into kickoff-locked per-player
:class:`WeeklyBaseline` values.  Independence is decided by the census
``providerFamily``, never by the source key: two sources of the SAME family
(e.g. a separately ingested RotoWire product beside RotoWire-via-Sleeper)
give ONE vote — the first adapter in registry order — and the rest are
counted in ``sameFamilyDuplicates``.  When two or more families price a
player, the combination is delegated to the canonical ensemble owner
(:func:`src.ros.projection_ensemble.combine_ensemble`, ``equal_family_mean``);
this module does not own a second combination rule.  Keyed APIs (Fantasy
Nerds, SportsDataIO, FantasyPros, DraftSharks) plug in here once their
adapters and owner-configured credentials exist; none is implemented.

Join keys
---------
Weekly rows carry Sleeper ``player_id`` and join on it.  The preseason
ensemble is keyed by normalized NAME (that is the key the projection lane
chose), so the fallback resolves name -> Sleeper id through the full
Sleeper player map and REFUSES a name two Sleeper players share rather than
guessing which one it meant (``ambiguous_name_player_ids``).

Scoring coverage
----------------
``uncovered_keys`` are league-paid categories the provider does not project
for the player's position: their contribution is UNKNOWN, never zero, and is
published.  The one exception we fill is the first-down bonus
(``bonus_fd_<pos>``): no projection publishes first downs, and the canonical
measured fit (:mod:`src.nfl_data.first_down_rate`) is reused to impute it.
That component is OURS, carried separately as ``imputed_points`` /
``imputed_keys``, never folded silently into the provider's number.

Missing is never zero: a player with no basis has no estimate at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.nfl_data.first_down_rate import (
    SLEEPER_PROJECTED_FD_KEYS,
    imputed_sleeper_first_down_bonus,
)
from src.utils.name_clean import normalize_player_name

SLEEPER_WEEKLY_SOURCE_KEY = "sleeperWeeklyProjections"
BASIS_WEEKLY = "weekly:rotowire_via_sleeper"
BASIS_WEEKLY_ENSEMBLE = "weekly:ensemble"
BASIS_PRESEASON = "preseason_full_season_fallback"
#: Factual source label for the one wired weekly source.
WEEKLY_SOURCE_LABEL = "RotoWire via Sleeper"
#: Human-facing wording per basis, published in lineage beside every count.
BASIS_LABELS: dict[str, str] = {
    BASIS_WEEKLY: f"Weekly projection — {WEEKLY_SOURCE_LABEL}, locked at kickoff",
    BASIS_WEEKLY_ENSEMBLE: (
        "Weekly projection — equal-family mean of independent weekly providers, "
        "each locked at kickoff"
    ),
    BASIS_PRESEASON: (
        "Preseason full-season per-game average — FALLBACK, NOT a current-week forecast"
    ),
}

#: ``weekly_state`` vocabulary.
WEEKLY_OK = "ok"
WEEKLY_FEATURE_DISABLED = "feature_disabled"
WEEKLY_NOT_REQUESTED = "not_requested"
WEEKLY_NO_USABLE_FETCH = "no_usable_fetch"
WEEKLY_SCORING_UNUSABLE = "scoring_unusable"


@dataclass(frozen=True)
class WeeklyBaseline:
    """One source's kickoff-locked baseline for one player."""

    player_id: str
    source_key: str
    provider_family: str
    basis: str
    position: str
    season: int
    #: Provider line under the league card + our imputed component.
    points: float
    provider_points: float
    imputed_points: float = 0.0
    imputed_keys: tuple[str, ...] = ()
    uncovered_keys: tuple[str, ...] = ()
    provider_as_of: str | None = None
    observed_at: str | None = None
    locked: bool | None = None


@dataclass(frozen=True)
class PlayerEstimate:
    """One player's pregame weekly baseline, with its provenance."""

    player_id: str
    #: The baseline the resolver scales: provider points + our imputed part.
    points: float
    basis: str
    #: Weekly: the provider line(s) under the league card, WITHOUT our
    #: imputation.  Preseason: the ensemble's per-game figure.
    provider_points: float
    #: Our first-down imputation (0.0 when none fired).
    imputed_points: float = 0.0
    imputed_keys: tuple[str, ...] = ()
    uncovered_keys: tuple[str, ...] = ()
    #: Provider's own last-changed stamp (weekly), when it stated one.
    provider_as_of: str | None = None
    #: When WE fetched the observation used as the baseline (weekly).
    observed_at: str | None = None
    #: True once kickoff has passed (the baseline can no longer change).
    kickoff_locked: bool | None = None
    join_key: str = "sleeper_player_id"
    #: Weekly provider families behind the number (one vote each).
    families: tuple[str, ...] = ()


@dataclass(frozen=True)
class GameDayEstimates:
    by_player_id: dict[str, PlayerEstimate]
    weekly_state: str
    weekly_reason: str | None
    preseason_source: str | None
    sources_loaded: tuple[str, ...] = ()
    sources_unavailable: tuple[str, ...] = ()
    #: Players whose preseason name join was refused as ambiguous.
    ambiguous_name_player_ids: tuple[str, ...] = ()
    #: Counts from the kickoff lock (summed over weekly sources), for lineage.
    weekly_counts: dict[str, int] = field(default_factory=dict)
    #: Newest provider stamp / fetch time among the weekly baselines used.
    weekly_as_of: str | None = None
    weekly_observed_at: str | None = None
    #: Per weekly source: state / reason / family / counts.
    weekly_sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def points_by_player_id(self) -> dict[str, float]:
        return {pid: e.points for pid, e in self.by_player_id.items()}

    @property
    def source_label(self) -> str | None:
        """``+``-joined bases actually used, or ``None`` when nothing priced."""
        bases = sorted({e.basis for e in self.by_player_id.values()})
        return "+".join(bases) if bases else None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _normalize_team(code: Any) -> str:
    from src.playerctx.normalize import normalize_team_code

    team = normalize_team_code(str(code or ""))
    return "LAR" if team == "LA" else team


def _rate(scoring_settings: Mapping[str, Any], key: str) -> float:
    """The league's rate for ``key``.  A key ABSENT from the scoring card is
    worth zero points — that is the host's own rule (absent and explicit
    zero score identically), not a missing measurement."""
    value = (scoring_settings or {}).get(key)
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _census(source_key: str) -> Mapping[str, Any]:
    from src.ros import projection_source_census as census

    return census.get_source(source_key) or {}


def _preseason_by_id(
    player_ids: Iterable[str],
    players_meta: Mapping[str, Any],
    preseason_by_name: Mapping[str, float],
) -> tuple[dict[str, float], tuple[str, ...]]:
    """Name-keyed ensemble -> Sleeper id, refusing names two players share.

    "Share" means two Sleeper players currently on NFL teams (or rostered
    here) normalize to the same name: the ensemble cannot say which one its
    number describes, so neither gets it.
    """
    from src.ros.game_day_capture import _display_name

    wanted = {str(pid) for pid in player_ids}
    names: dict[str, str] = {}
    for pid in wanted:
        key = normalize_player_name(_display_name(players_meta.get(pid), pid))
        if key:
            names[pid] = key
    wanted_names = set(names.values())
    holders: dict[str, int] = {}
    for pid, meta in (players_meta or {}).items():
        # Only players on an NFL team can be the one a CURRENT projection
        # means; counting retired namesakes would refuse half the league.
        # A rostered player we were asked about always counts.
        if not isinstance(meta, Mapping) or not (meta.get("team") or str(pid) in wanted):
            continue
        key = normalize_player_name(_display_name(meta, str(pid)))
        if key in wanted_names:
            holders[key] = holders.get(key, 0) + 1
    out: dict[str, float] = {}
    ambiguous: list[str] = []
    for pid, key in names.items():
        value = preseason_by_name.get(key)
        if value is None:
            continue
        if holders.get(key, 0) > 1:
            ambiguous.append(pid)
            continue
        out[pid] = float(value)
    return out, tuple(sorted(ambiguous))


#: Public name for the same join, for callers outside Game Day that price
#: rostered players from the name-keyed ensemble (the trade path's #1173
#: roster utility).  One join, one ambiguity rule.
preseason_by_id = _preseason_by_id


# ── Weekly source adapters ──────────────────────────────────────────────

WeeklyAdapter = Callable[..., tuple[dict[str, WeeklyBaseline], dict[str, int], str | None]]


def _sleeper_weekly_adapter(
    fetches: Sequence[Any],
    *,
    season: int,
    week: int,
    scoring_settings: Mapping[str, Any],
    kickoffs_by_team: Mapping[str, float],
    now: float,
    provider_family: str,
) -> tuple[dict[str, WeeklyBaseline], dict[str, int], str | None]:
    """RotoWire via Sleeper: ``(player_id -> baseline, counts, refusal)``."""
    from src.ros.sleeper_weekly_projections import (
        WeeklyProjectionError,
        build_weekly_observations,
        lock_baseline_at_kickoff,
    )

    observations = []
    for fetch in fetches:
        if getattr(fetch, "status", None) != "ok" or not getattr(fetch, "observed_at", None):
            continue
        try:
            batch = build_weekly_observations(
                fetch.rows,
                season=season,
                week=week,
                observed_at=fetch.observed_at,
                scoring_settings=scoring_settings,
            )
        except WeeklyProjectionError as exc:
            return {}, {}, f"{WEEKLY_SCORING_UNUSABLE}: {exc}"
        observations.extend(batch.observations)
    kickoffs: dict[str, str] = {}
    for obs in observations:
        stamp = kickoffs_by_team.get(_normalize_team(obs.team)) if obs.team else None
        if stamp is not None:
            kickoffs.setdefault(obs.game_id, _iso(stamp))
    lock = lock_baseline_at_kickoff(observations, kickoffs, now=_iso(now))
    counts = {
        "observations": len(observations),
        "baselines": len(lock.baselines),
        "noPreKickoffObservation": len(lock.no_pre_kickoff_observation),
        "unknownKickoff": len(lock.unknown_kickoff),
        "postKickoffObservationsIgnored": lock.post_kickoff_observations_ignored,
    }
    paid_fd_keys = [k for k in SLEEPER_PROJECTED_FD_KEYS if _rate(scoring_settings, k) != 0.0]
    out: dict[str, WeeklyBaseline] = {}
    refused_fd = 0
    for pid, entry in lock.baselines.items():
        obs = entry.observation
        if paid_fd_keys and any(k in obs.stat_line for k in paid_fd_keys):
            # The provider's *_fd keys are yardage/10, not first downs
            # (see first_down_rate.SLEEPER_PROJECTED_FD_KEYS); a card that
            # pays them would price that proxy.  Refused, not scored.
            refused_fd += 1
            continue
        imputed = imputed_sleeper_first_down_bonus(obs.stat_line, obs.position, scoring_settings)
        imputed_points = imputed[2] if imputed else 0.0
        imputed_keys = (imputed[0],) if imputed else ()
        out[pid] = WeeklyBaseline(
            player_id=pid,
            source_key=SLEEPER_WEEKLY_SOURCE_KEY,
            provider_family=provider_family,
            basis=BASIS_WEEKLY,
            position=obs.position,
            season=obs.season,
            points=obs.league_scored_points + imputed_points,
            provider_points=obs.league_scored_points,
            imputed_points=imputed_points,
            imputed_keys=imputed_keys,
            uncovered_keys=tuple(k for k in obs.uncovered_scoring_keys if k not in imputed_keys),
            provider_as_of=obs.provider_updated_at,
            observed_at=obs.observed_at,
            locked=entry.locked,
        )
    if refused_fd:
        counts["refusedProviderFirstDownKeys"] = refused_fd
    return out, counts, None


#: Census source key -> adapter, in PRECEDENCE order (first of a family wins
#: that family's single vote).  Add a keyed provider here with its adapter.
WEEKLY_SOURCE_ADAPTERS: dict[str, WeeklyAdapter] = {
    SLEEPER_WEEKLY_SOURCE_KEY: _sleeper_weekly_adapter,
}


def _combine_families(pid: str, votes: Sequence[WeeklyBaseline]) -> PlayerEstimate:
    """One vote per family; two or more families go to the ensemble owner."""
    if len(votes) == 1:
        b = votes[0]
        return PlayerEstimate(
            player_id=pid,
            points=b.points,
            basis=b.basis,
            provider_points=b.provider_points,
            imputed_points=b.imputed_points,
            imputed_keys=b.imputed_keys,
            uncovered_keys=b.uncovered_keys,
            provider_as_of=b.provider_as_of,
            observed_at=b.observed_at,
            kickoff_locked=b.locked,
            families=(b.provider_family,),
        )
    from src.ros.projection_ensemble import combine_ensemble
    from src.ros.projection_observations import ProjectionObservation

    observations = []
    for b in votes:
        entry = _census(b.source_key)
        observations.append(
            ProjectionObservation(
                census_source_key=b.source_key,
                provider_family=b.provider_family,
                evidence_class=str(entry.get("evidenceClass") or "PROJECTION_MODEL"),
                horizon="WEEKLY",
                access_posture=str(entry.get("accessPosture") or ""),
                player_key=f"player:{pid}",
                position=b.position,
                season=b.season,
                # Metadata only here (the combined value does not read it);
                # the provider stamp when stated, else when we fetched.
                as_of=b.provider_as_of or b.observed_at or "",
                games=1.0,
                league_scored_fpg=b.points,
                league_scored_is_native=False,
                native_fpg=None,
                native_is_scoring_native=False,
                stat_line_available=True,
                proj_high=None,
                proj_low=None,
                is_proxy=False,
            )
        )
    combined = combine_ensemble(observations, method="equal_family_mean")
    provider = sum(b.provider_points for b in votes) / len(votes)
    return PlayerEstimate(
        player_id=pid,
        points=combined.combined_league_scored_fpg,
        basis=BASIS_WEEKLY_ENSEMBLE,
        provider_points=provider,
        # equal_family_mean is linear, so our imputed share is the mean too.
        imputed_points=combined.combined_league_scored_fpg - provider,
        imputed_keys=tuple(sorted({k for b in votes for k in b.imputed_keys})),
        uncovered_keys=tuple(sorted({k for b in votes for k in b.uncovered_keys})),
        provider_as_of=max((b.provider_as_of for b in votes if b.provider_as_of), default=None),
        observed_at=max((b.observed_at for b in votes if b.observed_at), default=None),
        kickoff_locked=all(b.locked for b in votes)
        if all(b.locked is not None for b in votes)
        else None,
        families=tuple(sorted(b.provider_family for b in votes)),
    )


def resolve_game_day_estimates(
    *,
    player_ids: Iterable[str],
    players_meta: Mapping[str, Any],
    scoring_settings: Mapping[str, Any],
    season: int,
    week: int,
    now: float,
    preseason_by_name: Mapping[str, float] | None = None,
    preseason_source: str | None = None,
    sources_loaded: Sequence[str] = (),
    sources_unavailable: Sequence[str] = (),
    weekly_fetches: Sequence[Any] | None = None,
    weekly_fetches_by_source: Mapping[str, Sequence[Any]] | None = None,
    weekly_state: str = WEEKLY_NOT_REQUESTED,
    weekly_reason: str | None = None,
    kickoffs_by_team: Mapping[str, float] | None = None,
) -> GameDayEstimates:
    """Per-player baselines for ``player_ids``: locked weekly first, else preseason.

    ``weekly_fetches_by_source`` maps a census source key (one of
    :data:`WEEKLY_SOURCE_ADAPTERS`) to that source's fetch observations,
    possibly several taken at different times — each adapter's lock takes a
    player's last pre-kickoff one.  ``weekly_fetches`` is shorthand for the
    RotoWire-via-Sleeper source.  ``kickoffs_by_team`` maps a normalized NFL
    team code to its game's kickoff (epoch seconds).
    """
    ids = [str(p) for p in player_ids]
    preseason, ambiguous = (
        _preseason_by_id(ids, players_meta, preseason_by_name)
        if preseason_by_name and preseason_source
        else ({}, ())
    )

    by_source: dict[str, Sequence[Any]] = dict(weekly_fetches_by_source or {})
    if weekly_fetches:
        by_source.setdefault(SLEEPER_WEEKLY_SOURCE_KEY, weekly_fetches)

    per_source: dict[str, dict[str, WeeklyBaseline]] = {}
    source_info: dict[str, dict[str, Any]] = {}
    totals: dict[str, int] = {}
    for key, adapter in WEEKLY_SOURCE_ADAPTERS.items():
        fetches = by_source.get(key)
        if not fetches:
            continue
        family = str(_census(key).get("providerFamily") or key)
        baselines, counts, refusal = adapter(
            fetches,
            season=season,
            week=week,
            scoring_settings=scoring_settings,
            kickoffs_by_team=kickoffs_by_team or {},
            now=now,
            provider_family=family,
        )
        if refusal:
            state, reason = WEEKLY_SCORING_UNUSABLE, refusal
        elif not any(getattr(f, "status", None) == "ok" for f in fetches):
            state = WEEKLY_NO_USABLE_FETCH
            reason = "; ".join(
                sorted({str(getattr(f, "reason", "") or getattr(f, "status", "")) for f in fetches})
            )
        else:
            state, reason = WEEKLY_OK, None
        per_source[key] = baselines
        source_info[key] = {
            "providerFamily": family,
            "state": state,
            "reason": reason,
            "counts": dict(counts),
        }
        for name, n in counts.items():
            totals[name] = totals.get(name, 0) + n

    if source_info:
        states = [info["state"] for info in source_info.values()]
        agg_state = WEEKLY_OK if WEEKLY_OK in states else states[0]
        agg_reason = (
            None
            if agg_state == WEEKLY_OK
            else next((info["reason"] for info in source_info.values() if info["reason"]), None)
        )
    else:
        agg_state, agg_reason = weekly_state, weekly_reason

    out: dict[str, PlayerEstimate] = {}
    duplicates = 0
    for pid in ids:
        votes: dict[str, WeeklyBaseline] = {}
        for key in WEEKLY_SOURCE_ADAPTERS:
            b = per_source.get(key, {}).get(pid)
            if b is None:
                continue
            if b.provider_family in votes:
                # Same family = same evidence: one vote, never two.
                duplicates += 1
                continue
            votes[b.provider_family] = b
        if votes:
            out[pid] = _combine_families(pid, list(votes.values()))
            continue
        value = preseason.get(pid)
        if value is not None:
            out[pid] = PlayerEstimate(
                player_id=pid,
                points=value,
                basis=BASIS_PRESEASON,
                provider_points=value,
                join_key="normalized_name",
            )
    if duplicates:
        totals["sameFamilyDuplicates"] = duplicates

    weekly = [e for e in out.values() if e.basis != BASIS_PRESEASON]
    return GameDayEstimates(
        by_player_id=out,
        weekly_state=agg_state,
        weekly_reason=agg_reason,
        preseason_source=preseason_source if preseason else None,
        sources_loaded=tuple(sources_loaded),
        sources_unavailable=tuple(sources_unavailable),
        ambiguous_name_player_ids=ambiguous,
        weekly_counts=totals,
        weekly_as_of=max((e.provider_as_of for e in weekly if e.provider_as_of), default=None),
        weekly_observed_at=max((e.observed_at for e in weekly if e.observed_at), default=None),
        weekly_sources=source_info,
    )


__all__ = [
    "BASIS_LABELS",
    "BASIS_PRESEASON",
    "BASIS_WEEKLY",
    "BASIS_WEEKLY_ENSEMBLE",
    "SLEEPER_WEEKLY_SOURCE_KEY",
    "WEEKLY_SOURCE_ADAPTERS",
    "WEEKLY_SOURCE_LABEL",
    "GameDayEstimates",
    "PlayerEstimate",
    "WeeklyBaseline",
    "resolve_game_day_estimates",
]
