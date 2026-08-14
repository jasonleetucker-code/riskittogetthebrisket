"""One vote per provider family — B10-T3b.

WHAT CHANGED
────────────
B10-T2 declared which sources share a provider. It changed no value:
the blend still counted every source key as an independent opinion. This
is the unit that acts on the declaration.

After Hampel and before the blend, each correlation group is collapsed to
**one** value: the one published by its highest-precedence member present
on that row. A SELECTION, never an average.

WHY SELECTION, NOT AVERAGING
─────────────────────────────
A correlation group is a binary assertion — *these are not independent
votes*. Averaging a family's members quietly re-admits the derived one at
50%, which for ``fantasyProsFitzmaurice`` inside the ``fantasyProsSf``
consensus panel is precisely the nested-consensus prohibition, and for
``fantasyNavigatorSf`` inside ``ktc`` re-admits a republication of the
board's own anchor at half weight. It also manufactures a number no
source published.

Part of the intra-family spread is our own encoding artifact rather than
two opinions: ``ktcSfTep`` votes value-direct (``raw / site_max × 9999``)
while ``fantasyNavigatorSf`` votes rank → percentile → Hill.

If a family member genuinely carries independent signal, the repair is to
UNDECLARE the group — not to half-count it.

PRECEDENCE IS DECLARED, NOT INVENTED
─────────────────────────────────────
It is registry order, which already encodes the right heads: the board
before its republisher (``ktcSfTep`` → ``fantasyNavigatorSf``), the
consensus panel before the expert inside it (``fantasyProsSf`` →
``fantasyProsFitzmaurice``), and every vendor's main board before its
rookie-specialty board.

MEASURED on the pinned 2026-08-14 payload
──────────────────────────────────────────
455 values moved · p50 0.9% · p90 2.7% · max 14.8%
top-100 membership churn ZERO; top-200 three in, three out
direction 258 up / 197 down (balanced — no systematic re-pricing)
offense 375/406 moved, picks 66/103, IDP only 14/298 (max 0.9%)
priced count unchanged at 812, so the five newly-unpriced rows are a
swap at the rank-800 boundary rather than a loss.
"""

from __future__ import annotations

from src.api.data_contract import (
    _RANKING_SOURCES,
    _source_precedence,
    collapse_to_independent_families,
    correlation_group_for,
)


class TestOneVotePerFamily:
    def test_a_family_contributes_exactly_one_value(self):
        pairs = [
            ("ktcSfTep", 9000.0, True),
            ("fantasyNavigatorSf", 7000.0, False),
            ("fantasyCalc", 8000.0, False),
        ]
        kept, superseded = collapse_to_independent_families(pairs)

        assert [k for k, _v, _a in kept] == ["ktcSfTep", "fantasyCalc"]
        assert superseded == {"fantasyNavigatorSf": "ktcSfTep"}

    def test_the_head_keeps_its_own_published_value(self):
        """Not the mean of 9000 and 7000 — a number nobody published."""
        kept, _ = collapse_to_independent_families(
            [("ktcSfTep", 9000.0, True), ("fantasyNavigatorSf", 7000.0, False)]
        )
        assert [v for _k, v, _a in kept] == [9000.0]

    def test_the_nested_expert_does_not_outvote_its_panel(self):
        """The owner ruling, as arithmetic.

        An expert inside a consensus panel does not get a second vote,
        and does not get half of one either.
        """
        kept, superseded = collapse_to_independent_families(
            [
                ("fantasyProsSf", 6000.0, False),
                ("fantasyProsFitzmaurice", 4000.0, False),
            ]
        )
        assert [v for _k, v, _a in kept] == [6000.0]
        assert superseded == {"fantasyProsFitzmaurice": "fantasyProsSf"}

    def test_precedence_only_ranks_members_present_on_the_row(self):
        """An IDP row where the vendor's offense board is out of scope is
        decided by the board that actually covered the player."""
        kept, superseded = collapse_to_independent_families(
            [("dlfIdp", 5000.0, False), ("dlfRookieIdp", 4000.0, False)]
        )
        assert [k for k, _v, _a in kept] == ["dlfIdp"]
        assert superseded == {"dlfRookieIdp": "dlfIdp"}

    def test_a_main_board_outranks_the_same_vendors_rookie_board(self):
        """Once a rookie is promoted onto the main board, the rookie
        board is a pre-draft artifact, not the vendor's current view."""
        kept, _ = collapse_to_independent_families(
            [("dlfRookieSf", 4000.0, False), ("dlfSf", 5000.0, False)]
        )
        assert [k for k, _v, _a in kept] == ["dlfSf"]

    def test_independent_sources_are_untouched(self):
        pairs = [
            ("fantasyCalc", 8000.0, False),
            ("otcffbSf", 7500.0, False),
            ("yahooBoone", 7200.0, False),
        ]
        kept, superseded = collapse_to_independent_families(pairs)
        assert kept == pairs
        assert superseded == {}

    def test_the_anchor_flag_travels_with_the_surviving_member(self):
        """The family casts one vote, into whichever partition its own
        member belongs to — the flag is not inherited from a loser."""
        kept, _ = collapse_to_independent_families(
            [("draftSharks", 5000.0, True), ("draftSharksIdp", 4000.0, False)]
        )
        assert kept == [("draftSharks", 5000.0, True)]

    def test_ordering_is_preserved(self):
        """Only membership changes. The blend's count-aware ladder picks
        rungs by index, so a reordering here would be a silent second
        change riding along with this one."""
        pairs = [
            ("fantasyCalc", 8000.0, False),
            ("ktcSfTep", 9000.0, True),
            ("fantasyNavigatorSf", 7000.0, False),
            ("otcffbSf", 7500.0, False),
        ]
        kept, _ = collapse_to_independent_families(pairs)
        assert [k for k, _v, _a in kept] == ["fantasyCalc", "ktcSfTep", "otcffbSf"]

    def test_an_empty_row_collapses_to_nothing(self):
        assert collapse_to_independent_families([]) == ([], {})


class TestPrecedenceIsDeclaredByTheRegistry:
    """No second list to drift.

    If a future edit reorders the registry so a republisher precedes the
    board it republishes, that is a real change in which opinion the
    board hears — and it fails here rather than shipping quietly.
    """

    HEADS = {
        "ktc": "ktcSfTep",
        "fantasyPros": "fantasyProsSf",
        "dlf": "dlfSf",
        "flockFantasy": "flockFantasySf",
        "draftSharks": "draftSharks",
    }

    def test_each_declared_family_has_the_intended_head(self):
        for group, expected in self.HEADS.items():
            members = [
                str(s.get("key"))
                for s in _RANKING_SOURCES
                if correlation_group_for(str(s.get("key"))) == group
            ]
            assert members, f"{group} has no members"
            head = min(members, key=_source_precedence)
            assert head == expected, f"{group} head is {head}, expected {expected}"

    def test_precedence_is_total_over_the_registry(self):
        keys = [str(s.get("key")) for s in _RANKING_SOURCES]
        ranks = [_source_precedence(k) for k in keys]
        assert len(set(ranks)) == len(keys), "two sources share a precedence"

    def test_an_unregistered_key_sorts_last_rather_than_raising(self):
        """A retired source naming itself in cached data must not win a
        family by accident, and must not crash a board build."""
        assert _source_precedence("retiredSource") == len(_RANKING_SOURCES)
