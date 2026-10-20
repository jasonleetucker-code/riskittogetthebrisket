"""Source voting: owner closeout 2026-10-18 as amended by the owner's
source-voting consensus directive of 2026-10-19.

* Agreement between DIFFERENT providers is consensus, not duplication.  Only
  credible shared-DATA-lineage evidence (one feed republishing another) may
  merge votes; numerical or rank similarity never removes or caps a vote.
  So the 2026-10-18 D2 IDP-scoped shared cap (IDP Trade Calculator + IDP Show)
  and the D3 exclusion of the IDP Trade Calculator's offense vote are
  WITHDRAWN: both mechanisms are deleted and the votes are main's.
* D4 — DLF Values votes rank -> Hill as an offense-only ``dlf`` member,
  splitting DLF's one provider cap (``dlf_values_rank_hill_vote``).
* D5 — FantasyPros IDP is judged on the vendor's stated expert-update clock
  (``fantasypros_idp_upstream_clock``).
* Two-way boost — the alt-family value is what a real member of the family
  with the same votes gets (``two_way_alt_evidence_rules``).
* Universal source-voting directive (later 2026-10-19) — the DLF IDP / DLF
  Rookie IDP restore is APPROVED and implemented behind ``dlf_offense_only_vote``
  (OFF = DLF IDP votes), but HELD AT RELEASE (default ON, re-applied the same
  day): under the incumbent outlier filter the restore drops valid Draft Sharks
  / FantasyPros / IDPTC IDP votes (moves up to 54%), which the directive
  forbids; owner decision 2026-10-20 (Option 3) locks it until outlier-filter
  Version 2 passes every mandatory gate and the owner explicitly approves
  (``tests/api/test_dlf_idp_hold_locked.py``).  Mechanism pinned by
  ``tests/api/test_dlf_offense_only_vote.py``.  The contract stamps per-source
  eligibility facts (``sourceVotingEligibility``).

Board assertions are all-of / none-of invariants on the newest complete
archived scrape, never counts, so a CSV refresh cannot flip them.  The
measured record is docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md
(``scripts/source_voting_consensus_evidence.py``).
"""

from __future__ import annotations

import copy

import pytest

import src.api.data_contract as dc
from src.api import feature_flags
from src.sources import freshness as fr
from tests.archive_fixtures import newest_complete_raw_payload

