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

RECONCILIATION NOTE (2026-08-21, Integration, onto #1032's `main`).
``record`` originally read ``state["career"]`` from inside ``_score_state``.
#1032 (landed on `main` after this unit was written) repointed the headline
call's ``state["career"]`` from the true unbounded ``career_state`` to a new
per-season-reset ``season_state``, to fix ppg/wl_record cross-season
contamination.  Left as originally written, ``record`` would have silently
inherited that repointing and started reading a CURRENT-SEASON W-L instead
of the true career total this field is documented above to mean — the exact
contamination class #1032 exists to prevent, reintroduced for a new field by
a same-name accident.  Fixed by moving ``record`` out of ``_score_state``
entirely into ``build_section``'s existing headline-only post-pass (beside
``teamName``), reading ``career_state`` directly rather than through
``state["career"]``.  ``test_record_is_present_on_normal_scoring_rows``
below cannot itself catch this — its fixture is single-season, so
``career_state`` and ``season_state`` are numerically identical there.
``test_record_is_the_true_career_total_not_the_current_season_only`` is the
one that discriminates, reusing the two-season fixture
``test_power_v2_season_scoping.py`` built for exactly this class of bug.
"""

from __future__ import annotations

from src.ros import power_v2
from tests.ros.test_power_lenses import _scored_snapshot
from tests.ros.test_power_v2_season_scoping import _row, _two_season_snapshot
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


def test_record_is_the_true_career_total_not_the_current_season_only():
    """The discriminating assertion the single-season fixture above cannot
    make. Two-season fixture (``test_power_v2_season_scoping``): season 2025
    alpha wins all 3 (500 vs 50), season 2026 alpha loses all 3 (~10 vs
    ~200) -- bravo is the exact mirror.

    SEASON-2026-ONLY (the bug this reconciliation prevents): alpha "0-3",
    bravo "3-0" -- exactly what ``season_state``, the accumulator #1032
    repointed the headline ``ppg``/``wl_record`` onto, would produce if
    ``record`` had been left reading it too.

    TRUE CAREER (correct, matches ``power.py``'s own semantics): both
    owners split 3-3 across the two seasons -- a symmetric fixture on
    purpose, so a season-scoped bug can't hide behind an accidentally
    correct-looking asymmetric number.
    """
    out = power_v2.build_section(_two_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
    alpha = _row(out["currentRanking"], "alpha")
    bravo = _row(out["currentRanking"], "bravo")
    assert alpha["record"] == "3-3", (
        f"got {alpha['record']!r} -- season-2026-only would read '0-3'; "
        "record must be the true career total, not the season-scoped accumulator"
    )
    assert bravo["record"] == "3-3", (
        f"got {bravo['record']!r} -- season-2026-only would read '3-0'; "
        "record must be the true career total, not the season-scoped accumulator"
    )
