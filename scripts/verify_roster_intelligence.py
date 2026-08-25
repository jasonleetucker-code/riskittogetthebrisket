#!/usr/bin/env python3
"""Executable verification pack for the canonical roster-intelligence chain.

Thirteen checks over ``GET /api/roster/intelligence`` and the public
``/league?tab=teamAssignment`` section, covering V1-27 through V1-33.

**Read this before reading the output: a verification that cannot
distinguish "measured and found none" from "matched nothing" is not a
verification.**  That sentence is ``docs/lineup/C2_U1_CANONICAL_LINEUP.md``
§10a, written after a production checklist nearly passed vacuously — a
join by Sleeper id returned 0 hits because the payload keys assignments
by NAME, and 0-of-0 violations reads exactly like 0-of-240.  So every
check here publishes its own DENOMINATOR, and the harness — not the
individual check — downgrades any ``PASS`` with a zero denominator to
``UNMEASURABLE``.  A check author cannot forget to do it.

Two halves, deliberately split
==============================

``build_bundle_*`` fetches.  ``check_*`` decides, purely, from a
:class:`Bundle`.  Nothing in the check layer touches the network, which
is what lets ``tests/roster_intel/test_verification_pack.py`` drive
every check from fixtures — and is required by
``tests/infra/test_unit_suite_does_not_probe_production.py``, which
forbids the unit suite from probing production.

Evidence levels
===============

Each check declares the level its result can support, using the
vocabulary in ``docs/VERSION_1_COMPLETION_CONTRACT.md`` §"Verification
levels".  They are spelled ``EVIDENCE-L1``..``EVIDENCE-L4`` here
because that same document ALSO uses ``L1``..``L6`` for lanes, in the
same table — an ambiguity worth not importing into machine-readable
output.

  EVIDENCE-L1  deterministic — provable from config/logic alone
  EVIDENCE-L2  measured against a real board or contract
  EVIDENCE-L3  measured against a DEPLOYED response
  EVIDENCE-L4  EVIDENCE-L3 plus the user-facing surface consuming it

A check's declared level is the CEILING it can reach; a run against a
locally rebuilt contract reports EVIDENCE-L2 even for a check whose
ceiling is EVIDENCE-L3, because the evidence is only as strong as its
source.  ``--source`` records which it was.

Usage:
    python scripts/verify_roster_intelligence.py --base-url http://127.0.0.1:8000
    python scripts/verify_roster_intelligence.py --base-url "$PROD_PUBLIC_URL" \
        --league-key dynasty_main --league-key dynasty_new --json-out evidence.json
    python scripts/verify_roster_intelligence.py --offline --json-out evidence.json
        # rebuilds from the newest COMPLETE archived scrape — no server,
        # no auth, no network. Ceiling EVIDENCE-L2, never L3/L4.

Exit codes (the repo convention — ``scripts/backtest_perfect_draft.py``):
    0  every check was MEASURED and PASSED
    1  a check measured a violation
    2  one or more checks could not be measured

``2`` is deliberately distinct and is never collapsed into ``0``: "no
data" must not read as "passed".  It is also distinct from ``1``,
because "we looked and it is broken" and "we could not look" call for
different actions — the first is a defect, the second is a missing
credential, an undeployed endpoint, or a league with no contract.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

TAG = "[roster-verify]"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNMEASURED = 2

PASS = "PASS"
FAIL = "FAIL"
UNMEASURABLE = "UNMEASURABLE"

L1 = "EVIDENCE-L1"
L2 = "EVIDENCE-L2"
L3 = "EVIDENCE-L3"
L4 = "EVIDENCE-L4"

#: Owner-approved default from ``docs/GLOBAL_PERFORMANCE_STANDARD.md``:
#: "normal production p95 first useful data: <=2 seconds", with a warm
#: target of 1 second.  A cited budget, not one invented here.
LATENCY_BUDGET_MS = 2000.0
LATENCY_WARM_TARGET_MS = 1000.0

#: The multiplier the meaningful core is built with (#839 / decision 67),
#: shipped as the V1 champion and LABELLED PRIOR.  Read from the payload
#: when present; this is only the fallback for a payload that predates
#: the field, and a mismatch is reported rather than silently accepted.
EXPECTED_M = 1.5


# ---------------------------------------------------------------------------
# Result plumbing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict, carrying the evidence that produced it.

    ``denominator`` is the count of things actually examined.  It is not
    decoration: :func:`finalize` reads it, and a ``PASS`` over nothing
    becomes ``UNMEASURABLE``.
    """

    id: str
    name: str
    ceiling: str
    result: str
    denominator: int
    level: str | None = None
    reason: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "result": self.result,
            "level": self.level,
            "ceiling": self.ceiling,
            "denominator": self.denominator,
            "reason": self.reason,
            "evidence": dict(self.evidence),
        }


def unmeasurable(
    check_id: str, name: str, ceiling: str, reason: str, **evidence: Any
) -> CheckResult:
    """A check that could not run.  Never a pass, never a failure."""
    return CheckResult(
        id=check_id,
        name=name,
        ceiling=ceiling,
        result=UNMEASURABLE,
        denominator=0,
        reason=reason,
        evidence=evidence,
    )


def finalize(results: Sequence[CheckResult], *, source_level: str) -> list[CheckResult]:
    """Apply the two rules no individual check is trusted to apply itself.

    1. **Non-vacuity.**  A ``PASS`` that examined nothing is
       ``UNMEASURABLE``.  This is enforced here rather than in each
       check because "publish your denominator" is a convention and
       conventions are forgotten; a harness rule is not.  A ``FAIL``
       with a zero denominator is left alone — it is a contradiction
       the check itself is asserting, and hiding it would be worse.
    2. **Level ceiling.**  Evidence is only as strong as its source, so
       a check whose ceiling is EVIDENCE-L3 reports EVIDENCE-L2 when the
       run read a locally rebuilt contract.
    """
    order = [L1, L2, L3, L4]
    cap = order.index(source_level)
    out: list[CheckResult] = []
    for r in results:
        result, reason = r.result, r.reason
        if result == PASS and r.denominator <= 0:
            result = UNMEASURABLE
            reason = (
                "vacuous: the check passed having examined 0 items. "
                "0-of-0 is not evidence of compliance."
            )
        level = None
        if result != UNMEASURABLE:
            level = order[min(order.index(r.ceiling), cap)]
        out.append(
            CheckResult(
                id=r.id,
                name=r.name,
                ceiling=r.ceiling,
                result=result,
                denominator=r.denominator,
                level=level,
                reason=reason,
                evidence=r.evidence,
            )
        )
    return out


