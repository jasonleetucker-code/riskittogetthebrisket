"""#802 — individual special-teams scoring, and what "unscorable" may mean.

Sleeper's **Special Teams Player** categories are awarded to the individual
RB/WR/TE/DB who made the play, not to a team DST.  They are therefore points
belonging to assets this platform ranks, values and starts, and a league that
pays them is not being scored exactly until they are counted.

Three separate claims are pinned here, because they fail in different ways:

1. **The return family is scored.**  ``kr_yd`` / ``pr_yd`` / ``st_td`` landed
   with B7 / W18-F003 and are guarded here against regression — the nflverse
   feed publishes ``kickoff_return_yards`` / ``punt_return_yards`` /
   ``special_teams_tds`` and the engine reads them.

2. **Blocked kicks were a GAP recorded as impossible.**
   ``UNSCORABLE_REASONS`` said blocked kicks are "not a column on the weekly
   defensive feed" while ``def_punt_blocks`` / ``def_pat_blocks`` /
   ``def_fg_blocks`` were all populated on the feed the engine already reads.
   Measured on 2025 REG: 44 player-weeks, 234.08 points at 5.32/event, in DE,
   DT, SAF and LB.  A rule we can score and do not is a defect; recording it as
   permanently impossible hides the defect instead of reporting it.

3. **"Unscorable" is a property of a SOURCE, not of the universe.**  Every
   remaining reason on the live card is true of nflverse and false of the
   league host: Sleeper's own weekly dump publishes all of them.  A reason
   phrased as universal impossibility is the same silencing failure
   ``NOT_APPLICABLE`` was for ``st_`` — it suppresses the key from the warning
   surface without the limitation being true.

The player/DST separation is load-bearing throughout: ``st_tkl_solo`` and
``kr_yd`` are published under ONE key name on BOTH player and team entries, so
the split cannot be done by key family and must be done by entry kind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.nfl_data.realized_points import compute_weekly_points, sleeper_stat_line_from_row
from src.nfl_data.scoring_coverage import (
    _MAXIMAL_ROW,
    Coverage,
    UNSCORABLE_REASONS,
    audit_scoring_settings,
    classify,
    engine_reads_key,
)

EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "master-site-audit" / "evidence" / "W18"

#: The three nflverse columns that together are a player's blocked kicks.
#: No single column carries the total, which is why this is a SUM and not a
#: first-present candidate list.
BLOCK_COLUMNS = ("def_punt_blocks", "def_pat_blocks", "def_fg_blocks")


@pytest.fixture(scope="module")
def dynasty_main_card() -> dict:
    doc = json.loads(
        (EVIDENCE / "sleeper_league_1312006700437352448.json").read_text(encoding="utf-8")
    )
    return doc.get("scoring_settings") or {}


@pytest.fixture(scope="module")
def host_week() -> dict:
    """Sleeper's own wk14 2025 stat dump — the league host's truth."""
    return json.loads((EVIDENCE / "sleeper_stats_2025_wk14.json").read_text(encoding="utf-8"))


# ── 1. the return family stays scored ────────────────────────────────


@pytest.mark.parametrize("key", ["kr_yd", "pr_yd", "st_td"])
def test_player_return_categories_are_scored(key):
    assert engine_reads_key(key), f"{key} is a player ST rule and must be scored"


def test_return_yards_move_a_real_players_total(dynasty_main_card):
    """A returner's points must change when his return yards do."""
    row = {
        "season": 2025,
        "week": 1,
        "position": "WR",
        "kickoff_return_yards": 105,
        "punt_return_yards": 41,
    }
    with_returns = compute_weekly_points(row, dynasty_main_card, position="WR")
    without = compute_weekly_points(
        {**row, "kickoff_return_yards": 0, "punt_return_yards": 0},
        dynasty_main_card,
        position="WR",
    )
    assert with_returns.fantasy_points > without.fantasy_points
    # 105 * 0.0333.. + 41 * 0.0333.. = 4.8667
    assert with_returns.fantasy_points == pytest.approx(4.8667, abs=1e-3)
    assert without.fantasy_points == 0.0


