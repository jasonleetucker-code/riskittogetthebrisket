"""Tests for ``src.nfl_data.actuals_store``.

The guards here are written against §6.15 ("a guard that cannot fire").
Two of them exist specifically because the *silent* failure mode is the
realistic one:

* **The column-alias test is the load-bearing one.**  nflverse renamed
  six columns in the 2025 unified release.  Reading a renamed column
  returns ``None`` and the mapper produces a fully-formed row of zeros —
  no exception, no log line, a plausible-looking file on disk.  So the
  test asserts a NON-ZERO value came off the new spelling, which is the
  only assertion a rename can fail.  Asserting "the field exists" or
  "the row parsed" would pass against exactly the defect it names.
* **The idempotency test writes the same week twice with different
  numbers** and asserts one line survives carrying the SECOND set.  A
  test that wrote identical payloads twice would pass whether the store
  deduped or blindly appended two byte-identical lines.

Every fixture row uses the unified 2025 spellings measured live on
2026-07-27, with a second fixture in the retired pre-2025 spellings, so
the alias table is exercised from both sides.
"""

from __future__ import annotations

import json

import pytest

from src.api import feature_flags
from src.nfl_data import actuals_store


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "1")
    feature_flags.reload()
    yield
    feature_flags.reload()


# ── Fixtures ─────────────────────────────────────────────────────────
#
# Column names and values copied from the real 2025 unified release
# (stats_player/stats_player_week_2025.csv), week 1.


def _unified_qb_row() -> dict:
    return {
        "player_id": "00-0026158",
        "player_name": "J.Flacco",
        "player_display_name": "Joe Flacco",
        "position": "QB",
        "position_group": "QB",
        "team": "CLE",
        "opponent_team": "CIN",
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "completions": 31,
        "attempts": 45,
        "passing_yards": 290,
        "passing_tds": 1,
        # RENAMED — old spelling was ``interceptions``.
        "passing_interceptions": 2,
        # RENAMED — old spelling was ``sacks``.
        "sacks_suffered": 3,
        "carries": 2,
        "rushing_yards": 6,
        "rushing_tds": 0,
        "targets": 0,
        "receptions": 0,
        "receiving_yards": 0,
        "receiving_tds": 0,
        # RENAMED — old spelling was ``fumbles_lost``.
        "fumbles_lost_total": 1,
    }


def _unified_idp_row() -> dict:
    return {
        "player_id": "00-0032899",
        "player_name": "D.Slay",
        "player_display_name": "Darius Slay",
        "position": "CB",
        "team": "PIT",
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "def_tackles_solo": 5,
        # ``def_tackles`` was REMOVED; combined = solo + with_assist.
        "def_tackles_with_assist": 2,
        "def_tackle_assists": 1,
        "def_tackles_for_loss": 1,
        "def_tackles_for_loss_yards": 3,
        "def_sacks": 0,
        "def_sack_yards": 0,
        "def_qb_hits": 1,
        "def_pass_defended": 2,
        "def_interceptions": 1,
        "def_interception_yards": 14,
        "def_fumbles_forced": 1,
        "fumble_recovery_own": 0,
        "fumble_recovery_opp": 1,
        "fumble_recovery_yards_own": 0,
        "fumble_recovery_yards_opp": 7,
        "def_tds": 0,
        # RENAMED — old spelling was ``def_safety``.
        "def_safeties": 1,
    }


def _legacy_qb_row() -> dict:
    """The retired pre-2025 spellings, so the alias table is exercised
    from both directions — a backfill over 2023/2024 still goes through
    this same mapper."""
    return {
        "player_id": "00-0011111",
        "player_name": "L.Egacy",
        "position": "QB",
        "recent_team": "SEA",
        "season": 2024,
        "week": 4,
        "season_type": "REG",
        "completions": 20,
        "attempts": 30,
        "passing_yards": 240,
        "passing_tds": 2,
        "interceptions": 1,
        "sacks": 4,
        "carries": 1,
        "rushing_yards": 3,
        "rushing_tds": 0,
        "targets": 0,
        "receptions": 0,
        "receiving_yards": 0,
        "receiving_tds": 0,
        "fumbles_lost": 2,
    }


