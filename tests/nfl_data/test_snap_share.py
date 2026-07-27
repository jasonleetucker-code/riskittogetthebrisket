"""Snap share, and the ID join it depends on.

nflverse's snap-count release keys on `pfr_player_id`; every durable
artifact in this repo keys on GSIS. The cross-walk between them is the
whole problem, and the failure mode worth guarding is silent: an
unjoinable snap row is real playing time that simply disappears, and a
coverage figure computed after the drop reads as completeness.

So the load-bearing tests here are the ones asserting that unjoined rows
are COUNTED, and that a totally broken cross-walk writes nothing rather
than a confident-looking partial file.
"""

from __future__ import annotations

from src.nfl_data.snap_share import (
    MIN_GAMES,
    build_pfr_to_gsis,
    load_snap_share,
    persist_snap_share,
)

_ID_MAP = [
    {"gsis_id": "00-0036322", "pfr_id": "ChasJa00"},
    {"gsis_id": "00-0034796", "pfr_id": "SmitDe00"},
    # Rows that cannot participate in the join at all.
    {"gsis_id": "00-0099999", "pfr_id": ""},
    {"gsis_id": "", "pfr_id": "OrphAn00"},
]


def _snap(pfr, week, *, off=0.9, dfn=0.0, name="A Player", pos="WR", gt="REG"):
    return {
        "season": 2025,
        "week": week,
        "game_type": gt,
        "player": name,
        "pfr_player_id": pfr,
        "position": pos,
        "offense_snaps": int(round(off * 70)),
        "offense_pct": off,
        "defense_snaps": int(round(dfn * 70)),
        "defense_pct": dfn,
    }


def _providers(rows, id_map=None):
    return {
        "_snap_provider": lambda _s: rows,
        "_id_map_provider": lambda: (_ID_MAP if id_map is None else id_map),
    }


# ── The cross-walk ───────────────────────────────────────────────────


def test_the_crosswalk_skips_rows_missing_either_identifier():
    """A row with only one id cannot join. Including it with an empty
    key would produce an entry that silently matches nothing."""
    mapping = build_pfr_to_gsis(_ID_MAP)
    assert mapping == {"ChasJa00": "00-0036322", "SmitDe00": "00-0034796"}
    assert "" not in mapping


def test_an_empty_crosswalk_writes_nothing(tmp_path):
    """Every snap row would be unjoinable. A file built from that would
    be empty and indistinguishable from a season nobody played."""
    result = persist_snap_share(
        [2025], snap_dir=tmp_path, **_providers([_snap("ChasJa00", 1)], id_map=[])
    )
    assert result.seasons == []
    assert load_snap_share(2025, snap_dir=tmp_path) is None


# ── Unjoined rows are counted, not dropped ───────────────────────────


def test_unjoinable_rows_are_counted(tmp_path):
    """THE ASSERTION THAT MATTERS. These are real snaps this repo cannot
    attribute; dropping them silently would make coverage look total."""
    rows = [
        _snap("ChasJa00", 1),
        _snap("NoSuchId00", 1, name="Ghost"),
        _snap("NoSuchId00", 2, name="Ghost"),
    ]
    result = persist_snap_share([2025], snap_dir=tmp_path, **_providers(rows))
    assert result.unjoined_rows == 2
    assert result.to_dict()["unjoinedPlayers"] == 1
    assert result.players == 1
    # And it survives into the persisted file, not just the return value.
    assert load_snap_share(2025, snap_dir=tmp_path)["unjoinedRows"] == 2


# ── Aggregation ──────────────────────────────────────────────────────


def test_weekly_series_and_season_mean_are_both_kept(tmp_path):
    """The mean says whether he is a starter; the series says whether he
    is becoming one. The second is the one with trade value."""
    rows = [_snap("ChasJa00", w, off=0.5 + 0.1 * w) for w in range(1, 5)]
    persist_snap_share([2025], snap_dir=tmp_path, **_providers(rows))
    rec = load_snap_share(2025, snap_dir=tmp_path)["players"]["00-0036322"]
    assert rec["games"] == 4
    assert sorted(rec["weeks"]) == ["1", "2", "3", "4"]
    assert rec["weeks"]["4"]["offensePct"] == 0.9
    assert rec["offensePctMean"] == 0.75


def test_offense_and_defense_shares_stay_separate(tmp_path):
    """Summing a two-way player's shares would exceed 1.0 and describe
    nobody."""
    rows = [_snap("ChasJa00", 1, off=0.8, dfn=0.6, pos="WR")]
    persist_snap_share([2025], snap_dir=tmp_path, **_providers(rows))
    rec = load_snap_share(2025, snap_dir=tmp_path)["players"]["00-0036322"]
    assert rec["offensePctMean"] == 0.8
    assert rec["defensePctMean"] == 0.6


def test_a_thin_sample_is_flagged_rather_than_hidden(tmp_path):
    """A mean over two games is not a role. The number is still served;
    the claim about it is not."""
    thin = [_snap("ChasJa00", w) for w in range(1, MIN_GAMES)]
    persist_snap_share([2025], snap_dir=tmp_path, **_providers(thin))
    rec = load_snap_share(2025, snap_dir=tmp_path)["players"]["00-0036322"]
    assert rec["meanIsReliable"] is False

    full = [_snap("SmitDe00", w) for w in range(1, MIN_GAMES + 1)]
    persist_snap_share([2025], snap_dir=tmp_path, **_providers(full))
    rec2 = load_snap_share(2025, snap_dir=tmp_path)["players"]["00-0034796"]
    assert rec2["meanIsReliable"] is True


def test_zero_snap_weeks_do_not_drag_the_mean(tmp_path):
    """A healthy scratch is a zero-snap week. Averaging it in would
    report a starter as a rotational player."""
    rows = [_snap("ChasJa00", 1, off=0.9), _snap("ChasJa00", 2, off=0.0)]
    persist_snap_share([2025], snap_dir=tmp_path, **_providers(rows))
    rec = load_snap_share(2025, snap_dir=tmp_path)["players"]["00-0036322"]
    assert rec["offensePctMean"] == 0.9
    assert rec["games"] == 2  # the week is still recorded


def test_postseason_is_excluded_by_default(tmp_path):
    rows = [_snap("ChasJa00", 1), _snap("ChasJa00", 20, gt="POST")]
    persist_snap_share([2025], snap_dir=tmp_path, **_providers(rows))
    rec = load_snap_share(2025, snap_dir=tmp_path)["players"]["00-0036322"]
    assert rec["games"] == 1


def test_rerunning_replaces_the_season(tmp_path):
    persist_snap_share([2025], snap_dir=tmp_path, **_providers([_snap("ChasJa00", 1)]))
    persist_snap_share(
        [2025],
        snap_dir=tmp_path,
        **_providers([_snap("ChasJa00", 1), _snap("ChasJa00", 2)]),
    )
    from src.nfl_data.snap_share import snap_path

    text = snap_path(2025, snap_dir=tmp_path).read_text(encoding="utf-8").strip()
    assert len(text.splitlines()) == 1
    assert load_snap_share(2025, snap_dir=tmp_path)["players"]["00-0036322"]["games"] == 2


def test_load_of_a_missing_season_is_none(tmp_path):
    assert load_snap_share(1999, snap_dir=tmp_path) is None
