"""AL-P4 — dated, point-in-time pick-forecast / team-strength snapshot (CAPTURE ONLY).

Why this exists
───────────────
Adaptive Learning directive §10 (Future Draft Pick Learning) and §21
("capture first"; perishable audit ``docs/BRISKET_IDEAS.md`` §13.4, AL-P4).
The Pick Projector (``src/ros/pick_projection.py``) is computed per request
off the CURRENT ``team_ros_strength``, and that input is overwritten in place
(``data/ros/team_strength/*.json`` is un-staged from git by
``scheduled-refresh.yml``). So the state a pick forecast was made from at
week N cannot be rebuilt later, and the eventual draft slot can never be
joined back to it. Once a week is gone it is gone; a model of P(early / mid /
late) or of the empirical annual discount can only be evaluated
prospectively against records like these.

What one record is
──────────────────
One record per ``(leagueKey, NFL season, season type, capture window,
tier)``. Season and season type always come from Sleeper's own
``/state/nfl``. The capture WINDOW is ``nfl-week:<N>`` (Sleeper's week) while
the season type is ``regular`` / ``post``; outside those (``pre`` / ``off``)
the host's week does not advance with games, so a fixed week would collapse a
whole offseason into one record -- there the window is the UTC ISO week of the
capture (``iso-week:YYYY-Www``). Sleeper's ``/state/nfl`` offseason payload is
not recorded anywhere in this repository (no fixture, no cached response; the
consumers only gate on ``season_type`` -- ``game_day_live`` treats anything but
``regular`` as out of season, ``capture_game_day_predictions`` refuses
``pre``), so the window does not rely on what week it reports then. The raw
``nflState`` is recorded either way.

Within a window, records are APPEND-ONLY and ranked by TIER (``TIERS``,
ascending): ``captureSettled`` first, then completeness
(``degraded`` < ``partial`` < ``complete``). A run writes only when its tier
is strictly better than the best already recorded for the window, and the new
line names what it ``supersedes``; nothing is ever overwritten, so history is
kept and a re-run at an equal or lower tier is a no-op. ``current_snapshots``
answers "the record for each window"; ``iter_snapshots`` is the full history.

* **settled** -- no week of the current season is part-played: every week
  with a scored entry (``metrics.scored_weeks``) is final
  (``metrics.final_weeks`` -- the host clock, or full scoring plus every NFL
  game final). A Monday run before Monday Night Football is UNSETTLED and
  cannot take the window from a settled capture; a settled one supersedes it.
  Independent of WHEN Sleeper advances its week (not established in this
  repository): ``lastFinalWeek`` stamps the league's own finished-week
  boundary, so "after week N" and "during week N+1" read the same whatever the
  host's week number says. If the host week flips between the Tuesday slot and
  a catch-up slot, the catch-up records the next window with the same
  ``lastFinalWeek``.
* **completeness** -- ``degraded``: a CORE field (``CORE_LEAGUE_FIELDS`` /
  ``CORE_TEAM_FIELDS``: teams + standings, pick ownership, forecast) is null
  for a STRUCTURAL reason (e.g. the overlay pick fold carrying unidentifiable
  details); ``partial``: core present, some other field null for a TRANSIENT
  reason (``TRANSIENT_REASON_MARKERS``: a fetch failure, a timeout, a stale
  contract); ``complete``: neither.
* A core field null for a TRANSIENT reason is never written at all:
  ``record_snapshot`` raises ``TransientCaptureRefused`` and the recorder exits
  non-zero so systemd retries (one degraded run used to take the whole week).

Each record holds, per team, the outputs of the EXISTING canonical owners --
nothing here is a model:

=================  ======================================================
field              canonical owner consumed
=================  ======================================================
rosStrength        ``ros.team_strength.load_or_compute_team_strength``
depth              same row (``benchDepthScore`` / ``benchDepth``)
injuries           same row (``healthAvailabilityScore`` + ``fullRoster``
                   injured flags, Sleeper ``injury_status``)
roster             same row (``fullRoster``) — composition as of the week
record / points    ``public_league.metrics.season_standings`` (Sleeper's
                   roster ``settings``)
allPlay            ``public_league.luck.build_section`` current-season rows
remainingSchedule  ``ros.playoff_sim.remaining_schedule`` (the same
                   posted-matchup reader both simulators use)
rosterQuality      ``api.roster_intelligence.build_league_roster_intelligence``
                   ``strength`` (canonical 1-9999 board) — contract league only
age                same owner, ``agePortfolio`` — contract league only
ownedPicks         ``api.sleeper_overlay._build_teams_block`` pick fold, which
                   delegates to ``identity.picks.build_pick_ownership`` -- a
                   TEMPORARY private seam: the overlay is the only code that
                   folds ``/traded_picks`` today, and it cannot say how certain
                   its ownership is (a failed fetch reads as "no trades").
                   Until the ownership-certainty fix lands in the overlay, this
                   module observes the fetch itself and fails closed.
=================  ======================================================

plus league-level ``rules`` (``public_league.playoff_structure``, the league's
own ``settings`` verbatim, its drafts' order/slot maps, the scoring-config
fingerprint) and the ``forecast`` the Pick Projector serves today with its
model identity (module, code hash, git revision — it carries no version
constant, which the record says).

MISSING IS NEVER ZERO. Every tracked field is either a value or ``None``, and
every ``None`` has a machine-readable reason in that row's ``missing`` map
(``assert_missing_reasons`` enforces it before a write). Nothing is imputed:
a league whose ``/traded_picks`` fetch failed records NO pick ownership rather
than the default-ownership fold the overlay falls back to, and a pick forecast
is not recorded when its ownership input is unproven.

Boundaries
──────────
* **No served output changes.** Team strength is read with ``persist=False``;
  nothing here writes ``data/ros/``, ``exports/``, the contract, a flag or a
  cache another reader serves. The contract used for roster quality is built
  in memory from the freshest served payload and discarded.
* **Private, box-local, out of git.** The store is gitignored
  ``data/pick_forecast_snapshots/`` (monthly ``ledger-YYYY-MM.jsonl`` + the
  ``ledger.keys`` index — the neutral append-only owner
  ``src.utils.append_ledger``, shared with the sparse-evidence shadow).
  A store path under ``data/ros/`` is REFUSED: the scheduled refresh
  force-adds that tree, and these rows are per-manager roster intelligence.
* **Capture, not learning.** No consumer reads this store. Fitting a slot
  distribution or a discount curve from it is a separately authorized unit.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import append_ledger as _ledger

SCHEMA = "pick-forecast-snapshot/v2"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "data" / "pick_forecast_snapshots"
_FORCE_ADDED_ROOT = REPO_ROOT / "data" / "ros"

#: Per-team fields every record carries. Each is a value or ``None``; a
#: ``None`` must name its reason in the row's ``missing`` map.
TEAM_FIELDS: tuple[str, ...] = (
    "rosStrength",
    "depth",
    "injuries",
    "roster",
    "record",
    "points",
    "allPlay",
    "remainingSchedule",
    "rosterQuality",
    "age",
    "ownedPicks",
)

#: League-level fields with the same value-or-reason contract.
LEAGUE_FIELDS: tuple[str, ...] = (
    "pickOwnership",
    "forecast",
    "playoffStructure",
    "leagueSettings",
    "drafts",
    "draftOrderRule",
    "scoringConfigFingerprint",
)

#: The rookie-draft order rule has no canonical owner in this repository.
#: ``pick_projection`` ASSUMES reverse final standings; whether this league
#: uses that, a lottery, or a max-PF order is recorded nowhere, so the record
#: says so instead of copying the assumption in as a fact.
DRAFT_ORDER_RULE_UNOWNED = (
    "no_canonical_owner: no repository record states this league's rookie-draft "
    "order rule (reverse standings / lottery / max-PF); pick_projection ASSUMES "
    "reverse final standings"
)

_PROJECTOR_MODULE = REPO_ROOT / "src" / "ros" / "pick_projection.py"

#: Sleeper season types whose ``week`` advances with games. Anything else is
#: keyed by the capture's UTC ISO week instead (see the module docstring).
IN_SEASON_TYPES: tuple[str, ...] = ("regular", "post")

#: The fields a record is FOR. A null here for a transient reason refuses the
#: write; for a structural reason it makes the record ``degraded``.
CORE_LEAGUE_FIELDS: tuple[str, ...] = ("teams", "pickOwnership", "forecast")
CORE_TEAM_FIELDS: tuple[str, ...] = ("record", "points")

#: Reason fragments that mean "this read failed", not "this does not exist":
#: a fetch failure, a timeout, an exception from an owner, or a contract that
#: is stale or could not be built. Matched anywhere in a reason, because reasons
#: nest (``pick_ownership_unproven:traded_picks_fetch_failed_...``). Anything
#: else -- ``unidentifiable_pick_details:N``, ``canonical_contract_is_for_league``,
#: ``contract_build_skipped``, ``no_games_played``, ``draftOrderRule`` -- is
#: structural: a re-run would answer the same.
TRANSIENT_REASON_MARKERS: tuple[str, ...] = (
    "public_snapshot_failed",
    "league_has_no_current_season",
    "current_season_integrity_failed",
    "standings_failed",
    "all_play_failed",
    "remaining_schedule_failed",
    "scoring_fingerprint_failed",
    "team_strength_failed",
    "team_strength_unavailable_every_tier_declined",
    "sleeper_rosters_or_users_fetch_failed",
    "traded_picks_fetch_failed",
    "overlay_failed",
    "pick_projection_failed",
    "roster_intelligence_failed",
    "contract_stale",
    "contract_age_unknown",
    "contract_build_failed",
    "no_served_payload_on_disk",
    "playoff_structure_failed",
    "settlement_unknown",
)

COMPLETENESS_ORDER: tuple[str, ...] = ("degraded", "partial", "complete")
#: Every tier, ascending. Settledness outranks completeness: a settled capture
#: answers the week-boundary question an unsettled one cannot.
TIERS: tuple[str, ...] = tuple(
    f"{settled}/{completeness}"
    for settled in ("unsettled", "settled")
    for completeness in COMPLETENESS_ORDER
)
TOP_TIER = TIERS[-1]

#: An empty ``owner_id`` is an orphaned roster: every owner-keyed field is
#: UNKNOWN for it, never an empty list or another reason's default.
ORPHAN_ROSTER_REASON = "orphan_roster_owner_unknown"


class StorePathRefused(ValueError):
    """The store would land somewhere private rows must never go."""


class TransientCaptureRefused(RuntimeError):
    """A CORE field is null because a read failed; writing would lose the window.

    ``misses`` maps each refused field to its reason. The recorder exits
    non-zero on this so the unit is retried, rather than filing a degraded
    record in place of the complete one a retry would have produced.
    """

    def __init__(self, misses: Mapping[str, str]) -> None:
        self.misses = dict(misses)
        super().__init__(
            "core field(s) missing for a transient reason: "
            + ", ".join(f"{k}={v}" for k, v in sorted(self.misses.items()))
        )


# ── identity ─────────────────────────────────────────────────────────


def _window_text(window: str | int) -> str:
    return window if isinstance(window, str) else f"nfl-week:{int(window)}"


def snapshot_key(
    league_key: str, season: str, season_type: str, window: str | int, tier: str
) -> str:
    """One record per league per capture window per TIER (``window`` may be a
    Sleeper week number, meaning ``nfl-week:<n>``)."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    raw = f"{SCHEMA}|{league_key}|{season}|{season_type}|{_window_text(window)}|{tier}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tier_rank(tier: str) -> int:
    return TIERS.index(tier)


