"""Tests for ``src/trade/waiver_idp_best_available.py``.

The "Best Available IDPs" waivers card combines exactly two named sources
(IDP Trade Calculator + The IDP Show) with equal weight, over free-agent
IDP players only. Every scenario the owner's spec calls out (A-K) has a
dedicated test below; no network, no live board.
"""

from __future__ import annotations

from typing import Any

from src.trade.waiver_idp_best_available import best_available_idp


def _row(
    name: str,
    position: str,
    *,
    team: str = "XX",
    asset_class: str = "idp",
    idptc: float | None = None,
    idpshow_rank: float | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "displayName": name,
        "canonicalName": name,
        "position": position,
        "team": team,
        "assetClass": asset_class,
        "canonicalSiteValues": {},
        "sourceOriginalRanks": {},
        # Canonical fields this feature must NEVER read for scoring —
        # present here to prove they're ignored (see test_ignores_canonical_fields).
        "rankDerivedValue": 9999,
        "canonicalConsensusRank": 1,
        "sourceCount": 5,
    }
    if idptc is not None:
        row["canonicalSiteValues"]["idpTradeCalc"] = idptc
    if idpshow_rank is not None:
        row["sourceOriginalRanks"]["idpShowCombined"] = idpshow_rank
    return row


def _contract(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"playersArray": list(rows)}


def _by_name(result: dict[str, Any], name: str) -> dict[str, Any]:
    for c in result["candidates"]:
        if c["name"] == name:
            return c
    raise AssertionError(f"{name} not found in candidates")


# ── A: two-source composite correctness ─────────────────────────────────


def test_two_source_composite_is_hand_computed_average():
    contract = _contract(
        _row("Alpha", "LB", idptc=9000, idpshow_rank=1),
        _row("Bravo", "DB", idptc=5000, idpshow_rank=2),
        _row("Charlie", "DL", idptc=1000, idpshow_rank=3),
    )
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])
    alpha = _by_name(result, "Alpha")
    assert alpha["tier"] == "A"
    # Population size 3: idptc rank 1 -> score 100.0; idpshow rank 1 -> score 100.0
    assert alpha["idpTradeCalc"]["score"] == 100.0
    assert alpha["idpShowCombined"]["score"] == 100.0
    assert alpha["combinedScore"] == 100.0

    bravo = _by_name(result, "Bravo")
    # idptc rank 2/3 -> 50.0; idpshow rank 2/3 -> 50.0
    assert bravo["idpTradeCalc"]["score"] == 50.0
    assert bravo["idpShowCombined"]["score"] == 50.0
    assert bravo["combinedScore"] == 50.0
    assert bravo["combinedScore"] == round(
        (bravo["idpTradeCalc"]["score"] + bravo["idpShowCombined"]["score"]) / 2.0, 1
    )


# ── B: raw scale cannot distort weighting ───────────────────────────────


def test_huge_raw_value_gap_does_not_distort_composite():
    # Alpha has a massive idpTradeCalc value lead but a mediocre IDP Show
    # rank. If (48 + 12) / 2-style raw averaging leaked in, or if percentile
    # weighting favored magnitude over rank position, Alpha would wrongly
    # dominate. It must be scored purely on RANK POSITION within each
    # source's population, not raw magnitude.
    contract = _contract(
        _row("Alpha", "LB", idptc=9999, idpshow_rank=10),  # huge value, weak rank
        _row("Bravo", "LB", idptc=9000, idpshow_rank=1),  # close value, best rank
        *[_row(f"Filler{i}", "LB", idptc=100 - i, idpshow_rank=2 + i) for i in range(8)],
    )
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])
    alpha = _by_name(result, "Alpha")
    bravo = _by_name(result, "Bravo")
    # Bravo (idptc rank 2, idpshow rank 1) must outrank Alpha (idptc rank 1,
    # idpshow rank 10) on the combined score, because idpshow rank 10 of 10
    # scores 0.0 -- averaging with a perfect idptc rank still can't let raw
    # value magnitude buy back a bottom-of-population rank on the other side.
    assert bravo["combinedScore"] > alpha["combinedScore"]


# ── C: rostered player (another team) excluded ──────────────────────────


def test_rostered_on_another_team_excluded():
    contract = _contract(
        _row("Elite", "LB", idptc=9999, idpshow_rank=1),
        _row("Filler", "DB", idptc=100, idpshow_rank=2),
    )
    result = best_available_idp(contract, sleeper_teams=[{"players": ["Elite"]}, {"players": []}])
    names = {c["name"] for c in result["candidates"]}
    assert "Elite" not in names
    assert "Filler" in names


# ── D: player on the user's own roster excluded ─────────────────────────


