"""One position vocabulary across the roster chain (F4).

Integration's non-blocking finding 8: ``core._member`` groups players
with ``lineup.lineup_position`` while ``weakness.build_position_ranks``
and ``age_portfolio.build_youth_curve`` used
``replacement.normalize_base_position``.  Two vocabularies that agree on
almost everything, which is what makes the disagreement dangerous:

    token   lineup_position   normalize_base_position
    MLB     MLB               LB
    P       K                 P
    PK      K                 PK

An MLB-listed player would therefore be ranked inside the LB population
while his core position said ``MLB`` — a group that generates no reserve
demand and so no rungs.  Ranked against linebackers, reported as
nothing.

Zero of 660 rostered players and zero of 1,108 board rows carry any of
the three today, so this is latent rather than firing — the same class
as the ``ownerId`` collision, and worth closing for the same reason.
"""

from __future__ import annotations

import ast
import pathlib

from src.league_intel.replacement import normalize_base_position
from src.roster_intel.age_portfolio import build_youth_curve
from src.roster_intel.core import build_meaningful_core
from src.roster_intel.weakness import build_position_ranks
from src.ros.lineup import (
    RosterPlayer,
    lineup_position,
    player_eligible_for_slot,
    slot_eligible_positions,
)

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Every position token either vocabulary has ever been handed, plus the
#: shapes that break naive normalisers.
_TOKENS = [
    "QB", "RB", "WR", "TE", "K", "PK", "P", "DEF",
    "DL", "DE", "DT", "EDGE", "NT",
    "LB", "OLB", "ILB", "MLB",
    "DB", "CB", "S", "FS", "SS",
    "", "  ", "junk", "dl", "Edge",
]  # fmt: skip


def P(pid, pos, val):
    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=val)


# ══ The chain speaks ONE vocabulary ════════════════════════════════


def test_the_roster_chain_groups_every_token_the_same_way_everywhere():
    """RED before the fix. Two players whose tokens resolve to the SAME
    lineup family must land in the same ranked group — rank 1 and rank 2,
    not two competing rank 1s — and the same must hold for the youth
    curve, because the core groups them together and a player ranked in
    one group but reported in another is invisible.

    Asserted behaviourally rather than by reading internals: a shared
    group is exactly what "ranks 1 and 2" means.
    """
    same_family = [("MLB", "LB"), ("OLB", "ILB"), ("NT", "DE"), ("FS", "SS"), ("PK", "K")]
    for a_token, b_token in same_family:
        assert lineup_position(a_token) == lineup_position(b_token), (a_token, b_token)
        ranks = build_position_ranks([("a", a_token, 900.0), ("b", b_token, 100.0)], population="t")
        assert (ranks.rank_of("a"), ranks.rank_of("b")) == (1, 2), (a_token, b_token)

        youth = build_youth_curve([(a_token, 22.0), (b_token, 30.0)])
        assert set(youth.by_position) == {lineup_position(a_token)}, (a_token, b_token)


def test_tokens_from_different_families_are_never_pooled():
    """The other direction — a widened vocabulary must not collapse
    groups that are genuinely different."""
    for a_token, b_token in [("LB", "DL"), ("DB", "LB"), ("RB", "WR"), ("QB", "TE")]:
        assert lineup_position(a_token) != lineup_position(b_token)
        ranks = build_position_ranks([("a", a_token, 900.0), ("b", b_token, 100.0)], population="t")
        assert (ranks.rank_of("a"), ranks.rank_of("b")) == (1, 1), (a_token, b_token)


#: The C2 canonical chain. Deliberately NOT every module in the package:
#: ``marginal`` / ``profiles`` / ``targets`` are the older WS-J roster
#: engine behind ``/api/gameplan``, they group for REPLACEMENT-LEVEL
#: purposes, and re-grouping them would move a different owner's live
#: numbers. Named here so the boundary is a decision rather than an
#: oversight — the lane doc records it as a follow-up for that surface.
_C2_CHAIN = (
    "core.py",
    "strength.py",
    "weakness.py",
    "age_portfolio.py",
    "simulation.py",
    "droppability.py",
    "exposure.py",
)


def test_no_c2_chain_module_still_groups_by_the_replacement_vocabulary():
    """Structural. ``normalize_base_position`` is the REPLACEMENT owner's
    grouping and stays canonical for replacement level (lane doc §3); it
    is simply not the vocabulary that decides slots and core membership,
    so the chain must not group by it."""
    offenders = {}
    for name in _C2_CHAIN:
        path = REPO / "src/roster_intel" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and "replacement" in (node.module or ""):
                names = [a.name for a in node.names if a.name == "normalize_base_position"]
                if names:
                    offenders[name] = names
    assert offenders == {}, offenders


def test_an_mlb_is_ranked_and_reported_as_a_linebacker():
    """The concrete consequence, end to end: an MLB must reach the LB
    rung ladder rather than a group of his own."""
    pool = [P("MLB1", "MLB", 900), P("LB1", "LB", 800)]
    core = build_meaningful_core(pool, ["LB", "LB"], config={"reserveMultiplier": 1.0})
    positions = {m.player_id: m.position for m in core.members}
    assert positions["MLB1"] == "LB"

    ranks = build_position_ranks([("MLB1", "MLB", 900.0), ("LB1", "LB", 800.0)], population="t")
    # Ranked 1 and 2 means one shared LB population; two rank-1s
    # would mean the MLB got a group of his own, which generates
    # no reserve demand and therefore no rungs.
    assert (ranks.rank_of("MLB1"), ranks.rank_of("LB1")) == (1, 2)