def week_identity(nfl_state: Mapping[str, Any] | None) -> tuple[str, str, int] | None:
    """``(season, season_type, week)`` from Sleeper's ``/state/nfl``, or ``None``.

    Never derived from the calendar: a record filed under a week the host
    disagrees with is filed under the wrong week, so an unreadable state is a
    refusal, not a guess.
    """
    if not isinstance(nfl_state, Mapping):
        return None
    season = str(nfl_state.get("season") or "").strip()
    season_type = str(nfl_state.get("season_type") or "").strip()
    raw_week = nfl_state.get("week")
    if not season or not season_type or raw_week is None or isinstance(raw_week, bool):
        return None
    try:
        week = int(raw_week)
    except (TypeError, ValueError):
        return None
    if week < 0:
        return None
    return season, season_type, week


def capture_window(nfl_state: Mapping[str, Any], recorded_at: str) -> str:
    """``nfl-week:<N>`` in season, else the capture's UTC ``iso-week:YYYY-Www``."""
    ident = week_identity(nfl_state)
    if ident is None:
        raise ValueError("nfl_state carries no usable season / season_type / week")
    _season, season_type, week = ident
    if season_type in IN_SEASON_TYPES and week >= 1:
        return f"nfl-week:{week}"
    at = datetime.fromisoformat(str(recorded_at).replace("Z", "+00:00"))
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    year, iso_week, _ = at.astimezone(timezone.utc).isocalendar()
    return f"iso-week:{year}-W{iso_week:02d}"


