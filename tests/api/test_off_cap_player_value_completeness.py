"""#1101 — a rank cap may withhold a RANK; it may not erase a VALUE.

THE INVARIANT
─────────────
If a player is ranked or priced by any trusted dynasty source eligible to
participate in canonical valuation, and the canonical pipeline computes a
positive blend for that player, the board must publish a canonical
``rankDerivedValue`` for them — whether or not they survive
``OVERALL_RANK_LIMIT``.

Two concepts, deliberately separate:

  A. canonical VALUE availability   — ``rankDerivedValue``
  B. canonical TOP-BOARD membership — ``canonicalConsensusRank`` / tier

``OVERALL_RANK_LIMIT`` answers B and only B.  A row past it legitimately
publishes ``rankDerivedValue > 0`` beside ``canonicalConsensusRank: None``
and ``canonicalTierId: None``, and every test here asserts that pairing
rather than treating it as an inconsistency to be smoothed over.

WHAT THIS IS NOT
────────────────
Not a Trey Lance exception.  He is one witness (``TestTreyLance``), on
real tracked source evidence, and his expected canonical output is NOT
pinned to any historical number — the assertion is that legitimate
evidence cannot disappear into "unpriced", never that it reproduces a
particular value.  The general invariant is asserted on a synthetic board
built to be > ``OVERALL_RANK_LIMIT`` deep, so it holds for the population
rather than for one name.

MISSING IS NEVER ZERO — AND NEVER ONE
─────────────────────────────────────
The floor rule runs one way only.  Positive canonical evidence must
publish at least ``DISPLAY_SCALE_MIN``; ABSENT evidence must publish
nothing at all.  ``TestMissingStaysMissing`` is the control that keeps
the first half from quietly becoming "everything gets a 1".
"""

from __future__ import annotations

import contextlib
import io
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest

from src.api.data_contract import (
    OVERALL_RANK_LIMIT,
    build_api_data_contract,
)
from src.canonical.player_valuation import DISPLAY_SCALE_MIN
from tests.archive_fixtures import newest_complete_raw_payload

# ── Synthetic board ────────────────────────────────────────────────────
#
# Deep enough that the cap is genuinely exercised: ``N_PLAYERS`` sits
# comfortably past ``OVERALL_RANK_LIMIT`` so a well-defined off-cap
# population exists no matter how the sort resolves ties.
#
# Every synthetic player carries the SAME multi-source coverage, so the
# only thing separating an on-cap row from an off-cap one is its market
# value — which is exactly the variable the invariant is about.  A row
# that differed in coverage as well would let a failure be explained by
# the coverage instead of by the cap.

N_PLAYERS = OVERALL_RANK_LIMIT + 220
TARGET_OFFSET = 40
#: The witness: far enough past the cut that no tie-break can pull it back.
TARGET_NAME = f"Depth Player {OVERALL_RANK_LIMIT + TARGET_OFFSET:04d}"
#: A control with no source coverage whatsoever — see TestMissingStaysMissing.
NO_EVIDENCE_NAME = "No Evidence Player"


def _raw_payload() -> dict:
    players: dict[str, dict] = {}
    # Descend in steps of 10 from 9000 so ranks are strictly ordered and
    # no two rows tie; the deepest row still lands well above zero, so
    # nothing here is priced by the floor rather than by its evidence.
    market = 9000
    for i in range(1, N_PLAYERS + 1):
        sites = {
            "ktcSfTep": market,
            "idpTradeCalc": market,
            "draftSharks": market,
            "dlfSf": market,
            "fantasyProsSf": market,
        }
        row = {"_canonicalSiteValues": dict(sites), "position": "WR", "age": 25}
        row.update(sites)
        players[f"Depth Player {i:04d}"] = row
        market -= 10

    # No ``_canonicalSiteValues``, no per-site keys: nothing matched this
    # player, so no source rank exists and the row never enters the blend.
    players[NO_EVIDENCE_NAME] = {"position": "WR", "age": 25}

    return {
        "version": "off-cap-value-fixture",
        "date": "2026-08-25",
        "settings": {},
        "sites": {},
        "maxValues": {},
        "players": players,
    }


