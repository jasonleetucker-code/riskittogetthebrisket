"""Workstream G2 IDP source-integrity evaluation: deterministic unit tests.

Synthetic panels only (no live board, no network).  Plus the shadow-isolation
guard: nothing in production imports the research module, and the module imports
only an allow-listed owner.
"""

from __future__ import annotations

import ast
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.robust_filter_shadow import idp_source_integrity_g2 as g2

REPO = Path(__file__).resolve().parents[2]
MODULE = REPO / "src" / "robust_filter_shadow" / "idp_source_integrity_g2.py"
PREREG = (
    REPO / "docs" / "valuation" / "idp_accuracy" / "g2_source_integrity" / "PREREGISTRATION.json"
)


# ── builders ───────────────────────────────────────────────────────────


def _row(name, fam="LB", pid="1", sleeper_name=None, sleeper_fam=None, eligible=None, value=1000.0):
    return {
        "name": name,
        "key": g2._name_key(name),
        "playerId": pid,
        "family": fam,
        "sleeperName": sleeper_name if sleeper_name is not None else name,
        "sleeperFamily": sleeper_fam or fam,
        "eligibleFamilies": eligible if eligible is not None else [fam],
        "value": value,
        "rank": 1,
        "quarantined": False,
        "anomalyFlags": [],
        "droppedSources": [],
        "confidence": "low",
    }


def _obs(row, source, provider, value, raw=1.0, eff=1.0, voted=True, **kw):
    base = {
        "row": row,
        "source": source,
        "provider": provider,
        "voted": voted,
        "exclusion": None if voted else kw.pop("exclusion", "freshness_or_health_zero_weight"),
        "rawRank": raw,
        "effectiveRank": eff,
        "value": value,
        "valuePath": "rank_hill",
        "method": "exact",
        "scope": "overall_idp",
        "sharedMarketTranslated": False,
        "freshness": 1.0,
        "freshnessAgeHours": 1.0,
        "appliedWeight": 1.0,
        "matchedName": row,
        "ambiguous": False,
        "candidates": 1,
        "candidateNames": [row],
        "candidateKeys": [g2._name_key(row)],
        "vendorResolution": "single",
        "vendorPosition": None,
        "vendorValue": None,
        "vendorFamily": None,
        "vendorFamilies": [],
    }
    base.update(kw)
    return base


def _three_provider_panel(n=30):
    rows, obs = [], []
    for i in range(n):
        name = f"Player {i:02d}"
        fam = ("DL", "LB", "DB")[i % 3]
        rows.append(_row(name, fam, pid=str(100 + i), value=5000.0 - 100 * i))
        v = 5000.0 - 100 * i
        obs.append(_obs(name, "idpTradeCalc", "idpTradeCalculator", v, raw=i + 1, eff=i + 1))
        obs.append(_obs(name, "draftSharksIdp", "draftSharks", v * 1.05, raw=i + 1, eff=i + 2))
        obs.append(_obs(name, "fantasyProsIdp", "fantasyPros", v * 0.95, raw=i + 1, eff=i + 3))
    return {"rows": rows, "observations": obs}


def _big_panel(n=300):
    """Like ``_three_provider_panel`` but every value stays positive (geometric decay),
    so the injectors can reach the registered counts (E6: 200 rows)."""
    panel = _three_provider_panel(n)
    for r in panel["rows"]:
        i = int(r["name"].split()[-1])
        r["value"] = 5000.0 * 0.985**i
    for o in panel["observations"]:
        i = int(o["row"].split()[-1])
        scale = {"idpTradeCalc": 1.0, "draftSharksIdp": 1.05, "fantasyProsIdp": 0.95}[o["source"]]
        o["value"] = 5000.0 * 0.985**i * scale
        o["vendorFamily"] = ("DL", "LB", "DB")[i % 3]
    return panel


# ── preregistration lock ───────────────────────────────────────────────


def test_thresholds_match_preregistration():
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    assert prereg["thresholds"] == g2.THRESHOLDS


