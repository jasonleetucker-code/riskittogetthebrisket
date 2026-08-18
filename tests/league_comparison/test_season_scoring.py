"""A season must be scored under the rules that season was played under.

THE DEFECT
----------
Historical rescoring applied TODAY's scoring card to every season.  A league
that moved from 0.5 PPR to full PPR between 2023 and 2025 had its 2023
rewritten under rules nobody played, and the "realized points" described a
season that never happened.

Sleeper publishes the answer: a dynasty league chains year to year under a new
league id via ``previous_league_id``, and every link carries its own ``season``
and its own ``scoring_settings``.

THE PROPERTY THAT MATTERS
-------------------------
``test_changing_a_later_seasons_card_cannot_move_an_earlier_season`` is the
one the whole module exists for.  Note it is paired with a non-vacuity test:
a resolver that returned nothing, or zeros, would satisfy "the earlier season
did not move" perfectly while being useless.  Both directions are required —
the earlier season must be immovable by a LATER card and movable by its OWN.

Every test here is hermetic: the fetcher is injected, so no network and no
committed live payload.
"""

from __future__ import annotations

import pytest

from src.league_comparison import season_scoring as _ss

# ── A synthetic three-season chain, newest → oldest ───────────────────
#
# The rates differ per season on purpose; that is the whole point.

CHAIN = {
    "L2025": {
        "league_id": "L2025",
        "season": "2025",
        "previous_league_id": "L2024",
        "scoring_settings": {"rec": 1.0, "rec_yd": 0.1, "pass_td": 4.0},
    },
    "L2024": {
        "league_id": "L2024",
        "season": "2024",
        "previous_league_id": "L2023",
        "scoring_settings": {"rec": 0.5, "rec_yd": 0.1, "pass_td": 4.0},
    },
    "L2023": {
        "league_id": "L2023",
        "season": "2023",
        "previous_league_id": "",
        "scoring_settings": {"rec": 0.0, "rec_yd": 0.1, "pass_td": 6.0},
    },
}


def _fetcher(chain):
    def fetch(league_id):
        return chain.get(str(league_id))

    return fetch


def _score(stat_line, settings):
    """The dot product the real scorer performs, in one line.

    Deliberately not importing the production scorer: this file is about
    WHICH card is chosen, and pinning that against a second moving part
    would make a scorer change look like a resolver regression.
    """
    return sum(float(v) * float(settings.get(k, 0.0)) for k, v in stat_line.items())


# ── resolution ───────────────────────────────────────────────────────


def test_each_season_resolves_to_its_own_card():
    chain = _ss.resolve_season_cards("L2025", [2023, 2024, 2025], fetcher=_fetcher(CHAIN))
    assert chain.settings_for(2025)["rec"] == 1.0
    assert chain.settings_for(2024)["rec"] == 0.5
    assert chain.settings_for(2023)["rec"] == 0.0
    assert chain.settings_for(2023)["pass_td"] == 6.0
    assert not chain.unresolved


def test_seasons_are_indexed_by_their_own_season_field_not_walk_position():
    """A chain that skips a year must not shift every earlier card by one."""
    gapped = {
        "A": {"season": "2025", "previous_league_id": "B", "scoring_settings": {"rec": 1.0}},
        # 2024 does not exist; the chain jumps straight to 2023.
        "B": {"season": "2023", "previous_league_id": "", "scoring_settings": {"rec": 0.25}},
    }
    chain = _ss.resolve_season_cards("A", [2023, 2024, 2025], fetcher=_fetcher(gapped))
    assert chain.settings_for(2025)["rec"] == 1.0
    assert chain.settings_for(2023)["rec"] == 0.25
    assert chain.card_for(2024) is None
    assert chain.unresolved[2024] == _ss.REASON_NOT_IN_CHAIN


# ── the property the audit asked for ─────────────────────────────────


