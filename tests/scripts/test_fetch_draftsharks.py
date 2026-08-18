"""DraftSharks dynasty ingestion — the 2026-08-05 breakage, pinned.

WHAT HAPPENED.  ``scripts/fetch_draftsharks.py`` was written against a
DraftSharks page that put the whole ~874-row universe in one DOM, with
DL/LB/DB rows merely hidden by ``display:none``.  DraftSharks moved the
table behind htmx (``hx-get="/dynasty-rankings/load-table"``,
``hx-include="#sharedParams"``) with a ``fantasyPosition`` parameter that
decides which families are RENDERED AT ALL.  From 2026-08-05 every
2-hourly run harvested offense only, tripped the zero-IDP guard, and
exited 1.  Last-good preservation worked exactly as designed, so the
canonical board kept voting on 12-day-old DraftSharks evidence — 739
votes at full weight — while nothing in the blocking test suite noticed.

WHY THESE TESTS ARE SHAPED THIS WAY.  Nothing could see the defect
because extraction lived entirely in a JS string evaluated against a
live Playwright ``Page``: there was no seam a test could reach without a
browser and a credentialed session.  ``parse_rows`` is now a pure
function over HTML, so the two fixtures below exercise the real parser
deterministically in the blocking tier — no network, no browser, no
live board, and therefore nothing here that a source outage can flip
(``docs/ops/STABILIZATION_2026-08-16.md`` §3d).

The load-bearing test is
``test_offense_only_markup_cannot_silently_pass``.  A markup change that
leaves only offense visible is the exact failure that occurred, and it
must fail loudly and write nothing.
"""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from scripts import fetch_draftsharks as ds

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PRIOR = FIXTURES / "draftsharks_prior_markup.html"
CURRENT = FIXTURES / "draftsharks_current_markup.html"

# Families the dynasty board must never lose wholesale.  Losing one is
# indistinguishable from a smaller board unless something asserts it.
_EXPECTED_OFFENSE = ("QB", "RB", "WR", "TE")
_EXPECTED_IDP = ("DL", "LB", "DB")


def _split(rows):
    off = sum(1 for r in rows if ds.family_of(r.get("position", "")) == "offense")
    idp = sum(1 for r in rows if ds.family_of(r.get("position", "")) == "idp")
    return off, idp


class TestParserAgainstBothMarkups(unittest.TestCase):
    def test_fixtures_are_not_vacuous(self):
        """Guard on the guards: an empty fixture would make every
        assertion below pass by checking nothing."""
        for path in (PRIOR, CURRENT):
            self.assertTrue(path.is_file(), f"missing fixture {path}")
            rows = ds.parse_rows(path.read_text(encoding="utf-8"))
            self.assertGreater(len(rows), 0, f"{path.name} parsed to zero rows")
            self.assertTrue(
                all(r.get("vendorId") for r in rows),
                f"{path.name}: every row must carry DS's data-key",
            )

    def test_prior_markup_yields_both_families(self):
        rows = ds.parse_rows(PRIOR.read_text(encoding="utf-8"))
        off, idp = _split(rows)
        self.assertGreater(off, 0, "prior markup must yield offense rows")
        self.assertGreater(idp, 0, "prior markup must yield IDP rows")

    def test_current_markup_reproduces_the_defect(self):
        """The fixture is only useful if it still shows the failure."""
        rows = ds.parse_rows(CURRENT.read_text(encoding="utf-8"))
        off, idp = _split(rows)
        self.assertGreater(off, 0)
        self.assertEqual(idp, 0, "the current-markup fixture is meant to carry NO IDP rows")

    def test_hidden_rows_are_still_extracted(self):
        """`display:none` must not remove a row from the harvest — the
        prior board relied on exactly that, and a future CSS-aware
        rewrite would silently drop the whole IDP family again."""
        rows = ds.parse_rows(PRIOR.read_text(encoding="utf-8"))
        _, idp = _split(rows)
        self.assertGreater(idp, 0, "hidden IDP rows must survive extraction")