def test_dst_return_spellings_never_reach_a_player(dynasty_main_card):
    """``def_kr_yd`` / ``def_pr_yd`` are the TEAM rule family.  Scoring them
    on a player would pay one return twice — once to the returner and once
    to his defense."""
    for key in ("def_kr_yd", "def_pr_yd", "def_st_td", "def_st_ff"):
        assert classify(key) is Coverage.NOT_APPLICABLE
        assert not engine_reads_key(key)


# ── 2. blocked kicks ─────────────────────────────────────────────────


def test_blocked_kicks_are_scored():
    """RED until idp_blk_kick is wired.  5.32/event on the live card."""
    assert engine_reads_key("idp_blk_kick"), "idp_blk_kick is paid but not scored"


def test_blocked_kicks_sum_every_block_type():
    """A punt block, a PAT block and a FG block are each one blocked kick.

    First-present candidate resolution would score only the punt block and
    silently drop the other two — 23 of 2025's 44 blocks were field goals,
    the single largest category.
    """
    line = sleeper_stat_line_from_row(
        {
            "season": 2025,
            "week": 1,
            "position": "DE",
            "def_punt_blocks": 1,
            "def_pat_blocks": 1,
            "def_fg_blocks": 1,
        },
        position="DE",
    )
    assert line.get("idp_blk_kick") == 3.0


@pytest.mark.parametrize("column", BLOCK_COLUMNS)
def test_each_block_column_counts_on_its_own(column):
    line = sleeper_stat_line_from_row(
        {"season": 2025, "week": 1, "position": "DT", column: 1}, position="DT"
    )
    assert line.get("idp_blk_kick") == 1.0, f"{column} did not count as a blocked kick"


def test_blocked_kicks_are_idp_scoped():
    """``idp_blk_kick`` is an IDP rule.  A blocked kick by a rostered RB (3 of
    44 in 2025 were by RB/TE/OT) is deliberately not paid by it — the team
    ``blk_kick`` rule is a different family for an asset class this board does
    not value.
    """
    line = sleeper_stat_line_from_row(
        {"season": 2025, "week": 1, "position": "RB", "def_fg_blocks": 1}, position="RB"
    )
    assert "idp_blk_kick" not in line


def test_team_blocked_kick_rule_stays_non_player():
    assert classify("blk_kick") is Coverage.NOT_APPLICABLE


def test_blocked_kicks_are_no_longer_declared_impossible():
    assert (
        "idp_blk_kick" not in UNSCORABLE_REASONS
    ), "idp_blk_kick is scorable from def_punt_blocks/def_pat_blocks/def_fg_blocks"


def test_the_probe_row_can_fire_a_blocked_kick():
    """Non-vacuity: without these columns the new rule reads as a false GAP."""
    for column in BLOCK_COLUMNS:
        assert _MAXIMAL_ROW.get(column), f"{column} missing from the probe row"


# ── 3. unscorable is a statement about a source ──────────────────────


def test_every_unscorable_reason_names_its_limiting_source():
    """A reason that reads as universal impossibility is a false claim when
    another configured source publishes the category."""
    for key, reason in UNSCORABLE_REASONS.items():
        assert any(
            token in reason.lower() for token in ("nflverse", "play-by-play", "sleeper", "host")
        ), f"{key}: reason does not say WHICH source cannot supply it — {reason!r}"


def test_host_published_categories_are_recorded_as_recoverable():
    """The categories the league host publishes must be distinguishable from
    the ones no configured source can supply."""
    from src.nfl_data.scoring_coverage import HOST_PUBLISHED

    for key in ("st_tkl_solo", "st_ff", "rec_0_4", "rec_40p", "pass_int_td"):
        assert key in HOST_PUBLISHED, f"{key} is published by Sleeper but not recorded as such"


