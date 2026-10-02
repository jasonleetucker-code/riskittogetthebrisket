"""BROAD_CONTEXT: the fourth target-pricing disposition (owner decision 2, 2026-10-01).

Pinned here:

* every disposition path, with its ``dispositionReasons`` and
  ``targetPriceAuthority`` (NATIVE 1, VALIDATED_TRANSFORMABLE 1, BROAD_CONTEXT 0,
  TARGET_UNSUPPORTED 0);
* the NATIVE_COMPARABLE set is the pre-decision rule's (a frozen copy of #1586's
  three-disposition logic is the reference) MINUS exactly the trades failing the
  transaction-integrity gate, which now runs before the NATIVE check (owner
  TARGET_UNSUPPORTED definition); no fixture NATIVE trade is affected end to end;
* only TRULY unresolved identities are hard failures — an identified but
  unpriceable asset (startup pick, out-of-grammar pick) is BROAD_CONTEXT with
  ``includes_unpriceable_asset``;
* the three BROAD_CONTEXT kinds are mutually exclusive, precedence
  mismatch > unknown > timing_limited;
* the former #1595 "verified dynasty candidate" population maps into
  BROAD_CONTEXT unless another hard failure applies;
* TARGET_UNSUPPORTED is HARD insufficiency only;
* no consumer treats BROAD_CONTEXT as price authority.
"""

from __future__ import annotations

import ast
import itertools
from pathlib import Path

import pytest

from src.trade import market_trade_format as F
from src.trade import market_trade_groups as grp
from src.trade import market_trade_normalize as N
from src.trade import market_trade_report as R
from tests.trade.market_trade_fixtures import TARGET_POSITIONS, TARGET_SCORING, sleeper_league
from tests.trade.test_market_trade_census import _build, _seed, env  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
TARGET = F.format_from_sleeper_league(sleeper_league("TGT"))

SIDES = [
    [{"kind": "player", "canonicalId": "player:1", "position": "WR"}],
    [{"kind": "player", "canonicalId": "player:2", "position": "RB"}],
]
BRACKETED = {
    "timing": "at_or_before_trade",
    "exactAtTradeTime": True,
    "confirmationAfterTrade": "confirmed",
    "captureSource": "t",
}
POST_TRADE = {"timing": "post_trade_capture", "exactAtTradeTime": False}
SEASON_FINAL = {**POST_TRADE, "leagueStatusAtCapture": "complete"}
UNCONFIRMED = {
    "timing": "at_or_before_trade",
    "exactAtTradeTime": False,
    "confirmationAfterTrade": "missing",
}
CHANGED = {**UNCONFIRMED, "confirmationAfterTrade": "changed_after_trade"}
TIME_UNKNOWN = {"timing": "trade_time_unknown", "exactAtTradeTime": False}
UNDATED = {**BRACKETED, "captureSource": "legacy_snapshot_time_unknown"}

HARD_FAILURE_PREFIXES = (
    "dynasty_state_unverified",
    "not_dynasty:",
    "no_transaction_observation",
    "transaction_topology_unverifiable",
    "unusable_transaction_identity",
    "invalid_topology:",
    "unresolved_assets",
)


def fmt(**kw):
    return F.format_from_sleeper_league(sleeper_league("SRC", **kw))


def obs(evidence=None, sides=SIDES, source="sleeper_league_capture_full", **extra):
    out = {"formatSource": source, "formatEvidence": evidence, "sides": sides}
    out.update(extra)
    return out


def legacy_three_disposition(src, tgt, observation):
    """FROZEN reference: #1586 + #1606/#1607's decision, before owner decision 2.
    Only NATIVE is compared against it (the empty production registry never
    produces VALIDATED_TRANSFORMABLE)."""
    axes = F.compare_formats(src, tgt)
    if F.format_timing_cap(observation) is not None:
        return F.TARGET_UNSUPPORTED
    if all(axes[n]["state"] == F.MATCH for n in F.AXES):
        return F.NATIVE_COMPARABLE
    return F.TARGET_UNSUPPORTED


ONE_QB = [p if p != "SUPER_FLEX" else "FLEX" for p in TARGET_POSITIONS]
NO_CARD = sleeper_league("SRC") | {"scoring_settings": None}