class TestOffenseOnlyCannotSilentlyPass(unittest.TestCase):
    """The regression that matters."""

    def test_offense_only_markup_cannot_silently_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            sf = Path(tmp) / "sf.csv"
            idp = Path(tmp) / "idp.csv"
            rc = ds.main(
                [
                    "--from-file",
                    str(CURRENT),
                    "--dest-sf",
                    str(sf),
                    "--dest-idp",
                    str(idp),
                ]
            )
            self.assertNotEqual(rc, 0, "an IDP-less board must not exit 0")
            self.assertFalse(sf.exists(), "last-good preservation: no SF write")
            self.assertFalse(idp.exists(), "last-good preservation: no IDP write")

    def test_the_zero_idp_guard_itself_is_what_refuses(self):
        """Pin the GUARD, not just the outcome.

        Mutation-checked: deleting the zero-IDP guard leaves the
        outcome assertions above still green, because the
        positive-IDP-value guard catches an empty IDP set immediately
        afterwards.  Defence in depth is worth having, but it means an
        outcome test cannot tell which guard fired — so this one reads
        the diagnosis and fails if the specific guard stops running.
        """
        import contextlib
        import io

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(err):
            rc = ds.main(
                [
                    "--from-file",
                    str(CURRENT),
                    "--dest-sf",
                    str(Path(tmp) / "sf.csv"),
                    "--dest-idp",
                    str(Path(tmp) / "idp.csv"),
                ]
            )
        self.assertEqual(rc, 1)
        self.assertIn(
            "no IDP rows",
            err.getvalue(),
            "the zero-IDP guard must be the one that refuses an "
            "offense-only board, and must say so",
        )

    def test_a_board_missing_one_idp_family_still_fails_the_floor(self):
        """Losing DB alone leaves `idp_count > 0`, so the zero-IDP guard
        cannot see it.  The floor is what catches a partial family."""
        html = PRIOR.read_text(encoding="utf-8")
        stripped = html.replace('data-fantasy-position="DB"', 'data-fantasy-position="XX"')
        rows = ds.parse_rows(stripped)
        _, idp = _split(rows)
        self.assertGreater(idp, 0, "still has LB/DL, so zero-IDP would not fire")
        self.assertLess(idp, ds._DS_IDP_ROW_FLOOR, "and the floor is what refuses the write")


class TestPositionClassification(unittest.TestCase):
    def test_compound_labels_are_not_dropped(self):
        """`EDGE/DL` matched neither family set under the retired
        exact-match classifier, so those rows vanished from BOTH CSVs
        with no counter and no log line."""
        self.assertEqual(ds.family_of("EDGE/DL"), "idp")
        self.assertEqual(ds.family_of("WR/RB"), "offense")

    def test_every_expected_family_classifies(self):
        for pos in _EXPECTED_OFFENSE:
            self.assertEqual(ds.family_of(pos), "offense", pos)
        for pos in _EXPECTED_IDP:
            self.assertEqual(ds.family_of(pos), "idp", pos)

    def test_non_fantasy_positions_are_unclassified_not_misfiled(self):
        for pos in ("K", "DEF", ""):
            self.assertIsNone(ds.family_of(pos), pos)


class TestValueNormalisation(unittest.TestCase):
    """Exact decimal, zero tolerance — the equivalence gate's currency."""

    def test_trailing_zero_is_equal(self):
        self.assertEqual(ds.normalize_value("53"), ds.normalize_value("53.0"))

    def test_near_miss_is_not_equal(self):
        self.assertNotEqual(ds.normalize_value("53"), ds.normalize_value("52.99"))

    def test_negative_values_survive(self):
        """DS's board legitimately runs negative; a coercion to 0 here
        would erase the tail `test_ds_csvs_have_negative_rows` guards."""
        self.assertEqual(ds.normalize_value("-38"), Decimal("-38"))

    def test_missing_is_none_not_zero(self):
        self.assertIsNone(ds.normalize_value(""))
        self.assertIsNone(ds.normalize_value("—"))
        self.assertIsNone(ds.normalize_value(None))


