"""V1-132 (audit F-34): the horizon pick year is not a single-vendor
dependency.

THE DEFECT
──────────
The published pick years blend BOTH pick markets (``idpTradeCalc`` +
``ktcSfTep``) on their tier rows.  The HORIZON year blended
``idpTradeCalc`` alone on all twelve tier cells, because
``_inject_far_future_pick_sources`` derives the horizon year by cloning
the nearest published future year's entry out of the RAW scraper
payload — and ``ktcSfTep``'s pick values only reach a row through the
LATER CSV enrichment step, which the injection structurally cannot see
(and whose CSVs correctly carry no far-future year to enrich a
synthetic row with).  F-30 made the horizon COVERAGE guarantee
independent of the raw key set; the blended VALUE still was not.

THE INVARIANT
─────────────
On a payload where both pick markets publish tiers through year N, the
injected years N+1..horizon carry BOTH sources' derived entries — each
stepped from its own vendor's published template value by the measured
``derivedYearModel`` cell step, compounded across the gap — with
``derived_year_step`` provenance.  And a source that publishes NO picks
contributes nothing: missing stays missing (C1-U6-D1).

These are deterministic tests through the production entry point
(``build_api_data_contract`` with a temp ``csv_root``): no network, no
live board, no absolute live-board counts.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

from src.api.data_contract import (
    _complete_synthetic_pick_sources_from_enrichment,
    _load_pick_year_discount,
    _round_suffix,
    _year_step_for,
    build_api_data_contract,
)

TIERS = ("Early", "Mid", "Late")
VENDOR_ROUNDS = (1, 2, 3, 4)  # the rounds both pick markets publish

CURRENT_YEAR = 2026  # pinned by the payload's own slot-pick rows
TEMPLATE_YEAR = 2028  # nearest published future year — the injection's basis
HORIZON_YEAR = 2029  # CURRENT_YEAR + horizonYears(3), no vendor publishes it

# In-JSON pick market (the raw scraper payload carries these).
IDPTC_TIER_VALUES: dict[str, float] = {}
# CSV-only pick market (arrives via _enrich_from_source_csvs).
KTC_TIER_VALUES: dict[str, float] = {}
for _year, _base in ((2027, 5200.0), (TEMPLATE_YEAR, 4800.0)):
    for _t_i, _tier in enumerate(TIERS):
        for _rnd in VENDOR_ROUNDS:
            _name = f"{_year} {_tier} {_round_suffix(_rnd)}"
            _level = _base * (0.92**_t_i) * (0.62 ** (_rnd - 1))
            IDPTC_TIER_VALUES[_name] = float(round(_level))
            # A deliberately DIFFERENT number per cell, so "the horizon
            # carries KTC's derived value" is distinguishable from "the
            # horizon copied IDPTC's".  Integers, because the CSV parse
            # coerces the value column to int.
            KTC_TIER_VALUES[_name] = float(round(_level * 1.07))


def _raw_payload() -> dict:
    players: dict[str, dict] = {}

    # An offense pool priced by both markets, so the board has a real
    # population around the picks.
    market = 9500
    for i in range(1, 41):
        sites = {"ktcSfTep": market, "idpTradeCalc": market - 20}
        row: dict = {"_canonicalSiteValues": dict(sites), "position": "WR", "age": 25}
        row.update(sites)
        players[f"Pool Player {i:02d}"] = row
        market -= 150

    # Current-year SLOT picks pin the observed current draft year (the
    # lowest year carrying slot-specific labels IS the active draft).
    for slot, val in (("1.01", 6800), ("1.02", 6500), ("1.03", 6200)):
        players[f"{CURRENT_YEAR} Pick {slot}"] = {"idpTradeCalc": val, "position": "PICK"}

    # Future TIER picks: the in-JSON market only — exactly the raw
    # population production hands the injection.  ``ktcSfTep`` reaches
    # these rows via the CSV below, never via the payload.
    for name, val in IDPTC_TIER_VALUES.items():
        players[name] = {"idpTradeCalc": val, "position": "PICK"}

    return {
        "version": "v1-132-two-market-horizon-fixture",
        "date": "2026-08-25",
        "settings": {},
        "sites": [{"key": "idpTradeCalc"}, {"key": "ktcSfTep"}, {"key": "dlfSf"}],
        "maxValues": {},
        "players": players,
    }


def _write_csvs(root: Path) -> None:
    site_raw = root / "CSVs" / "site_raw"
    site_raw.mkdir(parents=True)
    # ktcSfTep: value-signal, players + published-year tier picks ONLY —
    # the vendor publishes nothing past TEMPLATE_YEAR.
    lines = ["name,value"]
    lines += [f"Pool Player {i:02d},{9500 - (i - 1) * 150}" for i in range(1, 41)]
    lines += [f"{name},{val}" for name, val in sorted(KTC_TIER_VALUES.items())]
    (site_raw / "ktcSfTep.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # dlfSf: rank-signal, players only — a registered source that
    # publishes NO picks at all (the missing-stays-missing control).
    dlf = ["name,rank"] + [f"Pool Player {i:02d},{i}" for i in range(1, 21)]
    (site_raw / "dlfSf.csv").write_text("\n".join(dlf) + "\n", encoding="utf-8")


@lru_cache(maxsize=1)
def _board() -> dict[str, dict]:
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        root = Path(tmp)
        _write_csvs(root)
        contract = build_api_data_contract(_raw_payload(), csv_root=root)
    return {str(r.get("canonicalName")): r for r in contract.get("playersArray") or []}


def _positive_sites(row: dict) -> dict[str, float]:
    return {
        k: float(v)
        for k, v in (row.get("canonicalSiteValues") or {}).items()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    }


def _horizon_cells() -> list[tuple[str, str, int]]:
    return [
        (f"{HORIZON_YEAR} {tier} {_round_suffix(rnd)}", tier, rnd)
        for tier in TIERS
        for rnd in VENDOR_ROUNDS
    ]


class TestHorizonBlendsBothMarkets(unittest.TestCase):
    """The invariant, through the production entry point."""

    def test_every_horizon_tier_cell_carries_both_markets(self) -> None:
        board = _board()
        cells = _horizon_cells()
        self.assertEqual(len(cells), 12, "non-vacuity: all twelve cells checked")
        cfg = _load_pick_year_discount()
        gap = HORIZON_YEAR - TEMPLATE_YEAR
        for name, tier, rnd in cells:
            row = board.get(name)
            self.assertIsNotNone(row, f"{name} missing — injection did not run")
            sites = _positive_sites(row)
            self.assertIn("idpTradeCalc", sites, f"{name} lost the in-JSON market's derived entry")
            self.assertIn(
                "ktcSfTep",
                sites,
                f"{name} carries no ktcSfTep — the horizon is a single-vendor "
                f"dependency (F-34); positive sources: {sorted(sites)}",
            )
            # Each vendor's entry is that vendor's own template value
            # stepped by the measured cell step — never the other
            # vendor's number, never the template value verbatim.
            step = _year_step_for(tier, rnd, cfg) ** gap
            template = f"{TEMPLATE_YEAR} {tier} {_round_suffix(rnd)}"
            expected_ktc = KTC_TIER_VALUES[template] * step
            self.assertAlmostEqual(
                sites["ktcSfTep"],
                expected_ktc,
                delta=1.0,
                msg=f"{name}: ktcSfTep {sites['ktcSfTep']} != {template} × {step:.4f}",
            )
            expected_idp = IDPTC_TIER_VALUES[template] * step
            self.assertAlmostEqual(
                sites["idpTradeCalc"],
                expected_idp,
                delta=1.0,
                msg=f"{name}: idpTradeCalc {sites['idpTradeCalc']} != {template} × {step:.4f}",
            )
            self.assertLess(
                sites["ktcSfTep"],
                KTC_TIER_VALUES[template],
                f"{name}: ktcSfTep not stepped — a fabricated published-looking anchor",
            )

    def test_horizon_rows_keep_derived_provenance(self) -> None:
        board = _board()
        for name, _tier, _rnd in _horizon_cells():
            row = board.get(name)
            self.assertIsNotNone(row, name)
            prov = row.get("pickValueProvenance") or {}
            self.assertEqual(
                prov.get("class"),
                "derived_year_step",
                f"{name}: a derivation must never present as {prov.get('class')!r}",
            )

    def test_a_source_publishing_no_picks_contributes_nothing(self) -> None:
        """Missing stays missing (C1-U6-D1).

        ``dlfSf`` covers twenty pool players and zero picks; nothing may
        manufacture a horizon pick entry for it.  Asserted as an exact
        set so ANY leaked key fails, not just the one control source.
        """
        board = _board()
        for name, _tier, _rnd in _horizon_cells():
            row = board.get(name)
            self.assertIsNotNone(row, name)
            self.assertEqual(
                set(_positive_sites(row)),
                {"idpTradeCalc", "ktcSfTep"},
                f"{name}: a source that published no picks contributed",
            )

    def test_published_years_keep_vendor_values_verbatim(self) -> None:
        """The completion widens the horizon only — a vendor-published
        year's entries are the vendor's numbers, never stepped."""
        board = _board()
        checked = 0
        for name, csv_value in KTC_TIER_VALUES.items():
            row = board.get(name)
            self.assertIsNotNone(row, name)
            sites = _positive_sites(row)
            self.assertEqual(
                sites.get("ktcSfTep"),
                float(csv_value),
                f"{name}: published-year ktcSfTep moved",
            )
            self.assertEqual(
                sites.get("idpTradeCalc"),
                float(IDPTC_TIER_VALUES[name]),
                f"{name}: published-year idpTradeCalc moved",
            )
            prov = row.get("pickValueProvenance") or {}
            self.assertEqual(prov.get("class"), "direct_market_blend", name)
            checked += 1
        self.assertEqual(checked, 24, "non-vacuity: both published years checked")


class TestCompletionRules(unittest.TestCase):
    """The fine-grained rules, at the unit the fix owns."""

    @staticmethod
    def _rows_and_derivations() -> tuple[list[dict], dict[str, dict]]:
        from src.api.data_contract import _canonical_match_key

        template = {
            "assetClass": "pick",
            "canonicalName": f"{TEMPLATE_YEAR} Early 1st",
            "canonicalSiteValues": {"idpTradeCalc": 5000, "ktcSfTep": 5350.0},
        }
        synthetic = {
            "assetClass": "pick",
            "canonicalName": f"{HORIZON_YEAR} Early 1st",
            # The injection already stepped the in-JSON market.
            "canonicalSiteValues": {"idpTradeCalc": 3926},
        }
        derivations = {
            _canonical_match_key(f"{HORIZON_YEAR} Early 1st"): {
                "factor": 0.7852,
                "basisYear": TEMPLATE_YEAR,
                "basisName": f"{TEMPLATE_YEAR} Early 1st",
                "family": "measured_vendor_year_step_v1",
                "classification": "PRIOR",
            }
        }
        return [template, synthetic], derivations

    def test_existing_injected_values_are_never_restepped(self) -> None:
        rows, derivations = self._rows_and_derivations()
        _complete_synthetic_pick_sources_from_enrichment(rows, derivations)
        self.assertEqual(rows[1]["canonicalSiteValues"]["idpTradeCalc"], 3926)

    def test_enriched_template_evidence_is_stepped_onto_the_synthetic_row(self) -> None:
        rows, derivations = self._rows_and_derivations()
        stamped = _complete_synthetic_pick_sources_from_enrichment(rows, derivations)
        self.assertEqual(stamped, 1)
        got = rows[1]["canonicalSiteValues"]["ktcSfTep"]
        cfg = _load_pick_year_discount()
        expected = 5350.0 * _year_step_for("Early", 1, cfg)
        self.assertAlmostEqual(got, expected, delta=0.11)

    def test_a_key_the_template_does_not_carry_stays_missing(self) -> None:
        rows, derivations = self._rows_and_derivations()
        _complete_synthetic_pick_sources_from_enrichment(rows, derivations)
        self.assertNotIn("dlfSf", rows[1]["canonicalSiteValues"])

    def test_empty_derivations_is_an_exact_no_op(self) -> None:
        rows, _ = self._rows_and_derivations()
        before = [dict(r["canonicalSiteValues"]) for r in rows]
        stamped = _complete_synthetic_pick_sources_from_enrichment(rows, {})
        self.assertEqual(stamped, 0)
        self.assertEqual([r["canonicalSiteValues"] for r in rows], before)


if __name__ == "__main__":
    unittest.main()
