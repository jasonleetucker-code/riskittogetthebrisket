"""End-to-end test of the orchestrator with mocked I/O.

We don't hit Sleeper or nflverse here — both are stubbed at the module
boundary so the test runs offline and pins the response shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api import league_registry as _league_registry
from src.league_comparison import (
    historical_stats as _stats_mod,
    service as _service,
    sleeper_scoring as _sleeper_mod,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolate_caches(tmp_path, monkeypatch):
    """Redirect both the per-league scoring cache and the disk
    comparison cache to a temp dir so tests don't bleed into each
    other or into real cache files.

    Also points the league registry at the REAL repo file (the global
    conftest points ``LEAGUE_REGISTRY_PATH`` at ``/nonexistent`` to
    keep other suites hermetic) — ``build_comparison`` now resolves
    "my league" through the registry (W18-F005), so a real registry
    entry has to be reachable for these tests to build anything.
    """
    _sleeper_mod.evict()
    monkeypatch.setattr(
        _service,
        "_cache_dir",
        lambda: tmp_path / "lc_cache",
    )
    monkeypatch.setenv(
        "LEAGUE_REGISTRY_PATH", str(_REPO_ROOT / "config" / "leagues" / "registry.json")
    )
    _league_registry.reload_registry()
    yield
    _sleeper_mod.evict()
    _league_registry.reload_registry()


_MY_SCORING = {
    "pass_yd": 0.04,
    "pass_td": 5,
    "pass_int": -2,
    "rush_yd": 0.1,
    "rush_td": 6,
    "rec": 0.75,
    "rec_yd": 0.1,
    "rec_td": 6,
    "bonus_rec_te": 0.38,
    "fum_lost": -2,
}
_BASE_SCORING = {
    "pass_yd": 0.04,
    "pass_td": 4,
    "pass_int": -2,
    "rush_yd": 0.1,
    "rush_td": 6,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6,
    "bonus_rec_te": 0.5,
    "fum_lost": -2,
}


def _load_real_league_ids():
    """Resolve the same two league ids ``build_comparison`` resolves —
    "my league" through the registry's default league (W18-F005),
    "baseline league" from the JSON config — so the stub stays in
    lockstep with whatever is actually configured."""
    config = _service._load_config()
    my_league = _league_registry.get_default_league()
    assert my_league is not None, "real_registry fixture did not load a default league"
    return my_league.sleeper_league_id, config["baseline_league"]["id"]


def _stub_scoring_fetch(monkeypatch):
    my_id, base_id = _load_real_league_ids()

    def fake(league_id, *, refresh=False):
        if league_id == my_id:
            return _sleeper_mod.LeagueScoringInfo(
                league_id=league_id,
                name="My League",
                season="2025",
                season_type="regular",
                scoring_settings=_MY_SCORING,
                scoring_hash="hashMY",
            )
        return _sleeper_mod.LeagueScoringInfo(
            league_id=league_id,
            name="Standard Baseline",
            season="2025",
            season_type="regular",
            scoring_settings=_BASE_SCORING,
            scoring_hash="hashBASE",
        )

    monkeypatch.setattr(_sleeper_mod, "fetch_league_scoring", fake)


def _row(pid, pos, week, season, **stats):
    base = {
        "player_id": pid,
        "player_name": pid.upper(),
        "position": pos,
        "season": season,
        "week": week,
        "passing_yards": 0,
        "passing_tds": 0,
        "interceptions": 0,
        "rushing_yards": 0,
        "rushing_tds": 0,
        "receptions": 0,
        "receiving_yards": 0,
        "receiving_tds": 0,
        "fumbles_lost": 0,
    }
    base.update(stats)
    return base


def _make_season(season: int):
    """Generate enough mock players to fill the top-N samples for one
    season."""
    rows: list[dict] = []
    # 30 QBs, 30 RBs, 40 WRs, 15 TEs — enough to cover the sample sizes
    # plus headroom.  Vary points by index so ranking is deterministic.
    for i in range(30):
        for week in range(1, 18):
            rows.append(
                _row(
                    f"qb{i}",
                    "QB",
                    week,
                    season,
                    passing_yards=200 + (29 - i) * 5,
                    passing_tds=2 if i < 12 else 1,
                )
            )
    for i in range(30):
        for week in range(1, 18):
            rows.append(
                _row(
                    f"rb{i}",
                    "RB",
                    week,
                    season,
                    rushing_yards=60 + (29 - i) * 3,
                    receptions=2 + (i % 4),
                    receiving_yards=15 + (i % 5) * 4,
                )
            )
    for i in range(40):
        for week in range(1, 18):
            rows.append(
                _row(
                    f"wr{i}",
                    "WR",
                    week,
                    season,
                    receptions=4 + (39 - i) // 5,
                    receiving_yards=50 + (39 - i) * 2,
                )
            )
    for i in range(15):
        for week in range(1, 18):
            rows.append(
                _row(
                    f"te{i}",
                    "TE",
                    week,
                    season,
                    receptions=3 + (14 - i) // 3,
                    receiving_yards=30 + (14 - i) * 2,
                )
            )
    return rows


def _stub_stats_fetch(monkeypatch, available_seasons):
    def fake_load(season):
        if season in available_seasons:
            return _make_season(season)
        return None

    monkeypatch.setattr(_stats_mod, "load_season_rows", fake_load)


# ── Tests ─────────────────────────────────────────────────────────────


def test_build_comparison_returns_full_shape(monkeypatch, tmp_path):
    _stub_scoring_fetch(monkeypatch)
    _stub_stats_fetch(monkeypatch, available_seasons={2022, 2023, 2024, 2025})
    # Point at the real config (it exists in the repo).
    out = _service.build_comparison(refresh=True)

    # Top-level keys
    for key in (
        "meta",
        "summary",
        "similarity",
        "positions",
        "flex",
        "bySeason",
        "idp",
        "warnings",
    ):
        assert key in out, f"missing top-level key: {key}"

    # Meta block
    meta = out["meta"]
    my_id, base_id = _load_real_league_ids()
    assert meta["myLeague"]["id"] == my_id
    assert meta["baselineLeague"]["id"] == base_id
    assert meta["seasonsRequested"] == [2022, 2023, 2024, 2025]
    assert meta["seasonsAvailable"] == [2022, 2023, 2024, 2025]
    assert meta["seasonsUnavailable"] == []

    # Per-position block has all four offense positions
    assert set(out["positions"].keys()) == {"QB", "RB", "WR", "TE"}
    for pos, comp in out["positions"].items():
        assert "my" in comp
        assert "baseline" in comp
        assert "diffPpImproved" in comp
        assert "diffPpLegacy" in comp
        assert "status" in comp
        assert "recommendation" in comp
        assert comp["my"]["metrics"]["sampleSize"] > 0
        assert comp["baseline"]["metrics"]["sampleSize"] > 0

    # Similarity block
    sim = out["similarity"]
    assert 0 <= sim["score"] <= 100
    assert sim["distortionLabel"] in {"Low", "Moderate", "High", "Severe"}

    # IDP placeholder
    assert out["idp"]["available"] is False
    assert out["idp"]["status"] == "placeholder"

    # bySeason has all four seasons
    assert set(out["bySeason"].keys()) == {"2022", "2023", "2024", "2025"}


def test_missing_season_emits_warning(monkeypatch):
    _stub_scoring_fetch(monkeypatch)
    _stub_stats_fetch(monkeypatch, available_seasons={2022, 2023, 2024})  # 2025 missing
    out = _service.build_comparison(refresh=True)
    assert out["meta"]["seasonsUnavailable"] == [2025]
    assert any("2025" in w for w in out["warnings"])
    # Combined still uses three seasons, equally weighted
    assert out["meta"]["seasonsAvailable"] == [2022, 2023, 2024]


def test_single_season_emits_limited_data_warning(monkeypatch):
    _stub_scoring_fetch(monkeypatch)
    _stub_stats_fetch(monkeypatch, available_seasons={2024})
    out = _service.build_comparison(refresh=True)
    assert out["meta"]["seasonsAvailable"] == [2024]
    assert any("limited" in w.lower() for w in out["warnings"])


def test_cache_hit_avoids_recomputation(monkeypatch):
    _stub_scoring_fetch(monkeypatch)
    _stub_stats_fetch(monkeypatch, available_seasons={2022, 2023, 2024, 2025})

    # Count how many times stats are loaded.
    call_count = {"n": 0}
    real_load = _stats_mod.load_season_rows

    def counting_load(season):
        call_count["n"] += 1
        return real_load(season)

    monkeypatch.setattr(_stats_mod, "load_season_rows", counting_load)

    first = _service.build_comparison(refresh=True)
    n_after_first = call_count["n"]
    assert n_after_first > 0

    # Second call without refresh should hit the disk cache and skip
    # all stat loads.
    second = _service.build_comparison(refresh=False)
    assert call_count["n"] == n_after_first
    assert second["meta"]["cacheHit"] is True
    # Same shape, same positions
    assert (
        second["positions"]["QB"]["my"]["improvedScore"]
        == first["positions"]["QB"]["my"]["improvedScore"]
    )


def test_refresh_bypasses_cache(monkeypatch):
    _stub_scoring_fetch(monkeypatch)
    _stub_stats_fetch(monkeypatch, available_seasons={2024})

    call_count = {"n": 0}
    real_load = _stats_mod.load_season_rows

    def counting_load(season):
        call_count["n"] += 1
        return real_load(season)

    monkeypatch.setattr(_stats_mod, "load_season_rows", counting_load)

    _service.build_comparison(refresh=True)
    after_first = call_count["n"]
    _service.build_comparison(refresh=True)
    # refresh=True must reload every season again
    assert call_count["n"] == 2 * after_first


def test_baseline_my_have_different_scoring_produces_meaningful_diff(monkeypatch):
    """Sanity: a high-PPR / TEP baseline vs a 0.75 PPR / lower-TEP my
    league should produce non-zero share differences when applied to
    the same stat rows."""
    _stub_scoring_fetch(monkeypatch)
    _stub_stats_fetch(monkeypatch, available_seasons={2024})
    out = _service.build_comparison(refresh=True)

    diffs = [abs(out["positions"][p]["diffPpImproved"]) for p in ("QB", "RB", "WR", "TE")]
    # At least one position should have a non-trivial difference given
    # the divergent scoring setups.
    assert max(diffs) > 0.1


def test_payload_is_json_serializable(monkeypatch):
    _stub_scoring_fetch(monkeypatch)
    _stub_stats_fetch(monkeypatch, available_seasons={2024})
    out = _service.build_comparison(refresh=True)
    # Will raise if anything in the payload is non-serializable
    json.dumps(out)


class TestSampleSizesFromRosterSettings:
    """W18-F005's other half: replacement-level cohort sizes derived
    from the league's OWN roster shape rather than a hand-maintained
    config guess that silently drifts when the lineup changes."""

    def test_reproduces_dynasty_mains_real_roster_shape(self):
        """QB counts SFLEX as real demand (the existing C2-CORE-01
        convention, not a new rule); RB/WR/TE are plain team_count *
        starters. Values pinned against the registry's real dynasty_main
        entry (12 teams; QB1/RB2/WR3/TE2/SFLEX1/DL3/LB3/DB3/IDP_FLEX0)."""
        roster_settings = {
            "teamCount": 12,
            "starters": {
                "QB": 1,
                "RB": 2,
                "WR": 3,
                "TE": 2,
                "FLEX": 2,
                "SFLEX": 1,
                "K": 1,
                "DL": 3,
                "LB": 3,
                "DB": 3,
                "IDP_FLEX": 0,
            },
        }
        got = _service._sample_sizes_from_roster_settings(roster_settings)
        assert got == {
            "QB": 24,  # 12 * (1 QB + 1 SFLEX)
            "RB": 24,  # 12 * 2
            "WR": 36,  # 12 * 3
            "TE": 24,  # 12 * 2 -- corrected from the old hardcoded 12
            "IDP_TOTAL": 108,  # 12 * (3 DL + 3 LB + 3 DB + 0 IDP_FLEX) -- corrected from 96
        }

    def test_a_non_idp_leagues_zero_idp_slots_derive_to_zero_not_omitted(self):
        """dynasty_new carries no DL/LB/DB/IDP_FLEX keys at all (it is
        not an IDP league) -- missing slot keys must derive to 0, not
        raise or silently drop the key."""
        roster_settings = {
            "teamCount": 10,
            "starters": {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2, "SFLEX": 1},
        }
        got = _service._sample_sizes_from_roster_settings(roster_settings)
        assert got["IDP_TOTAL"] == 0
        assert got["QB"] == 10 * (1 + 1)

    @pytest.mark.parametrize(
        "roster_settings",
        [
            {},
            {"teamCount": 12},  # no starters dict
            {"teamCount": 0, "starters": {"QB": 1}},  # non-positive team count
            {"teamCount": 12, "starters": "not-a-dict"},
        ],
    )
    def test_missing_or_malformed_roster_settings_fails_closed(self, roster_settings):
        """MISSING IS NEVER ZERO: a league with no derivable roster shape
        must refuse loudly, never silently produce a sample_sizes dict of
        zeros that would read as 'we measured zero demand'."""
        with pytest.raises(ValueError):
            _service._sample_sizes_from_roster_settings(roster_settings)
