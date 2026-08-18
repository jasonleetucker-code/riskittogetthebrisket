"""#802 — the ten scoring rules only play-by-play can supply.

WHY THIS FILE EXISTS
--------------------
``dynasty_main``'s card pays six reception-depth bands, three player
special-teams rules and a pick-six penalty. None of them is a column on
the nflverse WEEKLY feed, so ``compute_weekly_points`` scored them at
nothing and ``scoring_coverage`` called them UNSCORABLE — which was true
of that feed and false of the world. Measured on the league host's own
week-14 2025 dump: 451.53 points in one week, roughly 7,676 a season,
about two thirds of it the reception bands.

The predicates below are not designed, they are MEASURED. Every one was
reconciled against Sleeper's own weekly stat dumps for 2025 REG weeks 1,
3, 5, 8, 11, 14 and 17 before it was written down, and the reconciliation
for week 14 runs here as a test rather than living in a report:

    key            derived   host   weeks exact
    rec_0_4            870    870          7/7
    rec_5_9           1474   1474          7/7
    rec_10_19         1258   1258          7/7
    rec_20_29          374    374          7/7
    rec_30_39          135    135          7/7
    rec_40p             78     78          7/7
    st_ff               10     10          7/7
    st_fum_rec           8      8          7/7
    pass_int_td         12     12          7/7
    st_tkl_solo        758    759          6/7

Fixtures: ``tests/nfl_data/fixtures/pbp_2025_wk14_slice.csv`` (every
2025 REG week-14 play, pruned to the columns the producer reads) and
``docs/master-site-audit/evidence/W18/sleeper_stats_2025_wk14.json`` (the
host's own answer). Deterministic, committed, offline — no live board and
no network, per the repo's CI rule for the hard gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.nfl_data.pbp_weekly import (
    PbpWeeklyStats,
    SeasonPbpIndex,
    accumulate_weekly,
    attach_supplement,
    gsis_of_row,
    load_pbp_weekly,
    persist_pbp_weekly,
)
from src.nfl_data.realized_points import PBP_SUPPLEMENT_KEYS, PBP_SUPPLEMENT_ROW_KEY

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "master-site-audit" / "evidence" / "W18"
SLICE = FIXTURES / "pbp_2025_wk14_slice.csv"
HOST_WK14 = EVIDENCE / "sleeper_stats_2025_wk14.json"

BAND_KEYS = ("rec_0_4", "rec_5_9", "rec_10_19", "rec_20_29", "rec_30_39", "rec_40p")


@pytest.fixture(scope="module")
def derived():
    with SLICE.open("r", encoding="utf-8", newline="") as fh:
        by_player, weeks = accumulate_weekly(fh)
    return by_player, weeks


@pytest.fixture(scope="module")
def host_players():
    """The host's week-14 line, PLAYER entries only.

    Sleeper keys players by numeric id and team defenses by alpha team
    code, and several of these keys (``st_tkl_solo``, ``kr_yd``) appear on
    BOTH — one name, two meanings. Filtering here is the same rule
    ``realized_points.is_host_player_entry`` enforces in production.
    """
    raw = json.loads(HOST_WK14.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if k.replace("-", "").isdigit()}


def _host_total(host_players, key):
    return sum(float(v.get(key, 0) or 0) for v in host_players.values())


def _host_player_count(host_players, key):
    return sum(1 for v in host_players.values() if float(v.get(key, 0) or 0))


def _derived_total(by_player, key, week=14):
    return sum(float(w.get(week, {}).get(key, 0) or 0) for w in by_player.values())


def _derived_player_count(by_player, key, week=14):
    return sum(1 for w in by_player.values() if float(w.get(week, {}).get(key, 0) or 0))


# ── Host truth ───────────────────────────────────────────────────────


@pytest.mark.parametrize("key", sorted(PBP_SUPPLEMENT_KEYS))
def test_every_derived_key_matches_the_host_for_week_14(derived, host_players, key):
    """The whole justification for this module in one assertion.

    A predicate that is merely plausible is worth nothing here: each of
    these rules pays real points to assets this board ranks, and an
    approximation would be indistinguishable from the silent zero it
    replaces.
    """
    by_player, _weeks = derived
    assert _derived_total(by_player, key) == _host_total(host_players, key), key


@pytest.mark.parametrize("key", BAND_KEYS)
def test_the_bands_match_the_host_player_for_player_by_count(derived, host_players, key):
    """Totals can agree while individuals do not — this pins the shape.

    Player COUNT rather than a per-player join because Sleeper publishes a
    GSIS id for only 3,893 of its 12,221 player records, so a name-based
    join would be asserting the quality of the join and not the producer.
    """
    by_player, _weeks = derived
    assert _derived_player_count(by_player, key) == _host_player_count(host_players, key), key


def test_the_host_counts_a_negative_catch_as_a_reception_with_no_band(derived, host_players):
    """The one judgement call in the mapping, settled by measurement.

    Play-by-play has 537 completed passes in this week and the host
    reports ``rec`` 537 — so a lost-yardage catch IS a reception. Its
    bands total 523. The 14 missing are exactly the week's negative-yard
    receptions, and putting them in ``rec_0_4`` (the reading this repo
    shipped until 2026-08-18) would pay a band the host does not pay.
    """
    by_player, _weeks = derived
    banded = sum(_derived_total(by_player, k) for k in BAND_KEYS)
    host_banded = sum(_host_total(host_players, k) for k in BAND_KEYS)
    host_receptions = _host_total(host_players, "rec")

    assert banded == host_banded == 523.0
    assert host_receptions == 537.0
    assert host_receptions - host_banded == 14.0


def test_no_team_defence_leaks_into_the_derived_stats(derived):
    """Play-by-play credits PLAYERS, so this cannot regress by accident —
    but ``st_tkl_solo`` and ``kr_yd`` exist on both sides of the host's
    line, and asserting the id shape here is what keeps a future change
    from introducing a team row."""
    by_player, _weeks = derived
    assert all(gsis.startswith("00-") for gsis in by_player)


# ── The predicates that needed a constraint ──────────────────────────


def _csv(header, *rows):
    lines = [",".join(header)]
    lines.extend(",".join(str(c) for c in row) for row in rows)
    return lines


_MIN_HEADER = (
    "week,season_type,complete_pass,receiver_player_id,receiving_yards,yards_gained,"
    "special_teams_play,solo_tackle_1_player_id,solo_tackle_2_player_id,"
    "tackle_with_assist_1_player_id,tackle_with_assist_2_player_id,"
    "forced_fumble_player_1_player_id,forced_fumble_player_2_player_id,"
    "fumble_recovery_1_player_id,fumble_recovery_1_team,fumbled_1_team,"
    "fumble_recovery_2_player_id,fumble_recovery_2_team,fumbled_2_team,"
    "interception,return_touchdown,passer_player_id,posteam,td_team"
).split(",")


def _play(**kw):
    row = dict.fromkeys(_MIN_HEADER, "")
    row["week"] = kw.pop("week", 1)
    row["season_type"] = kw.pop("season_type", "REG")
    row.update(kw)
    return [row[c] for c in _MIN_HEADER]


def _accumulate(*plays):
    by_player, weeks = accumulate_weekly(_csv(_MIN_HEADER, *plays))
    return by_player, weeks


def test_recovering_your_own_special_teams_fumble_is_not_st_fum_rec():
    """The constraint IS the rule. Counting every recovery scores 20
    events against the host's 8 over the sampled weeks, because a muffed
    punt the kicking team's own returner falls on is not a takeaway."""
    by_player, _ = _accumulate(
        _play(
            special_teams_play=1,
            fumble_recovery_1_player_id="00-own",
            fumble_recovery_1_team="KC",
            fumbled_1_team="KC",
        ),
        _play(
            special_teams_play=1,
            fumble_recovery_1_player_id="00-opp",
            fumble_recovery_1_team="KC",
            fumbled_1_team="JAX",
        ),
    )
    assert "00-own" not in by_player
    assert by_player["00-opp"][1]["st_fum_rec"] == 1.0


