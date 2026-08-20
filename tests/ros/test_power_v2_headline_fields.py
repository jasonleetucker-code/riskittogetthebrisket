"""V1-52 item D — the canonical engine gains ``record``/``teamName``.

THE GAP THIS CLOSES.

The landing-page power-leader card (``overview.currentPowerLeader``) used to
read the legacy ``public_league/power.py`` engine specifically because
``power_v2``'s rows never carried a team's win/loss record or its team name —
fields the card needs and the legacy engine happened to already compute for
its own (different) purposes. Retiring that dependency without a second
computation of either field means exposing what the canonical engine already
builds internally, additively, rather than adding a shim in ``overview.py``
that re-derives them from a different source.

``record`` is a FACT (career wins/losses from ``career_state``, the same
accumulator ``power.py``'s own field reads), independent of whether a
component survives to produce a weighted score — so it is present on BOTH
the normal-scoring rows and the refuse-to-rank ("unrankable") rows. This
file pins both.

``teamName`` is a lookup (``_metrics.team_name``, the same helper
``power.py`` calls), computed once per HEADLINE row rather than per
trend-week row — the trend series has no use for it and 56+ weeks of unused
lookups per owner would be pure waste.
"""

from __future__ import annotations

from src.ros import power_v2
from tests.ros.test_power_lenses import _scored_snapshot
from tests.public_league.fixtures import build_test_snapshot


def test_record_is_present_on_normal_scoring_rows():
    out = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
    assert out["unrankable"] is None, "fixture must exercise the NORMAL scoring path"
    for row in out["currentRanking"]:
        assert "record" in row
        assert row["record"] is not None
        wins, losses = row["record"].split("-")
        assert int(wins) + int(losses) == 3, "3 scored weeks in the fixture"


def test_record_is_present_even_when_the_engine_refuses_to_rank():
    """The refusal withholds a SCORE, not a FACT.

    ``build_test_snapshot()`` is preseason with no team-strength snapshot —
    every historical-results component is suppressed and there is no
    forward-looking substitute, so ``power_v2`` correctly refuses to rank
    (V1-52 item B). A team's win/loss record is knowable regardless of
    whether a weighted score is computable, and a consumer withholding the
    whole row because ``record`` was missing would be a NEW defect this
    unit does not introduce.
    """
    out = power_v2.build_section(build_test_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
    assert out["unrankable"] is not None, "fixture must exercise the REFUSAL path"
    assert out["currentRanking"], "the refusal still lists every owner"
    for row in out["currentRanking"]:
        assert row["powerScore"] is None
        assert row["rank"] is None
        assert "record" in row, "a fact should not disappear because a score was withheld"
        assert row["record"] is not None


def test_team_name_is_present_only_on_headline_rows_not_the_trend():
    """A lookup per owner, once — not per trend week.

    Adding it to every trend-week row too would be harmless in isolation
    but wasteful at scale (56+ weeks x every owner, per V1_52's own
    measured cost note) for a field nothing in the trend series reads.
    """
    out = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
    for row in out["currentRanking"]:
        assert "teamName" in row
        assert row["teamName"] is not None

    assert out["trend"]["weeks"], "fixture must have real trend history"
    for week in out["trend"]["weeks"]:
        for row in week["rankings"]:
            assert "teamName" not in row


def test_team_name_is_the_same_lookup_power_py_uses():
    """Not a re-derivation — the same helper, same source data."""
    from src.public_league import metrics as _metrics

    snapshot = _scored_snapshot()
    out = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)
    league_id = snapshot.seasons[-1].league_id
    for row in out["currentRanking"]:
        rid = None
        for (lid, r), oid in snapshot.managers.roster_to_owner.items():
            if lid == league_id and oid == row["ownerId"]:
                rid = r
                break
        expected = _metrics.team_name(snapshot, league_id, rid)
        assert row["teamName"] == expected
