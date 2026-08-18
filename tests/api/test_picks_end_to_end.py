"""End-to-end safety rails for draft pick handling.

Draft picks travel the same authoritative pipeline as players:
scraper payload → ``build_api_data_contract`` → ``_compute_unified_rankings``
→ ``playersArray``.  The backend already stamps
``canonicalConsensusRank``, ``rankDerivedValue``, ``sourceRanks``,
``confidenceBucket``, and the full trust/audit block on every pick,
and the frontend now renders them on the rankings board and trade
calculator alongside players.

These tests guard the pick-specific invariants that must never
regress:

1. Picks survive the full contract build (assetClass=="pick", pos=="PICK")
2. Pick canonical ids do not collide with any player canonical name
3. Picks carry a unified rank + value + source ranks
4. Picks do not break ``assert_ranking_coherence`` (no duplicate
   ranks, monotonic value decrease, tier alignment)
5. Every top-400 1-src pick has an allowlist reason (or matches the
   structural exemption — expected_sources == matched_sources)
6. Picks from the live ``idpTradeCalc.csv`` do not silently disappear
   from the API output
7. Representative picks (2026 1.01, 1.06, 1.12, 2.06, 2027 Mid 1st)
   are present with positive values

Run with:  python3 -m pytest tests/api/test_picks_end_to_end.py -v
"""

from __future__ import annotations

import csv
import json
import re
import unittest
from pathlib import Path
from typing import Any

from src.api.data_contract import (
    _is_pick_name,
    assert_no_unexplained_single_source,
    assert_ranking_coherence,
    build_api_data_contract,
)


_REPO = Path(__file__).resolve().parents[2]


def _load_contract() -> dict[str, Any] | None:
    """Build a contract from the latest scraper export, or return None."""
    data_dir = _REPO / "exports" / "latest"
    json_files = sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        return None
    with json_files[0].open() as f:
        raw = json.load(f)
    return build_api_data_contract(raw)


def pick_anchor_rounds_by_source(
    raw_or_contract: dict[str, Any] | None,
) -> dict[str, dict[str, set[int]]]:
    """``{source: {year: {rounds that source published}}}`` from ``pickAnchors``.

    PER SOURCE, and that is the whole point: a union across sources hides the
    failure. Measured on the two boards below, the union reports
    ``{1,2,3,4}`` for every year in BOTH cases because `ktc` stayed intact,
    while the per-source view separates them cleanly.

    AUDIT F-30.  The completeness assertion below derives far-future pick
    values from the nearest published future year, per (tier, round).  When a
    pick market truncates its feed that derivation has no input, and C1-U6-D1
    is explicit that a round a source did not publish is ABSENT rather than
    substituted — so the pipeline correctly declines to price the rows.

    Measured 2026-08-18, two consecutive scrapes of the same day:

        15:09   ktc 84 anchors (2026:60 2027:12 2028:12)
                idpTradeCalc 84 anchors (2026:60 2027:12 2028:12)
        17:11   ktc 84 anchors — unchanged
                idpTradeCalc 16 anchors (2026:10 2027:3 2028:3), round 1 only

    `idpTradeCalc` is one of only two families that price picks, so losing its
    2028 rounds 2-4 removed the input for 2029 rounds 2-6: 5 rounds x 3 tiers =
    the exact 15 rows the assertion reported.
    """
    out: dict[str, dict[str, set[int]]] = {}
    anchors = (raw_or_contract or {}).get("pickAnchors")
    if not isinstance(anchors, dict):
        return out
    for source, board in anchors.items():
        if not isinstance(board, dict):
            continue
        per_year: dict[str, set[int]] = {}
        for key in board:
            m = re.match(
                r"^(20\d{2})\s+(?:Early|Mid|Late)\s+([1-6])(?:st|nd|rd|th)$", str(key), re.I
            )
            if m:
                per_year.setdefault(m.group(1), set()).add(int(m.group(2)))
        if per_year:
            out[str(source)] = per_year
    return out


_DEEP_TIER_GENERIC_RE = re.compile(r"^(20\d{2})\s+(Early|Mid|Late)\s+([1-6])(st|nd|rd|th)$", re.I)
_DEEP_TIER_SLOT_RE = re.compile(r"^(20\d{2})\s+Pick\s+([1-6])\.\d{1,2}$", re.I)