def _legacy_idp_row() -> dict:
    return {
        "player_id": "00-0022222",
        "player_name": "O.Ldbacker",
        "position": "LB",
        "recent_team": "SEA",
        "season": 2024,
        "week": 4,
        "season_type": "REG",
        # The published column, still present pre-2025.
        "def_tackles": 9,
        "def_tackles_solo": 6,
        "def_tackles_with_assist": 3,
        "def_tackle_assists": 3,
        "def_sacks": 1.5,
        "def_safety": 1,
    }


def _provider(rows):
    def _fn(_years):
        return list(rows)

    return _fn


# ── The rename guard ─────────────────────────────────────────────────


def test_renamed_offensive_columns_carry_nonzero_values():
    """The 2025 rename must not read as a zeroed stat line.

    Each assertion pins a NON-ZERO value onto a field whose source
    column was renamed.  Drop the new spelling from the alias table and
    every one of these goes to 0.0 — the mapper still returns a
    well-formed WeeklyStatRow, which is precisely why "did it parse?"
    is not a usable assertion here.
    """
    row = actuals_store.normalize_offensive_row(_unified_qb_row())
    assert row is not None
    assert row.recent_team == "CLE", "team (was recent_team)"
    assert row.interceptions == 2.0, "passing_interceptions (was interceptions)"
    assert row.sacks == 3.0, "sacks_suffered (was sacks)"
    assert row.fumbles_lost == 1.0, "fumbles_lost_total (was fumbles_lost)"


def test_renamed_defensive_columns_carry_nonzero_values():
    row = actuals_store.normalize_defensive_row(_unified_idp_row())
    assert row is not None
    assert row.team == "PIT"
    assert row.safeties == 1.0, "def_safeties (was def_safety)"
    assert row.passes_defended == 2.0
    assert row.fumble_recovery_opp == 1.0, "fumble_recovery_opp is not def_-prefixed"
    assert row.fumble_recovery_yards_opp == 7.0


def test_legacy_column_spellings_still_map():
    off = actuals_store.normalize_offensive_row(_legacy_qb_row())
    assert off is not None
    assert off.recent_team == "SEA"
    assert off.interceptions == 1.0
    assert off.sacks == 4.0
    assert off.fumbles_lost == 2.0

    dfn = actuals_store.normalize_defensive_row(_legacy_idp_row())
    assert dfn is not None
    assert dfn.safeties == 1.0
    assert dfn.sacks == 1.5


# ── The derived-tackles identity ─────────────────────────────────────


def test_tackle_fields_are_gamebook_values_not_raw_columns():
    """Two measurements, both against the retired 2024 defensive release:

    * ``def_tackles == def_tackles_solo + def_tackles_with_assist`` on
      9,994 of 9,994 rows — so ``def_tackles`` is the gamebook SOLO
      total, not combined.
    * ``def_tackles_solo`` excludes ``def_tackles_with_assist``: 342
      rows have solo 0 with with_assist > 0.

    The fixture is solo 5 / with_assist 2 / assists 1, so every wrong
    reading gives a different number and this assertion separates them:
    raw solo would be 5, ``def_tackles``-as-combined would be 7, the
    correct combined is 8.
    """
    row = actuals_store.normalize_defensive_row(_unified_idp_row())
    assert row is not None
    assert row.tackles_solo == 7.0, "gamebook solo = 5 unassisted + 2 with-assist"
    assert row.tackles_assist == 1.0
    assert row.tackles_combined == 8.0, "solo 7 + assists 1"


def test_published_def_tackles_is_used_as_the_solo_total():
    """Pre-2025 files publish ``def_tackles``; it IS gamebook solo, so
    it is read as solo and combined still adds assists on top."""
    row = actuals_store.normalize_defensive_row(_legacy_idp_row())
    assert row is not None
    assert row.tackles_solo == 9.0
    assert row.tackles_assist == 3.0
    assert row.tackles_combined == 12.0