def test_injection_floors_are_the_registered_counts():
    """Deviation D4 enforces counts the registered E-gate text states; it adds none."""
    egates = json.loads(PREREG.read_text(encoding="utf-8"))["eGates"]
    for gate, n in g2.REGISTERED_INJECTIONS.items():
        assert f"{n}" in egates[gate].split(":")[0] or egates[gate].startswith(f"{n} "), gate
    assert f"fewer than {g2.E7_MIN_SWAPS} swaps" in egates["E7_wrong_player_swap"]
    assert "INSUFFICIENT, never pass" in egates["E7_wrong_player_swap"]


def test_broad_change_mirrors_dataset_state_config():
    cfg = json.loads((REPO / "config/sources/freshness_v1.json").read_text(encoding="utf-8"))
    assert g2.THRESHOLDS["broadChangeMinRows"] == cfg["broadChange"]["minRows"]
    assert g2.THRESHOLDS["broadChangeMinFraction"] == cfg["broadChange"]["minFraction"]


# ── identity / family ──────────────────────────────────────────────────


def test_vendor_family_mismatch_is_defect_and_alt_eligible_is_advisory():
    rows = [_row("A Lb", "LB"), _row("B Edge", "LB", eligible=["DL", "LB"])]
    obs = [
        _obs("A Lb", "draftSharksIdp", "draftSharks", 100, vendorFamily="DB", vendorPosition="CB"),
        _obs(
            "B Edge", "draftSharksIdp", "draftSharks", 100, vendorFamily="DL", vendorPosition="DE"
        ),
    ]
    codes = {
        (f["row"], f["code"], f["severity"])
        for f in g2.identity_findings({"rows": rows, "observations": obs})
    }
    assert ("A Lb", "vendor_family_mismatch", g2.DEFECT) in codes
    assert ("B Edge", "vendor_family_alt_eligible", g2.ADVISORY) in codes


def test_sleeper_name_and_family_contradictions():
    rows = [
        _row("Right Name", "LB", sleeper_name="Someone Else"),
        _row("Fam Clash", "LB", sleeper_fam="DB", eligible=["DB"]),
        _row("Multi", "LB", sleeper_fam="DL", eligible=["DL", "LB"]),
    ]
    codes = {
        (f["row"], f["code"]) for f in g2.identity_findings({"rows": rows, "observations": []})
    }
    assert ("Right Name", "sleeper_name_mismatch") in codes
    assert ("Fam Clash", "sleeper_family_contradiction") in codes
    assert ("Multi", "family_multi_eligible") in codes
    assert ("Multi", "sleeper_family_contradiction") not in codes


def test_vendor_entry_resolution_cases():
    single = [{"rawName": "X", "family": "LB", "position": "LB", "rank": 1, "value": None}]
    assert g2._vendor_entry(single, "X")[1] == "single"
    collide = [
        {"rawName": "Byron Murphy II", "family": "DL", "position": "DT", "rank": 1, "value": None},
        {"rawName": "Byron Murphy Jr.", "family": "DB", "position": "CB", "rank": 2, "value": None},
    ]
    ent, how = g2._vendor_entry(collide, "Byron Murphy II")
    assert how == "exact_among_collision" and ent["family"] == "DL"
    same = [
        {"rawName": "Byron Murphy", "family": "DL", "position": "DT", "rank": 1, "value": None},
        {"rawName": "Byron Murphy", "family": "DB", "position": "CB", "rank": 2, "value": None},
    ]
    ent, how = g2._vendor_entry(same, "Byron Murphy")
    assert how == "dual_listing" and ent["family"] is None and ent["families"] == ["DB", "DL"]
    assert g2._vendor_entry(collide, "Byron Murphy")[1] == "unresolvable"
    assert g2._vendor_entry([], "X") == (None, "absent")


def test_dual_listing_outside_eligibility_is_defect():
    rows = [_row("Two Fam", "DL", eligible=["DL"])]
    obs = [
        _obs(
            "Two Fam",
            "idpShowCombined",
            "theIdpShow",
            100,
            vendorResolution="dual_listing",
            vendorFamilies=["DB", "DL"],
        )
    ]
    codes = {f["code"] for f in g2.identity_findings({"rows": rows, "observations": obs})}
    assert "dual_listing_wrong_family" in codes