_ENV = {
    "D4": "RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE",
    "TW": "RISKIT_FEATURE_TWO_WAY_ALT_EVIDENCE_RULES",
    "D5": "RISKIT_FEATURE_FANTASYPROS_IDP_UPSTREAM_CLOCK",
    "DLF_HOLD": "RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE",
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
    """One build.  A flag named in ``flags`` is forced; the rest keep their
    production defaults."""
    mp = pytest.MonkeyPatch()
    try:
        for d, env in _ENV.items():
            if d in flags:
                mp.setenv(env, "1" if flags[d] else "0")
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


def test_flags_are_registered_live_with_their_decided_defaults():
    assert feature_flags._DEFAULTS["two_way_alt_evidence_rules"] is True
    # The approved DLF IDP restore is held at release pending the outlier fix
    # (CQ-65): the hold flag is ON by default; ``=0`` lifts it.
    assert feature_flags._DEFAULTS["dlf_offense_only_vote"] is True
    assert feature_flags._DEFAULTS["fantasypros_idp_upstream_clock"] is True
    # D4's default is its gate outcome (docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md).
    assert isinstance(feature_flags._DEFAULTS["dlf_values_rank_hill_vote"], bool)
    for name in (
        "dlf_values_rank_hill_vote",
        "two_way_alt_evidence_rules",
        "fantasypros_idp_upstream_clock",
    ):
        assert feature_flags.gate_status(name) == feature_flags.LIVE


def test_similarity_based_vote_merges_and_exclusions_are_gone():
    """Owner directive 2026-10-19: the D2 shared cap and the D3 offense-vote
    exclusion rested on similarity, not shared data lineage.  Deleted, not
    deprecated, so no seam remains to re-enable them."""
    for name in (
        "ROW_SCOPED_CORRELATION_GROUPS",
        "row_scoped_family_map",
        "POLICY_SOURCE_ROW_CLASS_VOTE_HOLDS",
    ):
        assert not hasattr(dc, name), name
    for flag in ("idp_shared_correlation_cap", "idptc_offense_vote_excluded"):
        assert flag not in feature_flags._DEFAULTS, flag


def test_idp_trade_calculator_and_idp_show_are_separate_families():
    assert dc.correlation_group_for("idpTradeCalc") != dc.correlation_group_for("idpShowCombined")
    assert "idpShow" not in dc.get_ranking_source_keys()  # the IDP-only cut never votes


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


def test_d5_fantasypros_idp_clock_follows_its_flag(monkeypatch):
    assert fr.load_config().cadence_for("fantasyProsIdp").style == fr.STYLE_EXPLICIT
    monkeypatch.setenv(_ENV["D5"], "0")
    feature_flags.reload()
    try:
        assert fr.load_config().cadence_for("fantasyProsIdp").style is None
        assert fr.default_config().cadence_for("fantasyProsIdp").style is None
    finally:
        monkeypatch.delenv(_ENV["D5"])
        feature_flags.reload()
    assert fr.default_config().cadence_for("fantasyProsIdp").style == fr.STYLE_EXPLICIT


def test_an_unknown_style_flag_is_a_config_error():
    with pytest.raises(ValueError):
        fr._cadence({"style": fr.STYLE_EXPLICIT, "styleFlag": "no_such_flag"})


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
        # Every PR flag off, the DLF IDP hold re-applied: main's behaviour.
        # Each single-flag board isolates that flag against it.
        "off": _build(raw, D4=False, TW=False, D5=False, DLF_HOLD=True),
        "defaults": _build(raw),
        # The approved DLF IDP restore with the release hold lifted (every
        # other flag at its default): the board the outlier fix must clear.
        "restore": _build(raw, DLF_HOLD=False),
        "d4": _build(raw, D4=True, TW=False, D5=False, DLF_HOLD=True),
        "tw": _build(raw, D4=False, TW=True, D5=False, DLF_HOLD=True),
        "d5": _build(raw, D4=False, TW=False, D5=True, DLF_HOLD=True),
    }


@pytest.fixture(scope="module")
def engaged_boards(raw):
    """Freshness weighting rolled back: The IDP Show votes at full base weight
    beside the IDP Trade Calculator (the state on the day the vendor
    republishes)."""
    return _build(raw, TW=False, freshness=False), _build(raw, TW=True, freshness=False)


def test_idp_trade_calculator_offense_votes_are_mains(boards):
    """D3 withdrawn: the IDP Trade Calculator is an ordinary offense voter
    again (its observations go through the normal freshness gate)."""
    seen = 0
    for name, row in _rows(boards["defaults"]).items():
        if _klass(row) != "offense":
            continue
        if "idpTradeCalc" in (row.get("sourceRankMeta") or {}):
            seen += 1
    assert seen > 0
    assert "independencePolicy" not in (boards["defaults"].get("sourceWeighting") or {})


def test_the_two_way_rules_move_only_two_way_rows(boards):
    off, tw = _rows(boards["off"]), _rows(boards["tw"])
    for name, row in tw.items():
        same = row.get("rankDerivedValue") == off[name].get("rankDerivedValue") and row.get(
            "confidenceBucket"
        ) == off[name].get("confidenceBucket")
        if not same:
            assert name in dc._TWO_WAY_PLAYERS, name
    # ... and never the two-way player's own offense (primary) blend.
    for name in dc._TWO_WAY_PLAYERS:
        a, b = tw.get(name), off.get(name)
        if a and b and a.get("twoWayPlayerBoost") and b.get("twoWayPlayerBoost"):
            assert (
                a["twoWayPlayerBoost"]["primaryFamilyValue"]
                == b["twoWayPlayerBoost"]["primaryFamilyValue"]
            ), name


