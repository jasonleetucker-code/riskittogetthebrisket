#!/usr/bin/env python3
"""Independent reconciliation of dynasty_main multi-year draft capital (Batch E).

Run isolated so nothing from the repository can be imported::

    python3 -I scripts/check_draft_capital_multi_year.py --payload dc.json [--repo .]
        [--sleeper-dir DIR] [--before before.json]

It imports NOTHING from the repository (stdlib only).  It reads the repo's
draft-valuation snapshot files as DATA, fetches Sleeper itself (or reads a
saved copy with ``--sleeper-dir``: ``league.json``, ``rosters.json``,
``traded_picks.json``), folds pick ownership itself, re-derives the
rookie-auction curve from the formula's written definition, and checks the
``/api/draft-capital`` payload (``--payload``, a JSON dump of the endpoint or
of ``server._fetch_draft_capital("dynasty_main")``) against all of it:

1. identities — exactly 12 x 6 x 3 = 216 unique owned picks across the
   upcoming class and the two later classes, equal to this script's fold;
2. ownership — every pick's current owner equals this script's fold;
3. per-class totals — every class exactly $1,200 in whole dollars, All Years
   $3,600;
4. team totals — every per-year and All Years team figure is the exact sum of
   the picks that team owns; ``teamTotals`` is the upcoming class alone;
5. /trade — the stack's rule (``coveredPickYears`` + priced ``picks``
   assetIds are already in ``teamTotals``) adds no upcoming-class pick twice;
6. curve — the later classes' dollars match this script's own evaluation of
   the spreadsheet formula over the frozen 2026 inputs and each class's spine
   (and the stored per-year records match it too): known slots exactly, every
   unknown-slot round keeps its exact round dollars with shares <= $1 apart.

Exit 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
from collections import defaultdict
from decimal import Decimal, getcontext
from fractions import Fraction
from pathlib import Path

LEAGUE_KEY = "dynasty_main"
SLEEPER_LEAGUE_ID = "1312006700437352448"
TEAMS, ROUNDS, BUDGET = 12, 6, 1200
SLEEPER = "https://api.sleeper.app/v1"

getcontext().prec = 60

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append(("PASS" if ok else "FAIL", name, detail))
    return ok


# --- inputs -----------------------------------------------------------------------------


def _get(url: str):
    with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 — fixed Sleeper host
        return json.loads(resp.read())


def load_sleeper(sleeper_dir: str | None):
    if sleeper_dir:
        d = Path(sleeper_dir)
        return tuple(
            json.loads((d / f"{n}.json").read_text(encoding="utf-8"))
            for n in ("league", "rosters", "traded_picks")
        )
    base = f"{SLEEPER}/league/{SLEEPER_LEAGUE_ID}"
    return _get(base), _get(f"{base}/rosters"), _get(f"{base}/traded_picks")


def checksum_ok(payload: dict) -> bool:
    body = {k: v for k, v in payload.items() if k != "checksum"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest() == payload["checksum"]["value"]


def labels() -> list[str]:
    return [f"{r}.{s:02d}" for r in range(1, ROUNDS + 1) for s in range(1, TEAMS + 1)]


def read_values(rows: list[dict], key: str) -> list[Fraction]:
    assert [r["pick"] for r in rows] == labels(), "pick order"
    return [Fraction(Decimal(r[key])) for r in rows]


# --- the formula, from its written definition ----------------------------------------------


def evaluate_formula(b: list[Fraction], curves: list[list[Fraction]]) -> list[Fraction]:
    """The half-dollar "Final Dollar Per Pick" (column L) for 72 picks."""
    n = TEAMS * ROUNDS
    e = []
    for i in range(n):
        vals = sorted(c[i] for c in curves)
        e.append((vals[1] + sum(vals) / 3) / 2)
    head = [Decimal(x.numerator) / Decimal(x.denominator) for x in b[:6]]
    mean = sum(head) / 6
    sd = (sum((x - mean) ** 2 for x in head) / 5).sqrt()
    k = min(Decimal("0.08"), max(Decimal("0.03"), Decimal("0.6") * sd / mean))
    bd = [Decimal(x.numerator) / Decimal(x.denominator) for x in b]
    w = [
        bd[i] * (-k * i).exp() * (1 - Decimal("0.2") * (Decimal("-0.12") * i).exp())
        for i in range(n)
    ]
    wsum = sum(w)
    excess = [max(x - 1, Fraction(0)) for x in e]
    esum = sum(excess)
    floors = [1 + (1 if i // TEAMS == 4 else 0) for i in range(n)]
    pool = Decimal(BUDGET - sum(floors))
    c = [
        floors[i]
        + pool
        * (
            Decimal("0.6") * w[i] / wsum
            + Decimal("0.4")
            * Decimal(excess[i].numerator)
            / Decimal(excess[i].denominator)
            / (Decimal(esum.numerator) / Decimal(esum.denominator))
        )
        for i in range(n)
    ]
    units = [int(math.floor(2 * x)) for x in c]
    frac = [2 * c[i] - units[i] for i in range(n)]
    residual = 2 * BUDGET - sum(units)
    award = set(sorted(range(n), key=lambda i: (-frac[i], i))[:residual])
    caps = {4: 4, 5: 2}  # 0-based round index -> cap in half-dollar units
    kk: list[int] = []
    for i in range(n):
        v = units[i] + (1 if i in award else 0)
        if i > 0:
            cap = caps.get(i // TEAMS)
            if cap is not None:
                v = min(v, cap)
            v = min(v, kk[-1])
        kk.append(v)
    # The residual is carried over the first M1 = 12 picks only:
    # QUOTIENT(S, 12) + (i < MOD(S, 12)); later picks carry nothing.
    s = 2 * BUDGET - sum(kk)
    q = abs(s) // 12 * (1 if s >= 0 else -1)
    m = s % 12
    carry = [(q + (1 if i < m else 0)) if i < 12 else 0 for i in range(n)]
    return [Fraction(kk[i] + carry[i], 2) for i in range(n)]


def whole_dollars_step_a(ref: list[Fraction]) -> list[int] | None:
    """Floor, residual to the largest remainders (earlier pick on ties); ``None``
    when that breaks a constraint (the exact repair is not re-derived here)."""
    base = [math.floor(x) for x in ref]
    residual = BUDGET - sum(base)
    order = sorted(range(len(ref)), key=lambda i: (-(ref[i] - base[i]), i))
    out = list(base)
    for i in order[:residual]:
        out[i] += 1
    floors = [1 + (1 if i // TEAMS == 4 else 0) for i in range(len(ref))]
    caps = [None] + [{4: 2, 5: 1}.get(i // TEAMS) for i in range(1, len(ref))]
    ok = (
        sum(out) == BUDGET
        and all(out[i] >= floors[i] for i in range(len(out)))
        and all(c is None or out[i] <= c for i, c in enumerate(caps))
        and all(out[i] <= out[i - 1] for i in range(1, len(out)))
    )
    return out if ok else None


# --- the checks ----------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--payload", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--sleeper-dir")
    ap.add_argument("--before", help="an earlier payload, for the before/after table")
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    league, rosters, traded = load_sleeper(args.sleeper_dir)

    upcoming = int(payload["upcomingDraftYear"])
    classes = [upcoming, upcoming + 1, upcoming + 2]
    check(
        "available years",
        payload.get("availableYears") == classes,
        str(payload.get("availableYears")),
    )
    rounds = int((league.get("settings") or {}).get("draft_rounds") or 0)
    rids = sorted(int(r["roster_id"]) for r in rosters)
    check(
        "league shape 12 x 6",
        rounds == ROUNDS and rids == list(range(1, TEAMS + 1)),
        f"{len(rids)}x{rounds}",
    )

    # 1-2. identities + ownership, folded here.
    fold: dict[str, int] = {}
    for season in classes:
        for rnd in range(1, rounds + 1):
            for origin in rids:
                fold[f"pick:{LEAGUE_KEY}:{season}:r{rnd}:o{origin}"] = origin
    for t in traded:
        aid = f"pick:{LEAGUE_KEY}:{int(t['season'])}:r{int(t['round'])}:o{int(t['roster_id'])}"
        if aid in fold:
            fold[aid] = int(t["owner_id"])
    every = list(payload["picks"]) + list(payload["additionalClassPicks"])
    ids = [p.get("assetId") for p in every]
    check(
        "216 unique identities",
        len(ids) == 216 and len(set(ids)) == 216 and len(fold) == 216,
        f"{len(set(ids))}",
    )
    check("identities equal the fold", set(ids) == set(fold))
    wrong = [p["assetId"] for p in every if fold.get(p["assetId"]) != p.get("currentOwnerRosterId")]
    check("current owners equal the fold", not wrong, f"{len(wrong)} differ: {wrong[:5]}")

    # 3. per-class totals.
    by_class: dict[int, int] = defaultdict(int)
    for p in every:
        d = p.get("dollarValue")
        if not isinstance(d, int) or isinstance(d, bool) or p.get("isUnpriced") is True:
            check("every pick priced in whole dollars", False, p["assetId"])
            break
        by_class[int(p["season"])] += d
    else:
        check("every pick priced in whole dollars", True)
    check(
        "each class exactly $1,200",
        dict(by_class) == {y: BUDGET for y in classes},
        str(dict(by_class)),
    )
    check(
        "All Years $3,600",
        payload["allYearsSummary"]["totalDollars"] == 3 * BUDGET
        and sum(by_class.values()) == 3 * BUDGET,
    )

    # 4. team totals = exact sums of owned picks.
    owned_year: dict[tuple[str, int], int] = defaultdict(int)
    owned_all: dict[str, int] = defaultdict(int)
    for p in every:
        owned_year[(p["currentOwner"], int(p["season"]))] += p["dollarValue"]
        owned_all[p["currentOwner"]] += p["dollarValue"]
    bad = [
        (season, r["team"])
        for season, rows in payload["teamTotalsByYear"].items()
        for r in rows
        if r["auctionDollars"] != owned_year.get((r["team"], int(season)), 0)
    ]
    check("per-year team totals = sums of owned picks", not bad, str(bad[:5]))
    bad = [
        r["team"]
        for r in payload["allYearsTeamTotals"]
        if r["auctionDollars"] != owned_all.get(r["team"], 0)
    ]
    check("All Years team totals = sums of owned picks", not bad, str(bad[:5]))
    bad = [
        t["team"]
        for t in payload["teamTotals"]
        if t["auctionDollars"] != owned_year.get((t["team"], upcoming), 0)
    ]
    check(
        "teamTotals = the upcoming class alone",
        not bad and sum(t["auctionDollars"] for t in payload["teamTotals"]) == BUDGET,
        str(bad[:5]),
    )

    # 5. /trade stack rule: nothing of the upcoming class is added on top of teamTotals.
    covered = {int(y) for y in payload.get("coveredPickYears") or []}
    priced_ids = {p["assetId"] for p in payload["picks"] if isinstance(p.get("dollarValue"), int)}
    re_added = [
        a
        for a, _o in fold.items()
        if int(a.split(":")[2]) == upcoming and a not in priced_ids and upcoming not in covered
    ]
    check(
        "/trade: no upcoming-class double count",
        covered == {upcoming}
        and not re_added
        and {int(p["season"]) for p in payload["picks"]} == {upcoming}
        and upcoming not in {int(p["season"]) for p in payload["additionalClassPicks"]},
        f"covered={sorted(covered)} re_added={len(re_added)}",
    )

    # 6. the curve, re-derived here.
    cfg = repo / "config" / "draft_valuation"
    frozen = json.loads(
        (cfg / "frozen_inputs" / "2026_spreadsheet_baseline.json").read_text(encoding="utf-8")
    )
    check("frozen inputs checksum", checksum_ok(frozen))
    b = read_values(frozen["values"], "value")
    curve_dir = cfg / "historical_curves" / LEAGUE_KEY
    completed = sorted(int(p.stem) for p in curve_dir.glob("*.json") if p.stem.isdigit())
    for season in classes:
        spine = [y for y in completed if y < season][-3:]
        curves = []
        for y in spine:
            c = json.loads((curve_dir / f"{y}.json").read_text(encoding="utf-8"))
            check(f"{y} spine curve checksum", checksum_ok(c))
            curves.append(read_values(c["referenceDollars"], "dollars"))
        ref = evaluate_formula(b, curves)
        whole = whole_dollars_step_a(ref)
        check(
            f"{season} formula re-derived (spine {spine})", whole is not None and sum(ref) == BUDGET
        )
        if whole is None:
            continue
        if season == upcoming:
            # The workbook class: every pick at its (projected or final) slot.
            off = [
                p["assetId"]
                for p in payload["picks"]
                if p["dollarValue"] != whole[(p["round"] - 1) * TEAMS + int(p["pickInRound"]) - 1]
            ]
            check(f"{season} workbook-class slot dollars = re-derived curve", not off, str(off[:4]))
            continue
        recs = sorted((cfg / "published_allocations" / LEAGUE_KEY / str(season)).glob("*.json"))
        if recs:
            rec = json.loads(recs[-1].read_text(encoding="utf-8"))
            check(f"{season} stored record checksum", checksum_ok(rec))
            check(
                f"{season} stored record = re-derived whole dollars",
                [r["dollars"] for r in rec["finalWholeDollars"]] == whole,
            )
            check(
                f"{season} stored reference = re-derived half dollars",
                read_values(rec["referenceDollars"], "dollars") == ref,
            )
        block = (payload["budgetPolicy"].get("classes") or {}).get(str(season)) or {}
        check(
            f"{season} per-year fields",
            block.get("budgetBasis") == "per_class_pool"
            and block.get("spineYears") == spine
            and block.get("inputMode") == "frozen_fallback"
            and bool(block.get("curveId")),
            json.dumps(
                {k: block.get(k) for k in ("budgetBasis", "curveId", "spineYears", "inputMode")}
            ),
        )
        rows = [p for p in payload["additionalClassPicks"] if int(p["season"]) == season]
        problems = []
        for rnd in range(1, ROUNDS + 1):
            slot_d = whole[(rnd - 1) * TEAMS : rnd * TEAMS]
            rr = [p for p in rows if p["round"] == rnd]
            known = [p for p in rr if isinstance(p.get("slot"), int)]
            unknown = [p for p in rr if not isinstance(p.get("slot"), int)]
            for p in known:
                if p["dollarValue"] != slot_d[p["slot"] - 1]:
                    problems.append(f"{p['assetId']} slot dollars")
            rest = sum(
                d for s, d in enumerate(slot_d, start=1) if s not in {p["slot"] for p in known}
            )
            got = [p["dollarValue"] for p in unknown]
            if got and (sum(got) != rest or max(got) - min(got) > 1):
                problems.append(f"round {rnd} share {got} vs {rest}")
        check(
            f"{season} payload dollars follow the re-derived curve",
            not problems,
            "; ".join(problems[:4]),
        )

    # Before / after (report only).
    if args.before:
        before = json.loads(Path(args.before).read_text(encoding="utf-8"))
        print("\nBefore / after — later-class dollars per pick by round (min-max) and team totals")
        for season in classes[1:]:
            for label, pl in (("before", before), ("after", payload)):
                rows = [p for p in pl["additionalClassPicks"] if int(p["season"]) == season]
                per_round = []
                for rnd in range(1, ROUNDS + 1):
                    v = [
                        p["dollarValue"]
                        for p in rows
                        if p["round"] == rnd and isinstance(p.get("dollarValue"), int)
                    ]
                    per_round.append(f"R{rnd} ${min(v)}-{max(v)}" if v else f"R{rnd} unpriced")
                teams = {
                    r["team"]: r["auctionDollars"]
                    for r in pl["teamTotalsByYear"].get(str(season), [])
                }
                print(f"  {season} {label:6}: {', '.join(per_round)}")
                print(f"  {season} {label:6} teams: {json.dumps(teams, sort_keys=True)}")

    print("\nDraft-capital multi-year reconciliation (independent, no repo imports)")
    for status, name, detail in RESULTS:
        print(f"  {status}  {name}" + (f"  [{detail}]" if detail and status == "FAIL" else ""))
    failed = sum(1 for s, _n, _d in RESULTS if s == "FAIL")
    print(f"\n{len(RESULTS) - failed} PASS, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