class TestMultipassReconciliation(unittest.TestCase):
    @staticmethod
    def _row(vid, name, pos, value):
        return {"vendorId": vid, "name": name, "position": pos, "dsValue": value}

    def test_union_is_keyed_on_vendor_id_not_name(self):
        passes = {
            "all": [self._row("1", "Alpha", "QB", "100")],
            "DL": [self._row("2", "Alpha", "DL", "40")],
        }
        merged, report = self._reconcile(passes)
        self.assertEqual(len(merged), 2, "same name, different vendorId = two assets")
        self.assertEqual(report["identityCollisions"], [])

    def test_same_vendor_id_under_two_names_fails_closed(self):
        passes = {
            "all": [self._row("1", "Alpha", "QB", "100")],
            "DL": [self._row("1", "Beta", "DL", "40")],
        }
        _, report = self._reconcile(passes)
        self.assertEqual(report["identityCollisions"], ["1"])

    def test_value_disagreement_across_passes_is_reported(self):
        passes = {
            "all": [self._row("1", "Alpha", "DL", "44")],
            "DL": [self._row("1", "Alpha", "DL", "81")],
        }
        _, report = self._reconcile(passes)
        self.assertEqual(report["valueConflictCount"], 1)

    def test_formatting_difference_is_not_a_conflict(self):
        passes = {
            "all": [self._row("1", "Alpha", "DL", "53")],
            "DL": [self._row("1", "Alpha", "DL", " 53.0 ")],
        }
        _, report = self._reconcile(passes)
        self.assertEqual(report["valueConflictCount"], 0)
        self.assertEqual(report["overlappingAssets"], 1)

    def test_rows_without_a_vendor_id_are_counted_not_merged(self):
        passes = {"all": [self._row(None, "Alpha", "QB", "100")]}
        merged, report = self._reconcile(passes)
        self.assertEqual(merged, [])
        self.assertEqual(report["rowsWithoutVendorId"], 1)

    @staticmethod
    def _reconcile(passes):
        return ds.reconcile_passes(passes)


class TestUnionAdmissibility(unittest.TestCase):
    """The four ways a multipass union can be wrong while looking fine.

    Exercised through the pure gate rather than through navigation, so
    every refusal is reachable without a browser.
    """

    @staticmethod
    def _ok_report(**over):
        base = {
            "rowsWithoutVendorId": 0,
            "identityCollisions": [],
            "valueConflictCount": 0,
            "valueConflicts": [],
            "overlappingAssets": 100,
            "overlapByFamily": {"offense": 60, "idp": 40},
        }
        base.update(over)
        return base

    def test_a_healthy_report_is_admitted(self):
        """Anti-vacuity: if the happy path raised, every assertion below
        would pass for the wrong reason."""
        ds.assert_union_is_admissible(self._ok_report())

    def test_a_row_without_a_vendor_id_rejects_the_whole_union(self):
        """DraftSharks' data-key IS the reconciliation identity.  A row
        without one cannot be matched to its twin in another pass, and
        the three ways to carry on — fall back to name, synthesize an
        id, drop the row — are a known corruption mode, a fabrication,
        and silent data loss.  So the union fails, rather than the row
        being quietly omitted."""
        with self.assertRaises(RuntimeError) as ctx:
            ds.assert_union_is_admissible(self._ok_report(rowsWithoutVendorId=1))
        self.assertIn("data-key", str(ctx.exception))

    def test_an_identity_collision_rejects_the_union(self):
        with self.assertRaises(RuntimeError):
            ds.assert_union_is_admissible(self._ok_report(identityCollisions=["9962"]))

    def test_a_value_conflict_rejects_the_union(self):
        with self.assertRaises(RuntimeError):
            ds.assert_union_is_admissible(self._ok_report(valueConflictCount=1))

    def test_too_little_overlap_rejects_the_union(self):
        with self.assertRaises(RuntimeError) as ctx:
            ds.assert_union_is_admissible(
                self._ok_report(overlappingAssets=3, overlapByFamily={"offense": 2, "idp": 1})
            )
        self.assertIn("not enough overlap", str(ctx.exception))

    def test_overlap_concentrated_in_one_family_rejects_the_union(self):
        """A reassuring TOTAL that sits entirely on the offense side
        leaves every IDP value's currency unproven."""
        with self.assertRaises(RuntimeError) as ctx:
            ds.assert_union_is_admissible(
                self._ok_report(overlappingAssets=100, overlapByFamily={"offense": 100})
            )
        self.assertIn("idp", str(ctx.exception).lower())