def _is_deep_future_tier(name: str) -> bool:
    """Return True if `name` is a deep (R3-R6) pick row that is
    allowed to be unranked/unvalued.  Three categories qualify:

    1. Future-year (>=2027) generic tier rows (e.g. "2028 Late 5th") —
       after the pick-year discount these fall below OVERALL_RANK_LIMIT.
    2. Future-future-year (>=2028) R3+ generic tier rows — when a
       flatter-tail IDP Hill curve lifts deep IDP values slightly,
       2028 R3 picks can fall off the bottom of the cap.  2026/2027
       R3 picks are unaffected.
    3. Any year's R5/R6 generic tier or slot-specific row (e.g.
       "2026 Late 5th", "2026 Pick 6.03") — these are so deep on the
       board (below the last offensive veteran and IDP rookie) that
       they often fall off the bottom of the OVERALL_RANK_LIMIT cap.
       With FootballGuys SF + IDP added, the ranked board grew by
       ~750 matches and deep R5/R6 picks now routinely fall off.
    """
    s = str(name or "")
    # Generic tier rows ("Early 1st", "Mid 2nd", etc.).
    m = _DEEP_TIER_GENERIC_RE.match(s)
    if m:
        year = int(m.group(1))
        rnd = int(m.group(3))
        if year >= 2027 and rnd >= 4:
            return True
        if year >= 2028 and rnd >= 2:
            # 2028 R2-R3 generic tier rows sit near the OVERALL_RANK_LIMIT
            # cutoff after the future-year discount + Final Framework
            # PR 4 soft-fallback reshaping.  They're still in the
            # playersArray with a value, just off the ranked board.
            return True
        if rnd >= 5:  # any year's deep R5/R6 generic tier
            return True
        return False
    # Slot-specific rows ("2026 Pick 5.11", "2026 Pick 6.03").
    m = _DEEP_TIER_SLOT_RE.match(s)
    if m:
        rnd = int(m.group(2))
        return rnd >= 5
    return False


def _slot_pick_round(name: str) -> int | None:
    """Extract round number from a slot-specific pick name like
    '2026 Pick 3.06'. Returns None for non-slot-pick names."""
    import re

    m = re.match(r"^\d{4}\s+Pick\s+(\d+)\.\d+$", str(name or "").strip())
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            pass
    return None


def _pick_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in contract.get("playersArray", []) if r.get("assetClass") == "pick"]


def _player_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in contract.get("playersArray", []) if r.get("assetClass") != "pick"]


