"""Game Day per-player weekly baselines — which projection each player uses, and why.

One question, one owner: for this league-week, what is each rostered
player's PROVIDER weekly baseline (the pregame number our rest-of-game
forecast is scaled from), where did it come from, and what does it not
cover?  :mod:`src.ros.game_day_week` consumes the answer; it never picks a
source itself.

Two bases, never blended for one player
---------------------------------------
* ``weekly:rotowire_via_sleeper`` — the player's Sleeper weekly projection
  (RotoWire stat lines, :mod:`src.ros.sleeper_weekly_projections`),
  rescored under THIS league's card by the exact scorer, and LOCKED at his
  game's kickoff (:func:`lock_baseline_at_kickoff`): the last observation
  fetched at or before kickoff.  An in-game provider update can never drift
  the baseline; a player first seen after kickoff has no weekly baseline.
  Gated by the ``sleeper_weekly_projections`` flag, DEFAULT OFF: a source
  candidate whose terms are UNVERIFIED (census ``licensingStatus``);
  activation is pending terms verification.
* ``preseason_full_season_fallback`` — the per-game average from the
  full-season ROS ensemble (``PRESEASON_FULL_SEASON`` horizon).  Used only
  when no locked weekly baseline exists.  It is a FALLBACK and NOT a
  current-week forecast; :data:`BASIS_LABELS` carries that wording so no
  consumer can present it as the weekly projection.

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

Missing is never zero: a player with neither basis has no estimate at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from src.nfl_data.first_down_rate import (
    SLEEPER_PROJECTED_FD_KEYS,
    imputed_sleeper_first_down_bonus,
)
from src.utils.name_clean import normalize_player_name

BASIS_WEEKLY = "weekly:rotowire_via_sleeper"
BASIS_PRESEASON = "preseason_full_season_fallback"
#: Factual source label for the weekly basis.  Its terms are unverified, so
#: the label says it is a candidate, not an activated source.
WEEKLY_SOURCE_LABEL = (
    "RotoWire via Sleeper (source candidate — activation pending terms verification)"
)
#: Human-facing wording per basis, published in lineage beside every count.
BASIS_LABELS: dict[str, str] = {
    BASIS_WEEKLY: f"Weekly projection — {WEEKLY_SOURCE_LABEL}, locked at kickoff",
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
class PlayerEstimate:
    """One player's pregame weekly baseline, with its provenance."""

    player_id: str
    #: The baseline the resolver scales: provider points + our imputed part.
    points: float
    basis: str
    #: Weekly: the provider line under the league card, WITHOUT our
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
    #: Counts from the kickoff lock, for lineage.
    weekly_counts: dict[str, int] = field(default_factory=dict)
    #: Newest provider stamp / fetch time among the weekly baselines used.
    weekly_as_of: str | None = None
    weekly_observed_at: str | None = None

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