@lru_cache(maxsize=1)
def _board() -> dict[str, dict]:
    """Rows keyed by display name, built through the production entry point.

    ``csv_root`` points at an empty directory so no site-CSV enrichment
    runs and the fixture's own ``canonicalSiteValues`` are the whole
    input.
    """
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        contract = build_api_data_contract(_raw_payload(), csv_root=Path(tmp))
    return {str(row.get("displayName")): row for row in contract.get("playersArray") or []}


def _off_cap_players(board: dict[str, dict]) -> dict[str, dict]:
    return {
        name: row
        for name, row in board.items()
        if row.get("assetClass") != "pick" and row.get("canonicalConsensusRank") is None
    }


class TestOffCapTrustedPlayerIsPriced:
    """TEST 1 — the general invariant, asserted on the population."""

    def test_the_fixture_actually_exercises_the_cap(self) -> None:
        """Guard against a vacuous pass.

        If the board ever stops producing an off-cap population, every
        assertion below would hold over an empty set and report success
        while testing nothing.
        """
        board = _board()
        ranked = [r for r in board.values() if r.get("canonicalConsensusRank") is not None]
        assert (
            len(ranked) == OVERALL_RANK_LIMIT
        ), f"expected a full {OVERALL_RANK_LIMIT}-row ranked board, got {len(ranked)}"
        assert len(_off_cap_players(board)) >= 100

    def test_target_is_off_cap_and_source_backed(self) -> None:
        row = _board()[TARGET_NAME]
        assert row.get("canonicalConsensusRank") is None
        assert row.get("canonicalTierId") is None
        source_ranks = row.get("sourceRanks") or {}
        assert len(source_ranks) >= 2, source_ranks

    def test_target_carries_a_finite_canonical_value_at_or_above_the_floor(self) -> None:
        value = _board()[TARGET_NAME].get("rankDerivedValue")
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        assert value == value and value not in (float("inf"), float("-inf"))  # finite
        assert value >= DISPLAY_SCALE_MIN

    def test_every_source_backed_off_cap_player_is_priced(self) -> None:
        """The population, not the witness.

        A fix that priced only the target — or only the first N rows past
        the cut — passes the test above and fails this one.
        """
        unpriced = [
            name
            for name, row in _off_cap_players(_board()).items()
            if (row.get("sourceRanks") or {})
            and not (isinstance(row.get("rankDerivedValue"), (int, float)))
        ]
        assert (
            unpriced == []
        ), f"{len(unpriced)} source-backed off-cap players unpriced: {unpriced[:5]}"

    def test_priced_off_cap_players_never_fall_below_the_canonical_floor(self) -> None:
        """The floor rule, asserted as a property rather than as teeth.

        No row on any board measured so far comes near it — the Hill tail
        puts the deepest off-cap blend around 155 — so this currently
        discriminates nothing, and saying so is more useful than letting
        a future reader assume it caught something.  It is the assertion
        that stops a truncation from publishing 0 the day the tail moves.
        """
        below = {
            name: row.get("rankDerivedValue")
            for name, row in _off_cap_players(_board()).items()
            if isinstance(row.get("rankDerivedValue"), (int, float))
            and row["rankDerivedValue"] < DISPLAY_SCALE_MIN
        }
        assert below == {}, below

    def test_pricing_a_row_never_promotes_it_onto_the_top_board(self) -> None:
        """Value availability must not leak into board membership.

        A priced off-cap row keeps ``None`` for every ranking field.  The
        percentile is included because it is a STANDING within the ranked
        pool — a row outside that pool has no standing in it, and a
        number there would be a fabricated rank wearing another name.
        """
        offenders = {
            name: (
                row.get("canonicalConsensusRank"),
                row.get("canonicalTierId"),
                row.get("canonicalPercentile"),
            )
            for name, row in _off_cap_players(_board()).items()
            if row.get("rankDerivedValue") is not None
            and (
                row.get("canonicalConsensusRank") is not None
                or row.get("canonicalTierId") is not None
                or row.get("canonicalPercentile") is not None
            )
        }
        assert offenders == {}, offenders

    def test_priced_off_cap_players_are_marked_as_such(self) -> None:
        """Provenance: a consumer must be able to tell WHY a row has a
        value but no rank, without inferring it from the absence."""
        unmarked = [
            name
            for name, row in _off_cap_players(_board()).items()
            if row.get("rankDerivedValue") is not None and not row.get("offCapPlayerValue")
        ]
        assert unmarked == [], unmarked


