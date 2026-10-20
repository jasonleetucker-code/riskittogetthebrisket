"""Outlier-integrity-v2 Layer A — identity evidence (pure, synthetic).

Preregistration ``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` §3.1 and
§9 property 9 (wrong-player matches: A1, A2, A3, A4, A5, homonym).  Every case
here is synthetic: Stage 1 may not read a held-out or regression board.
"""

from __future__ import annotations

import itertools

from src.identity import resolution as r
from src.utils.name_clean import canonical_position_group


def _key(name: str) -> str:
    from src.api.data_contract import _canonical_match_key

    return _canonical_match_key(name)


def _row(**kw) -> r.RowIdentityEvidence:
    base = dict(player_id="100", name="Pat Player", position="WR", team="BUF", age=25.0)
    base.update(kw)
    return r.RowIdentityEvidence(**base)


def _ev(**kw) -> r.SourceEntryEvidence:
    base = dict(raw_name="Pat Player")
    base.update(kw)
    return r.SourceEntryEvidence(**base)


def _assess(row, cands, *, chosen=0, via="name_group", **kw) -> r.IdentityVerdict:
    return r.assess_identity_evidence(
        row=row,
        candidates=list(cands),
        chosen=chosen,
        via=via,
        canonical_match_key=_key,
        position_group=canonical_position_group,
        **kw,
    )


# ── team evidence ──────────────────────────────────────────────────────


def test_team_evidence_folds_provider_spellings_and_treats_fa_as_no_evidence():
    assert r.team_evidence("JAC") == "JAX"
    assert r.team_evidence("jax") == "JAX"
    assert r.team_evidence("GBP") == "GB"
    assert r.team_evidence("WSH") == "WAS"
    assert r.team_evidence("LA") == "LAR"
    for none in ("FA", "", None, "XYZ", "Bills"):
        assert r.team_evidence(none) is None


# ── A1 / A2 ────────────────────────────────────────────────────────────


def test_a1_a_sleeper_id_that_names_another_board_player_is_contradicted():
    owners = {"100": "Pat Player", "200": "Other Guy"}
    v = _assess(_row(), [_ev(sleeper_id="200")], sleeper_id_owner=owners.get)
    assert v.verdict == r.ID_CONTRADICTED
    assert v.reason == r.ID_REASON_SLEEPER_ID
    assert v.refused


def test_a1_an_unresolvable_sleeper_id_is_no_evidence_not_a_contradiction():
    """Measured shape: a vendor id column carrying ids that resolve to nobody
    must not refuse the correctly named player's vote."""
    owners = {"100": "Pat Player"}
    v = _assess(
        _row(), [_ev(sleeper_id="99999", team="BUF", position="WR")], sleeper_id_owner=owners.get
    )
    assert v.verdict == r.ID_VERIFIED  # name + position group + team still agree
    assert not v.refused


def test_a1_without_an_owner_lookup_any_mismatch_contradicts():
    v = _assess(_row(), [_ev(sleeper_id="200")])
    assert v.verdict == r.ID_CONTRADICTED


def test_a1_vendor_id_resolving_to_another_player_is_contradicted():
    v = _assess(_row(), [_ev(vendor_id="k1")], vendor_id_resolver={"k1": "200"}.get)
    assert v.reason == r.ID_REASON_VENDOR_ID
    # No resolver (the board path today): the vendor id cannot decide.
    assert _assess(_row(), [_ev(vendor_id="k1")]).verdict == r.ID_NAME_ONLY


def test_a2_non_name_rung_attaching_another_players_entry_is_contradicted():
    v = _assess(_row(player_id=None), [_ev(raw_name="Someone Else")], via="custom_rung")
    assert v.reason == r.ID_REASON_JOIN_INCONSISTENT
    # On the Sleeper-id rung the id vouches for a differently spelled name.
    ok = _assess(_row(), [_ev(raw_name="Patrick Player", sleeper_id="100")], via="sleeper_id")
    assert ok.verdict == r.ID_VERIFIED


# ── A3, rookie class, age ──────────────────────────────────────────────


def test_a3_an_idp_entry_on_an_offense_row_is_a_wrong_player():
    v = _assess(_row(position="WR"), [_ev(position="LB")])
    assert v.reason == r.ID_REASON_POSITION_GROUP


def test_a3_dl_lb_edge_drift_stays_inside_the_idp_group():
    for pub in ("LB", "EDGE", "DE", "DL"):
        v = _assess(_row(position="DL", team=None), [_ev(position=pub)])
        assert not v.refused, pub


def test_a3_a_registered_two_way_player_may_carry_its_alternate_group():
    row = _row(position="WR", alt_groups=frozenset({"IDP"}))
    assert not _assess(row, [_ev(position="CB")]).refused


def test_a3_unknown_or_missing_published_position_is_no_evidence():
    for pub in (None, "", "??"):
        assert not _assess(_row(), [_ev(position=pub)]).refused


def test_rookie_board_entry_on_a_veteran_row_is_contradicted():
    vet = _row(years_exp=4, rookie=False)
    assert _assess(vet, [_ev()], rookie_board=True).reason == r.ID_REASON_ROOKIE_CLASS
    assert not _assess(_row(years_exp=0, rookie=True), [_ev()], rookie_board=True).refused
    # Unknown experience is no evidence.
    assert not _assess(_row(years_exp=None), [_ev()], rookie_board=True).refused
    # Not a rookie board: no rookie-class check at all.
    assert not _assess(vet, [_ev()]).refused


