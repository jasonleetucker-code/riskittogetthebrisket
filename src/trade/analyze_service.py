"""The ONE owner of "how a 2-team trade becomes an analysis" (Brisket Trade
Advisor B0-c).

Before this module the orchestration lived inline in ``server.py``'s
``_build_trade_simulation`` and ``post_trade_analyze``: resolve the team's
competitive posture with the Analyze-Trade build rule, run
``trade_simulator.simulate_trade`` with Team Context's roster utility, stamp
``teamContext``, then call ``analyze_trade`` with provenance read from a
SECOND read of the global contract.  A public advisor that copied those steps
would be a second owner that drifts the first time a route changes.

So every 2-team analysis — ``/api/trade/analyze``, ``/api/trade/simulate``
and the public advisor — goes through these two functions:

* :func:`simulate_for_team` — posture (``build_if_missing = for_analysis and
  team_context``, the War Room rule), ``simulate_trade`` (roster utility only
  for an analysis with Team Context), and the ``teamContext`` stamp.
* :func:`analyze_for_team` — ``analyze_trade`` with provenance read from THE
  CONTRACT THE SIMULATION RAN AGAINST (never a second global read, so a
  publish mid-request cannot pair one board's verdict with another's stamp).

What stays in the routes: auth, body parsing, league resolution, the
cross-league overlay splice, team resolution, the NFL-team exposure block, comparables and
the decision receipt (``record_decision``).

Pure orchestration: computes no value, writes nothing.  Pinned by
``tests/trade/test_analyze_service.py`` (an AST guard that both routes call
this module and that nothing else composes ``simulate_trade`` with
``analyze_trade``) and by the War Room fixtures, which are generated through
it and must stay byte-equal.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable, ContextManager, Mapping, Sequence

from src.api import trade_simulator

#: ``stage(name)`` -> a context manager wrapped around each step.  An OBSERVER
#: hook (request timing); it never changes what runs.
StageHook = Callable[[str], ContextManager[Any]]


def _no_stage(_name: str) -> ContextManager[Any]:
    return nullcontext()


def simulate_for_team(
    contract: dict[str, Any],
    *,
    league_key: str | None,
    roster_settings: Mapping[str, Any] | None,
    resolved_team: dict[str, Any] | None,
    players_in: Sequence[str] = (),
    players_out: Sequence[str] = (),
    player_ids_in: Sequence[Any] | None = None,
    player_ids_out: Sequence[Any] | None = None,
    picks_in: Sequence[str] = (),
    picks_out: Sequence[str] = (),
    pick_ids_in: Sequence[Any] | None = None,
    pick_ids_out: Sequence[Any] | None = None,
    team_context: bool,
    for_analysis: bool,
    posture_resolver: Callable[..., Mapping[str, Any] | None] | None = None,
    stage: StageHook | None = None,
) -> dict[str, Any]:
    """Posture + ``simulate_trade`` + the ``teamContext`` stamp for one team.

    ``posture_resolver(contract, league_key, team, *, build_if_missing)``
    defaults to ``trade_simulator.competitive_posture_for``; tests pin it.
    """
    stage = stage or _no_stage
    resolver = posture_resolver or trade_simulator.competitive_posture_for
    with stage("posture"):
        posture = resolver(
            contract,
            league_key,
            resolved_team,
            build_if_missing=bool(for_analysis and team_context),
        )
    with stage("simulation"):
        result = trade_simulator.simulate_trade(
            contract,
            resolved_team=resolved_team,
            players_in=list(players_in or []),
            players_out=list(players_out or []),
            picks_in=list(picks_in or []),
            picks_out=list(picks_out or []),
            pick_asset_ids_in=list(pick_ids_in) if pick_ids_in is not None else None,
            pick_asset_ids_out=list(pick_ids_out) if pick_ids_out is not None else None,
            player_ids_in=list(player_ids_in) if player_ids_in is not None else None,
            player_ids_out=list(player_ids_out) if player_ids_out is not None else None,
            roster_settings=dict(roster_settings or {}),
            league_key=league_key,
            include_roster_utility=bool(for_analysis and team_context),
            competitive_posture=dict(posture) if isinstance(posture, Mapping) else posture,
        )
    if for_analysis:
        result["teamContext"] = {
            "applied": bool(team_context),
            "mode": "team" if team_context else "asset_only",
        }
    return result


def contract_provenance(contract: Any) -> dict[str, Any]:
    """The board stamp + scoring fingerprint of the contract analysed."""
    meta = contract.get("meta") if isinstance(contract, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    return {
        "boardStamp": meta.get("generatedAt"),
        "scoringFingerprint": meta.get("scoringFingerprint"),
    }


def analyze_for_team(
    simulation: dict[str, Any],
    *,
    contract: Any,
    team_goal: Any = None,
    comparables: dict[str, Any] | None = None,
    counterfactuals: bool = True,
) -> dict[str, Any]:
    """``analyze_trade`` over one :func:`simulate_for_team` result.

    ``counterfactuals=False`` skips the "what would change it" search (it
    never changes the decision; see ``trade_decision.decide``).
    """
    from src.trade.analyze_trade import analyze_trade  # noqa: PLC0415

    return analyze_trade(
        simulation,
        comparables=comparables,
        team_goal=team_goal,
        provenance=contract_provenance(contract),
        counterfactuals=counterfactuals,
    )
