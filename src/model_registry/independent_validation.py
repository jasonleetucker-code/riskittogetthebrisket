"""Independent validation targets for Hill Autopilot automatic promotion.

Owner methodology decision 1 (2026-10-01): automatic OFFENSE Hill promotion
requires at least one GENUINELY INDEPENDENT validation target. The dependent
board holdouts (``holdout.evaluate_offense_master``) stay required, but they
are necessary, not sufficient. With no eligible target the Autopilot decision
is ``AUTO_PROMOTION_BLOCKED`` with reason ``no_independent_validation_target``.

This module owns two things:

* the REGISTRY -- :data:`INDEPENDENT_VALIDATION_TARGETS`, a small explicit
  tuple. **It is empty today, deliberately.** No target exists that is both
  preregistered and independent of the KTC-family training substrate, and a
  target must never be created merely to restore automatic promotion;
* the ELIGIBILITY rule -- :func:`assess_target` -- and the per-run evidence
  (:func:`evaluate_independent_validation`) that ``autopilot.decide`` gates on.

The contract a target declares (:class:`IndependentValidationTarget`):

* ``target_id``;
* ``preregistration_path`` + ``preregistration_commit`` -- the preregistration
  document and the commit that first recorded it. The commit must be a full
  40-hex SHA (never a ref name or an abbreviation -- ``HEAD`` or a branch
  moves), a STRICT ancestor of HEAD, contain the file, and the file's blob at
  HEAD must be identical to the one at that commit. So the rule was committed
  BEFORE the registry entry that consumes it (which therefore lands in a later
  commit) and has not been edited since (:func:`git_preregistration_committed`);
* ``provenance`` -- every evidence component the target derives from, each with
  its B10 provider family and the registered source keys the lineage owner can
  answer for;
* ``independence`` -- an EXPLICIT treatment for every challenger training
  family (:data:`TREATMENT_NO_SHARED_PROVENANCE` or
  :data:`TREATMENT_COMPONENT_EXCLUDED`). A target is never wholesale
  "independent": a family the target did not anticipate makes it ineligible;
* ``rule`` -- the preregistered pass/fail rule, called with champion and
  challenger OFFENSE parameters.

A target is ELIGIBLE for a challenger only when every check passes; each
failure is a named reason, and anything unknowable fails closed:

* the challenger's training families are known (empty -> ineligible);
* the preregistration is committed (above);
* there is an explicit treatment for every training family;
* ``no_shared_provenance`` is not contradicted by a component of that family
  (mixed provenance must say what it does with the dependent component);
* ``component_excluded`` names a component that actually exists. **This is a
  DECLARATION the module cannot verify**: a rule receives only champion and
  challenger parameters, never the component data, so nothing here can prove
  the rule drops what the treatment says it drops. Reviewing a target's
  preregistration must therefore verify that its rule actually removes every
  excluded component before scoring; until the rule interface hands a rule only
  the non-excluded components, that review IS the enforcement;
* every SCORED component (not excluded) belongs to none of the training
  families, and its declared family matches the source registry;
* the lineage owner (``training_manifest.holdout_lineage`` over
  ``config/sources/source_lineage.json``) reconciles every scored source key
  ``INDEPENDENT_NO_EVIDENCE`` with every training family -- ``UNKNOWN``,
  ``SUSPECTED``, ``MEASURED`` and ``PROVEN`` all make the target ineligible.

When eligible targets exist, the challenger must pass EVERY one of them under
its preregistered rule (failing any eligible independent target is evidence
against the candidate; "pass any one" would invite target shopping). A rule
that raises fails closed.

Leading future candidate, recorded as a hook only: the completed-trade ledger
(``src/trade/market_trade_*``). Owner rule: KTC Trade Database evidence alone
is NOT independent for a KTC-trained curve, so that ledger needs its own
preregistration, deduplicated format-qualified transactions with independent
provenance (Sharp / Sleeper observations), registered lineage for each
component, and an explicit ``component_excluded`` treatment for any KTC-derived
component before it can be added here.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

REPO = Path(__file__).resolve().parents[2]

#: The exact reason ``autopilot.decide`` reports when no eligible target exists.
REASON_NO_TARGET = "no_independent_validation_target"
#: Eligible targets exist but the challenger did not pass every one.
REASON_TARGET_FAILED = "independent_validation_failed"
#: The evidence handed to ``decide`` was computed for a different challenger.
REASON_EVIDENCE_MISMATCH = "independent_validation_evidence_not_for_winner"

#: The target shares no provenance with this training family.
TREATMENT_NO_SHARED_PROVENANCE = "no_shared_provenance"
#: The target HAS a component of this training family; its preregistered rule
#: scores the target with that component removed.
TREATMENT_COMPONENT_EXCLUDED = "component_excluded"
TREATMENTS = frozenset({TREATMENT_NO_SHARED_PROVENANCE, TREATMENT_COMPONENT_EXCLUDED})

#: The lineage owner's only independent category (``source_census``).
_LINEAGE_INDEPENDENT = "INDEPENDENT_NO_EVIDENCE"


@dataclass(frozen=True)
class RuleOutcome:
    """What a target's preregistered rule concluded for one challenger."""

    passed: bool
    detail: Mapping[str, Any] = field(default_factory=dict)