class TestConfidenceIsAssessedNotAsserted:
    """A newly priced row must not become a newly CONFIDENT row.

    The gate in ``src/api/confidence.py`` is the only thing that decides a
    level, and the off-cap pass feeds it the same evidence assembly the
    ranked path uses.  What it may never do is claim ``high`` — or leave
    the row saying ``unpriced`` — merely because a value now exists.
    """

    def test_a_priced_row_no_longer_claims_to_be_unpriced(self) -> None:
        stale = {
            name: row.get("confidenceBasis")
            for name, row in _off_cap_players(_board()).items()
            if row.get("rankDerivedValue") is not None
            and row.get("confidenceBasis") in ("unpriced", "no_evidence", None)
        }
        assert stale == {}, stale

    def test_no_off_cap_player_is_promoted_to_high_confidence(self) -> None:
        promoted = {
            name: row.get("confidenceBucket")
            for name, row in _off_cap_players(_board()).items()
            if row.get("rankDerivedValue") is not None
            and str(row.get("confidenceBucket")) == "high"
        }
        assert promoted == {}, promoted

    def test_the_assessment_publishes_its_own_axes_and_reasons(self) -> None:
        """Auditable, not merely stamped: the level has to arrive with the
        evidence it was read from."""
        row = _board()[TARGET_NAME]
        assert row.get("confidenceBasis") == "evidence_gate"
        assert isinstance(row.get("confidenceAxes"), dict) and row["confidenceAxes"]
        assert isinstance(row.get("confidenceReasons"), list) and row["confidenceReasons"]
        # The post-Hampel set the assessment actually read, published so
        # the level can be checked against it rather than taken on trust.
        assert isinstance(row.get("effectiveSourceRanks"), dict)
        assert row["effectiveSourceRanks"]


class TestMissingStaysMissing:
    """TEST 3 — the control.

    ``MISSING IS NEVER ZERO`` and it is never ``DISPLAY_SCALE_MIN``
    either.  A floor is what a REAL value is held above; it is not what a
    missing one becomes.
    """

    def test_a_player_with_no_source_evidence_is_never_priced(self) -> None:
        row = _board()[NO_EVIDENCE_NAME]
        assert not (row.get("sourceRanks") or {}), "fixture drifted: control gained sources"
        assert row.get("rankDerivedValue") is None
        assert not row.get("offCapPlayerValue")

    def test_the_control_is_not_priced_through_the_values_bundle_either(self) -> None:
        """A value laundered into ``values.*`` is the same defect under a
        different field name."""
        values = _board()[NO_EVIDENCE_NAME].get("values") or {}
        for key in ("overall", "finalAdjusted", "displayValue"):
            assert values.get(key) is None, (key, values.get(key))

    def test_nothing_on_the_board_is_priced_without_source_evidence(self) -> None:
        """The population form of the control.

        Picks are excluded: a derived pick is priced from the pick
        completeness owner (year-step / round-step / generic tier EV),
        which is a different and separately authorized evidence class.
        """
        fabricated = [
            name
            for name, row in _board().items()
            if row.get("assetClass") != "pick"
            and row.get("rankDerivedValue") is not None
            and not (row.get("sourceRanks") or {})
        ]
        assert fabricated == [], fabricated


