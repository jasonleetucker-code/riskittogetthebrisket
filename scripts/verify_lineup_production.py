#!/usr/bin/env python3
"""Executable verification instrument for V1-27 / `C2-U1` §10.

`docs/lineup/C2_U1_CANONICAL_LINEUP.md` §10 lists six production checks
that stand between the canonical lineup owner and `VERIFIED` at
EVIDENCE-L3. §10a records them being run **by hand** on 2026-08-18, and
records — in its own words — that the run *nearly passed vacuously*:

    The first run joined assignments to eligibility by Sleeper player id
    and reported **0** hits — which reads exactly like "the property does
    not hold". It was a join failure.

A checklist that can only be re-run by repeating that reasoning is not a
checklist. This module is the same six checks as code, so the next run
is a command rather than an argument.

WHAT THIS DOES NOT DO
─────────────────────
It computes no lineup. Every check reads what production published and
asserts a property of it; the solve belongs to `src/ros/lineup.py` and
is not reimplemented, imported for recomputation, or second-guessed
here. A verification instrument that recomputes the thing it is checking
verifies only that it agrees with itself.

HARNESS REUSE
─────────────
The PASS/FAIL/UNMEASURABLE vocabulary, the vacuous-pass downgrade, level
capping and exit-code precedence are **imported** from
`scripts/verify_roster_intelligence.py`, not re-implemented. That module
is the owner of "how a verification check reports itself" in this repo,
and a second copy of those rules would drift from it exactly the way the
duplicate lineup engines this row exists to retire drifted from
`assign_lineup`.

THE JOIN TRAP, ENCODED
──────────────────────
`optimalLineup.assignments[].player` carries whatever
`RosterPlayer.player_id` held. On the contract stamp path
(`data_contract.stamp_optimal_lineups`) that is the **name** from
`sleeper.teams[].players`; on the roster-row adapter path
(`lineup.roster_player_from_row`) it is `playerId or canonicalName`. The
eligibility maps `sleeper.fantasyPositions` / `sleeper.positions` are
**name-keyed**.

So check 05 joins by name, and — the part that matters — it publishes
`assignmentsJoined` and refuses to report a clean result when that
denominator is 0. "Matched nothing" and "measured and found none" are
different answers and this module never conflates them.

Usage:
    # Production (EVIDENCE-L3) — needs a session cookie
    export ROSTER_VERIFY_COOKIE='session=…'
    python scripts/verify_lineup_production.py --base-url "$PROD_PUBLIC_URL"

    # Offline (EVIDENCE-L2) — rebuilds from the newest COMPLETE archive
    python scripts/verify_lineup_production.py --offline

Exit codes follow the repo convention (`scripts/backtest_perfect_draft.py`):
    0  every check was MEASURED and PASSED
    1  a check measured a violation
    2  one or more checks could not be measured
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.verify_roster_intelligence import (  # noqa: E402
    EXIT_UNMEASURED,
    FAIL,
    L2,
    L3,
    PASS,
    UNMEASURABLE,
    CheckResult,
    Unauthenticated,
    exit_code_for,
    fetch_json,
    finalize,
    unmeasurable,
    _auth_headers,
)

TAG = "[lineup-verify]"

#: The one value §10 item 1 accepts. A lineup solved from anything else
#: is a lineup solved from a default, which is the state C2-U1 §7 named
#: as the gap rather than papered over.
EXPECTED_SLOT_SOURCE = "sleeper_roster_positions"


# ---------------------------------------------------------------------------
# The bundle a check reasons over
# ---------------------------------------------------------------------------


class LineupBundle:
    """One league's published payloads. Any field may be absent.

    Absent is UNKNOWN. Every check that needs a missing field says
    ``UNMEASURABLE`` with a named reason rather than treating the gap as
    a clean result.
    """

    def __init__(
        self,
        league_key: str,
        contract: Mapping[str, Any] | None = None,
        simulate: Mapping[str, Any] | None = None,
    ) -> None:
        self.league_key = league_key
        self.contract = contract
        self.simulate = simulate
        self.errors: dict[str, str] = {}

    @property
    def sleeper(self) -> Mapping[str, Any]:
        block = (self.contract or {}).get("sleeper")
        return block if isinstance(block, Mapping) else {}

    @property
    def teams(self) -> list[Mapping[str, Any]]:
        teams = self.sleeper.get("teams")
        if isinstance(teams, list):
            return [t for t in teams if isinstance(t, Mapping)]
        return []

    def lineups(self) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
        """``(team, optimalLineup)`` for every team carrying the stamp."""
        out = []
        for team in self.teams:
            stamp = team.get("optimalLineup")
            if isinstance(stamp, Mapping):
                out.append((team, stamp))
        return out


def _name_keyed(block: Any) -> dict[str, Any]:
    return {str(k): v for k, v in block.items()} if isinstance(block, Mapping) else {}


# ---------------------------------------------------------------------------
# The checks. Pure functions of a LineupBundle.
# ---------------------------------------------------------------------------


def check_01_stamp_available_and_sourced(bundle: LineupBundle) -> CheckResult:
    """§10.1 — every team carries ``optimalLineup`` with ``available: true``
    and ``slotSource: "sleeper_roster_positions"``.

    The denominator is the team count, so a payload carrying no teams
    reports UNMEASURABLE rather than "0 violations".
    """
    name = "every team carries optimalLineup available + sleeper_roster_positions"
    teams = bundle.teams
    if not teams:
        return unmeasurable(
            "01", name, L3, "no sleeper.teams in payload", leagueKey=bundle.league_key
        )

    violations: list[dict[str, Any]] = []
    for team in teams:
        stamp = team.get("optimalLineup")
        label = team.get("name") or team.get("ownerId") or "<unnamed>"
        if not isinstance(stamp, Mapping):
            violations.append({"team": label, "kind": "stamp_absent"})
            continue
        if stamp.get("available") is not True:
            violations.append(
                {
                    "team": label,
                    "kind": "not_available",
                    "reason": stamp.get("reason"),
                }
            )
        if stamp.get("slotSource") != EXPECTED_SLOT_SOURCE:
            violations.append(
                {
                    "team": label,
                    "kind": "wrong_slot_source",
                    "slotSource": stamp.get("slotSource"),
                }
            )

    evidence = {
        "leagueKey": bundle.league_key,
        "teamsExamined": len(teams),
        "violations": violations[:10],
        "violationCount": len(violations),
    }
    if violations:
        return CheckResult(
            "01",
            name,
            L3,
            FAIL,
            len(teams),
            reason=f"{len(violations)} teams lack an available, correctly-sourced stamp",
            evidence=evidence,
        )
    return CheckResult("01", name, L3, PASS, len(teams), evidence=evidence)


def check_03_simulate_starter_neutral(bundle: LineupBundle) -> CheckResult:
    """§10.3 — ``/api/trade/simulate`` returns a ``teamImpact`` whose
    ``starterDelta`` is unchanged for a trade that moves no starter.

    The INVARIANT half is closed deterministically offline by
    ``tests/lineup/test_starter_neutral_trade.py`` (4 tests, mutation
    proven). What remains, and what this check measures, is the
    TRANSPORT half: that the deployed endpoint actually returns the
    block, over HTTP, on a real league.
    """
    name = "simulate returns teamImpact.starterDelta, all zero for a starter-neutral trade"
    payload = bundle.simulate
    if not isinstance(payload, Mapping):
        return unmeasurable(
            "03",
            name,
            L3,
            bundle.errors.get("simulate", "no simulate payload"),
            leagueKey=bundle.league_key,
        )

    impact = payload.get("teamImpact")
    if not isinstance(impact, Mapping):
        return CheckResult(
            "03",
            name,
            L3,
            FAIL,
            1,
            reason="response carried no teamImpact block",
            evidence={"leagueKey": bundle.league_key, "keys": sorted(payload)[:15]},
        )

    delta = impact.get("starterDelta")
    if not isinstance(delta, Mapping) or not delta:
        return unmeasurable(
            "03",
            name,
            L3,
            "teamImpact carried no populated starterDelta — nothing to measure",
            leagueKey=bundle.league_key,
        )

    moved = {k: v for k, v in delta.items() if v}
    evidence = {
        "leagueKey": bundle.league_key,
        "positionsExamined": len(delta),
        "starterDelta": dict(delta),
        "moved": moved,
    }
    if moved:
        return CheckResult(
            "03",
            name,
            L3,
            FAIL,
            len(delta),
            reason=f"a starter-neutral trade moved {len(moved)} position(s): {moved}",
            evidence=evidence,
        )
    return CheckResult("03", name, L3, PASS, len(delta), evidence=evidence)


def check_03a_sleeper_reachable_still_available(bundle: LineupBundle) -> CheckResult:
    """§10.3a — with Sleeper REACHABLE, teams still carry
    ``optimalLineup.available: true``.

    This is the §7a defect's state: the stamp did not survive the
    serving path, so a *healthy* Sleeper block produced unavailable
    lineups. Verify it explicitly and first — a payload whose sleeper
    block is empty cannot exercise it and must say so.
    """
    name = "with Sleeper reachable, lineups still available"
    sleeper = bundle.sleeper
    required = ("teams", "rosterPositions", "scoringSettings")
    missing = [k for k in required if not sleeper.get(k)]
    if missing:
        return unmeasurable(
            "03a",
            name,
            L3,
            f"sleeper block is not fully populated (missing {missing}) — "
            "this check needs the REACHABLE state to be real",
            leagueKey=bundle.league_key,
        )

    lineups = bundle.lineups()
    if not lineups:
        return unmeasurable(
            "03a", name, L3, "no optimalLineup stamps present", leagueKey=bundle.league_key
        )

    unavailable = [
        {"team": t.get("name") or t.get("ownerId"), "reason": s.get("reason")}
        for t, s in lineups
        if s.get("available") is not True
    ]
    evidence = {
        "leagueKey": bundle.league_key,
        "sleeperBlockPopulated": sorted(k for k in required if sleeper.get(k)),
        "lineupsExamined": len(lineups),
        "unavailable": unavailable[:10],
        "unavailableCount": len(unavailable),
    }
    if unavailable:
        return CheckResult(
            "03a",
            name,
            L3,
            FAIL,
            len(lineups),
            reason=(
                f"{len(unavailable)} lineups unavailable despite a populated sleeper "
                "block — this is the §7a serving-path defect"
            ),
            evidence=evidence,
        )
    return CheckResult("03a", name, L3, PASS, len(lineups), evidence=evidence)


def check_05_hybrid_started_off_primary(bundle: LineupBundle) -> CheckResult:
    """§10.5 — ``fantasyPositions`` is populated **and** at least one
    multi-position player is started in a slot its primary alone would
    not allow.

    THE JOIN. ``assignments[].player`` is name-keyed on the contract
    stamp path; so are ``fantasyPositions`` and ``positions``. The 2026-08-18
    run first joined by Sleeper id, matched nothing, and read that as a
    failing property.

    So this check publishes ``assignmentsJoined`` and returns
    UNMEASURABLE — never PASS, never FAIL — when the join matches
    nothing. A join that resolved no rows has measured no property.

    THE SECOND TRAP, also encoded. ``sleeper.positions`` carries the raw
    NFL position (``DE``, ``DT``, ``OLB``…) while slots and
    ``fantasyPositions`` speak the lineup vocabulary (``DL``, ``LB``…).
    Comparing them directly counts Myles Garrett — primary ``DE``, sole
    eligibility ``DL``, started at ``DL`` — as a player "started off his
    primary", which is simply a DE playing DL. Measured on the
    2026-08-24 board that error inflated the count from 3 to 16.

    Both sides are therefore normalised through ``lineup_position``, the
    canonical owner's own vocabulary function — not a local table. And a
    hit requires genuine multi-position eligibility, which is what §10
    item 5 actually describes ("a DL/LB hybrid").
    """
    from src.ros.lineup import lineup_position

    name = "fantasyPositions populated and a hybrid starts off its primary"
    sleeper = bundle.sleeper
    fantasy = _name_keyed(sleeper.get("fantasyPositions"))
    positions = _name_keyed(sleeper.get("positions"))

    if not fantasy:
        return unmeasurable(
            "05",
            name,
            L3,
            "sleeper.fantasyPositions is empty — eligibility was never published",
            leagueKey=bundle.league_key,
        )

    lineups = bundle.lineups()
    joined = 0
    unjoined: list[str] = []
    hybrids_started: list[dict[str, Any]] = []
    multi_position_players = 0

    for _team, stamp in lineups:
        for row in stamp.get("assignments") or []:
            if not isinstance(row, Mapping):
                continue
            player = str(row.get("player") or "")
            slot = str(row.get("slot") or "")
            if not player:
                continue
            eligible = fantasy.get(player)
            if eligible is None:
                unjoined.append(player)
                continue
            joined += 1
            # Both sides through the canonical vocabulary — see the
            # docstring's "second trap".
            eligible_set = {lineup_position(str(p)) for p in eligible if p}
            eligible_set.discard("")
            if len(eligible_set) > 1:
                multi_position_players += 1
            primary = lineup_position(str(positions.get(player) or ""))
            # Started off-primary: the slot names a position the player
            # is eligible for, but his PRIMARY is not that position —
            # and he genuinely holds more than one eligibility, which is
            # what makes it a hybrid rather than a vocabulary artifact.
            slot_up = lineup_position(slot)
            if primary and len(eligible_set) > 1 and slot_up in eligible_set and slot_up != primary:
                hybrids_started.append(
                    {
                        "player": player,
                        "primary": primary,
                        "eligible": sorted(eligible_set),
                        "startedAt": slot_up,
                    }
                )

    evidence = {
        "leagueKey": bundle.league_key,
        "eligibilityRecords": len(fantasy),
        "assignmentsJoined": joined,
        "assignmentsUnjoined": len(unjoined),
        "unjoinedSample": sorted(set(unjoined))[:10],
        "multiPositionStarters": multi_position_players,
        "hybridsStartedOffPrimary": hybrids_started[:10],
        "hybridCount": len(hybrids_started),
    }

    # The trap, closed. A zero-row join has measured nothing.
    if joined == 0:
        return unmeasurable(
            "05",
            name,
            L3,
            (
                "the assignment→eligibility join matched 0 of "
                f"{sum(len(s.get('assignments') or []) for _t, s in lineups)} assignments. "
                "This is a JOIN FAILURE, not a property failure — assignments are "
                "name-keyed on the contract stamp path. Do not read this as 'no hybrids'."
            ),
            **evidence,
        )

    if not hybrids_started:
        return CheckResult(
            "05",
            name,
            L3,
            FAIL,
            joined,
            reason=(
                f"joined {joined} assignments and found no player started off his "
                "primary position — eligibility is published but unused"
            ),
            evidence=evidence,
        )
    return CheckResult("05", name, L3, PASS, joined, evidence=evidence)


def check_06_no_player_started_twice(bundle: LineupBundle) -> CheckResult:
    """Not in §10, and deliberately added: no player may occupy two slots.

    §10's six items verify the stamp is present, sourced, eligible and
    consumed. None of them would catch the same player being seated
    twice, which is the failure mode a matching-based solver has and a
    greedy does not. Cheap to check against a published payload, and it
    is the one structural property of an assignment that a reader can
    confirm without recomputing the solve.
    """
    name = "no player occupies two starting slots"
    lineups = bundle.lineups()
    if not lineups:
        return unmeasurable(
            "06", name, L3, "no optimalLineup stamps present", leagueKey=bundle.league_key
        )

    examined = 0
    violations: list[dict[str, Any]] = []
    for team, stamp in lineups:
        seen: dict[str, int] = {}
        for row in stamp.get("assignments") or []:
            if not isinstance(row, Mapping):
                continue
            player = str(row.get("player") or "")
            if not player:
                continue
            examined += 1
            seen[player] = seen.get(player, 0) + 1
        dupes = {p: n for p, n in seen.items() if n > 1}
        if dupes:
            violations.append(
                {"team": team.get("name") or team.get("ownerId"), "duplicates": dupes}
            )

    evidence = {
        "leagueKey": bundle.league_key,
        "assignmentsExamined": examined,
        "violations": violations[:10],
        "violationCount": len(violations),
    }
    if not examined:
        return unmeasurable(
            "06", name, L3, "stamps carried no assignments", leagueKey=bundle.league_key
        )
    if violations:
        return CheckResult(
            "06",
            name,
            L3,
            FAIL,
            examined,
            reason=f"{len(violations)} teams seat a player in two slots",
            evidence=evidence,
        )
    return CheckResult("06", name, L3, PASS, examined, evidence=evidence)


#: In report order. Items 2 and 4 of §10 are deliberately absent — see
#: ``UNAUTOMATABLE`` below; asserting them here would be asserting
#: something this module cannot observe.
CHECKS: tuple[Callable[[LineupBundle], CheckResult], ...] = (
    check_01_stamp_available_and_sourced,
    check_03a_sleeper_reachable_still_available,
    check_03_simulate_starter_neutral,
    check_05_hybrid_started_off_primary,
    check_06_no_player_started_twice,
)

#: §10 items this instrument cannot honestly automate, recorded rather
#: than silently dropped. A checklist that quietly shrinks is how a
#: partial verification comes to read as a complete one.
UNAUTOMATABLE: tuple[tuple[str, str], ...] = (
    (
        "02",
        "/terminal + /rosters RENDER starters from the stamp. Needs an "
        "authenticated browser session and a human (or an E2E run) looking at "
        "the page. The server-side half — that the stamp is what the client is "
        "handed — is pinned offline by tests/lineup/test_serving_path.py.",
    ),
    (
        "04",
        "A scrape completes and the board is unchanged. Needs a PRE-deploy "
        "production snapshot, which was never captured (§10a item 4, PARTIAL). "
        "Capture one with scripts/golden_board.py BEFORE the next deploy and "
        "this becomes measurable; it cannot be reconstructed after the fact.",
    ),
)


def run_checks(bundle: LineupBundle, *, source_level: str = L3) -> list[CheckResult]:
    return finalize([c(bundle) for c in CHECKS], source_level=source_level)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

#: A trade with no assets on either side. Starter-neutral by construction:
#: nothing enters or leaves, so no seat can move. Deliberately the
#: weakest possible request — this check measures the TRANSPORT, and a
#: richer trade would make a failure ambiguous between "endpoint broken"
#: and "we picked players that really did move a starter".
_STARTER_NEUTRAL_TRADE: dict[str, Any] = {"playersIn": [], "playersOut": []}


def build_bundle_http(base_url: str, league_key: str) -> LineupBundle:
    """Fetch one league's payloads. Every failure is recorded, not raised."""
    import urllib.request

    bundle = LineupBundle(league_key)
    headers = _auth_headers()
    base = base_url.rstrip("/")

    try:
        payload, _elapsed = fetch_json(f"{base}/api/data?leagueKey={league_key}", headers=headers)
        bundle.contract = payload if isinstance(payload, Mapping) else None
        if not isinstance(payload, Mapping):
            bundle.errors["contract"] = "response was not a JSON object"
    except Unauthenticated as exc:
        bundle.errors["contract"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        bundle.errors["contract"] = f"unreachable: {exc}"

    body = dict(_STARTER_NEUTRAL_TRADE)
    body["leagueKey"] = league_key
    req = urllib.request.Request(
        f"{base}/api/trade/simulate",
        data=json.dumps(body).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            parsed = json.loads(resp.read().decode())
        bundle.simulate = parsed if isinstance(parsed, Mapping) else None
        if not isinstance(parsed, Mapping):
            bundle.errors["simulate"] = "response was not a JSON object"
    except Exception as exc:  # noqa: BLE001
        bundle.errors["simulate"] = f"unreachable: {exc}"

    return bundle


def build_bundle_offline(league_key: str) -> tuple[LineupBundle, str | None]:
    """Rebuild the contract from the newest COMPLETE archived scrape.

    EVIDENCE-L2, never higher: a locally rebuilt contract is real, but it
    is not a deployed response. ``simulate`` is left unset — there is no
    HTTP round-trip offline, and item 3's INVARIANT is already closed by
    ``tests/lineup/test_starter_neutral_trade.py``; fabricating a local
    call here would report transport evidence no request produced.
    """
    from src.api.data_contract import build_api_data_contract
    from tests.archive_fixtures import newest_complete_raw_payload

    bundle = LineupBundle(league_key)
    raw, source_path = newest_complete_raw_payload()
    if raw is None:
        bundle.errors["contract"] = "no complete archived scrape available"
        return bundle, None
    bundle.contract = build_api_data_contract(raw)
    return bundle, source_path


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
    print(f"{TAG} V1-27 / C2-U1 §10 production verification")
    print(f"{TAG} source={source}  sourceLevel={source_level}")
    print(f"{TAG} baseUrl={base_url or '(none — offline run)'}")
    if expect_sha:
        print(f"{TAG} operatorAssertedSha={expect_sha}")
    print(
        f"{TAG} NOTE: no API surface publishes the deployed commit, so an "
        "EVIDENCE-L3 claim binds to the SHA the OPERATOR asserts. Record it "
        "from the deploy run, not from here."
    )
    print("")
    width = max((len(r.id) for r in results), default=4)
    for r in results:
        print(f"  {r.result:<13} {r.id:<{width}}  {r.name}  [{r.level or '—'}; n={r.denominator}]")
        if r.reason:
            print(f"                {' ' * width}  → {r.reason}")
    print("")
    print(f"{TAG} ── §10 items this instrument cannot automate ──")
    for item, why in UNAUTOMATABLE:
        print(f"  MANUAL        {item}  {why}")
    print("")
    failed = [r for r in results if r.result == FAIL]
    unmeasured = [r for r in results if r.result == UNMEASURABLE]
    passed = [r for r in results if r.result == PASS]
    print(f"{TAG} ── verdict ──")
    print(f"{TAG} {len(passed)} passed · {len(failed)} failed · {len(unmeasured)} unmeasurable")
    for r in failed:
        print(f"{TAG} ::error title=Lineup verification failed::{r.id} {r.name}: {r.reason}")
    for r in unmeasured:
        print(
            f"{TAG} ::warning title=Lineup verification could not measure::{r.id} {r.name}: {r.reason}"
        )
    if unmeasured and not failed:
        print(f"{TAG} exit 2 — 'could not measure' is NOT 'passed'.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="", help="Server origin to probe.")
    parser.add_argument("--league-key", default="dynasty_main")
    parser.add_argument("--expect-sha", default=None)
    parser.add_argument("--json-out", default=None, type=Path)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Rebuild from the newest COMPLETE archive instead of probing a "
        "server. Ceiling EVIDENCE-L2 — never L3.",
    )
    args = parser.parse_args(argv)

    if args.offline:
        bundle, source_path = build_bundle_offline(args.league_key)
        level, source = L2, f"offline_archive:{source_path or '(none)'}"
    else:
        if not args.base_url:
            print(f"{TAG} ::error title=No base URL::Pass --base-url or use --offline.")
            print(f"{TAG} exit 2 — nothing was measured.")
            return EXIT_UNMEASURED
        bundle = build_bundle_http(args.base_url, args.league_key)
        level, source = L3, "deployed_http"

    results = run_checks(bundle, source_level=level)
    render(
        results,
        base_url=args.base_url,
        source=source,
        source_level=level,
        expect_sha=args.expect_sha,
    )
    code = exit_code_for(results)
    if args.json_out:
        artifact = {
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "row": "V1-27",
            "checklist": "docs/lineup/C2_U1_CANONICAL_LINEUP.md §10",
            "baseUrl": args.base_url,
            "operatorAssertedSha": args.expect_sha,
            "shaPublishedByApi": None,
            "sourceLevel": level,
            "exitCode": code,
            "leagueKey": bundle.league_key,
            "fetchErrors": bundle.errors,
            "checks": [r.to_dict() for r in results],
            "unautomatable": [{"item": i, "why": w} for i, w in UNAUTOMATABLE],
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
        print(f"{TAG} evidence written to {args.json_out}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
