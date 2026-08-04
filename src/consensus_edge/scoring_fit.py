"""What this league's scoring does to a player's value.

Consensus Edge shipped claiming "custom-league scoring adjustments" and
imported nothing from the scoring or league-intelligence packages — zero
references to VORP, zero to ``src.scoring``, zero to ``src.league_intel``.
The frontend even sent a ``leagueKey`` that the API accepted and threw
away. This module closes that gap.

**Where it enters, and why that matters.** The multiplier is applied to
FAIR VALUE, inside :mod:`consensus_edge.fair_value`, never as a fourth
additive component. Scoring fit changes what a player is worth to *this*
league; it is not independent evidence that the market is wrong about
him. Adding it separately would count the same effect twice — once in the
value and once in the score — which is the specific double-count the
brief forbids.

**Evidence-gated, per axis.** The repo already measured which effects
survive scrutiny and which do not, and this reuses those measurements
rather than writing a third scorer:

* **Reception depth resolves PER PLAYER.** Catch-depth distributions vary
  meaningfully and stably between receivers, and this league pays
  0.25→2.00 per catch by distance band. ``reception_fit`` measures it.
* **IDP resolves at POSITION level.** Individual IDP scoring ratios were
  measured as mostly noise; ``scoring_fit`` gates on depth-drift and
  marks a position untrusted when its ratio moves with sample size.
  Forcing a per-player number here would be noise wearing precision.
* **Anything unmeasurable contributes exactly 1.0**, and says so. Same
  ABSENT-tier discipline as ``league_intel/adjustment.py``: a caller
  structurally cannot smuggle in an unevidenced effect.

So "full per-player" means per-player *where the data supports it*, and
an honest fallback where it does not — with the resolved level stamped on
every row so a reader can tell which they got.

**It refuses cleanly.** The measurements need nflverse weekly rows and a
reception-depth payload. Outside production those are absent, every axis
returns 1.0, and the board is exactly what it was before — no silent
half-application.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

# Levels at which a player's multiplier was resolved.
LEVEL_PLAYER = "player"
LEVEL_POSITION = "position"
LEVEL_ABSENT = "absent"

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {}


@dataclass(frozen=True)
class PlayerScoringFit:
    """One player's scoring-fit multiplier and where it came from."""

    multiplier: float = 1.0
    level: str = LEVEL_ABSENT
    reason: str | None = None

    @property
    def is_inert(self) -> bool:
        return self.level == LEVEL_ABSENT or self.multiplier == 1.0


@dataclass
class ScoringFitBoard:
    """Multipliers for a whole board, plus what was and was not measured."""

    by_player: dict[str, PlayerScoringFit] = field(default_factory=dict)
    by_position: dict[str, float] = field(default_factory=dict)
    measured_axes: list[str] = field(default_factory=list)
    absent_axes: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    scoring_version: str | None = None
    baseline_version: str | None = None
    league_id: str | None = None

    def for_player(self, player_key: str, position: str | None) -> PlayerScoringFit:
        """Most specific multiplier available for this player.

        Player-level wins when present; otherwise the position tilt;
        otherwise exactly 1.0. Never raises and never guesses — an
        unknown position is a no-op, because the alternative is applying
        an IDP tilt to a wide receiver.
        """
        hit = self.by_player.get(player_key)
        if hit is not None:
            return hit
        pos = str(position or "").strip().upper()
        tilt = self.by_position.get(pos)
        if tilt is not None and tilt != 1.0:
            return PlayerScoringFit(multiplier=tilt, level=LEVEL_POSITION)
        return PlayerScoringFit(
            multiplier=1.0,
            level=LEVEL_ABSENT,
            reason=self.reasons.get("summary") or "no measured scoring effect for this player",
        )

    @property
    def active(self) -> bool:
        return bool(self.by_player) or any(v != 1.0 for v in self.by_position.values())

    def to_meta(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "measuredAxes": self.measured_axes,
            "absentAxes": self.absent_axes,
            "reasons": self.reasons,
            "playersWithPlayerLevelFit": len(self.by_player),
            "positionTilts": self.by_position,
            "scoringVersion": self.scoring_version,
            "baselineVersion": self.baseline_version,
            "leagueId": self.league_id,
        }