def test_an_unknown_fumbling_team_is_not_credited():
    """Missing is never a takeaway: with no fumbling team on the row the
    opponent test cannot be evaluated, and inventing the answer is what
    would put points on a board."""
    by_player, _ = _accumulate(
        _play(
            special_teams_play=1,
            fumble_recovery_1_player_id="00-x",
            fumble_recovery_1_team="KC",
        )
    )
    assert by_player == {}


def test_a_returned_interception_the_offence_scores_on_is_not_a_pick_six():
    """Real play, 2025 week 5: Cam Ward's interception was fumbled back on
    the return and Tennessee recovered it in the end zone.
    ``return_touchdown`` is 1 and the quarterback conceded nothing. Without
    the ``td_team != posteam`` clause he is charged -2 points."""
    by_player, _ = _accumulate(
        _play(
            interception=1,
            return_touchdown=1,
            passer_player_id="00-qb",
            posteam="TEN",
            td_team="TEN",
        ),
        _play(
            interception=1,
            return_touchdown=1,
            passer_player_id="00-qb2",
            posteam="KC",
            td_team="JAX",
        ),
    )
    assert "00-qb" not in by_player
    assert by_player["00-qb2"][1]["pass_int_td"] == 1.0


def test_special_teams_rules_do_not_fire_on_a_scrimmage_play():
    by_player, _ = _accumulate(
        _play(solo_tackle_1_player_id="00-lb", forced_fumble_player_1_player_id="00-lb"),
    )
    assert by_player == {}


