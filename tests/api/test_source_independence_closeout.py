"""Owner closeout 2026-10-18, Decisions 2-5: source independence.

* D2 — IDP-scoped shared correlation cap (``idp_shared_correlation_cap``):
  on a DEFENSIVE row where both the IDP Trade Calculator and The IDP Show
  combined board vote, they are one lineage for the family cap and the B11
  count.  Never offense or picks; never makes the IDP-only Show board a voter.
* D3 — the IDP Trade Calculator's offense vote is excluded
  (``idptc_offense_vote_excluded``); its IDP and pick votes are untouched.
* D4 — DLF Values votes rank -> Hill as an offense-only ``dlf`` member under
  DLF's one provider cap (``dlf_values_rank_hill_vote``).
* D5 — FantasyPros IDP is judged on the vendor's stated expert-update clock.

Board assertions are all-of / none-of invariants on the newest complete
archived scrape, never counts, so a CSV refresh cannot flip them.  The
measured record is docs/sources/IDP_SOURCE_INDEPENDENCE_CLOSEOUT_2026-10-18.md
(``scripts/source_independence_closeout.py``).
"""

from __future__ import annotations

import copy

import pytest

import src.api.data_contract as dc
from src.api import feature_flags
from src.sources import freshness as fr
from tests.archive_fixtures import newest_complete_raw_payload

_ENV = {
    "D2": "RISKIT_FEATURE_IDP_SHARED_CORRELATION_CAP",
    "D3": "RISKIT_FEATURE_IDPTC_OFFENSE_VOTE_EXCLUDED",
    "D4": "RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE",
}
_OFFENSE = {"QB", "RB", "WR", "TE"}
_IDP = {"DL", "LB", "DB"}


def _klass(row) -> str:
    pos = str(row.get("position") or "").upper()
    if row.get("assetClass") == "pick" or pos == "PICK":
        return "pick"
    return "idp" if pos in _IDP else ("offense" if pos in _OFFENSE else "other")


def _voting(row) -> dict:
    out = {}
    for k, m in (row.get("sourceRankMeta") or {}).items():
        if not isinstance(m, dict) or m.get("excludedReason"):
            continue
        w = m.get("preFamilyWeight", m.get("appliedWeight"))
        if isinstance(w, (int, float)) and w > 0:
            out[k] = m
    return out


def _rows(contract) -> dict[str, dict]:
    return {r["displayName"]: r for r in contract["playersArray"] if r.get("displayName")}


def _build(raw, **flags) -> dict:
    mp = pytest.MonkeyPatch()
    try:
        for d, env in _ENV.items():
            mp.setenv(env, "1" if flags.get(d, False) else "0")
        if "freshness" in flags:
            mp.setenv(
                "RISKIT_FEATURE_SOURCE_FRESHNESS_WEIGHTING", "1" if flags["freshness"] else "0"
            )
        feature_flags.reload()
        return dc.build_api_data_contract(copy.deepcopy(raw))
    finally:
        mp.undo()
        feature_flags.reload()


@pytest.fixture(scope="module")
def raw():
    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape available")
    return payload


# ── declarations ───────────────────────────────────────────────────────────


def test_flags_are_registered_live_with_the_decided_defaults():
    for name in (
        "idp_shared_correlation_cap",
        "idptc_offense_vote_excluded",
        "dlf_values_rank_hill_vote",
    ):
        assert feature_flags._DEFAULTS[name] is True
    for name in (
        "idp_shared_correlation_cap",
        "idptc_offense_vote_excluded",
        "dlf_values_rank_hill_vote",
    ):
        assert feature_flags.gate_status(name) == feature_flags.LIVE


def test_d2_rule_is_idp_only_and_never_registers_the_idp_only_show_board():
    (rule,) = dc.ROW_SCOPED_CORRELATION_GROUPS
    assert rule["assetClass"] == "idp"
    assert set(rule["members"]) == {"idpTradeCalc", "idpShowCombined"}
    assert rule["group"] == dc.correlation_group_for("idpShowCombined")
    assert "idpShow" not in dc.get_ranking_source_keys()


