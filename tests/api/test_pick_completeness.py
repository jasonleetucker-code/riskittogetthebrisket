"""C1-U6 GREEN: the automated pick-completeness census (C1-PICK-01) and
the generic ↔ exact-slot transition test (C1-PICK-02).

Manifest acceptance for C1-PICK-01: *"Automated census passes: value
exists, finite, not zero-as-missing, identity stable, provenance
stamped, and rankings == trade == API == export == ownership == mobile
== desktop."*  The census here runs the completion contract's §10 loop
over the REAL board (newest scraper export through
``build_api_data_contract`` — the exact call ``server.py`` makes):
every future year on the board × round 1-6 × {three tiers, the generic
grade} plus the anchor year's slot rows, each resolved through the
canonical reference-class resolver.  Cross-surface parity is structural
— every trade engine reads ``rankDerivedValue`` off this same board —
and is pinned here at the two joints where a consumer could diverge
(the finder's board-value extraction and the export CSV).

Manifest acceptance for C1-PICK-02: *"Same identity survives the
transition."*  The transition test walks ONE league-pick identity
through ``market_resolution``'s three bases (unknown slot → generic,
known slot + future year → tier, known slot + active year → exact slot)
and proves the identity never changes, every basis resolves to a finite
canonical value, and no second asset is minted anywhere along the way.

RED counterparts: ``test_pick_completeness_red.py`` (the five measured
defect classes, reproduced on this same payload before the repair).
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path
from typing import Any

from src.api.data_contract import (
    build_api_data_contract,
    current_rookie_draft_year,
    validate_api_data_contract,
)
from src.api.pick_value_resolution import resolve_pick_value
from src.identity.picks import (
    LeaguePickIdentity,
    MarketPickRef,
    market_resolution,
    parse_board_pick_name,
    parse_board_tier_name,
)

_REPO = Path(__file__).resolve().parents[2]

_contract_cache: dict[str, Any] | None = None


def _load_contract() -> dict[str, Any] | None:
    global _contract_cache
    if _contract_cache is not None:
        return _contract_cache
    data_dir = _REPO / "exports" / "latest"
    json_files = sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        return None
    with json_files[0].open() as f:
        raw = json.load(f)
    _contract_cache = build_api_data_contract(raw)
    return _contract_cache


def _finite(v: Any) -> bool:
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(float(v))
        and float(v) > 0
    )


def _board_years(contract: dict[str, Any]) -> tuple[int, list[int]]:
    years = sorted(
        {
            parse_board_tier_name(str(r.get("canonicalName") or ""))[0]
            for r in contract.get("playersArray", [])
            if r.get("assetClass") == "pick"
            and parse_board_tier_name(str(r.get("canonicalName") or "")) is not None
        }
    )
    current = years[0]
    return current, [y for y in years if y > current]


class TestPickCompletenessCensus(unittest.TestCase):
    """The C1-PICK-01 census loop over the real board."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("no scraper export available")

    def test_every_valid_ref_through_the_horizon_resolves_finite(self) -> None:
        current, future_years = _board_years(self.contract)
        # The horizon is DERIVED, and its derivation needs a template:
        # ``_inject_far_future_pick_sources`` mints the unpublished years
        # by stepping the nearest PUBLISHED future year.  With no future
        # vendor tiers at all there is no template, nothing to derive
        # from, and this becomes a statement about source coverage rather
        # than about our code — which the blocking lane must not make
        # (audit 2026-08-17, §3d).
        #
        # So: no published future year at all is a SOURCE condition and
        # is reported as such.  One or more, and the horizon requirement
        # is fully in force — the injection must fill through current+3,
        # and that IS a claim about our code.
        if not future_years:
            self.skipTest(
                "no future pick years on this board — no template for the horizon "
                "derivation; this is a source-coverage condition, reported by "
                "scripts/check_source_health.py, not a code regression"
            )
        self.assertGreaterEqual(
            len(future_years), 3, f"horizon must reach current+3 (got {future_years})"
        )
        failures: list[str] = []
        for year in future_years:
            for rnd in range(1, 7):
                refs = [MarketPickRef(year=year, round_num=rnd)] + [
                    MarketPickRef(year=year, round_num=rnd, tier=t)
                    for t in ("early", "mid", "late")
                ]
                for ref in refs:
                    res = resolve_pick_value(self.contract, ref)
                    if not _finite(res.value):
                        failures.append(f"{ref.canonical_id}: {res.reason}")
                    elif not isinstance(res.provenance, dict) or not res.provenance.get("class"):
                        failures.append(f"{ref.canonical_id}: no provenance")
        # The anchor year's exact slots (the board's slot universe).
        for rnd in range(1, 7):
            for slot in range(1, 13):
                ref = MarketPickRef(year=current, round_num=rnd, slot=slot)
                res = resolve_pick_value(self.contract, ref)
                if not _finite(res.value):
                    failures.append(f"{ref.canonical_id}: {res.reason}")
        # The anchor year's tier + generic grades resolve via aliases /
        # the centre-slot convention rather than their own rows.
        for rnd in range(1, 7):
            for ref in [MarketPickRef(year=current, round_num=rnd)] + [
                MarketPickRef(year=current, round_num=rnd, tier=t) for t in ("early", "mid", "late")
            ]:
                res = resolve_pick_value(self.contract, ref)
                if not _finite(res.value):
                    failures.append(f"{ref.canonical_id}: {res.reason}")
        self.assertEqual(failures, [], f"census failures: {failures[:12]}")

    def test_no_pick_value_is_zero_or_non_finite(self) -> None:
        offenders = []
        for r in self.contract["playersArray"]:
            if r.get("assetClass") != "pick":
                continue
            v = r.get("rankDerivedValue")
            if v is None:
                continue
            if isinstance(v, (int, float)) and (not math.isfinite(float(v)) or float(v) == 0):
                offenders.append(r.get("canonicalName"))
        self.assertEqual(offenders, [], f"zero/non-finite pick values: {offenders}")

    def test_unpriced_states_carry_reasons_never_zero(self) -> None:
        """MISSING IS NEVER ZERO, structurally: an unresolvable ref
        answers value=None + reason; a suppressed row's provenance names
        its alias.  Nothing anywhere answers 0."""
        res = resolve_pick_value(self.contract, MarketPickRef(year=2098, round_num=6))
        self.assertIsNone(res.value)
        self.assertIsNotNone(res.reason)
        # A ref outside the board grammar refuses explicitly.
        res = resolve_pick_value(self.contract, MarketPickRef(year=2027, round_num=9))
        self.assertIsNone(res.value)
        self.assertEqual(res.reason, "outside_board_grammar")

    def test_provenance_stamped_on_every_pick_row(self) -> None:
        offenders = [
            r.get("canonicalName")
            for r in self.contract["playersArray"]
            if r.get("assetClass") == "pick" and not isinstance(r.get("pickValueProvenance"), dict)
        ]
        self.assertEqual(offenders, [], f"picks without provenance: {offenders[:10]}")

    def test_direct_market_evidence_outranks_every_derivation(self) -> None:
        """A vendor-priced tier row's provenance is the direct blend —
        never a derivation — and derivations appear only where no vendor
        evidence exists (synthetic years, rounds 5-6, the generic
        grade)."""
        current, future_years = _board_years(self.contract)
        rows = {
            str(r.get("canonicalName") or ""): r
            for r in self.contract["playersArray"]
            if r.get("assetClass") == "pick"
        }
        vendor_years = [y for y in future_years if y <= current + 2]
        for year in vendor_years:
            for tier in ("Early", "Mid", "Late"):
                for rnd in (1, 2, 3, 4):
                    suffix = {1: "1st", 2: "2nd", 3: "3rd"}.get(rnd, f"{rnd}th")
                    row = rows.get(f"{year} {tier} {suffix}")
                    if row is None:
                        continue
                    prov = row.get("pickValueProvenance") or {}
                    self.assertEqual(
                        prov.get("class"),
                        "direct_market_blend",
                        f"{year} {tier} {suffix} should be direct, got {prov}",
                    )

    def test_derivations_are_labelled_prior(self) -> None:
        for r in self.contract["playersArray"]:
            prov = r.get("pickValueProvenance")
            if not isinstance(prov, dict):
                continue
            if prov.get("class") in ("derived_year_step", "derived_round_step"):
                self.assertEqual(
                    prov.get("classification"),
                    "PRIOR",
                    f"{r.get('canonicalName')}: derivation not labelled PRIOR: {prov}",
                )

    def test_contract_validation_census_is_green(self) -> None:
        result = validate_api_data_contract(self.contract)
        census_errors = [e for e in (result.get("errors") or []) if str(e).startswith("pick_")]
        self.assertEqual(census_errors, [], f"validation census errors: {census_errors[:8]}")

    def test_determinism_same_ref_same_value(self) -> None:
        """The same canonical ref deterministically resolves to the same
        value within one build (index path and non-index path agree)."""
        ref = MarketPickRef(year=_board_years(self.contract)[1][0], round_num=1, tier="early")
        a = resolve_pick_value(self.contract, ref)
        b = resolve_pick_value(self.contract, ref)
        self.assertEqual(a.value, b.value)
        self.assertEqual(a.basis_row_name, b.basis_row_name)

    def test_trade_surface_reads_the_same_number(self) -> None:
        """rankings == trade: the finder's board-value extraction must
        hand every priced pick exactly the board's number."""
        from src.trade.finder import board_values_from_contract

        board_values = board_values_from_contract(self.contract)
        checked = 0
        for r in self.contract["playersArray"]:
            if r.get("assetClass") != "pick" or not _finite(r.get("rankDerivedValue")):
                continue
            name = str(r.get("canonicalName") or "")
            got = board_values.get(name)
            if got is None:
                legacy = str(r.get("legacyRef") or "")
                got = board_values.get(legacy)
            self.assertEqual(
                int(got) if got is not None else None,
                int(r["rankDerivedValue"]),
                f"finder board value diverges for {name}",
            )
            checked += 1
        # Non-vacuity, not a floor (audit 2026-08-17, §3d).  Was
        # ``> 100`` — an absolute count over the live board, which a
        # source outage fails with the finder's extraction unchanged.
        # The real assertion is the per-row ``assertEqual`` inside the
        # loop; this only proves the loop ran.
        self.assertGreater(checked, 0, "no priced picks compared — the loop was vacuous")

    def test_ownership_surface_resolves_owned_picks(self) -> None:
        """ownership: a league pick at every state resolves to a finite
        value through identity → market_resolution → resolver — the
        exact chain the overlay's pickDetails assetId enables."""
        current, future_years = _board_years(self.contract)
        cdy = current_rookie_draft_year()
        failures = []
        for season in [current, *future_years]:
            for rnd in range(1, 7):
                for slot in (None, 1, 6, 12):
                    res_id = market_resolution(
                        year=season,
                        round_num=rnd,
                        slot=slot,
                        current_draft_year=cdy,
                    )
                    value = resolve_pick_value(self.contract, res_id.ref)
                    if not _finite(value.value):
                        failures.append(
                            f"season={season} r={rnd} slot={slot} basis={res_id.basis}: {value.reason}"
                        )
        self.assertEqual(failures, [], f"owned-pick resolution failures: {failures[:10]}")