def test_host_published_claims_are_true_of_the_host_dump(host_week):
    """Guards the claim against drift: every category we say the host
    publishes must actually appear on a player entry in the host's own dump.
    """
    from src.nfl_data.scoring_coverage import HOST_PUBLISHED

    seen = set()
    for pid, line in host_week.items():
        if not str(pid).isdigit() or not isinstance(line, dict):
            continue
        seen.update(k for k, v in line.items() if v)
    # st_fum_rec had no occurrence in this single week; it is published by the
    # host's schema but did not happen, which is not evidence against it.
    for key in HOST_PUBLISHED - {"st_fum_rec"}:
        assert key in seen, f"{key} claimed host-published but absent from the wk14 dump"


def test_describe_gaps_says_a_host_recoverable_rule_is_recoverable(dynasty_main_card):
    from src.nfl_data.scoring_coverage import describe_gaps

    lines = " ".join(describe_gaps(dynasty_main_card)).lower()
    assert "st_tkl_solo" in lines
    assert (
        "host" in lines or "sleeper" in lines
    ), "the warning surface must say the host can supply these, not merely that we cannot"


# ── the player/DST split, measured on the host's own dump ────────────


def test_shared_name_keys_appear_on_both_player_and_team_entries(host_week):
    """The reason the split cannot be done by key family.

    ``st_tkl_solo`` and ``kr_yd`` are published under one name on player
    entries AND on team entries, where they mean the team's total.  Any
    consumer of the host feed must separate by ENTRY KIND.
    """
    for key in ("st_tkl_solo", "kr_yd"):
        players = sum(
            1
            for pid, ln in host_week.items()
            if str(pid).isdigit() and isinstance(ln, dict) and ln.get(key)
        )
        teams = sum(
            1
            for pid, ln in host_week.items()
            if not str(pid).isdigit() and isinstance(ln, dict) and ln.get(key)
        )
        assert players > 0 and teams > 0, f"{key} no longer spans both entry kinds"


def test_pure_dst_keys_never_appear_on_a_player_entry(host_week):
    """If these ever landed on a player they would double-count against the
    player's own idp_* rule."""
    for key in ("int", "fum_rec", "pts_allow", "def_3_and_out", "safe"):
        offenders = [
            pid
            for pid, ln in host_week.items()
            if str(pid).isdigit() and isinstance(ln, dict) and ln.get(key)
        ]
        assert not offenders, f"{key} appeared on player entries {offenders[:3]}"


def test_the_live_card_still_has_no_gaps(dynasty_main_card):
    audit = audit_scoring_settings(dynasty_main_card)
    assert audit[Coverage.GAP] == {}


# ── the persisted store must be able to HOLD return production ────────


def test_the_persisted_stat_row_can_carry_return_production():
    """Latent, not live — but a schema that cannot represent a category is a
    silent zero waiting for its first consumer.

    Nothing scores from the persisted actuals store today (every
    realized-points consumer passes raw rows), which is the only reason this
    was not already costing points.
    """
    from src.nfl_data.actuals_store import normalize_offensive_row

    row = normalize_offensive_row(
        {
            "player_id": "00-0034796",
            "player_display_name": "Return Man",
            "position": "WR",
            "team": "PHI",
            "season": 2025,
            "week": 3,
            "kickoff_return_yards": 90,
            "punt_return_yards": 22,
            "special_teams_tds": 1,
        }
    )
    assert row is not None, "a returner with only return production was dropped entirely"
    assert row.kickoff_return_yards == 90
    assert row.punt_return_yards == 22
    assert row.special_teams_tds == 1


def test_a_persisted_row_round_trips_through_the_scorer(dynasty_main_card):
    """The store's fields must still be readable by the engine that scores
    them — the point of persisting them at all."""
    from dataclasses import asdict

    from src.nfl_data.actuals_store import normalize_offensive_row

    row = normalize_offensive_row(
        {
            "player_id": "00-0034796",
            "player_display_name": "Return Man",
            "position": "WR",
            "team": "PHI",
            "season": 2025,
            "week": 3,
            "kickoff_return_yards": 105,
            "punt_return_yards": 41,
        }
    )
    rp = compute_weekly_points(
        {**asdict(row), "season": 2025, "week": 3}, dynasty_main_card, position="WR"
    )
    assert rp.fantasy_points == pytest.approx(4.8667, abs=1e-3)