#: ``rule(champion_c, champion_s, challenger_c, challenger_s) -> RuleOutcome``.
TargetRule = Callable[[float, float, float, float], RuleOutcome]


@dataclass(frozen=True)
class ProvenanceComponent:
    """One body of evidence a target derives from."""

    component_id: str
    #: B10 provider family (``data_contract.correlation_group_for``).
    family: str
    #: Registered source keys the lineage owner can answer for. Empty -> the
    #: component's lineage is unverifiable and the target is ineligible.
    source_keys: tuple[str, ...]


@dataclass(frozen=True)
class IndependenceTreatment:
    """The explicit treatment of ONE challenger training family."""

    treatment: str
    #: For ``component_excluded``: the component ids removed before scoring.
    excluded_components: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class IndependentValidationTarget:
    target_id: str
    preregistration_path: str
    preregistration_commit: str
    provenance: tuple[ProvenanceComponent, ...]
    independence: Mapping[str, IndependenceTreatment]
    rule: TargetRule
    rule_id: str = ""


#: THE registry. Empty by owner decision 1: nothing preregistered is independent
#: of the KTC-family OFFENSE substrate today, and no target may be invented to
#: restore promotion. See the module docstring for the completed-trade-ledger hook.
INDEPENDENT_VALIDATION_TARGETS: tuple[IndependentValidationTarget, ...] = ()


@dataclass(frozen=True)
class TargetAssessment:
    target_id: str
    eligible: bool
    ineligible_reasons: tuple[str, ...]
    #: ``None`` when ineligible (the rule is never run) -- never ``False``.
    passed: bool | None = None
    rule_detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "targetId": self.target_id,
            "eligible": self.eligible,
            "ineligibleReasons": list(self.ineligible_reasons),
            "passed": self.passed,
            "ruleDetail": dict(self.rule_detail),
        }


@dataclass(frozen=True)
class IndependentValidationEvidence:
    """Every registered target's verdict for ONE challenger."""

    challenger_version: int | None
    training_families: tuple[str, ...]
    registry_size: int
    assessments: tuple[TargetAssessment, ...] = ()

    @property
    def eligible(self) -> tuple[TargetAssessment, ...]:
        return tuple(a for a in self.assessments if a.eligible)

    @property
    def passed(self) -> bool:
        """At least one eligible target, and the challenger passed every eligible one."""
        eligible = self.eligible
        return bool(eligible) and all(a.passed is True for a in eligible)

    @property
    def reason(self) -> str | None:
        if not self.eligible:
            return REASON_NO_TARGET
        return None if self.passed else REASON_TARGET_FAILED

    def to_dict(self) -> dict[str, Any]:
        return {
            "challengerVersion": self.challenger_version,
            "trainingFamilies": list(self.training_families),
            "registrySize": self.registry_size,
            "eligibleTargets": [a.target_id for a in self.eligible],
            "passed": self.passed,
            "reason": self.reason,
            "assessments": [a.to_dict() for a in self.assessments],
            "gatesPromotion": True,
        }


# ── eligibility (pure; I/O is injected) ──────────────────────────────────────

#: ``(path, commit) -> True`` only when the preregistration is committed and
#: unchanged since (exact rule: :func:`git_preregistration_committed`).
PreregistrationCheck = Callable[[str, str], bool]
#: ``source_key -> {training family: lineage category}`` from the lineage owner.
LineageLookup = Callable[[str], Mapping[str, str]]
#: ``source_key -> B10 family``, or ``None`` when the registry does not know it.
FamilyLookup = Callable[[str], "str | None"]