FORMATS = {
    "same": fmt(),
    "one_qb": fmt(roster_positions=ONE_QB),
    "ten_teams": fmt(teams=10),
    "idp_scoring": fmt(scoring=dict(TARGET_SCORING, idp_sack=4.0)),
    "no_card": F.format_from_sleeper_league(NO_CARD),
    "redraft": fmt(ltype=0),
    "keeper": fmt(ltype=1),
    "type_unknown": F.format_from_sleeper_league(
        {**sleeper_league("SRC"), "settings": {"num_teams": 12, "best_ball": 1}}
    ),
    "ktc": F.TradeMarketFormat(source=F.SOURCE_KTC, dynasty_state=F.DYNASTY),
    "nothing_observed": F.TradeMarketFormat(source=F.SOURCE_UNKNOWN, dynasty_state=F.DYNASTY),
}
EVIDENCE = {
    "bracketed": BRACKETED,
    "post_trade": POST_TRADE,
    "season_final": SEASON_FINAL,
    "unconfirmed": UNCONFIRMED,
    "changed": CHANGED,
    "time_unknown": TIME_UNKNOWN,
    "undated": UNDATED,
    "no_evidence_vendor": None,
}


def _pick(reason, ref=None):
    return {
        "kind": "pick",
        "canonicalId": None,
        "vendorRef": ref,
        "label": ref,
        "pick": None,
        "resolution": {"status": "unresolved", "method": "pick_label", "reason": reason},
    }


STARTUP_PICK = _pick("startup_pick_not_a_market_ref", "Startup Pick 1.05")
#: SYNTHETIC: a grammar refusal of a pick whose round IS real.  Today's
#: grammars refuse picks only for a round outside 1-20, so the normalizer
#: cannot currently emit this; the predicate still admits it.
OUT_OF_GRAMMAR_PICK = _pick("pick_outside_market_grammar", "2027 Round 3")
#: What the normalizer really emits for an out-of-range round: NOT identified.
ROUND_ZERO_PICK = _pick("pick_outside_market_grammar", "pick:2027:0")
ROUND_25_PICK = _pick("pick_outside_market_grammar", "pick:2027:25")
UNPARSEABLE_PICK = _pick("unparseable_pick_label")
UNRESOLVED_PLAYER = {
    "kind": "unresolved",
    "canonicalId": None,
    "resolution": {"status": "unresolved", "method": "name", "reason": "no_match"},
}

SIDE_VARIANTS = {
    "ok": SIDES,
    "empty": [],
    "one_sided": [SIDES[0], []],
    "unresolved": [[{"kind": "unresolved", "canonicalId": None}], SIDES[1]],
    "multi_team": [SIDES[0], SIDES[1], [{"kind": "player", "canonicalId": "player:3"}]],
    "startup_pick": [SIDES[0] + [STARTUP_PICK], SIDES[1]],
    "out_of_grammar_pick": [SIDES[0] + [OUT_OF_GRAMMAR_PICK], SIDES[1]],
    "unparseable_pick": [SIDES[0] + [UNPARSEABLE_PICK], SIDES[1]],
    "round_zero_pick": [SIDES[0] + [ROUND_ZERO_PICK], SIDES[1]],
    "round_25_pick": [SIDES[0] + [ROUND_25_PICK], SIDES[1]],
}
#: Side variants that fail the transaction-integrity gate.
INTEGRITY_FAILING_SIDES = {
    "empty",
    "one_sided",
    "unresolved",
    "unparseable_pick",
    "round_zero_pick",
    "round_25_pick",
}


def _variants():
    for (fk, f), (ek, ev), (sk, sides) in itertools.product(
        FORMATS.items(), EVIDENCE.items(), SIDE_VARIANTS.items()
    ):
        source = "ktc_vendor_settings" if ev is None else "sleeper_league_capture_full"
        yield f"{fk}/{ek}/{sk}", f, obs(ev, sides=sides, source=source)


VARIANTS = list(_variants())


# ── NATIVE: timing unchanged, integrity failures override ──────────────────