def test_shared_vendor_entry_and_alias_join():
    rows = [_row("P One", "LB", pid="1"), _row("P Two", "LB", pid="2")]
    obs = [
        _obs("P One", "idpTradeCalc", "idpTradeCalculator", 100, matchedName="P One"),
        _obs("P Two", "idpTradeCalc", "idpTradeCalculator", 100, matchedName="P One"),
        _obs(
            "P One",
            "draftSharksIdp",
            "draftSharks",
            100,
            candidateNames=["P One", "Pee One"],
            candidateKeys=sorted({g2._name_key("P One"), g2._name_key("Pee One")}),
        ),
    ]
    found = {
        (f["row"], f["source"], f["code"])
        for f in g2.identity_findings({"rows": rows, "observations": obs})
    }
    assert ("P One", "idpTradeCalc", "shared_vendor_entry") in found
    assert ("P Two", "idpTradeCalc", "shared_vendor_entry") in found
    assert ("P One", "draftSharksIdp", "ambiguous_alias_join") in found


# ── normalization ──────────────────────────────────────────────────────


def test_translation_inversion_ignores_ties_in_source_rank():
    ranked = [
        {"row": "a", "rawRank": 1.0, "effectiveRank": 10.0},
        {"row": "b", "rawRank": 2.0, "effectiveRank": 30.0},
        {"row": "c", "rawRank": 2.0, "effectiveRank": 20.0},  # tie: any order is fine
        {
            "row": "d",
            "rawRank": 3.0,
            "effectiveRank": 25.0,
        },  # worse rank, better than b -> inversion
    ]
    assert g2._translation_inversions(ranked) == [("b", "d")]


def test_rank_basis_probe_restart_vs_dominance_vs_ties():
    k = g2.THRESHOLDS["basisProbeK"]
    # combined list, LB dominant but DL/DB interleave near the top with distinct values
    dominance = [("LB", float(r), 1000 - r) for r in range(1, 40) if r not in (5, 12, 30, 33, 36)]
    dominance += [("DL", float(r), 1000 - r) for r in (5, 30, 33)] + [
        ("DL", float(60 + 3 * i), 0) for i in range(k)
    ]
    dominance += [("DB", float(r), 1000 - r) for r in (12, 36)] + [
        ("DB", float(80 + 3 * i), 0) for i in range(k)
    ]
    res = g2.rank_basis_probe(dominance)
    assert res["evaluable"] and not res["mixed"] and res["familyDominanceOnly"]
    # DB restarted 1..n on a combined board: collisions with distinct values
    restart = [
        (f, float(3 * i + j + 1), 1000 - (3 * i + j))
        for i in range(40)
        for j, f in enumerate(("DL", "LB"))
    ]
    restart += [("DB", float(i + 1), None) for i in range(40)]
    assert g2.rank_basis_probe(restart)["mixed"]
    # cross-market board: IDP ranks start deep; a restarted family sits above all others
    deep = [(f, float(100 + 3 * i + j), 0) for i in range(40) for j, f in enumerate(("DL", "LB"))]
    deep += [("DB", float(i + 1), None) for i in range(40)]
    assert g2.rank_basis_probe(deep)["mixed"]
    # equal vendor values at one rank are a tie, not a collision
    ties = [("LB", float(r), 1000 - r) for r in range(1, 40)]
    ties += [("DL", float(r), 1000 - r) for r in range(1, 40, 2)] + [
        ("DL", float(60 + i), 0) for i in range(k)
    ]
    ties += [("DB", float(r), 1000 - r) for r in range(2, 40, 3)] + [
        ("DB", float(90 + i), 0) for i in range(k)
    ]
    res = g2.rank_basis_probe(ties)
    assert res["crossFamilyCollisionShare"] == 0.0 and not res["mixed"]


# ── disagreement / providers ───────────────────────────────────────────


def test_one_vote_per_provider_and_classes():
    rows = [_row("X")]
    obs = [
        _obs("X", "dlfIdp", "dynastyLeagueFootball", 1000),
        _obs("X", "dlfRookieIdp", "dynastyLeagueFootball", 1200),
        _obs("X", "idpTradeCalc", "idpTradeCalculator", 1100),
        _obs("X", "draftSharksIdp", "draftSharks", 4000),
        _obs("X", "fantasyProsIdp", "fantasyPros", 900, voted=False),
    ]
    panel = {"rows": rows, "observations": obs}
    votes = g2.provider_votes(panel)
    assert votes["X"] == {
        "draftSharks": 4000.0,
        "dynastyLeagueFootball": 1100.0,
        "idpTradeCalculator": 1100.0,
    }
    dis = {d["provider"]: d for d in g2.disagreement(panel)}
    assert dis["draftSharks"]["class"] == "extreme"  # ln(4000/1100) > ln 3
    assert dis["idpTradeCalculator"]["class"] == "dissent"  # ln(1100/2550): between ln 2 and ln 3