class TestExpectedFamilyCompleteness(unittest.TestCase):
    """A depth floor cannot see a lost family."""

    @staticmethod
    def _board(**counts):
        rows = []
        n = 0
        for pos, count in counts.items():
            for _ in range(count):
                n += 1
                rows.append({"vendorId": str(n), "name": f"P{n}", "position": pos, "dsValue": "10"})
        return rows

    def test_a_complete_board_is_missing_nothing(self):
        rows = self._board(QB=1, RB=1, WR=1, TE=1, DL=1, LB=1, DB=1)
        self.assertEqual(ds.missing_expected_families(rows), [])

    def test_each_family_is_independently_detectable(self):
        full = dict(QB=1, RB=1, WR=1, TE=1, DL=1, LB=1, DB=1)
        for family in ("QB", "RB", "WR", "TE", "DL", "LB", "DB"):
            counts = {k: v for k, v in full.items() if k != family}
            self.assertEqual(
                ds.missing_expected_families(self._board(**counts)),
                [family],
                f"losing {family} must be detected on its own",
            )

    def test_a_lost_family_is_invisible_to_the_aggregate_floor(self):
        """DL=180 LB=150 DB=0 clears the IDP floor of 85 with room to
        spare.  This is the exact shape the floors cannot catch."""
        rows = self._board(QB=60, RB=60, WR=60, TE=60, DL=180, LB=150, DB=0)
        idp = sum(1 for r in rows if ds.family_of(r["position"]) == "idp")
        self.assertGreater(
            idp, ds._DS_IDP_ROW_FLOOR, "the aggregate floor is comfortably satisfied"
        )
        self.assertEqual(ds.missing_expected_families(rows), ["DB"])

    def test_aliases_canonicalize_into_their_family(self):
        """DS labelling a lineman EDGE still evidences the DL family —
        the gate is about the family being represented, not the token."""
        rows = self._board(QB=1, RB=1, WR=1, TE=1, EDGE=1, MLB=1, CB=1)
        self.assertEqual(ds.missing_expected_families(rows), [])
        self.assertEqual(ds.canonical_family("EDGE"), "DL")
        self.assertEqual(ds.canonical_family("CB"), "DB")
        self.assertEqual(ds.canonical_family("MLB"), "LB")

    def test_the_missing_family_error_is_named_and_fails_closed(self):
        import contextlib
        import io

        html = PRIOR.read_text(encoding="utf-8")
        # Remove the DB family from an otherwise-valid board.
        no_db = html.replace('data-fantasy-position="DB"', 'data-fantasy-position="LB"')
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(err):
            sf = Path(tmp) / "sf.csv"
            idp = Path(tmp) / "idp.csv"
            fixture = Path(tmp) / "no_db.html"
            fixture.write_text(no_db, encoding="utf-8")
            rc = ds.main(
                ["--from-file", str(fixture), "--dest-sf", str(sf), "--dest-idp", str(idp)]
            )
            self.assertEqual(rc, 2)
            self.assertFalse(sf.exists())
            self.assertFalse(idp.exists())
        self.assertIn("missing expected DraftSharks position families", err.getvalue())
        self.assertIn("DB", err.getvalue())


class TestSanitizerCannotLeak(unittest.TestCase):
    def test_fixture_generation_strips_every_identifying_string(self):
        html = PRIOR.read_text(encoding="utf-8")
        salted = (
            html.replace("Synthetic Player 0001", "Josh Allen")
            + f"<!-- {ds.LEAGUE_NAME} {ds.LEAGUE_ID} -->"
        )
        out = ds.sanitize_html_fixture(salted)
        for needle in (ds.LEAGUE_NAME, ds.LEAGUE_ID, "Josh Allen"):
            self.assertNotIn(needle, out, f"sanitizer leaked {needle!r}")

    def test_sanitized_output_is_still_parseable(self):
        """A fixture that cannot be parsed proves nothing."""
        out = ds.sanitize_html_fixture(PRIOR.read_text(encoding="utf-8"))
        rows = ds.parse_rows(out)
        off, idp = _split(rows)
        self.assertGreater(off, 0)
        self.assertGreater(idp, 0)

    def test_committed_fixtures_carry_no_real_identity(self):
        for path in (PRIOR, CURRENT):
            text = path.read_text(encoding="utf-8")
            for needle in (ds.LEAGUE_NAME, ds.LEAGUE_ID):
                self.assertNotIn(needle, text, f"{path.name} leaks {needle!r}")

    def test_sanitizer_is_deterministic(self):
        html = PRIOR.read_text(encoding="utf-8")
        self.assertEqual(ds.sanitize_html_fixture(html), ds.sanitize_html_fixture(html))


