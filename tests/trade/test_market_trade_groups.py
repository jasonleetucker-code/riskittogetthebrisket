"""§19 dedupe: one real trade counts once; distinct trades are never merged."""

from __future__ import annotations

import random
import time

import pytest

from src.trade import market_trade_groups as G


def P(cid):  # resolved asset
    return {
        "kind": "player" if cid.startswith("player:") else "pick",
        "canonicalId": cid,
        "matchKey": cid,
    }


def U(ref):  # unresolved asset
    return {"kind": "unresolved", "canonicalId": None, "matchKey": f"unresolved:{ref}"}


def obs(
    oid,
    sides,
    *,
    src="ktc_trade_database",
    league="L1",
    tx=None,
    date="2026-10-01",
    host="sleeper",
    **extra,
):
    return {
        "observationId": oid,
        "sourceFamily": src,
        "sourceNativeId": oid.split(":")[-1],
        "host": host,
        "hostLeagueId": league,
        "hostTxId": tx,
        "occurredDate": date,
        "teamCount": len(sides),
        "sides": sides,
        "provenance": [{"ktc_trade_database": "KTC_MARKET"}.get(src, "SHARP_DISCOVERY")],
        **extra,
    }


A_FOR_B = [[P("player:1")], [P("player:2"), P("mpick:2027:r1")]]
B_FOR_A = [[P("mpick:2027:r1"), P("player:2")], [P("player:1")]]


def test_repeat_crawl_of_one_sleeper_trade_counts_once():
    s1 = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", tx="T1")
    s2 = obs("own:main:T1", A_FOR_B, src="own_league_sleeper", tx="T1")
    res = G.group_observations([s1, s2, s1])  # the repeated object is the same observation
    assert res.volume["underlyingTradesPointEstimate"] == 1
    g = res.groups[0]
    assert g["dedupeState"] == G.CONFIRMED_DUPLICATE
    assert g["underlyingTradeId"] == G.underlying_trade_id_for_host_tx("sleeper", "L1", "T1")


def test_same_league_reached_via_two_sharp_managers_is_one_trade():
    via_a = obs(
        "sleeper:L1:T1",
        A_FOR_B,
        src="sleeper_sharp_discovery",
        tx="T1",
        sampleProvenance={"viaUserId": "a"},
    )
    via_b = obs(
        "sleeper:L1:T1#b",
        A_FOR_B,
        src="sleeper_sharp_discovery",
        tx="T1",
        sampleProvenance={"viaUserId": "b"},
    )
    res = G.group_observations([via_a, via_b])
    assert len(res.groups) == 1
    assert len(res.groups[0]["sampleProvenance"]) == 2, "both routes kept as provenance"


def test_proven_cross_source_match_collapses_and_keeps_both_provenances():
    s = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", tx="T1")
    k = obs("ktc:9", B_FOR_A, crossRefs=[("sleeper", "L1", "T1")])
    res = G.group_observations([s, k])
    assert len(res.groups) == 1
    g = res.groups[0]
    assert g["dedupeState"] == G.CONFIRMED_DUPLICATE
    assert G.REL_CROSS_SOURCE in g["relations"]
    assert g["provenance"] == ["KTC_MARKET", "SHARP_DISCOVERY"]


def test_unique_same_league_same_package_same_day_is_probable_and_counted_once():
    s = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", tx="T1")
    k = obs("ktc:9", B_FOR_A, date="2026-10-02")  # KTC day may lag by one
    res = G.group_observations([s, k])
    assert len(res.groups) == 1 and res.groups[0]["dedupeState"] == G.PROBABLE_DUPLICATE
    assert res.volume["underlyingTradesUpperBound"] == 2
    assert res.volume["underlyingTradesLowerBound"] == 1
    assert res.groups[0]["underlyingTradeId"] == "utrade:sleeper:L1:T1"


def test_identical_packages_in_two_distinct_leagues_stay_two():
    a = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", league="L1", tx="T1")
    b = obs("sleeper:L2:T7", A_FOR_B, src="sleeper_sharp_discovery", league="L2", tx="T7")
    k1 = obs("ktc:1", A_FOR_B, league="L3")
    k2 = obs("ktc:2", A_FOR_B, league="L4")
    res = G.group_observations([a, b, k1, k2])
    assert len(res.groups) == 4
    assert all(g["dedupeState"] == G.CONFIRMED_UNIQUE for g in res.groups)