def _scoring_cards() -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    """The league's card and the comparison baseline, both versioned.

    The league card comes from the committed dated snapshot under
    ``config/league_intel/`` — deliberately, not a live Sleeper fetch:
    a dynamically fetched card cannot be replayed, and a scoring-fit
    number that cannot be reproduced is not evidence.
    """
    meta: dict[str, Any] = {}
    try:
        from src.league_intel import config as league_config  # noqa: PLC0415

        cfg = league_config.load_canonical_config()
        my_scoring = dict(cfg.scoring_settings or {})
        meta["leagueId"] = cfg.sleeper_league_id
        meta["scoringVersion"] = str(cfg.sourced_at or cfg.config_version or "")
    except Exception as exc:  # noqa: BLE001 — absence is a state, not a crash
        return None, None, {"reason": f"league scoring unavailable: {exc}"}

    try:
        from src.scoring.baseline_config import build_default_baseline_config  # noqa: PLC0415

        baseline = build_default_baseline_config()
        baseline_scoring = dict(baseline.scoring_map or {})
        meta["baselineVersion"] = baseline.scoring_version
    except Exception as exc:  # noqa: BLE001
        return my_scoring or None, None, {**meta, "reason": f"baseline unavailable: {exc}"}

    if not my_scoring:
        return None, baseline_scoring, {**meta, "reason": "league snapshot carries no scoring map"}
    return my_scoring, baseline_scoring, meta


def measure(*, season: int | None = None, refresh: bool = False) -> ScoringFitBoard:
    """Measure both axes, cached per process.

    Cached because the IDP axis rescores every weekly row under two rate
    cards — far too heavy for a per-request path, and the answer only
    changes when a scoring card or a season does.
    """
    my_scoring, baseline_scoring, meta = _scoring_cards()
    cache_key = f"{meta.get('scoringVersion')}|{meta.get('baselineVersion')}|{season}"
    with _LOCK:
        if not refresh and _CACHE.get("key") == cache_key:
            return _CACHE["board"]

    board = ScoringFitBoard(
        scoring_version=meta.get("scoringVersion"),
        baseline_version=meta.get("baselineVersion"),
        league_id=meta.get("leagueId"),
    )

    if not my_scoring or not baseline_scoring:
        board.absent_axes = ["idpPositionFit", "receptionDepthFit"]
        board.reasons["summary"] = str(meta.get("reason") or "scoring cards unavailable")
        with _LOCK:
            _CACHE["key"] = cache_key
            _CACHE["board"] = board
        return board

    _measure_idp_axis(board, my_scoring, baseline_scoring, season)
    _measure_reception_axis(board, my_scoring, baseline_scoring, season)

    if not board.measured_axes:
        board.reasons.setdefault(
            "summary", "no scoring axis could be measured from the available data"
        )

    with _LOCK:
        _CACHE["key"] = cache_key
        _CACHE["board"] = board
    return board


def _measure_idp_axis(
    board: ScoringFitBoard,
    my_scoring: dict[str, Any],
    baseline_scoring: dict[str, Any],
    season: int | None,
) -> None:
    """Position-level IDP tilt, or nothing.

    Position level is not a shortcut — it is what the evidence supports.
    ``scoring_fit`` marks a position untrusted when its ratio drifts with
    sample depth, and ``multiplier_for`` already returns 1.0 for those,
    so an untrusted position is inert without any extra handling here.
    """
    try:
        from src.league_intel import scoring_fit as li_scoring_fit  # noqa: PLC0415
        from src.nfl_data.ingest import fetch_weekly_defensive_stats  # noqa: PLC0415

        # Same source `src/api/gameplan.py` uses for this measurement, so
        # the two cannot disagree about what "this league's IDP tilt" is.
        rows = fetch_weekly_defensive_stats([int(season)]) if season else None
        if not rows:
            board.absent_axes.append("idpPositionFit")
            board.reasons["idpPositionFit"] = "no weekly stat rows available for this season"
            return
        measurement = li_scoring_fit.measure_positional_scoring_fit(
            rows, my_scoring, baseline_scoring, season=season
        )
    except Exception as exc:  # noqa: BLE001 — heavy optional deps (pandas/nflverse)
        board.absent_axes.append("idpPositionFit")
        board.reasons["idpPositionFit"] = f"unavailable: {exc}"
        return

    if not getattr(measurement, "measured", False):
        board.absent_axes.append("idpPositionFit")
        board.reasons["idpPositionFit"] = getattr(measurement, "reason", "") or "not measured"
        return

    for position in li_scoring_fit.TRACKED_POSITIONS:
        board.by_position[position] = float(measurement.multiplier_for(position))
    board.measured_axes.append("idpPositionFit")


