#!/usr/bin/env python3
"""Validate the Young Core Index against a real league board (#838).

``OWNER_FEATURE_ADDENDUM_2026-08-14_AGE_VALUE_PORTFOLIO.md`` §5 requires
the index be *"validated against intuitive league examples before
treating it as canonical"*.  Unit tests cannot discharge that: they
prove the arithmetic on fixtures I chose, and the requirement is about
whether the number behaves sensibly on a roster nobody designed for it.

So this runs the canonical chain over a REAL contract and asserts the
four properties the addendum's guardrails turn on:

1. cheap young bench players cannot game the index;
2. meaningful-core selection matches the league's own slot config;
3. age never alters canonical player value;
4. league-relative ranks are credible and internally consistent.

Exit codes:  0 all properties hold · 1 a property failed · 2 no board.

``2`` is deliberately distinct: "no data" must never read as "passed",
which is the same rule ``scripts/backtest_perfect_draft.py`` already
sets for a blocked backtest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.api.roster_intelligence import build_league_roster_intelligence  # noqa: E402
from src.roster_intel.core import reserve_demand  # noqa: E402


def _load_contract(path: str | None) -> tuple[dict[str, Any] | None, str]:
    """A real contract: an explicit path, else the newest COMPLETE
    archived scrape (never merely the newest — see
    ``tests/archive_fixtures``)."""
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8")), path
    from tests.archive_fixtures import newest_complete_raw_payload

    raw, name = newest_complete_raw_payload()
    if raw is None:
        return None, "none"
    from src.api.data_contract import build_api_data_contract

    return build_api_data_contract(raw), name or "archive"


def _fmt(v: Any, spec: str = ".2f") -> str:
    return "None" if v is None else format(v, spec)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contract", help="path to a built contract JSON")
    ap.add_argument("--team-count", type=int, default=12)
    args = ap.parse_args()

    contract, source = _load_contract(args.contract)
    if contract is None:
        print("[young-core] NO BOARD AVAILABLE — cannot validate. Exit 2.")
        print("[young-core] 'no data' is not 'passed'.")
        return 2

    out = build_league_roster_intelligence(contract, team_count=args.team_count)
    teams = out["teams"]
    print(f"[young-core] source={source}")
    print(
        f"[young-core] teams={len(teams)} slots={len(out['starterSlots'])} "
        f"slotSource={out['slotSource']} rosterSource={out['rosterSource']}"
    )
    if not teams:
        print("[young-core] contract carries no rosters — cannot validate. Exit 2.")
        return 2

    failures: list[str] = []

    # ── Board ──────────────────────────────────────────────────────
    print("\n── league board ─────────────────────────────────────────")
    print(
        f"{'team':<12}{'rost':>5}{'core':>5}{'unpr':>5}{'strength':>10}{'rk':>4}"
        f"{'YCI':>7}{'coreAge':>8}{'rosterAge':>10}  needs"
    )
    ordered = sorted(teams.items(), key=lambda kv: kv[1]["strength"]["leagueRank"] or 999)
    for _oid, t in ordered:
        s, a, w, c = t["strength"], t["agePortfolio"], t["weakness"], t["core"]
        print(
            f"{t['teamName'][:11]:<12}{t['rosteredCount']:>5}{len(c['members']):>5}"
            f"{len(c['unpricedIds']):>5}{s['total']:>10.0f}{s['leagueRank']:>4}"
            f"{_fmt(a['youngCoreIndex'], '.1f'):>7}{_fmt(a['valueWeightedCoreAge']):>8}"
            f"{_fmt(a['valueWeightedRosterAge']):>10}  {','.join(w['urgentPositions']) or '-'}"
        )

    total_unpriced = sum(len(t["core"]["unpricedIds"]) for t in teams.values())
    total_rostered = sum(t["rosteredCount"] for t in teams.values())
    print(
        f"\n[unpriced] {total_unpriced} of {total_rostered} rostered players carry no "
        f"canonical value and are reported, not zeroed"
    )

    # ── 1. Cheap young bench cannot game the index ─────────────────
    # The addendum's named failure: "a roster full of low-value youth
    # cannot dominate the index".  Stuff the WEAKEST roster with 20
    # minimum-value 21-year-olds and require its index not to move.
    print("\n── 1. cheap young bench cannot game the index ────────────")
    victim = ordered[-1][0]
    before = teams[victim]["agePortfolio"]
    stuffed = json.loads(json.dumps(contract))
    fakes = [f"__CHEAP_YOUNGSTER_{i}" for i in range(20)]
    for team in stuffed["sleeper"]["teams"]:
        if str(team.get("ownerId")) == victim:
            team["players"] = list(team.get("players") or []) + fakes
    for i, name in enumerate(fakes):
        stuffed["sleeper"].setdefault("positions", {})[name] = ("WR", "RB", "TE")[i % 3]
        stuffed["playersArray"].append(
            {
                "playerId": name,
                "canonicalName": name,
                "displayName": name,
                "position": ("WR", "RB", "TE")[i % 3],
                "rankDerivedValue": 1.0,
                "age": 21.0,
            }
        )
    after = build_league_roster_intelligence(stuffed, team_count=args.team_count)
    a2 = after["teams"][victim]["agePortfolio"]
    d_age = abs((a2["valueWeightedCoreAge"] or 0) - (before["valueWeightedCoreAge"] or 0))
    d_idx = abs((a2["youngCoreIndex"] or 0) - (before["youngCoreIndex"] or 0))
    print(f"  team={teams[victim]['teamName']}  +20 cheap 21yo (value 1.0)")
    print(
        f"  coreAge {_fmt(before['valueWeightedCoreAge'])} → {_fmt(a2['valueWeightedCoreAge'])}"
        f"   (Δ {d_age:.4f})"
    )
    print(
        f"  YCI     {_fmt(before['youngCoreIndex'], '.1f')} → "
        f"{_fmt(a2['youngCoreIndex'], '.1f')}   (Δ {d_idx:.4f})"
    )
    if d_age > 0.25 or d_idx > 5.0:
        failures.append(f"cheap young bench moved the index (Δage={d_age:.3f}, ΔYCI={d_idx:.2f})")
    else:
        print("  PASS — the meaningful core excluded them; the index did not move")

    # ── 2. Core selection matches the league's slot config ─────────
    print("\n── 2. meaningful-core selection matches league config ────")
    demand = reserve_demand(out["starterSlots"])
    expected = len(out["starterSlots"]) + demand.total()
    print(
        f"  slots={len(out['starterSlots'])} + reserve demand={demand.total()} "
        f"⇒ core ceiling {expected}"
    )
    print(f"  reserve demand by slot: {demand.by_slot}")
    for _oid, t in ordered:
        c = t["core"]
        n = len(c["members"])
        unfilled = len(c["unfilledStarterSlots"]) + len(c["unfilledReserveSlots"])
        if n + unfilled != expected:
            failures.append(
                f"{t['teamName']}: core {n} + unfilled {unfilled} != ceiling {expected}"
            )
        dupes = len(c["members"]) - len({m["playerId"] for m in c["members"]})
        if dupes:
            failures.append(f"{t['teamName']}: {dupes} duplicate core members")
    if not failures:
        print("  PASS — every team's core + unfilled slots equals the ceiling, no duplicates")

    # ── 3. Age never alters canonical value ────────────────────────
    print("\n── 3. age never alters canonical player value ────────────")
    aged = json.loads(json.dumps(contract))
    for row in aged["playersArray"]:
        if isinstance(row.get("age"), (int, float)) and row["age"] > 0:
            row["age"] = float(row["age"]) + 5.0
    out3 = build_league_roster_intelligence(aged, team_count=args.team_count)
    moved = [
        t["teamName"]
        for oid, t in teams.items()
        if abs(out3["teams"][oid]["strength"]["total"] - t["strength"]["total"]) > 1e-6
    ]
    shifted = sum(
        1
        for oid, t in teams.items()
        if abs(
            (out3["teams"][oid]["agePortfolio"]["valueWeightedCoreAge"] or 0)
            - (t["agePortfolio"]["valueWeightedCoreAge"] or 0)
            - 5.0
        )
        < 1e-6
    )
    print(
        f"  +5 years on every player → Team Strength changed on {len(moved)} teams " f"(must be 0)"
    )
    print(f"  core age moved by exactly +5.00 on {shifted}/{len(teams)} teams")
    if moved:
        failures.append(f"age changed Team Strength on: {moved}")
    elif shifted != len(teams):
        failures.append(f"core age did not track the age shift on all teams ({shifted})")
    else:
        print("  PASS — age moves the age statistics and nothing else")

    # ── 4. Ranks are credible ──────────────────────────────────────
    print("\n── 4. league-relative ranks are credible ─────────────────")
    ranks = sorted(t["strength"]["leagueRank"] for t in teams.values())
    idx = [t["agePortfolio"]["youngCoreIndex"] for t in teams.values()]
    if ranks != list(range(1, len(teams) + 1)):
        failures.append(f"strength ranks are not a clean 1..N permutation: {ranks}")
    if any(i is None for i in idx):
        failures.append("some teams have no Young Core Index on a fully-aged board")
    else:
        print(
            f"  strength ranks 1..{len(teams)} complete; "
            f"YCI spans {min(idx):.1f}–{max(idx):.1f}"
        )
        # Strength and youth must be DIFFERENT axes — if the index just
        # re-reads strength it is not measuring roster construction.
        pairs = sorted(
            (
                (t["strength"]["leagueRank"], t["agePortfolio"]["youngCoreIndex"])
                for t in teams.values()
            ),
            key=lambda p: p[0],
        )
        inversions = sum(
            1
            for i in range(len(pairs))
            for j in range(i + 1, len(pairs))
            if pairs[i][1] < pairs[j][1]
        )
        print(
            f"  strength-rank vs YCI inversions: {inversions} of "
            f"{len(pairs) * (len(pairs) - 1) // 2} pairs"
        )
        if inversions == 0:
            failures.append("YCI is a pure restatement of strength rank — not a second axis")
        else:
            print("  PASS — youth is a genuinely separate axis from strength")

    # ── Verdict ────────────────────────────────────────────────────
    print("\n── verdict ──────────────────────────────────────────────")
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        return 1
    print("  all four properties hold on a real league board")
    print("  NOTE: this validates BEHAVIOUR, not calibration. The 0-100")
    print("  index remains a PRIOR until its weighting is calibrated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
