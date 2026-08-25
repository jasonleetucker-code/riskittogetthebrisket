"""IDP Show provider family: the combined Top-700 board is the sole vote.

Owner decision (2026-08-20): ``CSVs/site_raw/idpShowCombined.csv`` (the
COMBINED offense+IDP board) is the only ranking source The IDP Show may
contribute.  The older IDP-only board, ``CSVs/site_raw/idpShow.csv``, is
retired from voting — it remains acquired (see ``scripts/fetch_idpshow.py``
and ``deploy/idpshow_fetch_and_push.sh``) but unregistered, the same
acquired-but-inert posture ``draftSharksRosSf.csv`` already has.

This module pins four things:

1. Exactly one ``idpShow*`` key is ever registered as a voting source
   (never both boards at once — same-provider double counting).
2. The registered shape routes the combined board's native combined-pool
   rank through the GLOBAL Hill master via the ``is_cross_market`` /
   ``csv_rank_cross_market_keys`` path, not a shared-market crosswalk
   through another source's ladder.
3. A name that collides across two DIFFERENT canonical players in
   different position groups (issue #1011 — the Minnesota WR Justin
   Jefferson vs the Cleveland LB Justin Jefferson) is WITHHELD from
   voting for both, never attached to the wrong one and never a false
   zero.
4. A name that appears twice for the SAME canonical player (Travis
   Hunter's legitimate two-way listing) is unaffected by (3) — the
   source still votes, using its best entry.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.api import data_contract as dc
from src.api.data_contract import (
    _RANKING_SOURCES,
    _SOURCE_CSV_PATHS,
    _compute_unified_rankings,
    _enrich_from_source_csvs,
)
from src.canonical.rank_coordinates import RANK_POOL_SHARED_MARKET


def _row(name: str, pos: str, *, idp=None, ktc=None) -> dict:
    sites: dict = {}
    if idp is not None:
        sites["idpTradeCalc"] = idp
    if ktc is not None:
        sites["ktc"] = ktc
    return {
        "canonicalName": name,
        "displayName": name,
        "legacyRef": name,
        "position": pos,
        "assetClass": "offense" if pos in {"QB", "RB", "WR", "TE"} else "idp",
        "values": {"overall": 0, "rawComposite": 0, "finalAdjusted": 0, "displayValue": None},
        "canonicalSiteValues": sites,
        "sourceCount": 1,
    }


def _run_with_idpshow_combined_csv(players: list[dict], rows: list[tuple[str, str, int]]) -> None:
    """Enrich ``players`` from a synthetic idpShowCombined.csv.

    ``rows`` is a list of (name, position, rank) tuples matching the
    real vendor CSV shape (``name,position,rank``).
    """
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "idpShowCombined.csv"
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(("name", "position", "rank"))
            for name, pos, rank in rows:
                w.writerow([name, pos, rank])
        patched = dict(_SOURCE_CSV_PATHS)
        patched["idpShowCombined"] = {"path": str(p), "signal": "rank"}
        with mock.patch.object(dc, "_SOURCE_CSV_PATHS", patched):
            _enrich_from_source_csvs(players)


class TestExactlyOneVotingIdpShowKey(unittest.TestCase):
    """Structural guard: never register both IDP Show boards at once.

    This is the guard Task 2/4 of the owner decision asks for — it reads
    the actual production registry objects, not a hand-maintained mirror,
    so a future PR that re-adds ``idpShow`` (or any other ``idpShow*``
    key) alongside ``idpShowCombined`` fails this test immediately.
    """

    def test_ranking_sources_has_exactly_one_idpshow_key(self) -> None:
        matches = [
            str(s.get("key") or "")
            for s in _RANKING_SOURCES
            if str(s.get("key") or "").lower().startswith("idpshow")
        ]
        self.assertEqual(
            matches,
            ["idpShowCombined"],
            "exactly one idpShow* key may vote — found: " f"{matches!r}",
        )

    def test_source_csv_paths_has_exactly_one_idpshow_voting_key(self) -> None:
        matches = [k for k in _SOURCE_CSV_PATHS if k.lower().startswith("idpshow")]
        self.assertEqual(
            matches,
            ["idpShowCombined"],
            "exactly one idpShow* key may be a registered (voting) CSV source — "
            f"found: {matches!r}",
        )

    def test_old_idp_only_board_is_not_a_registered_source(self) -> None:
        self.assertNotIn("idpShow", _SOURCE_CSV_PATHS)
        keys = {str(s.get("key") or "") for s in _RANKING_SOURCES}
        self.assertNotIn("idpShow", keys)


class TestIdpShowCombinedRegistryShape(unittest.TestCase):
    def _entry(self) -> dict:
        return next(s for s in _RANKING_SOURCES if s.get("key") == "idpShowCombined")

    def test_is_cross_market_not_shared_market_translated(self) -> None:
        entry = self._entry()
        self.assertTrue(entry.get("is_cross_market"))
        self.assertFalse(entry.get("needs_shared_market_translation"))

    def test_scope_spans_both_pools(self) -> None:
        entry = self._entry()
        self.assertEqual(entry.get("scope"), dc.SOURCE_SCOPE_OVERALL_IDP)
        self.assertIn(dc.SOURCE_SCOPE_OVERALL_OFFENSE, entry.get("extra_scopes") or [])

    def test_declares_provider_family_for_the_dedup_guard(self) -> None:
        self.assertEqual(self._entry().get("correlation_group"), "idpShow")

    def test_is_not_declared_a_shared_market_bridge(self) -> None:
        # Task 6: this source's own vote is cross-market, but it must not
        # become a declared bridge that seeds OTHER specialists' ladders —
        # that is a different, CARDINAL-shaped commitment this evidence
        # (ordinal) does not support.
        from src.bridges.registry import load_bridge_descriptors

        families = {d.family for d in load_bridge_descriptors()}
        self.assertNotIn("idpShow", families)
        self.assertNotIn("idpShowCombined", families)


class TestIdpShowCombinedEndToEnd(unittest.TestCase):
    """Exercises the real ``_compute_unified_rankings`` pipeline."""

    def _anchor_offense_and_idp(self) -> list[dict]:
        # A small combined offense+IDP anchor population so the blend
        # has something to compute percentiles against.
        return [
            _row("Offense One", "WR", idp=9900, ktc=9900),
            _row("Offense Two", "RB", idp=9500, ktc=9500),
            _row("Myles Garrett", "DL", idp=9000, ktc=None),
        ]

    def test_combined_rank_routes_through_global_cross_market_pool(self) -> None:
        players = self._anchor_offense_and_idp()
        players.append(_row("Aidan Hutchinson", "DL"))
        _run_with_idpshow_combined_csv(
            players,
            [
                ("Bijan Robinson", "RB", 1),
                ("Josh Allen", "QB", 2),
                ("Aidan Hutchinson", "DL", 3),
            ],
        )
        _compute_unified_rankings(players, {})
        hutch = next(r for r in players if r["canonicalName"] == "Aidan Hutchinson")
        self.assertIn("idpShowCombined", hutch.get("canonicalSiteValues", {}))
        meta = (hutch.get("sourceRankMeta") or {}).get("idpShowCombined") or {}
        self.assertEqual(meta.get("rankCoordinatePool"), RANK_POOL_SHARED_MARKET)
        self.assertEqual(meta.get("method"), "csv_combined_cross_market")

    def test_does_not_need_a_shared_market_ladder_to_vote(self) -> None:
        # No idpTradeCalc / draftSharks backbone at all — an
        # idpShowCombined-only IDP row must still vote, because its own
        # rank is already a combined-pool ordinal.
        players = [
            _row("Offense One", "WR", ktc=9900),
            _row("Offense Two", "RB", ktc=9500),
            _row("Aidan Hutchinson", "DL"),
        ]
        _run_with_idpshow_combined_csv(
            players,
            [
                ("Bijan Robinson", "RB", 1),
                ("Josh Allen", "QB", 2),
                ("Aidan Hutchinson", "DL", 3),
            ],
        )
        _compute_unified_rankings(players, {})
        hutch = next(r for r in players if r["canonicalName"] == "Aidan Hutchinson")
        self.assertIn("idpShowCombined", hutch.get("sourceRanks", {}))


class TestCrossPositionNameCollisionWithheld(unittest.TestCase):
    """Issue #1011: two real, different people sharing a name."""

    def test_offense_and_idp_namesakes_are_both_withheld(self) -> None:
        players = [
            _row("Justin Jefferson", "WR"),  # the real Minnesota WR
            _row("Justin Jefferson", "LB"),  # the real Cleveland LB
        ]
        _run_with_idpshow_combined_csv(
            players,
            [
                # The vendor's own position label is untrustworthy here —
                # both rows say "LB" even though rank 13 is really the WR
                # (measured 2026-08-20) — so position-based disambiguation
                # is not attempted; both entries are withheld.
                ("Justin Jefferson", "LB", 13),
                ("Justin Jefferson", "LB", 622),
            ],
        )
        wr_row = players[0]
        lb_row = players[1]
        self.assertNotIn("idpShowCombined", wr_row.get("canonicalSiteValues", {}))
        self.assertNotIn("idpShowCombined", lb_row.get("canonicalSiteValues", {}))
        summary = dc._LAST_CONTRACT_JOIN_SUMMARY or {}
        withheld = summary.get("withheldForCrossGroupNameCollision") or {}
        self.assertIn("justin jefferson", withheld.get("idpShowCombined", []))

    def test_same_name_different_team_offense_idp_collision(self) -> None:
        # Byron Murphy: a DL (Seattle) and a CB (Minnesota) — two real
        # people, both IDP-adjacent-but-different groups is not this
        # shape, so use the DL/WR shape which is the one the join logic
        # actually distinguishes on (position GROUP, not full position).
        players = [
            _row("Byron Murphy", "DL"),
            _row("Byron Murphy", "WR"),
        ]
        _run_with_idpshow_combined_csv(
            players,
            [
                ("Byron Murphy", "DL", 237),
                ("Byron Murphy", "DL", 588),
            ],
        )
        for row in players:
            self.assertNotIn("idpShowCombined", row.get("canonicalSiteValues", {}))


class TestSingleCanonicalPlayerDuplicateStillVotes(unittest.TestCase):
    """Travis Hunter: one real person, listed twice by the vendor.

    Must NOT be destroyed by the cross-group withholding above — there
    is only one canonical position group here, so this never enters the
    ambiguous-groups branch.
    """

    def test_two_way_player_still_gets_a_vote(self) -> None:
        players = [_row("Travis Hunter", "DB")]
        _run_with_idpshow_combined_csv(
            players,
            [
                ("Travis Hunter", "DB", 109),
                ("Travis Hunter", "DB", 214),
            ],
        )
        sites = players[0]["canonicalSiteValues"]
        self.assertIn("idpShowCombined", sites)
        self.assertGreater(sites["idpShowCombined"], 0)
        summary = dc._LAST_CONTRACT_JOIN_SUMMARY or {}
        withheld = summary.get("withheldForCrossGroupNameCollision") or {}
        self.assertNotIn("travis hunter", withheld.get("idpShowCombined", []))


if __name__ == "__main__":
    unittest.main()