def exit_code_for(results: Sequence[CheckResult]) -> int:
    """Failures outrank unmeasured; both outrank success."""
    if any(r.result == FAIL for r in results):
        return EXIT_FAILED
    if any(r.result == UNMEASURABLE for r in results):
        return EXIT_UNMEASURED
    return EXIT_OK


# ---------------------------------------------------------------------------
# The bundle a check reasons over
# ---------------------------------------------------------------------------


@dataclass
class Bundle:
    """Everything one league's checks may read.  Any field may be absent.

    Absent is UNKNOWN, and every check that needs a missing field says
    ``UNMEASURABLE`` with a named reason rather than treating the gap as
    a clean result.
    """

    league_key: str
    registry: Mapping[str, Any] | None = None
    intelligence: Mapping[str, Any] | None = None
    team_assignment: Mapping[str, Any] | None = None
    latency_ms: dict[str, float] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def teams(self) -> list[Mapping[str, Any]]:
        payload = self.intelligence or {}
        teams = payload.get("teams")
        if isinstance(teams, Mapping):
            return [t for t in teams.values() if isinstance(t, Mapping)]
        if isinstance(teams, list):
            return [t for t in teams if isinstance(t, Mapping)]
        return []


def _members(team: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    core = team.get("core")
    if not isinstance(core, Mapping):
        return []
    return [m for m in (core.get("members") or []) if isinstance(m, Mapping)]


# ---------------------------------------------------------------------------
# The thirteen checks.  Pure functions of a Bundle (or of every Bundle).
# ---------------------------------------------------------------------------


def check_01_both_leagues(bundles: Sequence[Bundle]) -> CheckResult:
    """Every ACTIVE configured league answers, or says why it cannot.

    The denominator is the registry's active-league count, not the count
    that happened to respond — otherwise a run that reached one league
    of two would report "1 of 1".  That inversion is precisely how a
    partial verification reads as a complete one.
    """
    name = "every active configured league answers"
    if not bundles:
        return unmeasurable("01", name, L3, "no leagues resolved from the registry")

    answered, missing = [], []
    for b in bundles:
        if isinstance(b.intelligence, Mapping) and b.teams:
            answered.append(b.league_key)
        else:
            missing.append(
                {
                    "leagueKey": b.league_key,
                    "reason": b.errors.get("intelligence", "no teams in payload"),
                }
            )

    evidence = {
        "expected": [b.league_key for b in bundles],
        "answered": answered,
        "missing": missing,
    }
    if missing:
        return CheckResult(
            "01",
            name,
            L3,
            UNMEASURABLE,
            len(bundles),
            reason=(
                f"{len(missing)} of {len(bundles)} active leagues did not answer. "
                "Reported UNMEASURABLE rather than FAIL: a league with no loaded "
                "contract is un-probed, not defective."
            ),
            evidence=evidence,
        )
    return CheckResult("01", name, L3, PASS, len(bundles), evidence=evidence)


def check_02_threshold_scaling(bundle: Bundle) -> CheckResult:
    """Weakness thresholds scale with the league's OWN team count.

    ``thresholdRank == rung x teamCount``.  A 12-team league's QB2 line
    is rank 24; a 10-team league's is rank 20.  A hard-coded 12 would
    pass silently on ``dynasty_main`` and misprice every rung in
    ``dynasty_new``, which is why this is checked per league rather than
    once.
    """
    name = "weakness thresholds scale with teamCount"
    payload = bundle.intelligence
    if not isinstance(payload, Mapping):
        return unmeasurable(
            "02", name, L1, "no roster-intelligence payload", leagueKey=bundle.league_key
        )

    declared = payload.get("teamCount")
    registry_count = (bundle.registry or {}).get("teamCount")
    if not isinstance(declared, int) or declared <= 0:
        return unmeasurable(
            "02", name, L1, "payload declares no usable teamCount", leagueKey=bundle.league_key
        )

    violations: list[dict[str, Any]] = []
    examined = 0
    if isinstance(registry_count, int) and registry_count != declared:
        violations.append(
            {
                "kind": "teamCount_disagrees_with_registry",
                "payload": declared,
                "registry": registry_count,
            }
        )

    for team in bundle.teams:
        weakness = team.get("weakness")
        if not isinstance(weakness, Mapping):
            continue
        if weakness.get("available") is False:
            continue
        for need in weakness.get("needs") or []:
            if not isinstance(need, Mapping):
                continue
            for rung in need.get("rungs") or []:
                if not isinstance(rung, Mapping):
                    continue
                idx, threshold = rung.get("rung"), rung.get("thresholdRank")
                if not isinstance(idx, int) or not isinstance(threshold, int):
                    continue
                examined += 1
                if threshold != idx * declared:
                    violations.append(
                        {
                            "ownerId": team.get("ownerId"),
                            "label": rung.get("label"),
                            "rung": idx,
                            "thresholdRank": threshold,
                            "expected": idx * declared,
                        }
                    )

    evidence = {
        "leagueKey": bundle.league_key,
        "teamCount": declared,
        "registryTeamCount": registry_count,
        "rungsExamined": examined,
        "violations": violations[:20],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "02",
            name,
            L1,
            FAIL,
            examined,
            reason=f"{len(violations)} rung thresholds do not equal rung x {declared}",
            evidence=evidence,
        )
    return CheckResult("02", name, L1, PASS, examined, evidence=evidence)


_FLEX_FAMILIES = ("FLEX", "SUPER_FLEX", "IDP_FLEX")


def check_03_flex_from_config(bundle: Bundle) -> CheckResult:
    """FLEX / SUPER_FLEX / IDP-FLEX come from the league's ACTUAL config.

    Two properties, and the second is the one a naive check misses:

    * the slot list names its SOURCE (``sleeper_roster_positions`` or
      ``registry_starters``).  ``None`` is the ladder's refusal, and a
      payload that produced slots from neither rung invented them;
    * every declared flex slot is ACCOUNTED FOR — seated by a member or
      listed in ``unfilledStarterSlots``.  Without this, a solver that
      silently skipped the flex slots would still show a plausible
      lineup, and the count check alone would pass.
    """
    name = "flex slots come from actual league configuration"
    payload = bundle.intelligence
    if not isinstance(payload, Mapping):
        return unmeasurable(
            "03", name, L2, "no roster-intelligence payload", leagueKey=bundle.league_key
        )

    slot_source = payload.get("slotSource")
    declared = [str(s) for s in (payload.get("starterSlots") or [])]
    flex_declared = [s for s in declared if s in _FLEX_FAMILIES]

    if not slot_source:
        return CheckResult(
            "03",
            name,
            L2,
            FAIL,
            len(declared),
            reason="slotSource is absent — the slot list came from neither ladder rung, so it was invented",
            evidence={"leagueKey": bundle.league_key, "starterSlots": declared},
        )
    if not flex_declared:
        return unmeasurable(
            "03",
            name,
            L2,
            "this league declares no FLEX/SUPER_FLEX/IDP_FLEX slot, so there is nothing to verify",
            leagueKey=bundle.league_key,
            slotSource=slot_source,
            starterSlots=declared,
        )

    examined, violations = 0, []
    for team in bundle.teams:
        core = team.get("core")
        if not isinstance(core, Mapping) or core.get("available") is False:
            continue
        seated: dict[str, int] = {}
        for m in _members(team):
            if m.get("role") == "starter" and str(m.get("slot")) in _FLEX_FAMILIES:
                seated[str(m["slot"])] = seated.get(str(m["slot"]), 0) + 1
        unfilled = [str(s) for s in (core.get("unfilledStarterSlots") or [])]
        for fam in _FLEX_FAMILIES:
            want = flex_declared.count(fam)
            if not want:
                continue
            examined += want
            got = seated.get(fam, 0) + unfilled.count(fam)
            if got != want:
                violations.append(
                    {
                        "ownerId": team.get("ownerId"),
                        "slot": fam,
                        "declared": want,
                        "accountedFor": got,
                        "seated": seated.get(fam, 0),
                        "unfilled": unfilled.count(fam),
                    }
                )

    evidence = {
        "leagueKey": bundle.league_key,
        "slotSource": slot_source,
        "flexSlotsDeclared": flex_declared,
        "flexSlotsExamined": examined,
        "violations": violations[:20],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "03",
            name,
            L2,
            FAIL,
            examined,
            reason=f"{len(violations)} declared flex slots were neither seated nor reported unfilled",
            evidence=evidence,
        )
    return CheckResult("03", name, L2, PASS, examined, evidence=evidence)


def check_04_player_at_most_once(bundle: Bundle) -> CheckResult:
    """No player appears twice in one team's meaningful core.

    Decision 72: "a player used at FLEX cannot also count as
    native-position depth; every player counts at most once."  Checked
    as a multiset over ``core.members``, which is the population every
    downstream aggregate sums.
    """
    name = "every player appears at most once per core"
    if not isinstance(bundle.intelligence, Mapping):
        return unmeasurable(
            "04", name, L2, "no roster-intelligence payload", leagueKey=bundle.league_key
        )

    examined, violations = 0, []
    for team in bundle.teams:
        seen: dict[str, int] = {}
        for m in _members(team):
            pid = str(m.get("playerId") or "")
            if not pid:
                continue
            examined += 1
            seen[pid] = seen.get(pid, 0) + 1
        dupes = {pid: n for pid, n in seen.items() if n > 1}
        if dupes:
            violations.append({"ownerId": team.get("ownerId"), "duplicates": dupes})

    evidence = {
        "leagueKey": bundle.league_key,
        "membersExamined": examined,
        "violations": violations[:20],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "04",
            name,
            L2,
            FAIL,
            examined,
            reason=f"{len(violations)} teams double-count a player",
            evidence=evidence,
        )
    return CheckResult("04", name, L2, PASS, examined, evidence=evidence)


def check_05_starters_before_reserves(bundle: Bundle) -> CheckResult:
    """Starters are removed from the pool before the reserve solve.

    The observable consequence of the #899 ordering: the starter and
    reserve sets are DISJOINT.  A reserve solve that ran over the whole
    roster would re-select the best players it had just seated.
    """
    name = "starters are removed before the reserve solve"
    if not isinstance(bundle.intelligence, Mapping):
        return unmeasurable(
            "05", name, L2, "no roster-intelligence payload", leagueKey=bundle.league_key
        )

    examined, violations = 0, []
    for team in bundle.teams:
        starters = {str(m.get("playerId")) for m in _members(team) if m.get("role") == "starter"}
        reserves = {str(m.get("playerId")) for m in _members(team) if m.get("role") == "reserve"}
        examined += len(starters)
        overlap = sorted(starters & reserves)
        if overlap:
            violations.append(
                {"ownerId": team.get("ownerId"), "inBoth": overlap[:10], "count": len(overlap)}
            )

    evidence = {
        "leagueKey": bundle.league_key,
        "startersExamined": examined,
        "violations": violations[:20],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "05",
            name,
            L2,
            FAIL,
            examined,
            reason=f"{len(violations)} teams seat a player as both starter and reserve",
            evidence=evidence,
        )
    return CheckResult("05", name, L2, PASS, examined, evidence=evidence)


def check_06_core_ceiling(bundle: Bundle) -> CheckResult:
    """The core never exceeds ``starters + reserve demand``.

    ``reserve_demand(p) = ceil(M x starters(p)) - starters(p)``, so the
    ceiling is ``starterSlots + demand.total``.  Also re-derives the
    multiplier's own arithmetic from the published basis, because a
    ceiling computed from a wrong demand would be self-consistent and
    still wrong.
    """
    name = "core size respects starters + reserve demand"
    if not isinstance(bundle.intelligence, Mapping):
        return unmeasurable(
            "06", name, L2, "no roster-intelligence payload", leagueKey=bundle.league_key
        )

    examined, violations = 0, []
    for team in bundle.teams:
        core = team.get("core")
        if not isinstance(core, Mapping) or core.get("available") is False:
            continue
        demand = core.get("demand")
        if not isinstance(demand, Mapping):
            continue
        slots = [str(s) for s in (core.get("starterSlots") or [])]
        total_demand = demand.get("total")
        if not isinstance(total_demand, int):
            continue
        examined += 1
        ceiling = len(slots) + total_demand
        actual = len(_members(team))
        if actual > ceiling:
            violations.append(
                {
                    "ownerId": team.get("ownerId"),
                    "coreSize": actual,
                    "ceiling": ceiling,
                    "starterSlots": len(slots),
                    "reserveDemand": total_demand,
                }
            )

        m = demand.get("multiplier", EXPECTED_M)
        basis = demand.get("dedicatedBasis")
        by_slot = demand.get("bySlot")
        if (
            isinstance(basis, Mapping)
            and isinstance(by_slot, Mapping)
            and isinstance(m, (int, float))
        ):
            for pos, starters in basis.items():
                if not isinstance(starters, int) or starters <= 0:
                    continue
                want = math.ceil(m * starters) - starters
                got = by_slot.get(pos)
                if isinstance(got, int) and got != want:
                    violations.append(
                        {
                            "ownerId": team.get("ownerId"),
                            "slot": pos,
                            "starters": starters,
                            "multiplier": m,
                            "reserveDemand": got,
                            "expected": want,
                        }
                    )

    evidence = {
        "leagueKey": bundle.league_key,
        "teamsExamined": examined,
        "violations": violations[:20],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "06",
            name,
            L2,
            FAIL,
            examined,
            reason=f"{len(violations)} ceiling/demand violations",
            evidence=evidence,
        )
    return CheckResult("06", name, L2, PASS, examined, evidence=evidence)


def check_07_unpriced_reported(bundle: Bundle) -> CheckResult:
    """Unpriced rostered players are REPORTED, and reported once.

    The defect this exists for is not "some players are unpriced" — it
    is that they used to be structurally invisible.  ``ros_value=0.0``
    was appended for every row that would not match, so ``unpricedIds``
    came back empty not because everyone was priced but because the
    unpriced arrived indistinguishable from the worthless.

    Two properties, because "zero unpriced" is a legitimate answer and
    must not be forced to fail:

    * ``core.unpricedIds`` and ``strength.unpricedIds`` are the SAME
      fact and must agree — two publishers, one truth;
    * if a league reports zero unpriced while carrying members valued at
      exactly ``0.0``, that is the coercion signature and it fails.
    """
    name = "unpriced rostered players are reported, not coerced"
    if not isinstance(bundle.intelligence, Mapping):
        return unmeasurable(
            "07", name, L2, "no roster-intelligence payload", leagueKey=bundle.league_key
        )

    examined, violations = 0, []
    total_unpriced, zero_valued = 0, 0
    for team in bundle.teams:
        core, strength = team.get("core"), team.get("strength")
        if not isinstance(core, Mapping) or not isinstance(strength, Mapping):
            continue
        examined += int(team.get("rosteredCount") or 0)
        core_ids = set(core.get("unpricedIds") or [])
        strength_ids = set(strength.get("unpricedIds") or [])
        total_unpriced += len(core_ids)
        if core_ids != strength_ids:
            violations.append(
                {
                    "ownerId": team.get("ownerId"),
                    "kind": "publishers_disagree",
                    "onlyInCore": sorted(core_ids - strength_ids)[:5],
                    "onlyInStrength": sorted(strength_ids - core_ids)[:5],
                }
            )
        zeros = [str(m.get("playerId")) for m in _members(team) if m.get("value") == 0]
        zero_valued += len(zeros)
        if zeros and not core_ids:
            violations.append(
                {
                    "ownerId": team.get("ownerId"),
                    "kind": "zero_valued_members_but_none_reported_unpriced",
                    "zeroValuedMembers": zeros[:5],
                }
            )

    if not examined:
        return unmeasurable(
            "07", name, L2, "no rostered players in any team", leagueKey=bundle.league_key
        )

    evidence = {
        "leagueKey": bundle.league_key,
        "rosteredExamined": examined,
        "unpricedReported": total_unpriced,
        "zeroValuedMembers": zero_valued,
        "violations": violations[:20],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "07",
            name,
            L2,
            FAIL,
            examined,
            reason=f"{len(violations)} unpriced-reporting violations",
            evidence=evidence,
        )
    return CheckResult("07", name, L2, PASS, examined, evidence=evidence)


def check_08_missing_is_never_zero(bundle: Bundle) -> CheckResult:
    """An unpriced player is UNKNOWN — never a scored member worth 0.

    The structural form of MISSING IS NEVER ZERO: ``unpricedIds`` and
    the scored ``members`` must be DISJOINT.  A player in both would be
    declared unknown and simultaneously summed into Team Strength, which
    is the coercion wearing a disclosure.
    """
    name = "unpriced players are excluded from every value aggregate"
    if not isinstance(bundle.intelligence, Mapping):
        return unmeasurable(
            "08", name, L2, "no roster-intelligence payload", leagueKey=bundle.league_key
        )

    examined, violations = 0, []
    for team in bundle.teams:
        core = team.get("core")
        if not isinstance(core, Mapping):
            continue
        unpriced = {str(x) for x in (core.get("unpricedIds") or [])}
        examined += len(unpriced)
        member_ids = {str(m.get("playerId")) for m in _members(team)}
        both = sorted(unpriced & member_ids)
        if both:
            violations.append(
                {"ownerId": team.get("ownerId"), "unpricedButScored": both[:10], "count": len(both)}
            )

    if not examined:
        return unmeasurable(
            "08",
            name,
            L2,
            "no unpriced players anywhere in this league, so the exclusion rule was not exercised",
            leagueKey=bundle.league_key,
        )

    evidence = {
        "leagueKey": bundle.league_key,
        "unpricedExamined": examined,
        "violations": violations[:20],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "08",
            name,
            L2,
            FAIL,
            examined,
            reason=f"{len(violations)} teams score a player they declared unpriced",
            evidence=evidence,
        )
    return CheckResult("08", name, L2, PASS, examined, evidence=evidence)


def check_09_strength_groups_resum(bundle: Bundle) -> CheckResult:
    """Team Strength position groups re-sum to the published total.

    Tolerance is derived, not chosen: each group's ``value`` is rounded
    to 3 dp independently, so N groups can drift by up to N x 0.0005
    from the rounded total by rounding alone.  Anything beyond that is a
    partition defect — a player in no group, or in two.
    """
    name = "Team Strength position groups re-sum to total"
    if not isinstance(bundle.intelligence, Mapping):
        return unmeasurable(
            "09", name, L2, "no roster-intelligence payload", leagueKey=bundle.league_key
        )

    examined, violations = 0, []
    for team in bundle.teams:
        strength = team.get("strength")
        if not isinstance(strength, Mapping) or strength.get("available") is False:
            continue
        groups = [g for g in (strength.get("byPosition") or []) if isinstance(g, Mapping)]
        total = strength.get("total")
        if not isinstance(total, (int, float)):
            continue
        examined += 1
        summed = sum(float(g.get("value") or 0.0) for g in groups)
        tolerance = 0.0005 * max(len(groups), 1) + 1e-6
        if abs(summed - float(total)) > tolerance:
            violations.append(
                {
                    "ownerId": team.get("ownerId"),
                    "total": total,
                    "groupSum": round(summed, 4),
                    "delta": round(summed - float(total), 4),
                    "groups": len(groups),
                    "tolerance": tolerance,
                }
            )
        # Starter + reserve must also partition the same total.
        sv, rv = strength.get("starterValue"), strength.get("reserveValue")
        if isinstance(sv, (int, float)) and isinstance(rv, (int, float)):
            if abs((float(sv) + float(rv)) - float(total)) > 0.0015:
                violations.append(
                    {
                        "ownerId": team.get("ownerId"),
                        "kind": "starter_plus_reserve_ne_total",
                        "starterValue": sv,
                        "reserveValue": rv,
                        "total": total,
                    }
                )

    evidence = {
        "leagueKey": bundle.league_key,
        "teamsExamined": examined,
        "violations": violations[:20],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "09",
            name,
            L2,
            FAIL,
            examined,
            reason=f"{len(violations)} teams' groups do not re-sum to total",
            evidence=evidence,
        )
    return CheckResult("09", name, L2, PASS, examined, evidence=evidence)


def check_10_weakness_no_double_credit(bundle: Bundle) -> CheckResult:
    """No player is credited to two weakness rungs on the same team.

    A rung answers "who is your QB2?"  One player cannot be both the QB1
    and the QB2 answer; if he were, a one-deep room would read as two
    filled rungs and the need would vanish.
    """
    name = "weakness credits no player to two rungs"
    if not isinstance(bundle.intelligence, Mapping):
        return unmeasurable(
            "10", name, L2, "no roster-intelligence payload", leagueKey=bundle.league_key
        )

    examined, violations = 0, []
    for team in bundle.teams:
        weakness = team.get("weakness")
        if not isinstance(weakness, Mapping) or weakness.get("available") is False:
            continue
        seen: dict[str, list[str]] = {}
        for need in weakness.get("needs") or []:
            if not isinstance(need, Mapping):
                continue
            for rung in need.get("rungs") or []:
                if not isinstance(rung, Mapping):
                    continue
                pid = rung.get("playerId")
                if not pid:
                    continue
                examined += 1
                seen.setdefault(str(pid), []).append(str(rung.get("label") or ""))
        dupes = {pid: labels for pid, labels in seen.items() if len(labels) > 1}
        if dupes:
            violations.append({"ownerId": team.get("ownerId"), "duplicates": dupes})

    if not examined:
        return unmeasurable(
            "10",
            name,
            L2,
            "no weakness rung names a player, so no credit could be double-counted",
            leagueKey=bundle.league_key,
        )

    evidence = {
        "leagueKey": bundle.league_key,
        "rungCreditsExamined": examined,
        "violations": violations[:20],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "10",
            name,
            L2,
            FAIL,
            examined,
            reason=f"{len(violations)} teams credit one player to two rungs",
            evidence=evidence,
        )
    return CheckResult("10", name, L2, PASS, examined, evidence=evidence)


def check_11_young_core_scope_and_disclosure(bundle: Bundle) -> CheckResult:
    """Young Core is measured over the CORE, and says it is a PRIOR.

    Scope is checked through the portfolio's own coverage block: its
    ``totalPlayers`` must equal the core's member count and its
    ``totalValue`` must equal Team Strength's total.  A portfolio
    computed over the whole roster would silently pass a "does it have a
    number" check and fail both of these.

    The disclosure half is not cosmetic — ``#838`` ships the index as
    the V1 champion LABELLED ``PRIOR`` (validation against intuitive
    league examples not yet run), and a payload that drops the label
    presents an unvalidated number as a measured one.
    """
    name = "Young Core uses core-only value and discloses PRIOR"
    if not isinstance(bundle.intelligence, Mapping):
        return unmeasurable(
            "11", name, L2, "no roster-intelligence payload", leagueKey=bundle.league_key
        )

    examined, violations = 0, []
    for team in bundle.teams:
        age = team.get("agePortfolio")
        core = team.get("core")
        strength = team.get("strength")
        if not isinstance(age, Mapping) or age.get("available") is False:
            continue
        if not isinstance(core, Mapping) or not isinstance(strength, Mapping):
            continue
        examined += 1
        oid = team.get("ownerId")

        if age.get("youngCoreIndexStatus") != "PRIOR":
            violations.append(
                {
                    "ownerId": oid,
                    "kind": "missing_prior_disclosure",
                    "youngCoreIndexStatus": age.get("youngCoreIndexStatus"),
                }
            )
        if "valueWeightedRosterAge" not in age or "valueWeightedCoreAge" not in age:
            violations.append({"ownerId": oid, "kind": "core_and_roster_age_not_separately_named"})

        coverage = age.get("coverage")
        if isinstance(coverage, Mapping):
            n_members = len(_members(team))
            total_players = coverage.get("totalPlayers")
            if isinstance(total_players, int) and total_players != n_members:
                violations.append(
                    {
                        "ownerId": oid,
                        "kind": "population_is_not_the_core",
                        "coverageTotalPlayers": total_players,
                        "coreMembers": n_members,
                    }
                )
            total_value, strength_total = coverage.get("totalValue"), strength.get("total")
            if isinstance(total_value, (int, float)) and isinstance(strength_total, (int, float)):
                if abs(float(total_value) - float(strength_total)) > 0.0015:
                    violations.append(
                        {
                            "ownerId": oid,
                            "kind": "value_is_not_the_core_value",
                            "coverageTotalValue": total_value,
                            "teamStrengthTotal": strength_total,
                        }
                    )

    evidence = {
        "leagueKey": bundle.league_key,
        "portfoliosExamined": examined,
        "violations": violations[:20],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "11",
            name,
            L2,
            FAIL,
            examined,
            reason=f"{len(violations)} Young Core scope/disclosure violations",
            evidence=evidence,
        )
    return CheckResult("11", name, L2, PASS, examined, evidence=evidence)


def check_12_team_assignment_degrades_honestly(bundle: Bundle) -> CheckResult:
    """A degraded teamAssignment names its cause; it never invents one.

    ``#815``: production served ``{"assignments": []}`` with HTTP 200
    during a degraded snapshot and nothing distinguished "we asked and
    the answer is none" from "we could not ask", so the page printed a
    cause it had not measured.  The contract is three states, and the
    illegal one is empty-and-available-and-unexplained.
    """
    name = "teamAssignment reports unavailable rather than inventing a cause"
    section = bundle.team_assignment
    if not isinstance(section, Mapping):
        return unmeasurable(
            "12",
            name,
            L4,
            bundle.errors.get("team_assignment", "no teamAssignment section fetched"),
            leagueKey=bundle.league_key,
        )

    available = section.get("available")
    reason = section.get("unavailableReason")
    assignments = section.get("assignments") or []
    evidence = {
        "leagueKey": bundle.league_key,
        "available": available,
        "unavailableReason": reason,
        "assignments": len(assignments),
        "rosterScoringAvailable": section.get("rosterScoringAvailable"),
    }

    if available is None:
        return CheckResult(
            "12",
            name,
            L4,
            FAIL,
            1,
            reason="the section predates the availability flag: healthy and degraded are indistinguishable",
            evidence=evidence,
        )
    if available is False:
        if not reason:
            return CheckResult(
                "12", name, L4, FAIL, 1, reason="unavailable with no named cause", evidence=evidence
            )
        return CheckResult("12", name, L4, PASS, 1, evidence=evidence)
    if not assignments:
        return CheckResult(
            "12",
            name,
            L4,
            FAIL,
            1,
            reason="available: true with zero assignments and no reason — the #815 state exactly",
            evidence=evidence,
        )
    return CheckResult("12", name, L4, PASS, 1, evidence=evidence)


def check_13_latency(bundle: Bundle) -> CheckResult:
    """Endpoint latency against the owner-approved performance budget.

    ``docs/GLOBAL_PERFORMANCE_STANDARD.md``: "normal production p95
    first useful data: <=2 seconds", warm target 1 second.  A cited
    budget rather than one invented here, and a single sample is
    reported as a single sample — this is a smoke measurement, not a p95.
    """
    name = "endpoint latency within the performance budget"
    if not bundle.latency_ms:
        return unmeasurable(
            "13",
            name,
            L3,
            "no request was timed (nothing was fetched over HTTP)",
            leagueKey=bundle.league_key,
        )

    over = {k: round(v, 1) for k, v in bundle.latency_ms.items() if v > LATENCY_BUDGET_MS}
    evidence = {
        "leagueKey": bundle.league_key,
        "measuredMs": {k: round(v, 1) for k, v in bundle.latency_ms.items()},
        "budgetMs": LATENCY_BUDGET_MS,
        "warmTargetMs": LATENCY_WARM_TARGET_MS,
        "samples": 1,
        "note": "single sample per endpoint — a smoke measurement, not a p95",
        "overBudget": over,
    }
    if over:
        return CheckResult(
            "13",
            name,
            L3,
            FAIL,
            len(bundle.latency_ms),
            reason=f"{len(over)} endpoints exceeded the {LATENCY_BUDGET_MS:.0f} ms budget",
            evidence=evidence,
        )
    return CheckResult("13", name, L3, PASS, len(bundle.latency_ms), evidence=evidence)


#: Per-league checks, in report order.  Check 01 is league-SET scoped and
#: runs separately.
PER_LEAGUE_CHECKS: tuple[Callable[[Bundle], CheckResult], ...] = (
    check_02_threshold_scaling,
    check_03_flex_from_config,
    check_04_player_at_most_once,
    check_05_starters_before_reserves,
    check_06_core_ceiling,
    check_07_unpriced_reported,
    check_08_missing_is_never_zero,
    check_09_strength_groups_resum,
    check_10_weakness_no_double_credit,
    check_11_young_core_scope_and_disclosure,
    check_12_team_assignment_degrades_honestly,
    check_13_latency,
)


def run_checks(bundles: Sequence[Bundle], *, source_level: str = L3) -> list[CheckResult]:
    """Every check over every league, finalized.  Pure; no network."""
    results = [check_01_both_leagues(bundles)]
    for bundle in bundles:
        for check in PER_LEAGUE_CHECKS:
            r = check(bundle)
            results.append(
                CheckResult(
                    id=f"{r.id}/{bundle.league_key}",
                    name=r.name,
                    ceiling=r.ceiling,
                    result=r.result,
                    denominator=r.denominator,
                    level=r.level,
                    reason=r.reason,
                    evidence=r.evidence,
                )
            )
    return finalize(results, source_level=source_level)


# ---------------------------------------------------------------------------
# Transport.  Nothing above this line touches the network.
# ---------------------------------------------------------------------------

_ATTEMPTS = 3
_SLEEP_SECONDS = 4
_TIMEOUT_SECONDS = 30


class Unauthenticated(Exception):
    """The endpoint answered, and told us we may not look.

    A 401/403 is a definitive answer, not a transient blip: the service
    is up and correctly refusing an anonymous caller.  Retrying it is
    guaranteed to fail identically — ``verify-sharp-production.yml``
    spent 40 minutes per run learning that — and reporting it as a
    timeout hides a credential problem behind what looks like a slow
    deploy.
    """


def fetch_json(url: str, *, headers: Mapping[str, str]) -> tuple[Any, float]:
    """``(payload, elapsed_ms)``.  Raises on terminal or exhausted failure."""
    last = ""
    for attempt in range(1, _ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "roster-intelligence-verify/1.0",
                    "Cache-Control": "no-cache",
                    **dict(headers),
                },
            )
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                body = json.loads(response.read().decode("utf-8"))
                return body, (time.perf_counter() - started) * 1000.0
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise Unauthenticated(
                    f"HTTP {exc.code} from {url} — the service answered and "
                    "refused this caller. Most private routes sit behind "
                    "server.py::_private_api_gate; supply a session via "
                    "ROSTER_VERIFY_COOKIE or a token via ROSTER_VERIFY_BEARER. "
                    "A refusal on a route that should be PUBLIC is itself the "
                    "finding — check the route's gate rather than the credential."
                ) from exc
            last = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 — reported, never swallowed
            last = repr(exc)
        if attempt < _ATTEMPTS:
            time.sleep(_SLEEP_SECONDS)
    raise RuntimeError(f"{url}: {last}")


