"""The reconstructed baseline spans seasons, so it needs per-season rules.

``realized_ppg_history`` applied ONE scoring card to every season in its
window (2021-2025 for the shipped baseline).  For a league that changed its
rules that rewrites each prior year under rules nobody played — and the
baseline is what BDVM's fundamental values are built on, so the error
propagates into every priced player.

The same property the league-comparison resolver is pinned on applies here:
changing a later season's card must not move an earlier season's PPG.
"""

from __future__ import annotations

from src.bdvm.baseline import realized_ppg_history

CARDS = {
    2023: {"rec": 0.0, "rec_yd": 0.1},
    2024: {"rec": 0.5, "rec_yd": 0.1},
    2025: {"rec": 1.0, "rec_yd": 0.1},
}


def _rows():
    out = []
    for season in (2023, 2024, 2025):
        out.append(
            {
                "player_display_name": "A Receiver",
                "position": "WR",
                "season": season,
                "week": 1,
                "season_type": "REG",
                "receptions": 10,
                "receiving_yards": 100,
            }
        )
    return out


def _ppg(history, season):
    _pos, seasons = history["a receiver"]
    for s in seasons:
        if s.season == season:
            return s.ppg
    return None


def _norm(name):
    return str(name).strip().lower()


def test_each_season_uses_its_own_card():
    history = realized_ppg_history(
        _rows(), CARDS[2025], name_normalizer=_norm, scoring_for_season=CARDS.get
    )
    # 10 catches + 100 yards: 2023 pays 10.0, 2024 pays 15.0, 2025 pays 20.0.
    assert _ppg(history, 2023) == 10.0
    assert _ppg(history, 2024) == 15.0
    assert _ppg(history, 2025) == 20.0


def test_changing_a_later_card_cannot_move_an_earlier_season():
    before = realized_ppg_history(
        _rows(), CARDS[2025], name_normalizer=_norm, scoring_for_season=CARDS.get
    )
    mutated = dict(CARDS)
    mutated[2025] = {"rec": 99.0, "rec_yd": 9.9}
    after = realized_ppg_history(
        _rows(), mutated[2025], name_normalizer=_norm, scoring_for_season=mutated.get
    )
    assert _ppg(after, 2023) == _ppg(before, 2023)
    assert _ppg(after, 2025) != _ppg(before, 2025)  # non-vacuity


def test_an_unknown_season_is_dropped_not_scored_under_a_neighbour():
    partial = {2025: CARDS[2025]}
    history = realized_ppg_history(
        _rows(), CARDS[2025], name_normalizer=_norm, scoring_for_season=partial.get
    )
    assert _ppg(history, 2025) == 20.0
    assert _ppg(history, 2023) is None
    assert _ppg(history, 2024) is None


def test_omitting_the_resolver_keeps_the_single_card_behaviour():
    """Back-compat is explicit at the call site, not implicit in here."""
    history = realized_ppg_history(_rows(), CARDS[2025], name_normalizer=_norm)
    assert _ppg(history, 2023) == _ppg(history, 2025) == 20.0
