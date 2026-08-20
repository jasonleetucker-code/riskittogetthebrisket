#!/usr/bin/env python3
"""P9 — prove the Trade/Roster proving test FAILS when the integration is cut.

A green guard proves nothing on its own.  This script takes each structural or
behavioural property asserted by
``tests/trade/test_trade_consumes_roster.py``, deliberately breaks the exact
seam that property guards, re-runs only the test that guards it, and requires
RED.  Sources are restored afterwards whatever happens.

    python scripts/prove_trade_consumes_roster.py

Exit 0 iff every mutation was caught.  Exit 1 if any mutation survived — a
surviving mutation means the guard is decorative.  Exit 2 if a mutation could
not be applied at all, which usually means the code moved and the anchor needs
re-pointing; that is reported as an error rather than silently skipped, because
"could not break it" and "it holds" must not read the same.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEST = "tests/trade/test_trade_consumes_roster.py"

CAPACITY = "src/trade/roster_capacity.py"
TEAM_IMPACT = "src/trade/team_impact.py"
SUGGESTIONS = "src/trade/suggestions.py"
WAIVER = "src/trade/waiver.py"


@dataclass(frozen=True)
class Mutation:
    """One deliberate break, and the guard that must notice it."""

    label: str
    property_id: str
    #: ``(path, old, new)`` — ``old`` must appear EXACTLY once.
    edits: tuple[tuple[str, str, str], ...] = ()
    #: ``(path, text)`` appended verbatim.
    appends: tuple[tuple[str, str], ...] = ()
    #: pytest node id(s) that must go RED.
    guards: tuple[str, ...] = ()
    note: str = ""


LADDER_CALL = """        scarcity=context.scarcity,
        slot_eligibility=context.slot_eligibility,
        max_rungs=over_after_max,"""

SIM_CALL = """        before_pool,
        list(context.starter_slots),
        incoming=incoming_pool,
        outgoing_ids=[i for i in outgoing_ids if i in on_roster],"""

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        label="the configured flex rule stops reaching the cut ladder",
        property_id="P1",
        edits=(
            (
                CAPACITY,
                LADDER_CALL,
                """        scarcity=context.scarcity,
        max_rungs=over_after_max,""",
            ),
        ),
        guards=(
            f"{TEST}::TestP1ConfiguredSlotEligibilityReachesTheCutPath"
            "::test_a_narrowed_flex_changes_which_player_is_released",
        ),
        note="the exact regression #922 repaired at the owner",
    ),
    Mutation(
        label="the configured flex rule stops reaching team_impact's lineup",
        property_id="P1",
        edits=(
            (
                TEAM_IMPACT,
                """    assignment = assign_lineup(
        pool, slots, slot_eligibility=configured_slot_eligibility(roster_settings)
    )""",
                "    assignment = assign_lineup(pool, slots)",
            ),
        ),
        guards=(
            f"{TEST}::test_the_configured_flex_rule_reaches_the_team_impact_starter_projection",
        ),
        note="the same defect class as P1, in Trade's second lineup consumer",
    ),
    Mutation(
        label="suggestions rebuilds the two-entry eligibility map",
        property_id="P1",
        edits=(
            (
                SUGGESTIONS,
                """    demand = slot_demand(
        slots, eligibility_overrides=configured_slot_eligibility(settings)
    ).flex_priority""",
                """    overrides = {
        slot: settings[key]
        for slot, key in (("FLEX", "flexEligible"), ("IDP_FLEX", "idpFlexEligible"))
        if settings.get(key)
    }
    demand = slot_demand(slots, eligibility_overrides=overrides).flex_priority""",
            ),
        ),
        guards=(f"{TEST}::test_no_trade_module_reads_the_registrys_flex_keys_directly",),
    ),
    Mutation(
        label="Trade grows its own lineup solver",
        property_id="P2",
        appends=(
            (
                TEAM_IMPACT,
                "\n\ndef assign_lineup(pool, slots):  # pragma: no cover - mutation\n"
                "    return {}\n",
            ),
        ),
        guards=(f"{TEST}::test_no_trade_module_defines_a_name_another_owner_owns[lineup]",),
    ),
    Mutation(
        label="Trade grows a private slot->positions table",
        property_id="P2",
        appends=(
            (
                WAIVER,
                '\n\n_FLEX_TABLE = {"FLEX": ("RB", "WR", "TE")}  # mutation\n',
            ),
        ),
        guards=(f"{TEST}::test_trade_does_not_recompute_a_lineup_after_the_owner_solved_one",),
    ),
    Mutation(
        label="Trade grows its own Team Strength",
        property_id="P3",
        appends=(
            (
                SUGGESTIONS,
                "\n\ndef build_team_strength(core):  # pragma: no cover - mutation\n"
                "    return None\n",
            ),
        ),
        guards=(f"{TEST}::test_no_trade_module_defines_a_name_another_owner_owns[roster-intel]",),
    ),
    Mutation(
        label="Trade grows its own cut ladder",
        property_id="P4",
        appends=(
            (
                CAPACITY,
                "\n\ndef build_cut_ladder(*a, **k):  # pragma: no cover - mutation\n"
                "    return None\n",
            ),
        ),
        guards=(f"{TEST}::test_no_trade_module_defines_a_name_another_owner_owns[cut-ladder]",),
    ),
    Mutation(
        label="Trade reaches the ladder through the draft board instead of the adapter",
        property_id="P4",
        edits=(
            (
                CAPACITY,
                "from src.draft.displacement import (\n    RosterAsset,\n",
                "from src.draft.displacement import (\n    RosterAsset,\n    build_cut_ladder,\n",
            ),
        ),
        guards=(f"{TEST}::test_trade_reaches_the_cut_ladder_through_the_adapter_not_the_board",),
        note="both doors reach one owner, but only the adapter carries the flex rule",
    ),
    Mutation(
        label="the re-solve stops consuming capacity's forced drops",
        property_id="P5",
        edits=(
            (
                CAPACITY,
                "        outgoing_ids=[i for i in outgoing_ids if i in on_roster],",
                "        outgoing_ids=[],",
            ),
        ),
        guards=(f"{TEST}::test_a_forced_drop_is_never_also_retained",),
    ),
    Mutation(
        label="an unknown roster limit is coerced to a number",
        property_id="P6",
        edits=(
            (
                CAPACITY,
                "    limit = context.roster_limit\n    if limit is None:",
                "    limit = context.roster_limit\n"
                "    limit = 99 if limit is None else limit\n"
                "    if False:",
            ),
        ),
        guards=(f"{TEST}::test_an_unknown_roster_limit_stays_unknown",),
    ),
    Mutation(
        label="an unpriced forced drop is valued at zero",
        property_id="P7",
        edits=(
            (
                CAPACITY,
                "                value=(asset.board_value if asset is not None else None),",
                "                value=(\n"
                "                    (asset.board_value or 0.0) if asset is not None else 0.0\n"
                "                ),",
            ),
        ),
        guards=(f"{TEST}::test_an_unpriced_forced_drop_reports_null_and_is_counted_separately",),
    ),
    Mutation(
        label="the transaction is applied BEFORE the owner is called",
        property_id="P8",
        edits=(
            (
                CAPACITY,
                SIM_CALL,
                """        [p for p in before_pool if p.player_id not in set(outgoing_ids)]
        + incoming_pool,
        list(context.starter_slots),
        incoming=(),
        outgoing_ids=(),""",
            ),
        ),
        guards=(
            f"{TEST}::test_before_apply_resolve_after_is_the_order_and_the_owner_does_the_resolve",
        ),
        note="collapses before and after into one state; the cascade becomes invisible",
    ),
)


@dataclass
class Result:
    mutation: Mutation
    applied: bool
    caught: bool
    detail: str = ""
    failures: list[str] = field(default_factory=list)


def _run_guards(guards: tuple[str, ...]) -> tuple[bool, str]:
    """True when at least one guard is RED."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", *guards],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    tail = (proc.stdout or proc.stderr).strip().splitlines()
    return proc.returncode != 0, (tail[-1] if tail else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="run one property id (P1, P5, …)")
    args = parser.parse_args()

    selected = [m for m in MUTATIONS if not args.only or m.property_id == args.only]
    if not selected:
        print(f"no mutation matches {args.only!r}", file=sys.stderr)
        return 2

    baseline_ok, baseline_tail = _run_guards((TEST,))
    if baseline_ok:
        print(f"BASELINE IS ALREADY RED — fix the tree first: {baseline_tail}")
        return 2
    print(f"baseline GREEN: {baseline_tail}\n")

    results: list[Result] = []
    for mutation in selected:
        touched = {
            path: (REPO / path).read_text(encoding="utf-8")
            for path, *_ in [*[(p,) for p, _o, _n in mutation.edits], *mutation.appends]
        }
        try:
            failure = ""
            for path, old, new in mutation.edits:
                text = (REPO / path).read_text(encoding="utf-8")
                if text.count(old) != 1:
                    failure = f"anchor appears {text.count(old)}x in {path}"
                    break
                (REPO / path).write_text(text.replace(old, new), encoding="utf-8")
            if not failure:
                for path, extra in mutation.appends:
                    with (REPO / path).open("a", encoding="utf-8") as handle:
                        handle.write(extra)

            if failure:
                results.append(Result(mutation, applied=False, caught=False, detail=failure))
            else:
                caught, tail = _run_guards(mutation.guards)
                results.append(Result(mutation, applied=True, caught=caught, detail=tail))
        finally:
            for path, original in touched.items():
                (REPO / path).write_text(original, encoding="utf-8")

        last = results[-1]
        mark = (
            "RED (caught)" if last.caught else ("NOT APPLIED" if not last.applied else "SURVIVED")
        )
        print(f"[{last.mutation.property_id}] {last.mutation.label}\n    -> {mark} — {last.detail}")

    restored_ok, restored_tail = _run_guards((TEST,))
    print(f"\nafter restore: {'RED' if restored_ok else 'GREEN'} — {restored_tail}")
    if restored_ok:
        print("SOURCES DID NOT RESTORE CLEANLY", file=sys.stderr)
        return 2

    survived = [r for r in results if r.applied and not r.caught]
    unapplied = [r for r in results if not r.applied]
    print(f"\n{len(results) - len(survived) - len(unapplied)}/{len(results)} mutations caught")
    for r in survived:
        print(f"  SURVIVED  [{r.mutation.property_id}] {r.mutation.label}", file=sys.stderr)
    for r in unapplied:
        print(f"  NOT APPLIED [{r.mutation.property_id}] {r.detail}", file=sys.stderr)
    if unapplied:
        return 2
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
