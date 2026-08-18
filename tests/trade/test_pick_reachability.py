"""The arbitrage finder cannot currently trade a draft pick, and that is recorded.

Measured on the 2026-08-18 board across all twelve ``dynasty_main`` rosters:
**480 returned trades, 0 containing a pick**, shapes only ``(1,1)`` and
``(1,2)``.  Not because picks were rejected on merit — because they were never
candidates.  Two independent breaks, either of which alone is sufficient:

1. ``_resolve_roster`` reads ``team["players"]`` and never ``team["picks"]``,
   so no team's asset list can contain one.
2. The label grammars differ.  Rosters carry ``"2026 1.06 (own)"`` with
   ``baseLabel`` ``"2026 1.06"``; the priced pool carries ``"2026 Pick 1.06"``.
   Measured: **0 of 157** distinct roster pick labels match a pool key
   verbatim, and **3 of 90** baseLabels do.

Meanwhile the pool *does* carry **26 priced picks** with real market values and
ranks (``2026 Pick 1.01`` at 6,662, market rank 27), and 288 picks are owned
across the twelve rosters.  ``CLAUDE.md`` documents the finder's market gate as
``ktcSfTep`` for "offense **and picks**", so this is a gap between the
documented design and the live path, not an intended exclusion.

**Why this is pinned rather than fixed here.**  Making the finder emit
pick-bearing packages is a product change, not a defect repair: the manifest's
``C7-PICKGEN-01`` (posture-aware pick generation) owns *when* a pick belongs in
a package — "never generic equalizer filler, never inserted cosmetically, never
to make raw totals line up" — and it is P6, explicitly deferred.  Wiring picks
in first would ship exactly the filler behaviour that row exists to forbid.

So these tests assert the CURRENT limitation and its cause.  They fail the
moment someone wires picks through, which is precisely when
``C7-PICKGEN-01``'s policy stops being theoretical.  A limitation nobody
measured reads identically to a limitation nobody has.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from src.trade import finder


def _finder_source() -> str:
    return Path(inspect.getfile(finder)).read_text(encoding="utf-8")


def test_resolve_roster_reads_players_and_not_picks():
    """Structural, so it cannot pass by accident on a board that has no picks.

    The whole function is inspected: any read of a ``picks`` / ``pickDetails``
    key on the team dict means the first break has been repaired.
    """
    tree = ast.parse(_finder_source())
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_roster"
    )
    keys = {
        node.slice.value
        for node in ast.walk(target)
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    } | {
        node.args[0].value
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    assert "players" in keys, "the roster read moved — this guard needs rewriting"
    assert not ({"picks", "pickDetails"} & keys), (
        "`_resolve_roster` now reads pick ownership. That closes break 1 of 2 "
        "documented in this module. Before shipping it, check C7-PICKGEN-01: "
        "picks may not enter generated packages as equalizer filler."
    )


def test_an_owned_pick_never_reaches_a_returned_trade():
    """Behavioural counterpart, against a REAL board.

    A synthetic fixture cannot prove this: the finder's absolute value gates
    and its per-market top-150 filter are calibrated for the live scale, and a
    hand-built pool either fails them or has to be tuned until it passes, at
    which point it is testing the tuning.  So this runs the finder over the
    newest COMPLETE archived scrape (``tests/archive_fixtures``) — deterministic,
    tracked, and it SKIPS rather than passing vacuously when no complete bundle
    exists.

    The assertion is an INVARIANT ("no returned trade contains a pick"), never
    a count — per the CI rule that a blocking-gate test must not assert an
    absolute number over a board whose contents depend on which sources
    answered.
    """
    import pytest

    from src.api.data_contract import build_api_data_contract
    from tests.archive_fixtures import newest_complete_raw_payload

    raw, label = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape available")

    contract = build_api_data_contract(raw)
    teams = (contract.get("sleeper") or {}).get("teams") or []
    if len(teams) < 2:
        pytest.skip(f"{label}: fewer than two rosters")

    pool = finder.build_asset_pool(raw["players"])
    priced_picks = [a for a in pool if a.is_pick]
    assert priced_picks, (
        f"{label}: the pool prices no picks at all, so this test cannot "
        "distinguish 'picks are unreachable' from 'there were no picks'"
    )

    me = max(teams, key=lambda t: len(t.get("players") or []))
    owned = me.get("picks") or []
    assert owned, f"{label}: the fixture team owns no picks — nothing to reach"

    result = finder.find_trades(
        raw["players"],
        me["name"],
        [t["name"] for t in teams if t["name"] != me["name"]],
        teams,
        contract=contract,
    )
    trades = result["trades"]
    assert trades, f"{label}: the finder returned nothing — this proves nothing"

    for trade in trades:
        for side in ("give", "receive"):
            for asset in trade[side]:
                assert str(asset.get("pos") or "").upper() != "PICK", (
                    "a pick reached a returned trade. If that is deliberate, "
                    "this module's docstring and C7-PICKGEN-01 both need reading."
                )


def test_the_two_label_grammars_still_disagree():
    """Break 2 of 2, stated as the identity mismatch it is.

    Rosters name a pick one way and the priced pool another.  Repairing this
    belongs to `src/identity/picks.py`, which is the canonical owner of pick
    identity and already models exactly this distinction (a league pick's
    label vs a market pick reference).  It must NOT be repaired with a local
    regex in the finder.
    """
    roster_label = "2026 1.06 (own)"
    roster_base = "2026 1.06"
    pool_key = "2026 Pick 1.06"

    assert roster_label != pool_key
    assert roster_base != pool_key
    # And the finder's lookup is a verbatim/case-insensitive name match, so
    # neither form resolves.
    priced = {
        pool_key: {
            "_finalAdjusted": 5000,
            "position": "PICK",
            "_sites": 6,
            "_canonicalSiteValues": {"ktcSfTep": 4500, "idpTradeCalc": 4500},
        }
    }
    pool = finder.build_asset_pool(priced)
    by_name = {a.name: a for a in pool}
    assert pool_key in by_name
    assert roster_label not in by_name
    assert roster_base not in by_name