def test_changing_a_later_seasons_card_cannot_move_an_earlier_season():
    """Rewrite 2025's rules entirely; 2023's points must be byte-identical.

    This is the regression that proves as-of correctness. Under the old
    behaviour — one card applied to every season — it fails outright,
    because 2023 WAS 2025's card.
    """
    line = {"rec": 8, "rec_yd": 92, "pass_td": 1}

    before = _ss.resolve_season_cards("L2025", [2023], fetcher=_fetcher(CHAIN))
    points_before = _score(line, before.settings_for(2023))

    mutated = {k: dict(v) for k, v in CHAIN.items()}
    mutated["L2025"]["scoring_settings"] = {"rec": 99.0, "rec_yd": 9.9, "pass_td": 99.0}
    mutated["L2024"]["scoring_settings"] = {"rec": 42.0, "rec_yd": 4.2, "pass_td": 42.0}

    after = _ss.resolve_season_cards("L2025", [2023], fetcher=_fetcher(mutated))
    points_after = _score(line, after.settings_for(2023))

    assert points_after == points_before
    assert after.settings_for(2023) == CHAIN["L2023"]["scoring_settings"]


def test_the_earlier_season_IS_moved_by_its_own_card():
    """Non-vacuity for the test above.

    A resolver that returned nothing, or an all-zero card, would pass
    "the earlier season did not move" perfectly and be worthless.  2023's
    points must respond to 2023's rules.
    """
    line = {"rec": 8, "rec_yd": 92, "pass_td": 1}
    base = _ss.resolve_season_cards("L2025", [2023], fetcher=_fetcher(CHAIN))
    baseline = _score(line, base.settings_for(2023))
    assert baseline > 0, "a real stat line under a real card must score something"

    mutated = {k: dict(v) for k, v in CHAIN.items()}
    mutated["L2023"]["scoring_settings"] = {"rec": 1.0, "rec_yd": 0.1, "pass_td": 6.0}
    moved = _ss.resolve_season_cards("L2025", [2023], fetcher=_fetcher(mutated))
    assert _score(line, moved.settings_for(2023)) != baseline


def test_two_seasons_of_the_same_stat_line_score_differently():
    """The observable consequence, stated directly: identical production in
    2023 and 2025 is not worth the same, because the league changed."""
    line = {"rec": 8, "rec_yd": 92, "pass_td": 1}
    chain = _ss.resolve_season_cards("L2025", [2023, 2025], fetcher=_fetcher(CHAIN))
    assert _score(line, chain.settings_for(2025)) != _score(line, chain.settings_for(2023))


# ── fail closed ──────────────────────────────────────────────────────


def test_a_season_before_the_league_existed_is_unresolved_not_substituted():
    chain = _ss.resolve_season_cards("L2025", [2019], fetcher=_fetcher(CHAIN))
    assert chain.card_for(2019) is None
    assert chain.settings_for(2019) is None
    assert chain.unresolved[2019] == _ss.REASON_NOT_IN_CHAIN


def test_a_broken_chain_does_not_fall_back_to_todays_card():
    """The failure mode this module removes: a fetch dies mid-walk and the
    remaining seasons quietly inherit the current rules."""

    def exploding(league_id):
        if league_id == "L2025":
            return CHAIN["L2025"]
        raise OSError("network down")

    chain = _ss.resolve_season_cards("L2025", [2023, 2024, 2025], fetcher=exploding)
    assert chain.settings_for(2025)["rec"] == 1.0
    for season in (2023, 2024):
        assert chain.card_for(season) is None
        assert season in chain.unresolved


def test_an_empty_card_is_unresolved_rather_than_an_empty_ruleset():
    """A league object with `scoring_settings: {}` means we do not know the
    rules, not that every rule pays zero — the difference is every point on
    the board."""
    empty = {
        "A": {"season": "2025", "previous_league_id": "", "scoring_settings": {}},
    }
    chain = _ss.resolve_season_cards("A", [2025], fetcher=_fetcher(empty))
    assert chain.card_for(2025) is None
    assert chain.unresolved[2025] == _ss.REASON_NO_CARD


