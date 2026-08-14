"""Canonical dynasty value has ONE definition, and nothing device-local
may redefine it.

THE INVARIANT
-------------
The same asset, against the same canonical board snapshot, resolves to the
same canonical dynasty value on every surface — desktop, mobile, tablet,
PWA, narrow viewport, authenticated or public. A device-local preference
may choose which *lens* is displayed. It may not change what the canonical
value IS.

CLAUDE.md already states the governing rule, and states it as an
architectural requirement rather than a preference:

    Canonical player value has one owner, and every downstream engine and
    surface consumes that canonical value — unless it is deliberately
    showing an explicitly named alternate concept, in which case the name
    travels with the number.

    Serving a different quantity under the canonical field name is a
    defect, not an alternate opinion.

WHAT IS CANONICAL, AND WHY
--------------------------
``rankDerivedValue``, as produced by
``src/api/data_contract.py::_compute_unified_rankings`` — which CLAUDE.md
names "the one and only code path that determines live player values
(Final Framework)". That is the market-consensus board.

The league-adjusted number is ``canonical × positional-scarcity factor``,
where scarcity is measured from ONE league's rosters. It is:

  - a per-league quantity, while the canonical board is scoping-profile
    scoped and shared across leagues;
  - explicitly a toggle and NOT the default (``useSettings.js``: "Starts
    'market' on every device and is never auto-flipped");
  - measured as no improvement — ``docs/adjusted-board-backtest.md``
    ranks it against realized 2025 scoring over 572 players, and four
    framings all return "no difference detected" with three of four
    leaning negative.

So the adjusted number is a contextual analytic derived FROM canonical
value. It is not a second canonical value, and it is not more canonical
than the board it is computed from.

THE DEFECT THESE TESTS PIN
--------------------------
Both overlay appliers write the contextual number into the CANONICAL
FIELD NAME, destroying the canonical value in place:

    src/league_intel/overlay.py:92
        copy["rankDerivedValue"] = int(round(float(base) * float(factor)))

    frontend/lib/dynasty-data.js:1953, :1989
        next.rankDerivedValue = scale(row.rankDerivedValue, f);

After either runs, no consumer can recover the canonical value: it has
been overwritten, and no field carries it. Combined with ``valuationMode``
living in ``next_settings_v2`` in **localStorage only, never
server-synced**, that means one user on two devices gets two different
numbers under one field name, differing by up to ±25% — with nothing in
the payload naming which is which.

These tests are RED against that behaviour, by design. They describe the
contract the repair must satisfy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.league_intel import overlay

REPO = Path(__file__).resolve().parents[2]

#: The canonical field. Named once here so a rename has to come through
#: this test rather than around it.
CANONICAL_FIELD = "rankDerivedValue"


#: A board snapshot, deliberately spanning the shapes the overlay has to
#: survive: a QB the scarcity factor lifts, a WR it cuts, a row with no
#: factor at all, and a pick (``compute_scarcity`` has no PICK key, so
#: picks must come through untouched).
def _board() -> list[dict]:
    return [
        {
            "displayName": "Josh Allen",
            "canonicalName": "josh allen",
            "position": "QB",
            "assetClass": "offense",
            CANONICAL_FIELD: 9991,
            "values": {"overall": 9991, "finalAdjusted": 9991, "displayValue": 9991},
            "canonicalConsensusRank": 1,
        },
        {
            "displayName": "Puka Nacua",
            "canonicalName": "puka nacua",
            "position": "WR",
            "assetClass": "offense",
            CANONICAL_FIELD: 6000,
            "values": {"overall": 6000, "finalAdjusted": 6000, "displayValue": 6000},
            "canonicalConsensusRank": 12,
        },
        {
            "displayName": "Unfactored Player",
            "canonicalName": "unfactored player",
            "position": "TE",
            "assetClass": "offense",
            CANONICAL_FIELD: 3000,
            "values": {"overall": 3000, "finalAdjusted": 3000, "displayValue": 3000},
            "canonicalConsensusRank": 90,
        },
        {
            "displayName": "2027 Round 1",
            "canonicalName": "2027 round 1",
            "position": "PICK",
            "assetClass": "pick",
            CANONICAL_FIELD: 4200,
            "values": {"overall": 4200, "finalAdjusted": 4200, "displayValue": 4200},
            "canonicalConsensusRank": 40,
        },
    ]


#: Factors as the live overlay produces them — keyed by
#: ``row_factor_key``, sparse (absence means "unchanged").
def _factors(rows) -> dict[str, float]:
    # Keyed through ``row_factor_key`` rather than by a literal, because
    # that function is required to stay identical to
    # ``publish._row_key`` and a fixture spelling the key by hand would
    # keep passing after the two diverged — the exact silent failure its
    # own docstring warns about.
    by_canonical = {r["canonicalName"]: r for r in rows}
    wanted = {"josh allen": 1.25, "puka nacua": 0.80}
    factors = {overlay.row_factor_key(by_canonical[n]): f for n, f in wanted.items()}
    assert all(factors), "row_factor_key returned an empty key — fixture would be inert"
    return factors


def _apply():
    rows = _board()
    out = overlay.adjusted_rows(rows, _factors(rows))
    assert out is not None, "the overlay declined to apply — fixture no longer exercises it"
    return rows, {r.get("displayName"): r for r in out}


class TestInvariantA_CanonicalValueIsStable:
    """A — the canonical value does not depend on a display preference.

    The whole point. A user who flips "Market" / "My league" — or who
    simply opens the site on a second device where the localStorage
    default still says "market" — must not thereby change what the
    player's canonical dynasty value IS.
    """

    def test_the_canonical_value_survives_the_lens(self):
        rows, adjusted = _apply()
        before = {r["displayName"]: r[CANONICAL_FIELD] for r in rows}
        for name, canonical in before.items():
            row = adjusted[name]
            assert row.get(CANONICAL_FIELD) == canonical, (
                f"{name}: the league-adjusted lens overwrote {CANONICAL_FIELD} "
                f"({canonical} → {row.get(CANONICAL_FIELD)}). A contextual "
                "adjustment may not impersonate the canonical value — after "
                "this, no consumer can recover what the player is actually "
                "worth, and two devices with different localStorage disagree "
                "under one field name."
            )

    def test_the_source_rows_are_never_mutated(self):
        """``latest_contract_data`` is a shared module global."""
        rows = _board()
        overlay.adjusted_rows(rows, _factors(rows))
        assert rows[0][CANONICAL_FIELD] == 9991, (
            "the overlay mutated the caller's rows; one in-place multiply "
            "reprices the market board for every other request"
        )


class TestInvariantB_ContextualAdjustmentIsHonest:
    """B — if the adjusted number differs from canonical, it is a
    DISTINCT, explicitly-named concept that no consumer can mistake for
    canonical."""

    def test_the_adjusted_number_has_its_own_field(self):
        _, adjusted = _apply()
        allen = adjusted["Josh Allen"]
        candidates = [k for k in allen if "adjust" in k.lower() and "value" in k.lower()]
        assert candidates, (
            "the adjusted value has no field of its own — it exists only by "
            "having overwritten "
            f"{CANONICAL_FIELD}. The name must travel with the number, so a "
            "consumer can tell which semantic it is holding."
        )

    def test_the_adjusted_number_is_actually_the_adjustment(self):
        _, adjusted = _apply()
        allen = adjusted["Josh Allen"]
        field = next(
            (k for k in allen if "adjust" in k.lower() and "value" in k.lower()),
            None,
        )
        if field is None:
            pytest.skip("no adjusted field yet — covered by the test above")
        assert allen[field] == round(9991 * 1.25), (
            f"{field} does not carry canonical × factor; the lens is not "
            "computing what it claims to"
        )

    def test_every_value_alias_agrees_on_the_semantic(self):
        """``values.overall`` / ``finalAdjusted`` / ``displayValue`` are
        aliases of the canonical value. Scaling those while leaving the
        canonical field — or vice versa — publishes a row that disagrees
        with itself."""
        _, adjusted = _apply()
        for name, row in adjusted.items():
            values = row.get("values") or {}
            for alias in ("overall", "finalAdjusted", "displayValue"):
                if alias not in values:
                    continue
                assert values[alias] == row.get(CANONICAL_FIELD), (
                    f"{name}: values.{alias}={values[alias]} disagrees with "
                    f"{CANONICAL_FIELD}={row.get(CANONICAL_FIELD)} — one of "
                    "them is the lens and the other is canonical, under names "
                    "that claim to be the same number"
                )


class TestInvariantC_NoSilentFallback:
    """C — missing canonical data must not silently resolve to some other
    quantity presented as canonical."""

    def test_a_row_with_no_factor_is_untouched(self):
        rows, adjusted = _apply()
        row = adjusted["Unfactored Player"]
        assert row.get(CANONICAL_FIELD) == 3000, (
            "a row the lens has no factor for was altered anyway; absence of "
            "a factor means UNCHANGED, not zero and not a substitute"
        )

    def test_picks_are_not_repriced_by_a_player_scarcity_lens(self):
        """``compute_scarcity`` has no PICK key, so the lens is a no-op
        for picks. If a pick moves, the lens is applying a factor derived
        from a population it does not belong to."""
        _, adjusted = _apply()
        assert adjusted["2027 Round 1"].get(CANONICAL_FIELD) == 4200

    def test_a_missing_canonical_value_is_not_invented(self):
        rows = [
            {
                "displayName": "Unpriced Guy",
                "canonicalName": "unpriced guy",
                "position": "WR",
                "assetClass": "offense",
                CANONICAL_FIELD: None,
                "values": {},
            }
        ]
        out = overlay.adjusted_rows(rows, {overlay.row_factor_key(rows[0]): 1.25})
        if out is None:
            return  # declined to apply at all — also correct
        assert out[0].get(CANONICAL_FIELD) is None, (
            "an unpriced row acquired a value from the lens; missing is never "
            "zero and never a derived stand-in"
        )


class TestInvariantD_ResponsiveEqualityOfTransport:
    """D — mobile and desktop take different transports and must receive
    identical canonical valuation semantics.

    ``frontend/lib/device-profile.js::preferredDataView`` routes viewport
    <768px (or ``deviceMemory <= 4``, or a 2G/3G connection) to
    ``/api/data?view=compact`` and everything else to ``view=array``.
    That is a genuine device-conditional data path, and it is exactly the
    kind of optimization that quietly acquires semantics.

    Transport optimization may remove fields the surface does not render.
    It may not reprice anybody.
    """

    CAPTURE = REPO / "docs/master-site-audit/evidence/W06/contract-full.json"

    def _contract(self):
        if not self.CAPTURE.exists():
            pytest.skip("no full-contract capture in this environment")
        return json.loads(self.CAPTURE.read_text(encoding="utf-8"))

    def test_compact_and_array_price_every_player_identically(self):
        from src.api.compact_view import compact_contract

        full = self._contract()
        # ``array`` is the full contract minus the legacy dict
        # (server.py:2325-2326) — player rows are the same objects.
        array_rows = {r.get("displayName"): r for r in full.get("playersArray") or []}
        compact_rows = {
            r.get("displayName"): r for r in compact_contract(full).get("playersArray") or []
        }
        assert len(array_rows) > 500, f"fixture too small to be meaningful ({len(array_rows)})"
        assert array_rows.keys() == compact_rows.keys(), (
            "the compact view dropped or added players; it is a field-pruning "
            "transform, not a row filter"
        )

        mismatched = [
            (name, row.get(CANONICAL_FIELD), compact_rows[name].get(CANONICAL_FIELD))
            for name, row in array_rows.items()
            if row.get(CANONICAL_FIELD) != compact_rows[name].get(CANONICAL_FIELD)
        ]
        assert not mismatched, (
            "the mobile transport reprices players relative to desktop:\n"
            + "\n".join(f"  {n}: array={a} compact={c}" for n, a, c in mismatched[:10])
        )

    def test_compact_and_array_agree_on_every_value_alias(self):
        from src.api.compact_view import compact_contract

        full = self._contract()
        compact_rows = {
            r.get("displayName"): r for r in compact_contract(full).get("playersArray") or []
        }
        mismatched = []
        for row in full.get("playersArray") or []:
            name = row.get("displayName")
            if (row.get("values") or {}) != (compact_rows.get(name, {}).get("values") or {}):
                mismatched.append(name)
        assert not mismatched, (
            f"{len(mismatched)} players have different values.* between the "
            f"mobile and desktop transports, e.g. {mismatched[:5]}"
        )

    def test_the_legacy_dict_and_the_array_agree(self):
        """Two parallel encodings of one board ship in the same payload.

        ``buildRows`` prefers ``playersArray`` but falls back to the
        legacy ``players`` dict when it is empty, and
        ``mergeRankingsDelta`` can synthesize from either. If the two
        disagree, which one a client reads becomes a valuation decision.
        """
        full = self._contract()
        array_rows = {r.get("displayName"): r for r in full.get("playersArray") or []}
        legacy = full.get("players") or {}
        if not legacy:
            pytest.skip("capture carries no legacy dict")
        mismatched = [
            (name, row.get(CANONICAL_FIELD), array_rows[name].get(CANONICAL_FIELD))
            for name, row in legacy.items()
            if name in array_rows
            and row.get(CANONICAL_FIELD) != array_rows[name].get(CANONICAL_FIELD)
        ]
        assert not mismatched, (
            "the legacy dict and playersArray disagree on the canonical "
            f"value for {len(mismatched)} players, e.g. {mismatched[:5]}"
        )


class TestDeviceLocalStateCannotSelectAMethodology:
    """The original defect, stated as the contract that replaced it.

    ``valuationMode`` lived in ``next_settings_v2`` in localStorage,
    never server-synced, and the lens it selected overwrote
    ``rankDerivedValue`` — so one account on two devices rendered two
    numbers for one player under one field name.

    The repair is not "sync the setting". It is that there is only one
    methodology, so nothing device-local has a methodology to select. The
    setting is read and IGNORED rather than removed, which is what makes
    an old phone converge with no migration step.
    """

    def test_the_client_no_longer_reads_a_stored_valuation_mode(self):
        src = (REPO / "frontend/lib/valuation-mode.js").read_text(encoding="utf-8")
        body = src.split("export function readValuationMode()", 1)[-1].split("\n}", 1)[0]
        assert "localStorage" not in body, (
            "readValuationMode still reads localStorage — a device-local value "
            "can again decide which methodology a user sees"
        )
        assert "LEAGUE_ADJUSTED" not in body, (
            "readValuationMode can still answer leagueAdjusted; under the "
            "current ruling there is one canonical methodology"
        )

    def test_there_is_no_user_facing_valuation_basis_control(self):
        """A control that selects a methodology is how one player got two
        values. Removed, not disabled — a greyed-out control implies the
        choice still exists."""
        page = (REPO / "frontend/app/rankings/page.jsx").read_text(encoding="utf-8")
        assert (
            'label="Value basis"' not in page
        ), "the Market / My league selector is still rendered on /rankings"
        assert (
            '{ value: "leagueAdjusted"' not in page
        ), "the rankings page still offers leagueAdjusted as a choice"

    def test_the_engine_gate_never_serves_the_withdrawn_lens(self):
        """``_valuation_scoped_contract`` is the single place the lens
        ever reached an engine, so it is the single place it is closed.
        A stored ``leagueAdjusted`` is ignored, not refused."""
        src = (REPO / "server.py").read_text(encoding="utf-8")
        fn = src.split("async def _valuation_scoped_contract", 1)[-1].split("\ndef ", 1)[0]
        assert (
            "adjusted_contract" not in fn
        ), "the engine gate still applies the league-adjusted overlay"
        assert (
            '"leagueAdjusted"' not in fn.split("requested ==", 1)[-1].split("return", 1)[-1]
        ), "the engine gate can still answer with the leagueAdjusted mode"


class TestTheExperimentalLensIsIsolated:
    """It may exist. It may not own a canonical field."""

    def test_the_overlay_writes_only_experimental_field_names(self):
        _, adjusted = _apply()
        allen = adjusted["Josh Allen"]
        assert allen[overlay.EXPERIMENTAL_VALUE_FIELD] == round(9991 * 1.25)
        assert allen[CANONICAL_FIELD] == 9991
        for banned in overlay.CANONICAL_VALUE_FIELDS:
            if banned == CANONICAL_FIELD:
                continue
            values = allen.get("values") or {}
            if banned in values:
                assert values[banned] == 9991, (
                    f"values.{banned} moved with the experimental lens; the "
                    "canonical aliases must agree with the canonical value"
                )

    def test_the_experimental_field_name_cannot_be_mistaken_for_canonical(self):
        for name in (
            overlay.EXPERIMENTAL_VALUE_FIELD,
            overlay.EXPERIMENTAL_RANK_FIELD,
            overlay.EXPERIMENTAL_TIER_FIELD,
        ):
            assert name.startswith("experimental"), (
                f"{name} does not announce itself as experimental, so a "
                "consumer could read it as canonical"
            )