def test_native_set_is_the_pre_decision_rule_minus_integrity_failures():
    before = {
        k for k, f, o in VARIANTS if legacy_three_disposition(f, TARGET, o) == "NATIVE_COMPARABLE"
    }
    after = {
        k
        for k, f, o in VARIANTS
        if F.disposition(f, TARGET, observation=o)["disposition"] == F.NATIVE_COMPARABLE
    }
    failing = {k for k, _, o in VARIANTS if F.transaction_integrity_failures(o)}
    assert after == before - failing
    # The timing rule is untouched: nothing becomes native that was not.
    assert after <= before
    # Non-vacuous: the legacy rule made the identical format native for EVERY
    # topology (bracketed, or a non-capture vendor format with nothing to cap);
    # exactly the integrity-failing topologies drop out.
    native_formats = {f"same/{e}" for e in ("bracketed", "no_evidence_vendor")}
    assert before == {f"{nf}/{s}" for nf in native_formats for s in SIDE_VARIANTS}
    assert before - after == {f"{nf}/{s}" for nf in native_formats for s in INTEGRITY_FAILING_SIDES}
    # An identified-but-unpriceable asset is NOT an integrity failure.
    assert {"same/bracketed/startup_pick", "same/bracketed/out_of_grammar_pick"} <= after


@pytest.mark.parametrize(
    "sides,extra,reasons",
    [
        ([], {}, ["invalid_topology:empty"]),
        ([SIDES[0], []], {}, ["invalid_topology:two_team_one_sided"]),
        ([SIDES[0] + [UNRESOLVED_PLAYER], SIDES[1]], {}, ["unresolved_assets"]),
        ([SIDES[0] + [UNPARSEABLE_PICK], SIDES[1]], {}, ["unresolved_assets"]),
        (SIDES, {"dedupeState": "UNRESOLVED"}, ["unusable_transaction_identity"]),
    ],
)
def test_an_integrity_failing_all_match_bracketed_trade_is_target_unsupported(
    sides, extra, reasons
):
    o = obs(BRACKETED, sides=sides, **extra)
    # Legacy: native (every axis MATCH, bracketed).  Now the integrity gate wins.
    assert legacy_three_disposition(fmt(), TARGET, o) == F.NATIVE_COMPARABLE
    d = F.disposition(fmt(), TARGET, observation=o)
    assert d["disposition"] == F.TARGET_UNSUPPORTED
    assert d["dispositionReasons"] == reasons
    assert d["targetPriceAuthority"] == 0 and d["broadContextKind"] is None
    assert d["formatTimingCap"] is None
    assert d["strongestUnsupportedAxis"] == F.TRANSACTION_INTEGRITY_AXIS
    assert F.broad_context_kind(fmt(), d["comparability"], None) is None


def test_a_bare_format_comparison_has_no_transaction_to_fail():
    # No observation: a format statement, judged on format and timing alone.
    assert F.disposition(fmt(), TARGET)["disposition"] == F.NATIVE_COMPARABLE
    # ...while a non-native one still names the missing transaction.
    d = F.disposition(fmt(teams=10), TARGET)
    assert d["dispositionReasons"] == ["no_transaction_observation"]


def test_native_set_is_identical_end_to_end(env):  # noqa: F811
    _seed(env, non_dynasty=True)
    result = _build(env)
    tgt = result["targetFormat"]
    before_groups = [
        g
        for g in result["grouping"].groups
        if legacy_three_disposition(R._fmt_of(g), tgt, g) == F.NATIVE_COMPARABLE
    ]
    # No fixture NATIVE trade fails the integrity gate, so none is affected.
    assert not [g for g in before_groups if F.transaction_integrity_failures(g)]
    before = {g["underlyingTradeId"] for g in before_groups}
    after = {
        g["underlyingTradeId"]
        for g in result["grouping"].groups
        if g["disposition"] == F.NATIVE_COMPARABLE
    }
    assert after == before and len(after) == 6


# ── analysis-blocking unresolved vs identified-but-unpriceable ───────────