def test_every_requested_season_lands_in_exactly_one_bucket():
    """Nothing may be silently dropped: a caller reading only `cards` must be
    able to see, from `unresolved`, what it is not being told."""
    requested = [2019, 2023, 2024, 2025, 2030]
    chain = _ss.resolve_season_cards("L2025", requested, fetcher=_fetcher(CHAIN))
    assert set(chain.cards) | set(chain.unresolved) == set(requested)
    assert not (set(chain.cards) & set(chain.unresolved))


# ── walk safety ──────────────────────────────────────────────────────


def test_a_cyclic_chain_terminates():
    cyclic = {
        "A": {"season": "2025", "previous_league_id": "B", "scoring_settings": {"rec": 1.0}},
        "B": {"season": "2024", "previous_league_id": "A", "scoring_settings": {"rec": 0.5}},
    }
    chain = _ss.resolve_season_cards("A", [2024, 2025], fetcher=_fetcher(cyclic))
    assert chain.settings_for(2025)["rec"] == 1.0
    assert chain.settings_for(2024)["rec"] == 0.5


def test_the_walk_is_bounded():
    """A very long or malformed chain must not walk forever."""
    calls: list[str] = []

    def endless(league_id):
        calls.append(league_id)
        n = int(league_id)
        return {
            "season": str(2025 - n),
            "previous_league_id": str(n + 1),
            "scoring_settings": {"rec": 1.0},
        }

    _ss.resolve_season_cards("0", [2025], max_hops=5, fetcher=endless)
    assert len(calls) == 5


def test_a_repeated_season_keeps_the_nearer_league():
    """A malformed chain that repeats a season resolves to the league the
    manager is actually playing in, not the older duplicate."""
    dupe = {
        "NEW": {"season": "2025", "previous_league_id": "OLD", "scoring_settings": {"rec": 1.0}},
        "OLD": {"season": "2025", "previous_league_id": "", "scoring_settings": {"rec": 0.1}},
    }
    chain = _ss.resolve_season_cards("NEW", [2025], fetcher=_fetcher(dupe))
    assert chain.card_for(2025).league_id == "NEW"
    assert chain.settings_for(2025)["rec"] == 1.0


def test_no_league_id_is_unresolved_not_a_crash():
    chain = _ss.resolve_season_cards("", [2024], fetcher=_fetcher(CHAIN))
    assert chain.card_for(2024) is None
    assert 2024 in chain.unresolved


def test_the_chain_serialises_for_provenance():
    chain = _ss.resolve_season_cards("L2025", [2019, 2025], fetcher=_fetcher(CHAIN))
    doc = chain.to_dict()
    assert doc["seasons"]["2025"]["leagueId"] == "L2025"
    assert doc["unresolved"]["2019"] == _ss.REASON_NOT_IN_CHAIN
    # The card's rates are NOT serialised — this is provenance, not a
    # second copy of the scoring config for something to drift from.
    assert "scoringSettings" not in doc["seasons"]["2025"]


@pytest.mark.parametrize("bad", [None, "", "not-a-season"])
def test_a_hop_without_a_usable_season_is_skipped_not_guessed(bad):
    broken = {
        "A": {"season": "2025", "previous_league_id": "B", "scoring_settings": {"rec": 1.0}},
        "B": {"season": bad, "previous_league_id": "", "scoring_settings": {"rec": 0.5}},
    }
    chain = _ss.resolve_season_cards("A", [2024, 2025], fetcher=_fetcher(broken))
    assert chain.settings_for(2025)["rec"] == 1.0
    assert chain.card_for(2024) is None


# ── service wiring: which card actually reached the scorer ────────────


class _Info:
    """Minimal stand-in for LeagueScoringInfo."""

    def __init__(self, league_id, scoring):
        self.league_id = league_id
        self.scoring_settings = scoring