def test_two_host_transactions_in_one_league_are_never_merged():
    a = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", tx="T1")
    b = obs("sleeper:L1:T2", A_FOR_B, src="sleeper_sharp_discovery", tx="T2")
    res = G.group_observations([a, b])
    assert len(res.groups) == 2


def test_reversed_sides_do_not_evade_dedupe():
    assert G.package_signature(obs("x", A_FOR_B)) == G.package_signature(obs("y", B_FOR_A))


def test_ambiguous_candidate_is_possible_overlap_not_a_guess():
    # Two identical host trades in one league on one day; one KTC row matches
    # both.  Which one is it?  Unknowable — so nothing merges.
    s1 = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", tx="T1")
    s2 = obs("sleeper:L1:T2", A_FOR_B, src="sleeper_sharp_discovery", tx="T2")
    k = obs("ktc:9", A_FOR_B)
    res = G.group_observations([s1, s2, k])
    assert len(res.groups) == 3
    ktc_group = next(g for g in res.groups if g["members"] == ["ktc:9"])
    assert ktc_group["dedupeState"] == G.POSSIBLE_OVERLAP
    assert len(ktc_group["possibleOverlapWith"]) == 2
    assert res.volume["underlyingTradesLowerBound"] < res.volume["underlyingTradesPointEstimate"]


def test_unresolved_possible_duplicate_stays_explicitly_unresolved():
    s = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", tx="T1")
    k = obs("ktc:9", [[U("ktc:77")], [P("player:2"), P("mpick:2027:r1")]])
    res = G.group_observations([s, k])
    assert len(res.groups) == 2, "never deleted, never merged"
    states = {g["members"][0]: g["dedupeState"] for g in res.groups}
    assert states["ktc:9"] == G.POSSIBLE_OVERLAP
    assert states["sleeper:L1:T1"] == G.POSSIBLE_OVERLAP


def test_league_unknown_is_at_most_possible():
    s = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", tx="T1")
    k = obs("ktc:9", A_FOR_B, league=None, host="unknown")
    res = G.group_observations([s, k])
    assert len(res.groups) == 2
    assert {g["dedupeState"] for g in res.groups} == {G.POSSIBLE_OVERLAP}


def test_dates_apart_are_distinct():
    s = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", tx="T1", date="2026-10-01")
    k = obs("ktc:9", A_FOR_B, date="2026-10-05")
    assert len(G.group_observations([s, k]).groups) == 2


def test_one_sharp_trade_cannot_cast_two_independent_votes():
    s = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", tx="T1")
    res = G.group_observations([s])
    utid = res.groups[0]["underlyingTradeId"]
    # The Sharp-behaviour analysis holds only Sleeper's (league, tx) — and can
    # derive the very same id, so the two uses resolve to one event.
    sharp_use = {
        "use": "sharp_behaviour",
        "underlyingTradeId": G.underlying_trade_id_for_host_tx("sleeper", "L1", "T1"),
    }
    market_use = {"use": "broad_market", "underlyingTradeId": utid}
    assert G.count_independent_events([sharp_use, market_use]) == 1


def test_ktc_provenance_never_adds_a_count():
    s = obs("sleeper:L1:T1", A_FOR_B, src="sleeper_sharp_discovery", tx="T1")
    k = obs("ktc:9", A_FOR_B, crossRefs=[("sleeper", "L1", "T1")])
    assert G.group_observations([s, k]).volume["underlyingTradesUpperBound"] == 1


# ── FAAB / partial-record recording gaps (review finding 2) ───────────────

FAAB_CAVEAT = G.FAAB_NOT_RECORDED_CAVEAT


def F(amount):  # KTC records FAAB money as an asset
    return {"kind": "faab", "canonicalId": None, "matchKey": f"faab:{amount}"}


