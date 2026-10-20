"""Public fairness consistency audit — differential harness (read-only).

Owner decision 2026-10-20 §5 (``docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md``):
the public 2-, 3- and 4-team Brisket Trade Advisor must follow ONE
authoritative market-fairness calculation, never a roster-aware
recommendation.  Audit record:
``docs/trade/PUBLIC_FAIRNESS_CONSISTENCY_AUDIT_2026-10-20.md``.

This script changes nothing.  It runs against a READ-ONLY checkout of the
advisor lane (``--code-root``, e.g. a ``git archive`` of
``origin/claude/advisor-public-backend``) using that lane's own synthetic
four-team test league (``tests/api/trade_advisor_support.py`` — no real
league, roster, team or manager data), and checks:

P1  Team-Context invariance — every team's market-fairness state is the same
    in ``market_fairness``, ``asset_only`` and ``team_context`` modes, and
    under every injected competitive posture.
P2  One calculation at every N — the public reduction
    (``public_advisor.evaluate``) equals the engine's ``market_fairness``
    per-team states and overall, for 2-, 3- and 4-team trades.
P3  N = 2 symmetry — both teams of a 2-team trade carry the same state.
P4  Independent recomputation — at N = 2 each priced FAIR / NOT_FAIR equals
    ``fairness_bands.classify`` over the package model's adjusted totals,
    recomputed from the board values alone.
P5  Value-free reduction — the public result type carries no float and no
    integer outside roster ids / counts.
D1  Personalization delta (diagnostic, not a failure) — how often the
    PRIVATE roster-aware decision (component A, net of forced-release cost,
    and the 5-level category) disagrees with the public market answer.  This
    is what a public path built on the private decision — the advisor's
    pre-2026-10-20 design — would have published.

``--bands-root`` additionally runs a pure-math symmetry check of a band
owner (e.g. a ``git archive`` of ``origin/claude/fairness-bands-v2``), so the
N = 2 symmetry property is known to survive the v2 denominator.

Exit 0 when P1-P5 hold, 1 otherwise.  Output is JSON on stdout.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import random
import sys
import tempfile
from pathlib import Path
from typing import Any

POSTURES = {
    "PUSH": {"PUSH": 0.8, "HOLD": 0.1, "RETOOL": 0.05, "REBUILD": 0.05},
    "REBUILD": {"PUSH": 0.05, "HOLD": 0.1, "RETOOL": 0.05, "REBUILD": 0.8},
    "UNAVAILABLE": None,
}


def _posture_block(label: str) -> dict[str, Any]:
    probs = POSTURES[label]
    if probs is None:
        return {"available": False, "unavailableReason": "audit_injected_unavailable"}
    return {
        "available": True,
        "label": label,
        "evidence": "measured",
        "probabilities": probs,
        "confidence": "medium",
        "paramsVersion": "posture_v1_prior",
    }


def _setup(code_root: Path, roster_size: int) -> Any:
    sys.path.insert(0, str(code_root))
    from tests.api import trade_advisor_support as S  # noqa: PLC0415

    from src.api import league_registry  # noqa: PLC0415

    reg = S.registry_json()
    for lg in reg["leagues"]:
        if lg["key"] == "main":
            lg["rosterSettings"] = {**lg["rosterSettings"], "rosterSize": int(roster_size)}
    tmp = Path(tempfile.mkdtemp(prefix="pfa_"))
    (tmp / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
    import os  # noqa: PLC0415

    os.environ["LEAGUE_REGISTRY_PATH"] = str(tmp / "registry.json")
    league_registry.reload_registry()

    from src.roster_intel import best_ball_utility as bbu  # noqa: PLC0415

    by_id = {pid: S.PPG[n.lower()] for pid, n, *_r in S.PLAYERS if n.lower() in S.PPG}

    def fake_ppg(ids, season, scoring_settings):
        return (
            {i: by_id[str(i)] for i in ids if str(i) in by_id},
            {"state": "available", "source": "AUDIT_PROJECTIONS", "season": season},
        )

    bbu.league_scored_ppg_by_id = fake_ppg
    import src.bdvm.actuals as actuals  # noqa: PLC0415

    actuals.current_nfl_season = lambda today=None: 2026
    return S


def _trades(S: Any, rng: random.Random, n_random: int) -> list[tuple[str, list, tuple]]:
    """Shapes over the synthetic league: every 1-for-1, 2-for-1 and 1-for-2
    between every pair of teams (players and owned picks), plus random 3- and
    4-team trades in which every team both sends and receives."""
    c = S.contract()
    owned: dict[int, list[str]] = {}
    for t in c["sleeper"]["teams"]:
        rid = int(t["roster_id"])
        ids = [f"p:{p}" for p in t["playerIds"]]
        ids += [d["assetId"] for d in t.get("pickDetails") or []]
        owned[rid] = ids
    out: list[tuple[str, list, tuple]] = []
    for a, b in itertools.combinations(sorted(owned), 2):
        for k_a, k_b in ((1, 1), (2, 1), (1, 2)):
            for give_a in itertools.combinations(owned[a], k_a):
                for give_b in itertools.combinations(owned[b], k_b):
                    legs = [(x, a, b) for x in give_a] + [(x, b, a) for x in give_b]
                    out.append((f"2:{k_a}v{k_b}", legs, (a, b)))
    for n in (3, 4):
        for _ in range(n_random):
            teams = tuple(sorted(rng.sample(sorted(owned), n)))
            legs = []
            used: set[str] = set()
            # Every team sends one or two assets to a random other team, and the
            # ring guarantees every team also receives.
            ring = list(teams)
            rng.shuffle(ring)
            for i, rid in enumerate(ring):
                dest = ring[(i + 1) % n]
                for x in rng.sample(owned[rid], rng.choice((1, 2))):
                    if x not in used:
                        used.add(x)
                        legs.append((x, rid, dest))
            out.append((f"{n}:ring", legs, teams))
    return out


def _states(result: dict[str, Any]) -> dict[int, str]:
    return {int(r): str((t.get("fairness") or {}).get("state")) for r, t in result["teams"].items()}


def _objective_band(entry: dict[str, Any]) -> tuple[str | None, int | None]:
    """Private component A band level and the forced-release cost it charged."""
    decision = ((entry.get("analysis") or {}).get("decision")) or {}
    comps = decision.get("components") or {}
    a = comps.get("objectiveValue") if isinstance(comps, dict) else None
    if not isinstance(a, dict) or not a.get("evaluated"):
        return None, None
    band = a.get("band") or {}
    return band.get("level"), a.get("forcedReleaseCost")


def run(code_root: Path, roster_size: int, n_random: int, seed: int) -> dict[str, Any]:
    S = _setup(code_root, roster_size)
    from src.api import trade_simulator  # noqa: PLC0415
    from src.trade import analyze_service, public_advisor, trade_ledger  # noqa: PLC0415
    from src.valuation_math import fairness_bands  # noqa: PLC0415
    from src.valuation_math.package_model import adjusted_pair_totals  # noqa: PLC0415

    contract = S.contract()
    values = {f"p:{pid}": v for pid, _n, _p, _t, v, _r in S.PLAYERS}
    pick_values = {
        r["displayName"]: r["rankDerivedValue"]
        for r in contract["playersArray"]
        if r.get("assetClass") == "pick"
    }
    for t in contract["sleeper"]["teams"]:
        for d in t.get("pickDetails") or []:
            values[d["assetId"]] = pick_values.get(d["baseLabel"])

    snap = trade_ledger.snapshot_for(
        contract,
        league_key="main",
        roster_settings=dict(
            next(lg for lg in S.registry_json()["leagues"] if lg["key"] == "main")[
                "rosterSettings"
            ],
            rosterSize=roster_size,
        ),
    )
    policy = public_advisor.public_policy(max_teams=4, max_legs=128)
    rng = random.Random(seed)
    trades = _trades(S, rng, n_random)

    counts = {
        "trades": 0,
        "refusedByLedger": 0,
        "byTeamCount": {},
        "P1_teamContextInvariant_violations": 0,
        "P2_publicEqualsEngine_violations": 0,
        "P3_twoTeamSymmetry_violations": 0,
        "P4_independentRecompute_violations": 0,
        "P5_valueFree_violations": 0,
        "D1_privateComponentA_differs": 0,
        "D1_privateComponentA_differs_dueToForcedRelease": 0,
        "D1_privateCategory_notEven_whenPublicFair": 0,
        "D1_privateCategory_whenPublicFair": {},
        "D1_privateCategory_whenPublicNotFair": {},
        "D1_teamEvaluations": 0,
        "publicResults": {"FAIR": 0, "NOT_FAIR": 0, "UNABLE_TO_DETERMINE": 0},
    }
    examples: dict[str, list[Any]] = {}

    def _example(key: str, item: Any) -> None:
        examples.setdefault(key, [])
        if len(examples[key]) < 3:
            examples[key].append(item)

    real_posture = trade_simulator.competitive_posture_for
    for shape, legs, teams in trades:
        try:
            ledger = trade_ledger.validate_ledger(
                snap,
                teams=list(teams),
                legs=[{"id": a, "from": f, "to": t} for a, f, t in legs],
                policy=policy,
            )
        except trade_ledger.LedgerError:
            counts["refusedByLedger"] += 1
            continue
        counts["trades"] += 1
        n = len(teams)
        counts["byTeamCount"][str(n)] = counts["byTeamCount"].get(str(n), 0) + 1

        mf = analyze_service.analyze_trade_n(
            snap, ledger, mode="market_fairness", counterfactuals=False
        )
        base = _states(mf)
        variants = {"asset_only": None}
        for label in POSTURES:
            variants[f"team_context:{label}"] = label
        privates: dict[str, dict[str, Any]] = {}
        for name, label in variants.items():
            mode = "asset_only" if label is None else "team_context"
            block = _posture_block(label) if label else _posture_block("PUSH")
            res = analyze_service.analyze_trade_n(
                snap,
                ledger,
                mode=mode,
                counterfactuals=False,
                posture_resolver=lambda c, k, t, *, build_if_missing, b=block: dict(b),
            )
            privates[name] = res
            if _states(res) != base:
                counts["P1_teamContextInvariant_violations"] += 1
                _example("P1", {"shape": shape, "legs": legs, "variant": name})

        pub = public_advisor.evaluate(snap, ledger)
        pub_states = {t.roster_id: t.result for t in pub.teams}
        mapped = {
            rid: {"FAIR": "FAIR", "NOT_FAIR": "NOT_FAIR", "UNABLE": "UNABLE_TO_DETERMINE"}.get(s, s)
            for rid, s in base.items()
        }
        overall_engine = mf["summary"]["fairnessOverall"]["state"]
        overall_mapped = {
            "FAIR": "FAIR",
            "NOT_FAIR": "NOT_FAIR",
            "UNABLE": "UNABLE_TO_DETERMINE",
        }.get(overall_engine, overall_engine)
        if pub_states != mapped or pub.overall.result != overall_mapped:
            counts["P2_publicEqualsEngine_violations"] += 1
            _example("P2", {"shape": shape, "legs": legs, "public": pub_states, "engine": mapped})
        for r in pub.teams:
            counts["publicResults"][r.result] += 1

        # P5: the public dataclass tree carries no float, ints only as ids/counts.
        def _walk(obj: Any, path: str) -> None:
            if isinstance(obj, bool) or obj is None or isinstance(obj, str):
                return
            if isinstance(obj, float):
                raise ValueError(path)
            if isinstance(obj, int):
                if not (
                    path.endswith("roster_id")
                    or path.endswith("from_rid")
                    or path.endswith("to_rid")
                    or path.endswith("team_count")
                ):
                    raise ValueError(path)
                return
            if isinstance(obj, (list, tuple)):
                for i, v in enumerate(obj):
                    _walk(v, path)
                return
            if hasattr(obj, "__dataclass_fields__"):
                for f in obj.__dataclass_fields__:
                    _walk(getattr(obj, f), f"{path}.{f}")
                return
            raise ValueError(f"{path}:{type(obj).__name__}")

        try:
            _walk(pub, "$")
        except ValueError as err:
            counts["P5_valueFree_violations"] += 1
            _example("P5", {"shape": shape, "path": str(err)})

        if n == 2:
            a, b = teams
            if pub_states[a] != pub_states[b]:
                counts["P3_twoTeamSymmetry_violations"] += 1
                _example("P3", {"shape": shape, "legs": legs, "public": pub_states})
            gives_a = [values.get(x) for x, f, _t in legs if f == a]
            gives_b = [values.get(x) for x, f, _t in legs if f == b]
            if all(isinstance(v, (int, float)) and v and v > 0 for v in (*gives_a, *gives_b)):
                for me, send, recv in ((a, gives_a, gives_b), (b, gives_b, gives_a)):
                    s_adj, r_adj, _sv, _rv = adjusted_pair_totals(send, recv)
                    # The band owner's own base: v2 (OD-F2) divides by the larger
                    # package utility, v1 by the larger adjusted side.
                    if hasattr(fairness_bands, "larger_package_utility"):
                        denom = fairness_bands.larger_package_utility(send, recv)
                    else:
                        denom = max(s_adj, r_adj)
                    band = fairness_bands.classify(r_adj - s_adj, denom)
                    if hasattr(fairness_bands, "counts_as_fair_trade"):
                        is_fair = fairness_bands.counts_as_fair_trade(band["level"])
                    else:
                        is_fair = band["level"] == "fair"
                    expected = "FAIR" if is_fair else "NOT_FAIR"
                    if pub_states[me] != expected:
                        counts["P4_independentRecompute_violations"] += 1
                        _example(
                            "P4",
                            {
                                "shape": shape,
                                "legs": legs,
                                "team": me,
                                "expected": expected,
                                "public": pub_states[me],
                            },
                        )

        # D1: the private roster-aware decision vs the public market answer.
        tc = privates["team_context:PUSH"]
        for rid, entry in tc["teams"].items():
            if base[int(rid)] not in ("FAIR", "NOT_FAIR"):
                continue
            counts["D1_teamEvaluations"] += 1
            level, release = _objective_band(entry)
            if level is None:
                continue
            private_fair = level == "fair"
            public_fair = base[int(rid)] == "FAIR"
            if private_fair != public_fair:
                counts["D1_privateComponentA_differs"] += 1
                if release:
                    counts["D1_privateComponentA_differs_dueToForcedRelease"] += 1
                    _example(
                        "D1_forcedRelease",
                        {
                            "shape": shape,
                            "legs": legs,
                            "team": int(rid),
                            "public": base[int(rid)],
                            "privateComponentA": level,
                            "category": entry.get("category"),
                        },
                    )
            cat = str(entry.get("category"))
            bucket = (
                "D1_privateCategory_whenPublicFair"
                if public_fair
                else "D1_privateCategory_whenPublicNotFair"
            )
            counts[bucket][cat] = counts[bucket].get(cat, 0) + 1
            if public_fair and cat != "APPROXIMATELY_EVEN":
                counts["D1_privateCategory_notEven_whenPublicFair"] += 1
                _example(
                    "D1_category",
                    {
                        "shape": shape,
                        "legs": legs,
                        "team": int(rid),
                        "category": cat,
                        "reason": entry.get("categoryReason"),
                    },
                )
    trade_simulator.competitive_posture_for = real_posture

    failed = any(
        counts[k]
        for k in (
            "P1_teamContextInvariant_violations",
            "P2_publicEqualsEngine_violations",
            "P3_twoTeamSymmetry_violations",
            "P4_independentRecompute_violations",
            "P5_valueFree_violations",
        )
    )
    return {
        "codeRoot": str(code_root),
        "rosterSize": roster_size,
        "seed": seed,
        "bands": fairness_bands.receipt().get("version"),
        "counts": counts,
        "examples": examples,
        "ok": not failed,
    }


def bands_symmetry(bands_root: Path, n: int, seed: int) -> dict[str, Any]:
    """Pure math: under a band owner, does swapping a 2-team trade's sides
    ever change the band level?  Loads ``src/valuation_math`` from the root."""
    sys.path.insert(0, str(bands_root))
    spec = importlib.util.spec_from_file_location(
        "audit_fairness_bands", bands_root / "src" / "valuation_math" / "fairness_bands.py"
    )
    fb = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(fb)
    from src.valuation_math.package_model import adjusted_pair_totals  # noqa: PLC0415

    rng = random.Random(seed)
    mismatches = 0
    fair_by_level: dict[str, int] = {}
    for _ in range(n):
        send = [rng.uniform(50, 9999) for _ in range(rng.randint(1, 6))]
        recv = [rng.uniform(50, 9999) for _ in range(rng.randint(1, 6))]
        levels = []
        for s, r in ((send, recv), (recv, send)):
            s_adj, r_adj, _a, _b = adjusted_pair_totals(s, r)
            if hasattr(fb, "larger_package_utility"):
                base = fb.larger_package_utility(s, r)
            else:
                base = max(s_adj, r_adj)
            levels.append(fb.classify(r_adj - s_adj, base)["level"])
        if levels[0] != levels[1]:
            mismatches += 1
        fair_by_level[levels[0]] = fair_by_level.get(levels[0], 0) + 1
    receipt = fb.receipt()
    return {
        "bandsRoot": str(bands_root),
        "version": receipt.get("version"),
        "status": receipt.get("status"),
        "samples": n,
        "swapMismatches": mismatches,
        "levels": fair_by_level,
        "hasCountsAsFairTrade": hasattr(fb, "counts_as_fair_trade"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--code-root", type=Path, required=True)
    ap.add_argument(
        "--roster-size", type=int, default=6, help="cap; 6 puts the 6-man team at the cap"
    )
    ap.add_argument("--random", type=int, default=60, help="random 3- and 4-team trades each")
    ap.add_argument("--seed", type=int, default=20261020)
    ap.add_argument("--bands-root", type=Path, default=None)
    args = ap.parse_args()
    if args.bands_root is not None:
        out = bands_symmetry(args.bands_root, 20000, args.seed)
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0 if out["swapMismatches"] == 0 else 1
    out = run(args.code_root, args.roster_size, args.random, args.seed)
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