def test_two_provider_rows_are_not_evaluable_never_zero():
    panel = {
        "rows": [_row("Y")],
        "observations": [
            _obs("Y", "idpTradeCalc", "idpTradeCalculator", 10),
            _obs("Y", "draftSharksIdp", "draftSharks", 100),
        ],
    }
    assert {d["class"] for d in g2.disagreement(panel)} == {"not_evaluable"}


def test_extreme_attribution_needs_structural_evidence():
    panel = _three_provider_panel(9)
    panel["observations"][1]["value"] *= 10  # Player 00, draftSharks
    panel["observations"][1]["vendorFamily"] = "DB"  # row family DL: structural defect
    panel["observations"][4]["value"] *= 10  # Player 01, draftSharks, no structural defect
    res = g2.evaluate_panel(panel)
    att = {(e["row"], e["provider"]): e["attribution"] for e in res["disagreement"]["extreme"]}
    assert att[("Player 00", "draftSharks")] == "data_error_corroborated"
    assert att[("Player 01", "draftSharks")] == "unexplained_extreme_dissent"


def test_segment_shift_detects_whole_segment_scale():
    panel = _three_provider_panel(60)
    clean = {
        (s["provider"], s["family"]): s["shift"]
        for s in g2.segment_shifts(panel, g2.disagreement(panel))
    }
    assert not any(clean.values())
    inj = g2.inject_segment_scale(panel, "draftSharks", "LB", 5.0)
    got = {
        (s["provider"], s["family"]): s["shift"]
        for s in g2.segment_shifts(inj, g2.disagreement(inj))
    }
    assert got[("draftSharks", "LB")] and not got[("draftSharks", "DL")]


# ── stale / coverage / exclusions ──────────────────────────────────────


def test_stale_verdicts():
    vs = {
        "sources": [
            {"key": "a", "lastGenuineUpdate": "2026-01-10T12:00:00Z"},
            {
                "key": "b",
                "lastGenuineUpdate": "2026-01-01T00:00:00Z",
                "lastGenuineUpdateBasis": "publisher_timestamp",
            },
            {"key": "c", "lastGenuineUpdate": "2026-01-10T00:00:00Z"},
        ]
    }
    clocks = {
        "a": {"lastByteChange": "2026-01-10T00:00:00Z", "lastBroadChange": "2026-01-10T00:00:00Z"},
        "b": {"lastByteChange": "2026-01-12T00:00:00Z", "lastBroadChange": "2026-01-11T00:00:00Z"},
        "c": {"lastByteChange": "2026-01-10T03:00:00Z", "lastBroadChange": None},
    }
    got = {r["source"]: r["verdict"] for r in g2.stale_findings(vs, clocks, ["a", "b", "c", "d"])}
    assert got == {
        "a": "stamp_after_content",
        "b": "vendor_stamp_older_than_broad_change",
        "c": "consistent",
        "d": "not_evaluable",
    }


def test_priced_row_without_vote_is_reported_and_excluded_obs_never_vote():
    panel = {
        "rows": [_row("Z", value=500.0)],
        "observations": [_obs("Z", "idpShowCombined", "theIdpShow", 900, voted=False)],
    }
    res = g2.evaluate_panel(panel)
    assert res["coverage"]["pricedRowsWithoutVote"] == ["Z"]
    assert res["counts"]["votes"] == 0


def test_filter_drop_without_defect_is_false_exclusion_candidate():
    panel = _three_provider_panel(3)
    o = panel["observations"][2]
    o["voted"], o["exclusion"] = False, "outlier_filter"
    res = g2.evaluate_panel(panel)
    assert res["exclusions"]["falseExclusionCandidates"] == [
        {"row": "Player 00", "source": "fantasyProsIdp", "value": o["value"]}
    ]


# ── determinism / injections ───────────────────────────────────────────


