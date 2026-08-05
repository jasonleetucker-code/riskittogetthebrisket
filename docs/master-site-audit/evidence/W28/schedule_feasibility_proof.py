"""Feasibility proof for the W28 schedule spec (scratchpad only)."""

import random
import itertools
import json

D = {
    1: ["Michaela", "Blaine", "Ty", "Joel"],
    2: ["Jason", "Brent", "Roy", "Colin"],
    3: ["Eric", "Joey", "Kitch", "Ed"],
}
div = {t: d for d, ts in D.items() for t in ts}
teams = [t for ts in D.values() for t in ts]
# required game multiset
games = []
for a, b in itertools.combinations(teams, 2):
    games += [(a, b)] * (2 if div[a] == div[b] else 1)
assert len(games) == 14 * 6, len(games)


def solve(seed, tries=200000):
    rnd = random.Random(seed)
    for _ in range(tries):
        pool = list(games)
        rnd.shuffle(pool)
        weeks = []
        prev = set()
        ok = True
        for wk in range(1, 15):
            used = set()
            chosen = []
            for g in list(pool):
                a, b = g
                if a in used or b in used:
                    continue
                if frozenset(g) in prev:
                    continue
                if wk == 4 and (("Jason" in g) != ("Michaela" in g)):
                    continue
                if wk != 4 and set(g) == {"Jason", "Michaela"}:
                    continue
                if (
                    wk == 4
                    and set(g) != {"Jason", "Michaela"}
                    and ("Jason" in g or "Michaela" in g)
                ):
                    continue
                used |= set(g)
                chosen.append(g)
                pool.remove(g)
                if len(chosen) == 6:
                    break
            if len(chosen) != 6:
                ok = False
                break
            prev = {frozenset(g) for g in chosen}
            weeks.append(chosen)
        if ok and not pool:
            return weeks
    return None


s = solve(7)
print("solution found:", s is not None)
if s:
    # validate
    seen = {}
    for i, wk in enumerate(s, 1):
        assert len({t for g in wk for t in g}) == 12, f"wk{i} not all 12 exactly once"
        for g in wk:
            seen[frozenset(g)] = seen.get(frozenset(g), 0) + 1
    for a, b in itertools.combinations(teams, 2):
        want = 2 if div[a] == div[b] else 1
        assert seen.get(frozenset((a, b)), 0) == want, (a, b, seen.get(frozenset((a, b)), 0), want)
    for i in range(13):
        assert not (
            {frozenset(g) for g in s[i]} & {frozenset(g) for g in s[i + 1]}
        ), f"back-to-back wk{i+1}"
    w4 = [g for g in s[3] if set(g) == {"Jason", "Michaela"}]
    assert len(w4) == 1
    print("ALL CONSTRAINTS SATISFIED")
    print(json.dumps({f"week{i}": [list(g) for g in wk] for i, wk in enumerate(s, 1)}, indent=1))
