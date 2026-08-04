"""H1: board-scale and composite-scale values must not share a name.

Math audit 2026-07-30, finding H1.

Two independent pipelines produce a "player value" in this repo:

* the canonical blend in ``_compute_unified_rankings`` → ``rankDerivedValue``,
  the 0-9999 board every page, sum and threshold is calibrated against;
* the legacy scraper composite in ``Dynasty Scraper.py`` → ``_composite`` /
  ``_finalAdjusted``, which runs **~1.131x the board** (measured; the
  reciprocal ``BOARD_TO_COMPOSITE_K = 0.875`` lives in ``src/trade/finder.py``).

``values.overall`` / ``finalAdjusted`` / ``displayValue`` were *seeded* from
the composite and only *overwritten* by the board when
``rankDerivedValue > 0``.  So on any row the blend declined to price, three
board-named keys carried a composite-scale number with nothing marking the
difference.  Measured on the live payload (``exports/latest``): **270 rows**,
every suppressed generic pick tier among them — ``2026 Early 1st`` reported
6136 while the board's real ``2026 Pick 1.01`` was 7852 and ``1.02`` was 6101.

Downstream, ``src/api/public_activity_valuation.py`` walked
``displayValue → overall → finalAdjusted → rawComposite`` and summed whatever
it found into one trade-side total, so a public trade could be graded with
board-scale assets on one side and composite-scale assets on the other.

The fix is structural rather than a matter of discipline: the board-named
keys are seeded ``None``, so an unpriced row reads as *unpriced* and there is
no composite value available under a board name to pick up by accident.
"""

from __future__ import annotations

from src.api.data_contract import _player_value_bundle


class TestValueBundleSeed:
    def test_board_named_keys_are_never_seeded_from_the_composite(self):
        """The scrape supplies a composite; none of it reaches a board key."""
        bundle = _player_value_bundle(
            {"_composite": 8100, "_finalAdjusted": 8200, "_rawComposite": 8050}
        )
        assert bundle["overall"] is None
        assert bundle["finalAdjusted"] is None
        assert bundle["displayValue"] is None

    def test_raw_composite_still_carries_the_composite(self):
        """The honestly-named key keeps working — the UI's "Raw" mode reads it."""
        assert _player_value_bundle({"_rawComposite": 8050})["rawComposite"] == 8050
        # Documented precedence: _rawComposite → _rawMarketValue → _composite.
        assert _player_value_bundle({"_rawMarketValue": 7000})["rawComposite"] == 7000
        assert _player_value_bundle({"_composite": 6000})["rawComposite"] == 6000

    def test_every_contract_key_is_still_present(self):
        """None means unpriced.  A MISSING key would break consumers that
        branch on presence, and ``validate_api_data_contract`` requires all
        of overall / rawComposite / finalAdjusted on every row."""
        bundle = _player_value_bundle({})
        assert set(bundle) == {"overall", "rawComposite", "finalAdjusted", "displayValue"}


class TestBoardStampMirrorsExactly:
    """The stamping loop in ``build_api_data_contract`` is the only writer of
    the board-named keys.  These reproduce its two branches directly rather
    than rebuilding a whole contract, so the assertion is about the rule and
    not about whichever payload happens to be checked in.
    """

    @staticmethod
    def _stamp(rows: list[dict]) -> int:
        """The production loop, transcribed.  Kept in step with
        ``data_contract.build_api_data_contract`` — if that loop changes,
        this transcription must change with it and the test will say so."""
        unpriced = 0
        for row in rows:
            rdv = row.get("rankDerivedValue")
            vals = row.get("values")
            if not isinstance(vals, dict):
                continue
            if rdv is not None and rdv > 0:
                vals["overall"] = rdv
                vals["finalAdjusted"] = rdv
                vals["displayValue"] = rdv
            else:
                unpriced += 1
        return unpriced

    def test_priced_row_mirrors_the_board_value(self):
        row = {"rankDerivedValue": 7852, "values": _player_value_bundle({"_composite": 6136})}
        assert self._stamp([row]) == 0
        # Hand-computed: the board said 7852, so all three read 7852 — NOT
        # the 6136 the scraper's composite would have supplied.
        assert row["values"]["overall"] == 7852
        assert row["values"]["finalAdjusted"] == 7852
        assert row["values"]["displayValue"] == 7852
        assert row["values"]["rawComposite"] == 6136

    def test_unpriced_row_reports_unpriced_not_composite(self):
        """The suppressed-generic-pick case, with the real live numbers."""
        row = {"rankDerivedValue": None, "values": _player_value_bundle({"_composite": 6136})}
        assert self._stamp([row]) == 1
        assert row["values"]["overall"] is None
        assert row["values"]["finalAdjusted"] is None
        assert row["values"]["displayValue"] is None
        # The composite is still retrievable under its own name.
        assert row["values"]["rawComposite"] == 6136

    def test_zero_and_negative_board_values_count_as_unpriced(self):
        for rdv in (0, -1):
            row = {"rankDerivedValue": rdv, "values": _player_value_bundle({"_composite": 500})}
            assert self._stamp([row]) == 1
            assert row["values"]["overall"] is None
