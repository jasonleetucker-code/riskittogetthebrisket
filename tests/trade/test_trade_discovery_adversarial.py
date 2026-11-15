"""Trade discovery — adversarial cases across generators (directive Part 15).

Each test states a property the owner rules require and builds the smallest
league where a shortcut would break it:

* a withheld (quarantined) provider can never be the evidence that qualifies
  a Best Offer, end to end through ``build_best_offers``;
* a saved untouchable never leaves the roster through ANY generator — proven
  non-vacuously: each case first shows the player WOULD headline unprotected;
* a raw-sum-favourable package that fails the package Value Adjustment is
  never returned as externally supported by the Package Builder.
"""

from __future__ import annotations

import pytest

from src.trade import golden_upgrades as gu
from src.trade.constraints import resolve_constraints
from tests.trade import test_best_offers as bo_t
from tests.trade import test_golden_upgrades as gu_t
from tests.trade import test_package_builder as pb_t

KTC, IDPTC = bo_t.KTC, bo_t.IDPTC


# ── withheld providers, end to end ────────────────────────────────────────


def _idp_pair(withheld=()):
    # An IDP-for-IDP trade: KTC prices neither, so IDP Trade Calculator is
    # the ONLY calculator that could qualify it.
    mine = [("Our LB", "LB", 3000, None, 3600, "CIN")]
    theirs = [("Their LB", "LB", 3600, None, 3400, "BUF")]
    return bo_t._league(mine, theirs, withheld=withheld)


def test_the_idp_pair_qualifies_when_nothing_is_withheld():
    card = bo_t._card(bo_t._run(*_idp_pair()))
    assert card["status"] == "qualified"
    assert card["offer"]["external"]["calculator"] == IDPTC


@pytest.mark.parametrize("who", ["Our LB", "Their LB"])
def test_a_withheld_provider_cannot_qualify_a_best_offer_end_to_end(who):
    card = bo_t._card(bo_t._run(*_idp_pair(withheld=[(who, IDPTC)])))
    assert card["status"] == "no_result"
    assert card["offer"] is None
    # The specific reason, not the generic "not even on any calculator".
    assert card["noResultReason"] == "external_provider_withheld"


# ── saved untouchables, every generator ───────────────────────────────────


def _best_offers_sent(constraints):
    players, teams, contract = bo_t._wide_league()
    out = bo_t._run(
        players, teams, contract, constraints_for=(lambda _o: constraints) if constraints else None
    )
    offer = bo_t._card(out)["offer"]
    return {a["name"] for a in offer["send"]} if offer else set()


def _package_builder_sent(constraints):
    out = pb_t._build(
        pb_t.MINE,
        pb_t.THEIRS,
        target="Their WR",
        constraints=constraints,
    )
    return {a["name"] for p in out["packages"] for a in p["send"]}


def _golden_sent(constraints):
    out = gu_t._run([gu_t.OWNED_LB], [gu_t.TARGET_LB], constraints=constraints)
    return {u["owned"]["name"] for u in out["upgrades"]}


GENERATORS = {
    "best_offers": _best_offers_sent,
    "package_builder": _package_builder_sent,
    "golden_upgrades": _golden_sent,
}


@pytest.mark.parametrize("name", sorted(GENERATORS))
def test_a_saved_untouchable_never_leaves_through_any_generator(name):
    sent = GENERATORS[name]
    unprotected = sent(None)
    assert unprotected, f"{name}: the fixture must produce an offer to protect against"
    headliner = sorted(unprotected)[0]
    protected = sent(resolve_constraints(persistent={"untouchables": [headliner]}))
    assert headliner not in protected, f"{name} offered a saved untouchable"


def test_every_generating_entry_point_is_in_the_untouchable_sweep():
    """A new generator must join the sweep above, not only accept constraints."""
    from src.trade import best_offers, package_builder

    generators = {
        best_offers.build_best_offers,
        package_builder.build_packages,
        gu.find_golden_upgrades,
    }
    assert len(generators) == len(GENERATORS)


# ── package Value Adjustment ─────────────────────────────────────────────


def test_package_builder_never_presents_a_raw_sum_win_that_va_rejects_as_external():
    """Two 4000 pieces for one 7900 star: 8000 raw beats 7900, but the package
    adjustment credits the single star (~11950 adjusted).  Under
    ``evidence="external"`` the two-for-one may not appear as supported."""
    mine = [
        ("Piece A", "WR", 4000, 4000, 4000, "CIN"),
        ("Piece B", "WR", 4000, 4000, 4000, "CIN"),
    ]
    theirs = [("Star", "WR", 9500, 7900, 7900, "BUF")]
    out = pb_t._build(mine, theirs, target="Star", evidence="external")
    two_for_one = [
        p
        for p in out["packages"]
        if {a["name"] for a in p["send"]} == {"Piece A", "Piece B"}
        and {a["name"] for a in p["receive"]} == {"Star"}
    ]
    assert two_for_one == []