def test_evaluation_is_deterministic():
    panel = _three_provider_panel(30)
    assert (
        g2.evaluate_panel(panel)["digest"]
        == g2.evaluate_panel(json.loads(json.dumps(panel)))["digest"]
    )


def test_injections_are_seeded_and_detected():
    panel = _three_provider_panel(60)
    a, la = g2.inject_row_corruption(panel, 10, 7, 8.0)
    b, lb = g2.inject_row_corruption(panel, 10, 7, 8.0)
    assert la == lb and g2.digest(a) == g2.digest(b)
    assert len({r for r, _p in la}) == len(la)  # one corrupted vote per row
    ext = {(d["row"], d["provider"]) for d in g2.disagreement(a) if d["class"] == "extreme"}
    assert all(tuple(x) in ext for x in la)
    assert math.isclose(
        sum(o["value"] for o in panel["observations"]),
        sum(o["value"] for o in _three_provider_panel(60)["observations"]),
    )


def test_e_gates_on_synthetic_panel():
    panel = _big_panel(300)
    gates = g2.run_e_gates(panel, seed=1)
    for name in (
        "E1_determinism",
        "E2_vendor_family",
        "E3_sleeper_id",
        "E4_shared_entry",
        "E6_row_corruption",
        "E8_rank_inversion",
        "E9_stale_stamp",
        "E11_rank_basis_restart",
    ):
        assert gates[name]["pass"], (name, gates[name])
        assert gates[name]["verdict"] == "PASS"
    assert gates["E6_row_corruption"]["injected"] == 200


def test_e1_digest_is_the_reported_evaluation_digest_with_lineage():
    panel = _three_provider_panel(30)
    lineage = {"sources": {"idpTradeCalc": {"provider": "idpTradeCalculator"}}}
    gates = g2.run_e_gates(panel, seed=1, lineage=lineage)
    assert gates["E1_determinism"]["digest"] == g2.evaluate_panel(panel, lineage=lineage)["digest"]
    assert gates["E1_determinism"]["digest"] != g2.evaluate_panel(panel)["digest"]


def test_gates_below_their_registered_count_are_insufficient_never_pass():
    # 50 positive rows: E6 can build only 50 of its registered 200 corruptions and
    # E7 fewer than 20 swaps -- both are INSUFFICIENT even at perfect recall.
    gates = g2.run_e_gates(_three_provider_panel(90), seed=1)
    e6, e7 = gates["E6_row_corruption"], gates["E7_wrong_player_swap"]
    assert e6["injected"] < 200 and e6["recall"] == 1.0
    assert e6["verdict"] == "INSUFFICIENT" and e6["pass"] is False
    assert 0 < e7["injected"] < 20
    assert e7["verdict"] == "INSUFFICIENT" and e7["pass"] is False
    assert e7["recallWilson95Lower"] is not None


def test_e7_floor_is_enforced_even_at_full_recall(monkeypatch):
    """5 swaps detected 5/5 is INSUFFICIENT (the reviewer's case), 20/20 passes."""
    panel = _big_panel(300)

    def swaps(k):
        def fake(p, n, seed, min_ratio=4.0):
            inj = json.loads(json.dumps(p))
            labels = []
            for i in range(k):
                a, b = f"Player {i:02d}", f"Player {i + 150:02d}"
                for o in inj["observations"]:
                    if o["source"] == "idpTradeCalc" and o["row"] == a:
                        o["value"] *= 20
                labels.append((a, b, "idpTradeCalculator"))
            return inj, labels

        return fake

    monkeypatch.setattr(g2, "inject_swaps", swaps(5))
    e7 = g2.run_e_gates(panel, seed=1)["E7_wrong_player_swap"]
    assert (e7["injected"], e7["recall"], e7["verdict"], e7["pass"]) == (
        5,
        1.0,
        "INSUFFICIENT",
        False,
    )
    monkeypatch.setattr(g2, "inject_swaps", swaps(20))
    e7 = g2.run_e_gates(panel, seed=1)["E7_wrong_player_swap"]
    assert (e7["injected"], e7["verdict"], e7["pass"]) == (20, "PASS", True)


def test_wilson_lower_bound():
    assert g2.wilson_lower(0, 0) is None
    assert math.isclose(g2.wilson_lower(19, 21), 0.711, abs_tol=0.002)
    assert math.isclose(g2.wilson_lower(5, 5), 0.566, abs_tol=0.002)


