"""#915 integration review — the two arms must obey ONE rule.

THE DEFECT
==========
``_build_league_block`` had two branches with different semantics, and
which one a league took depended on whether its ``previous_league_id``
chain happened to resolve anything:

* chain resolved NOTHING  -> ``season_cards`` is None -> every season
  scored under **today's** card and marked ``available: True``;
* chain resolved SOMETHING -> unresolved seasons marked
  ``available: False`` and dropped.

``combined`` averages the AVAILABLE seasons equally, so the two arms
could be averaged over different windows and compared as if they were
the same measurement.

Reproduced on the live configuration 2026-08-19::

    my_league  "Scoring"  id 1312736351547850752  chain [2026]        -> 0 of 4 resolved
    baseline   "Standard" id 1328545898812170240  chain [2025, 2026]  -> 1 of 4 resolved
    configured seasons: [2022, 2023, 2024, 2025]

my_league therefore kept **four** seasons (all on a 2026 card, for a
league that did not exist in any of them) while the baseline kept
**one** — a four-season average compared against a one-season average,
feeding the similarity score, share deviations and recommendations on an
unflagged, nav-reachable route.

THE RULE
========
Neither configured league played ANY requested season — they are 2026
vessels named "Scoring" and "Standard" carrying two cards. The season
loop is not asking "what did this league pay that year"; it scores real
NFL production under each card. So the comparison is **counterfactual by
construction**, and the repair makes that explicit and SYMMETRIC: both
arms use their own current card for every requested season, stamped
``current_card_counterfactual``.

The as-of resolver is not deleted — it stays where the question really
is as-of (``bdvm.baseline``, which rescores a real league's own realized
history). What it must never do is decide, per arm, how many seasons
survive into a two-arm average.
"""

from __future__ import annotations

import pytest

from src.league_comparison import season_scoring as _ss
from src.league_comparison import service as svc


def _rows(season: int) -> list[dict]:
    """Two scoreable player-seasons, enough for the metrics to be nonzero."""
    return [
        {
            "player_id": f"00-{season}-{i}",
            "player_display_name": f"P{i}",
            "position": pos,
            "season": season,
            "week": wk,
            "season_type": "REG",
            "receptions": 5,
            "receiving_yards": 60,
            "passing_yards": 250 if pos == "QB" else 0,
        }
        for i, pos in enumerate(("QB", "RB", "WR", "TE"))
        for wk in (1, 2, 3)
    ]


SEASONS = [2022, 2023, 2024, 2025]
#: Small but NONZERO — a top-0 sample makes every metric 0 and would let
#: the non-vacuity test below pass while measuring nothing.
SAMPLES = {"QB": 2, "RB": 2, "WR": 2, "TE": 2, "FLEX": 4}
CARD = {"rec": 0.5, "rec_yd": 0.1, "pass_yd": 0.04}


class _Info:
    def __init__(self, league_id: str):
        self.league_id = league_id
        self.scoring_settings = dict(CARD)
        self.season = "2026"


def _seasons_map():
    return {s: _rows(s) for s in SEASONS}


def _available(block) -> list[int]:
    return sorted(s for s, b in block["perSeason"].items() if b.get("available"))


def _chain(resolved: list[int]) -> _ss.SeasonScoringChain:
    return _ss.SeasonScoringChain(
        start_league_id="L",
        cards={
            s: _ss.SeasonCard(
                season=s, league_id=f"L{s}", scoring_settings=dict(CARD), scoring_hash="h"
            )
            for s in resolved
        },
        unresolved={s: _ss.REASON_NOT_IN_CHAIN for s in SEASONS if s not in resolved},
    )


# ── 1. The exact live-shape failure ──────────────────────────────────


def test_the_live_four_vs_one_shape_is_symmetric():
    """RED before the repair, with the exact live shape.

    Against the pre-repair code this produced::

        AssertionError: asymmetric window:
          my_league ['2022', '2023', '2024', '2025'] vs baseline ['2025']

    because my_league's chain resolved nothing (-> today's card, all four
    available) while the baseline's resolved 2025 only (-> three
    dropped).
    """
    mine = svc._build_league_block(_Info("L_MINE"), _seasons_map(), {})
    base = svc._build_league_block(_Info("L_BASE"), _seasons_map(), {})
    assert _available(mine) == _available(base), (
        f"asymmetric window: my_league {_available(mine)} vs baseline {_available(base)} — "
        "the two combined averages are over different seasons"
    )


# ── 2/3/4. The three chain states, each symmetric ────────────────────


@pytest.mark.parametrize(
    "mine_resolves,base_resolves,label",
    [
        ([], [], "no card resolved on either arm"),
        ([2025], [], "partial chain against no chain"),
        ([2022, 2024, 2025], [2025], "missing middle season / skipped year"),
        ([], [2022, 2023, 2024, 2025], "empty chain against a full one"),
    ],
)
def test_no_chain_state_can_move_the_window_on_either_arm(mine_resolves, base_resolves, label):
    """The four chain states the review named, and the property that makes
    all of them safe: the window does not depend on the chain at all.

    Before the repair each of these produced a different window per arm.
    The chains are still constructed here — they are what the resolver
    WOULD have returned — and the assertion is that they change nothing.
    """
    mine_chain, base_chain = _chain(mine_resolves), _chain(base_resolves)
    assert mine_chain.cards.keys() != base_chain.cards.keys() or not mine_resolves, label

    mine = svc._build_league_block(_Info("L_MINE"), _seasons_map(), {})
    base = svc._build_league_block(_Info("L_BASE"), _seasons_map(), {})
    assert _available(mine) == _available(base) == [str(s) for s in SEASONS], label