def _auth_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    cookie = os.environ.get("ROSTER_VERIFY_COOKIE", "").strip()
    bearer = os.environ.get("ROSTER_VERIFY_BEARER", "").strip()
    if cookie:
        headers["Cookie"] = cookie
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def build_bundle_http(base_url: str, league_key: str, registry: Mapping[str, Any] | None) -> Bundle:
    """Fetch one league's payloads.  Every failure is recorded, not raised."""
    bundle = Bundle(league_key=league_key, registry=registry)
    headers = _auth_headers()
    base = base_url.rstrip("/")
    targets = {
        "intelligence": f"{base}/api/roster/intelligence?leagueKey={league_key}",
        "team_assignment": f"{base}/api/public/league/teamAssignment?leagueKey={league_key}",
    }
    for field_name, url in targets.items():
        try:
            payload, elapsed = fetch_json(url, headers=headers)
        except Unauthenticated as exc:
            bundle.errors[field_name] = str(exc)
            continue
        except Exception as exc:  # noqa: BLE001
            bundle.errors[field_name] = f"unreachable: {exc}"
            continue
        bundle.latency_ms[field_name] = elapsed
        if field_name == "team_assignment" and isinstance(payload, Mapping):
            payload = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
        setattr(bundle, field_name, payload if isinstance(payload, Mapping) else None)
        if not isinstance(payload, Mapping):
            bundle.errors[field_name] = "response was not a JSON object"
    return bundle