def test_row_scoped_family_map_engages_only_when_every_member_votes():
    base = {"idpTradeCalc": "idpTradeCalc", "idpShowCombined": "idpShow", "dlfSf": "dlf"}
    rules = {"idp_show_lineage_on_idp_rows"}
    m, engaged = dc.row_scoped_family_map(
        base, asset_class="idp", voting={"idpTradeCalc": 0.8}, enabled_rules=rules
    )
    assert m is base and engaged == ()
    m, engaged = dc.row_scoped_family_map(
        base,
        asset_class="offense",
        voting={"idpTradeCalc": 0.8, "idpShowCombined": 0.7},
        enabled_rules=rules,
    )
    assert m is base and engaged == ()
    m, engaged = dc.row_scoped_family_map(
        base,
        asset_class="idp",
        voting={"idpTradeCalc": 0.8, "idpShowCombined": 0.7},
        enabled_rules=set(),
    )
    assert m is base and engaged == ()
    m, engaged = dc.row_scoped_family_map(
        base,
        asset_class="idp",
        voting={"idpTradeCalc": 0.8, "idpShowCombined": 0.7},
        enabled_rules=rules,
    )
    assert engaged == ("idp_show_lineage_on_idp_rows",)
    assert m["idpTradeCalc"] == m["idpShowCombined"] == "idpShow"
    assert m["dlfSf"] == "dlf" and base["idpTradeCalc"] == "idpTradeCalc"


def test_family_cap_owner_caps_a_row_scoped_lineage_at_one_provider():
    weights = {"idpTradeCalc": 0.9, "idpShowCombined": 0.6, "draftSharksIdp": 1.0}
    plain, _ = dc.cap_family_weights(weights)
    assert plain == weights  # two families: nothing capped
    lineage = {"idpTradeCalc": "idpShow", "idpShowCombined": "idpShow"}
    capped, factor = dc.cap_family_weights(
        weights, family_of=lambda k: lineage.get(k) or dc.correlation_group_for(k)
    )
    assert capped["idpTradeCalc"] + capped["idpShowCombined"] == pytest.approx(1.0)
    assert capped["idpTradeCalc"] / capped["idpShowCombined"] == pytest.approx(1.5)
    assert capped["draftSharksIdp"] == 1.0 and factor["draftSharksIdp"] == 1.0


def test_d3_hold_is_offense_rows_only():
    hold = dc.POLICY_SOURCE_ROW_CLASS_VOTE_HOLDS["idpTradeCalc"]
    assert hold["assetClass"] == "offense"
    assert hold["flag"] == "idptc_offense_vote_excluded"
    assert set(dc.POLICY_SOURCE_ROW_CLASS_VOTE_HOLDS) == {"idpTradeCalc"}


def test_d4_dlf_values_is_an_offense_only_dlf_member_voting_rank():
    src = next(s for s in dc._RANKING_SOURCES if s["key"] == "dlfValuesSfTep")
    assert src["correlation_group"] == "dlf"
    assert src["scope"] == dc.SOURCE_SCOPE_OVERALL_OFFENSE and not src.get("extra_scopes")
    assert src["is_rank_signal"] is True
    assert "dlfValuesSfTep" not in dc._VALUE_BASED_SOURCES  # raw / max is rejected
    cfg = dc._SOURCE_CSV_PATHS["dlfValuesSfTep"]
    assert cfg["signal"] == "rank" and cfg["rank_from"] == "value_order"
    hold = dc.POLICY_SOURCE_VOTE_HOLDS["dlfValuesSfTep"]
    assert hold["flag"] == "dlf_values_rank_hill_vote" and hold["holdWhileFlag"] == "off"


def test_d4_value_order_ranks_share_ties_and_skip_non_positive(tmp_path):
    path = tmp_path / "dlfValuesSfTep.csv"
    path.write_text(
        "name,pos,team,value\nA,QB,X,900.5\nB,WR,X,700\nC,RB,X,700\nD,TE,X,0\nE,WR,X,12.25\n",
        encoding="utf-8",
    )
    dc._SOURCE_CSV_PARSE_CACHE.pop(str(path), None)
    lookup, err = dc._parse_source_csv_cached(path, "dlfValuesSfTep", "rank", "x.csv")
    assert err is None
    ranks = {e[0]: e[2] for entries in lookup.values() for e in entries}
    natives = {e[0]: e[3] for entries in lookup.values() for e in entries}
    assert ranks == {"A": 1.0, "B": 2.0, "C": 2.0, "E": 4.0}
    assert natives["A"] == 900.5  # the published number stays visible
    assert "D" not in ranks  # a non-positive value is missing, never a rank