class TestStructuralGuards(unittest.TestCase):
    """Source-text assertions.  A behavioural test cannot see a parser
    that reads the WRONG attribute and happens to agree today, because
    on the public board the static attributes and the rendered text
    carry the same number — they diverge only once our league is
    activated, which is exactly when no test is watching."""

    SOURCE = Path(ds.__file__).read_text(encoding="utf-8")

    @staticmethod
    def _code_strings() -> list[str]:
        """Every string literal that is CODE, with docstrings excluded.

        Scanning raw source text is wrong here: this module's own
        docstring names the forbidden boards in order to explain why
        they are forbidden, and a guard that fails on its own rationale
        just teaches the next person to delete the explanation.  So we
        parse, drop the docstring of every module/class/function, and
        assert against what is left — which is what "is this URL used as
        a fetch target?" actually means.
        """
        import ast

        tree = ast.parse(TestStructuralGuards.SOURCE)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docstrings.add(doc)
        return [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value not in docstrings
        ]

    @staticmethod
    def _strings_in(func_names: set[str]) -> list[str]:
        """String literals inside the named functions only, docstrings
        excluded."""
        import ast

        tree = ast.parse(TestStructuralGuards.SOURCE)
        found: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in func_names:
                continue
            doc = ast.get_docstring(node, clean=False)
            found.extend(
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and child.value != doc
            )
        return found

    # The functions that turn markup into the values we publish.
    _PARSER_FUNCS = {"parse_rows", "_cell_text", "sanitize_html_fixture"}

    def test_the_parser_never_reads_the_static_scoring_attributes(self):
        # Assembled, not written literally, so this guard cannot match
        # its own source text.
        needle = "data-scoring" + "-value"
        offenders = [s for s in self._strings_in(self._PARSER_FUNCS) if needle in s]
        self.assertEqual(
            offenders,
            [],
            "the parser must read rendered .column-title text; the "
            "data-scoring-value-* attributes are DraftSharks' PUBLIC "
            "defaults and would silently harvest unsynced values",
        )

    def test_the_public_default_attribute_is_read_only_to_prove_scoring(self):
        """The verification layer is ALLOWED to read the public default —
        that comparison is how it proves the worker transformed a pass.

        So the guard above is scoped to the parser rather than to the
        module.  This test pins the other half: the attribute has
        exactly one named home, and it is the proof function.  Widening
        that is what would let the public value drift back into the
        published board.
        """
        import ast

        needle = "data-scoring" + "-value"
        tree = ast.parse(self.SOURCE)
        homes = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if any(
                    isinstance(c, ast.Constant)
                    and isinstance(c.value, str)
                    and needle in c.value
                    and c.value != doc
                    for c in ast.walk(node)
                ):
                    homes.add(node.name)
        module_level = [
            t.id
            for n in tree.body
            if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
            and needle in n.value.value
            for t in n.targets
            if isinstance(t, ast.Name)
        ]
        self.assertEqual(
            module_level,
            ["_PUBLIC_VALUE_ATTR"],
            "the public-default attribute name must live in exactly one " "named constant",
        )
        self.assertEqual(
            homes,
            set(),
            "no function may hardcode the public-default attribute; it is "
            f"referenced via _PUBLIC_VALUE_ATTR (found in {sorted(homes)})",
        )

    def test_league_scoring_is_proven_per_pass_not_inferred_from_agreement(self):
        """Passes that are ALL public defaults would agree with each
        other perfectly, so the equivalence gate cannot detect them.
        The per-pass proof is what closes that hole — assert it exists
        and is actually called before rows are ingested."""
        import ast

        tree = ast.parse(self.SOURCE)
        names = {
            n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("_prove_pass_is_league_scored", names)

        harvest = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_harvest_full_universe"
        )
        called = {
            c.func.id
            for c in ast.walk(harvest)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        }
        self.assertIn(
            "_prove_pass_is_league_scored",
            called,
            "every pass must be proven league-scored before its rows enter " "reconciliation",
        )

    def test_the_alternate_scale_boards_are_not_fetched(self):
        strings = self._code_strings()
        for forbidden in ("/dynasty-rankings/idp", "/ros-rankings/"):
            offenders = [s for s in strings if forbidden in s]
            self.assertEqual(
                offenders,
                [],
                f"{forbidden} is a separately rescaled board; merging it "
                "with the combined board would splice two currencies",
            )

    def test_this_guard_can_actually_fire(self):
        """Anti-vacuity: prove the extractor returns real code strings,
        so the two assertions above are not passing on an empty list."""
        strings = self._code_strings()
        self.assertGreater(len(strings), 50, "the AST scan returned almost nothing")
        self.assertTrue(
            any("/dynasty-rankings/te-premium-superflex" in s for s in strings),
            "the board we DO fetch must be visible to this scan, or the "
            "forbidden-URL assertions prove nothing",
        )

    def test_the_floors_still_exist_and_match_the_contract(self):
        self.assertEqual(ds._DS_SF_ROW_FLOOR, 190)
        self.assertEqual(ds._DS_IDP_ROW_FLOOR, 85)

    def test_the_equivalence_gate_requires_real_overlap(self):
        self.assertGreaterEqual(
            ds._MIN_OVERLAP_FOR_EQUIVALENCE,
            25,
            "one coincidental match is not a proof of shared currency",
        )


if __name__ == "__main__":
    unittest.main()