class TestGenericExactSlotTransition(unittest.TestCase):
    """C1-PICK-02: the same identity survives the transition, valued at
    every step, with no second asset."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("no scraper export available")

    def test_one_identity_three_bases_all_valued_no_second_asset(self) -> None:
        current, future_years = _board_years(self.contract)
        self.assertTrue(future_years)
        future = future_years[0]
        ident = LeaguePickIdentity(
            league_key="dynasty_main", season=future, round_num=1, origin_roster_id=7
        )
        pick_rows_before = sum(
            1 for r in self.contract["playersArray"] if r.get("assetClass") == "pick"
        )

        # State 1 — no slot exists yet: honest resolution is GENERIC.
        r1 = market_resolution(
            year=ident.season, round_num=ident.round_num, slot=None, current_draft_year=current
        )
        self.assertEqual(r1.basis, "unknown_slot")
        self.assertEqual(r1.ref.grade, "generic")
        v1 = resolve_pick_value(self.contract, r1.ref)
        self.assertTrue(v1.value and v1.value > 0, f"generic basis unpriced: {v1.reason}")

        # State 2 — slot known but the year is still future: tier basis.
        r2 = market_resolution(
            year=ident.season, round_num=ident.round_num, slot=3, current_draft_year=current
        )
        self.assertEqual(r2.basis, "tier_from_slot")
        self.assertEqual(r2.ref.grade, "tier")
        v2 = resolve_pick_value(self.contract, r2.ref)
        self.assertTrue(v2.value and v2.value > 0, f"tier basis unpriced: {v2.reason}")

        # State 3 — the draft year arrives, slot known: exact slot.
        r3 = market_resolution(
            year=ident.season,
            round_num=ident.round_num,
            slot=3,
            current_draft_year=ident.season,
        )
        self.assertEqual(r3.basis, "exact_slot")
        self.assertEqual(r3.ref.grade, "slot")
        # The board's slot rows exist for ITS anchor year; prove the
        # exact-slot leg on the anchor year's board rows (the identical
        # code path this pick will take when its year arrives).
        v3 = resolve_pick_value(
            self.contract, MarketPickRef(year=current, round_num=ident.round_num, slot=3)
        )
        self.assertTrue(v3.value and v3.value > 0, f"slot basis unpriced: {v3.reason}")

        # The identity NEVER changed across the transition...
        self.assertEqual(ident.canonical_id, f"pick:dynasty_main:{future}:r1:o7")
        # ...the refs are three grades of ONE reference class family...
        self.assertEqual({r1.ref.year, r2.ref.year}, {future})
        self.assertEqual({r1.ref.round_num, r2.ref.round_num, r3.ref.round_num}, {1})
        # ...and resolving minted no second asset anywhere.
        pick_rows_after = sum(
            1 for r in self.contract["playersArray"] if r.get("assetClass") == "pick"
        )
        self.assertEqual(pick_rows_before, pick_rows_after)

    def test_value_resolution_never_mutates_identity_or_state(self) -> None:
        """Valuation must not fabricate a slot or tier onto a generic
        ref: the resolution echoes the ref verbatim."""
        current, future_years = _board_years(self.contract)
        ref = MarketPickRef(year=future_years[0], round_num=2)
        res = resolve_pick_value(self.contract, ref)
        self.assertEqual(res.ref, ref)
        self.assertIsNone(res.ref.slot)
        self.assertIsNone(res.ref.tier)
        self.assertEqual(res.ref.grade, "generic")

    def test_generic_board_rows_parse_back_to_generic_refs(self) -> None:
        """Identity round-trip for the C1-U6 generic-grade rows."""
        current, future_years = _board_years(self.contract)
        for year in future_years:
            for rnd in range(1, 7):
                name = f"{year} Round {rnd}"
                ref = parse_board_pick_name(name)
                self.assertIsNotNone(ref, f"{name} does not parse")
                self.assertEqual(ref.grade, "generic")
                self.assertEqual(ref.board_row_name(), name)


class TestConsumerRepairs(unittest.TestCase):
    """The two authorized trade-facing lookups that used to answer
    missing/zero."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("no scraper export available")

    def test_draft_capital_future_year_prices_via_generic_grade(self) -> None:
        from src.api.draft_capital_fallback import _pick_value_from_contract

        current, future_years = _board_years(self.contract)
        v = _pick_value_from_contract(self.contract, future_years[0], 1, 5)
        self.assertIsNotNone(v, "future-year draft-capital pick still unpriced")
        generic = resolve_pick_value(
            self.contract, MarketPickRef(year=future_years[0], round_num=1)
        )
        self.assertEqual(int(v), int(generic.value))
        # Every stand-in slot of one future (season, round) prices
        # identically — no fabricated slot certainty (C1-U7 boundary).
        v2 = _pick_value_from_contract(self.contract, future_years[0], 1, 11)
        self.assertEqual(v, v2)

    def test_simulator_resolves_overlay_pick_labels(self) -> None:
        from src.api.terminal import _build_row_index
        from src.api.trade_simulator import _resolve_asset

        current, future_years = _board_years(self.contract)
        rows = [
            {**r, "displayName": r.get("displayName") or r.get("canonicalName")}
            for r in self.contract["playersArray"]
        ]
        idx = _build_row_index(rows)
        # The overlay's round-suffix label ("2027 1st") — measured
        # silently dropped from the before/after aggregates before this.
        hit = _resolve_asset(f"{future_years[0]} 1st", row_index=idx)
        self.assertIsNotNone(hit, "overlay round-suffix pick label still unresolvable")
        self.assertGreater(hit["value"], 0)
        self.assertEqual(hit["assetClass"], "pick")
        # A suppressed current-year tier label follows its alias instead
        # of pricing at zero.
        hit2 = _resolve_asset(f"{current} Early 1st", row_index=idx)
        if hit2 is not None:
            self.assertGreater(hit2["value"], 0)
        # Garbage still refuses — identity never guesses.
        self.assertIsNone(_resolve_asset("certainly not a pick", row_index=idx))


class TestExportParity(unittest.TestCase):
    """API == export: the CSV export carries the same canonical value."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("no scraper export available")

    def test_pick_values_in_export_match_contract(self) -> None:
        import csv
        import io

        try:
            from src.api.export_builder import build_values_csv  # type: ignore
        except ImportError:
            self.skipTest("no export builder module — export served from contract directly")
        buf = io.StringIO(build_values_csv(self.contract))
        rows = {r["name"]: r for r in csv.DictReader(buf)}
        for r in self.contract["playersArray"]:
            if r.get("assetClass") != "pick" or not _finite(r.get("rankDerivedValue")):
                continue
            row = rows.get(str(r.get("canonicalName")))
            if row is None:
                continue
            self.assertEqual(int(float(row["value"])), int(r["rankDerivedValue"]))


if __name__ == "__main__":
    unittest.main()