def build_bundle_offline(
    league_key: str, registry: Mapping[str, Any] | None
) -> tuple[Bundle, str | None]:
    """Rebuild one league's payload from the newest COMPLETE archived scrape.

    EVIDENCE-L2, never higher: this reads a locally rebuilt contract, not
    a deployed response.  It exists because the pack's own documented
    offline command — ``pytest tests/roster_intel/test_verification_pack.py``
    — drives every check from a hand-built synthetic fixture and proves
    the checks are LIVE (RED on a violated payload), not that they hold
    on a real board.  ``V1_ROSTER_VERIFICATION_PACK.md`` §3's "216
    rungs" / "215 rung credits" table was produced against
    ``newest_complete_raw_payload()`` by hand, with no committed command
    to reproduce it.  This is that command, mirroring ``build_bundle_http``
    exactly except for where the payload comes from.

    ``team_assignment`` is left unset: the public teamAssignment section
    is a deploy-time overlay this archive does not carry, so check 12
    correctly reports UNMEASURABLE rather than a fabricated pass.

    ``bundle.latency_ms`` is likewise left EMPTY, deliberately: check 13
    polices HTTP endpoint latency against a p95 budget, and timing this
    function's local dict/CPU work would let it silently report a
    fabricated "PASS" for a quantity — a network round-trip — that was
    never measured. Local build time is not the evidence this check
    claims to carry.
    """
    from src.api.data_contract import build_api_data_contract
    from src.api.roster_intelligence import build_league_roster_intelligence
    from tests.archive_fixtures import newest_complete_raw_payload

    bundle = Bundle(league_key=league_key, registry=registry)
    raw, source_path = newest_complete_raw_payload()
    if raw is None:
        bundle.errors["intelligence"] = "no complete archived scrape available"
        return bundle, None

    contract = build_api_data_contract(raw)
    team_count = (registry or {}).get("teamCount")
    bundle.intelligence = build_league_roster_intelligence(
        contract, team_count=team_count if isinstance(team_count, int) else None
    )
    return bundle, source_path