def check_store_path(base: Path) -> Path:
    """Refuse a store under the force-added ``data/ros/`` tree."""
    resolved = Path(base).resolve()
    ros = _FORCE_ADDED_ROOT.resolve()
    if resolved == ros or ros in resolved.parents:
        raise StorePathRefused(
            f"{resolved} is under data/ros/, which scheduled-refresh.yml force-adds "
            "to a public repository; pick-forecast snapshots are private"
        )
    return resolved


# ── model identity of what is served today ───────────────────────────


def _git_revision() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    rev = out.stdout.strip()
    return rev if out.returncode == 0 and rev else None


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def projector_identity() -> dict[str, Any]:
    """What produced ``forecast``: the served Pick Projector, named exactly."""
    from src.ros import pick_projection  # noqa: PLC0415

    return {
        "module": "src.ros.pick_projection",
        "function": "build_pick_projections",
        "modelVersion": None,
        "modelVersionMissingReason": "pick_projection_carries_no_version_constant",
        "codeSha256": _file_sha256(_PROJECTOR_MODULE),
        "codeRevision": _git_revision(),
        "orderRuleAssumed": "reverse_final_standings",
        "strengthInput": "teamRosStrength",
        "confidenceCeilingByHorizon": dict(pick_projection.CONFIDENCE_CEILING_BY_HORIZON),
        "confidenceCeilingBeyond": pick_projection.CONFIDENCE_CEILING_BEYOND,
        "confidenceRatios": {
            "high": pick_projection.CONFIDENCE_HIGH_RATIO,
            "medium": pick_projection.CONFIDENCE_MEDIUM_RATIO,
        },
    }


# ── inputs (gathered from canonical owners) and the pure assembly ────


