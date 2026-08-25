"""V1-89: the ROS fetcher must PROVE it is looking at the league's board.

THE GAP.  ``scripts/fetch_draftsharks.py`` proves each pass is
league-scored by showing the WebAssembly worker rewrote values away from
the static ``data-scoring-value-*`` public defaults, and it fails closed
when it cannot.  ``scripts/fetch_draftsharks_ros.py`` had no equivalent:
it checked that a cookie FILE existed and published whatever came back.
An expired jar still renders a public board and still exits 0 — which
would stamp a fresh success over public data.

WHY THE PROOF IS DIFFERENT HERE, and this is the part worth not
"fixing" later: the ROS pages carry **zero** ``data-scoring-value``
attributes (measured 2026-08-25 against the live public pages), so there
is no public default to diverge from.  Copying the dynasty proof would
produce a predicate that is true of every page, authenticated or not —
a proof of nothing.  The two assertions used instead are the strongest
ones the pages actually expose, and BOTH are required because either
alone is bypassable: a cached shell can carry the league marker with no
board behind it, and a full public board can carry no marker at all.

The fixtures are synthetic and deliberately minimal.  What is measured
from the live site is recorded in ``_ROS_ROW_FLOORS``: an unauthenticated
fetch renders 25 rows and 0 league markers; the authenticated boards
carried 250 (SF) and 425 (IDP).
"""

from __future__ import annotations

import unittest

from scripts import fetch_draftsharks as ds_dynasty
from scripts import fetch_draftsharks_ros as ros


def _rows(n: int) -> list[dict]:
    return [{"name": f"Player {i}", "pos": "WR"} for i in range(n)]


def _authenticated_shell(extra: str = "") -> str:
    return (
        "<html><body><header><span class='league-name'>"
        f"{ros.LEAGUE_NAME}</span></header>"
        f"<table id='rankings'>{extra}</table></body></html>"
    )


def _public_shell() -> str:
    """What an expired/absent session renders: a real-looking board with
    a sign-in prompt and no league selected."""
    return (
        "<html><body><header><a href='/login'>Sign in</a>"
        "<span class='league-name'>Select a league</span></header>"
        "<table id='rankings'><tbody data-player-row></tbody></table>"
        "</body></html>"
    )


class TestTheProofIsNotVacuous(unittest.TestCase):
    def test_the_league_marker_is_absent_from_the_public_shell(self) -> None:
        """Guard on the guard: if the fixture happened to contain the
        marker, every assertion below would pass by checking nothing."""
        self.assertNotIn(ros.LEAGUE_NAME.casefold(), _public_shell().casefold())

    def test_the_floors_sit_above_a_public_board_and_below_a_live_one(self) -> None:
        for url, floor in ros._ROS_ROW_FLOORS.items():
            with self.subTest(url=url):
                # An unauthenticated page rendered 25 rows.
                self.assertGreater(floor, 25)
                # ...and the live boards were 250 / 425, so a floor must
                # leave real headroom rather than pin today's count.
                self.assertLess(floor, 250)

    def test_the_league_name_matches_the_minting_fetcher(self) -> None:
        """Two spellings of the league would let one fetcher prove
        something the other cannot."""
        self.assertEqual(ros.LEAGUE_NAME, ds_dynasty.LEAGUE_NAME)


class TestMutationA_Authenticated(unittest.TestCase):
    def test_marker_plus_adequate_rows_passes(self) -> None:
        for url, floor in ros._ROS_ROW_FLOORS.items():
            with self.subTest(url=url):
                ros.prove_ros_page_is_league_scoped(
                    url=url,
                    html=_authenticated_shell(),
                    rows=_rows(floor + 5),
                )

    def test_exactly_at_the_floor_passes(self) -> None:
        """The floor is a minimum, not a strict bound — an off-by-one
        here would reject a healthy board on a quiet week."""
        url = ros.ROS_SF_URL
        ros.prove_ros_page_is_league_scoped(
            url=url, html=_authenticated_shell(), rows=_rows(ros._ROS_ROW_FLOORS[url])
        )


