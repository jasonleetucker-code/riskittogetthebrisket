"""Automated rookie-class readiness and policy-driven promotion (Batch D).

Owner decision 12 (2026-10-18): "Approve Draft Valuation Batch D with your
recommended thresholds."  The thresholds were preregistered before any
candidate was evaluated — ``docs/draft/BATCH_D_PREREGISTRATION_2026-10-18.md``
and ``config/draft_valuation/promotion_policy.json`` (thresholds checksummed;
:func:`load_promotion_policy` refuses an edited copy).

This module is the policy-driven promotion path that ``readiness.py``'s own
comment reserves: ``readiness`` stays the report-only STRUCTURAL half
(``PROMOTION_ENABLED`` stays ``False`` there); this module evaluates the
policy gates on top of it and owns the live / dry-run switch.

States (``dynasty_main`` only)::

    FALLBACK_VERIFIED -> CANDIDATE_INCOMPLETE -> CANDIDATE_READY
        -> VALIDATED (freshness + stability) -> PROMOTABLE (review band passed)
        -> ACTIVE
    + VALIDATED_NEEDS_REVIEW, ERROR_*, ROLLED_BACK, LEAGUE_NOT_CONFIGURED

Three quantities are reported separately and never conflated:

``evaluationState``
    what THIS run's candidate earned (the pipeline above, or an ERROR_*).
``servingState``
    what the class serves: ``FALLBACK`` (the resolver's default rule — the
    frozen-fallback / workbook allocation), ``ACTIVE`` (a promoted
    generation) or ``ROLLED_BACK`` (held after an operator rollback).
``state``
    the headline: an error or ``LEAGUE_NOT_CONFIGURED`` if any, else
    ``ACTIVE`` / ``ROLLED_BACK`` when serving one, else ``evaluationState``.

Guarantees:

* Before ``nflDraftCompleteOn[Y]`` no class-Y candidate is built at all; the
  state is ``FALLBACK_VERIFIED`` with the reason named.
* Every failure keeps the previous generation: only
  ``published.publish_promoted_generation`` switches, and only after the
  candidate re-verifies; any exception leaves the old pointer in force.
* ``promotionMode: dry_run`` computes, records and alerts but never switches
  (no allocation, no pointer, no ledger write).
* One alert per state transition: transitions are create-only,
  sequence-numbered records; an alert is emitted only when a NEW transition
  record is created, so a persistent state never re-alerts.
* MISSING IS NEVER ZERO: an unknown contract age, health, confidence or
  draft status fails its gate; it never passes by default.

Storage (decision 12 item 7): everything here is written create-only and
checksummed under the repo-tracked ``config/draft_valuation/`` —
``readiness_evaluations/``, ``promotion_transitions/``, ``class_snapshots/``,
plus ``published.py``'s ``promoted_allocations/`` and ``promotion_pointers/``
— and committed by the scheduled refresh workflow.
"""

from __future__ import annotations

import json
import os
import statistics
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.draft.rookie_auction import published
from src.draft.rookie_auction.class_snapshot import (
    RookieClassSnapshot,
    SnapshotRecordError,
    build_class_candidate,
    frozen_fallback_snapshot,
    load_class_snapshot,
    row_identity,
)
from src.draft.rookie_auction.league_scope import LeagueNotConfiguredError, league_scope
from src.draft.rookie_auction.readiness import (
    FAIL,
    NOT_EVALUATED,
    PASS,
    POLICY_GATES,
    STATE_ERROR,
    STATE_FALLBACK,
    STATE_NOT_CONFIGURED,
    STATE_READY,
    GateResult,
    ReadinessReport,
    evaluate_class_readiness,
)
from src.draft.rookie_auction.snapshots import (
    CONFIG_DIR,
    SnapshotIntegrityError,
    available_completed_classes,
    canonical_checksum,
)
from src.identity.pick_lifecycle import (
    LIFECYCLE_ACTIVE,
    LeagueDraftEvidence,
    draft_class_lifecycle,
    is_retired,
)

__all__ = [
    "MODE_DRY_RUN",
    "MODE_LIVE",
    "POLICY_PATH",
    "PolicyError",
    "PromotionEvaluation",
    "PromotionPolicy",
    "RunOutcome",
    "class_window_gate",
    "diagnose",
    "finalize_completed_class_step",
    "load_evaluations",
    "load_promotion_policy",
    "operator_resume",
    "operator_rollback",
    "review_band_gate",
    "run_class_evaluation",
    "source_freshness_gate",
    "stability_gate",
]

POLICY_PATH = CONFIG_DIR / "promotion_policy.json"
POLICY_SCHEMA = "draft_valuation_promotion_policy_v1"
EVALUATION_SCHEMA = "draft_valuation_readiness_evaluation_v1"
TRANSITION_SCHEMA = "draft_valuation_promotion_transition_v1"
EVALUATION_DIR_NAME = "readiness_evaluations"
TRANSITION_DIR_NAME = "promotion_transitions"
CLASS_SNAPSHOT_DIR_NAME = "class_snapshots"

MODE_DRY_RUN = "dry_run"
MODE_LIVE = "live"

STATE_INCOMPLETE = "CANDIDATE_INCOMPLETE"
STATE_VALIDATED = "VALIDATED"
STATE_NEEDS_REVIEW = "VALIDATED_NEEDS_REVIEW"
STATE_PROMOTABLE = "PROMOTABLE"
STATE_ACTIVE = "ACTIVE"
STATE_ROLLED_BACK = "ROLLED_BACK"
STATE_ERROR_POLICY = "ERROR_POLICY_INVALID"
STATE_ERROR_CONTRACT = "ERROR_CONTRACT_UNAVAILABLE"
STATE_ERROR_STORE = "ERROR_STORE_INVALID"
STATE_ERROR_PUBLISH = "ERROR_PUBLISH_FAILED"

SERVING_FALLBACK = "FALLBACK"
SERVING_ACTIVE = "ACTIVE"
SERVING_ROLLED_BACK = "ROLLED_BACK"

DECISION_NONE = "none"
DECISION_HOLD = "hold"
DECISION_WOULD_PROMOTE = "would_promote"
DECISION_PROMOTED = "promoted"
DECISION_ALREADY_ACTIVE = "already_active"

GATE_WINDOW = "class_window_open"
GATE_FRESHNESS = "source_freshness"
GATE_STABILITY = "stability_vs_prior_generation"
GATE_REVIEW = "bounded_variation_vs_fallback"
GATE_FIRST_SWITCH = "first_switch_approval"

#: Structural gates readiness reports that mean nothing before a candidate
#: exists (the window is closed); they are omitted rather than shown FAIL.
_PRE_WINDOW_GATES = ("league_configured", "spine_available", "fallback_verified")


class PolicyError(ValueError):
    """The promotion policy file is missing, edited or malformed."""


# --- the policy -----------------------------------------------------------------