def test_rostered_on_own_team_excluded():
    contract = _contract(
        _row("MyGuy", "DL", idptc=9999, idpshow_rank=1),
        _row("Filler", "DB", idptc=100, idpshow_rank=2),
    )
    # "own" team is just one entry among sleeper_teams -- rostered_name_set
    # spans ALL teams, so this proves it isn't "every team except mine".
    result = best_available_idp(contract, sleeper_teams=[{"players": ["MyGuy"]}])
    names = {c["name"] for c in result["candidates"]}
    assert "MyGuy" not in names


# ── E: unknown ownership is NOT available ───────────────────────────────


def test_empty_sleeper_teams_means_ownership_unresolved():
    contract = _contract(_row("Anybody", "LB", idptc=9999, idpshow_rank=1))
    result = best_available_idp(contract, sleeper_teams=[])
    assert result["ownershipResolved"] is False
    assert result["candidates"] == []
    assert result["degraded"]["ownershipUnresolved"] is True


def test_none_sleeper_teams_means_ownership_unresolved():
    contract = _contract(_row("Anybody", "LB", idptc=9999, idpshow_rank=1))
    result = best_available_idp(contract, sleeper_teams=None)
    assert result["ownershipResolved"] is False
    assert result["candidates"] == []


# ── F: missing source is not converted to zero ──────────────────────────


def test_single_source_player_never_zero_filled():
    contract = _contract(
        _row("OnlyIdptc", "LB", idptc=9999),
        _row("OnlyIdpShow", "DB", idpshow_rank=1),
    )
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])

    only_idptc = _by_name(result, "OnlyIdptc")
    assert only_idptc["tier"] == "B"
    assert only_idptc["sourcesUsed"] == 1
    assert only_idptc["idpShowCombined"]["score"] is None
    assert only_idptc["combinedScore"] == only_idptc["idpTradeCalc"]["score"]

    only_idpshow = _by_name(result, "OnlyIdpShow")
    assert only_idpshow["tier"] == "B"
    assert only_idpshow["idpTradeCalc"]["score"] is None
    assert only_idpshow["combinedScore"] == only_idpshow["idpShowCombined"]["score"]


# ── G: duplicate identity collapses to one candidate ────────────────────


def test_one_row_with_both_source_keys_is_one_candidate():
    # Identity resolution already happened upstream; this is a structural
    # regression guard that a single row carrying both source fields never
    # produces two candidate entries.
    contract = _contract(_row("BothSources", "LB", idptc=9000, idpshow_rank=1))
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])
    matches = [c for c in result["candidates"] if c["name"] == "BothSources"]
    assert len(matches) == 1
    assert matches[0]["tier"] == "A"


# ── H: deterministic sort / tiebreakers ──────────────────────────────────


def test_tiebreak_order_is_deterministic():
    # Two Tier-A players tie on combined score; the better worst-source
    # score wins, then better idptc score, then name.
    contract = _contract(
        # Population of 4 for both sources.
        _row(
            "Zebra", "LB", idptc=9999, idpshow_rank=4
        ),  # idptc rank1->100, idpshow rank4->0 => combined 50
        _row(
            "Apple", "LB", idptc=1, idpshow_rank=1
        ),  # idptc rank4->0, idpshow rank1->100 => combined 50
        _row("Filler1", "LB", idptc=9000, idpshow_rank=2),
        _row("Filler2", "LB", idptc=8000, idpshow_rank=3),
    )
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])
    zebra = _by_name(result, "Zebra")
    apple = _by_name(result, "Apple")
    assert zebra["combinedScore"] == apple["combinedScore"] == 50.0
    # Both have worst-source score 0.0 (tied) -> falls to idptc score:
    # Zebra idptc score 100.0 > Apple idptc score 0.0 -> Zebra ranks first.
    zebra_idx = next(i for i, c in enumerate(result["candidates"]) if c["name"] == "Zebra")
    apple_idx = next(i for i, c in enumerate(result["candidates"]) if c["name"] == "Apple")
    assert zebra_idx < apple_idx


def test_sort_is_stable_across_repeated_calls():
    contract = _contract(
        _row("A", "LB", idptc=100, idpshow_rank=1),
        _row("B", "DB", idptc=100, idpshow_rank=1),
        _row("C", "DL", idptc=50, idpshow_rank=2),
    )
    teams = [{"players": []}]
    first = best_available_idp(contract, sleeper_teams=teams)
    second = best_available_idp(contract, sleeper_teams=teams)
    assert [c["name"] for c in first["candidates"]] == [c["name"] for c in second["candidates"]]


# ── I: Tier A fills the top 20 before Tier B (tier-priority rule) ───────