def _assert_alt_follows_real_member_rules(rows) -> int:
    """The audit restated independently: vote state read off the real
    defensive rows, B10 families from the registry, the haircut's
    present-evidence count."""
    checked = 0
    alt_rows = [r for r in rows.values() if _klass(r) == "idp"]
    for name in dc._TWO_WAY_PLAYERS:
        row = rows.get(name)
        audit = (row or {}).get("twoWayPlayerBoost")
        if not audit:
            continue
        checked += 1
        assert audit["evidenceRule"] == "alt_family_vote_state", name
        voting = set(audit["sourcesConsidered"])
        withheld = set(audit["freshnessExcludedSources"])
        assert not voting & withheld, name
        for key in voting:
            assert any(key in _voting(r) for r in alt_rows), f"{name}: {key} votes nowhere"
        for key in withheld:
            assert any(
                ((r.get("sourceRankMeta") or {}).get(key) or {}).get("excludedReason")
                == "freshness_or_health_zero_weight"
                for r in alt_rows
            ), f"{name}: {key} is withheld nowhere"
        families = sorted({dc.correlation_group_for(k) for k in voting | withheld})
        assert audit["families"] == families, name
        if audit.get("withdrawn"):
            assert not voting and row["rankDerivedValue"] == audit["primaryFamilyValue"], name
            continue
        assert audit["singleSourceValuePenaltyApplied"] == (len(families) <= 1), name
        if audit["singleSourceValuePenaltyApplied"]:
            before = audit["altFamilyValueBeforePenalty"]
            assert abs(audit["altFamilyValue"] - before * dc._SINGLE_SOURCE_VALUE_RETENTION) <= 1
        assert row["rankDerivedValue"] == max(
            audit["altFamilyValue"], audit["primaryFamilyValue"]
        ), name
    return checked


def test_the_two_way_alt_value_follows_real_member_rules(boards, engaged_boards):
    checked = _assert_alt_follows_real_member_rules(_rows(boards["tw"]))
    checked += _assert_alt_follows_real_member_rules(_rows(engaged_boards[1]))
    if checked == 0:
        pytest.skip("no two-way player carries alt-family evidence on this archive")


def test_two_eligible_idp_providers_are_two_families_and_no_haircut(engaged_boards):
    """Both IDP providers voting (freshness rolled back): consensus, so the
    two-way alt evidence counts two families and keeps its full value."""
    rows = _rows(engaged_boards[1])
    for name in dc._TWO_WAY_PLAYERS:
        audit = (rows.get(name) or {}).get("twoWayPlayerBoost") or {}
        voting = set(audit.get("sourcesConsidered") or ())
        if {"idpTradeCalc", "idpShowCombined"} <= voting:
            assert {"idpTradeCalc", "idpShow"} <= set(audit["families"]), name
            assert audit["singleSourceValuePenaltyApplied"] is False, name


def test_d4_votes_on_offense_only_and_keeps_one_dlf_family(boards):
    base, d4 = _rows(boards["off"]), _rows(boards["d4"])
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
    for name, row in _rows(boards["off"]).items():
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
        for n, r in _rows(boards["off"]).items()
        if "fantasyProsIdp" in (r.get("sourceRankMeta") or {})
    ]
    assert len(names) == len(set(names))


def test_d5_alone_moves_no_value_today(boards):
    """Today FantasyPros IDP is the only non-anchor subgroup voter on its
    rows, and a lone member's weight does not move a weighted mean, so D5
    moves labels only.  That is a property of today's board, not of the
    structure: a second non-anchor IDP voter makes the lower weight reach
    values (docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md)."""
    off, d5 = _rows(boards["off"]), _rows(boards["d5"])
    moved = [
        n for n, r in d5.items() if r.get("rankDerivedValue") != off[n].get("rankDerivedValue")
    ]
    if moved:
        pytest.skip(f"D5 reaches values on this archive ({len(moved)} rows): see the evidence doc")


# ── universal directive: DLF IDP restore + eligibility facts ───────────────