def test_unpriceable_pick_reasons_match_the_normalizer():
    startup = N.market_ref_from_vendor_label("Startup Pick 1.05", mid_is_vendor_default=True)
    assert startup[3] == "startup_pick_not_a_market_ref"
    deep = N._sleeper_asset("pick:2027:25", "pick", None)
    zero = N._sleeper_asset("pick:2027:0", "pick", None)
    for a in (deep, zero):
        assert a["canonicalId"] is None
        assert a["resolution"]["reason"] == "pick_outside_market_grammar"
    ktc_deep = N.market_ref_from_vendor_label("2027 Round 25", mid_is_vendor_default=True)
    assert ktc_deep[3] == "pick_outside_market_grammar"
    ktc_asset = N._pick_asset(
        None, vendor_ref="903", label="2027 Round 25", vendor_grade=None, reason=ktc_deep[3]
    )
    assert F._IDENTIFIED_UNPRICEABLE_PICK_REASONS == {
        "startup_pick_not_a_market_ref",
        "pick_outside_market_grammar",
    }
    # Round 0 and out-of-range rounds are NONSENSICAL identities, in every lane.
    for a in (deep, zero, ktc_asset):
        assert F.asset_identity_state(a) == F.ASSET_UNRESOLVED
    # Unparseable labels are UNKNOWN identities in every lane.
    for asset in (
        N._sleeper_asset("pick:x", "pick", None),
        N._own_asset("not-a-pick-id", "pick", None),
        N._pick_asset(None, vendor_ref="z", label="junk", vendor_grade=None, reason=None),
    ):
        assert F.asset_identity_state(asset) == F.ASSET_UNRESOLVED
    startup_asset = N._pick_asset(
        None,
        vendor_ref="Startup Pick 1.05",
        label="Startup Pick 1.05",
        vendor_grade=None,
        reason=startup[3],
    )
    assert F.asset_identity_state(startup_asset) == F.ASSET_UNPRICEABLE


def test_pick_round_range_is_the_market_pick_refs_own():
    from src.identity.picks import MarketPickRef

    assert (F._PICK_ROUND_MIN, F._PICK_ROUND_MAX) == (1, 20)
    MarketPickRef(year=2027, round_num=F._PICK_ROUND_MIN)
    MarketPickRef(year=2027, round_num=F._PICK_ROUND_MAX)
    for bad in (F._PICK_ROUND_MIN - 1, F._PICK_ROUND_MAX + 1):
        with pytest.raises(ValueError, match="round out of range"):
            MarketPickRef(year=2027, round_num=bad)


@pytest.mark.parametrize(
    "asset,state",
    [
        ({"kind": "player", "canonicalId": "player:1"}, F.ASSET_RESOLVED),
        ({"kind": "faab", "canonicalId": None}, F.ASSET_RESOLVED),
        (STARTUP_PICK, F.ASSET_UNPRICEABLE),
        (OUT_OF_GRAMMAR_PICK, F.ASSET_UNPRICEABLE),
        (ROUND_ZERO_PICK, F.ASSET_UNRESOLVED),
        (ROUND_25_PICK, F.ASSET_UNRESOLVED),
        (_pick("pick_outside_market_grammar"), F.ASSET_UNRESOLVED),  # round unreadable
        (_pick("pick_outside_market_grammar", "2027 Round 21"), F.ASSET_UNRESOLVED),
        (_pick("startup_pick_not_a_market_ref"), F.ASSET_UNPRICEABLE),
        (UNPARSEABLE_PICK, F.ASSET_UNRESOLVED),
        (_pick(None), F.ASSET_UNRESOLVED),
        (UNRESOLVED_PLAYER, F.ASSET_UNRESOLVED),
        ({"kind": "something_new", "canonicalId": None}, F.ASSET_UNRESOLVED),
    ],
)
def test_asset_identity_state(asset, state):
    assert F.asset_identity_state(asset) == state


@pytest.mark.parametrize("pick", [STARTUP_PICK, OUT_OF_GRAMMAR_PICK])
def test_a_dynasty_trade_with_an_unpriceable_pick_is_broad_context(pick):
    for f, kind in (
        (fmt(), F.BROAD_TIMING_LIMITED),
        (fmt(teams=10), F.BROAD_FORMAT_MISMATCH),
        (F.format_from_sleeper_league(NO_CARD), F.BROAD_FORMAT_UNKNOWN),
    ):
        d = F.disposition(
            f, TARGET, observation=obs(POST_TRADE, sides=[SIDES[0] + [pick], SIDES[1]])
        )
        assert d["disposition"] == F.BROAD_CONTEXT
        assert d["broadContextKind"] == kind
        assert "includes_unpriceable_asset" in d["dispositionReasons"]
        assert "unresolved_assets" not in d["dispositionReasons"]
        assert d["targetPriceAuthority"] == 0