def test_a_tackle_with_assist_on_a_special_teams_play_counts_as_solo():
    """Measured, not assumed: solo-only lands 748 of 759 over the seven
    sampled weeks and adding these columns lands 758, exact in six of the
    seven."""
    by_player, _ = _accumulate(
        _play(
            special_teams_play=1,
            solo_tackle_1_player_id="00-a",
            tackle_with_assist_1_player_id="00-b",
            tackle_with_assist_2_player_id="00-c",
        )
    )
    assert by_player["00-a"][1]["st_tkl_solo"] == 1.0
    assert by_player["00-b"][1]["st_tkl_solo"] == 1.0
    assert by_player["00-c"][1]["st_tkl_solo"] == 1.0


def test_only_regular_season_plays_are_accumulated_by_default():
    by_player, weeks = _accumulate(
        _play(
            week=20,
            season_type="POST",
            complete_pass=1,
            receiver_player_id="00-w",
            receiving_yards=12,
        ),
        _play(week=3, complete_pass=1, receiver_player_id="00-w", receiving_yards=12),
    )
    assert weeks == {3}
    assert set(by_player["00-w"]) == {3}


def test_a_renamed_column_raises_rather_than_reading_as_no_plays():
    """The 2025 weekly-stats rename went unnoticed for a season because a
    missing column and a stat that never happened look identical (#589).
    Here they must not."""
    header = [c for c in _MIN_HEADER if c != "special_teams_play"]
    with pytest.raises(ValueError, match="missing expected columns"):
        accumulate_weekly([",".join(header), ",".join([""] * len(header))])


# ── Missing is never zero ────────────────────────────────────────────


def test_an_uncovered_week_is_unknown_and_a_covered_one_is_zero():
    stats = PbpWeeklyStats(2025, {"00-a": {4: {"rec_0_4": 2.0}}}, [1, 2, 3, 4])
    assert stats.stats_for("00-a", 4) == {"rec_0_4": 2.0}
    assert stats.stats_for("00-b", 4) == {}, "covered week, no events — a real zero"
    assert stats.stats_for("00-a", 9) is None, "week never streamed — unknown"
    assert stats.stats_for("", 4) is None


@pytest.mark.parametrize(
    "row,stats_present,expected",
    [
        ({"player_id": "00-a", "week": 4}, True, {"rec_0_4": 2.0}),
        ({"player_id": "00-b", "week": 4}, True, {}),
        ({"player_id": "00-a", "week": 9}, True, None),
        ({"player_id": "00-a", "week": 4}, False, None),
        ({"week": 4}, True, None),
    ],
)
def test_attach_supplement_only_speaks_when_it_knows(row, stats_present, expected):
    stats = PbpWeeklyStats(2025, {"00-a": {4: {"rec_0_4": 2.0}}}, [1, 2, 3, 4])
    out = attach_supplement(row, stats if stats_present else None)
    assert out.get(PBP_SUPPLEMENT_ROW_KEY) == expected


def test_attach_supplement_does_not_mutate_the_caller_s_row():
    """Callers iterate rows they do not own — a cached nflverse frame, a
    shared fixture — and a stat row that quietly grew a key is the
    shared-mutable-global failure this repo has already had to repair."""
    stats = PbpWeeklyStats(2025, {"00-a": {4: {"rec_0_4": 2.0}}}, [4])
    row = {"player_id": "00-a", "week": 4}
    attach_supplement(row, stats)
    assert PBP_SUPPLEMENT_ROW_KEY not in row


def test_gsis_is_read_from_every_spelling_the_pipeline_uses():
    assert gsis_of_row({"player_id": "00-a"}) == "00-a"
    assert gsis_of_row({"player_id_gsis": "00-b"}) == "00-b"
    assert gsis_of_row({"gsis_id": "00-c"}) == "00-c"
    assert gsis_of_row({}) == ""


# ── Persistence ──────────────────────────────────────────────────────


def test_a_persisted_season_round_trips_through_the_loader(tmp_path):
    def lines(_season):
        with SLICE.open("r", encoding="utf-8", newline="") as fh:
            return list(fh)

    result = persist_pbp_weekly([2025], out_dir=tmp_path, _line_source=lines)
    assert result["seasons"] == [2025]

    payload = load_pbp_weekly(2025, out_dir=tmp_path)
    assert payload["weeksCovered"] == [14]
    assert sorted(payload["statKeys"]) == sorted(PBP_SUPPLEMENT_KEYS)

    stats = PbpWeeklyStats.from_payload(payload)
    with SLICE.open("r", encoding="utf-8", newline="") as fh:
        by_player, _weeks = accumulate_weekly(fh)
    for gsis, weeks in by_player.items():
        assert stats.stats_for(gsis, 14) == weeks[14]


def test_a_season_that_was_never_built_is_missing_not_empty(tmp_path):
    index = SeasonPbpIndex(out_dir=tmp_path)
    assert index.for_season(2019) is None
    assert index.seasons_missing == (2019,)
    assert PBP_SUPPLEMENT_ROW_KEY not in index.attach(
        {"player_id": "00-a", "season": 2019, "week": 1}
    )