def _measure_reception_axis(
    board: ScoringFitBoard,
    my_scoring: dict[str, Any],
    baseline_scoring: dict[str, Any],
    season: int | None,
) -> None:
    """Per-player reception-depth fit, or nothing.

    This is the axis that genuinely resolves per player: catch-depth
    distributions differ stably between receivers and this league pays by
    distance band. ``reception_fit`` refuses as a WHOLE when dispersion
    is unstable across pool depth — no individual multiplier from an
    unstable measurement is trustworthy, so there is no partial credit.
    """
    try:
        from src.league_intel import reception_fit as li_reception_fit  # noqa: PLC0415
        from src.nfl_data import reception_depth  # noqa: PLC0415

        payload = reception_depth.load_reception_depth(season) if season else None
        if not payload:
            board.absent_axes.append("receptionDepthFit")
            board.reasons["receptionDepthFit"] = "no reception-depth payload available"
            return
        measurement = li_reception_fit.measure_reception_depth_fit(
            payload, None, my_scoring, baseline_scoring, season=season
        )
    except Exception as exc:  # noqa: BLE001
        board.absent_axes.append("receptionDepthFit")
        board.reasons["receptionDepthFit"] = f"unavailable: {exc}"
        return

    multipliers = getattr(measurement, "multipliers", None) or {}
    trusted = bool(getattr(measurement, "trusted", False))
    if not multipliers or not trusted:
        board.absent_axes.append("receptionDepthFit")
        board.reasons["receptionDepthFit"] = getattr(measurement, "reason", "") or (
            "measurement not trusted" if multipliers else "no per-player multipliers produced"
        )
        return

    # ``multipliers`` is keyed by GSIS id; the board is keyed by display
    # name and contract rows carry no GSIS id. Without a resolved join
    # this axis must REFUSE rather than apply zero matches, because a
    # silent no-match is indistinguishable from "measured and neutral"
    # and would let the board claim a per-player scoring effect it never
    # actually applied. Supply ``gsis_to_player_key`` to activate it.
    join = _CACHE.get("gsisJoin")
    if not join:
        board.absent_axes.append("receptionDepthFit")
        board.reasons["receptionDepthFit"] = (
            "measured, but not applied: multipliers are keyed by GSIS id and no "
            "GSIS-to-board join is available (contract rows carry no GSIS id)"
        )
        return

    applied = 0
    for gsis_id, value in multipliers.items():
        player_key = join.get(str(gsis_id))
        if not player_key:
            continue
        board.by_player[str(player_key)] = PlayerScoringFit(
            multiplier=float(value), level=LEVEL_PLAYER
        )
        applied += 1

    if applied:
        board.measured_axes.append("receptionDepthFit")
    else:
        board.absent_axes.append("receptionDepthFit")
        board.reasons["receptionDepthFit"] = "measured, but no player matched the board"


def set_gsis_join(mapping: dict[str, str] | None) -> None:
    """Supply the GSIS-id → board-key map the reception axis needs.

    Deliberately injected rather than resolved in here: the identity
    mapping is the identity package's job, and guessing at it inside a
    scoring module is how two subtly different joins end up in one repo.
    """
    with _LOCK:
        _CACHE["gsisJoin"] = dict(mapping or {})
        _CACHE.pop("key", None)  # force a re-measure against the new join