@pytest.mark.parametrize("pick", [ROUND_ZERO_PICK, ROUND_25_PICK])
def test_an_out_of_range_round_pick_is_a_hard_failure(pick):
    sides = [SIDES[0] + [pick], SIDES[1]]
    for ev in (BRACKETED, POST_TRADE):
        d = F.disposition(fmt(), TARGET, observation=obs(ev, sides=sides))
        assert d["disposition"] == F.TARGET_UNSUPPORTED
        assert d["dispositionReasons"] == ["unresolved_assets"]
        assert d["targetPriceAuthority"] == 0


@pytest.mark.parametrize("pick", [STARTUP_PICK, OUT_OF_GRAMMAR_PICK])
def test_a_native_trade_with_an_unpriceable_asset_stays_native_and_says_so(pick):
    sides = [SIDES[0] + [pick], SIDES[1]]
    d = F.disposition(fmt(), TARGET, observation=obs(BRACKETED, sides=sides))
    assert d["disposition"] == F.NATIVE_COMPARABLE
    assert d["targetPriceAuthority"] == 1
    assert d["dispositionReasons"] == ["includes_unpriceable_asset"]
    assert d["broadContextKind"] is None and d["strongestUnsupportedAxis"] is None
    # A fully priceable native trade carries no reason.
    assert F.disposition(fmt(), TARGET, observation=obs(BRACKETED))["dispositionReasons"] == []


def test_an_unresolved_player_identity_is_target_unsupported():
    sides = [SIDES[0] + [UNRESOLVED_PLAYER], SIDES[1]]
    d = F.disposition(fmt(), TARGET, observation=obs(POST_TRADE, sides=sides))
    assert d["disposition"] == F.TARGET_UNSUPPORTED
    assert d["dispositionReasons"] == ["unresolved_assets"]


def test_classify_topology_is_unchanged_for_fit_suitability():
    # The other consumer keeps its stricter "can it enter a fit" flag.
    from src.trade import market_trade_eval as ev

    topo = ev.classify_topology({"sides": [SIDES[0] + [STARTUP_PICK], SIDES[1]]})
    assert "includes_unresolved" in topo["flags"]
    assert "includes_startup_pick" in topo["flags"]
    assert "includes_unresolved" in ev.fit_suitability({}, topo)["reasons"]


def test_native_result_shape_is_additive_only():
    d = F.disposition(fmt(), TARGET, observation=obs(BRACKETED))
    assert d["disposition"] == F.NATIVE_COMPARABLE
    assert d["strongestUnsupportedAxis"] is None and d["formatTimingCap"] is None
    assert d["translation"] is None
    assert d["targetPriceAuthority"] == 1
    assert d["broadContextKind"] is None and d["dispositionReasons"] == []


# ── the former #1595 population ────────────────────────────────────────────


def _former_candidate(f, o):
    """#1595's descriptive rule over the pre-decision disposition."""
    axes = F.compare_formats(f, TARGET)
    return (
        legacy_three_disposition(f, TARGET, o) == F.TARGET_UNSUPPORTED
        and axes["dynastyState"]["state"] == F.MATCH
    )


def test_former_candidates_map_to_broad_context_unless_a_hard_failure_applies():
    seen_broad = seen_hard = 0
    for key, f, o in VARIANTS:
        if not _former_candidate(f, o):
            continue
        d = F.disposition(f, TARGET, observation=o)
        hard = F.transaction_integrity_failures(o)
        if hard:
            assert d["disposition"] == F.TARGET_UNSUPPORTED, key
            assert d["dispositionReasons"] == hard, key
            seen_hard += 1
        else:
            assert d["disposition"] == F.BROAD_CONTEXT, key
            assert d["targetPriceAuthority"] == 0
            seen_broad += 1
    assert seen_broad and seen_hard


def test_former_candidates_end_to_end(env):  # noqa: F811
    _seed(env, non_dynasty=True)
    result = _build(env)
    tgt = result["targetFormat"]
    candidates = [g for g in result["grouping"].groups if _former_candidate(R._fmt_of(g), g)]
    assert candidates, "fixture has verified-dynasty non-native trades"
    for g in candidates:
        if g["disposition"] == F.TARGET_UNSUPPORTED:
            assert all(r.startswith(HARD_FAILURE_PREFIXES) for r in g["dispositionReasons"])
        else:
            assert g["disposition"] == F.BROAD_CONTEXT
    # Verified non-dynasty / unstated type stay TARGET_UNSUPPORTED.
    others = [
        g
        for g in result["grouping"].groups
        if F.compare_formats(R._fmt_of(g), tgt)["dynastyState"]["state"] != F.MATCH
    ]
    reasons = sorted(r for g in others for r in g["dispositionReasons"])
    assert {"not_dynasty:redraft", "not_dynasty:keeper", "dynasty_state_unverified"} <= set(reasons)
    assert all(g["disposition"] == F.TARGET_UNSUPPORTED for g in others)


