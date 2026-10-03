"""``activity.serving_view`` — the ``GET /api/public/league/activity`` body.

The section's in-process consumers (overview, CSV export, archives, the
full public contract, grading itself) read ``build_section``'s full output,
so the trim happens ONLY at the HTTP serving step.  Its two readers are
``app/league/sections/activity.jsx`` (+ ``TradeFlowSankey``,
``ActivityHeatmap``, ``TradeCard``) and ``lib/activity-feed.js``.

Pinned here:
    1. Every field those readers use survives (the consumer contract).
    2. Fields no reader uses are dropped, including grade diagnostics.
    3. Presence is preserved: an absent grade stays absent, an unavailable
       grade stays explicitly unavailable — nothing is coerced to a value.
    4. The full section is never mutated.
    5. A byte budget on a production-shaped feed.
"""

from __future__ import annotations

import copy
import json
import random
import unittest

from src.public_league import activity

# What the two page readers read, per level (the audit, as data).
_READ_SECTION = {
    "feed",
    "totalCount",
    "picksMovedCount",
    "playersMovedCount",
    "mostActiveTrader",
    "mostFrequentPartnerPair",
    "positionMixMoved",
}
_READ_TRADE = {"transactionId", "season", "week", "createdAt", "totalAssets", "sides"}
_READ_SIDE = {"rosterId", "ownerId", "displayName", "teamName", "receivedAssets", "grade"}
_READ_PLAYER = {"kind", "playerName", "position"}
_READ_PICK = {"kind", "label", "season", "round"}


def _player(rng: random.Random, i: int) -> dict:
    return {
        "kind": "player",
        "playerId": str(10000 + i),
        "playerName": rng.choice(("Emeka Egbuka", "J.J. McCarthy", "Malik Nabers", "Bo Nix")),
        "position": rng.choice(("QB", "RB", "WR", "TE", "LB")),
    }


def _pick(rng: random.Random) -> dict:
    season = rng.choice(("2026", "2027", "2028"))
    rnd = rng.randrange(1, 5)
    return {
        "kind": "pick",
        "season": season,
        "round": rnd,
        "fromRosterId": rng.randrange(1, 13),
        "label": f"{season} R{rnd}",
    }


def _production_shaped_section(n_trades: int = 222, limit: int = 200) -> dict:
    """Shape measured on the production payload of 2026-09-29: ~2.06 sides
    per trade, ~2.19 received assets per side, ~26% picks, ~88% of sides
    ungraded with every asset listed in ``missingAssets``."""
    rng = random.Random(1338)
    feed = []
    for t in range(n_trades):
        sides = []
        n_sides = 3 if rng.random() < 0.06 else 2
        for s in range(n_sides):
            received = [
                _pick(rng) if rng.random() < 0.26 else _player(rng, t * 10 + j)
                for j in range(rng.choice((1, 1, 2, 2, 3, 4)))
            ]
            sent = [
                _pick(rng) if rng.random() < 0.26 else _player(rng, t * 10 + j + 5)
                for j in range(rng.choice((1, 2, 2, 3)))
            ]
            if rng.random() < 0.88:
                grade = {
                    "grade": None,
                    "color": None,
                    "label": "Insufficient historical evidence",
                    "available": False,
                    "reason": "no_historical_evidence",
                    "missingAssets": [
                        {"kind": a["kind"], "name": a.get("playerName") or a.get("label")}
                        for a in received + sent
                    ],
                }
            else:
                grade = {"grade": "B+", "color": "#2ecc71", "label": "Slight overpay"}
            sides.append(
                {
                    "rosterId": s + 1,
                    "ownerId": str(468418790212759552 + s),
                    "displayName": "Manager",
                    "teamName": "Medical Murrayjuana",
                    "receivedAssets": received,
                    "sentAssets": sent,
                    "sentPlayerIds": [a["playerId"] for a in sent if a["kind"] == "player"],
                    "receivedPlayerCount": sum(a["kind"] == "player" for a in received),
                    "receivedPickCount": sum(a["kind"] == "pick" for a in received),
                    "notableAssetCount": 1,
                    "grade": grade,
                }
            )
        feed.append(
            {
                "transactionId": str(1410387162507075584 + t),
                "season": "2026",
                "leagueId": "1312006700437352448",
                "week": rng.randrange(0, 18),
                "createdAt": 1790625012570 - t * 86_400_000,
                "sides": sides,
                "totalAssets": sum(len(s["receivedAssets"]) for s in sides),
                "notableAssetCount": 2,
            }
        )
    blockbusters = copy.deepcopy(feed[:5])
    return {
        "feed": feed[:limit],
        "totalCount": len(feed),
        "perSeasonCounts": [{"season": "2026", "leagueId": "L", "tradeCount": len(feed)}],
        "byManager": [{"ownerId": str(i), "trades": 30 - i} for i in range(12)],
        "partnerPairs": [
            {"ownerIds": [str(i), str(j)], "trades": 3} for i in range(12) for j in range(i)
        ],
        "mostActiveTrader": {"ownerId": "1", "trades": 30, "displayName": "Jason"},
        "mostFrequentPartnerPair": {
            "ownerIds": ["1", "2"],
            "trades": 9,
            "displayNames": ["Jason", "MaKayla"],
        },
        "biggestBlockbusters": blockbusters,
        "timelineByWeek": [{"season": "2026", "week": w, "trades": 3} for w in range(18)],
        "positionMixMoved": {"WR": 40, "RB": 30, "QB": 20, "TE": 10},
        "picksMovedCount": 120,
        "playersMovedCount": 300,
    }