def _registry_entries(keys: Sequence[str] | None) -> list[tuple[str, dict[str, Any]]]:
    """Active leagues from the local registry, or exactly the keys asked for."""
    from src.api.league_registry import (
        active_leagues,
        get_league_by_key,
        get_league_roster_settings,
    )

    if keys:
        out = []
        for key in keys:
            cfg = get_league_by_key(key)
            settings = get_league_roster_settings(key) if cfg else {}
            out.append(
                (
                    key,
                    {
                        "teamCount": getattr(cfg, "team_count", None) if cfg else None,
                        "known": cfg is not None,
                        **(settings or {}),
                    },
                )
            )
        return out
    return [
        (
            cfg.key,
            {
                "teamCount": getattr(cfg, "team_count", None),
                "known": True,
                **(get_league_roster_settings(cfg.key) or {}),
            },
        )
        for cfg in active_leagues()
    ]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render(
    results: Sequence[CheckResult],
    *,
    base_url: str,
    source: str,
    source_level: str,
    expect_sha: str | None,
) -> None:
    print(f"{TAG} source={source}  sourceLevel={source_level}")
    print(f"{TAG} baseUrl={base_url or '(none — offline run)'}")
    if expect_sha:
        print(f"{TAG} operatorAssertedSha={expect_sha}")
    print(
        f"{TAG} NOTE: no API surface publishes the deployed commit, so an "
        "EVIDENCE-L3 claim binds to the SHA the OPERATOR asserts, recorded "
        "above and in the artifact. Record it from the deploy run, not from here."
    )
    print("")
    width = max((len(r.id) for r in results), default=4)
    for r in results:
        print(
            f"  {r.result:<13} {r.id:<{width}}  {r.name}  " f"[{r.level or '—'}; n={r.denominator}]"
        )
        if r.reason:
            print(f"                {' ' * width}  → {r.reason}")
    print("")
    failed = [r for r in results if r.result == FAIL]
    unmeasured = [r for r in results if r.result == UNMEASURABLE]
    passed = [r for r in results if r.result == PASS]
    print(f"{TAG} ── verdict ──")
    print(f"{TAG} {len(passed)} passed · {len(failed)} failed · {len(unmeasured)} unmeasurable")
    for r in failed:
        print(f"{TAG} ::error title=Roster verification failed::{r.id} {r.name}: {r.reason}")
    for r in unmeasured:
        print(
            f"{TAG} ::warning title=Roster verification could not measure::{r.id} {r.name}: {r.reason}"
        )
    if unmeasured and not failed:
        print(f"{TAG} exit 2 — 'could not measure' is NOT 'passed'.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ROSTER_VERIFY_BASE_URL", ""),
        help="Server origin to probe, e.g. http://127.0.0.1:8000. Required, and "
        "deliberately has NO default: an unset origin is an outage to "
        "surface, not a value to guess.",
    )
    parser.add_argument(
        "--league-key",
        action="append",
        dest="league_keys",
        default=None,
        help="Repeatable. Defaults to every ACTIVE league in the registry.",
    )
    parser.add_argument(
        "--expect-sha",
        default=None,
        help="The deployed commit the operator asserts this run measured. "
        "Recorded as provenance; the API publishes no SHA to check it against.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        type=Path,
        help="Write the machine-readable evidence artifact here.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Rebuild from the newest COMPLETE archived scrape instead of "
        "probing a server. No --base-url, no auth, no network. Ceiling "
        "EVIDENCE-L2 — a locally rebuilt contract, never a deployed "
        "response. Defaults --league-key to dynasty_main, the one this "
        "repo's archive fixture covers; pass --league-key to override.",
    )
    args = parser.parse_args(argv)

    if args.offline:
        keys = args.league_keys or ["dynasty_main"]
        try:
            entries = _registry_entries(keys)
        except Exception as exc:  # noqa: BLE001
            print(f"{TAG} ::error title=Registry unreadable::{exc}")
            return EXIT_UNMEASURED
        bundles, source_paths = [], []
        for key, reg in entries:
            bundle, source_path = build_bundle_offline(key, reg)
            bundles.append(bundle)
            if source_path:
                source_paths.append(source_path)
        results = run_checks(bundles, source_level=L2)
        source_desc = ", ".join(sorted(set(source_paths))) or "(no archive found)"
        render(
            results,
            base_url="",
            source=f"offline_archive:{source_desc}",
            source_level=L2,
            expect_sha=args.expect_sha,
        )
        code = exit_code_for(results)
        if args.json_out:
            artifact = {
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "baseUrl": "",
                "archiveSource": source_paths,
                "operatorAssertedSha": args.expect_sha,
                "shaPublishedByApi": None,
                "sourceLevel": L2,
                "exitCode": code,
                "leagues": [b.league_key for b in bundles],
                "fetchErrors": {b.league_key: b.errors for b in bundles if b.errors},
                "checks": [r.to_dict() for r in results],
            }
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(
                json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"{TAG} evidence written to {args.json_out}")
        return code

    if not args.base_url:
        print(f"{TAG} ::error title=No base URL::Pass --base-url or set ROSTER_VERIFY_BASE_URL.")
        print(f"{TAG} exit 2 — nothing was measured.")
        return EXIT_UNMEASURED

    try:
        entries = _registry_entries(args.league_keys)
    except Exception as exc:  # noqa: BLE001
        print(f"{TAG} ::error title=Registry unreadable::{exc}")
        return EXIT_UNMEASURED
    if not entries:
        print(f"{TAG} no active leagues configured — nothing to verify. exit 2.")
        return EXIT_UNMEASURED

    bundles = [build_bundle_http(args.base_url, key, reg) for key, reg in entries]
    results = run_checks(bundles, source_level=L3)
    render(
        results,
        base_url=args.base_url,
        source="deployed_http",
        source_level=L3,
        expect_sha=args.expect_sha,
    )

    code = exit_code_for(results)
    if args.json_out:
        artifact = {
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "baseUrl": args.base_url,
            "operatorAssertedSha": args.expect_sha,
            "shaPublishedByApi": None,
            "sourceLevel": L3,
            "exitCode": code,
            "leagues": [b.league_key for b in bundles],
            "fetchErrors": {b.league_key: b.errors for b in bundles if b.errors},
            "checks": [r.to_dict() for r in results],
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"{TAG} evidence written to {args.json_out}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
