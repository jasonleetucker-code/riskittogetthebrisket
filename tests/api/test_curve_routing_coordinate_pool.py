"""W02-F001 — the Hill curve must follow the rank's COORDINATE POOL.

The blend converts every rank-signal source's effective rank to a value
through a scope-level master Hill curve.  Which curve is a routing
decision, and ``_curve_for_source`` makes it from the source's
*declaration*::

    if src_def["is_cross_market"]:            → GLOBAL master
    elif src_def["scope"] == "overall_idp":   → IDP master
    else:                                     → OFFENSE master

That reads the registry entry and never looks at what actually happened
to the rank.  Three registered sources — ``dlfIdp``, ``idpShow`` and
``fantasyProsIdp`` — declare ``needs_shared_market_translation``, so the
pipeline crosswalks their native IDP-only ordinal through the backbone's
shared offense+IDP ladder before the curve ever sees it.  Their effective
rank is therefore a *shared-market* rank, identical in kind to the one
``idpTradeCalc`` and the DraftSharks pair carry — and it is priced with
the IDP-slice curve anyway.  A fourth, ``dlfRookieIdp``, reaches the same
place by a different road: Phase 1d translates its within-class rookie
rank through ``idpTradeCalc``'s ladder, which is also shared-market
space.

The defect is a COORDINATE mismatch, not a disagreement about defenders.
The same rank number, in the same pool, on the same board, must mean the
same value — otherwise "rank 120" is two different quantities depending
on which source emitted it, and the blend averages them as if they were
one.

What these tests are, individually:

* ``TestSameCoordinatePoolPricesIdentically``  — RED before the repair.
  Equal effective rank + equal pool must imply equal contribution.
* ``TestTranslatedIdpRankUsesSharedMarketCurve`` — RED. Names the curve.
* ``TestRookieLadderFollowsItsReferencePool``   — RED for the IDP ladder
  (reference ``idpTradeCalc`` = shared market), GREEN-and-must-stay for
  the offense ladder (reference ``ktcSfTep`` = offense pool).
* ``TestUntranslatedIdpRankKeepsIdpCurve``      — GUARD. Green before and
  after.  A rank that was NOT translated is still IDP-local, and the
  repair must not route every defender through GLOBAL just because the
  player is a defender.
* ``TestOffenseRoutingIsUnchanged``             — GUARD.
* ``TestTranslationProvenanceIsHonest``         — RED.
  ``sharedMarketTranslated`` records the source's *intent*, not the
  outcome: it stamps True even when the ladder was empty and
  ``method == "fallback"`` left the raw IDP rank in place.  Routing on a
  field that lies is how the wrong curve stays invisible.
* ``TestLiveBoardHonoursTheCoordinatePool``     — RED on the real
  exported board; skips when no export is present.

Everything runs through ``build_api_data_contract`` — the production
entry point — on a synthetic raw payload.  Synthetic because the
invariant is about coordinates, and a fixture that pins the ranks lets
the assertion be an equality rather than a tolerance; production because
a helper invented for the test would prove nothing about the live path.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

from src.api.data_contract import (
    _PERCENTILE_REFERENCE_N,
    build_api_data_contract,
)
from src.canonical.player_valuation import (
    HILL_GLOBAL_PERCENTILE_C,
    HILL_GLOBAL_PERCENTILE_S,
    HILL_PERCENTILE_C,
    HILL_PERCENTILE_S,
    IDP_HILL_PERCENTILE_C,
    IDP_HILL_PERCENTILE_S,
    percentile_to_value,
    rank_to_percentile,
)

REPO = Path(__file__).resolve().parents[2]

# The three routed scope masters, keyed by the coordinate pool their
# fit population lives in.
GLOBAL_CURVE = (HILL_GLOBAL_PERCENTILE_C, HILL_GLOBAL_PERCENTILE_S)
OFFENSE_CURVE = (HILL_PERCENTILE_C, HILL_PERCENTILE_S)
IDP_CURVE = (IDP_HILL_PERCENTILE_C, IDP_HILL_PERCENTILE_S)


def curve_value(effective_rank: int, curve: tuple[float, float]) -> int:
    """Value the production pipeline would stamp for this rank on ``curve``.

    Deliberately recomputed from the effective RANK through the canonical
    ``rank_to_percentile`` rather than from the stamped ``percentile``
    field, which is rounded to 6 places for display.
    """
    p = rank_to_percentile(float(effective_rank), reference_n=_PERCENTILE_REFERENCE_N)
    return int(round(percentile_to_value(p, midpoint=curve[0], slope=curve[1])))


# ── Fixture ────────────────────────────────────────────────────────────
#
# 160 rows in one deliberate order so that every pool's ranks are known
# in advance:
#
#   * offense and IDP veterans interleave, so IDP entries land at a wide
#     spread of shared-market ranks (2 … 120) rather than clustering.
#   * every rookie sits BELOW every veteran, and offense rookies above
#     IDP rookies.  That makes the shared-market IDP ladder's k-th entry
#     exactly the k-th IDP veteran, so ``dlfIdp``'s translated rank is
#     predictable instead of merely plausible.
#   * ``idpTradeCalc`` (the backbone, cross-market, value-direct) and the
#     DraftSharks pair (cross-market, rank-signal) carry the SAME values,
#     so DraftSharks' Phase-1b combined rank equals the backbone's rank
#     row for row.  DraftSharks is the comparator: it is the only
#     rank-signal source whose ranks are natively shared-market.
#
# Values are integers because ``canonicalSiteValues`` rounds — a
# fractional scale silently collapses distinct rows onto tied ranks.

N_OFF_VET = 60
N_IDP_VET = 60
N_OFF_ROOKIE = 20
N_IDP_ROOKIE = 20

IDP_POSITIONS = ("DL", "LB", "DB")


def _raw_payload() -> dict:
    players: dict[str, dict] = {}

    def add(name: str, position: str, market: int, rookie: bool, extra: tuple[str, ...]) -> None:
        ds_key = "draftSharksIdp" if position in IDP_POSITIONS else "draftSharks"
        sites: dict[str, int] = {"idpTradeCalc": market, ds_key: market}
        for key in extra:
            sites[key] = market
        row = {"_canonicalSiteValues": dict(sites), "position": position, "age": 25}
        row.update(sites)
        if rookie:
            row["_isRookie"] = True
        players[name] = row

    market = 9000
    for i in range(max(N_OFF_VET, N_IDP_VET)):
        if i < N_OFF_VET:
            add(f"Off Vet {i + 1:03d}", "WR", market, False, ("ktcSfTep", "dlfSf"))
            market -= 13
        if i < N_IDP_VET:
            add(f"Idp Vet {i + 1:03d}", "LB", market, False, ("dlfIdp", "fantasyProsIdp"))
            market -= 11
    for i in range(N_OFF_ROOKIE):
        add(f"Off Rook {i + 1:03d}", "RB", market, True, ("ktcSfTep", "dlfRookieSf"))
        market -= 7
    for i in range(N_IDP_ROOKIE):
        add(f"Idp Rook {i + 1:03d}", "DL", market, True, ("dlfRookieIdp",))
        market -= 5

    return {
        "version": "curve-routing-fixture",
        "date": "2026-08-11",
        "settings": {},
        "sites": {},
        "maxValues": {},
        "players": players,
    }


def _build(overrides_json: str | None = None) -> dict[str, dict]:
    """Build the contract through the production entry point.

    ``csv_root`` points at an empty directory so no site CSV enrichment
    runs and the fixture's ``canonicalSiteValues`` are the whole input.
    Returns rows keyed by display name.
    """
    overrides = json.loads(overrides_json) if overrides_json else None
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        contract = build_api_data_contract(
            _raw_payload(),
            csv_root=Path(tmp),
            source_overrides=overrides,
        )
    return {str(row.get("displayName")): row for row in contract.get("playersArray") or []}


@lru_cache(maxsize=4)
def board(overrides_json: str | None = None) -> dict[str, dict]:
    return _build(overrides_json)


NO_BACKBONE = json.dumps({"idpTradeCalc": {"include": False}})


def meta_for(rows: dict[str, dict], name: str, source: str) -> dict:
    return ((rows[name].get("sourceRankMeta") or {}).get(source)) or {}


IDP_VETS = [f"Idp Vet {i:03d}" for i in range(1, N_IDP_VET + 1)]
IDP_ROOKIES = [f"Idp Rook {i:03d}" for i in range(1, N_IDP_ROOKIE + 1)]
OFF_VETS = [f"Off Vet {i:03d}" for i in range(1, N_OFF_VET + 1)]
OFF_ROOKIES = [f"Off Rook {i:03d}" for i in range(1, N_OFF_ROOKIE + 1)]


# ── Fixture validity ───────────────────────────────────────────────────


class TestFixtureIsCapableOfDetectingTheDefect(unittest.TestCase):
    """Guard the guards.

    Every routing assertion below is an equality between two curves.  If
    the two curves happened to agree at the ranks the fixture exercises,
    the tests would pass while proving nothing.  These run first.
    """

    def test_the_three_master_curves_are_distinguishable(self) -> None:
        for rank in (2, 10, 40, 80, 120, 141, 160):
            g = curve_value(rank, GLOBAL_CURVE)
            i = curve_value(rank, IDP_CURVE)
            self.assertNotEqual(
                g,
                i,
                f"GLOBAL and IDP masters agree at rank {rank}; the routing "
                "tests would be vacuous there",
            )

    def test_the_translated_source_and_the_cross_market_source_share_ranks(self) -> None:
        """The comparison is only meaningful if the ranks really are equal."""
        rows = board()
        for name in IDP_VETS:
            dlf = meta_for(rows, name, "dlfIdp")
            ds = meta_for(rows, name, "draftSharksIdp")
            self.assertTrue(dlf and ds, f"{name} missing a source stamp: {sorted(dlf)}")
            self.assertEqual(
                dlf["effectiveRank"],
                ds["effectiveRank"],
                f"{name}: fixture no longer aligns the two shared-market pools",
            )

    def test_both_comparators_take_the_rank_hill_path(self) -> None:
        """A value-direct source would compare price, not curve routing."""
        rows = board()
        for name in IDP_VETS[:5]:
            for source in ("dlfIdp", "fantasyProsIdp", "draftSharksIdp"):
                self.assertEqual(
                    meta_for(rows, name, source).get("valueContributionPath"),
                    "rank_hill",
                    f"{name}/{source} is not on the Hill path",
                )


# ── A. Same coordinate pool ⇒ same price ───────────────────────────────


class TestSameCoordinatePoolPricesIdentically(unittest.TestCase):
    """RED before the repair.

    ``dlfIdp`` and ``fantasyProsIdp`` have been crosswalked onto the
    backbone's shared offense+IDP ladder.  ``draftSharksIdp`` is natively
    ranked in that same combined pool.  All three are rank-signal.  At an
    identical effective rank they are describing the identical position
    in the identical population, so the board has exactly one defensible
    value for them.
    """

    def test_translated_idp_matches_cross_market_at_the_same_rank(self) -> None:
        rows = board()
        mismatches: list[str] = []
        for name in IDP_VETS:
            ds = meta_for(rows, name, "draftSharksIdp")
            for source in ("dlfIdp", "fantasyProsIdp"):
                got = meta_for(rows, name, source)
                if got["valueContribution"] != ds["valueContribution"]:
                    mismatches.append(
                        f"{name}/{source}: rank {got['effectiveRank']} priced "
                        f"{got['valueContribution']} vs draftSharksIdp "
                        f"{ds['valueContribution']} at rank {ds['effectiveRank']}"
                    )
        self.assertEqual(
            mismatches,
            [],
            f"{len(mismatches)} shared-market ranks priced on two different "
            f"curves. First few: {mismatches[:5]}",
        )


# ── B. The translated rank names its curve ─────────────────────────────


class TestTranslatedIdpRankUsesSharedMarketCurve(unittest.TestCase):
    """RED before the repair.

    States the routing directly rather than by comparison: a rank that
    the pipeline itself placed in shared-market coordinates must be
    converted by the shared-market (GLOBAL) master.
    """

    def test_shared_market_translated_ranks_take_the_global_master(self) -> None:
        rows = board()
        wrong: list[str] = []
        for name in IDP_VETS:
            for source in ("dlfIdp", "fantasyProsIdp"):
                got = meta_for(rows, name, source)
                self.assertIn(
                    got["method"],
                    ("exact", "interpolated", "extrapolated"),
                    f"{name}/{source} was not actually translated",
                )
                rank = got["effectiveRank"]
                if got["valueContribution"] != curve_value(rank, GLOBAL_CURVE):
                    wrong.append(
                        f"{name}/{source}: rank {rank} → {got['valueContribution']} "
                        f"(GLOBAL says {curve_value(rank, GLOBAL_CURVE)}, "
                        f"IDP says {curve_value(rank, IDP_CURVE)})"
                    )
        self.assertEqual(
            wrong,
            [],
            f"{len(wrong)} translated IDP ranks priced off the IDP-slice "
            f"master. First few: {wrong[:5]}",
        )


# ── C. An UNtranslated IDP rank stays IDP-local ────────────────────────


class TestUntranslatedIdpRankKeepsIdpCurve(unittest.TestCase):
    """GUARD — green before the repair and required to stay green.

    ``translate_position_rank`` passes the raw rank through unchanged and
    reports ``fallback`` when the ladder is empty, which is what happens
    when the backbone source is switched off on an override board.  That
    rank is an IDP-only ordinal and the IDP-slice master is the right
    curve for it.  The repair must key on what happened to the rank, not
    on the player being a defender.
    """

    def test_fallback_ranks_are_not_promoted_to_the_global_master(self) -> None:
        rows = board(NO_BACKBONE)
        checked = 0
        for name in IDP_VETS:
            for source in ("dlfIdp", "fantasyProsIdp"):
                got = meta_for(rows, name, source)
                self.assertEqual(
                    got["method"],
                    "fallback",
                    f"{name}/{source}: expected an untranslated rank with the " "backbone disabled",
                )
                rank = got["effectiveRank"]
                self.assertEqual(
                    got["valueContribution"],
                    curve_value(rank, IDP_CURVE),
                    f"{name}/{source}: an untranslated IDP-only rank must keep " "the IDP master",
                )
                checked += 1
        self.assertEqual(checked, 2 * N_IDP_VET)

    def test_a_skipped_rookie_ladder_also_stays_idp_local(self) -> None:
        """With no ``idpTradeCalc`` there is no IDP rookie ladder either.

        Phase 1d skips the pair and the within-class rank survives.  That
        rank is not shared-market, so it does not get the GLOBAL master.
        (It is not really an IDP-overall rank either — that residual is
        the separately-tracked ``scale_integrity_lost`` condition, which
        this repair deliberately does not touch.)
        """
        rows = board(NO_BACKBONE)
        for name in IDP_ROOKIES:
            got = meta_for(rows, name, "dlfRookieIdp")
            self.assertEqual(got["method"], "direct")
            self.assertEqual(
                got["valueContribution"],
                curve_value(got["effectiveRank"], IDP_CURVE),
            )


# ── D. Offense routing is untouched ────────────────────────────────────


class TestOffenseRoutingIsUnchanged(unittest.TestCase):
    """GUARD.  The repair is about coordinate pools, and offense ranks
    never leave the offense pool."""

    def test_offense_rank_signal_source_keeps_the_offense_master(self) -> None:
        rows = board()
        for name in OFF_VETS:
            got = meta_for(rows, name, "dlfSf")
            self.assertEqual(got["method"], "direct")
            self.assertEqual(
                got["valueContribution"],
                curve_value(got["effectiveRank"], OFFENSE_CURVE),
                f"{name}/dlfSf left the OFFENSE master",
            )

    def test_offense_master_is_not_silently_the_global_one(self) -> None:
        rows = board()
        differing = [
            name
            for name in OFF_VETS
            if curve_value(meta_for(rows, name, "dlfSf")["effectiveRank"], OFFENSE_CURVE)
            != curve_value(meta_for(rows, name, "dlfSf")["effectiveRank"], GLOBAL_CURVE)
        ]
        self.assertTrue(
            differing,
            "OFFENSE and GLOBAL agree everywhere in this fixture, so the "
            "guard above proves nothing",
        )


# ── E. Rookie ladders inherit their reference pool ─────────────────────


class TestRookieLadderFollowsItsReferencePool(unittest.TestCase):
    """Translation moves a rank INTO the target ladder's coordinates.

    Phase 1d maps a within-class rookie rank onto a reference source's
    ranks, so the result lives in whatever pool that reference occupies:

      * ``dlfRookieSf`` → ``ktcSfTep``      → offense pool  (guard)
      * ``dlfRookieIdp`` → ``idpTradeCalc`` → shared market (RED)

    W02-F001 was recorded as an IDP-source problem.  It is not: it is a
    translation problem, and the rookie IDP ladder reaches the same wrong
    curve without any of the three flagged sources being involved.
    """

    def test_offense_rookie_ladder_keeps_the_offense_master(self) -> None:
        rows = board()
        for name in OFF_ROOKIES:
            got = meta_for(rows, name, "dlfRookieSf")
            self.assertEqual(got["method"], "rookie_ladder_translation_via_ktcSfTep")
            self.assertEqual(
                got["valueContribution"],
                curve_value(got["effectiveRank"], OFFENSE_CURVE),
                f"{name}/dlfRookieSf: ktcSfTep's ranks are offense-pool ranks",
            )

    def test_idp_rookie_ladder_lands_in_shared_market_coordinates(self) -> None:
        rows = board()
        wrong: list[str] = []
        for name in IDP_ROOKIES:
            got = meta_for(rows, name, "dlfRookieIdp")
            self.assertEqual(got["method"], "rookie_ladder_translation_via_idpTradeCalc")
            rank = got["effectiveRank"]
            if got["valueContribution"] != curve_value(rank, GLOBAL_CURVE):
                wrong.append(
                    f"{name}: rank {rank} → {got['valueContribution']} "
                    f"(GLOBAL {curve_value(rank, GLOBAL_CURVE)}, "
                    f"IDP {curve_value(rank, IDP_CURVE)})"
                )
        self.assertEqual(
            wrong,
            [],
            "IDP rookie ranks translated through idpTradeCalc's shared-market "
            f"ladder were priced on the IDP master. First few: {wrong[:5]}",
        )

    def test_idp_rookie_matches_the_cross_market_source_at_the_same_rank(self) -> None:
        rows = board()
        wrong: list[str] = []
        for name in IDP_ROOKIES:
            got = meta_for(rows, name, "dlfRookieIdp")
            ds = meta_for(rows, name, "draftSharksIdp")
            self.assertEqual(got["effectiveRank"], ds["effectiveRank"])
            if got["valueContribution"] != ds["valueContribution"]:
                wrong.append(
                    f"{name}: {got['valueContribution']} vs {ds['valueContribution']} "
                    f"at rank {ds['effectiveRank']}"
                )
        self.assertEqual(wrong, [], f"{len(wrong)} rookie ranks priced twice: {wrong[:5]}")


# ── F. Provenance must record the outcome, not the intent ──────────────


class TestTranslationProvenanceIsHonest(unittest.TestCase):
    """RED before the repair.

    ``sharedMarketTranslated`` is stamped as::

        bool(needs_shared_market and row_scope == SOURCE_SCOPE_OVERALL_IDP)

    — the source's registered INTENT.  When the ladder is empty,
    ``translate_position_rank`` returns the raw rank with
    ``method == "fallback"`` and the field still reads True.  A reader
    (or a router) that trusts it concludes the rank is shared-market when
    it is an untranslated IDP ordinal.  Any routing built on this field
    inherits the lie, so it has to say what happened.
    """

    def test_it_reads_false_when_no_translation_occurred(self) -> None:
        rows = board(NO_BACKBONE)
        lying = [
            f"{name}/{source}"
            for name in IDP_VETS
            for source in ("dlfIdp", "fantasyProsIdp")
            if meta_for(rows, name, source)["method"] == "fallback"
            and meta_for(rows, name, source)["sharedMarketTranslated"] is True
        ]
        self.assertEqual(
            lying,
            [],
            f"{len(lying)} rows claim a shared-market translation that did not "
            f"happen. First few: {lying[:5]}",
        )

    def test_it_still_reads_true_when_translation_did_occur(self) -> None:
        rows = board()
        for name in IDP_VETS[:10]:
            for source in ("dlfIdp", "fantasyProsIdp"):
                got = meta_for(rows, name, source)
                self.assertTrue(
                    got["sharedMarketTranslated"],
                    f"{name}/{source} was translated ({got['method']}) and must say so",
                )


# ── G. The same invariant on the real exported board ───────────────────


def _live_contract() -> dict | None:
    files = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
    if not files:
        return None
    with files[0].open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    with contextlib.redirect_stdout(io.StringIO()):
        return build_api_data_contract(raw)


class TestLiveBoardHonoursTheCoordinatePool(unittest.TestCase):
    """RED before the repair, on the board production actually serves.

    The synthetic fixture proves the mechanism; this proves it is not an
    artifact of the fixture.  Skips when no export is checked out.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = _live_contract()

    def _rows_with(self, predicate) -> list[tuple[str, str, dict]]:
        out: list[tuple[str, str, dict]] = []
        for row in self.contract.get("playersArray") or []:
            for source, meta in (row.get("sourceRankMeta") or {}).items():
                if not isinstance(meta, dict):
                    continue
                if meta.get("valueContributionPath") != "rank_hill":
                    continue
                if predicate(source, meta):
                    out.append((str(row.get("displayName")), source, meta))
        return out

    def test_every_translated_rank_is_priced_on_the_shared_market_master(self) -> None:
        if self.contract is None:
            self.skipTest("no exported board to build from")

        def translated(source: str, meta: dict) -> bool:
            method = str(meta.get("method") or "")
            if meta.get("sharedMarketTranslated") and method in (
                "exact",
                "interpolated",
                "extrapolated",
            ):
                return True
            return method == "rookie_ladder_translation_via_idpTradeCalc"

        rows = self._rows_with(translated)
        self.assertTrue(rows, "no translated rank-Hill rows on the live board")
        wrong = [
            f"{name}/{source} rank {meta['effectiveRank']} → "
            f"{meta['valueContribution']} (GLOBAL "
            f"{curve_value(meta['effectiveRank'], GLOBAL_CURVE)})"
            for name, source, meta in rows
            if meta["valueContribution"] != curve_value(meta["effectiveRank"], GLOBAL_CURVE)
        ]
        self.assertEqual(
            wrong,
            [],
            f"{len(wrong)} of {len(rows)} translated live rows are priced off "
            f"the wrong master. First few: {wrong[:5]}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
