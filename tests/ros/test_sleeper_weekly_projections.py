"""C5-PROJ-C — Sleeper weekly projections as a WEEKLY-horizon source.

Replayed from a trimmed real capture (2026 week 3, fetched
2026-09-25T00:58Z): 2 rows each for QB/RB/WR/TE/K/DL/LB/DB, one DL+LB
dual-position row, and one no-projection placeholder. No network: every
fetch test injects its transport, and the flag-off test proves the
transport is never called.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.api import feature_flags
from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.league_intel.scorer import score_stat_line
from src.ros import sleeper_weekly_projections as swp
from src.ros.projection_ensemble import combine_ensemble
from src.ros.projection_observations import ProjectionObservationError

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "game_day"
    / "sleeper_projections"
    / "2026_w3_rotowire_sample.json"
)
#: dynasty_main's committed, dated scoring snapshot — read from the repo,
#: never fetched.
DYNASTY_MAIN_CARD = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "league_intel"
    / "sleeper_league_snapshot_2026-07-26.json"
)
OBSERVED_AT = "2026-09-25T00:58:24+00:00"
SMALL_CARD = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "fgm_yds": 0.1,
    "xpm": 1.0,
    "xpmiss": -1.0,
    "idp_tkl_solo": 1.0,
    "idp_sack": 4.0,
}


@pytest.fixture(autouse=True)
def _reset_flags():
    feature_flags.reload()
    yield
    feature_flags.reload()


def _rows() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _batch(card=SMALL_CARD, rows=None, observed_at=OBSERVED_AT):
    return swp.build_weekly_observations(
        _rows() if rows is None else rows,
        season=2026,
        week=3,
        observed_at=observed_at,
        scoring_settings=card,
    )


# ── Parsing, coverage, missing-is-not-zero ───────────────────────────


class TestParse:
    def test_every_requested_position_including_k_and_idp_is_observed(self):
        batch = _batch()
        positions = {p for o in batch.observations for p in o.fantasy_positions}
        assert positions == set(swp.POSITIONS)
        assert len(batch.observations) == 17
        assert {o.horizon for o in batch.observations} == {"WEEKLY"}
        assert {o.game_type for o in batch.observations} == {"WEEKLY"}
        assert {o.provider_family for o in batch.observations} == {"rotowire"}

    def test_placeholder_row_is_refused_not_a_zero_projection(self):
        batch = _batch()
        assert "6462" not in batch.by_player_id()
        assert batch.refused == {"placeholder_no_projection": 1}

    def test_observations_are_keyed_by_sleeper_player_id(self):
        obs = _batch().by_player_id()["4881"]
        assert obs.player_key == "player:4881"
        assert obs.game_id == "202610309"
        assert obs.opponent == "DAL"
        assert obs.observed_at == OBSERVED_AT
        assert obs.provider_updated_at is not None
        assert obs.provider_updated_at.startswith("2026-09-25T00:50:12")

    def test_dual_position_player_carries_both_positions(self):
        obs = _batch().by_player_id()["7627"]
        assert obs.fantasy_positions == ("DL", "LB")
        assert obs.position == "DL"

    def test_a_row_from_another_model_is_refused_not_relabelled(self):
        rows = _rows()
        rows[0]["company"] = "someOtherModel"
        batch = _batch(rows=rows)
        assert batch.refused["model_company_mismatch"] == 1
        assert rows[0]["player_id"] not in batch.by_player_id()

    def test_wrong_week_or_season_rows_are_refused(self):
        rows = _rows()
        rows[0]["week"] = 4
        rows[1]["season"] = "2025"
        batch = _batch(rows=rows)
        assert batch.refused["week_mismatch"] == 1
        assert batch.refused["season_mismatch"] == 1

    def test_unusable_card_is_refused(self):
        with pytest.raises(swp.WeeklyProjectionError):
            _batch(card={})

    def test_naive_observed_at_is_refused(self):
        with pytest.raises(swp.WeeklyProjectionError):
            _batch(observed_at="2026-09-25T00:58:24")


# ── Exact-league scoring ─────────────────────────────────────────────


class TestScoring:
    @pytest.mark.parametrize(
        ("pid", "expected"),
        [
            # QB: 273.55*.04 + 1.65*4 - .46*2 + 52.68*.1 + .34*6
            ("4881", 273.55 * 0.04 + 1.65 * 4.0 - 0.46 * 2.0 + 52.68 * 0.1 + 0.34 * 6.0),
            # K: 72.33*.1 + 2.71 - .13
            ("11533", 72.33 * 0.1 + 2.71 - 0.13),
            # DL: 1.07 solo + .11 sacks * 4
            ("5226", 1.07 + 0.11 * 4.0),
        ],
    )
    def test_points_come_from_the_exact_scorer_under_the_callers_card(self, pid, expected):
        obs = _batch().by_player_id()[pid]
        assert obs.league_scored_points == pytest.approx(expected, abs=1e-9)
        assert (
            obs.league_scored_points
            == score_stat_line(dict(obs.stat_line), SMALL_CARD).total_points
        )

    def test_the_card_decides_the_points_not_a_hardcoded_league(self):
        a = _batch().by_player_id()["9488"]
        b = _batch(card={**SMALL_CARD, "rec": 0.5}).by_player_id()["9488"]
        assert a.league_scored_points - b.league_scored_points == pytest.approx(6.6 * 0.5)
        assert a.scoring_fingerprint == scoring_fingerprint(SMALL_CARD)
        assert b.scoring_fingerprint != a.scoring_fingerprint

    def test_native_total_is_diagnostic_only(self):
        obs = _batch().by_player_id()["5226"]
        assert obs.native_points_ppr == 1.39
        assert obs.league_scored_points != obs.native_points_ppr

    def test_accepts_a_league_intel_config(self):
        from src.league_intel.config import build_config_from_snapshot

        raw = json.loads(DYNASTY_MAIN_CARD.read_text(encoding="utf-8"))
        cfg = build_config_from_snapshot(raw, snapshot_path=DYNASTY_MAIN_CARD)
        via_cfg = _batch(card=cfg).by_player_id()["4881"].league_scored_points
        via_map = _batch(card=raw["scoring_settings"]).by_player_id()["4881"].league_scored_points
        assert via_cfg == via_map


# ── Uncovered categories are named, never silently zero ──────────────


class TestUncovered:
    CARD = {
        **SMALL_CARD,
        "bonus_fd_wr": 1.0,  # provider publishes rec_fd, never bonus_fd_wr
        "kr_yd": 0.03,  # provider publishes def_kr_yd, never kr_yd
        "st_tkl_solo": 1.33,  # special-teams tackles: never projected
        "fgmiss_0_19": -4.0,  # kicker-only; provider has no 0-19 miss key
        "idp_def_td": 6.0,  # IDP-only; provider projects no defensive TD
        "pts_allow_0": 10.0,  # TEAM defense — no individual player earns it
        "rec_fd": 0.0,  # zero-rate: never a gap
    }

    def test_wr_gaps(self):
        obs = _batch(card=self.CARD).by_player_id()["9488"]
        assert obs.uncovered_scoring_keys == ("bonus_fd_wr", "kr_yd", "st_tkl_solo")

    def test_kicker_gaps_include_kicker_only_keys(self):
        obs = _batch(card=self.CARD).by_player_id()["11533"]
        assert obs.uncovered_scoring_keys == ("fgmiss_0_19", "kr_yd", "st_tkl_solo")

    def test_idp_gaps_include_idp_only_keys_but_not_offense_bonuses(self):
        obs = _batch(card=self.CARD).by_player_id()["5226"]
        assert obs.uncovered_scoring_keys == ("idp_def_td", "kr_yd", "st_tkl_solo")

    def test_position_suffixed_bonus_only_applies_to_its_position(self):
        qb = _batch(card=self.CARD).by_player_id()["4881"]
        assert "bonus_fd_wr" not in qb.uncovered_scoring_keys

    def test_team_defense_and_zero_rate_keys_are_never_listed(self):
        for obs in _batch(card=self.CARD).observations:
            assert "pts_allow_0" not in obs.uncovered_scoring_keys
            assert "rec_fd" not in obs.uncovered_scoring_keys

    def test_a_category_published_for_the_position_is_not_a_gap(self):
        obs = _batch(card=self.CARD).by_player_id()["5226"]
        assert "idp_tkl_solo" not in obs.uncovered_scoring_keys
        wr = _batch(card=self.CARD).by_player_id()["9488"]
        # idp_tkl_solo is projected only for defenders: the provider's own
        # statement that a WR is not expected to earn it.
        assert "idp_tkl_solo" not in wr.uncovered_scoring_keys

    def test_dynasty_main_measured_example(self):
        """dynasty_main's committed card pays first-down bonuses, kick
        return yards and special-teams events the provider never
        projects — the example the unit handoff quotes."""
        card = json.loads(DYNASTY_MAIN_CARD.read_text(encoding="utf-8"))["scoring_settings"]
        by_id = _batch(card=card).by_player_id()
        assert by_id["9488"].uncovered_scoring_keys == (
            "bonus_fd_wr",
            "kr_yd",
            "st_ff",
            "st_fum_rec",
            "st_td",
            "st_tkl_solo",
        )
        assert set(by_id["11533"].uncovered_scoring_keys) >= {
            "fgmiss_0_19",
            "fgmiss_20_29",
            "fgmiss_50_59",
            "fgmiss_60p",
        }
        assert "idp_def_td" in by_id["5226"].uncovered_scoring_keys


# ── Acquisition: flag-gated, bounded, never networked in tests ───────


class TestFetch:
    def test_flag_is_off_by_default_and_no_request_is_made(self):
        def boom(url, timeout):  # pragma: no cover — must not be called
            raise AssertionError("network call with the flag off")

        assert swp.FEATURE_FLAG == "sleeper_weekly_projections"
        assert feature_flags.is_enabled(swp.FEATURE_FLAG) is False
        result = swp.fetch_weekly_projection_rows(2026, 3, http_get=boom)
        assert result.status == "feature_disabled"
        assert result.rows == ()
        assert result.observed_at is None

    def test_flag_on_returns_rows_with_a_utc_observed_at(self, monkeypatch):
        monkeypatch.setenv("RISKIT_FEATURE_SLEEPER_WEEKLY_PROJECTIONS", "1")
        feature_flags.reload()
        seen = {}

        def fake(url, timeout):
            seen["url"], seen["timeout"] = url, timeout
            return FIXTURE.read_bytes()

        clock = datetime(2026, 9, 25, 0, 58, 24, tzinfo=timezone.utc)
        result = swp.fetch_weekly_projection_rows(2026, 3, http_get=fake, now=lambda: clock)
        assert result.status == "ok"
        assert len(result.rows) == 18
        assert result.observed_at == OBSERVED_AT
        assert seen["timeout"] == swp.HTTP_TIMEOUT_SECONDS
        assert seen["url"].startswith("https://api.sleeper.app/projections/nfl/2026/3?")
        for pos in swp.POSITIONS:
            assert f"position%5B%5D={pos}" in seen["url"]

    def test_transport_failure_is_a_refusal_not_an_empty_success(self, monkeypatch):
        monkeypatch.setenv("RISKIT_FEATURE_SLEEPER_WEEKLY_PROJECTIONS", "1")
        feature_flags.reload()

        def fail(url, timeout):
            raise TimeoutError("timed out")

        result = swp.fetch_weekly_projection_rows(2026, 3, http_get=fail)
        assert result.status == "fetch_failed"
        assert "TimeoutError" in result.reason

    def test_non_list_payload_is_bad_payload(self, monkeypatch):
        monkeypatch.setenv("RISKIT_FEATURE_SLEEPER_WEEKLY_PROJECTIONS", "1")
        feature_flags.reload()
        result = swp.fetch_weekly_projection_rows(2026, 3, http_get=lambda u, t: b'{"a": 1}')
        assert result.status == "bad_payload"


# ── Kickoff baseline lock ────────────────────────────────────────────


def _fetch_at(minutes_before_kickoff: float, *, kickoff: datetime, rows=None):
    return _batch(
        rows=rows, observed_at=(kickoff - timedelta(minutes=minutes_before_kickoff)).isoformat()
    )


class TestBaselineLock:
    KICKOFF = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)

    def _drifted_rows(self, pass_yd: float):
        rows = _rows()
        for r in rows:
            if r["player_id"] == "4881":
                r["stats"]["pass_yd"] = pass_yd
        return rows

    def test_baseline_is_last_pre_kickoff_fetch_and_in_game_updates_do_not_drift_it(self):
        early = _fetch_at(120, kickoff=self.KICKOFF, rows=self._drifted_rows(250.0))
        late = _fetch_at(5, kickoff=self.KICKOFF, rows=self._drifted_rows(273.55))
        in_game = _fetch_at(-30, kickoff=self.KICKOFF, rows=self._drifted_rows(90.0))
        kickoffs = {"202610309": self.KICKOFF}
        obs = [
            o
            for b in (in_game, early, late)
            for o in b.observations
            if o.sleeper_player_id == "4881"
        ]
        lock = swp.lock_baseline_at_kickoff(obs, kickoffs, now=self.KICKOFF + timedelta(hours=1))
        entry = lock.baselines["4881"]
        assert entry.observation.stat_line["pass_yd"] == 273.55
        assert entry.observation.observed_at == late.observed_at
        assert entry.locked is True
        assert lock.post_kickoff_observations_ignored == 1

    def test_player_seen_only_after_kickoff_has_no_baseline(self):
        in_game = _fetch_at(-30, kickoff=self.KICKOFF)
        lock = swp.lock_baseline_at_kickoff(in_game.observations, {"202610309": self.KICKOFF})
        assert "4881" not in lock.baselines
        assert "4881" in lock.no_pre_kickoff_observation

    def test_unknown_kickoff_is_reported_not_locked(self):
        pre = _fetch_at(60, kickoff=self.KICKOFF)
        lock = swp.lock_baseline_at_kickoff(pre.observations, {"202610309": self.KICKOFF})
        assert set(lock.baselines) == {"4881", "11533"}
        assert "9488" in lock.unknown_kickoff

    def test_locked_is_unknown_without_now_and_false_before_kickoff(self):
        pre = _fetch_at(60, kickoff=self.KICKOFF)
        kickoffs = {"202610309": self.KICKOFF.isoformat()}
        assert (
            swp.lock_baseline_at_kickoff(pre.observations, kickoffs).baselines["4881"].locked
            is None
        )
        before = swp.lock_baseline_at_kickoff(
            pre.observations, kickoffs, now=self.KICKOFF - timedelta(minutes=1)
        )
        assert before.baselines["4881"].locked is False

    def test_naive_kickoff_is_refused(self):
        pre = _fetch_at(60, kickoff=self.KICKOFF)
        with pytest.raises(swp.WeeklyProjectionError):
            swp.lock_baseline_at_kickoff(pre.observations, {"202610309": "2026-09-27T17:00:00"})


# ── Ensemble membership (WEEKLY horizon only) ────────────────────────


class TestEnsembleAdapter:
    def test_single_weekly_family_is_an_honest_passthrough(self):
        obs = _batch().by_player_id()["9488"]
        combined = combine_ensemble([swp.to_projection_observation(obs)])
        assert combined.horizon == "WEEKLY"
        assert combined.combination_method == "single_family_passthrough"
        assert combined.family_count == 1
        assert combined.disagreement_spread is None
        assert combined.combined_league_scored_fpg == obs.league_scored_points
        assert combined.games == 1.0
        assert combined.as_of == obs.provider_updated_at

    def test_undated_row_cannot_enter_the_ensemble(self):
        rows = _rows()
        for r in rows:
            r.pop("updated_at", None)
            r.pop("last_modified", None)
        obs = _batch(rows=rows).by_player_id()["9488"]
        assert obs.provider_updated_at is None
        with pytest.raises(ProjectionObservationError):
            swp.to_projection_observation(obs)
