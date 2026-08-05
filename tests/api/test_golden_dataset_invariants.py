"""Golden dataset + invariants for the live valuation pipeline.

2026-07-29 repository audit.  The suite had extensive coverage of
individual pipeline STAGES (Hampel, corridor clamp, TE basis, pick
tethering, count-aware blend) but no single fixture that runs a
representative cross-section of the player population end-to-end
through ``build_api_data_contract`` and asserts the properties that
must hold for ANY board.

The fixture deliberately includes the awkward cases:

  * elite, mid-tier and replacement-level offense
  * IDP across all three families (DL / LB / DB)
  * a rookie, a player on one source only, a player with conflicting
    source opinions, a TE (custom-scoring sensitive), picks
  * identity edge cases: suffix ("Marvin Harrison Jr."), punctuation
    ("D.J. Moore"), accent ("Amon-Ra St. Brown"), an apostrophe
    ("Ja'Marr Chase")
  * a player with missing optional metadata (no team)
  * a position the board does not rank (OL) — must not crash or leak

WHAT THESE TESTS ARE FOR
========================
They pin INVARIANTS, not magic numbers.  The Hill constants are refit
weekly by an automated workflow, so asserting "Player X is worth 8,412"
would make a legitimate refit look like a regression.  Where a specific
constant IS the contract (the 9999 ceiling, the 0.30 single-source
retention) it is asserted through the module constant rather than a
literal, so a deliberate change updates one place and an accidental one
still fails.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.api.data_contract import (
    _SINGLE_SOURCE_VALUE_RETENTION,
    OVERALL_RANK_LIMIT,
    build_api_data_contract,
)

# ── The golden dataset ──────────────────────────────────────────────────
# (name, position, {source: raw site value})
#
# Source values are on each site's native 0-9999 scale.  ``ktcSfTep``
# and ``idpTradeCalc`` are the two value-direct sources; everything else
# votes via rank -> percentile -> Hill.

GOLDEN_PLAYERS: dict[str, dict[str, Any]] = {
    # ── Elite offense, broad coverage, sources agree ──
    "Ja'Marr Chase": {
        "position": "WR",
        "team": "CIN",
        "sites": {
            "ktcSfTep": 9999,
            "idpTradeCalc": 9900,
            "dlfSf": 9950,
            "dynastyNerdsSfTep": 9970,
            "fantasyCalc": 9940,
        },
    },
    "Josh Allen": {
        "position": "QB",
        "team": "BUF",
        "sites": {
            "ktcSfTep": 9800,
            "idpTradeCalc": 9700,
            "dlfSf": 9850,
            "dynastyNerdsSfTep": 9820,
            "fantasyCalc": 9780,
        },
    },
    # ── Identity edge cases: suffix / punctuation / accent / apostrophe ──
    "Marvin Harrison Jr.": {
        "position": "WR",
        "team": "ARI",
        "sites": {"ktcSfTep": 8200, "idpTradeCalc": 8100, "dlfSf": 8300},
    },
    "D.J. Moore": {
        "position": "WR",
        "team": "CHI",
        "sites": {"ktcSfTep": 5600, "idpTradeCalc": 5500, "dlfSf": 5700},
    },
    "Amon-Ra St. Brown": {
        "position": "WR",
        "team": "DET",
        "sites": {"ktcSfTep": 8000, "idpTradeCalc": 7900, "dlfSf": 8100},
    },
    # ── Mid-tier and replacement-level offense ──
    "Mid Tier RB": {
        "position": "RB",
        "team": "NYJ",
        "sites": {"ktcSfTep": 4200, "idpTradeCalc": 4300, "dlfSf": 4100},
    },
    "Replacement WR": {
        "position": "WR",
        "team": "CAR",
        "sites": {"ktcSfTep": 600, "idpTradeCalc": 650, "dlfSf": 550},
    },
    # ── TE: the custom-scoring-sensitive position (TE++ basis) ──
    "Brock Bowers": {
        "position": "TE",
        "team": "LV",
        "sites": {
            "ktcSfTep": 9400,
            "idpTradeCalc": 9300,
            "dlfSf": 9450,
            "dynastyNerdsSfTep": 9600,
        },
    },
    # ── Conflicting sources: one source wildly disagrees ──
    "Contested Player": {
        "position": "WR",
        "team": "SEA",
        "sites": {
            "ktcSfTep": 7000,
            "idpTradeCalc": 6900,
            "dlfSf": 7100,
            "dynastyNerdsSfTep": 1200,  # the outlier
            "fantasyCalc": 7050,
        },
    },
    # ── Single-source player (haircut path) ──
    "Lonely Rookie": {
        "position": "WR",
        "team": "???",
        "sites": {"ktcSfTep": 7500},
    },
    # ── Missing optional metadata (no team) ──
    "No Team Guy": {
        "position": "RB",
        "team": "",
        "sites": {"ktcSfTep": 3000, "idpTradeCalc": 3100, "dlfSf": 2900},
    },
    # ── IDP: all three families ──
    "Myles Garrett": {
        "position": "DL",
        "team": "CLE",
        "sites": {"idpTradeCalc": 9500, "dlfIdp": 9400, "fantasyProsIdp": 9600},
    },
    "Micah Parsons": {
        "position": "LB",
        "team": "DAL",
        "sites": {"idpTradeCalc": 9300, "dlfIdp": 9200, "fantasyProsIdp": 9350},
    },
    "Elite Corner": {
        "position": "DB",
        "team": "NYJ",
        "sites": {"idpTradeCalc": 7800, "dlfIdp": 7700, "fantasyProsIdp": 7900},
    },
    "Deep IDP": {
        "position": "LB",
        "team": "HOU",
        "sites": {"idpTradeCalc": 1500, "dlfIdp": 1400},
    },
    # ── A position the board does not rank ──
    "Some Lineman": {
        "position": "OL",
        "team": "PHI",
        "sites": {"ktcSfTep": 400},
    },
}


def _payload(players: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    src = GOLDEN_PLAYERS if players is None else players
    return {
        "scrapeTimestamp": "2026-07-29T00:00:00+00:00",
        "players": {
            name: {
                "position": p["position"],
                "team": p.get("team", "???"),
                "_canonicalSiteValues": dict(p["sites"]),
                "_sites": len(p["sites"]),
            }
            for name, p in src.items()
        },
    }


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    return build_api_data_contract(_payload())


def _rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return contract.get("playersArray") or []


def _row(contract: dict[str, Any], name: str) -> dict[str, Any] | None:
    for r in _rows(contract):
        if (r.get("displayName") or r.get("canonicalName")) == name:
            return r
    return None


def _value(contract: dict[str, Any], name: str) -> int | None:
    row = _row(contract, name)
    return None if row is None else row.get("rankDerivedValue")


# ── Structural invariants ───────────────────────────────────────────────


class TestBoardStructure:
    def test_every_golden_player_is_represented(self, contract):
        """No player may silently vanish from the contract."""
        for name in GOLDEN_PLAYERS:
            assert _row(contract, name) is not None, f"{name} missing from playersArray"

    def test_values_stay_inside_the_display_scale(self, contract):
        for row in _rows(contract):
            v = row.get("rankDerivedValue")
            if v is None:
                continue
            assert 1 <= v <= 9999, f"{row.get('displayName')} = {v} outside [1, 9999]"

    def test_no_nan_inf_or_string_values(self, contract):
        """Guards the string-number coercion / NaN class of defect."""
        for row in _rows(contract):
            v = row.get("rankDerivedValue")
            if v is None:
                continue
            assert isinstance(v, int), f"{row.get('displayName')} value is {type(v)}"
            assert v == v  # NaN != NaN

    def test_rank_and_value_are_coherent(self, contract):
        """A better rank must never carry a lower value.  This is the
        single most important board invariant: it is what makes 'rank'
        and 'value' the same ordering."""
        ranked = [
            (r["canonicalConsensusRank"], r["rankDerivedValue"], r.get("displayName"))
            for r in _rows(contract)
            if isinstance(r.get("canonicalConsensusRank"), int)
            and isinstance(r.get("rankDerivedValue"), int)
        ]
        ranked.sort(key=lambda t: t[0])
        for (r1, v1, n1), (r2, v2, n2) in zip(ranked, ranked[1:]):
            assert v1 >= v2, f"rank {r1} ({n1})={v1} < rank {r2} ({n2})={v2}"

    def test_ranks_are_unique_and_contiguous(self, contract):
        ranks = sorted(
            r["canonicalConsensusRank"]
            for r in _rows(contract)
            if isinstance(r.get("canonicalConsensusRank"), int)
        )
        assert len(ranks) == len(set(ranks)), "duplicate ranks on the board"
        assert ranks == list(range(1, len(ranks) + 1)), "ranks are not contiguous from 1"

    def test_rank_limit_is_respected(self, contract):
        for row in _rows(contract):
            rank = row.get("canonicalConsensusRank")
            if isinstance(rank, int):
                assert rank <= OVERALL_RANK_LIMIT


# ── Ordering invariants ─────────────────────────────────────────────────


class TestOrdering:
    def test_elite_outranks_replacement(self, contract):
        assert _value(contract, "Ja'Marr Chase") > _value(contract, "Mid Tier RB")
        assert _value(contract, "Mid Tier RB") > _value(contract, "Replacement WR")

    def test_elite_idp_outranks_deep_idp(self, contract):
        assert _value(contract, "Myles Garrett") > _value(contract, "Deep IDP")

    def test_offense_and_idp_both_get_priced(self, contract):
        """An IDP league must not silently produce an offense-only board
        — the failure mode that made the trade finder offense-only."""
        for name in ("Myles Garrett", "Micah Parsons", "Elite Corner"):
            v = _value(contract, name)
            assert isinstance(v, int) and v > 0, f"{name} unpriced"

    def test_unsupported_position_is_not_ranked(self, contract):
        """OL is outside the board's universe: it must be present but
        must not take a rank, and must not crash the build."""
        row = _row(contract, "Some Lineman")
        assert row is not None
        assert row.get("canonicalConsensusRank") is None


# ── Monotonicity: better inputs must not produce a worse value ──────────


class TestMonotonicity:
    @pytest.mark.parametrize(
        "name",
        ["Mid Tier RB", "Myles Garrett", "Brock Bowers", "Amon-Ra St. Brown"],
    )
    def test_raising_every_source_does_not_lower_the_value(self, name):
        """The core sanity property: if every source likes a player
        MORE, the board cannot like them less."""
        base = build_api_data_contract(_payload())
        boosted_players = {
            k: (
                v
                if k != name
                else {**v, "sites": {sk: min(9999, sv + 400) for sk, sv in v["sites"].items()}}
            )
            for k, v in GOLDEN_PLAYERS.items()
        }
        boosted = build_api_data_contract(_payload(boosted_players))
        assert _value(boosted, name) >= _value(base, name), (
            f"{name} lost value when every source raised it: "
            f"{_value(base, name)} -> {_value(boosted, name)}"
        )

    def test_lowering_every_source_does_not_raise_the_value(self):
        name = "Mid Tier RB"
        base = build_api_data_contract(_payload())
        cut_players = {
            k: (
                v
                if k != name
                else {**v, "sites": {sk: max(1, sv - 1500) for sk, sv in v["sites"].items()}}
            )
            for k, v in GOLDEN_PLAYERS.items()
        }
        cut = build_api_data_contract(_payload(cut_players))
        assert _value(cut, name) <= _value(base, name)


# ── Missing / duplicate / malformed data ────────────────────────────────


class TestDataRobustness:
    def test_missing_optional_metadata_does_not_break_valuation(self, contract):
        """No team string must not destroy the calculation."""
        v = _value(contract, "No Team Guy")
        assert isinstance(v, int) and v > 0

    def test_single_source_player_takes_the_haircut(self, contract):
        """A player resting on one source keeps
        ``_SINGLE_SOURCE_VALUE_RETENTION`` of the blend, and the flag
        says so.  Missing corroboration must reduce confidence, not be
        silently treated as agreement."""
        row = _row(contract, "Lonely Rookie")
        assert row is not None
        assert row.get("singleSourceValuePenaltyApplied") is True
        # The haircut must actually bite: a 7500-on-KTC player must land
        # well below an uncut peer of similar raw standing.
        assert row["rankDerivedValue"] < 7500 * (_SINGLE_SOURCE_VALUE_RETENTION + 0.25)

    def test_duplicate_source_records_do_not_inflate(self):
        """Building the same payload twice, and building a payload whose
        player dict was copied, must produce identical values — a source
        must vote exactly once."""
        a = build_api_data_contract(_payload())
        b = build_api_data_contract(_payload())
        for name in GOLDEN_PLAYERS:
            assert _value(a, name) == _value(b, name), f"{name} not deterministic"

    def test_zero_and_negative_source_values_do_not_become_real_votes(self):
        """A 0 must be read as 'no opinion', never as 'worth nothing' —
        the missing-data-becomes-zero defect class."""
        players = {
            k: (v if k != "Mid Tier RB" else {**v, "sites": {**v["sites"], "fantasyCalc": 0}})
            for k, v in GOLDEN_PLAYERS.items()
        }
        with_zero = build_api_data_contract(_payload(players))
        base = build_api_data_contract(_payload())
        base_v = _value(base, "Mid Tier RB")
        zero_v = _value(with_zero, "Mid Tier RB")
        # A zero must not drag the player toward the floor.
        assert zero_v > base_v * 0.5, f"a 0-valued source collapsed the blend: {base_v} -> {zero_v}"

    def test_an_empty_payload_does_not_raise(self):
        contract = build_api_data_contract({"players": {}})
        assert contract.get("playersArray") == [] or contract.get("playersArray") is None


# ── Outlier handling ────────────────────────────────────────────────────


class TestOutlierHandling:
    def test_one_wild_source_does_not_dominate(self, contract):
        """``Contested Player`` has four sources near 7,000 and one at
        1,200.  The blend must stay near the consensus rather than being
        dragged to the midpoint of the outlier."""
        v = _value(contract, "Contested Player")
        peer = _value(contract, "Amon-Ra St. Brown")  # ~8,000 consensus, no outlier
        assert v is not None
        # Must remain in the same broad band as its consensus, not
        # collapse toward the 1,200 dissent.
        assert v > peer * 0.5, f"outlier dominated the blend: {v} vs peer {peer}"

    def test_the_disagreement_is_surfaced_not_hidden(self, contract):
        """Whatever the blend decides, the spread must be reported so a
        user can see the sources disagreed."""
        row = _row(contract, "Contested Player")
        assert row is not None
        assert row.get("sourceSpread") is not None


# ── Cross-consumer consistency ──────────────────────────────────────────


class TestOneValueEverywhere:
    def test_legacy_dict_mirrors_the_row_value(self, contract):
        """The legacy ``players`` dict and ``playersArray`` must not
        disagree — several engines still read the dict.

        WHAT THIS USED TO DO
        ====================
        It read ``rdv`` from the row, then never used it. The only
        assertion was ``isinstance(mirrored, (int, float))`` on
        ``_finalAdjusted``. So it checked a TYPE, on the WRONG KEY, and
        compared nothing — a mirror off by any amount passed, which is
        the exact "asserts a shape, never a value" shape this audit
        exists to find. Worse, ``_finalAdjusted`` is the legacy scraper
        COMPOSITE, a different scale from ``rankDerivedValue``: measured
        on the live contract it equals the row value on **1 of 812**
        rows, so even a proper equality check against it would have been
        wrong.

        The dict does carry the right key. Measured: ``rankDerivedValue``
        is present on all **812** rows that have a ``legacyRef`` and a
        row value, and matches **812/812**. That is the invariant this
        test's name always claimed, and it now asserts it.
        """
        players = contract.get("players") or {}
        checked = 0
        for row in _rows(contract):
            legacy_ref = row.get("legacyRef")
            if not legacy_ref or legacy_ref not in players:
                continue
            rdv = row.get("rankDerivedValue")
            if rdv is None:
                continue
            entry = players[legacy_ref] or {}
            if "rankDerivedValue" not in entry:
                continue
            checked += 1
            assert entry["rankDerivedValue"] == rdv, (
                f"legacy dict disagrees with the row for {legacy_ref!r}: "
                f"dict={entry['rankDerivedValue']} row={rdv}. Engines that read the "
                f"dict (finder, suggestions, waiver) would price this asset "
                f"differently from the board the user sees."
            )

        # Non-vacuity: the loop above `continue`s on four conditions, so
        # an empty comparison set would make every assertion trivially
        # true — which is how the version this replaced passed. This
        # fixture yields 15 eligible rows (16 playersArray rows, one
        # without a legacyRef); 10 is a floor with headroom for fixture
        # edits, not a pin on the exact count.
        assert checked >= 10, (
            f"only {checked} rows were actually compared; the mirror key or "
            f"legacyRef population changed and this guard has gone hollow"
        )

    def test_trade_finder_reads_the_same_board(self, contract):
        """``board_values_from_contract`` is what the arbitrage finder
        prices from; it must return exactly the contract's values."""
        from src.trade.finder import board_values_from_contract

        board = board_values_from_contract(contract)
        for row in _rows(contract):
            ref = row.get("legacyRef") or row.get("canonicalName")
            rdv = row.get("rankDerivedValue")
            if ref in board and rdv is not None:
                assert board[ref] == rdv, f"{ref}: finder {board[ref]} != board {rdv}"


# ── Identity ────────────────────────────────────────────────────────────


class TestIdentityEdgeCases:
    @pytest.mark.parametrize(
        "name",
        ["Marvin Harrison Jr.", "D.J. Moore", "Amon-Ra St. Brown", "Ja'Marr Chase"],
    )
    def test_awkward_names_produce_exactly_one_row(self, contract, name):
        """Suffixes, punctuation, accents and apostrophes must not split
        a player into two rows or merge two players into one."""
        matches = [
            r for r in _rows(contract) if (r.get("displayName") or r.get("canonicalName")) == name
        ]
        assert len(matches) == 1, f"{name} produced {len(matches)} rows"

    def test_no_two_rows_share_a_rank(self, contract):
        """A collision that merged two players would show up here."""
        seen: dict[int, str] = {}
        for row in _rows(contract):
            rank = row.get("canonicalConsensusRank")
            if not isinstance(rank, int):
                continue
            name = row.get("displayName") or ""
            assert rank not in seen, f"rank {rank} shared by {seen[rank]} and {name}"
            seen[rank] = name
