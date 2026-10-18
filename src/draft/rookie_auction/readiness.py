"""Rookie-class readiness — REPORT-ONLY evidence for the first class switch (Batch B/D).

Answers one question: *could class ``Y``'s actual inputs replace the frozen
provisional fallback yet, and if not, exactly what is missing?*  It reports;
it never switches.  There is no promote function, nothing schedules this,
and :data:`PROMOTION_ENABLED` is a constant ``False`` — the first switch from
the frozen fallback to a real class needs owner approval of the switch
policy and of preregistered numeric thresholds (owner package PROMPT D;
"Decision 4").  Until then the strongest state this module can report is
``CANDIDATE_READY``, which means "every structural gate passed", not
"promotable".

States (the first three of the PROMPT D state machine; the rest are
deliberately unreachable here):

``LEAGUE_NOT_CONFIGURED``
    the curve is configured for ``dynasty_main`` only (owner scope
    2026-10-18); any other league is refused, not adapted.
``ERROR_FALLBACK_INVALID``
    the frozen fallback itself failed to load — nothing is safe to serve.
``FALLBACK_VERIFIED``
    the fallback loads and prices; there is no actual candidate yet
    (zero eligible rows for the target class).
``CANDIDATE_INCOMPLETE``
    some eligible rows exist, but a structural gate fails.
``CANDIDATE_READY``
    every structural gate passes.  Policy gates stay ``NOT_EVALUATED``.

Gate outcomes are ``PASS`` / ``FAIL`` / ``NOT_EVALUATED``; an unevaluated
gate never counts as a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.draft.rookie_auction.class_snapshot import (
    STATUS_COMPLETE,
    RookieClassSnapshot,
    frozen_fallback_snapshot,
)
from src.draft.rookie_auction.curve import (
    WORKBOOK_PARAMS,
    CurveInputError,
    CurveInvariantError,
    compute_curve,
    curve_receipt,
)
from src.draft.rookie_auction.league_scope import LeagueNotConfiguredError, league_scope
from src.draft.rookie_auction.snapshots import (
    CONFIG_DIR,
    SnapshotIntegrityError,
    SpineUnavailableError,
    load_frozen_rookie_inputs,
    spine_curves_for,
)

__all__ = [
    "PROMOTION_ENABLED",
    "GateResult",
    "ReadinessReport",
    "evaluate_class_readiness",
]

#: The first switch policy is an owner decision.  Nothing in this module (or
#: anywhere) may flip this; a future, owner-approved Batch D adds a separate
#: promotion path rather than editing this constant.
PROMOTION_ENABLED = False

PASS, FAIL, NOT_EVALUATED = "PASS", "FAIL", "NOT_EVALUATED"

STATE_NOT_CONFIGURED = "LEAGUE_NOT_CONFIGURED"
STATE_ERROR = "ERROR_FALLBACK_INVALID"
STATE_FALLBACK = "FALLBACK_VERIFIED"
STATE_INCOMPLETE = "CANDIDATE_INCOMPLETE"
STATE_READY = "CANDIDATE_READY"

#: Gates whose thresholds must be preregistered by the owner before any
#: candidate is looked at (PROMPT D item 2).  Reported, never passed.
POLICY_GATES = (
    ("source_freshness", "awaiting owner-preregistered freshness thresholds"),
    ("stability_vs_prior_generation", "awaiting owner-preregistered stability band"),
    ("bounded_variation_vs_fallback", "awaiting owner-preregistered review band"),
    ("first_switch_approval", "the first switch from the frozen fallback needs owner approval"),
)


@dataclass(frozen=True)
class GateResult:
    name: str
    outcome: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"gate": self.name, "outcome": self.outcome, "detail": self.detail}


@dataclass(frozen=True)
class ReadinessReport:
    target_draft_year: int
    league_key: str
    state: str
    gates: tuple[GateResult, ...]
    candidate_snapshot_sha256: str | None
    candidate_curve_receipt: dict[str, Any] | None
    fallback_curve_receipt: dict[str, Any] | None
    spine_years: tuple[int, ...] | None
    missing_reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def promotion_authorized(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "targetDraftYear": self.target_draft_year,
            "leagueKey": self.league_key,
            "state": self.state,
            "promotionAuthorized": False,
            "promotionEnabled": PROMOTION_ENABLED,
            "switchPolicy": "owner_approval_required",
            "gates": [g.to_dict() for g in self.gates],
            "missingReasons": list(self.missing_reasons),
            "spineYears": list(self.spine_years) if self.spine_years else None,
            "candidateSnapshotSha256": self.candidate_snapshot_sha256,
            "candidateCurveReceipt": self.candidate_curve_receipt,
            "fallbackCurveReceipt": self.fallback_curve_receipt,
        }


def evaluate_class_readiness(
    candidate: RookieClassSnapshot,
    *,
    league_key: str,
    config_dir: Path = CONFIG_DIR,
) -> ReadinessReport:
    """Evaluate ``candidate`` (from ``build_class_candidate``) against the gates."""
    target = candidate.target_draft_year
    gates: list[GateResult] = []
    try:
        league_scope(league_key)
    except LeagueNotConfiguredError as exc:
        return ReadinessReport(
            target_draft_year=target,
            league_key=league_key,
            state=STATE_NOT_CONFIGURED,
            gates=(GateResult("league_configured", FAIL, str(exc)),),
            candidate_snapshot_sha256=candidate.snapshot_sha256,
            candidate_curve_receipt=None,
            fallback_curve_receipt=None,
            spine_years=None,
            missing_reasons=tuple(candidate.missing_reasons),
        )
    gates.append(GateResult("league_configured", PASS, league_key))

    # Spine — the three completed classes before the target, per league.
    spine_years: tuple[int, ...] | None = None
    curves = None
    try:
        spine_years, curves = spine_curves_for(target, league_key=league_key, config_dir=config_dir)
        gates.append(GateResult("spine_available", PASS, f"spine {list(spine_years)}"))
    except (SpineUnavailableError, SnapshotIntegrityError, FileNotFoundError) as exc:
        gates.append(GateResult("spine_available", FAIL, str(exc)))

    # The frozen fallback must load and price, or nothing is safe to serve.
    fallback_receipt = None
    try:
        frozen = load_frozen_rookie_inputs(config_dir=config_dir)
        fallback = frozen_fallback_snapshot(target, league_key=league_key, frozen=frozen)
        if curves is not None:
            res = compute_curve(fallback.curve_values(), curves, WORKBOOK_PARAMS)
            fallback_receipt = curve_receipt(
                res,
                spine_years=spine_years,
                input_provenance={"mode": fallback.mode, "snapshot": fallback.snapshot_sha256},
            )
        gates.append(GateResult("fallback_verified", PASS, f"frozen {frozen.snapshot_id}"))
    except (SnapshotIntegrityError, FileNotFoundError, CurveInputError, CurveInvariantError) as exc:
        gates.append(GateResult("fallback_verified", FAIL, str(exc)))

    # Structural gates on the candidate.
    n = len(candidate.entries)
    ids = [e.canonical_player_id for e in candidate.entries]
    gates.append(
        GateResult(
            "league_context_known",
            PASS
            if candidate.idp_eligible is not None and candidate.league_key == league_key
            else FAIL,
            f"idpEligible={candidate.idp_eligible}, leagueKey={candidate.league_key}",
        )
    )
    gates.append(
        GateResult(
            "class_identity_verified",
            PASS if n and all(e.eligible_draft_year == target for e in candidate.entries) else FAIL,
            f"{n} entries proven to be class {target}",
        )
    )
    gates.append(
        GateResult(
            "exact_pick_count_unique",
            PASS if n == candidate.pick_count and len(set(ids)) == n and None not in ids else FAIL,
            f"{n}/{candidate.pick_count} entries, {len(set(ids))} unique identities",
        )
    )
    dup = [r for r in candidate.missing_reasons if r.startswith("duplicate_identity:")]
    gates.append(
        GateResult(
            "no_duplicate_identities",
            FAIL if dup else PASS,
            ", ".join(dup) if dup else "none",
        )
    )

    candidate_receipt = None
    if candidate.status == STATUS_COMPLETE and curves is not None:
        try:
            res = compute_curve(candidate.curve_values(), curves, WORKBOOK_PARAMS)
            candidate_receipt = curve_receipt(
                res,
                spine_years=spine_years,
                input_provenance={"mode": candidate.mode, "snapshot": candidate.snapshot_sha256},
            )
            gates.append(
                GateResult(
                    "formula_exact_budget", PASS, f"total ${candidate_receipt['totalDollars']}"
                )
            )
        except (CurveInputError, CurveInvariantError) as exc:
            gates.append(GateResult("formula_exact_budget", FAIL, str(exc)))
    else:
        gates.append(
            GateResult("formula_exact_budget", NOT_EVALUATED, "candidate incomplete or no spine")
        )

    for name, why in POLICY_GATES:
        gates.append(GateResult(name, NOT_EVALUATED, why))

    by_name = {g.name: g.outcome for g in gates}
    structural = [g for g in gates if g.name not in {p for p, _ in POLICY_GATES}]
    if by_name.get("fallback_verified") != PASS:
        state = STATE_ERROR
    elif n == 0:
        state = STATE_FALLBACK
    elif all(g.outcome == PASS for g in structural):
        state = STATE_READY
    else:
        state = STATE_INCOMPLETE

    return ReadinessReport(
        target_draft_year=target,
        league_key=league_key,
        state=state,
        gates=tuple(gates),
        candidate_snapshot_sha256=candidate.snapshot_sha256,
        candidate_curve_receipt=candidate_receipt,
        fallback_curve_receipt=fallback_receipt,
        spine_years=spine_years,
        missing_reasons=tuple(candidate.missing_reasons),
    )