def _rows(season):
    return [
        {
            "player_id": "00-0001",
            "player_display_name": "A Receiver",
            "position": "WR",
            "season": season,
            "week": 1,
            "receptions": 8,
            "receiving_yards": 92,
        }
    ]


def test_the_service_scores_each_season_under_its_own_card(monkeypatch):
    """End-to-end at the seam that had the defect: identical production in
    two seasons must score differently when the league's rules changed."""
    from src.league_comparison import service as _svc

    info = _Info("L2025", CHAIN["L2025"]["scoring_settings"])
    chain = _ss.resolve_season_cards("L2025", [2023, 2025], fetcher=_fetcher(CHAIN))
    block = _svc._build_league_block(
        info,
        {2023: _rows(2023), 2025: _rows(2025)},
        {"WR": 5, "FLEX": 5},
        chain,
    )
    got_2023 = block["perSeason"]["2023"]
    got_2025 = block["perSeason"]["2025"]
    assert got_2023["cardBasis"] == "season_card"
    assert got_2025["cardBasis"] == "season_card"
    # 2023 pays rec 0.0, 2025 pays rec 1.0 — same 8 catches, different points.
    assert got_2023["topPlayers"][0]["totalPoints"] != got_2025["topPlayers"][0]["totalPoints"]


def test_an_unresolved_season_is_excluded_not_scored_with_todays_card():
    from src.league_comparison import service as _svc

    info = _Info("L2025", CHAIN["L2025"]["scoring_settings"])
    chain = _ss.resolve_season_cards("L2025", [2019, 2025], fetcher=_fetcher(CHAIN))
    block = _svc._build_league_block(
        info, {2019: _rows(2019), 2025: _rows(2025)}, {"WR": 5, "FLEX": 5}, chain
    )
    assert block["perSeason"]["2019"]["available"] is False
    assert block["perSeason"]["2019"]["unavailableReason"] == "scoring_card_unresolved"
    assert block["perSeason"]["2025"]["available"] is not False


def test_no_chain_falls_back_but_says_so():
    """Degradation must be labelled.  Blanking the whole comparison on a
    transient outage would be worse than a weaker number — but an unlabelled
    weaker number is exactly the silence this work removes."""
    from src.league_comparison import service as _svc

    info = _Info("L2025", CHAIN["L2025"]["scoring_settings"])
    block = _svc._build_league_block(info, {2023: _rows(2023)}, {"WR": 5, "FLEX": 5}, None)
    assert block["perSeason"]["2023"]["cardBasis"] == "current_card_unverified"


def test_a_totally_failed_walk_degrades_rather_than_blanking(monkeypatch):
    """The walker degrades internally, so an empty map is indistinguishable
    from 'no network' — it must not be treated as authoritative absence."""
    from src.league_comparison import service as _svc

    monkeypatch.setattr(
        _svc._season_scoring,
        "resolve_season_cards",
        lambda lid, seasons, **kw: _ss.SeasonScoringChain(
            start_league_id=lid, unresolved={s: _ss.REASON_FETCH_FAILED for s in seasons}
        ),
    )
    assert _svc._resolve_season_cards_or_none("L2025", [2023, 2025]) is None


def test_a_partially_resolved_walk_is_trusted():
    """Non-vacuity for the rule above: once ANY card resolves, the chain's
    gaps are real and must be honoured."""
    from src.league_comparison import service as _svc

    import src.league_comparison.season_scoring as real

    original = real.resolve_season_cards
    try:
        real.resolve_season_cards = lambda lid, seasons, **kw: original(
            lid, seasons, fetcher=_fetcher(CHAIN), **kw
        )
        chain = _svc._resolve_season_cards_or_none("L2025", [2019, 2025])
    finally:
        real.resolve_season_cards = original
    assert chain is not None
    assert 2019 in chain.unresolved
    assert chain.card_for(2025) is not None