def assess_target(
    target: IndependentValidationTarget,
    *,
    training_families: Iterable[str],
    preregistration_committed: PreregistrationCheck,
    lineage_for: LineageLookup,
    family_of: FamilyLookup,
) -> TargetAssessment:
    """Whether ``target`` may validate a challenger trained on ``training_families``.

    Every failed check is recorded (not only the first), so a reader sees the
    whole distance between a candidate target and eligibility."""
    fams = sorted({str(f) for f in training_families if f})
    reasons: list[str] = []
    if not fams:
        reasons.append("challenger_training_families_unknown")
    path = str(target.preregistration_path or "")
    commit = str(target.preregistration_commit or "")
    if not path or not commit:
        reasons.append("preregistration_undeclared")
    else:
        try:
            committed = bool(preregistration_committed(path, commit))
        except Exception:  # noqa: BLE001 - an unanswerable check fails closed
            committed = False
        if not committed:
            reasons.append(f"preregistration_not_committed:{path}@{commit}")
    if not target.provenance:
        reasons.append("provenance_undeclared")

    components = {c.component_id: c for c in target.provenance}
    excluded: set[str] = set()
    for fam in fams:
        treat = target.independence.get(fam)
        if treat is None:
            reasons.append(f"missing_independence_treatment:{fam}")
            continue
        if treat.treatment not in TREATMENTS:
            reasons.append(f"unknown_independence_treatment:{fam}:{treat.treatment}")
            continue
        of_family = {cid for cid, c in components.items() if c.family == fam}
        if treat.treatment == TREATMENT_NO_SHARED_PROVENANCE:
            if of_family:
                reasons.append(
                    f"treatment_contradicts_provenance:{fam}:" + ",".join(sorted(of_family))
                )
            continue
        # component_excluded -- DECLARATION ONLY: the rule never sees component
        # data, so that it actually drops these is verified at preregistration
        # review, not here (module docstring; HILL_AUTOPILOT_V2 gate 7).
        named = set(treat.excluded_components)
        if not named:
            reasons.append(f"component_excluded_names_nothing:{fam}")
        missing = named - set(components)
        if missing:
            reasons.append(f"excluded_component_unknown:{fam}:" + ",".join(sorted(missing)))
        uncovered = of_family - named
        if uncovered:
            reasons.append(f"family_component_not_excluded:{fam}:" + ",".join(sorted(uncovered)))
        excluded |= named & set(components)

    scored = [c for cid, c in sorted(components.items()) if cid not in excluded]
    if target.provenance and not scored:
        reasons.append("no_scored_provenance")
    fam_set = set(fams)
    for comp in scored:
        if comp.family in fam_set:
            reasons.append(f"derives_from_training_family:{comp.component_id}:{comp.family}")
        if not comp.source_keys:
            reasons.append(f"provenance_unverifiable:{comp.component_id}")
            continue
        for key in comp.source_keys:
            try:
                registered = family_of(key)
            except Exception:  # noqa: BLE001
                registered = None
            if registered is None:
                reasons.append(f"source_unregistered:{key}")
            elif registered != comp.family:
                reasons.append(f"family_mismatch:{key}:{registered}!={comp.family}")
            try:
                cats = dict(lineage_for(key))
            except Exception:  # noqa: BLE001 - an unanswerable lineage fails closed
                cats = {}
            for fam in fams:
                cat = cats.get(fam, "UNKNOWN")
                if cat != _LINEAGE_INDEPENDENT:
                    reasons.append(f"lineage_not_independent:{key}:{fam}:{cat}")

    return TargetAssessment(target.target_id, not reasons, tuple(reasons))


def evaluate_independent_validation(
    targets: Iterable[IndependentValidationTarget],
    *,
    challenger_version: int | None,
    training_families: Iterable[str],
    champion_c: float,
    champion_s: float,
    challenger_c: float,
    challenger_s: float,
    preregistration_committed: PreregistrationCheck,
    lineage_for: LineageLookup,
    family_of: FamilyLookup,
) -> IndependentValidationEvidence:
    """Assess every target, then run the preregistered rule of each eligible one."""
    fams = tuple(sorted({str(f) for f in training_families if f}))
    targets = tuple(targets)
    out: list[TargetAssessment] = []
    for target in targets:
        a = assess_target(
            target,
            training_families=fams,
            preregistration_committed=preregistration_committed,
            lineage_for=lineage_for,
            family_of=family_of,
        )
        if a.eligible:
            try:
                outcome = target.rule(
                    float(champion_c), float(champion_s), float(challenger_c), float(challenger_s)
                )
                passed = outcome.passed is True
                detail: Mapping[str, Any] = dict(outcome.detail)
            except Exception as exc:  # noqa: BLE001 - a broken rule never passes
                passed = False
                detail = {"ruleError": f"{type(exc).__name__}: {exc}"}
            a = TargetAssessment(a.target_id, True, (), passed, detail)
        out.append(a)
    return IndependentValidationEvidence(challenger_version, fams, len(targets), tuple(out))


