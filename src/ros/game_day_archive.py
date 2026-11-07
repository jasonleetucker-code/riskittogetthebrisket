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

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.utils.config_loader import repo_root

_LOG = logging.getLogger(__name__)

ARCHIVE_ROOT = repo_root() / "data" / "game_day" / "predictions"

#: Per-run capture CONTEXT (injury state, board identity) lives in a
#: SIBLING tree, never inside a league-week directory: every ``*.json``
#: there is read back as a :class:`WeeklyPredictionSnapshot` by
#: :func:`load_snapshots_for_week`, so a context file beside the team
#: snapshots would break every reader of the week.
CONTEXT_ROOT = repo_root() / "data" / "game_day" / "capture_context"
CONTEXT_SCHEMA = "game-day-capture-context/v1"

#: A capture is taken at one of these moments. Distinct captures for the
#: same (league, season, week, team) are DISTINCT rows, never an
#: overwrite of one another — spec §5/§6 needs both a pregame snapshot
#: (for calibration against what was predicted before anything happened)
#: and later in-game/postgame snapshots (for live-updating evaluation).
#:
#: ``pregame_late`` (owner directive 2026-11-07, Part 7) is a SECOND
#: pre-event observation taken before the week's first SUNDAY kickoff.
#: ``pregame`` is taken before the week's FIRST kickoff (Thursday night,
#: usually ~Wednesday evening), so without it every Sunday/Monday game is
#: only ever archived against inputs four days stale.  It is its own kind,
#: so its own file (``<team>_pregame_late.json``): it can never overwrite
#: or be mistaken for the early snapshot, which stays the evidence of what
#: was knowable before ANY game of the week.
CAPTURE_KINDS: frozenset[str] = frozenset({"pregame", "pregame_late", "in_game", "postgame"})


class GameDayArchiveError(ValueError):
    """Raised on a malformed write, or a refused duplicate capture."""


