"""Source dataset state — fetch time is not data freshness.

Pins the owner directive of 2026-09-23 (and its required revision):

* an unchanged re-fetch moves NO data clock;
* a 1- or 2-row legitimate change moves ``lastAnyMeaningfulChangeAt`` only;
* a broad board update moves both clocks;
* a markup-only change, a failed scrape and a CAPTCHA/challenge page move
  neither clock and never replace the last valid content;
* players and picks are independent subsets;
* malformed / collapsed / duplicate-exploded boards are detected.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.sources.dataset_integrity import DEGRADED, FAILED, HEALTHY, parse_board
from src.sources.dataset_state import observe, record_source_file

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _board(values: dict[str, float], picks: dict[str, float] | None = None, extra: str = "") -> str:
    lines = ["name,value" + extra]
    for n, v in values.items():
        lines.append(f"{n},{v}" + ("," + "x" if extra else ""))
    for n, v in (picks or {}).items():
        lines.append(f"{n},{v}" + ("," + "x" if extra else ""))
    return "\n".join(lines) + "\n"


BASE = {f"Player {i}": 1000.0 + i for i in range(100)}
PICKS = {"2027 Early 1st": 6000.0, "2027 Mid 1st": 5000.0, "2027 Late 1st": 4000.0}


def _seed(source_key: str = "idpTradeCalc") -> dict:
    return observe(
        None, source_key=source_key, board=parse_board(_board(BASE, PICKS)), observed_at=T0
    )


def _players(state: dict) -> dict:
    return state["subsets"]["players"]


class TestThreeClocks:
    def test_unchanged_refetch_does_not_reset_data_freshness(self):
        state = _seed()
        later = observe(
            state,
            source_key="idpTradeCalc",
            board=parse_board(_board(BASE, PICKS)),
            observed_at=T0 + timedelta(days=22),
        )
        assert later == state  # nothing moved at all — not even the file

    def test_one_player_change_moves_any_change_only(self):
        changed = dict(BASE, **{"Player 7": 5000.0})
        state = observe(
            _seed(),
            source_key="idpTradeCalc",
            board=parse_board(_board(changed, PICKS)),
            observed_at=T0 + timedelta(days=3),
        )
        p = _players(state)
        assert p["lastAnyMeaningfulChangeAt"] == "2026-09-04T00:00:00Z"
        assert p["lastBroadDatasetChangeAt"] == "2026-09-01T00:00:00Z"
        assert p["changeHistory"][-1]["broad"] is False
        assert p["rowChangedAt"]["player 7"] == "2026-09-04T00:00:00Z"
        assert p["rowChangedAt"]["player 8"] == "2026-09-01T00:00:00Z"

    def test_two_player_change_is_still_not_broad(self):
        changed = dict(BASE, **{"Player 7": 5000.0, "Player 8": 10.0})
        state = observe(
            _seed(),
            source_key="idpTradeCalc",
            board=parse_board(_board(changed, PICKS)),
            observed_at=T0 + timedelta(days=3),
        )
        assert _players(state)["changeHistory"][-1] == {
            "at": "2026-09-04T00:00:00Z",
            "rowsChanged": 2,
            "rowsAdded": 0,
            "rowsRemoved": 0,
            "rowsTotal": 100,
            "broad": False,
        }
        assert _players(state)["lastBroadDatasetChangeAt"] == "2026-09-01T00:00:00Z"

    def test_broad_update_moves_both_clocks(self):
        republished = {k: v + 50 for k, v in BASE.items()}
        state = observe(
            _seed(),
            source_key="idpTradeCalc",
            board=parse_board(_board(republished, PICKS)),
            observed_at=T0 + timedelta(days=5),
        )
        p = _players(state)
        assert (
            p["lastAnyMeaningfulChangeAt"]
            == p["lastBroadDatasetChangeAt"]
            == "2026-09-06T00:00:00Z"
        )

    def test_markup_only_change_moves_neither_clock(self):
        # Extra non-content column (e.g. a page-render stamp) changes nothing.
        with_markup = _board(BASE, PICKS, extra=",renderedAt")
        state = observe(
            _seed(),
            source_key="idpTradeCalc",
            board=parse_board(with_markup),
            observed_at=T0 + timedelta(days=2),
        )
        assert _players(state)["lastAnyMeaningfulChangeAt"] == "2026-09-01T00:00:00Z"
        assert _players(state)["changeHistory"] == []

    def test_row_order_is_not_content(self):
        shuffled = dict(reversed(list(BASE.items())))
        state = observe(
            _seed(),
            source_key="idpTradeCalc",
            board=parse_board(_board(shuffled, PICKS)),
            observed_at=T0 + timedelta(days=2),
        )
        assert _players(state)["changeHistory"] == []


class TestFailuresNeverLookFresh:
    def test_failed_scrape_moves_neither_clock(self, tmp_path):
        state_dir = tmp_path / "state"
        csv = tmp_path / "board.csv"
        csv.write_text(_board(BASE, PICKS))
        before, _ = record_source_file(
            source_key="dlfSf", csv_path=csv, signal="value", state_dir=state_dir, observed_at=T0
        )
        csv.unlink()  # the fetch produced nothing
        after, _ = record_source_file(
            source_key="dlfSf",
            csv_path=csv,
            signal="value",
            state_dir=state_dir,
            observed_at=T0 + timedelta(days=14),
        )
        assert after["health"]["state"] == FAILED
        assert after["subsets"] == before["subsets"]

    def test_captcha_html_cannot_become_player_values(self):
        page = (
            "<!DOCTYPE html><html><head><title>Just a moment...</title></head>cf-challenge</html>"
        )
        board = parse_board(page)
        assert board.health == FAILED
        assert board.subset_rows("players") == {}
        state = observe(
            _seed(), source_key="idpTradeCalc", board=board, observed_at=T0 + timedelta(days=1)
        )
        assert _players(state) == _players(_seed())
        assert state["health"]["state"] == FAILED

    def test_malformed_values_are_rejected(self):
        text = "name,value\n" + "".join(f"P{i},abc\n" for i in range(50))
        assert parse_board(text).health == FAILED

    def test_player_count_collapse_is_detected_and_moves_no_clock(self):
        seed = _seed()
        tiny = {k: v + 9 for k, v in list(BASE.items())[:20]}
        state = observe(
            seed,
            source_key="idpTradeCalc",
            board=parse_board(_board(tiny)),
            observed_at=T0 + timedelta(days=1),
        )
        assert state["health"]["state"] == DEGRADED
        assert any("row-count collapse" in e for e in state["health"]["errors"])
        assert _players(state) == _players(seed)

    def test_duplicate_player_explosion_is_detected(self):
        text = "name,value\n" + "".join(f"Same Guy,{1000 + i}\n" for i in range(60))
        board = parse_board(text)
        assert board.health == DEGRADED
        assert any("duplicate" in e for e in board.errors)

    def test_healthy_board_is_healthy(self):
        assert parse_board(_board(BASE, PICKS)).health == HEALTHY


class TestIdpSubsetsAreIndependent:
    def test_players_can_update_while_picks_stay_stale(self):
        state = observe(
            _seed(),
            source_key="idpTradeCalc",
            board=parse_board(_board({k: v + 5 for k, v in BASE.items()}, PICKS)),
            observed_at=T0 + timedelta(days=20),
        )
        assert state["subsets"]["players"]["lastBroadDatasetChangeAt"] == "2026-09-21T00:00:00Z"
        assert state["subsets"]["picks"]["lastBroadDatasetChangeAt"] == "2026-09-01T00:00:00Z"

    def test_idp_show_and_idptc_are_tracked_separately(self, tmp_path):
        state_dir = tmp_path / "s"
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text(_board(BASE))
        b.write_text("name,rank\n" + "".join(f"P{i},{i + 1}\n" for i in range(100)))
        record_source_file(
            source_key="idpTradeCalc",
            csv_path=a,
            signal="value",
            state_dir=state_dir,
            observed_at=T0,
        )
        record_source_file(
            source_key="idpShowCombined",
            csv_path=b,
            signal="rank",
            state_dir=state_dir,
            observed_at=T0,
        )
        a.write_text(_board({k: v + 1 for k, v in BASE.items()}))
        idptc, _ = record_source_file(
            source_key="idpTradeCalc",
            csv_path=a,
            signal="value",
            state_dir=state_dir,
            observed_at=T0 + timedelta(days=9),
        )
        show, _ = record_source_file(
            source_key="idpShowCombined",
            csv_path=b,
            signal="rank",
            state_dir=state_dir,
            observed_at=T0 + timedelta(days=9),
        )
        assert idptc["subsets"]["players"]["lastBroadDatasetChangeAt"] == "2026-09-10T00:00:00Z"
        assert show["subsets"]["players"]["lastBroadDatasetChangeAt"] == "2026-09-01T00:00:00Z"
        assert (state_dir / "idpTradeCalc_dataset.json").exists()
        assert (state_dir / "idpShowCombined_dataset.json").exists()


class TestPersistenceIsQuiet:
    def test_unchanged_refetch_does_not_rewrite_the_file(self, tmp_path):
        csv = tmp_path / "b.csv"
        csv.write_text(_board(BASE))
        _, first = record_source_file(
            source_key="k", csv_path=csv, signal="value", state_dir=tmp_path, observed_at=T0
        )
        _, second = record_source_file(
            source_key="k",
            csv_path=csv,
            signal="value",
            state_dir=tmp_path,
            observed_at=T0 + timedelta(days=1),
        )
        assert first is True and second is False


def test_refresh_workflow_skips_exactly_the_prod_timer_owned_boards():
    """One writer per state file: the 2-hourly refresh must skip the boards
    whose production timers record their own state — the same set the
    server's post-scrape recorder skips."""
    import re
    from pathlib import Path

    from scripts.record_source_datasets import PROD_TIMER_OWNED_KEYS

    wf = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "scheduled-refresh.yml"
    ).read_text(encoding="utf-8")
    m = re.search(r"record_source_datasets\.py\s*\\\s*\n\s*--skip ([^\n|]+)", wf)
    assert m, "scheduled-refresh.yml no longer records dataset state with --skip"
    assert set(m.group(1).split()) - {"\\"} == set(PROD_TIMER_OWNED_KEYS)