def _weekly_baselines(
    fetches: Sequence[Any],
    *,
    season: int,
    week: int,
    scoring_settings: Mapping[str, Any],
    kickoffs_by_team: Mapping[str, float],
    now: float,
) -> tuple[dict[str, Any], dict[str, int], str | None]:
    """``(player_id -> BaselineEntry, counts, refusal reason)``."""
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
    return dict(lock.baselines), counts, None


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
    weekly_state: str = WEEKLY_NOT_REQUESTED,
    weekly_reason: str | None = None,
    kickoffs_by_team: Mapping[str, float] | None = None,
) -> GameDayEstimates:
    """Per-player baselines for ``player_ids``: locked weekly first, else preseason.

    ``weekly_fetches`` are :class:`~src.ros.sleeper_weekly_projections.FetchResult`
    observations (possibly several, fetched at different times — the lock
    takes each player's last pre-kickoff one).  ``kickoffs_by_team`` maps a
    normalized NFL team code to its game's kickoff (epoch seconds).
    """
    ids = [str(p) for p in player_ids]
    preseason, ambiguous = (
        _preseason_by_id(ids, players_meta, preseason_by_name)
        if preseason_by_name and preseason_source
        else ({}, ())
    )

    baselines: dict[str, Any] = {}
    counts: dict[str, int] = {}
    state, reason = weekly_state, weekly_reason
    paid_fd_keys = [k for k in SLEEPER_PROJECTED_FD_KEYS if _rate(scoring_settings, k) != 0.0]
    if weekly_fetches:
        baselines, counts, refusal = _weekly_baselines(
            weekly_fetches,
            season=season,
            week=week,
            scoring_settings=scoring_settings,
            kickoffs_by_team=kickoffs_by_team or {},
            now=now,
        )
        if refusal:
            state, reason = WEEKLY_SCORING_UNUSABLE, refusal
        elif not any(getattr(f, "status", None) == "ok" for f in weekly_fetches):
            state = WEEKLY_NO_USABLE_FETCH
            reason = reason or "; ".join(
                sorted(
                    {
                        str(getattr(f, "reason", "") or getattr(f, "status", ""))
                        for f in weekly_fetches
                    }
                )
            )
        else:
            state = WEEKLY_OK

    out: dict[str, PlayerEstimate] = {}
    weekly_as_of: str | None = None
    weekly_observed_at: str | None = None
    refused_fd = 0
    for pid in ids:
        entry = baselines.get(pid)
        if entry is not None:
            obs = entry.observation
            if paid_fd_keys and any(k in obs.stat_line for k in paid_fd_keys):
                # The provider's *_fd keys are yardage/10, not first downs
                # (see first_down_rate.SLEEPER_PROJECTED_FD_KEYS); a card that
                # pays them would price that proxy.  Refused, not scored.
                refused_fd += 1
                entry = None
        if entry is not None:
            obs = entry.observation
            imputed = imputed_sleeper_first_down_bonus(
                obs.stat_line, obs.position, scoring_settings
            )
            imputed_points = imputed[2] if imputed else 0.0
            imputed_keys = (imputed[0],) if imputed else ()
            uncovered = tuple(k for k in obs.uncovered_scoring_keys if k not in imputed_keys)
            out[pid] = PlayerEstimate(
                player_id=pid,
                points=obs.league_scored_points + imputed_points,
                basis=BASIS_WEEKLY,
                provider_points=obs.league_scored_points,
                imputed_points=imputed_points,
                imputed_keys=imputed_keys,
                uncovered_keys=uncovered,
                provider_as_of=obs.provider_updated_at,
                observed_at=obs.observed_at,
                kickoff_locked=entry.locked,
            )
            if obs.provider_updated_at and (
                weekly_as_of is None or obs.provider_updated_at > weekly_as_of
            ):
                weekly_as_of = obs.provider_updated_at
            if weekly_observed_at is None or obs.observed_at > weekly_observed_at:
                weekly_observed_at = obs.observed_at
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
    if refused_fd:
        counts["refusedProviderFirstDownKeys"] = refused_fd

    return GameDayEstimates(
        by_player_id=out,
        weekly_state=state,
        weekly_reason=reason,
        preseason_source=preseason_source if preseason else None,
        sources_loaded=tuple(sources_loaded),
        sources_unavailable=tuple(sources_unavailable),
        ambiguous_name_player_ids=ambiguous,
        weekly_counts=counts,
        weekly_as_of=weekly_as_of,
        weekly_observed_at=weekly_observed_at,
    )


def _rate(scoring_settings: Mapping[str, Any], key: str) -> float:
    try:
        return float((scoring_settings or {}).get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "BASIS_LABELS",
    "BASIS_PRESEASON",
    "BASIS_WEEKLY",
    "WEEKLY_SOURCE_LABEL",
    "GameDayEstimates",
    "PlayerEstimate",
    "resolve_game_day_estimates",
]