# ══ Nothing else changes eligibility ═══════════════════════════════


def test_only_mlb_changed_and_every_other_token_resolves_exactly_as_before():
    """The proof the brief asks for. ``lineup_position`` is what decides
    which slots a player is legal in, so a change to its family table is
    an eligibility change — and exactly one token was intended to move.

    The pre-fix answers are frozen here literally rather than recomputed,
    so a future edit to the table cannot quietly move a second one.
    """
    frozen_pre_fix = {
        "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE",
        "K": "K", "PK": "K", "P": "K", "DEF": "DEF",
        "DL": "DL", "DE": "DL", "DT": "DL", "EDGE": "DL", "NT": "DL",
        "LB": "LB", "OLB": "LB", "ILB": "LB",
        "MLB": "MLB",          # <- the only intended change, to "LB"
        "DB": "DB", "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB",
        "": "", "  ": "", "junk": "JUNK", "dl": "DL", "Edge": "DL",
    }  # fmt: skip
    changed = {
        token: (before, lineup_position(token))
        for token, before in frozen_pre_fix.items()
        if lineup_position(token) != before
    }
    assert changed == {"MLB": ("MLB", "LB")}, changed


def test_hybrid_and_idp_family_eligibility_is_untouched():
    """DL/EDGE/LB/DB families and hybrid ``fantasy_positions`` must keep
    working exactly as they did — the property C2-U1 measured at 10/10
    against Sleeper's own awarded lineups."""
    for slot, expected in (
        ("DL", {"DL", "DE", "DT", "EDGE"}),
        ("LB", {"LB"}),
        ("DB", {"DB", "S", "CB"}),
        ("FLEX", {"RB", "WR", "TE"}),
        ("SUPER_FLEX", {"QB", "RB", "WR", "TE"}),
    ):
        assert set(slot_eligible_positions(slot)) == expected, slot

    hybrid = RosterPlayer("h", "H", "DL", 10.0, fantasy_positions=("DL", "LB"))
    assert player_eligible_for_slot("DL", hybrid)
    assert player_eligible_for_slot("LB", hybrid)
    assert player_eligible_for_slot("IDP_FLEX", hybrid)
    assert not player_eligible_for_slot("WR", hybrid)


def test_an_mlb_can_now_actually_fill_the_slots_he_is_legal_for():
    """The defect this closes is not cosmetic: before, an MLB resolved to
    a family matching NO slot, so a real linebacker could not start."""
    mlb = RosterPlayer("m", "M", "MLB", 10.0)
    assert player_eligible_for_slot("LB", mlb)
    assert player_eligible_for_slot("IDP_FLEX", mlb)
    assert not player_eligible_for_slot("DL", mlb)
    assert not player_eligible_for_slot("QB", mlb)


def test_the_replacement_owner_keeps_its_own_vocabulary():
    """Not collapsed into one another. They answer different questions and
    the lane doc's §3 boundary table says so; this unit stops the roster
    chain GROUPING by the wrong one, it does not retire either."""
    assert normalize_base_position("MLB") == "LB"
    assert normalize_base_position("P") == "P"
    assert normalize_base_position("PK") == "PK"


def test_the_eligibility_widening_is_exactly_the_scraper_spellings():
    """The proof the brief asks for, stated as a frozen delta.

    Eligibility is now decided on the raw token OR its resolved family,
    because those are two spellings of one fact. That is strictly a
    widening — an ``or`` cannot make an eligible player ineligible — and
    what it adds is exactly the six roster spellings that previously
    resolved to a correct family and then matched no slot at all.

    Frozen literally, so a later change to either table has to come back
    here and say what else it moved.
    """
    from src.ros.lineup import _eligible_for_slot

    tokens = [
        "QB", "RB", "WR", "TE", "K", "PK", "P", "DEF",
        "DL", "DE", "DT", "EDGE", "NT",
        "LB", "OLB", "ILB", "MLB",
        "DB", "CB", "S", "FS", "SS",
    ]  # fmt: skip
    slots = ["QB", "RB", "WR", "TE", "K", "DL", "LB", "DB", "FLEX", "SUPER_FLEX", "IDP_FLEX"]

    gained, lost = set(), set()
    for token in tokens:
        for slot in slots:
            raw_match = token in slot_eligible_positions(slot)
            now = _eligible_for_slot(slot, token)
            if now and not raw_match:
                gained.add((token, slot))
            if raw_match and not now:
                lost.add((token, slot))

    assert lost == set(), lost
    assert gained == {
        ("PK", "K"), ("P", "K"),
        ("NT", "DL"), ("NT", "IDP_FLEX"),
        ("OLB", "LB"), ("OLB", "IDP_FLEX"),
        ("ILB", "LB"), ("ILB", "IDP_FLEX"),
        ("MLB", "LB"), ("MLB", "IDP_FLEX"),
        ("FS", "DB"), ("FS", "IDP_FLEX"),
        ("SS", "DB"), ("SS", "IDP_FLEX"),
    }, gained  # fmt: skip


def test_a_player_with_an_empty_position_is_eligible_for_nothing():
    """Missing is not "fits anywhere". The widening must not turn an
    unknown position into a wildcard."""
    from src.ros.lineup import _eligible_for_slot

    for slot in ("QB", "FLEX", "IDP_FLEX", "SUPER_FLEX"):
        assert not _eligible_for_slot(slot, "")
        assert not _eligible_for_slot(slot, "   ")
    assert not player_eligible_for_slot("FLEX", P("x", "", 10.0))
