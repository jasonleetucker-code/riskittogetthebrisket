"""W02-F003 — what the IDP market corridor does today, pinned.

These began as **characterization** tests, written GREEN against the
pre-repair board so that any candidate policy's effect would show up as a
test diff rather than as a number someone had to notice. They did exactly
that: removing the hard cap turned seven of them red, four here and three
in `test_market_corridor_clamp.py`, and each was then rewritten against
the measured post-repair behaviour with the reason recorded in the
assertion message. That RED set is the change's receipt.

They still are not assertions that any of this is *correct* — they pin
what the pipeline does so the next change has to argue with them.

The existing `test_market_corridor_clamp.py` covers the mechanism's happy
path. What was missing, and what B3 needs before touching anything, is a
pinned record of the *live* distribution: how much of the IDP board the
corridor decides, which band it uses, where clamped rows land, which way
they move, and what the anchor actually is.

Everything drives `build_api_data_contract` — the production entry point.
The synthetic cases build a raw payload and let the real pipeline run;
none of them re-implements the corridor formula, because a test that
re-implements the thing it is testing pins the copy rather than the code.

Measured at the B3 pin (code `2449af9ac`, board sha256₁₆
`8fb6ede274171aee`). Bounds are deliberately loose where the underlying
quantity is a property of this week's market data rather than of the code
— a tight assertion there goes red when sources agree more closely, which
is noise. Where the quantity is a property of the CODE (no clamp capped,
every clamp on the band edge, the anchor being a voting source) the
assertion is exact.
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
    _MARKET_ANCHOR_BY_ASSET_CLASS,
    _MARKET_ANCHOR_FALLBACKS,
    _MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS,
    _MARKET_CORRIDOR_MIN_BUCKET_N,
    _MARKET_CORRIDOR_PERCENTILE,
    _RANKING_SOURCES,
    build_api_data_contract,
)

REPO = Path(__file__).resolve().parents[2]


def _live() -> dict | None:
    files = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
    if not files:
        return None
    raw = json.loads(files[0].read_text(encoding="utf-8"))
    with contextlib.redirect_stdout(io.StringIO()):
        return build_api_data_contract(raw)


@lru_cache(maxsize=1)
def live() -> dict | None:
    return _live()


# ── the configuration itself ───────────────────────────────────────────


class TestCorridorConfiguration(unittest.TestCase):
    def test_no_asset_class_carries_a_hard_cap_after_b3(self) -> None:
        """The B3 repair. The facility is kept — the mechanism is
        generic — but nothing populates it, so the band is whatever the
        board's own drift distribution produces."""
        self.assertEqual(_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS, {})

    def test_the_empirical_machinery_is_still_configured(self) -> None:
        self.assertEqual(_MARKET_CORRIDOR_PERCENTILE, 0.90)
        self.assertEqual(_MARKET_CORRIDOR_MIN_BUCKET_N, 30)

    def test_every_idp_anchor_is_a_voting_source_in_the_blend_it_clamps(self) -> None:
        """The lineage fact, pinned at the registry level.

        `idpTradeCalc` anchors the corridor AND votes in the blend the
        corridor constrains; so does every fallback. This is not a
        statement that the corridor is wrong — it is the reason the
        corridor cannot be described as independent market evidence, and
        it must not become true-by-accident of some future source.
        """
        voting = {str(s.get("key") or "") for s in _RANKING_SOURCES}
        chain = _MARKET_ANCHOR_FALLBACKS["idp"]
        self.assertEqual(chain, ["idpTradeCalc", "dlfIdp", "idpShow", "fantasyProsIdp"])
        for key in chain:
            self.assertIn(
                key,
                voting,
                f"{key} anchors the IDP corridor but no longer votes — the "
                "lineage claim in the B3 evidence needs re-deriving",
            )
        self.assertEqual(_MARKET_ANCHOR_BY_ASSET_CLASS["idp"], "idpTradeCalc")


# ── the live distribution ──────────────────────────────────────────────