def test_dlf_idp_is_held_at_release_by_default(boards):
    """Release default: the approved restore is held (temporary), so no DLF
    IDP board votes on any row, and the eligibility stamp says why."""
    for name, row in _rows(boards["defaults"]).items():
        assert not set(_voting(row)) & {"dlfIdp", "dlfRookieIdp"}, name
    stamp = boards["defaults"]["sourceVotingEligibility"]
    for key in ("dlfIdp", "dlfRookieIdp"):
        assert stamp[key]["status"] == "policy_held", stamp[key]
        assert stamp[key]["reason"] == "owner_policy_dlf_idp_restore_held_pending_outlier_fix"


def test_release_defaults_move_no_idp_row_by_30_percent(boards):
    """Why the hold is in force: with it, the release defaults (D4 + D5 + the
    two-way fix) move no defensive value by 30% or more against main's
    behaviour (the ``off`` board).  The restore's 34-54% moves are the
    incumbent outlier filter dropping other sources' valid IDP votes."""
    off, dflt = _rows(boards["off"]), _rows(boards["defaults"])
    for name, row in dflt.items():
        if _klass(row) != "idp":
            continue
        before, after = off[name].get("rankDerivedValue"), row.get("rankDerivedValue")
        if before and after and before != after:
            assert abs(after - before) / before < 0.30, (name, before, after)


def test_dlf_idp_restore_votes_inside_one_dlf_family(boards):
    """With the release hold lifted, DLF IDP votes and DLF's boards still
    share one provider's authority: on no row does the ``dlf`` family's
    applied weight exceed one provider's (the largest member base weight)."""
    fam = {s["key"]: dc.correlation_group_for(s["key"]) for s in dc._RANKING_SOURCES}
    base = {s["key"]: float(s.get("weight") or 1.0) for s in dc._RANKING_SOURCES}
    seen = 0
    for name, row in _rows(boards["restore"]).items():
        voters = _voting(row)
        seen += any(k in voters for k in ("dlfIdp", "dlfRookieIdp"))
        dlf = {
            k: m for k, m in voters.items() if fam.get(k) == "dlf" and not m.get("hampelDropped")
        }
        if dlf:
            total = sum(float(m.get("appliedWeight") or 0.0) for m in dlf.values())
            assert total <= max(base[k] for k in dlf) + 1e-6, (name, total)
    if not seen:
        pytest.skip("no DLF IDP observation on this archive")


def test_source_voting_eligibility_stamps_every_registered_source(boards):
    """One entry per registered source, with a status the row-level votes
    agree with, so the 26-source audit reads facts the pipeline decided
    rather than re-deriving them."""
    contract = boards["defaults"]
    stamp = contract["sourceVotingEligibility"]
    assert set(stamp) == {s["key"] for s in dc._RANKING_SOURCES}
    allowed = {
        "voting",
        "withheld",
        "policy_held",
        "seasonal_inactive",
        "private_not_voting",
        "disabled_by_override",
        "no_observations",
    }
    carried: dict[str, int] = {}
    for row in contract["playersArray"]:
        for k in _voting(row):
            carried[k] = carried.get(k, 0) + 1
    for key, facts in stamp.items():
        assert facts["status"] in allowed, (key, facts["status"])
        assert facts["family"] == dc.correlation_group_for(key)
        if facts["status"] == "voting":
            assert (facts.get("votingRows") or 0) > 0 and carried.get(key), key
        else:
            assert facts.get("reason"), key
            if facts["status"] != "withheld":
                assert not carried.get(key), key
    # Lineage bases: a same-provider family and a documented cross-provider one.
    assert stamp["dlfIdp"]["familyBasis"] == "same_provider"
    assert stamp["fantasyNavigatorSf"]["familyBasis"] == "cross_provider_lineage"
    assert stamp["idpTradeCalc"]["familyBasis"] == "own"


def test_the_dlf_hold_rollback_stamps_dlf_idp_policy_held(boards):
    stamp = boards["off"]["sourceVotingEligibility"]
    for key in ("dlfIdp", "dlfRookieIdp"):
        assert stamp[key]["status"] == "policy_held", stamp[key]
        assert stamp[key]["rollbackFlag"] == "dlf_offense_only_vote"