class TestLegacyMirror:
    """TEST 6 — one asset, one value, whichever shape the consumer reads.

    The runtime view strips ``playersArray``, so the legacy dict is what a
    real frontend build sees.  A value published in one and not the other
    is the row carrying two answers.
    """

    def test_legacy_dict_agrees_with_the_canonical_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            contract = build_api_data_contract(_raw_payload(), csv_root=Path(tmp))
        legacy = contract.get("players") or {}
        rows = contract.get("playersArray") or []
        checked = 0
        for row in rows:
            if row.get("assetClass") == "pick" or not row.get("offCapPlayerValue"):
                continue
            ref = row.get("legacyRef")
            pdata = legacy.get(ref)
            if not isinstance(pdata, dict):
                continue
            assert pdata.get("rankDerivedValue") == row.get("rankDerivedValue"), ref
            checked += 1
        assert checked > 0, "no off-cap player reached the legacy dict — test is vacuous"


class TestTopBoardIsInert:
    """TEST 4 — this repair ADDS values below the cap; it reprices nothing.

    Measured out-of-band on the pinned 2026-08-25 archive board
    (``dynasty_export_20260825_073239.zip``), before vs after: 0 of 740
    ranked rows moved value, 0 moved rank, 0 moved tier, and 186 off-cap
    players were newly priced in the range 155..1186.

    What is asserted HERE is the structural property that MAKES that true
    and keeps it true: the off-cap pass iterates
    ``row_normalized[OVERALL_RANK_LIMIT:]``, a slice positionally disjoint
    from the ``[:OVERALL_RANK_LIMIT]`` the ranked pass enumerates, so no
    ranked row is reachable from it.  A future edit that widened the slice
    would break the disjointness these tests check.
    """

    def test_no_ranked_row_was_written_by_the_off_cap_pass(self) -> None:
        board = _board()
        touched = {
            name: row.get("canonicalConsensusRank")
            for name, row in board.items()
            if row.get("canonicalConsensusRank") is not None
            and (row.get("offCapPlayerValue") or row.get("offCapPickValue"))
        }
        assert touched == {}, touched

    def test_the_ranked_board_is_contiguous_and_complete(self) -> None:
        """If the off-cap pass had promoted or displaced anything, the
        ranked ordinals would not still be exactly 1..N."""
        ranks = sorted(
            row["canonicalConsensusRank"]
            for row in _board().values()
            if row.get("canonicalConsensusRank") is not None
        )
        assert ranks == list(range(1, len(ranks) + 1))

    def test_every_ranked_row_still_carries_a_value(self) -> None:
        missing = [
            name
            for name, row in _board().items()
            if row.get("canonicalConsensusRank") is not None and row.get("rankDerivedValue") is None
        ]
        assert missing == [], missing

    def test_off_cap_values_never_exceed_the_deepest_ranked_value(self) -> None:
        """Ordering sanity: a row past the cut cannot be worth more than
        the last row that made it.  A violation would mean the off-cap
        pass read a different quantity than the sort did.
        """
        board = _board()
        ranked = [
            (row["canonicalConsensusRank"], row.get("rankDerivedValue"))
            for row in board.values()
            if row.get("canonicalConsensusRank") is not None and row.get("assetClass") != "pick"
        ]
        deepest = min(v for _, v in ranked if v is not None)
        over = {
            name: row.get("rankDerivedValue")
            for name, row in _off_cap_players(board).items()
            if isinstance(row.get("rankDerivedValue"), (int, float))
            and row["rankDerivedValue"] > deepest
        }
        assert over == {}, (deepest, over)