class UnreadableSnapshotError(GameDayArchiveError):
    """A snapshot file exists at the tuple's path but cannot be read back.

    Distinct from ``None`` ("never captured"): the append-only slot is
    occupied, so a retry cannot fill it, and the observation is lost unless
    an operator recovers the file.  Only possible for a file written before
    :func:`_write_once` published atomically, or damaged after the fact.
    """


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
    #: What this capture was taken alongside: the projection inputs the
    #: estimates came from, the injury report as known at capture time and
    #: the canonical board current when it ran (see
    #: :func:`src.ros.game_day_capture.snapshot_provenance`).  ``None`` on
    #: every snapshot written before 2026-11-07 -- absent, never inferred.
    provenance: Mapping[str, Any] | None = field(default=None, hash=False)

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
        out: dict[str, Any] = {
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
        # Only when recorded: a snapshot written without provenance stays
        # byte-identical to the pre-2026-11-07 shape.
        if self.provenance is not None:
            out["provenance"] = dict(self.provenance)
        return out

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
            provenance=data.get("provenance"),
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
    provenance: Mapping[str, Any] | None = None,
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
        provenance=dict(provenance) if provenance is not None else None,
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
    _write_once(path, json.dumps(snapshot.to_dict(), indent=1))
    return snapshot


def _write_once(path: Path, text: str) -> None:
    """Create ``path`` holding exactly ``text``, refusing if it already exists.

    **A final path only ever holds complete content.**  The text goes to a
    temp file in the same directory first (a ``.tmp`` name, so the week
    readers' ``*.json`` glob never sees it), is flushed and fsynced, and only
    then published under the final name with ``os.link`` -- which fails with
    ``FileExistsError`` when the name is taken.  So the two properties hold
    together: two overlapping runs (a timer firing while a manual capture is
    in flight) cannot both publish, and a kill, timeout or full disk
    mid-write leaves at worst a stray ``.tmp`` file, never a truncated
    snapshot at the permanent, append-only name.

    The rule this replaced exclusive-created the FINAL path and wrote into
    it, so an interrupted write left partial JSON that the append-only rule
    then protected for good -- and because the readers parsed every file in
    a week folder, that one file broke both capture kinds for the rest of
    the week.

    Fallback: a filesystem without hard links (any ``os.link`` failure other
    than ``FileExistsError``) publishes by exclusive create of the final path
    -- still never an overwrite; the readers report a truncated file as
    unreadable rather than crash on it.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError as exc:
            raise GameDayArchiveError(
                f"{path} already exists — captures are append-only and are never overwritten"
            ) from exc
        except (OSError, AttributeError, NotImplementedError):
            _exclusive_create(path, text)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _exclusive_create(path: Path, text: str) -> None:
    """The no-hard-link fallback: exclusive create (``"x"``), never replace."""
    try:
        with path.open("x", encoding="utf-8") as fh:
            fh.write(text)
    except FileExistsError as exc:
        raise GameDayArchiveError(
            f"{path} already exists — captures are append-only and are never overwritten"
        ) from exc


def _read_json(path: Path) -> tuple[Any, str | None]:
    """``(parsed, None)`` or ``(None, reason)`` -- never raises on bad bytes."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _snapshot_kind_from_name(path: Path) -> str | None:
    """The capture kind a snapshot FILE NAME claims (``<team>_<kind>.json``).

    Used only to attribute a file whose content cannot be read; a readable
    snapshot's kind always comes from its content.  Longest kind first, so
    ``_pregame_late`` is never read as ``_pregame``.
    """
    for kind in sorted(CAPTURE_KINDS, key=len, reverse=True):
        if path.stem.endswith(f"_{kind}"):
            return kind
    return None


def _unreadable_entry(path: Path, kind: str | None, reason: str) -> dict[str, Any]:
    return {"path": str(path), "captureKind": kind, "reason": reason}


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
    snap, reason = _parse_snapshot(path)
    if snap is None:
        raise UnreadableSnapshotError(
            f"{path} exists but cannot be read back ({reason}) — the {capture_kind!r} "
            "slot is occupied, so this observation cannot be re-captured"
        )
    return snap


def _parse_snapshot(path: Path) -> tuple[WeeklyPredictionSnapshot | None, str | None]:
    data, reason = _read_json(path)
    if reason is not None:
        return None, reason
    try:
        return WeeklyPredictionSnapshot.from_dict(data), None
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def scan_snapshots_for_week(
    league_key: str,
    season: int,
    week: int,
    *,
    capture_kind: str | None = None,
    base_dir: Path | None = None,
) -> tuple[list[WeeklyPredictionSnapshot], list[dict[str, Any]]]:
    """``(snapshots, unreadable)`` for one league-week.

    A file that cannot be parsed back into a snapshot is reported in
    ``unreadable`` (``path`` / ``captureKind`` claimed by its NAME /
    ``reason``) instead of raising: one damaged file must not hide every
    other team's and every other kind's evidence for the week.  With
    ``capture_kind`` given, an unreadable file is reported only when its name
    claims that kind (or claims no recognisable kind)."""
    root = (base_dir or ARCHIVE_ROOT) / str(season) / league_key / f"week_{week}"
    if not root.exists():
        return [], []
    out: list[WeeklyPredictionSnapshot] = []
    unreadable: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        snap, reason = _parse_snapshot(path)
        if snap is None:
            claimed = _snapshot_kind_from_name(path)
            if capture_kind is None or claimed in (None, capture_kind):
                unreadable.append(_unreadable_entry(path, claimed, str(reason)))
            continue
        if capture_kind is not None and snap.capture_kind != capture_kind:
            continue
        out.append(snap)
    return out, unreadable


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
    none.  An unreadable file is logged and left out (a team it held is then
    missing, which is exactly what a gap check must see) -- use
    :func:`scan_snapshots_for_week` to get the list of them."""
    snaps, unreadable = scan_snapshots_for_week(
        league_key, season, week, capture_kind=capture_kind, base_dir=base_dir
    )
    for entry in unreadable:
        _LOG.warning(
            "game day archive: unreadable snapshot %s (%s)", entry["path"], entry["reason"]
        )
    return snaps


# ── per-run capture context ──────────────────────────────────────────


def _context_path(season: int, week: int, capture_kind: str, stamp: str, *, base_dir: Path) -> Path:
    root = base_dir / str(season) / f"week_{week}"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{capture_kind}__{stamp}.json"


def record_capture_context(
    *,
    season: int,
    week: int,
    capture_kind: str,
    injuries: Mapping[str, Any],
    canonical_board: Mapping[str, Any],
    run_id: str = "",
    base_dir: Path | None = None,
) -> tuple[Path, str, dict[str, Any]]:
    """Record what one capture RUN was taken alongside.  Returns
    ``(path, sha256 of the bytes written, record)``.

    One file per run, never per week: two runs of the same window (league A
    captured at 20:00, league B only at 00:00 after a Sleeper failure) each
    saw their own injury report, and each team snapshot points at the exact
    file it was captured with (``provenance.captureContext``).  The name
    carries the real capture instant to the microsecond and the file is
    created exclusively, so a context is never overwritten -- the same
    append-only rule as :func:`record_snapshot`.

    ``capturedAt`` is stamped here from the real clock, never accepted.
    The two blocks are already-resolved data (the owner of each is named in
    it); this store only records them.
    """
    if capture_kind not in CAPTURE_KINDS:
        raise GameDayArchiveError(f"capture_kind {capture_kind!r} not in {sorted(CAPTURE_KINDS)}")
    for name, block in (("injuries", injuries), ("canonical_board", canonical_board)):
        if not isinstance(block, Mapping) or block.get("state") not in {"known", "unavailable"}:
            raise GameDayArchiveError(
                f"{name}: a context block must state 'known' or 'unavailable' -- an "
                "absent block would read as 'nothing to report'"
            )
    now = datetime.now(timezone.utc)
    record = {
        "schema": CONTEXT_SCHEMA,
        "season": int(season),
        "week": int(week),
        "captureKind": capture_kind,
        "capturedAt": now.isoformat(),
        "runId": run_id,
        "injuries": dict(injuries),
        "canonicalBoardAtCapture": dict(canonical_board),
    }
    path = _context_path(
        season,
        week,
        capture_kind,
        now.strftime("%Y%m%dT%H%M%S%fZ"),
        base_dir=base_dir or CONTEXT_ROOT,
    )
    _write_once(path, json.dumps(record, indent=1, sort_keys=True, default=str))
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), record


def scan_capture_contexts(
    season: int,
    week: int,
    *,
    capture_kind: str | None = None,
    base_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(records oldest first, unreadable)`` for one week -- the posture of
    :func:`scan_snapshots_for_week`: a damaged context file is reported, never
    raised, so it cannot block either kind's evidence."""
    root = (base_dir or CONTEXT_ROOT) / str(season) / f"week_{week}"
    if not root.exists():
        return [], []
    out: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        record, reason = _read_json(path)
        if reason is None and not isinstance(record, dict):
            reason = f"not a context record ({type(record).__name__})"
        if reason is not None:
            prefix = path.stem.split("__", 1)[0]
            claimed = prefix if prefix in CAPTURE_KINDS else None
            if capture_kind is None or claimed in (None, capture_kind):
                unreadable.append(_unreadable_entry(path, claimed, reason))
            continue
        if capture_kind is not None and record.get("captureKind") != capture_kind:
            continue
        out.append(record)
    return sorted(out, key=lambda r: str(r.get("capturedAt"))), unreadable


def load_capture_contexts(
    season: int,
    week: int,
    *,
    capture_kind: str | None = None,
    base_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Every recorded context for one week, oldest first.  Empty means none
    was recorded -- not an error: every week before 2026-11-07 has none.  An
    unreadable file is logged and left out (:func:`scan_capture_contexts`
    returns it)."""
    records, unreadable = scan_capture_contexts(
        season, week, capture_kind=capture_kind, base_dir=base_dir
    )
    for entry in unreadable:
        _LOG.warning("game day archive: unreadable context %s (%s)", entry["path"], entry["reason"])
    return records