def _bytes(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class ServingViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.section = _production_shaped_section()
        self.view = activity.serving_view(self.section)

    def test_every_field_the_page_readers_use_survives(self) -> None:
        self.assertEqual(set(self.view), _READ_SECTION)
        self.assertEqual(self.view["mostActiveTrader"], self.section["mostActiveTrader"])
        self.assertEqual(
            self.view["mostFrequentPartnerPair"], self.section["mostFrequentPartnerPair"]
        )
        self.assertEqual(len(self.view["feed"]), len(self.section["feed"]))
        for got, full in zip(self.view["feed"], self.section["feed"], strict=True):
            self.assertEqual(set(got), _READ_TRADE)
            for key in _READ_TRADE - {"sides"}:
                self.assertEqual(got[key], full[key])
            for side, full_side in zip(got["sides"], full["sides"], strict=True):
                self.assertEqual(set(side), _READ_SIDE)
                for key in ("rosterId", "ownerId", "displayName", "teamName"):
                    self.assertEqual(side[key], full_side[key])
                for asset, full_asset in zip(
                    side["receivedAssets"], full_side["receivedAssets"], strict=True
                ):
                    wanted = _READ_PLAYER if full_asset["kind"] == "player" else _READ_PICK
                    self.assertEqual(asset, {k: full_asset[k] for k in wanted})

    def test_grade_keeps_its_display_fields_and_drops_diagnostics(self) -> None:
        seen_unavailable = seen_graded = False
        for trade, full in zip(self.view["feed"], self.section["feed"], strict=True):
            for side, full_side in zip(trade["sides"], full["sides"], strict=True):
                grade, full_grade = side["grade"], full_side["grade"]
                if full_grade.get("available") is False:
                    seen_unavailable = True
                    self.assertEqual(
                        grade,
                        {
                            "available": False,
                            "grade": None,
                            "color": None,
                            "label": "Insufficient historical evidence",
                        },
                    )
                else:
                    seen_graded = True
                    # No ``available`` key invented for a graded side.
                    self.assertEqual(grade, full_grade)
        self.assertTrue(seen_unavailable and seen_graded)

    def test_an_absent_grade_stays_absent(self) -> None:
        # Grading disabled (no ledger): the feed carries no grade at all,
        # and the view must not manufacture one.
        section = _production_shaped_section(n_trades=3, limit=3)
        for trade in section["feed"]:
            for side in trade["sides"]:
                del side["grade"]
        view = activity.serving_view(section)
        for trade in view["feed"]:
            for side in trade["sides"]:
                self.assertNotIn("grade", side)

    def test_the_full_section_is_never_mutated(self) -> None:
        section = _production_shaped_section(n_trades=20, limit=20)
        before = copy.deepcopy(section)
        activity.serving_view(section)
        self.assertEqual(section, before)

    def test_byte_budget_on_a_production_shaped_feed(self) -> None:
        full, served = _bytes(self.section), _bytes(self.view)
        # Production 2026-09-29: 423,332 B -> 173,988 B (41%).  The
        # synthetic feed lands in the same place; a later field added to
        # the view without a reader shows up here first.
        self.assertLess(served, 0.5 * full, (served, full))
        self.assertLess(served / len(self.view["feed"]), 900, served)


if __name__ == "__main__":
    unittest.main()
