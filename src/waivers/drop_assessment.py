"""Dynasty asset protection — may weekly streaming release this player?

For every player on ONE team's roster this answers: may the streaming
optimizer release him, and at what stated dynasty cost?  It is a
CLASSIFIER over inputs other owners compute.  It derives no value, no
replacement level, no lineup and no protection of its own:

* value / confidence / quarantine — the contract row (``rankDerivedValue``,
  ``confidenceBucket``, ``retainedAuthority``, ``quarantined``);
* replacement level — ``src/roster_intel/droppability.py::team_droppability``
  (``waiverValues``), the C2-DROP-01 consumer interface over
  ``src/draft/displacement.py``; the cost of a release is that owner's
  ``effective_cut_cost`` with scarcity inert;
* roster join — ``src/draft/context.py::build_roster_assets`` (the same join
  the cut ladder reads, so the two cannot disagree about who is on a roster);
* user protection — ``src/trade/constraints.py::TradeConstraints.block_reason``;
* value trend — ``src/history/asof.py::value_as_of`` (never a future
  observation);
* snap share / trend / depth — the playerctx snapshot
  (``src/playerctx/service.py::load_playerctx``);
* draft capital — ``src/bdvm/context.py::build_player_context`` over the
  cached nflverse id map (``src/nfl_data/ingest.fetch_id_map``, cache only).

Every threshold lives in ``config/waivers/streaming_protection.json`` as a
labelled PRIOR, and a missing or malformed file REFUSES — there is no code
default.

Three classes:

* ``protected`` — never auto-released: a user lock (absolute), an unpriced or
  quarantined value (missing is never zero, so never cheap), a meaningful
  dynasty asset, or a protecting development flag.
* ``churn`` — releasable at (near) zero dynasty cost: at or within the
  board's agreement band of the best equivalent free agent at his position,
  with no development flag, no churn-blocking unknown, and not a weekly
  starter the caller said it needs.
* ``conditional`` — everything else; droppable only within the user's
  explicit dynasty-loss budget, charged ``dynastyCost``.

``dynastyCost`` is the value above replacement (``max(0, V - W)``), not the
board value, because a release at or below the best free agent at the same
position loses nothing the wire cannot give back today.  ``dynastyValue`` is
kept beside it for a conservative budget.  Two consequences a consumer must
respect (see ``docs/waivers/DYNASTY_DROP_ASSESSMENT.md``): the replacement
is ONE player, so several releases at one position cannot each be charged
against the same free agent; and since the cost is already net of a
replacement, the solver must not also credit the added streamer's dynasty
value against it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping

from src.draft.context import (
    build_roster_assets,
    contract_teams,
    index_contract_rows,
    match_team,
)
from src.draft.displacement import RosterAsset, effective_cut_cost
from src.roster_intel.droppability import TeamNotInLeague, team_droppability
from src.utils.name_clean import normalize_player_name, normalize_position_family

__all__ = [
    "ASSESSMENT_CONTRACT_VERSION",
    "CLASS_CHURN",
    "CLASS_CONDITIONAL",
    "CLASS_PROTECTED",
    "DropAssessmentConfigError",
    "DropReason",
    "DynastyDropAssessment",
    "ProtectionConfig",
    "TeamDropAssessment",
    "TeamNotInLeague",
    "assess_team_drops",
    "load_protection_config",
]

ASSESSMENT_CONTRACT_VERSION = "dynasty-drop-assessment/2026-10-29.v1"

CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "waivers" / "streaming_protection.json"
)

CLASS_PROTECTED = "protected"
CLASS_CONDITIONAL = "conditional"
CLASS_CHURN = "churn"
_CLASSES = (CLASS_PROTECTED, CLASS_CONDITIONAL, CLASS_CHURN)

# Input states.  ``unavailable`` / ``stale`` / ``not_supplied`` are three
# different claims and are never collapsed into a value.
STATE_AVAILABLE = "available"
STATE_UNAVAILABLE = "unavailable"
STATE_STALE = "stale"
STATE_NOT_SUPPLIED = "not_supplied"

# Development flag vocabulary.  Which ones protect and which only block churn
# is CONFIG (``protectingFlags`` / ``churnBlockingFlags``), never code.
FLAG_YOUNG_RISING = "young_rising_usage"
FLAG_YOUNG_ESTABLISHED = "young_established_usage"
FLAG_HIGH_DRAFT_RECENT = "high_draft_capital_recent"
FLAG_VALUE_TRENDING_UP = "value_trending_up"
FLAG_YOUNG_USAGE_UNKNOWN = "young_usage_unknown"
FLAG_RECENT_DRAFT_UNKNOWN = "recent_draft_capital_unknown"
FLAG_AGE_UNKNOWN = "age_unknown"
KNOWN_FLAGS = frozenset(
    {
        FLAG_YOUNG_RISING,
        FLAG_YOUNG_ESTABLISHED,
        FLAG_HIGH_DRAFT_RECENT,
        FLAG_VALUE_TRENDING_UP,
        FLAG_YOUNG_USAGE_UNKNOWN,
        FLAG_RECENT_DRAFT_UNKNOWN,
        FLAG_AGE_UNKNOWN,
    }
)

RECOVERY_RISK_UNMEASURED = {
    "state": "unmeasured",
    "reason": (
        "no owner measures how often a released player is claimed by a rival in this "
        "league (src/trade/faab_history.py records bids, not post-release claims); "
        "no probability is invented"
    ),
}

# IDP / offense family of a bdvm ``true_position`` — used ONLY to confirm a
# name-keyed draft-capital record is the same player (identity guard).
_TRUE_POSITION_FAMILY = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "DT": "DL",
    "EDGE": "DL",
    "LB": "LB",
    "CB": "DB",
    "S": "DB",
}
_IDP_FAMILIES = frozenset({"DL", "LB", "DB"})

_DEFAULT = object()


class DropAssessmentConfigError(ValueError):
    """``config/waivers/streaming_protection.json`` is missing or malformed."""


# ── Config ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProtectionConfig:
    version: str
    sha256: str
    path: str
    churn_gap_max_by_confidence: Mapping[str, float]
    protect_gap_min: float
    clearly_below_gap_max: float
    young_age_max: float
    rising_snap_trend_min_pts: float
    min_games_for_trend: int
    established_snap_pct_min: float
    no_usage_snap_pct_max: float
    high_draft_capital_max_overall: int
    recent_draft_max_years_exp: int
    value_trend_window_days: int
    value_trend_up_min_ratio: float
    trend_max_observation_age_days: int
    usage_snapshot_max_age_days: float
    protecting_flags: frozenset[str]
    churn_blocking_flags: frozenset[str]

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "sha256": self.sha256, "path": self.path}


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def load_protection_config(path: Path | str | None = None) -> ProtectionConfig:
    """Read and validate the protection PRIORs — or refuse."""
    target = Path(path) if path is not None else CONFIG_PATH
    try:
        raw = target.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise DropAssessmentConfigError(f"{target}: unreadable ({exc})") from exc
    if not isinstance(doc, dict):
        raise DropAssessmentConfigError(f"{target}: not an object")
    version = doc.get("version")
    if not isinstance(version, str) or not version.strip():
        raise DropAssessmentConfigError(f"{target}: version missing")
    params = doc.get("parameters")
    if not isinstance(params, dict):
        raise DropAssessmentConfigError(f"{target}: parameters missing")

    def entry(name: str) -> Any:
        e = params.get(name)
        if not isinstance(e, dict) or "value" not in e:
            raise DropAssessmentConfigError(f"{target}: {name} missing")
        if e.get("class") != "PRIOR":
            raise DropAssessmentConfigError(f"{target}: {name} must be declared class PRIOR")
        if not str(e.get("rationale") or "").strip():
            raise DropAssessmentConfigError(f"{target}: {name} has no rationale")
        return e["value"]

    def number(name: str, lo: float, hi: float) -> float:
        v = _num(entry(name))
        if v is None or not lo <= v <= hi:
            raise DropAssessmentConfigError(f"{target}: {name} missing or out of range")
        return v

    def flags(name: str) -> frozenset[str]:
        v = entry(name)
        if not isinstance(v, list) or not all(isinstance(f, str) for f in v):
            raise DropAssessmentConfigError(f"{target}: {name} must be a list of flag codes")
        unknown = set(v) - KNOWN_FLAGS
        if unknown:
            raise DropAssessmentConfigError(
                f"{target}: {name} names unknown flags {sorted(unknown)}"
            )
        return frozenset(v)

    churn = entry("churnGapMaxByConfidence")
    if not isinstance(churn, dict) or not churn:
        raise DropAssessmentConfigError(f"{target}: churnGapMaxByConfidence must be a map")
    churn_map: dict[str, float] = {}
    for bucket, v in churn.items():
        fv = _num(v)
        if fv is None or not -2.0 < fv < 2.0:
            raise DropAssessmentConfigError(f"{target}: churnGapMaxByConfidence.{bucket} invalid")
        churn_map[str(bucket)] = fv

    protect = number("protectGapMin", -2.0, 2.0)
    clearly_below = number("clearlyBelowGapMax", -2.0, 2.0)
    if not clearly_below < 0.0 < protect:
        raise DropAssessmentConfigError(f"{target}: need clearlyBelowGapMax < 0 < protectGapMin")
    if any(v >= protect for v in churn_map.values()):
        raise DropAssessmentConfigError(f"{target}: every churn gap must be below protectGapMin")

    protecting = flags("protectingFlags")
    blocking = flags("churnBlockingFlags")
    if protecting & blocking:
        raise DropAssessmentConfigError(f"{target}: a flag cannot both protect and block churn")

    return ProtectionConfig(
        version=version,
        sha256=hashlib.sha256(raw).hexdigest(),
        path=str(target),
        churn_gap_max_by_confidence=churn_map,
        protect_gap_min=protect,
        clearly_below_gap_max=clearly_below,
        young_age_max=number("youngAgeMax", 0, 60),
        rising_snap_trend_min_pts=number("risingSnapTrendMinPts", 0.0, 100.0),
        min_games_for_trend=int(number("minGamesForTrend", 1, 30)),
        established_snap_pct_min=number("establishedSnapPctMin", 0.0, 100.0),
        no_usage_snap_pct_max=number("noUsageSnapPctMax", 0.0, 100.0),
        high_draft_capital_max_overall=int(number("highDraftCapitalMaxOverall", 1, 400)),
        recent_draft_max_years_exp=int(number("recentDraftMaxYearsExp", 0, 30)),
        value_trend_window_days=int(number("valueTrendWindowDays", 1, 365)),
        value_trend_up_min_ratio=number("valueTrendUpMinRatio", 0.0, 10.0),
        trend_max_observation_age_days=int(number("trendMaxObservationAgeDays", 0, 365)),
        usage_snapshot_max_age_days=number("usageSnapshotMaxAgeDays", 0.0, 365.0),
        protecting_flags=protecting,
        churn_blocking_flags=blocking,
    )


# ── Public contract ──────────────────────────────────────────────────


@dataclass(frozen=True)
class DropReason:
    code: str
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "evidence": dict(self.evidence)}


@dataclass(frozen=True)
class DynastyDropAssessment:
    player_id: str
    name: str
    #: Position family: DL / LB / DB / QB / RB / WR / TE / K ("" when unknown).
    position: str
    drop_class: str
    #: ``rankDerivedValue``; ``None`` when the board did not price him.
    dynasty_value: float | None
    #: Waiver level at his position (best equivalent free agent); ``None`` when
    #: no free agent at the position is priced.
    replacement_value: float | None
    #: ``dynasty_value - replacement_value`` (signed); ``None`` when either is.
    value_above_replacement: float | None
    #: Dynasty value lost by releasing him: ``max(0, value_above_replacement)``
    #: via the displacement owner; the full ``dynasty_value`` when replacement
    #: is unknown; ``None`` when unpriced.
    dynasty_cost: float | None
    confidence: str | None
    reasons: tuple[DropReason, ...]
    inputs: Mapping[str, Mapping[str, Any]]
    locks: tuple[Mapping[str, Any], ...]
    development_flags: tuple[str, ...]
    #: ``weekly_starter`` / ``bench`` when the caller supplied lineup
    #: membership, else ``unknown``.
    roster_role: str
    recovery_risk: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "name": self.name,
            "position": self.position,
            "dropClass": self.drop_class,
            "dynastyValue": _r(self.dynasty_value),
            "replacementValue": _r(self.replacement_value),
            "valueAboveReplacement": _r(self.value_above_replacement),
            "dynastyCost": _r(self.dynasty_cost),
            "valueScale": "rankDerivedValue",
            "confidence": self.confidence,
            "reasons": [r.to_dict() for r in self.reasons],
            "inputs": {k: dict(v) for k, v in self.inputs.items()},
            "locks": [dict(lock) for lock in self.locks],
            "developmentFlags": list(self.development_flags),
            "rosterRole": self.roster_role,
            "recoveryRisk": dict(self.recovery_risk),
        }


@dataclass(frozen=True)
class TeamDropAssessment:
    league_key: str
    team: Mapping[str, Any]
    assessments: tuple[DynastyDropAssessment, ...]
    summary: Mapping[str, Any]
    config: ProtectionConfig
    as_of: str
    replacement_values: Mapping[str, float]
    waiver_population: Mapping[str, Any]
    notes: tuple[str, ...] = ()

    def by_player_id(self) -> dict[str, DynastyDropAssessment]:
        return {a.player_id: a for a in self.assessments}

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": ASSESSMENT_CONTRACT_VERSION,
            "leagueKey": self.league_key,
            "team": dict(self.team),
            "asOf": self.as_of,
            "configVersion": self.config.version,
            "configHash": self.config.sha256,
            "valueScale": "rankDerivedValue",
            "replacementValues": dict(self.replacement_values),
            "waiverPopulation": dict(self.waiver_population),
            "summary": dict(self.summary),
            "assessments": [a.to_dict() for a in self.assessments],
            "notes": list(self.notes),
        }


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)


def _input(state: str, value: Any = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"state": state, "value": value}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


# ── Input readers (consume owners, never re-derive) ──────────────────


def _parse_instant(stamp: Any) -> datetime | None:
    s = str(stamp or "").strip()
    if not s:
        return None
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class _UsageIndex:
    """playerctx snapshot → per-player snap / depth record, with freshness."""

    def __init__(self, snapshot: Mapping[str, Any] | None, now: datetime, cfg: ProtectionConfig):
        self.snapshot = snapshot if isinstance(snapshot, Mapping) else None
        self.state = STATE_UNAVAILABLE
        self.reason: str | None = "no_playerctx_snapshot"
        self.as_of: str | None = None
        if self.snapshot is None:
            return
        stamp = self.snapshot.get("asOf") or self.snapshot.get("generatedAt")
        instant = _parse_instant(stamp)
        self.as_of = str(stamp) if stamp else None
        if instant is None:
            # An undated snapshot cannot prove it is current.
            self.state, self.reason = STATE_STALE, "playerctx_snapshot_undated"
            return
        age_days = (now - instant).total_seconds() / 86400.0
        if age_days > cfg.usage_snapshot_max_age_days:
            self.state, self.reason = STATE_STALE, f"playerctx_snapshot_{age_days:.1f}_days_old"
            return
        self.state, self.reason = STATE_AVAILABLE, None

    def record(self, player_id: str) -> Mapping[str, Any] | None:
        if self.snapshot is None:
            return None
        index = self.snapshot.get("sleeperIndex") or {}
        players = self.snapshot.get("players") or {}
        key = index.get(str(player_id)) if isinstance(index, Mapping) else None
        rec = players.get(key) if key is not None and isinstance(players, Mapping) else None
        return rec if isinstance(rec, Mapping) else None


def _default_playerctx() -> Mapping[str, Any] | None:
    from src.playerctx.service import load_playerctx  # noqa: PLC0415

    return load_playerctx()


def _default_draft_rows() -> list[Mapping[str, Any]]:
    """The CACHED nflverse id map — never a network fetch on a request path
    (``cache_only=True``).  Empty when nothing is materialised."""
    try:
        from src.nfl_data import ingest  # noqa: PLC0415

        return list(ingest.fetch_id_map(cache_only=True) or [])
    except Exception:  # noqa: BLE001 - unavailable input, stated per player
        return []


def _opt_pick(v: Any) -> int | None:
    try:
        n = int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


class _DraftIndex:
    """Draft capital from the nflverse id map, joined EXACTLY when possible.

    1. ``gsis`` — the playerctx record carries the player's GSIS id (its own
       Sleeper→GSIS join), and the id map is keyed by ``gsis_id``: an exact
       identity join.
    2. ``name_guarded`` — otherwise ``src/bdvm/context.py::build_player_context``
       (keyed by normalised NAME, last row wins on a collision) behind an
       identity guard: the record must agree with the board row on position
       family and on career length.  Measured on the 2026-10-29 board, the name
       map alone returns a CB for one star WR and an LB for another; the guard
       refuses both.
    """

    def __init__(self, rows: Iterable[Mapping[str, Any]] | None):
        rows = [r for r in (rows or []) if isinstance(r, Mapping)]
        self.available = bool(rows)
        self.by_gsis = {str(r.get("gsis_id")): r for r in rows if r.get("gsis_id")}
        self.by_name: Mapping[str, Any] = {}
        if rows:
            from src.bdvm.context import build_player_context  # noqa: PLC0415

            self.by_name = build_player_context(
                id_map_rows=rows, name_normalizer=normalize_player_name
            )

    def lookup(
        self,
        row: Mapping[str, Any],
        family: str,
        gsis: str | None,
        season_ref: int,
    ) -> dict[str, Any]:
        from src.bdvm.context import draft_capital_score  # noqa: PLC0415

        if not self.available:
            return _input(STATE_UNAVAILABLE, reason="no_draft_capital_data")
        exact = self.by_gsis.get(str(gsis)) if gsis else None
        if exact is not None:
            overall = _opt_pick(exact.get("draft_pick"))
            draft_year = _opt_pick(exact.get("draft_year"))
            join = "gsis"
        else:
            name = row.get("canonicalName") or row.get("displayName") or ""
            ctx = self.by_name.get(normalize_player_name(str(name))) if name else None
            if ctx is None:
                return _input(STATE_UNAVAILABLE, reason="no_draft_record")
            refusal = _name_identity_refusal(ctx, row, family, season_ref)
            if refusal:
                return _input(STATE_UNAVAILABLE, reason=refusal)
            overall = getattr(ctx, "draft_overall", None)
            draft_year = getattr(ctx, "draft_year", None)
            join = "name_guarded"
        return _input(
            STATE_AVAILABLE,
            overall,
            draftYear=draft_year,
            draftCapitalScore=round(draft_capital_score(overall), 3),
            undrafted=overall is None,
            identityJoin=join,
            source="nflverse id map (cache only); score src/bdvm/context.py::draft_capital_score",
        )


def _name_identity_refusal(
    ctx: Any, row: Mapping[str, Any], family: str, season_ref: int
) -> str | None:
    ctx_family = _TRUE_POSITION_FAMILY.get(str(getattr(ctx, "true_position", "") or ""))
    if ctx_family is None or not family:
        return "identity_unconfirmed_position_unknown"
    years_exp = row.get("yearsExp")
    rookie_season = getattr(ctx, "rookie_season", None)
    career_known = isinstance(years_exp, int) and isinstance(rookie_season, int)
    if career_known and abs((season_ref - rookie_season) - years_exp) > 1:
        return "identity_unconfirmed_career_length_mismatch"
    if ctx_family == family:
        return None
    # Sleeper and nflverse list edge / hybrid defenders differently (a Sleeper
    # DL is often an nflverse LB), so a cross-family IDP listing is accepted
    # only when the career length independently agrees.
    if ctx_family in _IDP_FAMILIES and family in _IDP_FAMILIES and career_known:
        return None
    return "identity_unconfirmed_position_mismatch"


def _trend_input(
    player_id: str,
    current: float | None,
    days: int,
    on: date,
    cfg: ProtectionConfig,
    ledger_path: Path | None,
    ledger_present: bool,
) -> dict[str, Any]:
    if current is None:
        return _input(STATE_UNAVAILABLE, reason="no_current_value")
    if not ledger_present:
        return _input(STATE_UNAVAILABLE, reason="temporal_ledger_absent")
    if not player_id or not str(player_id).isdigit():
        return _input(STATE_UNAVAILABLE, reason="no_platform_player_id")
    from src.history.asof import value_as_of  # noqa: PLC0415

    target = on - timedelta(days=days)
    res = value_as_of(
        f"player:{player_id}",
        target,
        max_age_days=cfg.trend_max_observation_age_days,
        path=ledger_path,
    )
    past = res.get("value")
    if not isinstance(past, (int, float)) or isinstance(past, bool) or past <= 0:
        return _input(
            STATE_UNAVAILABLE,
            reason=str(res.get("missingReason") or "no_positive_past_value"),
            requestedDate=target.isoformat(),
        )
    return _input(
        STATE_AVAILABLE,
        round((float(current) - float(past)) / float(past), 4),
        pastValue=float(past),
        observedDate=res.get("observedDate"),
        fidelity=res.get("fidelity"),
        requestedDate=target.isoformat(),
        source="src/history/asof.py canonical_board",
    )


# ── Classification ───────────────────────────────────────────────────


def _usage_inputs(
    rec: Mapping[str, Any] | None, usage: _UsageIndex
) -> tuple[dict[str, Any], dict[str, Any]]:
    if usage.state != STATE_AVAILABLE:
        bad = _input(usage.state, reason=usage.reason, snapshotAsOf=usage.as_of)
        return bad, dict(bad)
    snaps = rec.get("snaps") if rec else None
    depth = rec.get("depth") if rec else None
    if isinstance(snaps, Mapping):
        snap_in = _input(
            STATE_AVAILABLE,
            {
                "season": snaps.get("season"),
                "games": snaps.get("games"),
                "side": snaps.get("side"),
                "pct": snaps.get("pct"),
                "recentPct": snaps.get("recentPct"),
                "trend": snaps.get("trend"),
            },
            snapshotAsOf=usage.as_of,
            source="playerctx snaps",
        )
    else:
        snap_in = _input(
            STATE_UNAVAILABLE,
            reason="no_snap_record (absent is not zero usage)",
            snapshotAsOf=usage.as_of,
        )
    if isinstance(depth, Mapping):
        depth_in = _input(
            STATE_AVAILABLE,
            {"rank": depth.get("rank"), "depthPosition": depth.get("depthPosition")},
            snapshotAsOf=usage.as_of,
            source="playerctx depth",
        )
    else:
        depth_in = _input(STATE_UNAVAILABLE, reason="no_depth_record", snapshotAsOf=usage.as_of)
    return snap_in, depth_in


def _gap(v: float, w: float) -> float:
    mean = (v + w) / 2.0
    return (v - w) / mean if mean > 0 else 0.0


def _assess_one(
    asset: RosterAsset,
    row: Mapping[str, Any] | None,
    *,
    cfg: ProtectionConfig,
    waiver_values: Mapping[str, float],
    lock_reason: str | None,
    usage: _UsageIndex,
    draft_index: _DraftIndex,
    season_ref: int,
    weekly_starters: frozenset[str] | None,
    injury_status: Mapping[str, Any] | None,
    lineup_required: frozenset[str],
    on: date,
    ledger_path: Path | None,
    ledger_present: bool,
) -> DynastyDropAssessment:
    row = row or {}
    family = normalize_position_family(asset.position) if asset.position else ""
    value = (
        float(asset.board_value)
        if isinstance(asset.board_value, (int, float)) and asset.board_value > 0
        else None
    )
    confidence = row.get("confidenceBucket") if row else None
    quarantined = bool(row.get("quarantined")) if row else False
    replacement = waiver_values.get(asset.position) if asset.position else None
    replacement = float(replacement) if isinstance(replacement, (int, float)) else None

    var: float | None = None
    gap: float | None = None
    if value is not None and replacement is not None:
        var = value - replacement
        gap = _gap(value, replacement)
        # The displacement owner's cost, scarcity inert: max(0, V - W).
        cost: float | None = effective_cut_cost(asset, {asset.position: replacement})[0]
    elif value is not None:
        cost = value  # replacement unknown: charge the full board value
    else:
        cost = None

    age = row.get("age") if isinstance(row.get("age"), (int, float)) else None
    years_exp = row.get("yearsExp") if isinstance(row.get("yearsExp"), int) else None
    rec = usage.record(asset.player_id)
    snap_in, depth_in = _usage_inputs(rec, usage)
    gsis = (rec or {}).get("gsisId") if usage.snapshot is not None else None
    draft_in = (
        draft_index.lookup(row, family, str(gsis) if gsis else None, season_ref)
        if row
        else _input(STATE_UNAVAILABLE, reason="not_on_board")
    )
    trend30 = _trend_input(
        asset.player_id, value, cfg.value_trend_window_days, on, cfg, ledger_path, ledger_present
    )
    trend60 = _trend_input(
        asset.player_id,
        value,
        2 * cfg.value_trend_window_days,
        on,
        cfg,
        ledger_path,
        ledger_present,
    )
    if weekly_starters is None:
        role = "unknown"
        role_in = _input(STATE_NOT_SUPPLIED, reason="caller_did_not_supply_weekly_lineup")
    else:
        role = "weekly_starter" if asset.player_id in weekly_starters else "bench"
        role_in = _input(STATE_AVAILABLE, role, source="caller")
    if injury_status is None:
        injury_in = _input(STATE_NOT_SUPPLIED, reason="no_injury_feed_supplied")
    elif asset.player_id in injury_status:
        injury_in = _input(STATE_AVAILABLE, injury_status[asset.player_id], source="caller")
    else:
        injury_in = _input(STATE_AVAILABLE, None, note="no_injury_listed", source="caller")

    inputs: dict[str, dict[str, Any]] = {
        "dynastyValue": (
            _input(STATE_AVAILABLE, value, source="rankDerivedValue")
            if value is not None
            else _input(STATE_UNAVAILABLE, reason="unpriced_by_board")
        ),
        "confidence": _input(
            STATE_AVAILABLE if confidence else STATE_UNAVAILABLE,
            confidence,
            retainedAuthority=row.get("retainedAuthority") if row else None,
            quarantined=quarantined or None,
        ),
        "replacementLevel": (
            _input(STATE_AVAILABLE, replacement, source="team_droppability.waiverValues")
            if replacement is not None
            else _input(STATE_UNAVAILABLE, reason="no_priced_free_agent_at_position")
        ),
        "age": _input(STATE_AVAILABLE, age) if age is not None else _input(STATE_UNAVAILABLE),
        "yearsExp": (
            _input(STATE_AVAILABLE, years_exp, rookie=years_exp == 0)
            if years_exp is not None
            else _input(STATE_UNAVAILABLE)
        ),
        "draftCapital": draft_in,
        "snapUsage": snap_in,
        "depthChart": depth_in,
        "injury": injury_in,
        "valueTrend30d": trend30,
        "valueTrend60d": trend60,
        "weeklyRole": role_in,
        "lineupRequiredAlone": _input(
            STATE_AVAILABLE,
            asset.player_id in lineup_required,
            source="cut ladder undroppable (releasing him alone empties a starting slot)",
        ),
    }

    # ── Development flags ──
    flags: list[str] = []
    snaps = snap_in.get("value") if snap_in["state"] == STATE_AVAILABLE else None
    young = age is not None and age <= cfg.young_age_max
    if age is None:
        flags.append(FLAG_AGE_UNKNOWN)
    if young:
        if snaps is None:
            flags.append(FLAG_YOUNG_USAGE_UNKNOWN)
        else:
            games = snaps.get("games")
            trend = _num(snaps.get("trend"))
            pct = _num(snaps.get("pct"))
            if (
                trend is not None
                and isinstance(games, (int, float))
                and games >= cfg.min_games_for_trend
                and trend >= cfg.rising_snap_trend_min_pts
            ):
                flags.append(FLAG_YOUNG_RISING)
            if pct is not None and pct >= cfg.established_snap_pct_min:
                flags.append(FLAG_YOUNG_ESTABLISHED)
    if years_exp is not None and years_exp <= cfg.recent_draft_max_years_exp:
        if draft_in["state"] != STATE_AVAILABLE:
            flags.append(FLAG_RECENT_DRAFT_UNKNOWN)
        elif (
            isinstance(draft_in.get("value"), int)
            and draft_in["value"] <= cfg.high_draft_capital_max_overall
        ):
            flags.append(FLAG_HIGH_DRAFT_RECENT)
    t30 = trend30.get("value") if trend30["state"] == STATE_AVAILABLE else None
    if isinstance(t30, (int, float)) and t30 >= cfg.value_trend_up_min_ratio:
        flags.append(FLAG_VALUE_TRENDING_UP)
    flags = sorted(set(flags))

    observed_no_usage = (
        snaps is not None
        and _num(snaps.get("pct")) is not None
        and _num(snaps.get("recentPct")) is not None
        and float(snaps["pct"]) <= cfg.no_usage_snap_pct_max
        and float(snaps["recentPct"]) <= cfg.no_usage_snap_pct_max
    )

    # ── Classification, in strict priority order ──
    reasons: list[DropReason] = []
    locks: list[dict[str, Any]] = []
    value_ev = {"dynastyValue": _r(value), "replacementValue": _r(replacement), "gap": gap}
    if lock_reason is not None:
        locks.append({"reason": lock_reason, "source": "src/trade/constraints.py"})
        cls = CLASS_PROTECTED
        reasons.append(
            DropReason("user_lock", "user protection is absolute", {"blockReason": lock_reason})
        )
    elif value is None:
        cls = CLASS_PROTECTED
        reasons.append(
            DropReason(
                "unpriced_never_auto_drop",
                "the board did not price him; an unknown value is never treated as cheap",
                {"onBoard": asset.on_board},
            )
        )
    elif quarantined:
        cls = CLASS_PROTECTED
        reasons.append(
            DropReason(
                "value_quarantined_never_auto_drop",
                "his value failed an integrity check and is not an ordinary canonical number",
                {"anomalyFlags": list(row.get("anomalyFlags") or [])},
            )
        )
    elif gap is None:
        cls = CLASS_CONDITIONAL
        reasons.append(
            DropReason(
                "replacement_level_unavailable",
                "no priced free agent at his position; releasing him is charged full board value",
                value_ev,
            )
        )
    elif gap >= cfg.protect_gap_min:
        cls = CLASS_PROTECTED
        reasons.append(
            DropReason(
                "meaningful_dynasty_asset",
                "value is well above the best free agent at his position",
                {**value_ev, "protectGapMin": cfg.protect_gap_min},
            )
        )
    elif protecting := [f for f in flags if f in cfg.protecting_flags]:
        if gap <= cfg.clearly_below_gap_max and observed_no_usage:
            cls = CLASS_CONDITIONAL
            reasons.append(
                DropReason(
                    "development_flag_overridden_no_usage",
                    "development flag, but clearly below replacement and observed with no usage",
                    {**value_ev, "flags": protecting, "snaps": snaps},
                )
            )
        else:
            cls = CLASS_PROTECTED
            reasons.append(
                DropReason(
                    "development_upside",
                    "development evidence protects him despite a value near replacement",
                    {**value_ev, "flags": protecting},
                )
            )
    else:
        churn_max = cfg.churn_gap_max_by_confidence.get(str(confidence or ""))
        blockers = [f for f in flags if f in cfg.churn_blocking_flags]
        if churn_max is None:
            cls = CLASS_CONDITIONAL
            reasons.append(
                DropReason(
                    "confidence_not_churn_eligible",
                    "his value's confidence bucket admits no zero-cost release",
                    {**value_ev, "confidence": confidence},
                )
            )
        elif gap > churn_max:
            cls = CLASS_CONDITIONAL
            reasons.append(
                DropReason(
                    "above_replacement_band",
                    "worth measurably more than the best free agent at his position",
                    {**value_ev, "churnGapMax": churn_max, "confidence": confidence},
                )
            )
        elif blockers:
            cls = CLASS_CONDITIONAL
            reasons.append(
                DropReason(
                    "churn_blocked_by_signal",
                    "replaceable on value, but an unknown or rising signal makes a free release unsafe",
                    {**value_ev, "flags": blockers},
                )
            )
        elif role == "weekly_starter":
            cls = CLASS_CONDITIONAL
            reasons.append(
                DropReason(
                    "weekly_starter",
                    "replaceable on value, but the caller's weekly lineup starts him",
                    value_ev,
                )
            )
        else:
            cls = CLASS_CHURN
            reasons.append(
                DropReason(
                    "replaceable_by_free_agent",
                    "at or within the agreement band of the best free agent at his position",
                    {**value_ev, "churnGapMax": churn_max, "confidence": confidence},
                )
            )

    return DynastyDropAssessment(
        player_id=asset.player_id,
        name=asset.name,
        position=family,
        drop_class=cls,
        dynasty_value=value,
        replacement_value=replacement,
        value_above_replacement=var,
        dynasty_cost=cost,
        confidence=str(confidence) if confidence else None,
        reasons=tuple(reasons),
        inputs=inputs,
        locks=tuple(locks),
        development_flags=tuple(flags),
        roster_role=role,
        recovery_risk=dict(RECOVERY_RISK_UNMEASURED),
    )


# ── Entry point ──────────────────────────────────────────────────────


def assess_team_drops(
    contract: Mapping[str, Any],
    *,
    league_key: str,
    owner_id: str | None = None,
    roster_id: Any = None,
    team_name: str | None = None,
    constraints: Any = None,
    weekly_starter_ids: Collection[str] | None = None,
    config_path: Path | str | None = None,
    now: datetime | None = None,
    player_context_snapshot: Any = _DEFAULT,
    draft_rows: Any = _DEFAULT,
    history_path: Path | None = None,
    injury_status: Mapping[str, Any] | None = None,
    unavailable_keys: Iterable[str] | None = None,
) -> TeamDropAssessment:
    """Assess every player on one team's roster.

    ``constraints`` is a resolved :class:`src.trade.constraints.TradeConstraints`;
    a ``resolution_failed`` set protects EVERY player (fail closed).  ``None``
    means the caller supplied none and is stamped ``not_supplied`` — a route
    must pass the user's resolved constraints.

    ``player_context_snapshot`` / ``draft_rows`` default to the on-disk
    owners (playerctx snapshot; cached nflverse id map).  Passing ``None``
    states the input is unavailable.  Raises :class:`TeamNotInLeague` when the
    team cannot be resolved and :class:`DropAssessmentConfigError` when the
    PRIORs cannot be read.
    """
    cfg = load_protection_config(config_path)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    meta_key = str(((contract or {}).get("meta") or {}).get("leagueKey") or "")
    if meta_key and league_key and meta_key != league_key:
        raise ValueError(f"league_mismatch: contract is {meta_key}, request is {league_key}")

    teams = contract_teams(contract)
    if not teams:
        raise TeamNotInLeague("no_rosters_loaded")
    team = match_team(teams, owner_id=owner_id, roster_id=roster_id, team_name=team_name)
    if team is None:
        raise TeamNotInLeague(str(owner_id or roster_id or team_name or ""))
    # Same resolution order as ``match_team``, so the ladder is this team's.
    drop = team_droppability(
        contract,
        owner_id=str(team.get("ownerId") or "") or None,
        roster_id=team.get("roster_id"),
        team_name=str(team.get("name") or "") or None,
        unavailable_keys=unavailable_keys,
    )
    waiver_values = {str(k): float(v) for k, v in (drop.get("waiverValues") or {}).items()}
    lineup_required = frozenset(
        str(u.get("playerId")) for u in (drop.get("cutLadder") or {}).get("undroppable") or []
    )

    by_id, by_name = index_contract_rows(contract)
    assets, unmatched = build_roster_assets(team, by_name, by_id)

    if player_context_snapshot is _DEFAULT:
        player_context_snapshot = _default_playerctx()
    if draft_rows is _DEFAULT:
        draft_rows = _default_draft_rows()
    draft_index = _DraftIndex(draft_rows)
    usage = _UsageIndex(player_context_snapshot, now, cfg)

    from src.bdvm.actuals import nfl_projection_season  # noqa: PLC0415
    from src.history import store as history_store  # noqa: PLC0415

    season_ref = nfl_projection_season(now.date())
    ledger = Path(history_path) if history_path is not None else history_store.DB_PATH
    ledger_present = ledger.is_file()
    starters = (
        frozenset(str(x) for x in weekly_starter_ids) if weekly_starter_ids is not None else None
    )

    notes: list[str] = []
    resolution_failed = bool(getattr(constraints, "resolution_failed", False))
    if constraints is None:
        notes.append("no user constraints supplied — locks state not_supplied")
    if resolution_failed:
        notes.append("user protections could not be resolved — every player is protected")
    if unmatched:
        notes.append(
            f"{len(unmatched)} rostered player(s) did not join to the board — unpriced, protected"
        )

    out: list[DynastyDropAssessment] = []
    for asset in assets:
        row = by_id.get(str(asset.player_id).strip().lower()) if asset.on_board else None
        if row is None and asset.on_board:
            # The join keyed this asset by name only because its row carries no
            # playerId; a name hit that DOES carry one is another player.
            named = by_name.get(str(asset.name).strip().lower())
            row = named if named is not None and not named.get("playerId") else None
        lock_reason = None
        if constraints is not None:
            lock_reason = constraints.block_reason(
                {
                    "name": asset.name,
                    "playerId": asset.player_id,
                    "position": asset.position,
                    "team": (row or {}).get("team"),
                }
            )
        out.append(
            _assess_one(
                asset,
                row,
                cfg=cfg,
                waiver_values=waiver_values,
                lock_reason=lock_reason,
                usage=usage,
                draft_index=draft_index,
                season_ref=season_ref,
                weekly_starters=starters,
                injury_status=injury_status,
                lineup_required=lineup_required,
                on=now.date(),
                ledger_path=ledger,
                ledger_present=ledger_present,
            )
        )
    out.sort(key=lambda a: (a.player_id, a.name))

    counts = {c: sum(1 for a in out if a.drop_class == c) for c in _CLASSES}
    coverage: dict[str, dict[str, int]] = {}
    for a in out:
        for name, inp in a.inputs.items():
            bucket = coverage.setdefault(name, {})
            bucket[inp["state"]] = bucket.get(inp["state"], 0) + 1
    summary = {
        "rosterPlayers": len(out),
        "counts": counts,
        "unpriced": sum(1 for a in out if a.dynasty_value is None),
        "locked": sum(1 for a in out if a.locks),
        "locksState": (
            "unresolved"
            if resolution_failed
            else ("not_supplied" if constraints is None else "resolved")
        ),
        "weeklyRoleState": STATE_NOT_SUPPLIED if starters is None else STATE_AVAILABLE,
        "usageSnapshot": {"state": usage.state, "asOf": usage.as_of, "reason": usage.reason},
        "temporalLedger": "present" if ledger_present else "absent",
        "draftCapitalSource": "available" if draft_index.available else "unavailable",
        "inputCoverage": coverage,
        "recoveryRisk": RECOVERY_RISK_UNMEASURED["state"],
    }
    return TeamDropAssessment(
        league_key=league_key,
        team={
            "ownerId": str(team.get("ownerId") or ""),
            "rosterId": team.get("roster_id"),
            "teamName": str(team.get("name") or ""),
        },
        assessments=tuple(out),
        summary=summary,
        config=cfg,
        as_of=now.isoformat(),
        replacement_values={k: round(v, 1) for k, v in sorted(waiver_values.items())},
        waiver_population=dict(drop.get("waiverPopulation") or {}),
        notes=tuple(notes),
    )