def test_ktc_faab_asset_does_not_split_one_trade_from_its_sleeper_record():
    # Same trade, same league: KTC saw "$10 FAAB" ride along, Sleeper could not.
    s = obs(
        "sleeper:L1:T1",
        [[P("player:1")], [P("player:2")]],
        src="sleeper_sharp_discovery",
        tx="T1",
        caveats=[FAAB_CAVEAT],
    )
    k = obs("ktc:9", [[P("player:1")], [P("player:2"), F(10.0)]])
    assert G.classify_pair(s, k)[0] == G.REL_PROBABLE
    res = G.group_observations([s, k])
    assert len(res.groups) == 1 and res.groups[0]["dedupeState"] == G.PROBABLE_DUPLICATE


def test_faab_only_side_strips_to_an_empty_side_and_still_matches():
    s = obs(
        "sleeper:L1:T1",
        [[], [P("player:2")]],
        src="sleeper_sharp_discovery",
        tx="T1",
        caveats=[FAAB_CAVEAT],
    )
    k = obs("ktc:9", [[P("player:2")], [F(25.0)]])
    assert G.classify_pair(s, k)[0] == G.REL_PROBABLE


def test_faab_is_not_stripped_when_neither_side_lacks_it():
    a = obs("ktc:1", [[P("player:1")], [P("player:2"), F(10.0)]])
    b = obs("ktc:2", [[P("player:1")], [P("player:2")]])
    assert G.classify_pair(a, b)[0] == G.REL_DISTINCT


def test_faab_mismatch_without_league_identity_is_possible_not_distinct():
    s = obs(
        "sleeper:L1:T1",
        [[P("player:1")], [P("player:2")]],
        src="sleeper_sharp_discovery",
        tx="T1",
        caveats=[FAAB_CAVEAT],
    )
    k = obs("ktc:9", [[P("player:1")], [P("player:2"), F(10.0)]], league=None, host="unknown")
    assert G.classify_pair(s, k)[0] == G.REL_POSSIBLE
    res = G.group_observations([s, k])
    assert {g["dedupeState"] for g in res.groups} == {G.POSSIBLE_OVERLAP}


@pytest.mark.parametrize("caveat", ["partial_record_adds_without_sender:1", "released_in_trade:1"])
def test_partial_record_package_mismatch_is_at_most_possible(caveat):
    # Sleeper saw only part of the trade (one asset fewer than KTC).
    s = obs(
        "sleeper:L1:T1",
        [[P("player:1")], [P("player:2")]],
        src="sleeper_sharp_discovery",
        tx="T1",
        caveats=[caveat],
    )
    k = obs("ktc:9", [[P("player:1"), P("player:3")], [P("player:2")]])
    rel, evidence = G.classify_pair(s, k)
    assert rel == G.REL_POSSIBLE, evidence
    res = G.group_observations([s, k])
    assert len(res.groups) == 2, "possible overlap is never merged"
    assert {g["dedupeState"] for g in res.groups} == {G.POSSIBLE_OVERLAP}


def test_partial_record_team_count_mismatch_is_not_distinct():
    s = obs(
        "sleeper:L1:T1",
        [[P("player:1")], [P("player:2")]],
        src="sleeper_sharp_discovery",
        tx="T1",
        caveats=["partial_record_adds_without_sender:1"],
    )
    k = obs("ktc:9", [[P("player:1")], [P("player:2")], [P("player:3")]])
    assert G.classify_pair(s, k)[0] == G.REL_POSSIBLE


def test_complete_record_package_mismatch_stays_distinct():
    s = obs("sleeper:L1:T1", [[P("player:1")], [P("player:2")]], tx="T1")
    k = obs("ktc:9", [[P("player:1"), P("player:3")], [P("player:2")]])
    assert G.classify_pair(s, k)[0] == G.REL_DISTINCT


# ── Blocking: complete and bounded (review finding 1) ─────────────────────


def _brute_force_edges(observations, tol=G.DEFAULT_DAY_TOLERANCE):
    out = set()
    for i in range(len(observations)):
        for j in range(i + 1, len(observations)):
            rel, _ = G.classify_pair(observations[i], observations[j], day_tolerance=tol)
            if rel != G.REL_DISTINCT:
                out.add((i, j))
    return out


