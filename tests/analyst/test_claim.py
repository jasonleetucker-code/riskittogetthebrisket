"""The analyst claim record, and the invariants that cannot be repaired later.

Owner spec §4.16 / §4.19 / §4.20 (T-NEW-10).  Several of these hold things
that are unrecoverable once a row has been written the wrong way: a stored
paraphrase is indistinguishable from a quote, and a claim stored without its
game type cannot have one inferred back.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.analyst import claim as C
from src.analyst.stance import SourceLabel, Stance

NOW = dt.datetime(2026, 8, 18, 12, 0, tzinfo=dt.timezone.utc)


def _source(analyst="analyst:mattie", content="ep:101", platform="podcast"):
    return C.SourceRef(analyst_id=analyst, content_id=content, platform=platform)


def _claim(**kw):
    base = dict(
        source=_source(),
        asset_key="player:4034",
        stance=Stance.BUY,
        source_label=SourceLabel.BUY,
        take_type=C.TakeType.BUY_SELL_VALUE,
        said_at=NOW,
        provenance=C.Provenance.TRANSCRIPT_PARAPHRASE,
        game_type=C.GameType.DYNASTY,
    )
    base.update(kw)
    return C.AnalystClaim(**base)


class TestAttributionIsMandatory:
    @pytest.mark.parametrize("field", ["analyst_id", "content_id", "platform"])
    def test_an_unattributable_take_is_not_a_claim(self, field):
        kwargs = {"analyst_id": "a", "content_id": "c", "platform": "p", field: "  "}
        with pytest.raises(ValueError, match=field):
            C.SourceRef(**kwargs)

    def test_a_claim_must_name_its_asset(self):
        with pytest.raises(ValueError, match="asset"):
            _claim(asset_key="")


class TestProvenanceCannotBeLaunderedIntoAQuote:
    """The one invariant that is unrecoverable after storage."""

    def test_a_verbatim_quote_is_allowed(self):
        c = _claim(provenance=C.Provenance.TRANSCRIPT_VERBATIM, quote="I'm buying him everywhere")
        assert c.quote

    @pytest.mark.parametrize(
        "provenance",
        [
            C.Provenance.TRANSCRIPT_PARAPHRASE,
            C.Provenance.MODEL_INFERENCE,
            C.Provenance.STRUCTURED_FEED,
        ],
    )
    def test_nothing_else_may_carry_a_quote(self, provenance):
        with pytest.raises(ValueError, match="quote"):
            _claim(provenance=provenance, quote="I'm buying him everywhere")

    def test_inference_is_still_a_valid_claim_without_a_quote(self):
        """Refusing the quote must not refuse the claim — a model reading is
        legitimate evidence as long as it is labelled as one."""
        c = _claim(provenance=C.Provenance.MODEL_INFERENCE)
        assert c.provenance is C.Provenance.MODEL_INFERENCE
        assert c.to_dict()["provenance"] == "model_inference"


class TestGameTypeFailsClosed:
    def test_only_a_proven_dynasty_take_is_dynasty_evidence(self):
        assert _claim(game_type=C.GameType.DYNASTY).is_dynasty_evidence

    @pytest.mark.parametrize(
        "game_type",
        [C.GameType.REDRAFT, C.GameType.BEST_BALL, C.GameType.UNKNOWN],
    )
    def test_everything_else_is_not(self, game_type):
        assert not _claim(game_type=game_type).is_dynasty_evidence

    def test_unknown_is_the_default_so_silence_never_becomes_dynasty(self):
        c = C.AnalystClaim(
            source=_source(),
            asset_key="player:1",
            stance=Stance.BUY,
            source_label=SourceLabel.BUY,
            take_type=C.TakeType.ROLE,
            said_at=NOW,
            provenance=C.Provenance.STRUCTURED_FEED,
        )
        assert c.game_type is C.GameType.UNKNOWN
        assert not c.is_dynasty_evidence

    def test_the_dynasty_gate_is_a_gate_not_a_hint(self):
        claims = [
            _claim(game_type=C.GameType.DYNASTY),
            _claim(game_type=C.GameType.REDRAFT),
            _claim(game_type=C.GameType.UNKNOWN),
        ]
        assert len(C.dynasty_claims(claims)) == 1


class TestConditionalStancesCarryTheirTrigger:
    def test_a_conditional_buy_without_a_condition_is_refused(self):
        """'Buy only if cheap' and 'buy' are different claims (§4.16)."""
        with pytest.raises(ValueError, match="conditional"):
            _claim(stance=Stance.CONDITIONAL_BUY)

    def test_with_a_condition_it_is_fine(self):
        c = _claim(
            stance=Stance.CONDITIONAL_BUY,
            conditions=(C.Condition("only under a 2027 2nd", kind="price"),),
        )
        assert c.to_dict()["conditions"] == [{"text": "only under a 2027 2nd", "kind": "price"}]

    def test_an_empty_condition_is_not_a_condition(self):
        with pytest.raises(ValueError, match="trigger"):
            C.Condition("   ")

    def test_unconditional_stances_need_none(self):
        assert _claim(stance=Stance.STASH, source_label=SourceLabel.STASH).conditions == ()


class TestOneAnalystOneVote:
    """§4.16: repeated takes from the same analyst/thesis lineage must not
    become independent votes.  §4.20: nor may podcast + YouTube syndication."""

    def test_the_same_thesis_repeated_weekly_counts_once(self):
        claims = [
            _claim(
                source=_source(content=f"ep:{i}"),
                said_at=NOW - dt.timedelta(days=7 * i),
                thesis_id="thesis:breakout-year-3",
            )
            for i in range(4)
        ]
        assert len(C.independent_claims(claims)) == 1

    def test_the_most_recent_airing_survives(self):
        old = _claim(
            source=_source(content="ep:1"),
            said_at=NOW - dt.timedelta(days=30),
            thesis_id="t1",
            notes="old",
        )
        new = _claim(source=_source(content="ep:2"), said_at=NOW, thesis_id="t1", notes="new")
        survivors = C.independent_claims([old, new])
        assert [c.notes for c in survivors] == ["new"]

    def test_syndication_across_platforms_is_one_opinion(self):
        """Same analyst, same thesis, podcast and its YouTube cut."""
        pod = _claim(source=_source(content="ep:1", platform="podcast"), thesis_id="t1")
        tube = _claim(source=_source(content="vid:1", platform="youtube"), thesis_id="t1")
        assert len(C.independent_claims([pod, tube])) == 1

    def test_two_different_analysts_are_two_votes(self):
        a = _claim(source=_source(analyst="analyst:a"), thesis_id="t1")
        b = _claim(source=_source(analyst="analyst:b"), thesis_id="t1")
        assert len(C.independent_claims([a, b])) == 2

    def test_the_same_analyst_on_two_different_players_is_two_claims(self):
        a = _claim(asset_key="player:1", thesis_id="t1")
        b = _claim(asset_key="player:2", thesis_id="t1")
        assert len(C.independent_claims([a, b])) == 2

    def test_without_a_thesis_id_a_repeated_stance_still_collapses(self):
        """The safe direction: under-count a genuinely new argument rather
        than manufacture independent votes out of a restatement."""
        claims = [_claim(source=_source(content=f"ep:{i}")) for i in range(3)]
        assert len(C.independent_claims(claims)) == 1

    def test_a_changed_mind_is_a_new_vote(self):
        bull = _claim(thesis_id="t1", stance=Stance.BUY, source_label=SourceLabel.BUY)
        bear = _claim(
            source=_source(content="ep:9"),
            thesis_id="t2",
            stance=Stance.SELL,
            source_label=SourceLabel.SELL,
            said_at=NOW,
        )
        assert len(C.independent_claims([bull, bear])) == 2

    def test_a_retraction_removes_the_claim_it_supersedes(self):
        """A retraction must not be outvoted by its own original, whatever
        the dates say."""
        original = _claim(
            source=_source(content="ep:1"), thesis_id="t1", said_at=NOW + dt.timedelta(days=1)
        )
        retraction = _claim(
            source=_source(content="ep:2"), thesis_id="t2", supersedes="ep:1", said_at=NOW
        )
        survivors = C.independent_claims([original, retraction])
        assert [c.source.content_id for c in survivors] == ["ep:2"]

    def test_an_empty_set_is_empty_not_an_error(self):
        assert C.independent_claims([]) == []


class TestTheDiscoveryWindowIsNotTheVotingWindow:
    def test_said_at_and_discovered_at_are_separate(self):
        c = _claim(said_at=NOW - dt.timedelta(days=10), discovered_at=NOW)
        payload = c.to_dict()
        assert payload["saidAt"] != payload["discoveredAt"]

    def test_discovery_is_optional_and_absent_is_null_not_a_guess(self):
        assert _claim().to_dict()["discoveredAt"] is None


class TestExplicitCallsVersusDiscussion:
    def test_a_stance_is_an_explicit_call(self):
        assert _claim().is_explicit_call

    def test_no_signal_is_an_answer_and_not_a_call(self):
        c = _claim(stance=Stance.NO_SIGNAL, source_label=SourceLabel.INSUFFICIENT_SIGNAL)
        assert not c.is_explicit_call
        assert c.to_dict()["stance"] == "NO_SIGNAL"


class TestClaimFromLabel:
    def test_it_translates_once_and_keeps_the_source_word(self):
        c = C.claim_from_label(
            SourceLabel.SLEEPER,
            source=_source(),
            asset_key="player:9",
            take_type=C.TakeType.DURABLE_THESIS,
            said_at=NOW,
            provenance=C.Provenance.TRANSCRIPT_PARAPHRASE,
        )
        assert c.stance is Stance.BUY
        assert c.source_label is SourceLabel.SLEEPER

    def test_a_stash_label_stays_speculative_through_the_helper(self):
        c = C.claim_from_label(
            SourceLabel.STASH,
            source=_source(),
            asset_key="player:9",
            take_type=C.TakeType.BUY_SELL_VALUE,
            said_at=NOW,
            provenance=C.Provenance.TRANSCRIPT_PARAPHRASE,
        )
        assert c.stance is Stance.STASH


class TestSerialisation:
    def test_the_payload_carries_every_decision_input(self):
        c = _claim(
            asset_side=C.AssetSide.IDP,
            conditions=(C.Condition("if he stays cheap"),),
            stance=Stance.CONDITIONAL_BUY,
            tags=("post-camp",),
        )
        payload = c.to_dict()
        for key in (
            "analystId",
            "contentId",
            "platform",
            "assetKey",
            "stance",
            "sourceLabel",
            "takeType",
            "saidAt",
            "provenance",
            "gameType",
            "assetSide",
            "isDynastyEvidence",
            "isExplicitCall",
            "conditions",
            "thesisKey",
        ):
            assert key in payload, key
        assert payload["assetSide"] == "idp"

    def test_the_thesis_key_is_stable_and_platform_independent(self):
        pod = _claim(source=_source(content="ep:1", platform="podcast"), thesis_id="t1")
        tube = _claim(source=_source(content="vid:1", platform="youtube"), thesis_id="t1")
        assert pod.thesis_key == tube.thesis_key