@dataclass(frozen=True)
class PromotionPolicy:
    version: str
    status: str
    mode: str
    league_key: str
    nfl_draft_complete_on: Mapping[int, date]
    contract_max_age_hours: int
    forbid_quarantined: bool
    require_positive_value: bool
    confidence_top_picks: int
    confidence_allowed: frozenset[str]
    stability_window_hours: int
    stability_max_gap_hours: int
    stability_pick_band_dollars: int
    stability_total_abs_change_dollars: int
    review_slot_abs_dollars: int
    review_slot_relative: Fraction
    review_first_round_picks: int
    review_first_round_relative: Fraction
    promotable_hold_hours: int
    includes_first_switch: bool
    thresholds_checksum: str

    @property
    def live(self) -> bool:
        return self.mode == MODE_LIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "promotionMode": self.mode,
            "leagueKey": self.league_key,
            "thresholdsChecksum": self.thresholds_checksum,
        }


def _req_int(obj: Mapping[str, Any], key: str, what: str) -> int:
    v = obj.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise PolicyError(f"{what}.{key} must be a positive integer, got {v!r}")
    return v


def _req_fraction(obj: Mapping[str, Any], key: str, what: str) -> Fraction:
    v = obj.get(key)
    if not isinstance(v, str):
        raise PolicyError(f"{what}.{key} must be a decimal string, got {v!r}")
    try:
        f = Fraction(v)
    except (ValueError, ZeroDivisionError) as exc:
        raise PolicyError(f"{what}.{key} unreadable: {v!r}") from exc
    if f <= 0:
        raise PolicyError(f"{what}.{key} must be positive")
    return f


def _req_true(obj: Mapping[str, Any], key: str, what: str) -> bool:
    if obj.get(key) is not True:
        raise PolicyError(f"{what}.{key} must be true")
    return True