class TestPicksPresentInContract(unittest.TestCase):
    """Picks must survive the full contract build."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")

    def test_picks_present_in_players_array(self) -> None:
        picks = _pick_rows(self.contract)
        # The scraper payload currently carries ~120 distinct pick
        # canonical names (slot-specific 2026 Pick 1.01..6.12 +
        # generic 2027/2028 Early/Mid/Late × 1st..4th).  Require at
        # least 60 as a sanity floor — enough that a regression where
        # picks are dropped entirely (or scoped-out of the board) would
        # trip the test but shallow data drift does not.
        self.assertGreaterEqual(
            len(picks),
            60,
            f"Too few picks in playersArray: {len(picks)}",
        )

    def test_every_pick_is_PICK_position(self) -> None:
        picks = _pick_rows(self.contract)
        bad = [p for p in picks if p.get("position") != "PICK"]
        self.assertEqual(
            bad,
            [],
            "Pick rows with wrong position: "
            f"{[(p['canonicalName'], p.get('position')) for p in bad[:5]]}",
        )

    def test_every_pick_has_rank_and_value(self) -> None:
        # VALUE is unconditional since C1-U6 (manifest C1-PICK-01):
        # every non-suppressed pick row publishes a finite positive
        # canonical value — the deep-tier "allowed to be unvalued"
        # tolerance this test used to carry is retired.  RANK remains
        # legitimately absent for the known rank-less classes:
        #   1. Alias-suppressed current-year generic tiers (value also
        #      absent there — the alias's centre slot carries it).
        #   2. Slot-specific picks in the anchor year — rookie-tethered
        #      by value, intentionally un-ranked.
        #   3. Off-cap or derived pick rows (round-step / generic-grade
        #      / below OVERALL_RANK_LIMIT) — valued, never ranked.
        picks = _pick_rows(self.contract)

        # AUDIT F-30 — this assertion tests OUR derivation, not the vendors'
        # uptime, and the difference decides whether a truncated upstream feed
        # is allowed to redden every open PR.
        #
        # It lives in the HARD gate (`-m "not livedata"`) and builds from the
        # LIVE committed board, which `docs/ops/STABILIZATION_2026-08-16.md`
        # §3d forbids precisely because the result is a function of which
        # sources answered the last scrape.  On 2026-08-18 that bit: a single
        # `idpTradeCalc` pick-board truncation left 15 unpriced 2029 rows and
        # turned every open PR red — the incident that stabilization was
        # written to prevent, reached through a different door.
        #
        # `tests/archive_fixtures.newest_complete_raw_payload()` is the
        # prescribed escape and does NOT help here: it classifies degradation
        # off `settings.sourceRunSummary`, and `failedSources` is ABSENT from
        # all 176 committed archives, so a silently truncated pick board still
        # reads as complete.  (That blind spot is census S-2.)
        #
        # So skip on the PREMISE the assertion depends on: pick anchors that
        # actually cover the rounds a horizon year must derive from.  The guard
        # keeps its teeth — if our code breaks while anchors are complete this
        # still fails — and the live-board question stays owned by
        # `validate_api_data_contract`'s pick census, which is advisory on PRs
        # and blocking at deploy.
        published = pick_anchor_rounds_by_source(self.contract)
        thin = {
            src: {y: sorted(r) for y, r in years.items() if len(r) < 4}
            for src, years in published.items()
        }
        thin = {src: cells for src, cells in thin.items() if cells}
        if thin:
            self.skipTest(
                f"a pick market truncated its feed ({thin}) — the far-future "
                "derivation has no input for the missing rounds, so this would "
                "assert vendor uptime rather than our code (F-30). The contract "
                "pick census owns the live-board question."
            )

        value_missing_rows = [
            p["canonicalName"]
            for p in picks
            if not p.get("pickGenericSuppressed")
            and (not p.get("rankDerivedValue") or p.get("rankDerivedValue", 0) <= 0)
        ]
        self.assertEqual(
            value_missing_rows,
            [],
            f"Picks missing a finite canonical value: {value_missing_rows[:10]}",
        )
        # Ranked-or-known-rank-less: a RANKED pick must also be valued.
        rank_no_value = [
            p["canonicalName"]
            for p in picks
            if p.get("canonicalConsensusRank") and not p.get("rankDerivedValue")
        ]
        self.assertEqual(rank_no_value, [], f"Ranked picks without value: {rank_no_value[:10]}")
        # 2026 slot picks in rounds 1-4 must have VALUE (anchored to
        # the corresponding rookie). Later-round slot picks depend on
        # rookie universe depth; if the rookie list runs out before
        # round 5-6, some deep picks legitimately end up without an
        # anchored value — this mirrors the pre-change behaviour where
        # those picks had tier-value approximations only.
        slot_2026_early = [
            p
            for p in picks
            if str(p.get("canonicalName") or "").startswith("2026 Pick ")
            and _slot_pick_round(p.get("canonicalName") or "") in (1, 2, 3, 4)
        ]
        value_missing = [
            p["canonicalName"]
            for p in slot_2026_early
            if not p.get("rankDerivedValue") or p.get("rankDerivedValue", 0) <= 0
        ]
        self.assertEqual(
            value_missing,
            [],
            f"2026 rounds 1-4 slot picks missing anchored value: {value_missing[:5]}",
        )

    def test_every_pick_has_source_ranks(self) -> None:
        # sourceRanks reflect VOTES, and three classes legitimately
        # carry none: suppressed generic tiers, derived rows (round-step
        # completions and generic-grade rows carry provenance instead of
        # votes — no vendor prices them), and deep tethered slot rows.
        picks = _pick_rows(self.contract)
        empty = [
            p["canonicalName"]
            for p in picks
            if not (p.get("sourceRanks") or {})
            and not p.get("pickGenericSuppressed")
            and (p.get("pickValueProvenance") or {}).get("class")
            not in ("derived_round_step", "derived_uniform_tier_ev", "rookie_pool_tether")
            and not _is_deep_future_tier(p["canonicalName"])
        ]
        self.assertEqual(empty, [], f"Picks with no sourceRanks: {empty[:10]}")


class TestPickCanonicalIdentity(unittest.TestCase):
    """Pick canonical ids must not collide with player names."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")

    def test_pick_names_match_pick_detector(self) -> None:
        picks = _pick_rows(self.contract)
        bad = [p["canonicalName"] for p in picks if not _is_pick_name(p["canonicalName"] or "")]
        self.assertEqual(
            bad,
            [],
            f"assetClass=='pick' rows whose name fails _is_pick_name: {bad[:5]}",
        )

    def test_pick_names_unique_against_players(self) -> None:
        picks = _pick_rows(self.contract)
        players = _player_rows(self.contract)
        pick_names = {p["canonicalName"] for p in picks}
        player_names = {p["canonicalName"] for p in players}
        collisions = pick_names & player_names
        self.assertEqual(
            collisions,
            set(),
            f"Pick canonical names collide with player names: {sorted(collisions)[:5]}",
        )

    def test_no_player_name_accidentally_flagged_as_pick(self) -> None:
        players = _player_rows(self.contract)
        flagged = [
            p["canonicalName"] for p in players if _is_pick_name(p.get("canonicalName") or "")
        ]
        self.assertEqual(
            flagged,
            [],
            f"Player rows whose name matches pick pattern: {flagged[:5]}",
        )