def test_tier_a_candidates_precede_tier_b_when_enough_exist():
    rows = []
    # 25 Tier-A candidates with modest scores.
    for i in range(25):
        rows.append(_row(f"TwoSource{i}", "LB", idptc=100 - i, idpshow_rank=i + 1))
    # One Tier-B candidate with a "perfect" single-source score that would
    # beat every Tier-A combined score under flat score-only sorting.
    rows.append(_row("OneSourceStar", "DB", idptc=999999))
    contract = _contract(*rows)
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])
    top_20 = result["candidates"][:20]
    assert all(c["tier"] == "A" for c in top_20)
    names = {c["name"] for c in top_20}
    assert "OneSourceStar" not in names


def test_tier_b_fills_remaining_slots_when_fewer_than_20_tier_a():
    rows = []
    for i in range(5):
        rows.append(_row(f"TwoSource{i}", "LB", idptc=100 - i, idpshow_rank=i + 1))
    for i in range(5):
        rows.append(_row(f"OneSourceOnly{i}", "DB", idptc=50 - i))
    contract = _contract(*rows)
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])
    assert result["availableCount"] == 10
    top_5 = result["candidates"][:5]
    assert all(c["tier"] == "A" for c in top_5)
    rest = result["candidates"][5:]
    assert all(c["tier"] == "B" for c in rest)


# ── J: fewer than 20 displays truthfully ─────────────────────────────────


def test_fewer_than_20_reports_true_count_with_no_padding():
    contract = _contract(
        _row("Only1", "LB", idptc=9000, idpshow_rank=1),
        _row("Only2", "DB", idptc=100, idpshow_rank=2),
    )
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])
    assert result["availableCount"] == 2
    assert len(result["candidates"]) == 2


# ── K: degraded state — missing source is surfaced, never faked ────────


def test_missing_source_reports_zero_population_and_no_fabricated_scores():
    contract = _contract(
        _row("IdptcOnly1", "LB", idptc=9000),
        _row("IdptcOnly2", "DB", idptc=100),
    )
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])
    assert result["sources"]["idpShowCombined"]["populationSize"] == 0
    assert "idpShowCombined" in result["degraded"]["missingSources"]
    assert "idpTradeCalc" not in result["degraded"]["missingSources"]
    for c in result["candidates"]:
        assert c["idpShowCombined"]["score"] is None
        assert c["tier"] == "B"


# ── Non-IDP / pick rows never enter the candidate pool ──────────────────


def test_offense_and_pick_rows_excluded():
    contract = _contract(
        _row("QBGuy", "QB", idptc=9999, idpshow_rank=1),
        _row("SomePick", "PICK", asset_class="pick", idptc=9999, idpshow_rank=1),
        _row("RealIdp", "LB", idptc=100, idpshow_rank=2),
    )
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])
    names = {c["name"] for c in result["candidates"]}
    assert names == {"RealIdp"}


def test_ignores_canonical_fields_entirely():
    # Every row in this suite carries a strong rankDerivedValue /
    # canonicalConsensusRank / sourceCount (see _row's defaults) to prove
    # they are structurally never read. A row with NEITHER named source but
    # a strong canonical value must never appear.
    contract = _contract(_row("CanonicalOnly", "LB"))  # no idptc, no idpshow
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])
    assert result["candidates"] == []


# ── Filter-then-slice safety (frontend DL/LB/DB filter correctness) ─────


def test_position_filter_must_apply_to_full_list_not_pre_sliced_top_20():
    """Guards the frontend's filter-then-slice contract.

    Each candidate's score reflects its rank across the WHOLE cross-position
    IDP population (per the "entire relevant IDP ranking population"
    requirement), so a legitimate top-position player can sit outside the
    top 20 overall. The backend must return the full candidate list so a
    client-side position filter can find them; if the backend only returned
    a pre-sliced top 20, filtering to one position afterward could wrongly
    lose players who rank, say, 21st-30th overall but are top-10 at their
    position.
    """
    rows = []
    # 25 DB players occupying every top overall slot.
    for i in range(25):
        rows.append(_row(f"DB{i}", "DB", idptc=1000 - i, idpshow_rank=i + 1))
    # 5 LB players who rank below all 25 DBs overall, but are the only LBs.
    for i in range(5):
        rows.append(_row(f"LB{i}", "LB", idptc=100 - i, idpshow_rank=100 + i))
    contract = _contract(*rows)
    result = best_available_idp(contract, sleeper_teams=[{"players": []}])

    # None of the LBs made the naive "top 20 overall" cut.
    naive_top_20_names = {c["name"] for c in result["candidates"][:20]}
    assert not any(name.startswith("LB") for name in naive_top_20_names)

    # But filtering the FULL list to LB and taking the top N finds them all.
    lb_filtered = [c for c in result["candidates"] if c["position"] == "LB"][:5]
    assert {c["name"] for c in lb_filtered} == {f"LB{i}" for i in range(5)}
    # And they are still the true top 5 LBs by combined score, descending.
    scores = [c["combinedScore"] for c in lb_filtered]
    assert scores == sorted(scores, reverse=True)