# ── Production gating: zeroed def_* blocks must not create IDP rows ──


def test_offensive_row_with_zeroed_defensive_block_is_not_a_defender():
    """The unified release gives every offensive player a full set of
    zeroed ``def_*`` columns.  Persisting those would triple the file
    and make every QB look like a rostered IDP with a blank stat line."""
    qb = _unified_qb_row()
    qb.update({k: 0 for k in ("def_tackles_solo", "def_sacks", "def_pass_defended")})
    assert actuals_store.normalize_defensive_row(qb) is None


def test_row_without_a_player_id_is_dropped():
    row = _unified_qb_row()
    row["player_id"] = ""
    assert actuals_store.normalize_offensive_row(row) is None


def test_row_with_no_production_at_all_is_dropped():
    row = {"player_id": "00-0099999", "season": 2025, "week": 1, "position": "WR"}
    assert actuals_store.normalize_offensive_row(row) is None
    assert actuals_store.normalize_defensive_row(row) is None


# ── Persistence ──────────────────────────────────────────────────────


def test_persist_writes_one_line_per_week_with_both_blocks(tmp_path):
    out = tmp_path / "actuals"
    rows = [_unified_qb_row(), _unified_idp_row()]
    result = actuals_store.persist_weekly_actuals(
        [2025],
        actuals_dir=out,
        cache_dir=tmp_path / "cache",
        _offensive_provider=_provider(rows),
        _defensive_provider=_provider(rows),
    )

    assert result.weeks_written == 1
    assert result.player_weeks == 2
    assert result.offense_records == 1
    assert result.defense_records == 1

    path = actuals_store.season_path(2025, actuals_dir=out)
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["season"] == 2025
    assert entry["week"] == 1
    assert entry["seasonType"] == "REG"
    assert entry["playerCount"] == 2
    assert entry["schemaVersion"] == actuals_store.ACTUALS_SCHEMA_VERSION

    qb = entry["players"]["00-0026158"]
    assert qb["position"] == "QB"
    assert qb["defense"] is None, "a QB with a zeroed def_ block is not a defender"
    assert qb["offense"]["passing_yards"] == 290.0
    assert qb["offense"]["interceptions"] == 2.0
    # Not joined — see the module docstring.  None means "not fetched",
    # which is a different claim from 0.
    assert qb["offense"]["snap_count"] is None

    idp = entry["players"]["00-0032899"]
    assert idp["offense"] is None
    assert idp["defense"]["tackles_combined"] == 8.0


def test_reruns_replace_a_week_rather_than_appending(tmp_path):
    """nflverse revises box scores for days after a game.  Two copies of
    week 1 would make 'which is current?' unanswerable.

    The second write carries DIFFERENT numbers, so a store that appended
    (or that kept the first copy) fails here.  Identical payloads would
    pass either way.
    """
    out = tmp_path / "actuals"
    kwargs = {"actuals_dir": out, "cache_dir": tmp_path / "cache", "refresh": True}

    first = _unified_qb_row()
    actuals_store.persist_weekly_actuals(
        [2025], _offensive_provider=_provider([first]), _defensive_provider=_provider([]), **kwargs
    )

    revised = _unified_qb_row()
    revised["passing_yards"] = 311
    actuals_store.persist_weekly_actuals(
        [2025],
        _offensive_provider=_provider([revised]),
        _defensive_provider=_provider([]),
        **kwargs,
    )

    lines = (
        actuals_store.season_path(2025, actuals_dir=out).read_text(encoding="utf-8").strip().split("\n")
    )
    assert len(lines) == 1, "a revised week must replace, not accumulate"
    entry = json.loads(lines[0])
    assert entry["players"]["00-0026158"]["offense"]["passing_yards"] == 311.0


