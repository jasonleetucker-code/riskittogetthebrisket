"""Regression cover for audit defects D9, D11 and D13.

Each class names the defect it pins so a future change that reintroduces
one fails with the reason attached.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

import server
from src.intel import crawler


class TestD9PickHorizon:
    """Pick holdings must start at the first season whose picks EXIST.

    Two bugs: the base year came from the wall clock (which disagrees
    with the league's own season for most of the calendar), and the
    current season's picks were seeded even after that season's rookie
    draft had been held.
    """

    def test_uses_the_leagues_season_not_the_wall_clock(self):
        out = crawler._pick_holdings(
            ["1"], [], draft_rounds=1, now_year=2027, season_year=2026, draft_status="pre_draft"
        )
        seasons = {p.split(":")[1] for p in out["1"]}
        assert seasons == {
            "2026",
            "2027",
            "2028",
        }, "the horizon must anchor on the league's season, not the wall-clock year"

    def test_wall_clock_is_the_fallback_when_season_is_unknown(self):
        out = crawler._pick_holdings(["1"], [], draft_rounds=1, now_year=2026)
        assert {p.split(":")[1] for p in out["1"]} == {"2026", "2027", "2028"}

    @pytest.mark.parametrize("status", ["pre_draft", "drafting", ""])
    def test_current_season_picks_survive_while_still_draftable(self, status):
        out = crawler._pick_holdings(
            ["1"], [], draft_rounds=1, now_year=2026, season_year=2026, draft_status=status
        )
        assert "pick:2026:1" in out["1"]

    @pytest.mark.parametrize("status", ["in_season", "post_season", "complete"])
    def test_drafted_season_is_dropped_from_the_horizon(self, status):
        """Once the rookie draft has happened those picks are spent —
        crediting a roster with them invents assets."""
        out = crawler._pick_holdings(
            ["1"], [], draft_rounds=1, now_year=2026, season_year=2026, draft_status=status
        )
        seasons = {p.split(":")[1] for p in out["1"]}
        assert "2026" not in seasons
        assert seasons == {"2027", "2028", "2029"}

    def test_unknown_status_is_treated_as_still_draftable(self):
        """Degrade toward the prior behaviour rather than silently
        deleting a season's picks on an unexpected status string."""
        out = crawler._pick_holdings(
            ["1"], [], draft_rounds=1, now_year=2026, season_year=2026, draft_status=None
        )
        assert "pick:2026:1" in out["1"]

    def test_traded_pick_diffs_still_apply_on_the_shifted_horizon(self):
        out = crawler._pick_holdings(
            ["1", "2"],
            [{"season": "2027", "round": 1, "roster_id": 2, "owner_id": 1}],
            draft_rounds=1,
            now_year=2026,
            season_year=2026,
            draft_status="in_season",
        )
        assert out["1"].count("pick:2027:1") == 2  # own + acquired
        assert "pick:2027:1" not in out.get("2", [])


class TestD11NoBlockingIoInAsyncHandler:
    def test_intel_snapshot_read_is_threadpooled(self):
        """A synchronous snapshot read on the event loop blocks every
        other in-flight request.

        Asserted on the AST rather than on source text: the call spans
        several lines, so a line-by-line string check reports a false
        failure on correctly-wrapped code.
        """
        tree = ast.parse(textwrap.dedent(inspect.getsource(server.post_waiver_faab_recommend)))

        def is_snapshot_call(node):
            return (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "load_intel_snapshot"
            )

        # Every load_intel_snapshot call must be an ARGUMENT to
        # run_in_threadpool, never invoked directly.
        threadpooled = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "run_in_threadpool"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Attribute) and arg.attr == "load_intel_snapshot":
                        threadpooled.add("wrapped")

        direct = [n for n in ast.walk(tree) if is_snapshot_call(n)]
        assert not direct, "load_intel_snapshot is invoked directly on the event loop"
        assert threadpooled, "load_intel_snapshot is not passed to run_in_threadpool"


class TestD13RefreshCooldown:
    """Any signed-in session could re-trigger a minutes-long Sleeper
    crawl the moment the previous one finished.  The process lock only
    stopped CONCURRENT runs."""

    def setup_method(self):
        server._intel_refresh_reset_for_tests()

    def teardown_method(self):
        server._intel_refresh_reset_for_tests()

    def test_first_trigger_is_allowed(self):
        assert server._intel_refresh_cooldown_remaining("alice") == 0

    def test_second_trigger_is_blocked(self):
        server._intel_refresh_mark_triggered("alice")
        assert server._intel_refresh_cooldown_remaining("alice") > 0

    def test_cooldown_is_per_user(self):
        server._intel_refresh_mark_triggered("alice")
        assert server._intel_refresh_cooldown_remaining("bob") == 0

    def test_cooldown_expires(self, monkeypatch):
        server._intel_refresh_mark_triggered("alice")
        blocked = server._intel_refresh_cooldown_remaining("alice")
        assert blocked > 0
        # Advance past the window.
        real = server.time.monotonic()
        monkeypatch.setattr(
            server.time,
            "monotonic",
            lambda: real + server._INTEL_MANUAL_REFRESH_COOLDOWN_SEC + 1,
        )
        assert server._intel_refresh_cooldown_remaining("alice") == 0

    def test_zero_cooldown_disables_the_guard(self, monkeypatch):
        monkeypatch.setattr(server, "_INTEL_MANUAL_REFRESH_COOLDOWN_SEC", 0.0)
        server._intel_refresh_mark_triggered("alice")
        assert server._intel_refresh_cooldown_remaining("alice") == 0

    def test_cron_bearer_path_is_exempt(self):
        """The cron is the intended scheduled driver — throttling it
        would defeat the schedule it exists to keep.  The handler only
        computes a cooldown key when the caller is NOT the cron."""
        src = inspect.getsource(server.post_intel_refresh)
        assert "is_cron = _intel_bearer_auth_ok(request)" in src
        assert "if not is_cron:" in src
        assert "refresh_cooldown" in src

    def test_cooldown_is_stamped_only_after_a_run_starts(self):
        """A 409 (someone else already crawling) must not burn the
        caller's window for work they never got."""
        src = inspect.getsource(server.post_intel_refresh)
        marks = [
            i for i, ln in enumerate(src.splitlines()) if "_intel_refresh_mark_triggered" in ln
        ]
        assert marks, "cooldown is never stamped"
        lines = src.splitlines()
        for idx in marks:
            after = "\n".join(lines[idx : idx + 6])
            assert "202" in after, "stamp must sit on the 202 (started) path"