class TestNoSecondOwner:
    """TEST 7 — the value comes from the canonical pipeline, and from
    nowhere else.

    The banned fallbacks are the legacy scraper composite family.  They
    live on a different scale, so splicing one in would be a second board
    wearing the canonical field name — the defect class W29-F001 closed.
    """

    BANNED = ("_composite", "_rawComposite", "_finalAdjusted", "composite")

    def test_off_cap_value_is_not_any_banned_composite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            contract = build_api_data_contract(_raw_payload(), csv_root=Path(tmp))
        legacy = contract.get("players") or {}
        checked = 0
        for row in contract.get("playersArray") or []:
            if not row.get("offCapPlayerValue"):
                continue
            pdata = legacy.get(row.get("legacyRef")) or {}
            value = row.get("rankDerivedValue")
            for field in self.BANNED:
                raw = pdata.get(field) if isinstance(pdata, dict) else None
                if raw is None:
                    continue
                assert value != raw, f"{row.get('displayName')}: value came from {field}"
            checked += 1
        assert checked > 0

    def test_the_off_cap_value_is_the_pipeline_blend_the_row_already_carried(self) -> None:
        """``_blendedValueUncapped`` is the pre-cap blend the pipeline
        stamped on every row.  The published off-cap value must be that
        number (subject only to the canonical floor), not a second
        computation of it.
        """
        mismatched = {}
        for name, row in _off_cap_players(_board()).items():
            value = row.get("rankDerivedValue")
            if value is None:
                continue
            blend = row.get("_blendedValueUncapped")
            if blend is None:
                mismatched[name] = ("no blend stamp", value)
                continue
            # The ranked path truncates; the floor lifts a sub-1 blend.
            if abs(value - blend) > 1:
                mismatched[name] = (blend, value)
        assert mismatched == {}, mismatched

    def test_the_frontend_materializer_declares_no_value_fallback(self) -> None:
        """Structural: the repair is backend-only by construction.

        ``buildRows`` may assign a local DISPLAY ORDINAL to rows the
        backend left unranked (documented, and unchanged here).  What it
        must never do is turn that ordinal — or any other client-side
        quantity — into a canonical VALUE.
        """
        js = (
            Path(__file__).resolve().parents[2] / "frontend" / "lib" / "dynasty-data.js"
        ).read_text(encoding="utf-8")
        # A frontend value owner would have to WRITE the canonical field.
        for pattern in ("rankDerivedValue =", "rankDerivedValue:"):
            for line in js.splitlines():
                if pattern not in line:
                    continue
                stripped = line.strip()
                # Reads and pass-throughs are fine; a computed assignment
                # from a local ordinal is not.
                assert "computedConsensusRank" not in stripped, stripped


class TestTreyLance:
    """TEST 5 — the reported symptom, on real tracked source evidence.

    Deliberately NOT pinned to 896 / 1095 / 1123.  Those numbers
    established that source coverage exists and what the board used to
    show; they are not a methodology, and asserting them would convert a
    truthfulness invariant into a snapshot of one day's blend.

    The claim under test is only this: evidence this broad cannot
    disappear into "unpriced".
    """

    NAME = "Trey Lance"

    @staticmethod
    @lru_cache(maxsize=1)
    def _real_board() -> tuple[dict | None, str | None]:
        payload, archive = newest_complete_raw_payload()
        if payload is None:
            return None, None
        with contextlib.redirect_stdout(io.StringIO()):
            contract = build_api_data_contract(payload)
        rows = {
            str(row.get("canonicalName") or row.get("displayName")): row
            for row in contract.get("playersArray") or []
        }
        return rows, archive

    def _row(self) -> dict:
        rows, _ = self._real_board()
        if rows is None:
            pytest.skip("no complete archived scrape available")
        row = rows.get(self.NAME)
        if row is None:
            pytest.skip(f"{self.NAME} is not on the archived board")
        return row

    def test_he_carries_qualifying_dynasty_source_evidence(self) -> None:
        source_ranks = self._row().get("sourceRanks") or {}
        assert len(source_ranks) >= 2, source_ranks

    def test_his_canonical_value_is_positive(self) -> None:
        value = self._row().get("rankDerivedValue")
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        assert value >= DISPLAY_SCALE_MIN
        assert value > 0

    def test_a_missing_top_board_rank_is_acceptable_and_a_missing_value_is_not(self) -> None:
        """States the ruling explicitly so a future reader does not
        'repair' the null rank back into a fabricated one."""
        row = self._row()
        if row.get("canonicalConsensusRank") is None:
            assert row.get("canonicalTierId") is None
            assert row.get("offCapPlayerValue") is True
        assert row.get("rankDerivedValue") is not None