def test_a_partial_fetch_leaves_other_weeks_untouched(tmp_path):
    out = tmp_path / "actuals"
    kwargs = {"actuals_dir": out, "cache_dir": tmp_path / "cache", "refresh": True}

    w1 = _unified_qb_row()
    w2 = _unified_qb_row()
    w2["week"] = 2
    actuals_store.persist_weekly_actuals(
        [2025],
        _offensive_provider=_provider([w1, w2]),
        _defensive_provider=_provider([]),
        **kwargs,
    )

    # A re-run covering only week 2 must not truncate week 1.
    w2b = _unified_qb_row()
    w2b["week"] = 2
    w2b["passing_yards"] = 400
    actuals_store.persist_weekly_actuals(
        [2025], _offensive_provider=_provider([w2b]), _defensive_provider=_provider([]), **kwargs
    )

    entries = actuals_store.load_season(2025, actuals_dir=out)
    assert [e["week"] for e in entries] == [1, 2]
    assert entries[0]["players"]["00-0026158"]["offense"]["passing_yards"] == 290.0
    assert entries[1]["players"]["00-0026158"]["offense"]["passing_yards"] == 400.0


def test_regular_season_and_playoffs_are_separate_lines(tmp_path):
    out = tmp_path / "actuals"
    reg = _unified_qb_row()
    post = _unified_qb_row()
    post.update({"week": 19, "season_type": "POST"})
    actuals_store.persist_weekly_actuals(
        [2025],
        actuals_dir=out,
        cache_dir=tmp_path / "cache",
        _offensive_provider=_provider([reg, post]),
        _defensive_provider=_provider([]),
    )
    entries = actuals_store.load_season(2025, actuals_dir=out)
    assert [(e["week"], e["seasonType"]) for e in entries] == [(1, "REG"), (19, "POST")]
    assert [e["week"] for e in actuals_store.load_season(2025, actuals_dir=out, season_types=["REG"])] == [1]


def test_duplicate_rows_from_the_two_fetchers_collapse(tmp_path):
    """After #589 both fetchers request the same unified CSV, so the
    same physical row arrives twice.  It must merge, not double."""
    out = tmp_path / "actuals"
    rows = [_unified_qb_row(), _unified_idp_row()]
    result = actuals_store.persist_weekly_actuals(
        [2025],
        actuals_dir=out,
        cache_dir=tmp_path / "cache",
        _offensive_provider=_provider(rows),
        _defensive_provider=_provider(rows),
    )
    assert result.offensive_rows_fetched == 2
    assert result.defensive_rows_fetched == 2
    assert result.player_weeks == 2, "two distinct players, not four records"


def test_without_refresh_a_rerun_is_served_the_ttl_cache(tmp_path):
    """The counterpart to the two tests above, and the reason ``refresh``
    exists at all.

    Inside the 24-hour TTL a re-run never reaches the provider, so a
    revised box score cannot land.  Pinning it here means the flag has a
    stated behaviour on both settings — an option whose "off" path is
    untested is indistinguishable from one that does nothing.
    """
    out = tmp_path / "actuals"
    kwargs = {"actuals_dir": out, "cache_dir": tmp_path / "cache"}
    calls: list = []

    def counting(rows):
        def _fn(years):
            calls.append(years)
            return list(rows)

        return _fn

    actuals_store.persist_weekly_actuals(
        [2025],
        _offensive_provider=counting([_unified_qb_row()]),
        _defensive_provider=counting([]),
        **kwargs,
    )
    assert len(calls) == 2, "cold: both fetchers hit their provider"

    revised = _unified_qb_row()
    revised["passing_yards"] = 311
    actuals_store.persist_weekly_actuals(
        [2025],
        _offensive_provider=counting([revised]),
        _defensive_provider=counting([]),
        **kwargs,
    )
    assert len(calls) == 2, "warm: the TTL cache short-circuits the provider"

    entry = json.loads(
        actuals_store.season_path(2025, actuals_dir=out).read_text(encoding="utf-8").strip()
    )
    assert entry["players"]["00-0026158"]["offense"]["passing_yards"] == 290.0