def load_promotion_policy(path: Path | None = None) -> PromotionPolicy:
    """Load and verify the preregistered policy.  Raises :class:`PolicyError`."""
    from src.api.league_registry import SCORING_SNAPSHOT_MAX_AGE_HOURS  # noqa: PLC0415

    p = Path(path) if path is not None else POLICY_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError(f"policy unreadable: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != POLICY_SCHEMA:
        raise PolicyError("not a promotion policy")
    status = str(raw.get("status") or "")
    if not status.startswith("OWNER_APPROVED_"):
        raise PolicyError(f"policy is not owner-approved (status {status!r})")
    thresholds = raw.get("thresholds")
    if not isinstance(thresholds, dict):
        raise PolicyError("policy has no thresholds")
    recorded = (raw.get("thresholdsChecksum") or {}).get("value")
    # The thresholds object itself, exactly as the preregistration states.
    actual = _sha_json(thresholds)
    if recorded != actual:
        raise PolicyError("thresholds checksum mismatch — preregistered thresholds were edited")
    mode = raw.get("promotionMode")
    if mode not in (MODE_DRY_RUN, MODE_LIVE):
        raise PolicyError(f"promotionMode must be {MODE_DRY_RUN!r} or {MODE_LIVE!r}, got {mode!r}")
    try:
        league_scope(raw.get("leagueKey"))
    except LeagueNotConfiguredError as exc:
        raise PolicyError(str(exc)) from exc

    window = thresholds.get("classWindow") or {}
    dates: dict[int, date] = {}
    for y, d in (window.get("nflDraftCompleteOn") or {}).items():
        try:
            dates[int(y)] = date.fromisoformat(str(d))
        except ValueError as exc:
            raise PolicyError(f"classWindow.nflDraftCompleteOn[{y}] unreadable: {d!r}") from exc
    fr = thresholds.get("sourceFreshness") or {}
    if fr.get("requireContractHealthOk") is not True:
        raise PolicyError("sourceFreshness.requireContractHealthOk must be true")
    max_age = _req_int(fr, "contractMaxAgeHours", "sourceFreshness")
    if max_age != int(SCORING_SNAPSHOT_MAX_AGE_HOURS):
        raise PolicyError(
            f"sourceFreshness.contractMaxAgeHours {max_age} != the repo staleness budget "
            f"{SCORING_SNAPSHOT_MAX_AGE_HOURS} (SCRAPE_INTERVAL_HOURS x 3)"
        )
    allowed = fr.get("confidenceAllowedBuckets")
    if not isinstance(allowed, list) or not allowed or not all(isinstance(b, str) for b in allowed):
        raise PolicyError("sourceFreshness.confidenceAllowedBuckets must be a list of names")
    st = thresholds.get("stability") or {}
    rb = thresholds.get("reviewBand") or {}
    pr = thresholds.get("promotion") or {}
    return PromotionPolicy(
        version=str(raw.get("version") or ""),
        status=status,
        mode=mode,
        league_key=str(raw["leagueKey"]),
        nfl_draft_complete_on=dates,
        contract_max_age_hours=max_age,
        forbid_quarantined=_req_true(fr, "forbidQuarantinedEntries", "sourceFreshness"),
        require_positive_value=_req_true(fr, "requirePositiveRankDerivedValue", "sourceFreshness"),
        confidence_top_picks=_req_int(fr, "confidenceTopPicks", "sourceFreshness"),
        confidence_allowed=frozenset(allowed),
        stability_window_hours=_req_int(st, "windowHours", "stability"),
        stability_max_gap_hours=_req_int(st, "maxGapHours", "stability"),
        stability_pick_band_dollars=_req_int(st, "pickBandDollars", "stability"),
        stability_total_abs_change_dollars=_req_int(st, "totalAbsChangeDollars", "stability"),
        review_slot_abs_dollars=_req_int(rb, "slotAbsDollars", "reviewBand"),
        review_slot_relative=_req_fraction(rb, "slotRelativeOfFallback", "reviewBand"),
        review_first_round_picks=_req_int(rb, "firstRoundPicks", "reviewBand"),
        review_first_round_relative=_req_fraction(rb, "firstRoundTotalRelative", "reviewBand"),
        promotable_hold_hours=_req_int(pr, "promotableHoldHours", "promotion"),
        includes_first_switch=bool(pr.get("includesFirstSwitchFromFrozenFallback") is True),
        thresholds_checksum=actual,
    )


def _sha_json(obj: Any) -> str:
    import hashlib  # noqa: PLC0415

    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- time ---------------------------------------------------------------------------


def _ts(value: Any) -> datetime:
    ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return ts.astimezone(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat()


def _hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600.0


# --- gates ----------------------------------------------------------------------


def class_window_gate(policy: PromotionPolicy, draft_year: int, now: datetime) -> GateResult:
    opens = policy.nfl_draft_complete_on.get(int(draft_year))
    if opens is None:
        return GateResult(
            GATE_WINDOW,
            FAIL,
            f"nfl_draft_completion_date_not_configured:{draft_year} (policy classWindow)",
        )
    opens_at = datetime(opens.year, opens.month, opens.day, tzinfo=timezone.utc)
    if now < opens_at:
        return GateResult(
            GATE_WINDOW,
            FAIL,
            f"class_window_closed:opens {opens_at.isoformat()} (NFL Draft {draft_year} "
            "not yet complete per policy)",
        )
    return GateResult(GATE_WINDOW, PASS, f"opened {opens_at.isoformat()}")


def _contract_as_of(contract: Mapping[str, Any] | None) -> datetime | None:
    from src.api.data_contract import _payload_as_of  # noqa: PLC0415

    if not isinstance(contract, Mapping):
        return None
    as_of = _payload_as_of(contract)
    return as_of.astimezone(timezone.utc) if as_of is not None else None


def source_freshness_gate(
    candidate: RookieClassSnapshot,
    contract: Mapping[str, Any] | None,
    *,
    policy: PromotionPolicy,
    now: datetime,
) -> GateResult:
    """Decision 12 item 2 — every condition must hold; unknown fails."""
    failures: list[str] = []
    health = contract.get("contractHealth") if isinstance(contract, Mapping) else None
    if not isinstance(health, Mapping) or "ok" not in health:
        failures.append("contract_health_unknown")
    elif health.get("ok") is not True:
        failures.append(f"contract_health_not_ok:{health.get('status')}")
    as_of = _contract_as_of(contract)
    if as_of is None:
        failures.append("contract_as_of_unknown")
    else:
        age = _hours(now - as_of)
        if age < 0:
            failures.append(f"contract_as_of_in_future:{as_of.isoformat()}")
        elif age > policy.contract_max_age_hours:
            failures.append(f"contract_stale:{age:.2f}h>{policy.contract_max_age_hours}h")
    rows = contract.get("playersArray") if isinstance(contract, Mapping) else None
    by_id: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, Mapping) and str(row.get("assetClass") or "").lower() != "pick":
            rid = row_identity(row)
            if rid is not None:
                by_id.setdefault(rid, []).append(row)
    for entry in candidate.entries:
        found = by_id.get(entry.canonical_player_id or "", [])
        if len(found) != 1:
            failures.append(f"row_unresolved:{entry.canonical_player_id}:{len(found)}")
            continue
        row = found[0]
        if policy.forbid_quarantined and row.get("quarantined") is not False:
            # ``quarantined`` absent is unknown, not "not quarantined".
            failures.append(f"quarantined_or_unknown:{entry.canonical_player_id}")
        v = row.get("rankDerivedValue")
        if policy.require_positive_value and (
            isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0
        ):
            failures.append(f"no_positive_value:{entry.canonical_player_id}")
        if entry.rank <= policy.confidence_top_picks:
            bucket = row.get("confidenceBucket")
            if bucket not in policy.confidence_allowed:
                failures.append(f"confidence:{entry.canonical_player_id}={bucket}")
    if len(candidate.entries) != candidate.pick_count:
        failures.append(f"entries:{len(candidate.entries)}/{candidate.pick_count}")
    if failures:
        shown = failures[:12] + ([f"+{len(failures) - 12} more"] if len(failures) > 12 else [])
        return GateResult(GATE_FRESHNESS, FAIL, "; ".join(shown))
    return GateResult(
        GATE_FRESHNESS,
        PASS,
        f"contract healthy, {_hours(now - as_of):.2f}h old; 72 entries unquarantined and "
        f"positive; top {policy.confidence_top_picks} confidence "
        f"{sorted(policy.confidence_allowed)}",
    )


def review_band_gate(
    candidate_dollars: Sequence[int] | None,
    fallback_dollars: Sequence[int] | None,
    policy: PromotionPolicy,
) -> tuple[GateResult, dict[str, Any]]:
    """Decision 12 item 4 — slot-by-slot vs the frozen-fallback curve."""
    if not candidate_dollars or not fallback_dollars:
        return GateResult(GATE_REVIEW, NOT_EVALUATED, "whole dollars unavailable"), {}
    if len(candidate_dollars) != len(fallback_dollars):
        return GateResult(GATE_REVIEW, FAIL, "length mismatch vs fallback"), {}
    breaches = []
    for i, (c, f) in enumerate(zip(candidate_dollars, fallback_dollars)):
        band = max(Fraction(policy.review_slot_abs_dollars), policy.review_slot_relative * f)
        if abs(c - f) > band:
            breaches.append({"overall": i + 1, "candidate": c, "fallback": f, "band": str(band)})
    n1 = policy.review_first_round_picks
    c1, f1 = sum(candidate_dollars[:n1]), sum(fallback_dollars[:n1])
    first_round_rel = Fraction(abs(c1 - f1), f1) if f1 else None
    first_round_breach = (
        first_round_rel is None or first_round_rel > policy.review_first_round_relative
    )
    info = {
        "slotBreaches": breaches,
        "firstRound": {
            "candidateTotal": c1,
            "fallbackTotal": f1,
            "relativeDifference": None if first_round_rel is None else str(first_round_rel),
            "limit": str(policy.review_first_round_relative),
            "breach": first_round_breach,
        },
    }
    if breaches or first_round_breach:
        why = []
        if breaches:
            why.append(
                f"{len(breaches)} slot(s) outside max(${policy.review_slot_abs_dollars}, "
                f"{policy.review_slot_relative} x fallback)"
            )
        if first_round_breach:
            why.append(f"picks 1-{n1} total {c1} vs fallback {f1}")
        return GateResult(GATE_REVIEW, FAIL, "; ".join(why)), info
    return GateResult(GATE_REVIEW, PASS, "within the review band"), info


@dataclass(frozen=True)
class _Point:
    at: datetime
    eligible: bool  # structurally CANDIDATE_READY and source_freshness PASS
    identity_sha: str | None
    dollars: tuple[int, ...] | None
    evaluation_state: str


def _point_from_record(rec: Mapping[str, Any]) -> _Point:
    cand = rec.get("candidate") or {}
    d = cand.get("wholeDollars")
    return _Point(
        at=_ts(rec["evaluatedAt"]),
        eligible=bool(rec.get("structuralReady")) and bool(rec.get("freshnessPass")),
        identity_sha=cand.get("identitySetSha256"),
        dollars=tuple(d) if isinstance(d, list) else None,
        evaluation_state=str(rec.get("evaluationState")),
    )


def _trailing_run(
    points: Sequence[_Point], predicate: Callable[[_Point], bool], max_gap_h: float
) -> list[_Point]:
    """The longest contiguous suffix satisfying ``predicate`` with no gap > max_gap."""
    run: list[_Point] = []
    for p in reversed(points):
        if not predicate(p):
            break
        if run and _hours(run[-1].at - p.at) > max_gap_h:
            break
        run.append(p)
    run.reverse()
    return run


def stability_gate(
    history: Sequence[_Point], current: _Point, policy: PromotionPolicy
) -> tuple[GateResult, dict[str, Any]]:
    """Decision 12 item 3, over persisted evaluations plus the current one."""
    if not current.eligible or current.dollars is None:
        return (
            GateResult(GATE_STABILITY, NOT_EVALUATED, "current evaluation not ready and fresh"),
            {},
        )
    points = [p for p in history if p.at < current.at] + [current]
    run = _trailing_run(
        points,
        lambda p: p.eligible and p.dollars is not None and p.identity_sha == current.identity_sha,
        policy.stability_max_gap_hours,
    )
    span = _hours(current.at - run[0].at)
    info: dict[str, Any] = {
        "runStart": _iso(run[0].at),
        "runEvaluations": len(run),
        "runHours": round(span, 3),
        "requiredHours": policy.stability_window_hours,
    }
    if span < policy.stability_window_hours:
        brk = len(points) - len(run)
        cause = "no prior evaluations"
        if brk > 0:
            prev = points[brk - 1]
            if _hours(run[0].at - prev.at) > policy.stability_max_gap_hours:
                cause = f"gap {_hours(run[0].at - prev.at):.2f}h > {policy.stability_max_gap_hours}h reset the window"
            elif not prev.eligible:
                cause = f"evaluation at {_iso(prev.at)} was not ready and fresh"
            elif prev.identity_sha != current.identity_sha:
                cause = f"72-identity set changed after {_iso(prev.at)}"
        return (
            GateResult(
                GATE_STABILITY,
                FAIL,
                f"window {span:.2f}h < {policy.stability_window_hours}h ({cause})",
            ),
            info,
        )
    # The trailing window: the latest start that still spans the required hours.
    window = run
    for i in range(len(run) - 1, -1, -1):
        if _hours(current.at - run[i].at) >= policy.stability_window_hours:
            window = run[i:]
            break
    n = len(current.dollars)
    medians = [statistics.median([Fraction(p.dollars[k]) for p in window]) for k in range(n)]
    breaches = []
    for p in window:
        for k in range(n):
            if abs(Fraction(p.dollars[k]) - medians[k]) > policy.stability_pick_band_dollars:
                breaches.append(
                    {
                        "at": _iso(p.at),
                        "overall": k + 1,
                        "dollars": p.dollars[k],
                        "median": str(medians[k]),
                    }
                )
    total_change = sum(abs(a - b) for a, b in zip(window[-1].dollars, window[0].dollars))
    info.update(
        {
            "windowStart": _iso(window[0].at),
            "windowEvaluations": len(window),
            "windowHours": round(_hours(current.at - window[0].at), 3),
            "pickBandBreaches": breaches[:24],
            "pickBandBreachCount": len(breaches),
            "totalAbsChange": total_change,
            "totalAbsChangeLimit": policy.stability_total_abs_change_dollars,
        }
    )
    why = []
    if breaches:
        why.append(
            f"{len(breaches)} pick value(s) outside +/-${policy.stability_pick_band_dollars} of the window median"
        )
    if total_change > policy.stability_total_abs_change_dollars:
        why.append(
            f"total absolute change {total_change} > ${policy.stability_total_abs_change_dollars}"
        )
    if why:
        return GateResult(GATE_STABILITY, FAIL, "; ".join(why)), info
    return (
        GateResult(
            GATE_STABILITY,
            PASS,
            f"{len(window)} evaluations over {info['windowHours']}h; total change {total_change}",
        ),
        info,
    )


def _promotable_clock(
    history: Sequence[_Point], current: _Point, policy: PromotionPolicy, since: datetime | None
) -> tuple[float, str | None]:
    """Hours the class has been PROMOTABLE without a break (or since ``since``)."""
    points = [p for p in history if p.at < current.at] + [current]
    run = _trailing_run(
        points,
        lambda p: p.evaluation_state == STATE_PROMOTABLE and (since is None or p.at >= since),
        policy.stability_max_gap_hours,
    )
    if not run:
        return 0.0, None
    return _hours(current.at - run[0].at), _iso(run[0].at)


def _draft_status_hold(evidence: LeagueDraftEvidence | None, year: int) -> str | None:
    """``None`` when the class's rookie draft is known not to have started."""
    if evidence is None:
        return "draft_status_unobserved:no_draft_evidence"
    lc = draft_class_lifecycle(year, evidence)
    if lc.status == LIFECYCLE_ACTIVE and all(
        r.startswith("draft_not_started:") for r in lc.reasons
    ):
        return None
    if tuple(lc.reasons) == ("no_draft_observed_for_season",) and evidence.draft_lists_observed:
        return None  # the league's draft list was read and holds no class-Y draft yet
    return f"draft_started_or_unknown:{lc.status}:{','.join(lc.reasons)}"


# --- records --------------------------------------------------------------------


def _store(root: Path | None) -> Path:
    """The Batch D record store: repo-tracked ``config/draft_valuation/``.

    Resolved at call time from ``published.PROMOTION_ROOT`` (the same
    directory in production) so the test suite's redirect covers it.
    """
    return Path(root) if root is not None else published.PROMOTION_ROOT


def _class_dir(root: Path, name: str, league_key: str, year: int) -> Path:
    return root / name / league_key / str(int(year))


def _create_only(path: Path, payload: Mapping[str, Any]) -> bool:
    """Atomically create ``path``; ``False`` if an identical file already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".rec.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)
            return True
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != json.loads(json.dumps(payload)):
                raise
            return False
    finally:
        tmp.unlink(missing_ok=True)


def _sealed(payload: dict[str, Any]) -> dict[str, Any]:
    payload["checksum"] = {"algorithm": "sha256", "value": canonical_checksum(payload)}
    return payload


def _verified(path: Path, schema: str) -> dict[str, Any]:
    rec = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rec, dict) or rec.get("schema") != schema:
        raise ValueError(f"{path.name}: wrong schema")
    if (rec.get("checksum") or {}).get("value") != canonical_checksum(rec):
        raise ValueError(f"{path.name}: checksum mismatch — record was edited")
    return rec


def load_evaluations(
    league_key: str, draft_year: int, *, store_root: Path | None = None
) -> list[dict[str, Any]]:
    """Every persisted evaluation for (league, year), oldest first.  Refuses an edit."""
    d = _class_dir(_store(store_root), EVALUATION_DIR_NAME, league_key, draft_year)
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            rec = _verified(p, EVALUATION_SCHEMA)
            if rec.get("leagueKey") != league_key or rec.get("draftYear") != int(draft_year):
                raise ValueError(f"{p.name}: filed under the wrong league or year")
            out.append(rec)
    out.sort(key=lambda r: _ts(r["evaluatedAt"]))
    return out


def _load_transitions(league_key: str, year: int, store_root: Path) -> list[dict[str, Any]]:
    d = _class_dir(store_root, TRANSITION_DIR_NAME, league_key, year)
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            rec = _verified(p, TRANSITION_SCHEMA)
            if p.name != f"{int(rec.get('sequence', -1)):06d}.json":
                raise ValueError(f"{p.name}: sequence does not match the file name")
            out.append(rec)
    return out


def _write_class_snapshot(snapshot: RookieClassSnapshot, root: Path) -> Path:
    d = _class_dir(
        root, CLASS_SNAPSHOT_DIR_NAME, snapshot.league_key or "", snapshot.target_draft_year
    )
    path = d / f"{snapshot.snapshot_sha256}.json"
    _create_only(path, snapshot.to_dict())
    return path


def _load_stored_snapshot(
    league_key: str, year: int, sha: str, root: Path
) -> RookieClassSnapshot | None:
    p = _class_dir(root, CLASS_SNAPSHOT_DIR_NAME, league_key, year) / f"{sha}.json"
    try:
        return load_class_snapshot(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, SnapshotRecordError):
        return None


# --- the evaluation -------------------------------------------------------------


@dataclass(frozen=True)
class PromotionEvaluation:
    league_key: str
    draft_year: int
    evaluated_at: str
    policy: Mapping[str, Any] | None
    state: str
    evaluation_state: str
    serving_state: str
    gates: tuple[GateResult, ...]
    reasons: tuple[str, ...]
    window_open: bool
    structural_ready: bool
    freshness_pass: bool
    candidate_snapshot_sha256: str | None
    identity_set_sha256: str | None
    candidate_whole_dollars: tuple[int, ...] | None
    fallback_whole_dollars: tuple[int, ...] | None
    stability: Mapping[str, Any] = field(default_factory=dict)
    review: Mapping[str, Any] = field(default_factory=dict)
    promotion: Mapping[str, Any] = field(default_factory=dict)
    generation: Mapping[str, Any] = field(default_factory=dict)
    contract_as_of: str | None = None

    @property
    def would_promote(self) -> bool:
        return self.promotion.get("decision") == DECISION_WOULD_PROMOTE

    def transition_key(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "evaluationState": self.evaluation_state,
            "servingState": self.serving_state,
            "wouldPromote": self.would_promote,
        }

    def record(self) -> dict[str, Any]:
        return {
            "schema": EVALUATION_SCHEMA,
            "leagueKey": self.league_key,
            "draftYear": self.draft_year,
            "evaluatedAt": self.evaluated_at,
            "policy": dict(self.policy) if self.policy else None,
            "state": self.state,
            "evaluationState": self.evaluation_state,
            "servingState": self.serving_state,
            "windowOpen": self.window_open,
            "structuralReady": self.structural_ready,
            "freshnessPass": self.freshness_pass,
            "gates": [g.to_dict() for g in self.gates],
            "reasons": list(self.reasons),
            "contractAsOf": self.contract_as_of,
            "candidate": {
                "snapshotSha256": self.candidate_snapshot_sha256,
                "identitySetSha256": self.identity_set_sha256,
                "wholeDollars": None
                if self.candidate_whole_dollars is None
                else list(self.candidate_whole_dollars),
            },
            "fallbackWholeDollars": None
            if self.fallback_whole_dollars is None
            else list(self.fallback_whole_dollars),
            "stability": dict(self.stability),
            "reviewBand": dict(self.review),
            "promotion": dict(self.promotion),
            "generation": dict(self.generation),
        }


@dataclass(frozen=True)
class RunOutcome:
    evaluation: PromotionEvaluation
    evaluation_path: Path | None
    transition: Mapping[str, Any] | None  # newly created transition record, else None
    alerts: tuple[str, ...]
    snapshot_path: Path | None = None


def _headline(evaluation_state: str, serving_state: str) -> str:
    if evaluation_state.startswith("ERROR_") or evaluation_state == STATE_NOT_CONFIGURED:
        return evaluation_state
    if serving_state in (SERVING_ACTIVE, SERVING_ROLLED_BACK):
        return serving_state
    return evaluation_state


def _identity_sha(snapshot: RookieClassSnapshot) -> str:
    return _sha_json(sorted(str(e.canonical_player_id) for e in snapshot.entries))


def _serving(gen: published.GenerationState) -> str:
    if gen.held:
        return SERVING_ROLLED_BACK
    return SERVING_ACTIVE if gen.active_checksum else SERVING_FALLBACK


def _evaluate(
    *,
    league_key: str,
    year: int,
    now: datetime,
    policy: PromotionPolicy | None,
    policy_error: str | None,
    contract: Mapping[str, Any] | None,
    contract_error: str | None,
    observed_nfl_season: int | None,
    evidence: LeagueDraftEvidence | None,
    store_root: Path,
    config_dir: Path,
    promotion_root: Path | None,
) -> tuple[PromotionEvaluation, RookieClassSnapshot | None, published.PromotionPreview | None]:
    at = _iso(now)
    gates: list[GateResult] = []
    reasons: list[str] = []
    base = dict(
        league_key=league_key,
        draft_year=year,
        evaluated_at=at,
        policy=policy.to_dict() if policy else None,
        window_open=False,
        structural_ready=False,
        freshness_pass=False,
        candidate_snapshot_sha256=None,
        identity_set_sha256=None,
        candidate_whole_dollars=None,
        fallback_whole_dollars=None,
    )

    def done(eval_state, serving, **kw):
        kw.setdefault("gates", tuple(gates))
        kw.setdefault("reasons", tuple(reasons))
        return PromotionEvaluation(
            **{**base, **kw},
            state=_headline(eval_state, serving),
            evaluation_state=eval_state,
            serving_state=serving,
        )

    try:
        league_scope(league_key)
    except LeagueNotConfiguredError as exc:
        gates.append(GateResult("league_configured", FAIL, str(exc)))
        return done(STATE_NOT_CONFIGURED, SERVING_FALLBACK), None, None

    gen = published.generation_state(league_key, year, root=promotion_root)
    serving = _serving(gen)
    generation = gen.to_dict()
    if gen.error is not None:
        reasons.append(f"pointer_history_unreadable:{gen.error}")
        return done(STATE_ERROR_STORE, SERVING_FALLBACK, generation=generation), None, None
    if policy is None:
        reasons.append(f"policy_invalid:{policy_error}")
        return done(STATE_ERROR_POLICY, serving, generation=generation), None, None

    window = class_window_gate(policy, year, now)
    if window.outcome != PASS:
        # No candidate is built before the window opens (decision 12 item 1).
        empty = build_class_candidate(
            None, target_draft_year=year, league_key=league_key, observed_nfl_season=None
        )
        rep = evaluate_class_readiness(empty, league_key=league_key, config_dir=config_dir)
        gates.extend(g for g in rep.gates if g.name in _PRE_WINDOW_GATES)
        gates.append(window)
        gates.extend(GateResult(n, NOT_EVALUATED, "class window closed") for n, _ in POLICY_GATES)
        reasons.append(window.detail)
        state = STATE_ERROR if rep.state == STATE_ERROR else STATE_FALLBACK
        return done(state, serving, generation=generation), None, None

    base["window_open"] = True
    if contract_error is not None or not isinstance(contract, Mapping):
        gates.append(window)
        reasons.append(f"contract_unavailable:{contract_error or 'no contract'}")
        return done(STATE_ERROR_CONTRACT, serving, generation=generation), None, None

    as_of = _contract_as_of(contract)
    base["contract_as_of"] = _iso(as_of) if as_of else None
    candidate = build_class_candidate(
        contract,
        target_draft_year=year,
        league_key=league_key,
        observed_nfl_season=observed_nfl_season,
        as_of=_iso(as_of) if as_of else None,
    )
    rep: ReadinessReport = evaluate_class_readiness(
        candidate, league_key=league_key, config_dir=config_dir
    )
    policy_names = {n for n, _ in POLICY_GATES}
    gates.extend(g for g in rep.gates if g.name not in policy_names)
    gates.append(window)
    reasons.extend(rep.missing_reasons)
    base["candidate_snapshot_sha256"] = candidate.snapshot_sha256
    fallback = (rep.fallback_curve_receipt or {}).get("finalWholeDollars")
    base["fallback_whole_dollars"] = tuple(fallback) if isinstance(fallback, list) else None

    if rep.state != STATE_READY:
        gates.extend(
            GateResult(n, NOT_EVALUATED, "candidate not structurally ready")
            for n, _ in POLICY_GATES
        )
        state = rep.state if rep.state in (STATE_ERROR, STATE_FALLBACK) else STATE_INCOMPLETE
        return done(state, serving, generation=generation), candidate, None

    base["structural_ready"] = True
    base["identity_set_sha256"] = _identity_sha(candidate)
    dollars = (rep.candidate_curve_receipt or {}).get("finalWholeDollars")
    base["candidate_whole_dollars"] = tuple(dollars) if isinstance(dollars, list) else None

    fresh = source_freshness_gate(candidate, contract, policy=policy, now=now)
    gates.append(fresh)
    base["freshness_pass"] = fresh.outcome == PASS

    try:
        history = [
            _point_from_record(r) for r in load_evaluations(league_key, year, store_root=store_root)
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        reasons.append(f"evaluation_log_unreadable:{exc}")
        gates.extend(
            GateResult(n, NOT_EVALUATED, "evaluation log unreadable")
            for n in (GATE_STABILITY, GATE_REVIEW, GATE_FIRST_SWITCH)
        )
        return done(STATE_ERROR_STORE, serving, generation=generation), candidate, None

    current = _Point(
        at=now,
        eligible=base["freshness_pass"],
        identity_sha=base["identity_set_sha256"],
        dollars=base["candidate_whole_dollars"],
        evaluation_state=STATE_READY,
    )
    stable, stability = stability_gate(history, current, policy)
    gates.append(stable)
    review, review_info = review_band_gate(
        base["candidate_whole_dollars"], base["fallback_whole_dollars"], policy
    )
    gates.append(review)
    gates.append(
        GateResult(
            GATE_FIRST_SWITCH,
            PASS if policy.includes_first_switch else FAIL,
            "owner approved automatic promotion including the first switch (decision 12)"
            if policy.includes_first_switch
            else "policy does not include the first switch",
        )
    )

    if fresh.outcome != PASS or stable.outcome != PASS:
        eval_state = STATE_READY
    elif review.outcome == FAIL:
        eval_state = STATE_NEEDS_REVIEW
    elif review.outcome == PASS and policy.includes_first_switch:
        eval_state = STATE_PROMOTABLE
    else:
        eval_state = STATE_VALIDATED

    promotion: dict[str, Any] = {"decision": DECISION_NONE, "mode": policy.mode}
    preview = None
    if eval_state == STATE_PROMOTABLE:
        since = _ts(gen.last_action_at) if gen.last_action_at else None
        hours, run_start = _promotable_clock(
            history,
            _Point(now, True, current.identity_sha, current.dollars, STATE_PROMOTABLE),
            policy,
            since,
        )
        promotion.update(
            {
                "promotableHours": round(hours, 3),
                "promotableSince": run_start,
                "requiredHours": policy.promotable_hold_hours,
            }
        )
        holds = []
        if gen.held:
            holds.append("rolled_back:resume required")
        draft_hold = _draft_status_hold(evidence, year)
        if draft_hold:
            holds.append(draft_hold)
        if hours < policy.promotable_hold_hours:
            holds.append(f"promotable_for_{hours:.2f}h_of_{policy.promotable_hold_hours}h")
        receipt = rep.candidate_curve_receipt or {}
        allocation = published.AllocationCandidate(
            draft_year=year,
            reference_dollars=tuple(receipt.get("referenceDollars") or ()),
            effective_at=at,
            provenance={
                "source": "canonical_class_snapshot",
                "classSnapshotSha256": candidate.snapshot_sha256,
                "contractAsOf": base["contract_as_of"],
                "policyVersion": policy.version,
                "thresholdsChecksum": policy.thresholds_checksum,
                "spineYears": list(rep.spine_years or ()),
            },
        )
        preview = published.preview_promotion(league_key, allocation, root=promotion_root)
        if preview.record is None:
            holds.append(f"candidate_refused:{preview.refusal}")
        if holds:
            promotion.update({"decision": DECISION_HOLD, "holds": holds})
        elif preview.same_as_active:
            promotion["decision"] = DECISION_ALREADY_ACTIVE
        else:
            promotion["decision"] = DECISION_PROMOTED if policy.live else DECISION_WOULD_PROMOTE
            promotion["allocation"] = allocation
    return (
        done(
            eval_state,
            serving,
            stability=stability,
            review=review_info,
            promotion=promotion,
            generation=generation,
        ),
        candidate,
        preview,
    )


def run_class_evaluation(
    *,
    league_key: str,
    draft_year: int,
    contract: Mapping[str, Any] | None,
    now: datetime,
    observed_nfl_season: int | None,
    evidence: LeagueDraftEvidence | None,
    contract_error: str | None = None,
    policy_path: Path | None = None,
    store_root: Path | None = None,
    config_dir: Path = CONFIG_DIR,
    promotion_root: Path | None = None,
    persist: bool = True,
) -> RunOutcome:
    """One scheduled readiness evaluation for one class (decision 12).

    Persists the evaluation (only once the class window is open — before
    that nothing about a candidate exists to record), switches the
    generation when the policy is live and the class is eligible, and records
    a transition — with exactly one alert — when the state changed.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    year = int(draft_year)
    store_root = _store(store_root)
    proot = Path(promotion_root) if promotion_root is not None else published.PROMOTION_ROOT
    try:
        policy, policy_error = load_promotion_policy(policy_path), None
    except PolicyError as exc:
        policy, policy_error = None, str(exc)

    evaluation, candidate, _preview = _evaluate(
        league_key=league_key,
        year=year,
        now=now,
        policy=policy,
        policy_error=policy_error,
        contract=contract,
        contract_error=contract_error,
        observed_nfl_season=observed_nfl_season,
        evidence=evidence,
        store_root=store_root,
        config_dir=config_dir,
        promotion_root=proot,
    )

    promotion = dict(evaluation.promotion)
    allocation = promotion.pop("allocation", None)
    snapshot_path: Path | None = None
    eval_state, serving = evaluation.evaluation_state, evaluation.serving_state
    reasons = list(evaluation.reasons)
    if promotion.get("decision") == DECISION_PROMOTED and persist and candidate is not None:
        # Every failure below keeps the previous generation: the pointer is
        # written last, and only publish_promoted_generation writes it.
        try:
            snapshot_path = _write_class_snapshot(candidate, store_root)
            pointer = published.publish_promoted_generation(
                league_key,
                allocation,
                at=evaluation.evaluated_at,
                reason=f"automatic promotion: PROMOTABLE for {promotion.get('promotableHours')}h",
                context={
                    "classSnapshotSha256": candidate.snapshot_sha256,
                    "policyVersion": policy.version if policy else None,
                },
                root=proot,
            )
            promotion["pointer"] = None if pointer is None else pointer["sequence"]
            if pointer is not None:
                serving = SERVING_ACTIVE
        except (published.GenerationError, OSError, ValueError) as exc:
            eval_state = STATE_ERROR_PUBLISH
            promotion["decision"] = DECISION_HOLD
            promotion["holds"] = [f"publish_failed:{exc}"]
            reasons.append(f"publish_failed:{exc}")
    elif promotion.get("decision") == DECISION_PROMOTED:
        promotion["decision"] = DECISION_WOULD_PROMOTE  # persist=False: never switch
    gen_after = published.generation_state(league_key, year, root=proot).to_dict()
    evaluation = PromotionEvaluation(
        **{
            **evaluation.__dict__,
            "evaluation_state": eval_state,
            "serving_state": serving,
            "state": _headline(eval_state, serving),
            "promotion": promotion,
            "reasons": tuple(reasons),
            "generation": gen_after,
        }
    )

    evaluation_path: Path | None = None
    if persist and evaluation.window_open:
        rec = _sealed(evaluation.record())
        d = _class_dir(store_root, EVALUATION_DIR_NAME, league_key, year)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        evaluation_path = d / f"{stamp}__{rec['checksum']['value'][:16]}.json"
        _create_only(evaluation_path, rec)

    transition, alerts = _record_transition(evaluation, store_root=store_root, persist=persist)
    if transition is not None and evaluation.would_promote and candidate is not None and persist:
        snapshot_path = _write_class_snapshot(candidate, store_root)
    return RunOutcome(evaluation, evaluation_path, transition, alerts, snapshot_path)


def _alert_text(ev: PromotionEvaluation, previous: Mapping[str, Any] | None) -> str:
    was = (previous or {}).get("to") or {}
    failing = [f"{g.name}: {g.detail}" for g in ev.gates if g.outcome == FAIL]
    lines = [
        f"Draft valuation {ev.league_key} {ev.draft_year}: "
        f"{was.get('state', 'NONE')} -> {ev.state}",
        f"evaluationState={ev.evaluation_state} servingState={ev.serving_state} "
        f"mode={(ev.policy or {}).get('promotionMode')}",
    ]
    if ev.would_promote:
        lines.append("DRY RUN: this class is eligible for automatic promotion; nothing switched.")
    if ev.promotion.get("decision") == DECISION_HOLD:
        lines.append("held: " + "; ".join(ev.promotion.get("holds") or []))
    if failing:
        lines.append("failing gates: " + " | ".join(failing[:6]))
    if ev.reasons:
        lines.append("reasons: " + "; ".join(list(ev.reasons)[:6]))
    return "\n".join(lines)


def _record_transition(
    ev: PromotionEvaluation, *, store_root: Path, persist: bool, note: str | None = None
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    try:
        history = _load_transitions(ev.league_key, ev.draft_year, store_root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # An unreadable transition log must not suppress or repeat alerts
        # silently: alert once in-process and write nothing.
        return None, (
            f"Draft valuation {ev.league_key} {ev.draft_year}: transition log unreadable ({exc})",
        )
    last = history[-1] if history else None
    key = ev.transition_key()
    if last is not None and last.get("to") == key:
        return None, ()
    text = _alert_text(ev, last) + (f"\n{note}" if note else "")
    rec = _sealed(
        {
            "schema": TRANSITION_SCHEMA,
            "leagueKey": ev.league_key,
            "draftYear": ev.draft_year,
            "sequence": (int(last["sequence"]) + 1) if last else 1,
            "at": ev.evaluated_at,
            "from": None if last is None else last.get("to"),
            "to": key,
            "alert": text,
        }
    )
    if not persist:
        return rec, (text,)
    path = _class_dir(store_root, TRANSITION_DIR_NAME, ev.league_key, ev.draft_year) / (
        f"{rec['sequence']:06d}.json"
    )
    try:
        created = _create_only(path, rec)
    except (FileExistsError, OSError) as exc:
        return None, (
            f"Draft valuation {ev.league_key} {ev.draft_year}: transition not recorded ({exc})",
        )
    return (rec, (text,)) if created else (None, ())


# --- operator commands ----------------------------------------------------------


def _operator_evaluation(
    league_key: str,
    year: int,
    now: datetime,
    serving: str,
    reason: str,
    gen: dict[str, Any],
    store_root: Path,
) -> PromotionEvaluation:
    """An operator action as an evaluation-shaped transition.

    It keeps the newest recorded ``evaluationState`` so the next scheduled
    run, if the candidate is unchanged, finds no transition and does not
    alert a second time for the same operator action.
    """
    try:
        history = _load_transitions(league_key, year, store_root)
    except (OSError, ValueError, KeyError, TypeError):
        history = []
    prev_eval = ((history[-1].get("to") or {}).get("evaluationState") if history else None) or (
        STATE_FALLBACK
    )
    return PromotionEvaluation(
        league_key=league_key,
        draft_year=year,
        evaluated_at=_iso(now),
        policy=None,
        state=_headline(prev_eval, serving),
        evaluation_state=prev_eval,
        serving_state=serving,
        gates=(),
        reasons=(reason,),
        window_open=False,
        structural_ready=False,
        freshness_pass=False,
        candidate_snapshot_sha256=None,
        identity_set_sha256=None,
        candidate_whole_dollars=None,
        fallback_whole_dollars=None,
        generation=gen,
    )


def operator_rollback(
    league_key: str,
    draft_year: int,
    *,
    now: datetime,
    reason: str,
    store_root: Path | None = None,
    promotion_root: Path | None = None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """One-command rollback: restore the previous generation, record ROLLED_BACK."""
    store_root = _store(store_root)
    proot = Path(promotion_root) if promotion_root is not None else published.PROMOTION_ROOT
    pointer = published.rollback_generation(
        league_key, draft_year, at=_iso(now), reason=reason, root=proot
    )
    gen = published.generation_state(league_key, draft_year, root=proot).to_dict()
    ev = _operator_evaluation(
        league_key,
        int(draft_year),
        now,
        SERVING_ROLLED_BACK,
        f"operator rollback: {reason}",
        gen,
        store_root,
    )
    _, alerts = _record_transition(
        ev,
        store_root=store_root,
        persist=True,
        note=f"restored generation: {pointer['activeRecordChecksum'] or 'fallback'}",
    )
    return pointer, alerts


def operator_resume(
    league_key: str,
    draft_year: int,
    *,
    now: datetime,
    reason: str,
    store_root: Path | None = None,
    promotion_root: Path | None = None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Clear a rollback hold; automatic promotion may run again (48 h clock restarts)."""
    store_root = _store(store_root)
    proot = Path(promotion_root) if promotion_root is not None else published.PROMOTION_ROOT
    pointer = published.resume_generation(
        league_key, draft_year, at=_iso(now), reason=reason, root=proot
    )
    gen = published.generation_state(league_key, draft_year, root=proot)
    ev = _operator_evaluation(
        league_key,
        int(draft_year),
        now,
        _serving(gen),
        f"operator resume: {reason}",
        gen.to_dict(),
        store_root,
    )
    _, alerts = _record_transition(ev, store_root=store_root, persist=True)
    return pointer, alerts


def diagnose(
    league_key: str,
    draft_year: int,
    *,
    now: datetime,
    policy_path: Path | None = None,
    store_root: Path | None = None,
    promotion_root: Path | None = None,
) -> dict[str, Any]:
    """Operator diagnostic: policy, generation, newest evaluation, gates, window."""
    store_root = _store(store_root)
    proot = Path(promotion_root) if promotion_root is not None else published.PROMOTION_ROOT
    out: dict[str, Any] = {"leagueKey": league_key, "draftYear": int(draft_year), "now": _iso(now)}
    try:
        policy = load_promotion_policy(policy_path)
        out["policy"] = policy.to_dict()
        out["classWindow"] = class_window_gate(policy, draft_year, now).to_dict()
    except PolicyError as exc:
        policy = None
        out["policy"] = {"error": str(exc)}
    out["generation"] = published.generation_state(league_key, draft_year, root=proot).to_dict()
    try:
        evals = load_evaluations(league_key, draft_year, store_root=store_root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        evals = []
        out["evaluationLogError"] = str(exc)
    out["evaluationCount"] = len(evals)
    if evals:
        last = evals[-1]
        out["latest"] = {
            k: last.get(k)
            for k in (
                "evaluatedAt",
                "state",
                "evaluationState",
                "servingState",
                "gates",
                "reasons",
                "stability",
                "reviewBand",
                "promotion",
            )
        }
        if policy is not None:
            points = [_point_from_record(r) for r in evals]
            if points[-1].eligible:
                _, info = stability_gate(points[:-1], points[-1], policy)
                out["window"] = info
    try:
        transitions = _load_transitions(league_key, int(draft_year), store_root)
        out["transitions"] = [
            {"sequence": t["sequence"], "at": t["at"], "to": t["to"]} for t in transitions[-10:]
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        out["transitionLogError"] = str(exc)
    return out


# --- ledger finalization (decision 12 item 8) -------------------------------------


def finalize_completed_class_step(
    *,
    league_key: str,
    draft_class: int,
    evidence: LeagueDraftEvidence | None,
    live: bool,
    store_root: Path | None = None,
    config_dir: Path = CONFIG_DIR,
    promotion_root: Path | None = None,
    fetch: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """File a completed class into the spine ledger, with the Sleeper cutoff.

    Inputs are the class snapshot of the generation that was SERVING at the
    pre-draft cutoff (the newest pointer at or before it); with none, the
    frozen fallback — what the auction actually used.  Dry run reports what
    it would file and writes nothing.
    """
    from src.draft.rookie_auction.ledger import (  # noqa: PLC0415
        ImmutableSnapshotConflict,
        LedgerRefusal,
        finalize_completed_class,
        pre_draft_cutoff_from_sleeper,
    )

    year = int(draft_class)
    store_root = _store(store_root)
    out: dict[str, Any] = {"draftClass": year, "leagueKey": league_key}
    try:
        if year in available_completed_classes(league_key=league_key, config_dir=config_dir):
            return {**out, "status": "already_finalized"}
    except (SnapshotIntegrityError, OSError) as exc:
        return {**out, "status": "refused", "reason": f"ledger_unreadable:{exc}"}
    lc = draft_class_lifecycle(year, evidence)
    if not is_retired(lc):
        return {**out, "status": "not_complete", "reasons": list(lc.reasons)}
    try:
        cutoff = pre_draft_cutoff_from_sleeper(evidence, year, fetch=fetch)
    except LedgerRefusal as exc:
        return {**out, "status": "refused", "reason": exc.reason, "detail": str(exc)}
    out["preDraftCutoff"] = cutoff

    proot = Path(promotion_root) if promotion_root is not None else published.PROMOTION_ROOT
    gen = published.generation_state(league_key, year, root=proot)
    if gen.error is not None:
        return {**out, "status": "refused", "reason": f"pointer_history_unreadable:{gen.error}"}
    stack: list[str] = []
    for p in gen.pointers:
        if _ts(p["at"]) > _ts(cutoff):
            break
        if p["action"] == published.ACTION_PROMOTE:
            stack.append(p["activeRecordChecksum"])
        elif p["action"] == published.ACTION_ROLLBACK and stack:
            stack.pop()
    inputs: RookieClassSnapshot | None
    if stack:
        record = published.load_promoted_record(league_key, year, stack[-1], root=proot)
        sha = ((record or {}).get("provenance") or {}).get("classSnapshotSha256")
        inputs = _load_stored_snapshot(league_key, year, sha, store_root) if sha else None
        if inputs is None:
            return {**out, "status": "refused", "reason": "serving_generation_snapshot_missing"}
        out["inputs"] = {"mode": inputs.mode, "snapshotSha256": inputs.snapshot_sha256}
    else:
        inputs = frozen_fallback_snapshot(year, league_key=league_key)
        out["inputs"] = {"mode": inputs.mode, "snapshotSha256": inputs.snapshot_sha256}
    if not live:
        return {**out, "status": "would_finalize"}
    if evidence is None:
        return {**out, "status": "refused", "reason": "no_draft_evidence"}
    try:
        res = finalize_completed_class(
            league_key=league_key,
            draft_class=year,
            inputs=inputs,
            evidence=evidence,
            pre_draft_cutoff=cutoff,
            config_dir=config_dir,
        )
    except (LedgerRefusal, ImmutableSnapshotConflict) as exc:
        return {
            **out,
            "status": "refused",
            "reason": getattr(exc, "reason", type(exc).__name__),
            "detail": str(exc),
        }
    return {
        **out,
        "status": "finalized" if res.created else "already_finalized",
        "path": str(res.path),
        "checksum": res.checksum,
    }