# ── every path, its reasons and its authority ─────────────────────────────


def test_timing_limited_post_trade_all_axes_match():
    d = F.disposition(fmt(), TARGET, observation=obs(POST_TRADE))
    assert (d["disposition"], d["broadContextKind"]) == (F.BROAD_CONTEXT, F.BROAD_TIMING_LIMITED)
    assert d["targetPriceAuthority"] == 0
    assert d["dispositionReasons"] == [
        "format_capture_post_trade",
        "format_unconfirmed_at_trade",
        "post_trade_capture",
        "all_observed_axes_match_target",
    ]
    assert d["strongestUnsupportedAxis"] == F.FORMAT_TIMING_AXIS


def test_timing_limited_season_final_settings():
    d = F.disposition(fmt(), TARGET, observation=obs(SEASON_FINAL))
    assert d["broadContextKind"] == F.BROAD_TIMING_LIMITED
    assert "season_final_settings" in d["dispositionReasons"]


@pytest.mark.parametrize(
    "evidence,cap",
    [
        (UNCONFIRMED, F.TIMING_CAP_UNCONFIRMED_AFTER_TRADE),
        (CHANGED, F.TIMING_CAP_CHANGED_AFTER_TRADE),
        (TIME_UNKNOWN, F.TIMING_CAP_TIME_UNKNOWN),
        (UNDATED, F.TIMING_CAP_UNDATED_SNAPSHOT),
        (None, F.TIMING_CAP_UNPROVEN),
    ],
)
def test_every_timing_cap_maps_to_timing_limited(evidence, cap):
    d = F.disposition(fmt(), TARGET, observation=obs(evidence))
    assert d["disposition"] == F.BROAD_CONTEXT
    assert d["broadContextKind"] == F.BROAD_TIMING_LIMITED
    assert d["formatTimingCap"] == cap
    assert d["dispositionReasons"][:2] == [cap, "format_unconfirmed_at_trade"]
    assert "all_observed_axes_match_target" in d["dispositionReasons"]
    assert "post_trade_capture" not in d["dispositionReasons"]


def test_format_mismatch_known_difference():
    d = F.disposition(fmt(roster_positions=ONE_QB), TARGET, observation=obs(BRACKETED))
    assert (d["disposition"], d["broadContextKind"]) == (F.BROAD_CONTEXT, F.BROAD_FORMAT_MISMATCH)
    assert d["dispositionReasons"] == ["format_axes_differ", "no_validated_translator"]
    assert d["strongestUnsupportedAxis"] == "qbDemand"
    assert d["targetPriceAuthority"] == 0


def test_format_mismatch_with_a_timing_cap_stamps_both():
    d = F.disposition(fmt(teams=10), TARGET, observation=obs(SEASON_FINAL))
    assert d["broadContextKind"] == F.BROAD_FORMAT_MISMATCH
    assert {"format_axes_differ", "season_final_settings", "format_capture_post_trade"} <= set(
        d["dispositionReasons"]
    )
    assert "all_observed_axes_match_target" not in d["dispositionReasons"]


def test_an_unknown_axis_beats_timing_limited():
    # NO_CARD: every observed axis matches, the scoring axes are UNKNOWN, and
    # the capture is post-trade.  An unobserved axis could still differ, so
    # this is format_unknown, with the timing reasons kept.
    d = F.disposition(F.format_from_sleeper_league(NO_CARD), TARGET, observation=obs(POST_TRADE))
    assert d["broadContextKind"] == F.BROAD_FORMAT_UNKNOWN
    assert d["dispositionReasons"] == [
        "format_capture_post_trade",
        "format_unconfirmed_at_trade",
        "post_trade_capture",
        "format_axes_unknown",
        "all_observed_axes_match_target",
    ]