@dataclass
class SnapshotInputs:
    """Everything one record is built from, already read from its owner.

    Every ``*_reason`` names why its sibling is ``None``. Tests build this
    directly; :func:`gather_inputs` fills it on the box.
    """

    league_key: str
    nfl_state: Mapping[str, Any]
    rosters: list[Mapping[str, Any]] | None = None
    rosters_reason: str | None = None
    team_names: Mapping[str, str] = field(default_factory=dict)
    league: Mapping[str, Any] | None = None
    league_reason: str | None = None
    drafts: list[Mapping[str, Any]] | None = None
    drafts_reason: str | None = None
    scoring_fingerprint: str | None = None
    scoring_fingerprint_reason: str | None = None
    playoff_structure: Mapping[str, Any] | None = None
    playoff_structure_reason: str | None = None
    strength_rows: list[Mapping[str, Any]] | None = None
    strength_reason: str | None = None
    strength_source: str | None = None
    standings: list[Mapping[str, Any]] | None = None
    standings_reason: str | None = None
    luck_rows: list[Mapping[str, Any]] | None = None
    luck_reason: str | None = None
    remaining_schedule: list[tuple[int, str, str]] | None = None
    remaining_schedule_reason: str | None = None
    roster_intel: Mapping[str, Any] | None = None
    roster_intel_reason: str | None = None
    overlay_teams: list[Mapping[str, Any]] | None = None
    overlay_reason: str | None = None
    forecast: Mapping[str, Any] | None = None
    forecast_reason: str | None = None
    #: ``True`` / ``False``, or ``None`` when settlement could not be read.
    capture_settled: bool | None = None
    capture_settled_reason: str | None = "settlement_not_observed"
    last_final_week: int | None = None
    in_progress_weeks: list[int] = field(default_factory=list)
    provenance: Mapping[str, Any] = field(default_factory=dict)


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pick_ownership(
    league_key: str, overlay_teams: Iterable[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """League picks by canonical id with their CURRENT owner, from the overlay fold.

    The id is re-minted through ``LeaguePickIdentity`` and must agree with the
    overlay's own ``assetId`` stamp — a pick the owner cannot identify is
    counted, never guessed.
    """
    from src.identity.picks import LeaguePickIdentity  # noqa: PLC0415

    picks: list[dict[str, Any]] = []
    unidentified = 0
    for team in overlay_teams:
        for detail in team.get("pickDetails") or []:
            if not isinstance(detail, Mapping):
                continue
            season = _int(detail.get("season"))
            rnd = _int(detail.get("round"))
            origin = _int(detail.get("original_roster_id"))
            owner = _int(detail.get("owner_roster_id"))
            if season is None or rnd is None or origin is None or owner is None:
                unidentified += 1
                continue
            try:
                ident = LeaguePickIdentity(
                    league_key=league_key, season=season, round_num=rnd, origin_roster_id=origin
                )
            except ValueError:
                unidentified += 1
                continue
            stamped = detail.get("assetId")
            if stamped is not None and stamped != ident.canonical_id:
                unidentified += 1
                continue
            picks.append(
                {
                    "assetId": ident.canonical_id,
                    "season": season,
                    "round": rnd,
                    "originRosterId": origin,
                    "ownerRosterId": owner,
                    # The overlay fold never fetches draft order, so slot is
                    # UNKNOWN here (None), never 0 and never a tier.
                    "slot": detail.get("slot"),
                }
            )
    picks.sort(key=lambda p: (p["season"], p["round"], p["originRosterId"]))
    if not picks:
        return None, "overlay_teams_carry_no_identifiable_picks"
    if unidentified:
        # Partial ownership is not ownership: a forecast or a learner joining
        # against it would silently miss the unidentified assets.
        return None, f"unidentifiable_pick_details:{unidentified}"
    return picks, None


def _forecast_block(league_key: str, forecast: Mapping[str, Any]) -> dict[str, Any]:
    """The served Pick Projector output, each pick joined to its canonical id."""
    from src.identity.picks import LeaguePickIdentity  # noqa: PLC0415

    picks = []
    for p in forecast.get("picks") or []:
        row = dict(p)
        try:
            row["assetId"] = LeaguePickIdentity(
                league_key=league_key,
                season=int(p["season"]),
                round_num=int(p["round"]),
                origin_roster_id=int(p["originalRosterId"]),
            ).canonical_id
        except (KeyError, TypeError, ValueError):
            row["assetId"] = None
        picks.append(row)
    return {
        "model": projector_identity(),
        "projectedOrder": list(forecast.get("projectedOrder") or []),
        "picks": picks,
        "meta": dict(forecast.get("meta") or {}),
    }


def _injuries(row: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    roster = row.get("fullRoster")
    if not isinstance(roster, list):
        return None, "team_strength_row_has_no_fullRoster"
    injured = [
        {
            "playerId": p.get("playerId"),
            "canonicalName": p.get("canonicalName"),
            "position": p.get("position"),
            "rosValue": p.get("rosValue"),
        }
        for p in roster
        if isinstance(p, Mapping) and p.get("injured") is True
    ]
    return (
        {
            "healthAvailabilityScore": row.get("healthAvailabilityScore"),
            "injuredPlayers": injured,
            # hydrate_roster_players' rule, stated so a learner knows what
            # "injured" meant at capture time.
            "injuredDefinition": "sleeper injury_status in {OUT, IR, PUP, DOUBTFUL}",
        },
        None,
    )


def _team_row(
    rid: int,
    owner_id: str,
    inputs: SnapshotInputs,
    *,
    strength_by_rid: Mapping[int, Mapping[str, Any]],
    standing_by_rid: Mapping[int, Mapping[str, Any]],
    luck_by_owner: Mapping[str, Mapping[str, Any]],
    schedule_by_owner: Mapping[str, list[dict[str, Any]]] | None,
    schedule_reason: str | None,
    picks_by_owner: Mapping[int, list[str]] | None,
    picks_reason: str | None,
) -> dict[str, Any]:
    missing: dict[str, str] = {}
    out: dict[str, Any] = {
        "rosterId": rid,
        "ownerId": owner_id or None,
        "teamName": inputs.team_names.get(owner_id) if owner_id else None,
    }

    srow = strength_by_rid.get(rid)
    if srow is None:
        reason = inputs.strength_reason or "team_absent_from_team_strength_rows"
        for name in ("rosStrength", "depth", "injuries", "roster"):
            out[name] = None
            missing[name] = reason
    else:
        out["rosStrength"] = {k: v for k, v in srow.items() if k != "fullRoster"}
        out["depth"] = {
            "benchDepthScore": srow.get("benchDepthScore"),
            "benchDepth": srow.get("benchDepth"),
        }
        out["injuries"], injury_reason = _injuries(srow)
        if injury_reason:
            missing["injuries"] = injury_reason
        roster = srow.get("fullRoster")
        out["roster"] = roster if isinstance(roster, list) else None
        if out["roster"] is None:
            missing["roster"] = "team_strength_row_has_no_fullRoster"

    stand = standing_by_rid.get(rid)
    if stand is None:
        reason = inputs.standings_reason or "team_absent_from_standings"
        out["record"] = out["points"] = None
        missing["record"] = missing["points"] = reason
    else:
        games = _int(stand.get("games"))
        out["record"] = {
            k: stand.get(k)
            for k in ("wins", "losses", "ties", "games", "winPct", "standing", "sleeperRank")
        }
        ppg = None
        if games:
            ppg = round(float(stand.get("pointsFor")) / games, 2)
        out["points"] = {
            "pointsFor": stand.get("pointsFor"),
            "pointsAgainst": stand.get("pointsAgainst"),
            "pointsPerGame": ppg,
            "pointsPerGameMissingReason": None if games else "no_games_played",
        }

    # allPlay, remainingSchedule, rosterQuality and age are keyed by OWNER. An
    # orphaned roster (empty owner_id) has none of them KNOWN -- never [], and
    # never another reason's default.
    lrow = luck_by_owner.get(owner_id) if owner_id else None
    if not owner_id:
        out["allPlay"] = None
        missing["allPlay"] = ORPHAN_ROSTER_REASON
    elif lrow is None:
        out["allPlay"] = None
        missing["allPlay"] = inputs.luck_reason or "no_scored_regular_season_weeks_this_season"
    else:
        out["allPlay"] = {
            k: lrow.get(k)
            for k in (
                "gamesPlayed",
                "allPlayWinPct",
                "expectedWins",
                "actualWins",
                "luckDelta",
                "pointsFor",
                "pointsAgainst",
            )
        }

    if schedule_by_owner is None:
        out["remainingSchedule"] = None
        missing["remainingSchedule"] = schedule_reason or "remaining_schedule_unavailable"
    elif not owner_id:
        out["remainingSchedule"] = None
        missing["remainingSchedule"] = ORPHAN_ROSTER_REASON
    elif owner_id not in schedule_by_owner:
        # Others have posted future matchups and this owner has none: that is
        # not "no opponents left", it is an owner the schedule does not place.
        out["remainingSchedule"] = None
        missing["remainingSchedule"] = "owner_absent_from_posted_schedule"
    else:
        out["remainingSchedule"] = schedule_by_owner[owner_id]

    intel_teams = inputs.roster_intel.get("teams") if inputs.roster_intel else None
    intel = intel_teams.get(owner_id) if isinstance(intel_teams, Mapping) and owner_id else None
    if not owner_id:
        out["rosterQuality"] = out["age"] = None
        missing["rosterQuality"] = missing["age"] = ORPHAN_ROSTER_REASON
    elif intel is None:
        reason = inputs.roster_intel_reason or "team_absent_from_roster_intelligence"
        out["rosterQuality"] = out["age"] = None
        missing["rosterQuality"] = missing["age"] = reason
    else:
        out["rosterQuality"] = intel.get("strength")
        out["age"] = intel.get("agePortfolio")
        for name in ("rosterQuality", "age"):
            if out[name] is None:
                missing[name] = "roster_intelligence_row_omits_field"

    if picks_by_owner is None:
        out["ownedPicks"] = None
        missing["ownedPicks"] = picks_reason or "pick_ownership_unavailable"
    else:
        out["ownedPicks"] = picks_by_owner.get(rid, [])

    out["missing"] = missing
    return out


def assemble_snapshot(inputs: SnapshotInputs, *, recorded_at: str | None = None) -> dict[str, Any]:
    """Pure: build one record from already-gathered canonical outputs."""
    ident = week_identity(inputs.nfl_state)
    if ident is None:
        raise ValueError("nfl_state carries no usable season / season_type / week")
    season, season_type, week = ident
    recorded_at = recorded_at or datetime.now(timezone.utc).isoformat()

    league_missing: dict[str, str] = {}

    picks, picks_reason = (None, inputs.overlay_reason or "overlay_teams_unavailable")
    if inputs.overlay_teams is not None:
        picks, picks_reason = _pick_ownership(inputs.league_key, inputs.overlay_teams)
    if picks is None:
        league_missing["pickOwnership"] = str(picks_reason)

    if inputs.forecast is not None and picks is not None:
        forecast: dict[str, Any] | None = _forecast_block(inputs.league_key, inputs.forecast)
    else:
        forecast = None
        league_missing["forecast"] = (
            inputs.forecast_reason
            if inputs.forecast is None
            else f"pick_ownership_unproven:{picks_reason}"
        ) or "forecast_unavailable"

    settings = (inputs.league or {}).get("settings") if inputs.league is not None else None
    league_settings = dict(settings) if isinstance(settings, Mapping) else None
    if league_settings is None:
        league_missing["leagueSettings"] = inputs.league_reason or "league_has_no_settings_block"
    if inputs.playoff_structure is None:
        league_missing["playoffStructure"] = (
            inputs.playoff_structure_reason or "playoff_structure_unavailable"
        )
    if inputs.drafts is None:
        league_missing["drafts"] = inputs.drafts_reason or "drafts_unavailable"
    if inputs.scoring_fingerprint is None:
        league_missing["scoringConfigFingerprint"] = (
            inputs.scoring_fingerprint_reason or "scoring_fingerprint_unavailable"
        )
    league_missing["draftOrderRule"] = DRAFT_ORDER_RULE_UNOWNED

    strength_by_rid: dict[int, Mapping[str, Any]] = {}
    for row in inputs.strength_rows or []:
        rid = _int(row.get("rosterId"))
        if rid is not None:
            strength_by_rid[rid] = row
    standing_by_rid: dict[int, Mapping[str, Any]] = {}
    for row in inputs.standings or []:
        rid = _int(row.get("rosterId"))
        if rid is not None:
            standing_by_rid[rid] = row
    luck_by_owner = {str(r.get("ownerId")): r for r in inputs.luck_rows or [] if r.get("ownerId")}

    schedule_by_owner: dict[str, list[dict[str, Any]]] | None = None
    schedule_reason = inputs.remaining_schedule_reason
    if inputs.remaining_schedule:
        schedule_by_owner = {}
        for wk, a, b in inputs.remaining_schedule:
            schedule_by_owner.setdefault(str(a), []).append({"week": int(wk), "opponent": str(b)})
            schedule_by_owner.setdefault(str(b), []).append({"week": int(wk), "opponent": str(a)})
        for games in schedule_by_owner.values():
            games.sort(key=lambda g: g["week"])
    elif inputs.remaining_schedule is not None and not schedule_reason:
        # Season over, or the host has not posted the schedule: either way
        # no remaining opponent is KNOWN, which is not "no opponents".
        schedule_reason = "no_posted_future_regular_season_matchups"

    picks_by_owner: dict[int, list[str]] | None = None
    if picks is not None:
        picks_by_owner = {}
        for p in picks:
            picks_by_owner.setdefault(p["ownerRosterId"], []).append(p["assetId"])

    teams: list[dict[str, Any]] = []
    if inputs.rosters is None:
        league_missing["teams"] = inputs.rosters_reason or "current_season_rosters_unavailable"
    else:
        for roster in inputs.rosters:
            rid = _int(roster.get("roster_id"))
            if rid is None:
                continue
            teams.append(
                _team_row(
                    rid,
                    str(roster.get("owner_id") or "").strip(),
                    inputs,
                    strength_by_rid=strength_by_rid,
                    standing_by_rid=standing_by_rid,
                    luck_by_owner=luck_by_owner,
                    schedule_by_owner=schedule_by_owner,
                    schedule_reason=schedule_reason,
                    picks_by_owner=picks_by_owner,
                    picks_reason=picks_reason,
                )
            )
        teams.sort(key=lambda t: t["rosterId"])
        if not teams:
            league_missing["teams"] = "current_season_has_no_identifiable_rosters"

    window = capture_window(inputs.nfl_state, recorded_at)
    record = {
        "schema": SCHEMA,
        "key": None,  # set below, once the tier is known
        "leagueKey": inputs.league_key,
        "season": season,
        "seasonType": season_type,
        "week": week,
        "captureWindow": window,
        "recordedAt": recorded_at,
        "asOf": recorded_at,
        "nflState": dict(inputs.nfl_state),
        "captureSettled": inputs.capture_settled,
        "captureSettledReason": None if inputs.capture_settled else inputs.capture_settled_reason,
        "lastFinalWeek": inputs.last_final_week,
        "inProgressWeeks": list(inputs.in_progress_weeks),
        "teamStrengthSource": inputs.strength_source,
        "rules": {
            "playoffStructure": dict(inputs.playoff_structure)
            if inputs.playoff_structure is not None
            else None,
            "leagueSettings": league_settings,
            "drafts": [dict(d) for d in inputs.drafts] if inputs.drafts is not None else None,
            "draftOrderRule": None,
            "scoringConfigFingerprint": inputs.scoring_fingerprint,
        },
        "pickOwnership": picks,
        "forecast": forecast,
        "teams": teams,
        "missing": league_missing,
        "provenance": dict(inputs.provenance),
        "supersedes": None,  # set by record_snapshot when a lower tier is replaced
        "supersedesTier": None,
    }
    assert_missing_reasons(record)
    completeness = completeness_of(record)
    tier = f"{'settled' if inputs.capture_settled is True else 'unsettled'}/{completeness}"
    record["completeness"] = completeness
    record["transientMissing"] = transient_misses(record)
    record["tier"] = tier
    record["tierRank"] = tier_rank(tier)
    record["key"] = snapshot_key(inputs.league_key, season, season_type, window, tier)
    return record


def is_transient_reason(reason: Any) -> bool:
    text = str(reason or "")
    return any(marker in text for marker in TRANSIENT_REASON_MARKERS)


def _all_misses(record: Mapping[str, Any]) -> dict[str, str]:
    out = {str(k): str(v) for k, v in (record.get("missing") or {}).items()}
    for team in record.get("teams") or []:
        for name, reason in (team.get("missing") or {}).items():
            out[f"teams[{team.get('rosterId')}].{name}"] = str(reason)
    return out


def core_misses(record: Mapping[str, Any]) -> dict[str, str]:
    """Every CORE field that is null, with its reason (path -> reason)."""
    out = {
        name: str(reason)
        for name, reason in (record.get("missing") or {}).items()
        if name in CORE_LEAGUE_FIELDS
    }
    for team in record.get("teams") or []:
        for name, reason in (team.get("missing") or {}).items():
            if name in CORE_TEAM_FIELDS:
                out[f"teams[{team.get('rosterId')}].{name}"] = str(reason)
    return out


def transient_misses(record: Mapping[str, Any]) -> dict[str, str]:
    """Every null field (league or team) whose reason is a failed read."""
    return {k: v for k, v in _all_misses(record).items() if is_transient_reason(v)}


def transient_core_misses(record: Mapping[str, Any]) -> dict[str, str]:
    """CORE nulls caused by a failed read -- the condition that refuses a write."""
    return {k: v for k, v in core_misses(record).items() if is_transient_reason(v)}


def completeness_of(record: Mapping[str, Any]) -> str:
    """``degraded`` (a core null), ``partial`` (a transient non-core null), or ``complete``."""
    if core_misses(record):
        return "degraded"
    if transient_misses(record):
        return "partial"
    return "complete"


def assert_missing_reasons(record: Mapping[str, Any]) -> None:
    """Every ``None`` tracked field names its reason. Raises otherwise."""
    league_missing = record.get("missing") or {}
    rules = record.get("rules") or {}
    league_values = {
        "pickOwnership": record.get("pickOwnership"),
        "forecast": record.get("forecast"),
        **{k: rules.get(k) for k in LEAGUE_FIELDS if k not in {"pickOwnership", "forecast"}},
    }
    for name, value in league_values.items():
        if value is None and not league_missing.get(name):
            raise ValueError(f"league field {name!r} is None with no recorded reason")
    if not record.get("teams") and not league_missing.get("teams"):
        raise ValueError("record has no teams and no recorded reason")
    for team in record.get("teams") or []:
        team_missing = team.get("missing") or {}
        for name in TEAM_FIELDS:
            if name not in team:
                raise ValueError(f"team {team.get('rosterId')} omits field {name!r}")
            if team[name] is None and not team_missing.get(name):
                raise ValueError(
                    f"team {team.get('rosterId')} field {name!r} is None with no recorded reason"
                )


# ── gathering from the canonical owners (box I/O) ────────────────────


def _reason(exc: BaseException) -> str:
    return f"{type(exc).__name__}:{exc}"[:300]


def _team_strength_file(league_key: str, fast_path: bool) -> dict[str, Any]:
    """Provenance of the persisted team-strength file: where, when, how old."""
    from src.ros.team_strength import team_strength_snapshot_path  # noqa: PLC0415

    try:
        path = Path(team_strength_snapshot_path(league_key))
    except Exception as exc:  # noqa: BLE001
        return {"path": None, "missingReason": f"path_unresolvable:{_reason(exc)}"}
    try:
        rel = str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        rel = str(path)
    out: dict[str, Any] = {"path": rel, "fastPathFresh": fast_path}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        out.update(mtime=None, ageHours=None, missingReason="no_persisted_team_strength_file")
        return out
    now = datetime.now(timezone.utc).timestamp()
    out["mtime"] = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
    out["ageHours"] = round((now - mtime) / 3600.0, 3)
    return out


def capture_settlement(current: Any) -> tuple[bool, str | None, int | None, list[int]]:
    """Is the current season at a clean week boundary? ``(settled, reason,
    lastFinalWeek, inProgressWeeks)``.

    Settled iff every week carrying a scored entry (``metrics.scored_weeks``)
    is final (``metrics.final_weeks``: the host clock, or full scoring plus every
    NFL game of the week final). A part-played week -- Monday before Monday
    Night Football, or Thursday after kickoff -- is not settled. Both owners
    are canonical; nothing here re-derives "final".
    """
    from src.public_league import metrics  # noqa: PLC0415

    scored = set(metrics.scored_weeks(current.matchups_by_week))
    final = set(metrics.final_weeks(current))
    in_progress = sorted(scored - final)
    finished = sorted(scored & final)
    last_final = finished[-1] if finished else None
    if in_progress:
        return False, f"weeks_in_progress:{in_progress}", last_final, in_progress
    return True, None, last_final, []


def contract_league_key(contract: Mapping[str, Any] | None) -> str | None:
    """Which league's rosters a contract carries — decided by FACT, not label.

    ``build_api_data_contract`` stamps no ``meta.leagueKey``; the server adds
    the default league's key afterwards, which is a label. The fact is the
    contract's own ``sleeper.leagueId`` (the league the scrape fetched rosters
    from), resolved through the registry. A ``meta.leagueKey`` that disagrees
    with it is a chimera and answers ``None``; so does an unregistered id.
    """
    if not isinstance(contract, Mapping):
        return None
    sleeper = contract.get("sleeper")
    league_id = sleeper.get("leagueId") if isinstance(sleeper, Mapping) else None
    if not league_id:
        return None
    try:
        from src.api.league_registry import league_key_for_sleeper_id  # noqa: PLC0415

        key = league_key_for_sleeper_id(str(league_id))
    except Exception:  # noqa: BLE001
        return None
    stamped = (contract.get("meta") or {}).get("leagueKey")
    if key is None or (stamped is not None and stamped != key):
        return None
    return key


def gather_inputs(
    cfg: Any,
    nfl_state: Mapping[str, Any],
    *,
    contract: Mapping[str, Any] | None,
    contract_reason: str | None,
    provenance: Mapping[str, Any] | None = None,
    http_get: Callable[[str], Any] | None = None,
) -> SnapshotInputs:
    """Read every input from its canonical owner. Never raises per input.

    Read-only by construction: ``load_or_compute_team_strength`` is called with
    ``persist=False``, so a capture run cannot overwrite the served snapshot.
    """
    league_key = cfg.key
    inputs = SnapshotInputs(
        league_key=league_key, nfl_state=dict(nfl_state), provenance=dict(provenance or {})
    )

    # The full Sleeper player dump is needed only when team strength will be
    # computed live (the snapshot tier hydrates names from it). When the read
    # path will answer from the fresh persisted file, skip the 5 MB download.
    fast_rows = None
    try:
        from src.ros.team_strength import persisted_fast_path_rows  # noqa: PLC0415

        fast_rows = persisted_fast_path_rows(league_key)
    except Exception:  # noqa: BLE001
        fast_rows = None
    need_dump = fast_rows is None
    inputs.provenance = {
        **dict(inputs.provenance),
        "teamStrengthFile": _team_strength_file(league_key, fast_rows is not None),
        "nflPlayerDumpRequested": need_dump,
    }

    def _season_unavailable(reason: str) -> None:
        inputs.rosters_reason = inputs.league_reason = inputs.drafts_reason = reason
        inputs.standings_reason = inputs.luck_reason = reason
        inputs.remaining_schedule_reason = inputs.playoff_structure_reason = reason
        inputs.scoring_fingerprint_reason = reason
        inputs.capture_settled, inputs.capture_settled_reason = None, reason

    snapshot = None
    try:
        from src.public_league.snapshot import build_public_snapshot  # noqa: PLC0415

        snapshot = build_public_snapshot(cfg.sleeper_league_id, include_nfl_players=need_dump)
    except Exception as exc:  # noqa: BLE001
        _season_unavailable(f"public_snapshot_failed:{_reason(exc)}")

    current = snapshot.current_season if snapshot is not None else None
    if snapshot is not None and current is None:
        # A registered league always has a current season; an empty chain is
        # a failed /league fetch (sleeper_client answers failures with None).
        _season_unavailable("league_has_no_current_season")
    if current is not None:
        # sleeper_client answers every failed GET with [], so a blip on
        # /rosters or /users yields a snapshot that LOOKS whole. The one
        # definition of "we know who is in this league right now".
        from src.public_league.snapshot import current_season_integrity_error  # noqa: PLC0415

        try:
            integrity = current_season_integrity_error(snapshot)
        except Exception as exc:  # noqa: BLE001
            integrity = _reason(exc)
        if integrity is not None:
            _season_unavailable(f"current_season_integrity_failed:{integrity}"[:300])
            current = None
            snapshot = None  # untrustworthy: not handed to team strength either

    if current is not None:
        from src.public_league import luck, metrics  # noqa: PLC0415
        from src.public_league.playoff_structure import resolve_playoff_structure  # noqa: PLC0415

        inputs.rosters = [dict(r) for r in current.rosters or [] if isinstance(r, Mapping)]
        inputs.team_names = {
            str(r.get("owner_id")): metrics.display_name_for(snapshot, str(r.get("owner_id")))
            for r in inputs.rosters
            if r.get("owner_id")
        }
        inputs.league = dict(current.league or {})
        inputs.drafts = [
            {
                k: d.get(k)
                for k in (
                    "draft_id",
                    "season",
                    "type",
                    "status",
                    "start_time",
                    "settings",
                    "draft_order",
                    "slot_to_roster_id",
                    "metadata",
                )
            }
            for d in current.drafts or []
            if isinstance(d, Mapping)
        ]
        try:
            inputs.playoff_structure = resolve_playoff_structure(current).to_dict()
        except Exception as exc:  # noqa: BLE001
            inputs.playoff_structure_reason = f"playoff_structure_failed:{_reason(exc)}"
        try:
            from src.ros import power_snapshots  # noqa: PLC0415

            inputs.scoring_fingerprint = power_snapshots.scoring_config_fingerprint(snapshot)
        except Exception as exc:  # noqa: BLE001
            inputs.scoring_fingerprint_reason = f"scoring_fingerprint_failed:{_reason(exc)}"
        try:
            inputs.standings = metrics.season_standings(current, snapshot.managers)
        except Exception as exc:  # noqa: BLE001
            inputs.standings_reason = f"standings_failed:{_reason(exc)}"
        try:
            section = luck.build_section(snapshot)
            inputs.luck_rows = list(section.get("currentSeasonRanked") or [])
        except Exception as exc:  # noqa: BLE001
            inputs.luck_reason = f"all_play_failed:{_reason(exc)}"
        try:
            from src.ros.playoff_sim import remaining_schedule  # noqa: PLC0415

            inputs.remaining_schedule = list(remaining_schedule(snapshot))
        except Exception as exc:  # noqa: BLE001
            inputs.remaining_schedule_reason = f"remaining_schedule_failed:{_reason(exc)}"
        try:
            (
                inputs.capture_settled,
                inputs.capture_settled_reason,
                inputs.last_final_week,
                inputs.in_progress_weeks,
            ) = capture_settlement(current)
        except Exception as exc:  # noqa: BLE001
            inputs.capture_settled = None
            inputs.capture_settled_reason = f"settlement_unknown:{_reason(exc)}"

    try:
        from src.ros.team_strength import load_or_compute_team_strength  # noqa: PLC0415

        rows = load_or_compute_team_strength(league_key, snapshot=snapshot, persist=False)
        if rows:
            inputs.strength_rows = rows
            inputs.strength_source = (
                "persisted_snapshot"
                if fast_rows is not None and rows == fast_rows
                else "live_compute"
            )
        else:
            inputs.strength_reason = "team_strength_unavailable_every_tier_declined"
    except Exception as exc:  # noqa: BLE001
        inputs.strength_reason = f"team_strength_failed:{_reason(exc)}"

    if contract is None:
        inputs.roster_intel_reason = contract_reason or "canonical_contract_unavailable"
    else:
        contract_league = contract_league_key(contract)
        if contract_league != league_key:
            # The contract's rosters belong to one league; pricing another
            # league's teams from them would be a chimera.
            inputs.roster_intel_reason = f"canonical_contract_is_for_league:{contract_league}"
        else:
            try:
                from src.api.roster_intelligence import (  # noqa: PLC0415
                    build_league_roster_intelligence,
                )

                team_count = None
                if inputs.rosters:
                    team_count = len(inputs.rosters)
                inputs.roster_intel = build_league_roster_intelligence(
                    contract, team_count=team_count
                )
            except Exception as exc:  # noqa: BLE001
                inputs.roster_intel_reason = f"roster_intelligence_failed:{_reason(exc)}"

    # Pick ownership: the overlay's fold, with the /traded_picks outcome
    # observed. The fold itself treats a failed fetch as "no trades" and
    # returns DEFAULT ownership; a capture must not record that as fact.
    # TEMPORARY SEAM: ``_build_teams_block`` / ``_http_get_json`` are private to
    # the overlay, which is the only owner of the ownership fold today. This
    # use stays (a second fold would be a second owner) until the overlay can
    # state its own ownership certainty; then the observation below goes and
    # this reads that statement instead.
    traded_ok: dict[str, bool] = {}
    try:
        from src.api import sleeper_overlay  # noqa: PLC0415

        base_get = http_get or sleeper_overlay._http_get_json

        def _observing_get(url: str) -> Any:
            result = base_get(url)
            if url.rstrip("/").endswith("/traded_picks"):
                traded_ok["ok"] = isinstance(result, list)
            return result

        teams = sleeper_overlay._build_teams_block(
            cfg.sleeper_league_id, None, getter=_observing_get
        )
        if teams is None:
            inputs.overlay_reason = "sleeper_rosters_or_users_fetch_failed"
        elif traded_ok.get("ok") is not True:
            inputs.overlay_reason = "traded_picks_fetch_failed_ownership_unproven"
        else:
            inputs.overlay_teams = teams
    except Exception as exc:  # noqa: BLE001
        inputs.overlay_reason = f"overlay_failed:{_reason(exc)}"

    if inputs.overlay_teams is None:
        inputs.forecast_reason = f"pick_ownership_unproven:{inputs.overlay_reason}"
    elif not inputs.strength_rows:
        inputs.forecast_reason = f"team_strength_unavailable:{inputs.strength_reason}"
    else:
        try:
            from src.ros.pick_projection import build_pick_projections  # noqa: PLC0415

            # The exact call /api/ros/pick-projections serves.
            inputs.forecast = build_pick_projections(
                list(inputs.overlay_teams), list(inputs.strength_rows)
            )
        except Exception as exc:  # noqa: BLE001
            inputs.forecast_reason = f"pick_projection_failed:{_reason(exc)}"

    return inputs


# ── the store ────────────────────────────────────────────────────────


def _window_keys(
    league_key: str, season: str, season_type: str, window: str | int
) -> list[tuple[str, str]]:
    """``(tier, key)`` for every tier of one window, ascending."""
    return [(t, snapshot_key(league_key, season, season_type, window, t)) for t in TIERS]


def best_recorded(
    base: Path,
    league_key: str,
    season: str,
    season_type: str,
    window: str | int,
    *,
    known: set[str] | None = None,
) -> tuple[str, str] | None:
    """The highest ``(tier, key)`` already recorded for a window, or ``None``.

    Read from the sidecar key index alone: every tier's key is derivable, so
    no record is parsed to answer it.
    """
    keys = recorded_keys(base) if known is None else known
    best = None
    for tier, key in _window_keys(league_key, season, season_type, window):
        if key in keys:
            best = (tier, key)
    return best


def record_snapshot(record: Mapping[str, Any], base: Path = DEFAULT_DIR) -> bool:
    """Append ``record`` if its tier beats the window's best. True when written.

    Refuses (``TransientCaptureRefused``) a record whose CORE field is null
    for a transient reason: that is a failed read, and filing it would hold the
    window with a record a retry would have bettered. Never overwrites -- a
    better tier is a NEW line naming the key it ``supersedes``; an equal or
    lower tier is a no-op (False).
    """
    base = check_store_path(base)
    assert_missing_reasons(record)
    refused = transient_core_misses(record)
    if refused:
        raise TransientCaptureRefused(refused)
    tier = record.get("tier")
    league_key, season = record.get("leagueKey"), record.get("season")
    season_type, window = record.get("seasonType"), record.get("captureWindow")
    if tier not in TIERS or record.get("key") != snapshot_key(
        league_key, season, season_type, window, tier
    ):
        raise ValueError("record key does not match its league / season / window / tier")
    best = best_recorded(base, league_key, season, season_type, window)
    if best is not None and tier_rank(best[0]) >= tier_rank(tier):
        return False
    out = dict(record)
    out["supersedes"] = best[1] if best else None
    out["supersedesTier"] = best[0] if best else None
    return _ledger.append_record(base, out)


def recorded_keys(base: Path = DEFAULT_DIR) -> set[str]:
    return _ledger.recorded_keys(check_store_path(base))


def iter_snapshots(base: Path = DEFAULT_DIR):
    """Every recorded snapshot -- the full history, superseded ones included."""
    yield from _ledger.iter_all_records(check_store_path(base))


def current_snapshots(base: Path = DEFAULT_DIR) -> list[dict[str, Any]]:
    """The CURRENT record per (league, season, season type, window): its best tier."""
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for rec in iter_snapshots(base):
        if rec.get("tier") not in TIERS:
            continue  # not a record this schema can rank; never guessed into one
        ident = (
            rec.get("leagueKey"),
            rec.get("season"),
            rec.get("seasonType"),
            rec.get("captureWindow"),
        )
        held = best.get(ident)
        if held is None or tier_rank(rec["tier"]) > tier_rank(held["tier"]):
            best[ident] = rec
    return list(best.values())