def test_dataset_recorder_reads_the_value_column_for_value_order_boards():
    from scripts.record_source_datasets import recorded_sources

    got = {k: sig for k, _p, sig in recorded_sources()}
    assert got["dlfValuesSfTep"] == "value"
    assert got["dlfSf"] == "rank"


def test_d5_fantasypros_idp_uses_the_vendor_stated_clock():
    cfg = fr.load_config()
    assert cfg.cadence_for("fantasyProsIdp").style == fr.STYLE_EXPLICIT


def test_d5_rescraping_unchanged_content_cannot_refresh_the_age():
    """A later broad change (a re-scrape, a revert, a parser re-keying) never
    makes the clock fresher than the vendor's own expert-update time."""
    cfg = fr.load_config()
    as_of = fr.parse_iso("2026-10-18T12:00:00Z")
    state = {
        "changeHistory": [
            {"at": "2026-09-04T05:00:00Z", "broad": True},
            {"at": "2026-10-18T06:00:00Z", "broad": True},
        ],
        "lastAnyMeaningfulChangeAt": "2026-10-18T06:00:00Z",
        "lastBroadDatasetChangeAt": "2026-10-18T06:00:00Z",
    }
    sub = fr.assess_subset(
        "fantasyProsIdp",
        "players",
        state,
        as_of=as_of,
        cfg=cfg,
        upstream={"publishedAt": "2026-09-04T02:34:24Z"},
    )
    assert sub.clock == "upstreamPublishedAt"
    assert sub.age_hours > 1000
    assert sub.freshness < 0.5  # stale is reported stale ...
    no_upstream = fr.assess_subset("fantasyProsIdp", "players", state, as_of=as_of, cfg=cfg)
    assert no_upstream.clock == "lastBroadDatasetChangeAt"  # ... and absence is not invented


# ── the real board ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def boards(raw):
    return {
        "base": _build(raw),
        "d2": _build(raw, D2=True),
        "d3": _build(raw, D3=True),
        "d4": _build(raw, D4=True),
    }


_LEGACY_TWO_WAY_AUDIT = {
    "applied",
    "altFamily",
    "altFamilyValue",
    "primaryFamilyValue",
    "sourcesConsidered",
}
#: Independent restatement of the D2 rule (deliberately NOT read from
#: ``dc.ROW_SCOPED_CORRELATION_GROUPS``), as in
#: ``scripts/source_independence_closeout.py``.
_D2_MEMBERS = ("idpTradeCalc", "idpShowCombined")
_D2_GROUP = "idpShow"


def _two_way_evidence_rule_acted(row) -> bool:
    """Under D2 a two-way player's alt (defensive) value is held to the
    row-level evidence rules (``_apply_two_way_player_boost``).  It can differ
    from the D2-off value only through one of them, each stamped on the audit:
    a withheld copy left the alt value, the lineage rule merged the alt
    evidence, or one lineage kept the single-source retention."""
    audit = row.get("twoWayPlayerBoost") or {}
    return bool(
        audit.get("freshnessExcludedSources")
        or audit.get("sharedLineageCaps")
        or audit.get("singleSourceValuePenaltyApplied")
    )


def test_d2_preserves_every_value_where_the_show_does_not_vote(boards):
    base, d2 = _rows(boards["base"]), _rows(boards["d2"])
    for name, row in base.items():
        voters = _voting(row)
        if _klass(row) == "idp" and {"idpTradeCalc", "idpShowCombined"} <= set(voters):
            continue
        if name in dc._TWO_WAY_PLAYERS and _two_way_evidence_rule_acted(d2[name]):
            # Pinned positively by the next test.
            continue
        assert d2[name].get("rankDerivedValue") == row.get("rankDerivedValue"), name
        assert d2[name].get("confidenceBucket") == row.get("confidenceBucket"), name
        assert not d2[name].get("sharedLineageCaps"), name


