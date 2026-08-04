"""TE starter demand from ACTUAL weekly scoring, measured symmetrically.

Two things the projection path gets wrong:

1. It optimizes on ``rosValue``, a season-long MEAN.  Best ball pays
   for weekly spikes and a mean erases them, so a TE averaging 8 PPG
   who hits 22 twice never wins a FLEX slot on a point estimate.  The
   "FLEX never takes a TE" claim is an artifact of that.

2. More importantly for the PREMIUM: the derivation compares a 1-TE
   reference against our 2-TE league.  If the league endpoint is
   measured from weekly actuals, the reference endpoint MUST be too.
   Using measured 2-TE demand against an assumed 1.0 reference is
   apples-to-oranges and inflates the premium.

So both vectors are re-solved over the same 2025 weekly scores.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

# Derived from this file's location, not hardcoded.  This previously
# pointed at ``.claude/worktrees/agent-aeac57da8fea835ea`` — the throwaway
# worktree it happened to be written in, deleted the moment that agent
# finished. Every run since has failed on the fixture read below with a
# FileNotFoundError naming a directory nobody recognises.
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.ros.lineup import RosterPlayer, optimize_lineup  # noqa: E402

FIX = REPO / "tests/league_intel/fixtures/matchups_2025"
META = json.loads((FIX / "players_meta.json").read_text())


def _slots(te_count: int) -> list[str]:
    """This league's lineup with ONLY the TE count parameterised.

    The two arms must differ in exactly one slot or the comparison
    measures something other than TE premium.  They are built from one
    expression for that reason: the OLD arm used to be written out
    longhand and carried ``DL 2 / LB 2 / DB 2`` against NEW's 3/3/3, so
    it quietly dropped a slot at each IDP position too — the same wrong
    2/2/2 table that was deleted from the frontend on 2026-07-30, and a
    direct contradiction of this module's own docstring claim that the
    vectors are "measured symmetrically".

    The IDP slots do not compete with TE for a slot (the eligibility
    pools are disjoint), so this does not move the measured ratio — but
    "it happened not to matter" is not a reason to leave an asymmetry in
    a symmetric measurement.
    """
    return (
        ["QB"]
        + ["RB"] * 2
        + ["WR"] * 3
        + ["TE"] * te_count
        + ["FLEX"] * 2
        + ["SUPER_FLEX"]
        + ["K"]
        + ["DL"] * 3
        + ["LB"] * 3
        + ["DB"] * 3
    )


NEW = _slots(2)  # our league: 2 TE
OLD = _slots(1)  # 1-TE reference


def base_pos(pid: str) -> str:
    m = META.get(str(pid)) or {}
    pos = m.get("position") or ""
    fps = m.get("fantasy_positions") or []
    if pos == "TE" or "TE" in fps:
        return "TE"
    return (fps[0] if fps else pos).upper()


weeks = []
for w in range(1, 18):
    f = FIX / f"w{w}.json"
    if f.exists():
        weeks.append((w, json.loads(f.read_text())))

results = {}
excluded_rosters = []
for label, slots in (("OLD 1-TE", OLD), ("NEW 2-TE", NEW)):
    te_started, flex, sflex, tw, skipped = [], Counter(), Counter(), 0, 0
    te_rostered = []
    for w, entries in weeks:
        for e in entries:
            ids = [str(p) for p in (e.get("players") or [])]
            pts = {str(k): float(v) for k, v in (e.get("players_points") or {}).items()}
            if not ids or not pts:
                continue
            roster = []
            for pid in ids:
                m = META.get(pid) or {}
                pos = (m.get("position") or "").upper()
                if not pos:
                    continue
                roster.append(
                    RosterPlayer(
                        pid,
                        pid,
                        pos,
                        pts.get(pid, 0.0),
                        1.0,
                        False,
                        False,
                        tuple(m.get("fantasy_positions") or ()),
                    )
                )
            sol = optimize_lineup(roster, starter_slots=slots)
            if sol.unfilled_slots:
                skipped += 1
                if label == "NEW 2-TE":
                    excluded_rosters.append((len(ids), sum(1 for p in ids if base_pos(p) == "TE")))
                continue
            tw += 1
            n_te = 0
            for row in sol.starting_lineup:
                bp = base_pos(row["playerId"])
                if bp == "TE":
                    n_te += 1
                if row["slot"] == "FLEX":
                    flex[bp] += 1
                elif row["slot"] == "SUPER_FLEX":
                    sflex[bp] += 1
            te_started.append(n_te)
            te_rostered.append(sum(1 for p in ids if base_pos(p) == "TE"))
    results[label] = (te_started, flex, sflex, tw, skipped, te_rostered)
    tot_flex = sum(flex.values()) or 1
    print(f"\n=== {label} ({len(slots)} slots) ===")
    print(f"  team-weeks solved {tw}, skipped(unfilled) {skipped}")
    print(f"  FLEX: {dict(flex.most_common())}  TE share {flex['TE'] / tot_flex:.1%}")
    print(f"  SUPER_FLEX: {dict(sflex.most_common())}")
    print(
        f"  TE started/team-week: mean {statistics.mean(te_started):.3f}  "
        f"median {statistics.median(te_started)}  max {max(te_started)}"
    )
    print(f"  TE rostered/team    : mean {statistics.mean(te_rostered):.2f}")

new_te = statistics.mean(results["NEW 2-TE"][0])
old_te = statistics.mean(results["OLD 1-TE"][0])
print("\n=== SYMMETRIC ENDPOINTS (both from the same weekly actuals) ===")
print(f"  reference (1-TE rules) TE started/team : {old_te:.3f}")
print(f"  league    (2-TE rules) TE started/team : {new_te:.3f}")
print(f"  ratio                                  : {new_te / old_te:.3f}")
print(
    f"  (an ASSUMED 1.0 reference would imply a ratio of {new_te:.3f} — "
    f"{(new_te / old_te - 1) * 100:.0f}% vs {(new_te - 1) * 100:.0f}%)"
)

print("\n=== EXCLUSION-BIAS CHECK (NEW vector skips) ===")
if excluded_rosters:
    sizes = [s for s, _ in excluded_rosters]
    tes = [t for _, t in excluded_rosters]
    kept = results["NEW 2-TE"][5]
    print(f"  skipped {len(excluded_rosters)} team-weeks")
    print(f"    roster size: mean {statistics.mean(sizes):.1f}")
    print(f"    TE count   : mean {statistics.mean(tes):.2f}")
    kept_mean = statistics.mean(kept)
    skip_mean = statistics.mean(tes)
    print(f"  kept  TE count: mean {kept_mean:.2f}")
    # State the conclusion the data actually supports, not a template.
    if skip_mean > kept_mean:
        print("  => skipped entries carry MORE TEs, so the retained sample skews")
        print("     TE-SHALLOW and TE demand is if anything UNDERstated.")
    elif skip_mean < kept_mean:
        print("  => skipped entries carry FEWER TEs, so the retained sample skews")
        print("     TE-DEEP and TE demand is OVERstated.")
    else:
        print("  => skipped and retained carry equal TE counts; no directional bias.")
else:
    print("  no exclusions")
