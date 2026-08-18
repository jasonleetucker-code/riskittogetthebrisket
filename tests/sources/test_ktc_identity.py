"""KTC identity: one owner, no fabricated names, no failure-gated map.

The defect this suite exists for: ``Dynasty Scraper.py`` built its KTC
playerID -> name map inside a block guarded by ``if "content" in dir()``,
and ``content`` was bound in exactly one place — inside Strategy 3, which
itself only ran ``if not name_map:``.  The comment above it said "Always
build".  It could only build when the primary scrape had FAILED, so the
crowd databases it fed never once ran on a healthy scrape.  Measured:
``ktcCrowd`` appears in 0 of 173 committed export archives, decompressed.

The structural assertions are structural because the defect WAS the
control flow — a behavioural test would have needed a browser and a live
KTC session, which is exactly why it survived unseen through three audits.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import unittest

from src.sources.ktc_identity import (
    SEARCH_INDEX_VAR,
    VALUE_BOARD_VAR,
    KtcIdentityCollision,
    parse_ktc_identity,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SCRAPER = REPO / "Dynasty Scraper.py"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _feed(html: str, var: str) -> list:
    return json.loads(re.search(r"var\s+%s\s*=\s*(\[.*?\]);" % var, html, re.DOTALL).group(1))


def _page(html: str, wrapped: str) -> str:
    """Replace one inline array so a single condition can be varied."""
    return html


# ── The map itself ───────────────────────────────────────────────────


class TestIdentityMapConstruction(unittest.TestCase):
    def test_the_search_index_is_preferred_over_the_value_board(self):
        m = parse_ktc_identity(_fixture("ktc_waiver_page.html"))
        self.assertEqual(m.source, SEARCH_INDEX_VAR)

    def test_the_value_board_is_a_recorded_fallback_not_a_silent_one(self):
        """A fallback that looks like a success is how 47 dropped claims
        per fetch stayed invisible."""
        html = _fixture("ktc_waiver_page.html").replace(
            f"var {SEARCH_INDEX_VAR} =", "var someOtherThing ="
        )
        m = parse_ktc_identity(html)
        self.assertEqual(m.source, VALUE_BOARD_VAR)
        self.assertTrue(m.players)

    def test_the_search_index_resolves_strictly_more_than_the_value_board(self):
        """The property that makes the preference correct rather than
        arbitrary.  The fixture reproduces the real population gap."""
        html = _fixture("ktc_waiver_page.html")
        search = parse_ktc_identity(html)
        board = parse_ktc_identity(html.replace(f"var {SEARCH_INDEX_VAR} =", "var other ="))
        self.assertGreater(len(search.players), len(board.players))
        self.assertTrue(set(board.players).issubset(set(search.players)))

    def test_no_arrays_at_all_is_unobserved_not_an_empty_market(self):
        m = parse_ktc_identity("<html><body>nothing here</body></html>")
        self.assertIsNone(m.source)
        self.assertEqual(len(m), 0)

    def test_an_id_claimed_by_two_names_fails_closed(self):
        html = _fixture("ktc_waiver_page.html")
        rows = _feed(html, SEARCH_INDEX_VAR)
        rows.append({**rows[0], "playerName": "Someone Else Entirely"})
        clashed = re.sub(
            r"var %s = \[.*?\];" % SEARCH_INDEX_VAR,
            "var %s = %s;" % (SEARCH_INDEX_VAR, json.dumps(rows)),
            html,
            flags=re.DOTALL,
        )
        with self.assertRaises(KtcIdentityCollision):
            parse_ktc_identity(clashed)

    def test_an_identical_duplicate_dedupes_harmlessly(self):
        html = _fixture("ktc_waiver_page.html")
        rows = _feed(html, SEARCH_INDEX_VAR)
        rows.append(dict(rows[0]))
        duped = re.sub(
            r"var %s = \[.*?\];" % SEARCH_INDEX_VAR,
            "var %s = %s;" % (SEARCH_INDEX_VAR, json.dumps(rows)),
            html,
            flags=re.DOTALL,
        )
        self.assertEqual(len(parse_ktc_identity(duped)), len(parse_ktc_identity(html)))

    def test_a_row_with_an_id_and_no_name_is_not_a_resolution(self):
        html = _fixture("ktc_waiver_page.html")
        rows = _feed(html, SEARCH_INDEX_VAR)
        rows.append({"playerID": 999999, "playerName": "", "position": "WR"})
        html2 = re.sub(
            r"var %s = \[.*?\];" % SEARCH_INDEX_VAR,
            "var %s = %s;" % (SEARCH_INDEX_VAR, json.dumps(rows)),
            html,
            flags=re.DOTALL,
        )
        m = parse_ktc_identity(html2)
        self.assertIsNone(m.name_for(999999))
        self.assertEqual(m.missing_names, 1)


# ── Classification ───────────────────────────────────────────────────


class TestAssetClassification(unittest.TestCase):
    def setUp(self):
        self.trade_html = _fixture("ktc_trade_page.html")
        self.m = parse_ktc_identity(self.trade_html)

    def test_a_pick_referenced_by_id_is_a_pick_not_a_player(self):
        pick_id = next(iter(self.m.picks))
        asset = self.m.classify(pick_id)
        self.assertEqual(asset.kind, "pick")
        self.assertFalse(asset.is_player)

    def test_a_pick_written_as_a_label_is_recognised(self):
        for label in ("2026 Pick 1.02", "2028 Round 5", "Startup Pick 26.01"):
            with self.subTest(label=label):
                self.assertEqual(self.m.classify(label).kind, "pick")

    def test_a_faab_amount_is_not_a_player(self):
        asset = self.m.classify("$3.00")
        self.assertEqual(asset.kind, "faab_amount")
        self.assertFalse(asset.is_player)

    def test_the_no_drop_sentinel_is_named_as_such(self):
        asset = self.m.classify("-1")
        self.assertEqual(asset.kind, "unresolved")
        self.assertEqual(asset.reason, "sentinel_no_asset")

    def test_an_unknown_id_stays_unresolved_and_is_never_given_a_name(self):
        asset = self.m.classify("987654321")
        self.assertEqual(asset.kind, "unresolved")
        self.assertEqual(asset.reason, "id_not_in_index")
        self.assertIsNone(asset.name)

    def test_an_unrecognised_label_is_not_quietly_filed_as_a_pick(self):
        self.assertEqual(self.m.classify("Some Future Vendor Format").kind, "unresolved")

    def test_every_reference_in_the_trade_fixture_is_named(self):
        """No reference may fall through to 'we could not tell'."""
        unresolved = []
        for row in _feed(self.trade_html, "trades"):
            for side in ("teamOne", "teamTwo"):
                for value in (row.get(side) or {}).values():
                    if not isinstance(value, list):
                        continue
                    for ref in value:
                        asset = self.m.classify(ref)
                        if asset.kind == "unresolved":
                            unresolved.append((asset.raw, asset.reason))
        self.assertEqual(unresolved, [])

    def test_every_claim_in_the_waiver_fixture_resolves_to_a_player(self):
        html = _fixture("ktc_waiver_page.html")
        m = parse_ktc_identity(html)
        misses = [
            r.get("pickedUpPlayer")
            for r in _feed(html, "waivers")
            if not m.classify(r.get("pickedUpPlayer")).is_player
        ]
        self.assertEqual(misses, [])


# ── No fabricated identity, anywhere ─────────────────────────────────


class TestNoFabricatedPlayerIdentity(unittest.TestCase):
    """``Player#12345`` is TRUTHY, so it passed every downstream
    emptiness check and then joined nothing — a missing identity wearing
    the costume of a present one."""

    def test_the_owner_never_manufactures_a_name(self):
        m = parse_ktc_identity(_fixture("ktc_waiver_page.html"))
        for ref in ("987654321", "-1", "", None, "not an id"):
            with self.subTest(ref=ref):
                self.assertIsNone(m.classify(ref).name)

    def test_the_fabricating_helper_is_gone_from_the_scraper(self):
        needle = "Player" + "#"  # assembled so this line is not its own match
        hits = [
            i
            for i, line in enumerate(SCRAPER.read_text(encoding="utf-8").splitlines(), 1)
            if needle in line
        ]
        self.assertEqual(hits, [], f"fabricated identities constructed at lines {hits}")


# ── The control-flow defect cannot come back ─────────────────────────


def _scrape_ktc() -> ast.AST:
    tree = ast.parse(SCRAPER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "scrape_ktc":
            return node
    raise AssertionError("scrape_ktc not found")


class TestTheInvertedGuardCannotReturn(unittest.TestCase):
    def test_nothing_probes_whether_a_local_happens_to_be_bound(self):
        src = ast.unparse(_scrape_ktc()).replace('"', "'")
        self.assertNotIn(
            "'content' in dir()",
            src,
            "a guard that asks whether an earlier branch bound a local is "
            "how the crowd path was gated on its own failure",
        )

    def test_the_page_source_is_bound_on_every_path(self):
        """``content`` must not be assigned only inside a branch
        conditioned on the ranking parse having failed."""
        fn = _scrape_ktc()

        def binds_content(node) -> bool:
            return any(
                isinstance(sub, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "content" for t in sub.targets)
                for sub in ast.walk(node)
            )

        # Which assignments sit inside a branch conditioned on the
        # ranking parse having failed?  Needs real parent tracking —
        # ``content = ""`` is nested several blocks deep, so scanning
        # ``fn.body`` alone would call every binding conditional.
        failure_gated: set[int] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and "name_map" in ast.unparse(node.test):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "content" for t in sub.targets
                    ):
                        failure_gated.add(id(sub))

        all_bindings = [
            sub
            for sub in ast.walk(fn)
            if isinstance(sub, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "content" for t in sub.targets)
        ]
        free = [b for b in all_bindings if id(b) not in failure_gated]

        self.assertTrue(all_bindings, "content is never bound at all")
        self.assertTrue(
            free,
            "every binding of `content` sits inside a branch that only runs "
            "when the ranking parse failed — this is the original defect",
        )


class TestOneOwner(unittest.TestCase):
    def test_the_scraper_carries_no_ktc_identity_implementation(self):
        """The scraper's crowd path was RETIRED, not re-pointed — so it
        needs no KTC id map at all.  A second implementation appearing
        here would be a second owner regardless of whether it agrees."""
        src = SCRAPER.read_text(encoding="utf-8")
        for symbol in ("KTC_ID_TO_NAME", "KTC_CROWD_DATA", "ktcIdMap", "ktcCrowd"):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, src)

    def test_the_live_producer_delegates_rather_than_re_deriving(self):
        producer = (REPO / "scripts" / "fetch_crowd_faab.py").read_text(encoding="utf-8")
        self.assertIn("parse_ktc_identity", producer)
        self.assertNotIn(
            "var\\s+%s" % VALUE_BOARD_VAR,
            producer,
            "the producer is parsing the identity array itself again",
        )

    @staticmethod
    def _code_only(path: pathlib.Path) -> str:
        """Source with comments and docstrings blanked IN PLACE.

        Line structure is preserved — an earlier version joined tokens
        with spaces, which silently stopped the pattern matching and
        made the guard report a clean tree that was not clean.

        A guard that trips on the prose explaining WHY something is
        forbidden just teaches the next person to delete the
        explanation, hence the blanking.
        """
        import io
        import tokenize

        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT:
                    row, col = tok.start
                    lines[row - 1] = lines[row - 1][:col]
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass

        try:
            tree = ast.parse(text)
        except SyntaxError:
            return "\n".join(lines)

        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                if isinstance(first.value.value, str):
                    for i in range(first.lineno - 1, first.end_lineno):
                        lines[i] = ""
        return "\n".join(lines)

    #: Second id -> name derivations that exist, are KNOWN, and are not
    #: repaired by this unit.  Pinned exactly rather than allowlisted by
    #: pattern: adding a new one fails this test, and removing this one
    #: also fails it, so neither direction can happen silently.
    KNOWN_DEFERRED_DERIVATIONS = {
        # scrape_ktc Strategy 2 builds playerID -> playerName from the
        # page source to join KTC's value-history API onto names.  Same
        # concept as the owner, and the owner covers ~4x as many players
        # (search index vs the inline board).  NOT migrated here because
        # that map feeds KTC's RANKING values: changing it changes the
        # canonical board, which this unit promises not to touch (the
        # board-inertness measurement is 0/0/0/0).  Repairing it is a
        # board-affecting change and needs its own measured unit.
        "Dynasty Scraper.py",
    }

    def test_no_second_identity_parser_exists_in_the_tree(self):
        """Structural guard on the CONCEPT, not on the byte string.

        Deliberately NOT "nobody may read ``playersArray``": that array
        is also KTC's value board, and reading it for VALUES is a
        different concept with its own owner (``src/trade/ktc_import.py``
        for calculator import, ``scripts/check_ktc_health.py`` for the
        health probe, the scraper's Strategy 3 for rankings).  A guard
        that flagged those would be pressure to delete a legitimate
        caller.

        What must be unique is the id -> IDENTITY mapping.  Two markers:
        touching the search index at all (its only purpose is identity),
        and pairing ``playerID`` with ``playerName`` in one pattern —
        exactly the shape of the regex this unit deleted.

        Needles are assembled at runtime so this file is not its own
        match.
        """
        index_marker = SEARCH_INDEX_VAR
        id_key, name_key = "player" + "ID", "player" + "Name"
        owner = (REPO / "src" / "sources" / "ktc_identity.py").resolve()

        found: dict[str, str] = {}
        for path in (
            list(REPO.glob("*.py"))
            + list((REPO / "src").rglob("*.py"))
            + list((REPO / "scripts").rglob("*.py"))
        ):
            if path.resolve() == owner:
                continue
            code = self._code_only(path)
            rel = str(path.relative_to(REPO))
            if index_marker in code:
                found[rel] = "reads the search index"
                continue
            for line in code.splitlines():
                if id_key in line and name_key in line:
                    found[rel] = "pairs id with name"
                    break

        unexpected = {k: v for k, v in found.items() if k not in self.KNOWN_DEFERRED_DERIVATIONS}
        self.assertEqual(unexpected, {}, f"a new second KTC identity parser appeared: {unexpected}")

        vanished = self.KNOWN_DEFERRED_DERIVATIONS - set(found)
        self.assertEqual(
            vanished,
            set(),
            f"{vanished} no longer derives identity — delete it from "
            "KNOWN_DEFERRED_DERIVATIONS so the guard stays exact",
        )


if __name__ == "__main__":
    unittest.main()


# ── The live seam, end to end ────────────────────────────────────────


class TestTheCrowdFaabSeam(unittest.TestCase):
    """producer -> identity -> storage -> crowd_bid_index -> recommender.

    An integration test over the SEAM, not merely "the producer returned
    records".  The defect class this guards is a joinable-looking row
    whose player nobody can actually look up.
    """

    def _rows(self):
        import scripts.fetch_crowd_faab as producer

        html = _fixture("ktc_waiver_page.html")
        # Exercise the real parser against fixture HTML rather than the
        # network: fetch_rows' only impure step is the urlopen above it.
        identity = parse_ktc_identity(html)
        rows = []
        for row in _feed(html, "waivers"):
            settings = row.get("settings") or {}
            budget = float(settings.get("totalBlindBidWaiverAmount") or 0)
            bid = float(row.get("blindBid") or 0)
            if budget <= 0 or bid < 0:
                continue
            picked = identity.classify(row.get("pickedUpPlayer"))
            if not picked.is_player:
                continue
            rows.append(
                {
                    "id": row.get("id"),
                    "date": row.get("date"),
                    "added": picked.name,
                    "bid": bid,
                    "budget": budget,
                    "bidPct": round(100.0 * bid / budget, 3),
                    "settings": {"leagueId": str(settings.get("id") or "")},
                }
            )
        self.assertTrue(producer.fetch_rows)  # the module imports cleanly
        return rows

    def test_every_stored_row_carries_a_player_the_index_can_key(self):
        from src.trade.faab_history import crowd_bid_index
        from src.utils.name_clean import compact_name_key

        rows = self._rows()
        self.assertTrue(rows, "the fixture produced no rows at all")
        index = crowd_bid_index({"rows": rows})
        for row in rows:
            with self.subTest(added=row["added"]):
                self.assertIn(compact_name_key(row["added"]), index)

    def test_a_zero_bid_survives_the_seam(self):
        """$0 adds are the modal outcome and the most informative thing
        the feed says.  Dropping them is what made the legacy analytics
        report a 2% median against a true 0%."""
        from src.trade.faab_history import crowd_bid_index

        index = crowd_bid_index(
            {
                "rows": [
                    {"added": "Zero Bidder", "bidPct": 0.0, "settings": {"leagueId": "x"}},
                    {"added": "Zero Bidder", "bidPct": 0.0, "settings": {"leagueId": "y"}},
                ]
            }
        )
        self.assertIn("zerobidder", index)
        self.assertEqual(index["zerobidder"]["medianPct"], 0.0)

    def test_the_producer_refuses_rather_than_emitting_unjoinable_rows(self):
        """No identity observed is NOT an empty market."""
        import scripts.fetch_crowd_faab as producer

        html = _fixture("ktc_waiver_page.html")
        blinded = html.replace("var allPlayerSearchValues =", "var a =").replace(
            "var playersArray =", "var b ="
        )
        import unittest.mock as mock

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def read(self_inner):
                return blinded.encode()

        with mock.patch.object(producer.urllib.request, "urlopen", lambda *a, **k: _Resp()):
            with self.assertRaises(RuntimeError):
                producer.fetch_rows()


class TestFormatFilteringCannotYieldAHealthyZero(unittest.TestCase):
    """A settings-key rename must fail LOUDLY, not report an empty market.

    Measured against the live feed before the fix: renaming ``qBs`` took
    the comparable count from 95/200 to **0/200**, and the producer
    reported that as a normal "0 comparable, continue".  A missing key
    had become the positive claim *"this league is 1QB"*.

    Deterministic, over the fixture: per the §3d stabilization rule a
    hard-gate test must not assert an absolute count over live data.
    """

    def _rows_from(self, mutate=None):
        import scripts.fetch_crowd_faab as producer

        html = _fixture("ktc_waiver_page.html")
        if mutate:
            rows = _feed(html, "waivers")
            for row in rows:
                mutate(row.setdefault("settings", {}))
            html = re.sub(
                r"var waivers = \[.*?\];",
                "var waivers = %s;" % json.dumps(rows),
                html,
                flags=re.DOTALL,
            )
        import unittest.mock as mock

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def read(self_inner):
                return html.encode()

        with mock.patch.object(producer.urllib.request, "urlopen", lambda *a, **k: _Resp()):
            return producer, producer.fetch_rows()

    def test_a_stated_format_still_classifies(self):
        producer, rows = self._rows_from()
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNotNone(row["settings"]["superflex"])
            self.assertIsNotNone(row["settings"]["tep"])

    def test_a_renamed_key_raises_instead_of_reporting_an_empty_market(self):
        def rename(settings):
            settings.pop("qBs", None)
            settings["quarterbacks"] = 2

        with self.assertRaises(RuntimeError) as ctx:
            self._rows_from(rename)
        self.assertIn("unreadable format", str(ctx.exception))

    def test_an_unstated_format_is_never_counted_as_comparable(self):
        """Fails closed: a league we cannot classify must not be priced
        as though it matched."""
        import scripts.fetch_crowd_faab as producer

        unknown = {"settings": {"teams": 12, "superflex": None, "tep": None}}
        self.assertFalse(producer.comparable(unknown, teams=12, superflex=True, tep=True))
        self.assertFalse(producer.comparable(unknown, teams=12, superflex=False, tep=False))

    def test_an_explicit_zero_is_not_the_same_as_an_absent_key(self):
        """``tep: 0`` is a real statement (no TE premium); a missing
        ``tep`` is not."""
        import scripts.fetch_crowd_faab as producer

        stated = {"settings": {"teams": 12, "superflex": False, "tep": 0}}
        self.assertTrue(producer.comparable(stated, teams=12, superflex=False, tep=False))