def test_a_known_difference_beats_unknown_axes_and_timing():
    no_card_10 = sleeper_league("SRC", teams=10) | {"scoring_settings": None}
    d = F.disposition(F.format_from_sleeper_league(no_card_10), TARGET, observation=obs(POST_TRADE))
    assert d["broadContextKind"] == F.BROAD_FORMAT_MISMATCH
    assert {"format_axes_differ", "format_axes_unknown", "format_capture_post_trade"} <= set(
        d["dispositionReasons"]
    )


def test_broad_context_kinds_are_mutually_exclusive_on_every_variant():
    seen = set()
    for key, f, o in VARIANTS:
        d = F.disposition(f, TARGET, observation=o)
        if d["disposition"] != F.BROAD_CONTEXT:
            continue
        states = {d["comparability"][n]["state"] for n in F.AXES}
        diff = F.DIFFERENT in states
        unknown = F.UNKNOWN in states or f.source == F.SOURCE_UNKNOWN
        timed = d["formatTimingCap"] is not None
        expected = {
            F.BROAD_FORMAT_MISMATCH: diff,
            F.BROAD_FORMAT_UNKNOWN: not diff and unknown,
            F.BROAD_TIMING_LIMITED: not diff and not unknown and timed,
        }
        # Exactly one predicate holds, and it is the stamped kind.
        assert sum(expected.values()) == 1, key
        assert expected[d["broadContextKind"]], key
        seen.add(d["broadContextKind"])
    assert seen == {F.BROAD_FORMAT_MISMATCH, F.BROAD_FORMAT_UNKNOWN, F.BROAD_TIMING_LIMITED}


def test_format_unknown_axes_get_their_own_kind_and_reason():
    d = F.disposition(F.format_from_sleeper_league(NO_CARD), TARGET, observation=obs(BRACKETED))
    assert (d["disposition"], d["broadContextKind"]) == (F.BROAD_CONTEXT, F.BROAD_FORMAT_UNKNOWN)
    assert d["dispositionReasons"] == ["format_axes_unknown", "all_observed_axes_match_target"]
    assert d["targetPriceAuthority"] == 0


def test_a_never_observed_format_is_format_unknown_not_timing_limited():
    d = F.disposition(FORMATS["nothing_observed"], TARGET, observation=obs(POST_TRADE))
    assert d["broadContextKind"] == F.BROAD_FORMAT_UNKNOWN
    assert "all_observed_axes_match_target" not in d["dispositionReasons"]
    assert "format_axes_unknown" in d["dispositionReasons"]


def test_ktc_source_level_dynasty_with_unknown_card_is_broad_context():
    d = F.disposition(FORMATS["ktc"], TARGET, observation=obs(None, source="ktc_vendor_settings"))
    assert d["disposition"] == F.BROAD_CONTEXT
    assert d["broadContextKind"] == F.BROAD_FORMAT_UNKNOWN


@pytest.mark.parametrize(
    "key,reason",
    [
        ("redraft", "not_dynasty:redraft"),
        ("keeper", "not_dynasty:keeper"),
        ("type_unknown", "dynasty_state_unverified"),
    ],
)
def test_dynasty_lane_failures_are_target_unsupported(key, reason):
    for ev in (BRACKETED, POST_TRADE):
        d = F.disposition(FORMATS[key], TARGET, observation=obs(ev))
        assert d["disposition"] == F.TARGET_UNSUPPORTED
        assert d["dispositionReasons"] == [reason]
        assert d["targetPriceAuthority"] == 0 and d["broadContextKind"] is None


@pytest.mark.parametrize(
    "observation,reasons",
    [
        (None, ["no_transaction_observation"]),
        ({"formatEvidence": POST_TRADE}, ["transaction_topology_unverifiable"]),
        (obs(POST_TRADE, sides=[]), ["invalid_topology:empty"]),
        (obs(POST_TRADE, sides=[SIDES[0], []]), ["invalid_topology:two_team_one_sided"]),
        (
            obs(POST_TRADE, sides=SIDE_VARIANTS["unresolved"]),
            ["unresolved_assets"],
        ),
        (
            obs(POST_TRADE, dedupeState="UNRESOLVED"),
            ["unusable_transaction_identity"],
        ),
    ],
)
def test_integrity_failures_are_target_unsupported(observation, reasons):
    # A known mismatch (10 teams), so the trade is non-native whatever its
    # timing evidence; without the hard failure it would be BROAD_CONTEXT.
    d = F.disposition(fmt(teams=10), TARGET, observation=observation)
    assert d["disposition"] == F.TARGET_UNSUPPORTED
    assert d["dispositionReasons"] == reasons
    assert d["targetPriceAuthority"] == 0