def test_blocking_drops_no_pair_classify_would_keep():
    """Property check against a brute-force scan on a dense random sample:
    every non-DISTINCT pair is a candidate (blocking is exact, not lossy)."""
    rng = random.Random(1586)
    assets = [f"player:{n}" for n in range(6)] + ["mpick:2026:r1", "mpick:2027:r1"]
    leagues = ["L1", "L2", None]
    caveat_pool = [[], [], [FAAB_CAVEAT], ["partial_record_adds_without_sender:1"]]
    rows = []
    for n in range(160):
        league = rng.choice(leagues)
        sides = [
            [P(a) for a in rng.sample(assets, rng.randint(1, 2))],
            [P(a) for a in rng.sample(assets, rng.randint(0, 2))],
        ]
        if rng.random() < 0.2:
            sides[1].append(F(rng.choice([5.0, 10.0])))
        if rng.random() < 0.1:
            sides[0].append(U(f"x{n}"))
        rows.append(
            obs(
                f"o:{n}",
                sides,
                league=league,
                host="sleeper" if league else "unknown",
                tx=(f"T{rng.randint(0, 40)}" if league and rng.random() < 0.5 else None),
                date=rng.choice(["2026-10-01", "2026-10-02", "2026-10-04", None]),
                caveats=rng.choice(caveat_pool),
            )
        )
    expected = _brute_force_edges(rows)
    assert expected, "non-vacuity: the sample must contain related pairs"
    candidates = G._candidate_pairs(rows, G.DEFAULT_DAY_TOLERANCE)
    assert expected <= candidates


def test_complexity_guard_20k_rows_sharing_generic_pick_keys():
    """20k rows that ALL share a generic pick key (the shape that made the
    asset-keyed blocking O(n^2): ~200M tuples) must stay bounded and fast."""
    n_rows, n_leagues = 20_000, 2_000
    rows = []
    for n in range(n_rows):
        league = f"L{n % n_leagues}"
        day = f"2026-09-{1 + (n // n_leagues) % 28:02d}"
        rows.append(
            obs(
                f"ktc:{n}",
                [[P("mpick:2026:r1"), P(f"player:{n % 977}")], [P(f"player:{(n * 7) % 983}")]],
                league=league,
                date=day,
            )
        )
    # Plus 500 league-less rows that share one identical generic package.
    for n in range(500):
        rows.append(
            obs(
                f"ktc:nl{n}",
                [[P("mpick:2026:r1")], [P("mpick:2027:r1")]],
                league=None,
                host="unknown",
                date=f"2026-09-{1 + n % 28:02d}",
            )
        )
    t0 = time.perf_counter()
    candidates = G._candidate_pairs(rows, G.DEFAULT_DAY_TOLERANCE)
    blocking_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    res = G.group_observations(rows)
    total_s = time.perf_counter() - t0
    # Asset-keyed blocking produced ~n^2/2 = 210M pairs here.
    assert len(candidates) < 200_000, len(candidates)
    assert res.volume["candidatePairsCompared"] == len(candidates)
    assert res.volume["rawObservations"] == n_rows + 500
    assert blocking_s < 10 and total_s < 60, (blocking_s, total_s)


def test_own_league_row_without_league_id_never_splits_from_its_partial_twin():
    """An own-league row recorded before the sleeperLeagueId column carries the
    real Sleeper tx id but no league id; its Sharp-discovery twin is a partial
    record with a different package.  Same tx id must never classify DISTINCT
    (one trade counted twice) -- at most POSSIBLE, and the two must meet in
    candidate blocking."""
    own = obs("own:main:T9", A_FOR_B, src="own_league_sleeper", tx="T9", league=None)
    twin = obs(
        "sleeper:L1:T9",
        [[P("player:1")], [P("player:2")]],
        src="sleeper_sharp_discovery",
        tx="T9",
        caveats=["partial_record_missing_roster"],
    )
    relation, _why = G.classify_pair(own, twin)
    assert relation == G.REL_POSSIBLE
    res = G.group_observations([own, twin])
    # Possible overlap: both observations kept, linked, and counted with bounds
    # (1..2) -- never two confirmed-unique trades.
    assert {g["dedupeState"] for g in res.groups} == {G.POSSIBLE_OVERLAP}
    assert res.volume["underlyingTradesLowerBound"] == 1
    assert res.volume["underlyingTradesUpperBound"] == 2
    assert res.volume["edgesByRelation"].get(G.REL_POSSIBLE) == 1