# ── default (real) providers, used by scripts/hill_autopilot.py ─────────────


#: A full, lowercase git object id. Ref names and abbreviations are refused.
_FULL_SHA = re.compile(r"[0-9a-f]{40}")


def normalize_repo_path(path: str) -> str:
    """Repo-relative POSIX form: backslashes become ``/`` and leading ``./``
    SEGMENTS are removed -- never the leading ``.`` of a name (``.github``)."""
    rel = str(path).replace("\\", "/")
    while rel.startswith("./"):
        rel = rel.removeprefix("./")
    return rel


def git_preregistration_committed(
    path: str, commit: str, *, repo: Path = REPO, git_executable: str = "git"
) -> bool:
    """Whether ``path`` was preregistered at ``commit`` and is unchanged at HEAD.

    True only when ALL of these hold; anything else -- including any git error,
    a missing git, or a shallow clone (whose history boundary cannot prove
    ancestry) -- is ``False``. Never raises.

    * ``commit`` is a full 40-hex SHA that resolves to exactly itself: ref names
      (``HEAD``, ``origin/main``) and abbreviations are refused;
    * it is a STRICT ancestor of HEAD (HEAD itself is refused), so the registry
      entry that consumes it landed in a later commit;
    * ``path`` is a file (blob) at that commit;
    * its blob at HEAD is identical -- the preregistration was not edited since.
    """
    commit = str(commit or "")
    rel = normalize_repo_path(path or "")
    if not rel or not _FULL_SHA.fullmatch(commit):
        return False

    def _git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                [git_executable, *args],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None

    if _git("rev-parse", "--is-shallow-repository") != "false":
        return False
    if _git("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}") != commit:
        return False
    head = _git("rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if head is None or not _FULL_SHA.fullmatch(head) or head == commit:
        return False
    if _git("merge-base", "--is-ancestor", commit, head) is None:
        return False
    if _git("cat-file", "-t", f"{commit}:{rel}") != "blob":
        return False
    at_prereg = _git("rev-parse", "--verify", "--quiet", f"{commit}:{rel}")
    at_head = _git("rev-parse", "--verify", "--quiet", f"{head}:{rel}")
    return at_prereg is not None and at_prereg == at_head


def offense_training_lineage() -> tuple[tuple[str, ...], Mapping[str, set[str]]]:
    """The current manifest's OFFENSE training families and their lineage keys.

    Every tournament-eligible challenger was fitted under the CURRENT manifest
    (``training_run.tournament_exclusion_reason`` drops ``stale_code_or_manifest``),
    so the current manifest's trainers ARE the winner's trainers."""
    from src.model_registry.training_manifest import (  # noqa: PLC0415
        default_manifest,
        trainer_lineage_keys,
    )

    m = default_manifest()
    by_family: dict[str, set[str]] = {}
    for b in m.trainers("OFFENSE"):
        by_family.setdefault(b.family, set()).update(trainer_lineage_keys(b))
    return tuple(sorted(by_family)), by_family


def lineage_lookup(trainers_by_family: Mapping[str, Iterable[str]]) -> LineageLookup:
    """Per-source lineage categories from the ONE owner (fail closed on UNKNOWN)."""
    from src.model_registry.training_manifest import (  # noqa: PLC0415
        default_lineage_view,
        holdout_lineage,
        registry_view,
    )

    reg = registry_view()
    lineage = default_lineage_view()

    def _lookup(source_key: str) -> Mapping[str, str]:
        tags = holdout_lineage(
            source_key, trainers_by_family, lineage=lineage, family_of=reg.family_of
        )
        return {d.trainer_family: d.category for d in tags}

    return _lookup


def registry_family_lookup() -> FamilyLookup:
    from src.model_registry.training_manifest import registry_view  # noqa: PLC0415

    reg = registry_view()
    known = set(reg.csv_paths) | set(reg.ranking_game_types)

    def _family(source_key: str) -> str | None:
        return reg.family_of(source_key) if source_key in known else None

    return _family