def test_b_gates_are_emitted_and_scoped_to_idp_sources():
    panel = _three_provider_panel(30)
    panel["observations"].append(
        _obs(
            "Player 05",
            "fantasyNavigatorSf",
            "fantasyNavigator",
            None,
            voted=False,
            exclusion="not_voting_by_registry_or_hold",
        )
    )
    lineage = {
        "sources": {
            "idpTradeCalc": {"provider": "idpTradeCalculator"},
            "draftSharksIdp": {"provider": "draftSharks"},
            "fantasyProsIdp": {"provider": "fantasyPros"},
        }
    }
    ev = g2.evaluate_panel(panel, lineage=lineage)
    b = g2.b_gates(ev, ["idpTradeCalc", "draftSharksIdp", "fantasyProsIdp"])
    assert all(b[k]["pass"] for k in b if k != "summary"), b
    assert b["summary"] == {
        "passed": 8,
        "failed": 0,
        "idpSources": ["draftSharksIdp", "fantasyProsIdp", "idpTradeCalc"],
        "nonIdpSourcesObserved": ["fantasyNavigatorSf"],
    }
    # an IDP source with no lineage provider fails B8; the offense source never does
    b = g2.b_gates(g2.evaluate_panel(panel, lineage={"sources": {}}), ["idpTradeCalc"])
    assert b["B8_lineage"]["verdict"] == "FAIL"
    assert b["B8_lineage"]["unregisteredIdpSources"] == ["idpTradeCalc"]
    # a failing check flips its gate
    bad = json.loads(json.dumps(ev))
    bad["segments"][0]["shift"] = True
    bad["exclusions"]["falseExclusionCandidates"] = [{"row": "x", "source": "y", "value": 1}]
    b = g2.b_gates(bad, ["idpTradeCalc", "draftSharksIdp", "fantasyProsIdp"])
    assert b["B5_false_exclusions"]["verdict"] == b["B6_segments"]["verdict"] == "FAIL"
    assert b["summary"]["failed"] == 2


# ── board refusal (the V2.1 seal) ──────────────────────────────────────


def test_seal_is_checked_before_any_archive_byte_is_read(monkeypatch):
    from scripts import research_idp_source_integrity_g2 as run  # noqa: PLC0415

    board = json.loads(run.BOARDS.read_text(encoding="utf-8"))["boards"][0]

    def never(*_a, **_k):
        raise AssertionError("archive read before the seal check")

    monkeypatch.setattr(run, "load_archive", never)
    monkeypatch.setattr(
        run,
        "add_commit",
        lambda rel: (board["addCommit"], datetime(2026, 11, 1, tzinfo=timezone.utc)),
    )
    for fn in (
        lambda: run.run(board["board"], board["role"], Path("unused.json"), 1),
        lambda: run.exploratory(board["board"], board["role"], Path("unused.json")),
    ):
        with pytest.raises(SystemExit, match="seal"):
            fn()


def test_script_refuses_boards_inside_the_v21_seal():
    from scripts import research_idp_source_integrity_g2 as run  # noqa: PLC0415

    assert run.in_v21_seal(datetime(2026, 10, 21, 1, 5, tzinfo=timezone.utc))
    assert run.in_v21_seal(datetime(2026, 12, 8, 23, 0, tzinfo=timezone.utc))
    assert not run.in_v21_seal(datetime(2026, 10, 20, 17, 38, 56, tzinfo=timezone.utc))
    assert not run.in_v21_seal(datetime(2026, 12, 9, 0, 0, tzinfo=timezone.utc))
    boards = json.loads(run.BOARDS.read_text(encoding="utf-8"))["boards"]
    for b in boards:
        when = datetime.fromisoformat(b["addCommitTime"].replace("Z", "+00:00"))
        assert not run.in_v21_seal(when), b["board"]


def test_changed_rows_ignores_renames():
    from scripts import research_idp_source_integrity_g2 as run  # noqa: PLC0415

    old = {"Camryn Bynum": 37.0, "A": 1.0, "B": 2.0}
    new = {"Cam Bynum": 37.0, "A": 1.0, "B": 3.0}
    assert run.changed_rows(old, new) == 1