def test_persist_with_no_rows_writes_no_file(tmp_path):
    out = tmp_path / "actuals"
    result = actuals_store.persist_weekly_actuals(
        [2025],
        actuals_dir=out,
        cache_dir=tmp_path / "cache",
        _offensive_provider=_provider([]),
        _defensive_provider=_provider([]),
    )
    assert result.weeks_written == 0
    assert not actuals_store.season_path(2025, actuals_dir=out).exists()


def test_feature_flag_off_persists_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "0")
    feature_flags.reload()
    out = tmp_path / "actuals"
    calls = []

    def provider(years):
        calls.append(years)
        return [_unified_qb_row()]

    result = actuals_store.persist_weekly_actuals(
        [2025],
        actuals_dir=out,
        cache_dir=tmp_path / "cache",
        _offensive_provider=provider,
        _defensive_provider=provider,
    )
    assert calls == []
    assert result.weeks_written == 0


# ── Read paths ───────────────────────────────────────────────────────


def test_load_player_weeks_returns_a_flat_time_series(tmp_path):
    out = tmp_path / "actuals"
    for season, weeks in ((2024, (3, 4)), (2025, (1,))):
        rows = []
        for wk in weeks:
            r = _unified_qb_row()
            r.update({"season": season, "week": wk, "passing_yards": 100 * wk})
            rows.append(r)
        actuals_store.persist_weekly_actuals(
            [season],
            actuals_dir=out,
            cache_dir=tmp_path / "cache",
            _offensive_provider=_provider(rows),
            _defensive_provider=_provider([]),
        )

    series = actuals_store.load_player_weeks("00-0026158", actuals_dir=out)
    assert [(s["season"], s["week"]) for s in series] == [(2024, 3), (2024, 4), (2025, 1)]
    assert [s["offense"]["passing_yards"] for s in series] == [300.0, 400.0, 100.0]
    assert all(s["capturedAt"] for s in series)


def test_load_player_weeks_unknown_player_is_empty_not_an_error(tmp_path):
    assert actuals_store.load_player_weeks("00-0000000", actuals_dir=tmp_path / "nope") == []
    assert actuals_store.load_player_weeks("", actuals_dir=tmp_path) == []


def test_coverage_reports_what_is_on_disk(tmp_path):
    out = tmp_path / "actuals"
    empty = actuals_store.coverage(actuals_dir=out)
    assert empty["dirExists"] is False
    assert empty["seasons"] == {}

    actuals_store.persist_weekly_actuals(
        [2025],
        actuals_dir=out,
        cache_dir=tmp_path / "cache",
        _offensive_provider=_provider([_unified_qb_row()]),
        _defensive_provider=_provider([_unified_idp_row()]),
    )
    cov = actuals_store.coverage(actuals_dir=out)
    assert cov["dirExists"] is True
    assert cov["seasons"]["2025"]["weeks"] == [1]
    assert cov["seasons"]["2025"]["playerWeeks"] == 2
    assert cov["seasons"]["2025"]["seasonTypes"] == ["REG"]
    assert cov["seasons"]["2025"]["capturedAt"]


def test_a_truncated_tail_line_does_not_wedge_the_season(tmp_path):
    out = tmp_path / "actuals"
    actuals_store.persist_weekly_actuals(
        [2025],
        actuals_dir=out,
        cache_dir=tmp_path / "cache",
        _offensive_provider=_provider([_unified_qb_row()]),
        _defensive_provider=_provider([]),
    )
    path = actuals_store.season_path(2025, actuals_dir=out)
    with path.open("a", encoding="utf-8") as f:
        f.write('{"season":2025,"week":2,"play')  # killed mid-write
    entries = actuals_store.load_season(2025, actuals_dir=out)
    assert [e["week"] for e in entries] == [1]


# ── The home question ────────────────────────────────────────────────


def test_actuals_dir_is_not_the_ttl_cache():
    """``data/nfl_data_cache/`` evicts on a 24h timer, so nothing
    accumulates there.  The two must never converge on one path."""
    from src.nfl_data import cache as ttl_cache

    assert actuals_store.default_actuals_dir() != ttl_cache._default_cache_dir()
    assert actuals_store.default_actuals_dir().parts[-2:] == ("nfl_data", "actuals")