def test_published_age_beyond_tau_is_contradicted_and_missing_age_is_not():
    assert _assess(_row(age=26.0), [_ev(age=22.3)], tau_age=2.0).reason == r.ID_REASON_AGE
    assert not _assess(_row(age=26.0), [_ev(age=24.5)], tau_age=2.0).refused
    assert not _assess(_row(age=None), [_ev(age=22.3)], tau_age=2.0).refused
    assert not _assess(_row(age=26.0), [_ev(age=22.3)], tau_age=None).refused


# ── A4 in-source duplicates ────────────────────────────────────────────


def _murphys():
    return [
        _ev(raw_name="Byron Murphy II", position="DT", team="SEA", value=4000.0, rank=40.0),
        _ev(raw_name="Byron Murphy Jr.", position="CB", team="MIN", value=6000.0, rank=20.0),
    ]


def test_a4_two_people_on_one_key_are_split_by_their_own_position():
    row_dl = _row(player_id=None, name="Byron Murphy", position="DL", team=None)
    v = _assess(row_dl, _murphys(), chosen=1)  # the loader kept the higher value (Jr.)
    assert v.verdict != r.ID_UNRESOLVED
    assert v.selected == 0  # the DT entry votes for the DL row, with ITS value
    row_db = _row(player_id=None, name="Byron Murphy", position="DB", team=None)
    v2 = _assess(row_db, _murphys(), chosen=1)
    assert v2.selected is None  # the join's own choice was already right


def test_a4_indistinguishable_entries_with_different_observations_are_refused():
    cands = [_ev(value=10.0, rank=5.0), _ev(value=3.0, rank=40.0)]
    v = _assess(_row(player_id=None, team=None), cands)
    assert v.verdict == r.ID_UNRESOLVED
    assert v.reason == r.ID_REASON_AMBIGUOUS_IN_SOURCE


def test_a4_the_same_row_listed_twice_is_not_ambiguous():
    cands = [_ev(value=10.0, rank=5.0), _ev(value=10.0, rank=5.0)]
    assert not _assess(_row(player_id=None, team=None), cands).refused


def test_a4_one_person_listed_on_two_pages_keeps_the_joins_choice():
    """FantasyPros IDP lists an edge rusher on its DL and LB pages: one person
    (same team, compatible families), two observations — not an identity
    ambiguity."""
    cands = [
        _ev(position="DL", team="BUF", value=50.0, rank=30.0),
        _ev(position="LB", team="BUF", value=70.0, rank=12.0),
    ]
    row = _row(player_id=None, position="DL", team="BUF")
    v = _assess(row, cands, chosen=1)
    assert not v.refused
    assert v.selected is None


def test_a4_decision_is_order_independent():
    row_dl = _row(player_id=None, name="Byron Murphy", position="DL", team=None)
    base = _murphys()
    for perm in itertools.permutations(range(2)):
        cands = [base[i] for i in perm]
        chosen = cands.index(base[1])
        v = _assess(row_dl, cands, chosen=chosen)
        picked = cands[v.selected if v.selected is not None else chosen]
        assert picked.raw_name == "Byron Murphy II"


# ── homonyms, A5, team-only ────────────────────────────────────────────


def test_same_group_homonyms_are_held_unless_the_entry_separates_them():
    row = _row(player_id=None, name="Josh Allen", position="DL", team="JAX")
    other = _row(player_id=None, name="Josh Allen", position="LB", team="BUF")
    held = _assess(row, [_ev(raw_name="Josh Allen", position="DL")], homonyms=[other])
    assert held.reason == r.ID_REASON_HOMONYM
    ok = _assess(row, [_ev(raw_name="Josh Allen", position="DL", team="JAX")], homonyms=[other])
    assert ok.verdict == r.ID_VERIFIED


def test_a5_a_non_exact_rung_needs_position_and_team_or_id():
    v = _assess(_row(player_id=None, team=None), [_ev()], via="fuzzy")
    assert v.reason == r.ID_REASON_LOW_EVIDENCE_RUNG
    ok = _assess(_row(player_id=None), [_ev(position="WR", team="BUF")], via="fuzzy")
    assert ok.verdict == r.ID_VERIFIED


def test_team_only_mismatch_is_held_and_released_by_continuity():
    held = _assess(_row(team="NYG"), [_ev(position="WR", team="MIN")])
    assert held.reason == r.ID_REASON_TEAM_ONLY_MISMATCH
    assert held.verdict == r.ID_UNRESOLVED
    released = _assess(_row(team="NYG"), [_ev(position="WR", team="MIN")], team_continuity=True)
    assert not released.refused
    # A matching id vouches regardless of team lag.
    assert not _assess(_row(team="NYG"), [_ev(team="MIN", sleeper_id="100")]).refused
    # A free agent / blank team is no evidence of a mismatch.
    assert not _assess(_row(team="FA"), [_ev(team="MIN")]).refused


def test_verified_and_name_only():
    assert _assess(_row(), [_ev(position="WR", team="BUF")]).verdict == r.ID_VERIFIED
    assert _assess(_row(), [_ev(sleeper_id="100")]).verdict == r.ID_VERIFIED
    name_only = _assess(_row(), [_ev()])
    assert name_only.verdict == r.ID_NAME_ONLY
    assert name_only.reason == r.ID_REASON_NAME_ONLY
    assert not name_only.refused


def test_the_served_csv_join_is_untouched():
    """Layer A grades a join; it never changes ``match_row_to_source_entry``."""
    decision = r.match_row_to_source_entry(
        row_player_id="1",
        row_name="Pat Player",
        row_position="WR",
        per_source={f"{_key('Pat Player')}::OFFENSE": {"value": 1}},
        sid_index={},
        row_groups_by_key={},
        canonical_match_key=_key,
        position_group=canonical_position_group,
    )
    assert decision == r.CsvJoinDecision(
        entry_key=f"{_key('Pat Player')}::OFFENSE", via="name_group"
    )