def test_vendor_join_coverage_bands_and_unjoined_sources():
    contract = {
        "playersArray": [
            {"sourceAudit": {"matchedDetails": {"draftSharksIdp": {"matchedName": f"P{i}"}}}}
            for i in range(1, 50)
        ]
    }
    table = [{"Player": f"P{i}", "Rank": str(i), "Fantasy Position": "LB"} for i in range(1, 61)]
    table.append({"Player": "2027 Early 1st", "Rank": "61", "Fantasy Position": ""})
    cov = g2.vendor_join_coverage(
        contract, {"draftSharksIdp": table, "dlfIdp": [{"name": "X", "rank": "1"}]}
    )
    ds = cov["draftSharksIdp"]
    assert ds["vendorRowsConsidered"] == 60
    assert ds["bands"]["1-50"]["unjoined"] == 1 and ds["bands"]["51-150"]["unjoined"] == 10
    assert ds["orderBasis"] == "file_order" and ds["rankColumnMonotoneInFileOrder"] is True
    assert cov["dlfIdp"]["evaluable"] is False and cov["dlfIdp"]["bands"] == {}


def test_vendor_join_coverage_file_order_and_absence_rule():
    """FantasyPros-style: per-position originalRank after the combined head must not
    re-sort the list; an unjoined name carried by ANOTHER source's join (an alias) or
    sharing an IDP row's key is on the board, everything else is absent."""
    board = [
        {
            "displayName": "Jaylahn Tuimoloau",
            "assetClass": "idp",
            "position": "DL",
            "sourceAudit": {"matchedDetails": {"idpTradeCalc": {"matchedName": "JT Tuimoloau"}}},
        },
        {
            "displayName": "Kept Player",
            "assetClass": "idp",
            "position": "LB",
            "sourceAudit": {"matchedDetails": {"fantasyProsIdp": {"matchedName": "Kept Player"}}},
        },
        {"displayName": "Other Key", "assetClass": "idp", "position": "CB", "sourceAudit": {}},
        {"displayName": "Byron Murphy", "assetClass": "idp", "position": "DT", "sourceAudit": {}},
    ]
    fp = [{"name": "Kept Player", "originalRank": "1", "family": "LB"}]
    fp += [{"name": f"Head {i}", "originalRank": str(i), "family": "LB"} for i in range(2, 52)]
    # past the combined head the vendor rank restarts per position
    fp.append({"name": "JT Tuimoloau", "originalRank": "3", "family": "DL"})
    fp.append({"name": "Other Key", "originalRank": "4", "family": "DB"})
    fp.append({"name": "Gone Player", "originalRank": "5", "family": "DB"})
    # same name key as the DT row, different family: a collision, still absent
    fp.append({"name": "Byron Murphy Jr.", "originalRank": "6", "family": "DB"})
    idptc = [{"name": "Gone Player", "value": "100"}]
    cov = g2.vendor_join_coverage(
        {"playersArray": board}, {"fantasyProsIdp": fp, "idpTradeCalc": idptc}
    )["fantasyProsIdp"]
    assert cov["rankColumnMonotoneInFileOrder"] is False
    band = cov["bands"]["51-150"]  # file order: positions 51..55
    assert band["rows"] == 5
    assert band["onBoardOtherName"] == ["JT Tuimoloau", "Other Key"]
    assert band["absent"] == ["Head 51", "Gone Player", "Byron Murphy Jr."]
    assert band["absentInIdpTradeCalc"] == ["Gone Player"]


# ── isolation ──────────────────────────────────────────────────────────


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


@pytest.mark.parametrize("root", ["src", "server.py", "frontend"])
def test_nothing_in_production_imports_the_research_module(root):
    target = "idp_source_integrity_g2"
    base = REPO / root
    files = (
        [base]
        if base.is_file()
        else [p for p in base.rglob("*.py") if "node_modules" not in p.parts]
    )
    for path in files:
        if path.resolve() == MODULE.resolve():
            continue
        assert not any(target in m for m in _imports(path)), path


def test_module_imports_only_allowlisted_owners():
    allowed_src = {"src.utils.name_clean"}
    for mod in _imports(MODULE):
        if mod.startswith("src."):
            assert mod in allowed_src, mod