class TestLiveCorridorDistribution(unittest.TestCase):
    """Pins what the corridor decides on the board production serves."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = live()

    def _rows(self) -> list[dict]:
        if self.contract is None:
            self.skipTest("no exported board to build from")
        return list(self.contract.get("playersArray") or [])

    def _clamped(self) -> list[dict]:
        return [r for r in self._rows() if r.get("marketCorridorClamp")]

    def _ranked_idp(self) -> list[dict]:
        return [
            r
            for r in self._rows()
            if r.get("assetClass") == "idp" and r.get("canonicalConsensusRank")
        ]

    def test_the_corridor_is_a_tail_rail_not_a_majority_of_the_board(self) -> None:
        """The B3 repair's headline effect.

        Before: 183/329 = 55.6%, reaching 25 of the top third. After:
        32/329 = 9.7%, entirely in the tail. The exact share is
        market-dependent, so this asserts the *shape* — a minority of
        rows, and none near the top of the board.
        """
        clamped, pop = self._clamped(), self._ranked_idp()
        self.assertGreater(len(pop), 50, "too few ranked IDP rows to characterize")
        rate = len(clamped) / len(pop)
        self.assertLess(
            rate,
            0.25,
            f"the corridor is back to deciding {rate:.1%} of the ranked IDP "
            "board — B3 reduced it to a tail rail; re-derive before accepting",
        )
        ranked = sorted(pop, key=lambda r: r["canonicalConsensusRank"])
        top_third = {str(r.get("displayName")) for r in ranked[: max(1, len(ranked) // 3)]}
        in_top = [r for r in clamped if str(r.get("displayName")) in top_third]
        self.assertEqual(
            in_top,
            [],
            f"{len(in_top)} clamped rows are in the top third of the IDP "
            "board — the corridor is overriding well-ranked players again",
        )

    def test_the_corridor_no_longer_overrides_well_covered_rows(self) -> None:
        """Criterion 2 of the B3 evaluation, as a test.

        With the cap in place the clamp rate was INVERTED against the
        board's own confidence — 63.9% of high-confidence rows against
        45.8% of medium — and 89.3% of 3-source rows were clamped while
        5-source rows were 26.2%. After the repair no row with five or
        more contributing sources is clamped at all.
        """
        thick = [r for r in self._clamped() if len(r.get("sourceRankMeta") or {}) >= 5]
        self.assertEqual(
            [str(r.get("displayName")) for r in thick],
            [],
            "a row backed by five or more sources was overridden toward a "
            "single anchor source that is itself one of those sources",
        )

    def test_only_idp_rows_are_clamped(self) -> None:
        """Offense is exempt by an explicit guard; picks reach the loop and
        are dropped for having no anchor chain, which is a different
        mechanism and worth pinning separately."""
        classes = {str(r.get("assetClass")) for r in self._clamped()}
        self.assertEqual(classes, {"idp"})

    def test_every_clamp_now_uses_the_board_derived_band(self) -> None:
        """The inverse of the defect. Before B3 every clamp reported
        ``cappedByMaxBand: True`` and ``bandPct: 0.15``; the empirical
        band was computed and discarded 183 times out of 183."""
        clamped = self._clamped()
        self.assertTrue(clamped)
        for r in clamped:
            c = r["marketCorridorClamp"]
            self.assertFalse(
                c["cappedByMaxBand"], f"{r.get('displayName')} was capped by a hard band"
            )
            self.assertIsNone(c["maxBandPct"])
            self.assertGreater(c["bandPct"], 0.15)

    def test_every_clamped_row_lands_exactly_on_the_band_edge(self) -> None:
        """So a clamped row's value is `anchor × (1 ± band)` — the blend
        does not determine it."""
        for r in self._clamped():
            c = r["marketCorridorClamp"]
            sign = 1 if c["direction"] == "down" else -1
            edge = c["marketAnchor"] * (1.0 + sign * c["bandPct"])
            self.assertLessEqual(
                abs(round(edge) - c["clampedValue"]),
                1,
                f"{r.get('displayName')} did not land on the band edge",
            )

    def test_the_corridor_now_acts_predominantly_as_a_ceiling(self) -> None:
        """B3 measured 23 up / 160 down. Pre-B2 it was 57/74, so the
        direction flipped when the curve-routing repair raised IDP values."""
        clamped = self._clamped()
        down = sum(1 for r in clamped if r["marketCorridorClamp"]["direction"] == "down")
        self.assertGreater(
            down / len(clamped),
            0.60,
            "the corridor is no longer predominantly a ceiling — re-derive "
            "the B3 direction finding before relying on it",
        )

    def test_the_anchor_is_idptradecalc_and_it_also_voted(self) -> None:
        """The double-count, on live rows: on every clamped row the anchor
        source also contributed to the blend being clamped."""
        clamped = self._clamped()
        also_voted = 0
        for r in clamped:
            source = str(r["marketCorridorClamp"].get("marketSource"))
            self.assertEqual(source, "idpTradeCalc")
            if source in (r.get("sourceRankMeta") or {}):
                also_voted += 1
        self.assertEqual(
            also_voted,
            len(clamped),
            "some clamped row was anchored to a source that did not vote on "
            "it — the fallback chain has started firing, which changes the "
            "lineage analysis",
        )

    def test_suppressing_the_corridor_changes_the_served_board(self) -> None:
        """Guards the measurement route itself. `consensus_edge` relies on
        this flag; if it stopped doing anything, the fair-value board would
        silently become anchor-contaminated again."""
        if self.contract is None:
            self.skipTest("no exported board to build from")
        files = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
        raw = json.loads(files[0].read_text(encoding="utf-8"))
        with contextlib.redirect_stdout(io.StringIO()):
            unclamped = build_api_data_contract(raw, suppress_market_corridor_clamp=True)
        self.assertFalse(
            [r for r in unclamped.get("playersArray") or [] if r.get("marketCorridorClamp")]
        )
        served = {
            r.get("displayName"): r.get("rankDerivedValue")
            for r in self.contract.get("playersArray") or []
        }
        without = {
            r.get("displayName"): r.get("rankDerivedValue")
            for r in unclamped.get("playersArray") or []
        }
        moved = [k for k, v in served.items() if k in without and without[k] != v]
        self.assertGreater(len(moved), 10, "the corridor moved almost nothing")


# ── deterministic mechanism cases through the production path ──────────

IDP_POSITIONS = ("DL", "LB", "DB")


def _payload(rows: list[tuple[str, str, dict]]) -> dict:
    players: dict[str, dict] = {}
    for name, pos, sites in rows:
        row = {"_canonicalSiteValues": dict(sites), "position": pos, "age": 25}
        row.update(sites)
        players[name] = row
    return {
        "version": "corridor-fixture",
        "date": "2026-08-11",
        "settings": {},
        "sites": {},
        "maxValues": {},
        "players": players,
    }


def _build(rows: list[tuple[str, str, dict]], **kwargs) -> dict[str, dict]:
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        contract = build_api_data_contract(_payload(rows), csv_root=Path(tmp), **kwargs)
    return {str(r.get("displayName")): r for r in contract.get("playersArray") or []}


class TestCorridorMechanismOnSyntheticBoards(unittest.TestCase):
    """Cases the live board cannot exhibit on demand."""

    @staticmethod
    def _rows(idp_extra: dict | None = None) -> list[tuple[str, str, dict]]:
        rows: list[tuple[str, str, dict]] = []
        market = 9000
        for i in range(40):
            rows.append(
                (
                    f"Off {i + 1:02d}",
                    "WR",
                    {"ktcSfTep": market, "idpTradeCalc": market, "dlfSf": market},
                )
            )
            market -= 90
        for i in range(40):
            sites = {"idpTradeCalc": market, "dlfIdp": market, "idpShow": market}
            if idp_extra and i == 0:
                sites.update(idp_extra)
            rows.append((f"Idp {i + 1:02d}", "LB", sites))
            market -= 70
        return rows

    def test_a_row_with_no_anchor_is_never_clamped(self) -> None:
        """`_market_anchor_for_row` returns (None, None) when nothing in the
        chain contributed, and the caller must skip rather than invent a
        band. Missing is not zero."""
        rows = self._rows()
        rows.append(("Anchorless DB", "DB", {"draftSharksIdp": 40}))
        built = _build(rows)
        row = built["Anchorless DB"]
        self.assertIsNone(row.get("marketCorridorClamp"))

    def test_picks_reach_the_loop_and_are_dropped_for_having_no_chain(self) -> None:
        """The offense guard is `assetClass == "offense"`, so picks are NOT
        exempted by it — they survive to `_market_anchor_for_row` and are
        dropped there because `_MARKET_ANCHOR_FALLBACKS` has no pick key.
        Two different mechanisms with the same visible outcome; pinned so a
        future pick anchor does not silently start clamping picks."""
        self.assertNotIn("pick", _MARKET_ANCHOR_FALLBACKS)
        if live() is not None:
            picks = [
                r
                for r in live().get("playersArray") or []
                if r.get("assetClass") == "pick" and r.get("marketCorridorClamp")
            ]
            self.assertEqual(picks, [])

    def test_offense_rows_are_never_clamped_even_when_they_drift(self) -> None:
        built = _build(self._rows())
        for name, row in built.items():
            if row.get("assetClass") == "offense":
                self.assertIsNone(row.get("marketCorridorClamp"), name)

    def test_a_tight_board_uses_the_empirical_band_not_the_cap(self) -> None:
        """The percentile machinery is live code, not dead code — it is
        this week's unusually wide IDP disagreement that makes the cap win
        every time on the real board. Proven here rather than asserted, so
        the B3 conclusion says 'unreachable on this board', not 'dead'."""
        built = _build(self._rows())
        clamps = [r["marketCorridorClamp"] for r in built.values() if r.get("marketCorridorClamp")]
        if not clamps:
            self.skipTest("tight fixture produced no clamps, which is the point")
        self.assertTrue(
            any(not c["cappedByMaxBand"] for c in clamps),
            "even a tight synthetic board is capped — the empirical band may "
            "genuinely be unreachable, which would change the B3 conclusion",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