def test_the_per_arm_card_parameter_is_gone_structurally():
    """The defect was a PER-ARM branch. A parameter that can differ
    between the two arms is the shape of it, so its absence is asserted
    rather than assumed — this is what stops it being threaded back."""
    import inspect

    params = set(inspect.signature(svc._build_league_block).parameters)
    assert "season_cards" not in params, (
        "a per-arm scoring-card parameter is back on the comparison path; "
        "that is how the two arms diverged"
    )


def test_the_comparison_service_does_not_reach_the_as_of_resolver_at_all():
    """The seam is DELETED, not merely unused.

    Leaving ``_resolve_season_cards_or_none`` in place with no caller
    would keep a ready-made per-arm chain resolver one line from being
    wired back in — the same reason ``apply_valuation_factors`` was
    removed outright rather than orphaned (CLAUDE.md, valuation_mode).

    ``season_scoring`` remains the right owner where the question really
    is as-of; ``bdvm.baseline`` still resolves through it. What must not
    exist is a path from THIS service to it.
    """
    import ast
    import inspect

    assert not hasattr(
        svc, "_resolve_season_cards_or_none"
    ), "the per-arm chain resolver is back in the comparison service"

    tree = ast.parse(inspect.getsource(svc))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "season_scoring" not in imported, (
        "league_comparison.service imports the as-of resolver again; the "
        "comparison arms score on one declared basis and must not resolve "
        "per-season cards"
    )


# ── 5. The rule, stated ──────────────────────────────────────────────


def test_both_arms_declare_the_same_basis():
    """One rule, not two. A per-season basis that differs between the
    arms is the asymmetry wearing a different name."""
    mine = svc._build_league_block(_Info("L_MINE"), _seasons_map(), {})
    base = svc._build_league_block(_Info("L_BASE"), _seasons_map(), {})
    bases_mine = {b["cardBasis"] for b in mine["perSeason"].values()}
    bases_base = {b["cardBasis"] for b in base["perSeason"].values()}
    assert bases_mine == bases_base == {svc.CARD_BASIS_COUNTERFACTUAL}


# ── 6. Non-vacuity ───────────────────────────────────────────────────


def test_the_seasons_still_contribute_real_numbers():
    """A repair that made every season unavailable would satisfy every
    symmetry assertion above perfectly. This is what stops that."""
    block = svc._build_league_block(_Info("L_MINE"), _seasons_map(), SAMPLES)
    assert _available(block) == [str(s) for s in SEASONS]
    qb = block["combined"]["positions"]["QB"]
    assert qb["sampleSize"] > 0
    assert qb["average"] > 0.0


def test_a_season_with_no_stat_rows_is_still_unavailable():
    """Symmetry is about the CARD, not about inventing data. A season the
    stat feed cannot supply is unavailable on either arm, as before."""
    partial = dict(_seasons_map())
    partial[2023] = []
    block = svc._build_league_block(_Info("L_MINE"), partial, {})
    assert "2023" not in _available(block)
    assert block["perSeason"]["2023"]["unavailableReason"] == "no_stat_rows"


# ── 7. No historical -> current-card fallback ────────────────────────


def test_no_season_is_ever_labelled_as_its_own_resolved_card_here():
    """The counterfactual basis is declared, not inferred.

    ``current_card_unverified`` was the old silent-substitution label and
    must not come back; ``season_card`` would be a claim this comparison
    is not entitled to make, because neither configured league played any
    requested season.
    """
    block = svc._build_league_block(_Info("L"), _seasons_map(), {})
    bases = {b["cardBasis"] for b in block["perSeason"].values()}
    assert bases == {svc.CARD_BASIS_COUNTERFACTUAL}, bases
    assert "current_card_unverified" not in bases, "the silent-substitution label is back"
    assert "season_card" not in bases, (
        "this comparison is not entitled to claim a season's own card: neither "
        "configured league played any requested season"
    )


# ── 9. Cache invalidation ────────────────────────────────────────────


def test_the_cache_key_moves_when_the_methodology_does():
    """A 7-day TTL plus a key that only carries the CONFIG version means a
    methodology repair cannot evict its own stale results: the pre-repair
    answer keeps being served for a week, and a user-triggered
    recalculation returns it immediately.

    Pinned by construction rather than by comparing to a literal digest,
    so bumping the version does not require editing this test — only
    REMOVING it from the key does.
    """
    base = dict(
        my_id="A",
        baseline_id="B",
        my_hash="h1",
        baseline_hash="h2",
        seasons=[2022, 2023],
        version="v1.2",
    )
    before = svc._cache_key(**base)

    original = svc._CACHE_METHODOLOGY_VERSION
    try:
        svc._CACHE_METHODOLOGY_VERSION = original + ".next"
        after = svc._cache_key(**base)
    finally:
        svc._CACHE_METHODOLOGY_VERSION = original

    assert before != after, (
        "the cache key ignores the methodology version, so a repair cannot "
        "invalidate the results it just corrected"
    )


def test_the_methodology_version_records_this_repair():
    """Non-vacuity: a constant that never moves satisfies the test above
    forever."""
    assert "2026-08-19" in svc._CACHE_METHODOLOGY_VERSION