class TestMutationB_MarkerRemoved(unittest.TestCase):
    def test_same_rows_without_the_league_marker_fails_closed(self) -> None:
        url = ros.ROS_SF_URL
        with self.assertRaises(ros.RosAuthError) as ctx:
            ros.prove_ros_page_is_league_scoped(
                url=url,
                html="<html><body><table id='rankings'></table></body></html>",
                rows=_rows(500),
            )
        self.assertIn("auth_required", str(ctx.exception))

    def test_an_empty_page_is_auth_required_not_merely_quiet(self) -> None:
        with self.assertRaises(ros.RosAuthError):
            ros.prove_ros_page_is_league_scoped(url=ros.ROS_SF_URL, html="", rows=_rows(500))


class TestMutationC_PublicDefaultPage(unittest.TestCase):
    def test_a_valid_looking_cookie_jar_serving_a_public_page_fails(self) -> None:
        """The whole point: the jar existing proves nothing about what
        came back."""
        for url in (ros.ROS_SF_URL, ros.ROS_IDP_URL):
            with self.subTest(url=url):
                with self.assertRaises(ros.RosAuthError) as ctx:
                    ros.prove_ros_page_is_league_scoped(
                        url=url, html=_public_shell(), rows=_rows(25)
                    )
                self.assertIn("auth_required", str(ctx.exception))


class TestMutationD_TruncatedBoard(unittest.TestCase):
    def test_marker_present_but_implausible_population_fails(self) -> None:
        for url, floor in ros._ROS_ROW_FLOORS.items():
            with self.subTest(url=url):
                with self.assertRaises(ros.RosAuthError) as ctx:
                    ros.prove_ros_page_is_league_scoped(
                        url=url, html=_authenticated_shell(), rows=_rows(floor - 1)
                    )
                self.assertIn("implausible_population", str(ctx.exception))

    def test_zero_rows_behind_a_valid_marker_fails(self) -> None:
        with self.assertRaises(ros.RosAuthError):
            ros.prove_ros_page_is_league_scoped(
                url=ros.ROS_SF_URL, html=_authenticated_shell(), rows=[]
            )

    def test_an_unknown_url_has_no_floor_and_leans_on_the_marker(self) -> None:
        """Explicit, so it is a decision rather than an accident: a URL
        with no configured floor is still gated by the marker."""
        ros.prove_ros_page_is_league_scoped(
            url="https://www.draftsharks.com/ros-rankings/other",
            html=_authenticated_shell(),
            rows=_rows(1),
        )
        with self.assertRaises(ros.RosAuthError):
            ros.prove_ros_page_is_league_scoped(
                url="https://www.draftsharks.com/ros-rankings/other",
                html=_public_shell(),
                rows=_rows(1),
            )


class TestTheProofIsWiredIn(unittest.TestCase):
    """A correct predicate nothing calls proves nothing."""

    def test_the_page_fetch_calls_the_proof(self) -> None:
        import inspect

        src = inspect.getsource(ros._fetch_page)
        self.assertIn("prove_ros_page_is_league_scoped", src)

    def test_an_auth_failure_aborts_before_any_csv_write(self) -> None:
        """Fail-closed means last-good survives.  If the auth branch fell
        through to the writers, a rejected page would truncate both CSVs
        to a header — worse than the gap being closed."""
        import inspect

        src = inspect.getsource(ros.main_async)
        self.assertIn("except RosAuthError", src)
        write_at = src.index("_write_csv")
        for handler in [m for m in src.split("except RosAuthError")[1:]]:
            self.assertIn("return 2", handler[: handler.index("except Exception")])
        self.assertLess(src.index("except RosAuthError"), write_at)

    def test_a_failed_sf_fetch_preserves_last_good(self) -> None:
        import inspect

        src = inspect.getsource(ros.main_async)
        self.assertIn("sf_page_failed", src)
        self.assertIn("preserving last-good", src)


if __name__ == "__main__":
    unittest.main()