def _assert_two_way_follows_row_level_evidence(base_rows, d2_rows) -> int:
    """The alt value under D2, checked against an INDEPENDENT restatement of
    the rules (vote state read off the real defensive rows, the D2 merge,
    the haircut's present-evidence count).  Returns rows checked."""
    checked = 0
    for name in dc._TWO_WAY_PLAYERS:
        off, on = base_rows.get(name), d2_rows.get(name)
        if not off or not on or not on.get("twoWayPlayerBoost"):
            continue
        checked += 1
        legacy, audit = off["twoWayPlayerBoost"], on["twoWayPlayerBoost"]
        # Rollback: the D2-off boost is the pre-closeout boost, key for key.
        assert set(legacy) == _LEGACY_TWO_WAY_AUDIT, name
        voting, withheld = set(audit["sourcesConsidered"]), set(audit["freshnessExcludedSources"])
        assert not voting & withheld, name
        # Only observations the pre-closeout boost could read, nothing new:
        # voters it priced, withheld copies the row actually carries.
        assert voting <= set(legacy["sourcesConsidered"]), name
        for key in withheld:
            assert float((on.get("canonicalSiteValues") or {}).get(key) or 0) > 0, name
        alt_rows = [r for r in d2_rows.values() if _klass(r) == "idp"]
        for key in voting:
            assert any(key in _voting(r) for r in alt_rows), f"{name}: {key} votes nowhere"
        for key in withheld:
            assert any(
                ((r.get("sourceRankMeta") or {}).get(key) or {}).get("excludedReason")
                == "freshness_or_health_zero_weight"
                for r in alt_rows
            ), f"{name}: {key} is withheld nowhere"
        engaged = set(_D2_MEMBERS) <= voting
        assert bool(audit["sharedLineageCaps"]) == engaged, name
        lineages = {
            (_D2_GROUP if engaged and k in _D2_MEMBERS else dc.correlation_group_for(k))
            for k in voting | withheld
        }
        assert audit["lineages"] == sorted(lineages), name
        assert audit["singleSourceValuePenaltyApplied"] == (len(lineages) <= 1), name
        if audit["singleSourceValuePenaltyApplied"]:
            before = audit["altFamilyValueBeforePenalty"]
            assert abs(audit["altFamilyValue"] - before * dc._SINGLE_SOURCE_VALUE_RETENTION) <= 1
        expected = max(audit["altFamilyValue"], audit["primaryFamilyValue"])
        assert on["rankDerivedValue"] == expected, name
    return checked


def test_d2_two_way_alt_value_follows_the_row_level_evidence_rules(boards, engaged_boards):
    """Independent review of the closeout: the boost read raw
    ``canonicalSiteValues``, so the two-way alt value kept a copy that did not
    vote and escaped the haircut D2's merged lineage gives every real defender
    resting on it.  Checked on the real board (where The IDP Show may be
    withheld) and with freshness rolled back (where both copies vote)."""
    checked = _assert_two_way_follows_row_level_evidence(_rows(boards["base"]), _rows(boards["d2"]))
    checked += _assert_two_way_follows_row_level_evidence(*(_rows(c) for c in engaged_boards))
    if checked == 0:
        pytest.skip("no two-way player carries alt-family evidence on this archive")


@pytest.fixture(scope="module")
def engaged_boards(raw):
    """With freshness weighting rolled back The IDP Show votes at full base
    weight, so the rule engages on real rows (the state it would be in the
    day the vendor republishes)."""
    return _build(raw, freshness=False), _build(raw, D2=True, freshness=False)


def test_d2_engages_exactly_where_both_vote_on_defensive_rows(engaged_boards):
    off, on = (_rows(c) for c in engaged_boards)
    engaged = 0
    for name, row in on.items():
        both = {"idpTradeCalc", "idpShowCombined"} <= set(_voting(off[name]))
        expect = _klass(row) == "idp" and both
        assert bool(row.get("sharedLineageCaps")) == expect, name
        if not expect:
            continue
        engaged += 1
        kept = {k: m for k, m in _voting(row).items() if not m.get("hampelDropped")}
        lineage = sum(
            float(kept[k]["appliedWeight"])
            for k in ("idpTradeCalc", "idpShowCombined")
            if k in kept
        )
        assert lineage <= 1.0 + 1e-3, name
        if "idpTradeCalc" in kept and "idpShowCombined" in kept:
            assert row["independentSourceCount"] == off[name]["independentSourceCount"] - 1
    if engaged == 0:
        pytest.skip("The IDP Show casts no vote on this archive even at full weight")