class TestPicksDoNotBreakSafetyRails(unittest.TestCase):
    """Picks must coexist with the board-level assertions."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")

    def test_ranking_coherence_with_picks(self) -> None:
        # ``assert_ranking_coherence`` walks rows in the order supplied
        # and requires strictly increasing ranks, so the caller is
        # responsible for sorting by rank first.  Existing coherence
        # tests (tests/api/test_ranking_coherence.py) sort the same way.
        ranked = sorted(
            [r for r in self.contract["playersArray"] if r.get("canonicalConsensusRank")],
            key=lambda r: int(r["canonicalConsensusRank"]),
        )
        errors = assert_ranking_coherence(ranked)
        self.assertEqual(errors, [], "\n".join(errors[:5]))

    def test_no_unexplained_single_source_with_picks(self) -> None:
        # All 1-src picks in the top 400 must either be explicitly
        # allowlisted or structurally single-source (expected ==
        # matched).  The assertion function already handles both cases.
        unexplained = assert_no_unexplained_single_source(
            self.contract["playersArray"], rank_limit=400
        )
        self.assertEqual(
            unexplained,
            [],
            "Unexplained 1-src rows (including any picks): "
            f"{[u['canonicalName'] for u in unexplained[:5]]}",
        )


class TestIdpTradeCalcPicksSurviveEnrichment(unittest.TestCase):
    """Every pick in the IDPTC CSV must end up in the final contract."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")
        csv_path = _REPO / "CSVs" / "site_raw" / "idpTradeCalc.csv"
        if not csv_path.exists():
            self.skipTest("No idpTradeCalc.csv snapshot")
        self.csv_picks: list[str] = []
        with csv_path.open("r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = (row.get("name") or row.get("Name") or "").strip()
                if name and _is_pick_name(name):
                    self.csv_picks.append(name)

    def test_idptc_picks_all_present_in_contract(self) -> None:
        if not self.csv_picks:
            self.skipTest("No picks in idpTradeCalc.csv")
        contract_pick_names = {p["canonicalName"] for p in _pick_rows(self.contract)}
        missing = [n for n in self.csv_picks if n not in contract_pick_names]
        self.assertEqual(
            missing,
            [],
            f"IDPTC picks missing from contract output: {missing[:10]}",
        )


class TestRepresentativePicks(unittest.TestCase):
    """Specific picks from the 7-point verification list must be findable."""

    TARGETS = [
        "2026 Pick 1.01",  # early-1st, slot-specific
        "2026 Pick 1.06",  # mid-1st, slot-specific
        "2026 Pick 1.12",  # late-1st, slot-specific
        "2026 Pick 2.06",  # mid-2nd, slot-specific
        "2027 Mid 1st",  # generic future 1st
    ]

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")
        self.by_name = {p["canonicalName"]: p for p in _pick_rows(self.contract)}

    def test_targets_have_rank_and_value(self) -> None:
        # 2026 slot-specific picks are intentionally un-ranked — they
        # carry the rookie-anchored value only (``rankDerivedValue``)
        # so they don't consume merged-board rank slots. Tier-generic
        # picks and future-year picks still hold real ranks.
        for name in self.TARGETS:
            with self.subTest(pick=name):
                row = self.by_name.get(name)
                self.assertIsNotNone(row, f"{name} missing from pick contract output")
                assert row is not None
                is_2026_slot = name.startswith("2026 Pick ")
                if is_2026_slot:
                    self.assertIsNone(
                        row.get("canonicalConsensusRank"),
                        f"{name} should be un-ranked (anchored to rookie only)",
                    )
                else:
                    self.assertTrue(
                        row.get("canonicalConsensusRank"),
                        f"{name} has no canonicalConsensusRank",
                    )
                self.assertGreater(
                    int(row.get("rankDerivedValue") or 0),
                    0,
                    f"{name} has non-positive rankDerivedValue",
                )
                self.assertEqual(row.get("assetClass"), "pick")
                self.assertEqual(row.get("position"), "PICK")
                # Every target must have at least one ranking source.
                self.assertTrue(
                    (row.get("sourceRanks") or {}),
                    f"{name} has no sourceRanks",
                )

    def test_early_first_has_higher_value_than_late_first(self) -> None:
        """2026 slot picks no longer carry ranks — value is the only
        comparison signal (anchored to the corresponding rookie)."""
        early = self.by_name.get("2026 Pick 1.01")
        late = self.by_name.get("2026 Pick 1.12")
        if not early or not late:
            self.skipTest("Slot-specific 1st not in snapshot")
        self.assertGreater(
            int(early["rankDerivedValue"]),
            int(late["rankDerivedValue"]),
            "Early 1st should have higher value than late 1st",
        )

    def test_anchored_value_survives_legacy_dict_mirror(self) -> None:
        """Anchored slot-pick values must reach the runtime view.

        ``/api/data?view=app`` strips ``playersArray`` and reads from
        the legacy ``players`` dict.  A previous regression had the
        pick legacy-mirror clearing ``rankDerivedValue`` whenever the
        rank was None — that fired on suppressed generic tiers (where
        clearing is correct) AND on anchored slot picks (where it
        silently dropped the rookie-anchored value).  This test pins
        that the legacy dict carries the same anchored value the
        ``playersArray`` row does for every 2026 slot-specific pick.
        """
        legacy = self.contract.get("players") or {}
        pa = self.contract.get("playersArray") or []
        mismatched: list[str] = []
        for row in pa:
            name = str(row.get("canonicalName") or "")
            if not name.startswith("2026 Pick "):
                continue
            if row.get("assetClass") != "pick":
                continue
            pa_value = row.get("rankDerivedValue")
            if pa_value is None or pa_value <= 0:
                continue
            legacy_ref = row.get("legacyRef") or name
            legacy_row = legacy.get(legacy_ref)
            if not isinstance(legacy_row, dict):
                mismatched.append(f"{name}: missing legacy row")
                continue
            legacy_value = legacy_row.get("rankDerivedValue")
            if legacy_value != pa_value:
                mismatched.append(f"{name}: playersArray={pa_value} legacy={legacy_value}")
        self.assertEqual(
            mismatched,
            [],
            "Anchored slot picks lost value in legacy mirror:\n" + "\n".join(mismatched[:10]),
        )


class TestPickValueProjections(unittest.TestCase):
    """``pickProjectedDraftValue`` and friends pin the on-draft value
    estimate for every pick.

    The pick year discount deflates future picks below their on-draft
    equivalent (a 2027 1st today is 82% of a 2026 1.01 because of one
    year of uncertainty + opportunity cost).  ``_stamp_pick_value_projections``
    inverts that discount to project the on-draft value:

        projected = rankDerivedValue / pickYearDiscount

    The frontend reads these stamps to render
    "projected ~X,XXX at the 2027 draft (▲21%)" annotations on pick
    rows in the player popup.
    """

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")
        self.picks = _pick_rows(self.contract)
        if not self.picks:
            self.skipTest("No pick rows in the contract")

    def test_every_pick_carries_projection_stamps(self) -> None:
        """Every pick row with a positive ``rankDerivedValue`` carries
        all four projection fields.  A pick whose ``rankDerivedValue``
        is zero or missing has no projection — that's the documented
        boundary (e.g. extremely deep tier-generic rows that fell off
        the OVERALL_RANK_LIMIT cap)."""
        missing_stamps: list[str] = []
        for row in self.picks:
            rdv = row.get("rankDerivedValue")
            if not isinstance(rdv, (int, float)) or rdv <= 0:
                continue
            for field in (
                "pickProjectedDraftValue",
                "pickProjectedDraftYear",
                "pickProjectedDraftValueGain",
                "pickProjectedDraftValueGainPct",
            ):
                if row.get(field) is None:
                    missing_stamps.append(f"{row.get('canonicalName')}: missing {field}")
        self.assertEqual(
            missing_stamps,
            [],
            "Every valued pick must stamp the full projection block:\n"
            + "\n".join(missing_stamps[:10]),
        )

    def test_baseline_year_picks_project_to_current_value(self) -> None:
        """Baseline-year picks (2026, the current draft) have
        ``pickYearDiscount == 1.0`` (or unstamped, equivalent), so the
        projection equals today's value with zero gain."""
        baseline_picks = [
            r
            for r in self.picks
            if int(r.get("pickProjectedDraftYear") or 0) == 2026
            and (r.get("rankDerivedValue") or 0) > 0
        ]
        if not baseline_picks:
            self.skipTest("No 2026 picks with positive value in contract")
        for row in baseline_picks:
            with self.subTest(pick=row.get("canonicalName")):
                rdv = int(row["rankDerivedValue"])
                self.assertEqual(
                    int(row["pickProjectedDraftValue"]),
                    rdv,
                    "2026 pick projection must equal today's value (no discount to invert)",
                )
                self.assertEqual(int(row["pickProjectedDraftValueGain"]), 0)
                self.assertEqual(int(row["pickProjectedDraftValueGainPct"]), 0)

    def test_future_year_picks_project_above_today(self) -> None:
        """Future-year picks (2027+) have ``pickYearDiscount < 1.0``
        applied, so the projection inverts to a value strictly above
        today's.  Pin the math: projected = round(rdv / discount)."""
        future_picks = [
            r
            for r in self.picks
            if int(r.get("pickProjectedDraftYear") or 0) >= 2027
            and (r.get("rankDerivedValue") or 0) > 0
            and r.get("pickYearDiscount") is not None
        ]
        if not future_picks:
            self.skipTest("No future-year picks with discount in contract")
        for row in future_picks:
            with self.subTest(pick=row.get("canonicalName")):
                rdv = float(row["rankDerivedValue"])
                discount = float(row["pickYearDiscount"])
                expected = int(round(rdv / discount))
                actual = int(row["pickProjectedDraftValue"])
                # Allow ±1 for rounding noise around the int boundary.
                self.assertLessEqual(
                    abs(actual - expected),
                    1,
                    f"projection math drifted: rdv={rdv}, discount={discount}, "
                    f"expected≈{expected}, got {actual}",
                )
                self.assertGreater(
                    actual,
                    int(rdv),
                    f"future-year pick must project ABOVE today's value: "
                    f"rdv={rdv}, projected={actual}",
                )
                self.assertGreater(int(row["pickProjectedDraftValueGain"]), 0)
                self.assertGreater(int(row["pickProjectedDraftValueGainPct"]), 0)

    def test_projection_year_matches_canonical_name(self) -> None:
        """``pickProjectedDraftYear`` extracts the year from the
        canonical name (e.g. ``"2027 Mid 1st"`` → 2027)."""
        for row in self.picks:
            year_stamp = row.get("pickProjectedDraftYear")
            if year_stamp is None:
                continue
            with self.subTest(pick=row.get("canonicalName")):
                name = str(row.get("canonicalName") or "")
                m = re.search(r"\b(20\d{2})\b", name)
                self.assertIsNotNone(m, f"pick name lacks a year but has projection stamp: {name}")
                assert m is not None
                self.assertEqual(int(year_stamp), int(m.group(1)))


if __name__ == "__main__":
    unittest.main()