def test_multi_team_and_faab_are_valid_topology():
    faab = [SIDES[0] + [{"kind": "faab", "canonicalId": None}], SIDES[1]]
    for sides in (SIDE_VARIANTS["multi_team"], faab):
        d = F.disposition(fmt(), TARGET, observation=obs(POST_TRADE, sides=sides))
        assert d["disposition"] == F.BROAD_CONTEXT


def test_possible_overlap_is_not_a_hard_failure():
    d = F.disposition(fmt(), TARGET, observation=obs(POST_TRADE, dedupeState="POSSIBLE_OVERLAP"))
    assert d["disposition"] == F.BROAD_CONTEXT


def test_dedupe_unresolved_literal_matches_the_groups_owner():
    assert F._DEDUPE_UNRESOLVED == grp.UNRESOLVED


def test_authority_table_and_helper():
    assert F.TARGET_PRICE_AUTHORITY == {
        F.NATIVE_COMPARABLE: 1,
        F.VALIDATED_TRANSFORMABLE: 1,
        F.BROAD_CONTEXT: 0,
        F.TARGET_UNSUPPORTED: 0,
    }
    assert set(F.DISPOSITIONS) == set(F.TARGET_PRICE_AUTHORITY)
    assert F.target_price_authority(None) == 0
    assert F.target_price_authority({"disposition": "SOMETHING_NEW"}) == 0
    for _, f, o in VARIANTS:
        d = F.disposition(f, TARGET, observation=o)
        assert d["targetPriceAuthority"] == F.target_price_authority(d)
        assert d["disposition"] in F.DISPOSITIONS
        assert (d["broadContextKind"] is not None) == (d["disposition"] == F.BROAD_CONTEXT)


def test_no_validated_transformable_exists_in_production():
    assert len(F.DEFAULT_REGISTRY) == 0
    assert all(
        F.disposition(f, TARGET, observation=o)["disposition"] != F.VALIDATED_TRANSFORMABLE
        for _, f, o in VARIANTS
    )


# ── no consumer treats BROAD_CONTEXT as price authority ───────────────────


def test_report_native_counts_exclude_broad_context(env):  # noqa: F811
    _seed(env)
    result = _build(env)
    groups = result["grouping"].groups
    assert any(g["disposition"] == F.BROAD_CONTEXT for g in groups)
    cov = R.coverage_report(result)
    assert cov["nativeComparableTrades"] == sum(
        1 for g in groups if g["disposition"] == F.NATIVE_COMPARABLE
    )
    census = R.target_format_census(result)
    assert census["sections"]["matchToTarget"]["trades"]["nativeComparable"] == 6
    assert all(
        g["targetPriceAuthority"] == (1 if g["disposition"] == F.NATIVE_COMPARABLE else 0)
        for g in groups
    )


def _modules_referencing(name: str) -> set[str]:
    hits = set()
    for path in (REPO / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == name:
                hits.add(path.relative_to(REPO).as_posix())
            elif isinstance(node, ast.Name) and node.id == name:
                hits.add(path.relative_to(REPO).as_posix())
    return hits


def test_only_the_owner_and_the_report_reference_the_broad_context_disposition():
    # Any new consumer of BROAD_CONTEXT must be reviewed: it carries
    # targetPriceAuthority 0 and may never feed target pricing.
    assert _modules_referencing("BROAD_CONTEXT") <= {
        "src/trade/market_trade_format.py",
        "src/trade/market_trade_report.py",
    }


def test_comparable_trades_does_not_consume_ledger_dispositions():
    # ``comparable_trades`` has its own own-league comps tiers (one of them is
    # named BROAD_MARKET_CONTEXT) and must not read the ledger's disposition as
    # price authority.
    src = (REPO / "src/trade/comparable_trades.py").read_text(encoding="utf-8")
    assert "market_trade_format" not in src
    assert '"disposition"' not in src and "targetPriceAuthority" not in src
