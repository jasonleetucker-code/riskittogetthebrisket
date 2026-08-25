"""C5-GD-02 — prediction archive without temporal leakage.

Named unit in `docs/C_SERIES_SCOPE_MANIFEST.md` (row `C5-GD-02`, flagged
`RET` — irreversible evidence, collection should start as early as the
phase allows). Governed by `docs/GAME_DAY_PROBABILITY_SPEC.md` §5's
archival requirement and `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` §10's
historical-contract field list.

**What this module is.** A pure, append-only capture store for
per-(league, season, week, team) prediction-relevant state: roster
composition, the lineup-eligible pool, per-player point estimates (with
an explicit availability flag — never a fabricated 0.0 for "no
estimate"), the league's scoring/slot configuration identity, and a real
wall-clock capture timestamp. Nothing here computes a probability,
simulates a week, or aggregates a standings credit.

**Why this exists now, before the model that will consume it.** Both
`docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` §4 (xWAR) and
`docs/GAME_DAY_PROBABILITY_SPEC.md` §10-12 require "the same archived
no-lookahead league-week scoring distribution/simulation" — and neither
exists in this codebase (confirmed by a two-agent audit before this unit
was written: every simulation engine found is forward-looking from live
roster state, and no archived per-week roster/projection data exists
before whenever capture starts). A pre-game prediction snapshot is
PERISHABLE: once a week is scored, the pre-event state that produced any
prediction is gone unless it was captured before the outcome was known.
Building the actual joint weekly simulator is deliberately NOT this
unit's job — its distribution family, sample count and correlation
handling are product-semantics-changing methodology choices this unit
must not invent unilaterally (see the calibration policy's PRIOR/
VALIDATED classification requirement). This module only makes sure the
evidence that simulator will eventually need to validate against is not
silently lost while nobody has decided that methodology yet.

**Where estimates come from is deliberately NOT this module's concern.**
A caller resolves point estimates (from BDVM, a future ensemble, or
elsewhere) and passes them in already-built. This keeps the store itself
dependency-light, testable without any live service, and honest about
what it owns: recording facts, not resolving them — the same separation
`src/history/store.py` (a pure store; callers pass already-resolved
values) already establishes for asset-value history. This module lives
beside it in spirit but not in code: `src/history/`'s own documented
scope is asset-identity-keyed observations only (no team/roster/week
axis anywhere in its schema, confirmed by reading it in full before
writing this module) — a league-week snapshot is a genuinely different
concept and does not belong inside that owner's table.

**Timestamp authority.** `captured_at` is always the real wall-clock
UTC instant `record_snapshot` is called — it is not a caller-supplied
field, structurally, so a caller cannot backdate a snapshot to make a
later capture look like it happened earlier. There is no floor constant
here analogous to `src.history.store.HISTORY_FLOOR`: there is no
earlier data to backfill, and none is invented — the floor is simply
"whenever this unit first deploys," which is not backfilled as a
"reconstructed" state (that fidelity label stays undefined here, the
same way `src/history/asof.py` defines but never produces one, per its
own documented precedent).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.config_loader import repo_root

ARCHIVE_ROOT = repo_root() / "data" / "game_day" / "predictions"

#: A capture is taken at one of these moments. Distinct captures for the
#: same (league, season, week, team) are DISTINCT rows, never an
#: overwrite of one another — spec §5/§6 needs both a pregame snapshot
#: (for calibration against what was predicted before anything happened)
#: and later in-game/postgame snapshots (for live-updating evaluation).
CAPTURE_KINDS: frozenset[str] = frozenset({"pregame", "in_game", "postgame"})


class GameDayArchiveError(ValueError):
    """Raised on a malformed write, or a refused duplicate capture."""


@dataclass(frozen=True)
class PlayerPointEstimate:
    """One player's point estimate for one team-week, or the explicit
    absence of one.

    ``point_estimate is None`` means genuinely unavailable — a source
    covers this league/format but not this specific player, or no
    source was queried for them. It is never coerced to 0.0; a 0.0
    estimate is a real claim ("this player is expected to score
    nothing") and must not read the same as "we don't know."
    """

    player_id: str
    position: str
    is_lineup_eligible: bool
    point_estimate: float | None = None
    estimate_source: str | None = None

    def __post_init__(self) -> None:
        if self.point_estimate is None and self.estimate_source is not None:
            raise GameDayArchiveError(
                f"{self.player_id}: estimate_source set without a point_estimate — "
                "a source with no estimate is not evidence of anything"
            )
        if self.point_estimate is not None and self.estimate_source is None:
            raise GameDayArchiveError(
                f"{self.player_id}: point_estimate given with no estimate_source — "
                "every real estimate must be attributable"
            )


@dataclass(frozen=True)
class WeeklyPredictionSnapshot:
    """One (league, season, week, team, capture_kind) prediction record.

    ``captured_at`` is stamped by :func:`record_snapshot` from the real
    clock — it is never accepted from a caller, so a snapshot cannot be
    backdated. See the module docstring for why there is deliberately no
    HISTORY_FLOOR-style constant here.
    """

    league_key: str
    season: int
    week: int
    team_id: str
    capture_kind: str
    captured_at: str
    scoring_config_id: str
    starter_slots: tuple[str, ...]
    roster: tuple[PlayerPointEstimate, ...]
    run_id: str = ""

    def __post_init__(self) -> None:
        if self.capture_kind not in CAPTURE_KINDS:
            raise GameDayArchiveError(
                f"capture_kind {self.capture_kind!r} not in {sorted(CAPTURE_KINDS)}"
            )
        if not self.roster:
            raise GameDayArchiveError(
                f"{self.league_key}/{self.season}/w{self.week}/{self.team_id}: "
                "empty roster — a snapshot with nobody on it is not evidence, "
                "it is a caller bug"
            )
        seen: set[str] = set()
        for p in self.roster:
            if p.player_id in seen:
                raise GameDayArchiveError(
                    f"{self.league_key}/{self.season}/w{self.week}/{self.team_id}: "
                    f"duplicate player_id {p.player_id!r} in roster"
                )
            seen.add(p.player_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "leagueKey": self.league_key,
            "season": self.season,
            "week": self.week,
            "teamId": self.team_id,
            "captureKind": self.capture_kind,
            "capturedAt": self.captured_at,
            "scoringConfigId": self.scoring_config_id,
            "starterSlots": list(self.starter_slots),
            "runId": self.run_id,
            "roster": [
                {
                    "playerId": p.player_id,
                    "position": p.position,
                    "isLineupEligible": p.is_lineup_eligible,
                    "pointEstimate": p.point_estimate,
                    "estimateSource": p.estimate_source,
                }
                for p in self.roster
            ],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "WeeklyPredictionSnapshot":
        return WeeklyPredictionSnapshot(
            league_key=data["leagueKey"],
            season=int(data["season"]),
            week=int(data["week"]),
            team_id=data["teamId"],
            capture_kind=data["captureKind"],
            captured_at=data["capturedAt"],
            scoring_config_id=data["scoringConfigId"],
            starter_slots=tuple(data.get("starterSlots") or ()),
            run_id=data.get("runId", ""),
            roster=tuple(
                PlayerPointEstimate(
                    player_id=r["playerId"],
                    position=r["position"],
                    is_lineup_eligible=bool(r["isLineupEligible"]),
                    point_estimate=r.get("pointEstimate"),
                    estimate_source=r.get("estimateSource"),
                )
                for r in data.get("roster") or ()
            ),
        )


def _snapshot_path(
    league_key: str, season: int, week: int, team_id: str, capture_kind: str, *, base_dir: Path
) -> Path:
    # Deterministic path from identity alone (no timestamp in the name) —
    # this is what makes "write again for the same tuple" collide on the
    # same file and be refusable, rather than silently accumulating
    # unbounded duplicate captures the way a timestamped filename would.
    root = base_dir / str(season) / league_key / f"week_{week}"
    root.mkdir(parents=True, exist_ok=True)
    safe_team = str(team_id).replace("/", "_")
    return root / f"{safe_team}_{capture_kind}.json"


def record_snapshot(
    *,
    league_key: str,
    season: int,
    week: int,
    team_id: str,
    capture_kind: str,
    scoring_config_id: str,
    starter_slots: "tuple[str, ...] | list[str]",
    roster: "tuple[PlayerPointEstimate, ...] | list[PlayerPointEstimate]",
    run_id: str = "",
    base_dir: Path | None = None,
) -> WeeklyPredictionSnapshot:
    """Capture one (league, season, week, team, capture_kind) prediction
    snapshot. Refuses (raises :class:`GameDayArchiveError`) if this exact
    tuple has already been captured — append-only, never a silent
    overwrite, matching `src/history/store.py`'s own discipline for
    asset-value observations.

    ``captured_at`` is not a parameter: it is always the real UTC instant
    this function runs, so a snapshot cannot be backdated by a caller.
    """
    snapshot = WeeklyPredictionSnapshot(
        league_key=league_key,
        season=season,
        week=week,
        team_id=team_id,
        capture_kind=capture_kind,
        captured_at=datetime.now(timezone.utc).isoformat(),
        scoring_config_id=scoring_config_id,
        starter_slots=tuple(starter_slots),
        roster=tuple(roster),
        run_id=run_id,
    )
    root = base_dir or ARCHIVE_ROOT
    path = _snapshot_path(league_key, season, week, team_id, capture_kind, base_dir=root)
    if path.exists():
        raise GameDayArchiveError(
            f"a {capture_kind!r} snapshot for {league_key}/{season}/w{week}/{team_id} "
            f"already exists at {path} — captures are append-only; this is not the "
            "place to update a prediction, only to record it once. If a genuinely "
            "distinct later capture is needed, use a different capture_kind."
        )
    path.write_text(json.dumps(snapshot.to_dict(), indent=1), encoding="utf-8")
    return snapshot


def load_snapshot(
    league_key: str,
    season: int,
    week: int,
    team_id: str,
    capture_kind: str,
    *,
    base_dir: Path | None = None,
) -> WeeklyPredictionSnapshot | None:
    """The one snapshot for this exact tuple, or ``None`` if it was never
    captured. ``None`` here means "no evidence was recorded" — a distinct
    state from a snapshot that recorded genuinely missing point
    estimates (which is a real, present snapshot with `point_estimate is
    None` entries)."""
    root = base_dir or ARCHIVE_ROOT
    path = _snapshot_path(league_key, season, week, team_id, capture_kind, base_dir=root)
    if not path.exists():
        return None
    return WeeklyPredictionSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_snapshots_for_week(
    league_key: str,
    season: int,
    week: int,
    *,
    capture_kind: str | None = None,
    base_dir: Path | None = None,
) -> list[WeeklyPredictionSnapshot]:
    """Every team's snapshot for one league-week, optionally filtered to
    one capture_kind. Empty list means nothing was captured — not an
    error, since a week before this unit's deployment genuinely has
    none."""
    root = (base_dir or ARCHIVE_ROOT) / str(season) / league_key / f"week_{week}"
    if not root.exists():
        return []
    out: list[WeeklyPredictionSnapshot] = []
    for path in sorted(root.glob("*.json")):
        snap = WeeklyPredictionSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if capture_kind is not None and snap.capture_kind != capture_kind:
            continue
        out.append(snap)
    return out