def test_d2_one_lineage_rows_take_the_single_source_haircut(engaged_boards):
    """Independent review of the closeout: the haircut counted families on the
    registry map, so a defensive row priced only by the IDP Trade Calculator
    and its correlated IDP Show copy escaped the 30% haircut that the same row
    takes with the calculator alone.  D2 merges them into one lineage."""
    off, on = (_rows(c) for c in engaged_boards)
    checked = 0
    for name, row in on.items():
        if not row.get("sharedLineageCaps") or _klass(row) != "idp":
            continue
        kept = {k for k, m in _voting(row).items() if not m.get("hampelDropped")}
        if not kept or not kept <= {"idpTradeCalc", "idpShowCombined"}:
            continue
        if not row.get("rankDerivedValue"):
            continue
        checked += 1
        assert row.get("singleSourceValuePenaltyApplied"), name
        assert not off[name].get("singleSourceValuePenaltyApplied"), name
        assert row["rankDerivedValue"] < off[name]["rankDerivedValue"], name
    if checked == 0:
        pytest.skip("no defensive row rests solely on the merged lineage on this archive")


def test_d2_never_reprices_an_offense_row_except_two_way_players(engaged_boards):
    off, on = (_rows(c) for c in engaged_boards)
    for name, row in on.items():
        if _klass(row) != "offense":
            continue
        if row.get("rankDerivedValue") != off[name].get("rankDerivedValue"):
            assert name in dc._TWO_WAY_PLAYERS, name


def test_d3_removes_only_the_offense_vote(boards):
    base, d3 = _rows(boards["base"]), _rows(boards["d3"])
    keys = ("rawRank", "valueContribution", "appliedWeight")
    for name, row in d3.items():
        meta = (row.get("sourceRankMeta") or {}).get("idpTradeCalc")
        before = (base[name].get("sourceRankMeta") or {}).get("idpTradeCalc")
        if _klass(row) == "offense":
            assert meta is None, name
            assert "idpTradeCalc" not in (row.get("effectiveSourceRanks") or {}), name
            if base[name].get("rankDerivedValue"):
                assert row.get("rankDerivedValue"), f"{name}: exclusion must not unprice"
        elif before or meta:
            assert before and meta and all(before.get(k) == meta.get(k) for k in keys), name
    held = boards["d3"]["sourceWeighting"]["independencePolicy"]["rowClassVoteHolds"]
    assert held["idpTradeCalc"]["rowsHeld"] == sum(
        1
        for r in base.values()
        if _klass(r) == "offense" and "idpTradeCalc" in (r.get("sourceRankMeta") or {})
    )


def test_d4_votes_on_offense_only_and_keeps_one_dlf_family(boards):
    base, d4 = _rows(boards["base"]), _rows(boards["d4"])
    voted = False
    for name, row in d4.items():
        meta = (row.get("sourceRankMeta") or {}).get("dlfValuesSfTep")
        if meta:
            voted = True
            assert _klass(row) == "offense", name
        dlf = sum(
            float(m.get("appliedWeight") or 0.0)
            for k, m in _voting(row).items()
            if dc.correlation_group_for(k) == "dlf" and not m.get("hampelDropped")
        )
        assert dlf <= 1.0 + 1e-3, name
        if _klass(row) == "idp":
            assert row.get("rankDerivedValue") == base[name].get("rankDerivedValue"), name
    assert voted
    for name, row in _rows(boards["base"]).items():
        assert "dlfValuesSfTep" not in (row.get("effectiveSourceRanks") or {}), name


def test_d4_flag_off_holds_dlf_values_through_the_policy_gate(monkeypatch):
    monkeypatch.setenv(_ENV["D4"], "0")
    feature_flags.reload()
    try:
        state = dc._source_vote_state()["dlfValuesSfTep"]
        assert state["voteState"] == dc.VOTE_STATE_HELD and state["votes"] is False
        assert state["heldFromVote"] == "owner_policy_dlf_values_release_gated"
    finally:
        monkeypatch.delenv(_ENV["D4"])
        feature_flags.reload()
    assert "dlfValuesSfTep" not in dc._source_vote_state()  # released: default state


def test_d5_duplicate_csv_identities_cast_one_vote(boards):
    """FantasyPros IDP lists dual-eligible edge rushers on two positional
    pages; the board ranks over its own rows (one per player), so a duplicate
    CSV entry can never be a second vote or push other players down."""
    names = [
        n
        for n, r in _rows(boards["base"]).items()
        if "fantasyProsIdp" in (r.get("sourceRankMeta") or {})
    ]
    assert len(names) == len(set(names))
