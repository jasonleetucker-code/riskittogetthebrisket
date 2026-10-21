"""The ONE owner of "how a team-attributed trade becomes an analysis", any
number of teams (Brisket Trade Advisor B0-c; N-team engine, spec
``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §2.5).

Before this module the orchestration lived inline in ``server.py``'s
``_build_trade_simulation`` and ``post_trade_analyze``: resolve the team's
competitive posture with the Analyze-Trade build rule, run
``trade_simulator.simulate_trade`` with Team Context's roster utility, stamp
``teamContext``, then call ``analyze_trade`` with provenance read from a
SECOND read of the global contract.  A public advisor that copied those steps
would be a second owner that drifts the first time a route changes.

So every team-attributed analysis — ``/api/trade/analyze``,
``/api/trade/simulate``, ``/api/trade/analyze-multi`` and the public advisor —
goes through these two functions:

* :func:`simulate_for_team` — posture (``build_if_missing = for_analysis and
  team_context``, the War Room rule), ``simulate_trade`` (roster utility only
  for an analysis with Team Context), and the ``teamContext`` stamp.
* :func:`analyze_for_team` — ``analyze_trade`` with provenance read from THE
  CONTRACT THE SIMULATION RAN AGAINST (never a second global read, so a
  publish mid-request cannot pair one board's verdict with another's stamp).

:func:`analyze_trade_n` is the one N-team composer: a per-team loop over
those same two functions, one snapshot and one validated ledger
(``src/trade/trade_ledger.py``), every team evaluated independently from that
one snapshot — which is simultaneous application by construction (a team's
roster changes only through its own legs; no chain of 2-team trades is ever
modelled).  Per team it adds only projections (``src/trade/team_verdicts.py``).
At N = 2 each team's ``simulation`` + ``analysis`` equal the 2-team route's.

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

import threading
from contextlib import nullcontext
from typing import Any, Callable, ContextManager, Literal, Mapping, Sequence

from src.api import trade_simulator

#: ``stage(name)`` -> a context manager wrapped around each step.  An OBSERVER
#: hook (request timing); it never changes what runs.
StageHook = Callable[[str], ContextManager[Any]]


def _no_stage(_name: str) -> ContextManager[Any]:
    return nullcontext()


#: "Not passed" for :func:`analyze_for_team`'s ``comparables``.
_UNSET: Any = object()


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
    include_roster_capacity: bool = True,
    unverifiable_asset_ids: Sequence[str] = (),
    scarcity_reading: tuple[Any, Any] | None = None,
) -> dict[str, Any]:
    """Posture + ``simulate_trade`` + the ``teamContext`` stamp for one team.

    ``posture_resolver(contract, league_key, team, *, build_if_missing)``
    defaults to ``trade_simulator.competitive_posture_for``; tests pin it.
    ``include_roster_capacity`` / ``unverifiable_asset_ids`` /
    ``scarcity_reading`` pass straight to ``simulate_trade`` (the N-team
    engine's market-fairness mode, ownership evidence and once-per-request
    scarcity read); their defaults leave the output byte-identical.
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
            include_roster_capacity=include_roster_capacity,
            unverifiable_asset_ids=list(unverifiable_asset_ids or ()),
            scarcity_reading=scarcity_reading,
        )
    if for_analysis:
        result["teamContext"] = {
            "applied": bool(team_context),
            "mode": "team" if team_context else "asset_only",
        }
    return result


def contract_provenance(contract: Any) -> dict[str, Any]:
    """The board stamp + scoring fingerprint of the contract analysed.

    The served board stamps ``generatedAt`` at the TOP level, not under
    ``meta`` (five-point review 2026-10-20, #1871: reading ``meta.generatedAt``
    made every receipt's ``boardStamp`` null).  The stamp therefore comes from
    ``trade_analyze_runtime.contract_generation`` -- the ONE reader the in-flight
    key and the decision receipt share (top level, ``meta`` fallback, ``None``
    when absent).
    """
    from src.api.trade_analyze_runtime import contract_generation  # noqa: PLC0415

    meta = contract.get("meta") if isinstance(contract, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    return {
        "boardStamp": contract_generation(contract) if isinstance(contract, dict) else None,
        "scoringFingerprint": meta.get("scoringFingerprint"),
    }


def analyze_for_team(
    simulation: dict[str, Any],
    *,
    contract: Any,
    team_goal: Any = None,
    comparables: Any = _UNSET,
    counterfactuals: bool = True,
) -> dict[str, Any]:
    """``analyze_trade`` over one :func:`simulate_for_team` result.

    ``comparables`` is the exact object the 2-team route passes (the
    ``comparable_trades`` payload); omitted means not computed.
    ``counterfactuals=False`` skips the "what would change it" search (it
    never changes the decision; see ``trade_decision.decide``).
    """
    from src.trade.analyze_trade import analyze_trade  # noqa: PLC0415

    return analyze_trade(
        simulation,
        comparables=None if comparables is _UNSET else comparables,
        team_goal=team_goal,
        provenance=contract_provenance(contract),
        counterfactuals=counterfactuals,
    )


# ── N teams (spec docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §2.5-§2.9) ─────────

MULTI_TEAM_VERSION = "multi_team_v1"
Mode = Literal["team_context", "asset_only", "market_fairness"]
MODES: tuple[str, ...] = ("team_context", "asset_only", "market_fairness")

#: ``comparables_provider(flows, simulation) -> comparables payload`` — the
#: route's own ``comparable_trades`` call for that team (N = 2 only).
ComparablesProvider = Callable[[Any, dict[str, Any]], Any]


class PackageModelUnavailable(RuntimeError):
    """The active package model is not geom with a readable config — the
    N-team engine has no defined meaning under the KTC rollback model."""


class ConservationViolation(RuntimeError):
    """A per-team result failed to reconcile with the ledger (I6 / I13).
    Never published: the private route answers 500, the public route 503."""


def package_model_ready() -> bool:
    from src.valuation_math import package_model  # noqa: PLC0415

    try:
        return (
            package_model.config_state() == "ok"
            and package_model.active_model_id() == package_model.GEOM_Q078_V1
        )
    except Exception:  # noqa: BLE001 — unknown is not ready
        return False


def _no_posture(contract: Any, league_key: Any, team: Any, *, build_if_missing: bool) -> dict:
    """The market-fairness posture: explicitly not requested (an explicit
    callable, because ``simulate_for_team`` falls back to the real resolver
    when handed ``None``)."""
    return {"available": False, "unavailableReason": "not_requested_market_fairness"}


class _PostureMemo:
    """One league posture bundle per request and build rule, each team's block
    looked up from it with the owner's own lookup
    (``trade_simulator.league_posture_bundle`` + ``posture_block_for`` — the two
    halves of ``competitive_posture_for``, so a block is byte-identical to that
    function's answer for the team).

    The bundle is keyed by ``ownerId``: a team whose ``ownerId`` is empty or
    shared with another snapshot team (orphan / co-owned) gets
    ``owner_identity_ambiguous``, never another team's block.
    """

    def __init__(self, snap: Any) -> None:
        self._snap = snap
        self._lock = threading.Lock()
        self._bundles: dict[bool, tuple[Any, Any, Any]] = {}
        counts: dict[str, int] = {}
        for t in snap.teams_by_roster_id.values():
            oid = str(t.get("ownerId") or "").strip()
            counts[oid] = counts.get(oid, 0) + 1
        self._owner_counts = counts

    def __call__(
        self, contract: Any, league_key: Any, team: Any, *, build_if_missing: bool
    ) -> dict[str, Any]:
        oid = str((team or {}).get("ownerId") or "").strip()
        if not oid or self._owner_counts.get(oid, 0) != 1:
            return {"available": False, "unavailableReason": "owner_identity_ambiguous"}
        key = bool(build_if_missing)
        with self._lock:
            bundle = self._bundles.get(key)
            if bundle is None:
                bundle = trade_simulator.league_posture_bundle(
                    self._snap.contract, self._snap.league_key, build_if_missing=key
                )
                self._bundles[key] = bundle
        postures, meta, unavailable = bundle
        if unavailable is not None:
            return dict(unavailable)
        return trade_simulator.posture_block_for(postures or {}, meta, team)


def _team_stage(stage: StageHook, rid: int) -> StageHook:
    return lambda name: stage(f"team:{rid}:{name}")


#: Every per-leg ``valueState`` the N-team payload can carry.  Only
#: ``priced`` carries a number; consumers must treat any state they do not
#: recognise as NOT priced (fail closed).
VALUE_STATES = ("priced", "unpriced", "off_board", "not_held", "quarantined", "stale")


def _value_entry(asset: Mapping[str, Any] | None) -> tuple[Any, str]:
    """``(value, valueState)`` for one leg's resolved asset.

    States: ``off_board`` (not resolved), ``unpriced`` (no positive canonical
    value), ``quarantined`` (the pipeline's quarantine verdict), ``stale``
    (the confidence owner's freshness axis reads ``low``), ``priced``.  The
    three evidence states are read through ``trade_decision.asset_evidence_codes``
    — the same codes, in the same order, the decision's evidence gates raise —
    so a value the decision withholds as untrustworthy is never presented as
    ``priced`` (R1-L2 / E-1 F2).  Every non-``priced`` state carries
    ``value: None``: the number is withheld, never 0, and it never enters a
    raw total.
    """
    from src.trade.trade_decision import asset_evidence_codes  # noqa: PLC0415

    if asset is None:
        return None, "off_board"
    codes = asset_evidence_codes(dict(asset))
    if "unpriced_assets" in codes:
        return None, "unpriced"
    if "quarantined_values" in codes:
        return None, "quarantined"
    if "stale_values" in codes:
        return None, "stale"
    return asset["value"], "priced"


def _match_assets(
    legs: Sequence[Any],
    resolved: Sequence[Mapping[str, Any]],
    labels: Mapping[str, str],
) -> dict[str, Mapping[str, Any] | None]:
    """Each leg's resolved simulation asset: players by ``playerId``, picks by
    the proven ``assetId``, else by the label the engine passed (consumed once).
    ``None`` when the simulation did not resolve the leg."""
    from src.trade.trade_ledger import PLAYER_PREFIX  # noqa: PLC0415

    pool = list(resolved)
    used: set[int] = set()
    out: dict[str, Mapping[str, Any] | None] = {}

    def _take(pred: Callable[[Mapping[str, Any]], bool]) -> Mapping[str, Any] | None:
        for i, a in enumerate(pool):
            if i not in used and pred(a):
                used.add(i)
                return a
        return None

    for leg in legs:
        aid = leg.asset_id
        if aid.startswith(PLAYER_PREFIX):
            pid = aid[len(PLAYER_PREFIX) :]
            out[aid] = _take(lambda a, pid=pid: str(a.get("playerId") or "") == pid)
        else:
            hit = _take(lambda a, aid=aid: str(a.get("assetId") or "") == aid)
            if hit is None:
                label = labels.get(aid, "")
                hit = _take(
                    lambda a, label=label: not a.get("assetId")
                    and str(a.get("sourceLabel") or "") == label
                )
            out[aid] = hit
    return out


def _side_rows(
    legs: Sequence[Any],
    resolved: Sequence[Mapping[str, Any]],
    labels: Mapping[str, str],
    *,
    direction: str,
    not_held: set[str],
) -> list[dict[str, Any]]:
    from src.trade.trade_ledger import PLAYER_PREFIX  # noqa: PLC0415

    matched = _match_assets(legs, resolved, labels)
    rows = []
    for leg in legs:
        aid = leg.asset_id
        hit = matched.get(aid)
        if hit is None and aid in not_held:
            value, state = None, "not_held"
        else:
            value, state = _value_entry(hit)
        row = {
            "assetId": aid,
            "kind": "player" if aid.startswith(PLAYER_PREFIX) else "pick",
            "label": labels.get(aid, aid),
        }
        if direction == "gives":
            row["toRosterId"] = leg.to_roster_id
        else:
            row["fromRosterId"] = leg.from_roster_id
        row["value"] = value
        row["valueState"] = state
        rows.append(row)
    return rows


def _assert_conserved(ledger: Any, teams: Mapping[int, Mapping[str, Any]]) -> None:
    """I6 / I7 / I13: every leg exactly once in its sender's ``gives`` and once
    in its receiver's ``receives``, nothing else, and one value per asset in
    every view that prices it.  Raises :class:`ConservationViolation`."""
    expected = {leg.asset_id: leg for leg in ledger.legs}
    sent: dict[str, list[tuple[int, Any]]] = {}
    recv: dict[str, list[tuple[int, Any]]] = {}
    for rid, t in teams.items():
        for g in t.get("gives") or []:
            sent.setdefault(g["assetId"], []).append((rid, g))
        for r in t.get("receives") or []:
            recv.setdefault(r["assetId"], []).append((rid, r))
    if set(sent) != set(expected) or set(recv) != set(expected):
        raise ConservationViolation("per-team assets do not reconcile with the ledger")
    for aid, leg in expected.items():
        if len(sent[aid]) != 1 or len(recv[aid]) != 1:
            raise ConservationViolation(f"{aid} counted more than once")
        (s_rid, s_row), (r_rid, r_row) = sent[aid][0], recv[aid][0]
        if s_rid != leg.from_roster_id or r_rid != leg.to_roster_id:
            raise ConservationViolation(f"{aid} attributed to the wrong team")
        if (
            s_row["valueState"] == "priced"
            and r_row["valueState"] == "priced"
            and s_row["value"] != r_row["value"]
        ):
            raise ConservationViolation(f"{aid} carries two values")


def analyze_trade_n(
    snap: Any,
    ledger: Any,
    *,
    mode: Mode,
    counterfactuals: bool,
    team_goals: Mapping[int, Any] | None = None,
    posture_resolver: Callable[..., Mapping[str, Any] | None] | None = None,
    comparables_provider: ComparablesProvider | None = None,
    stage: StageHook | None = None,
) -> dict[str, Any]:
    """The ONE N-team composer: every participating team's own analysis.

    ``snap`` / ``ledger`` come from ``src/trade/trade_ledger.py``
    (``snapshot_for`` + ``validate_ledger``).  Per team, in ascending
    ``rosterId`` (the order affects timing only): :func:`simulate_for_team`
    on that team's gives and receives — players by Sleeper id, picks by
    canonical id, labels for display only — then :func:`analyze_for_team`,
    then the projections of ``team_verdicts``.  Each team is evaluated from
    the SAME snapshot with only its own legs applied, so all roster changes
    are simultaneous and a team's result never depends on legs between other
    teams (I10).

    Modes:

    * ``team_context`` (private default) — Team Context on; one posture
      bundle per request (built if missing, the War Room rule);
    * ``asset_only`` (private toggle) — Team Context off, posture read warm;
    * ``market_fairness`` (public advisor) — Team Context off, no posture, no
      roster capacity / final roster / utility, nothing written anywhere.

    Not flag-gated: the private flag gates the private route only.  Refuses
    (:class:`PackageModelUnavailable`) unless the active package model is
    geom with a readable config.  A per-team result that does not reconcile
    with the ledger raises :class:`ConservationViolation` — never published.
    Writes nothing (the private route records the decision receipts).
    """
    from src.trade import roster_capacity, team_verdicts  # noqa: PLC0415
    from src.trade.trade_ledger import pick_label, player_label, team_flows  # noqa: PLC0415

    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    if not package_model_ready():
        raise PackageModelUnavailable("active package model is not geom/ok")
    stage = stage or _no_stage
    team_context = mode == "team_context"
    include_capacity = mode != "market_fairness"
    if mode == "market_fairness":
        resolver = _no_posture
    elif posture_resolver is not None:
        resolver = posture_resolver
    else:
        resolver = _PostureMemo(snap)
    # R1-1: ONE scarcity read per request, shared by every team (the posture
    # bundle's ``_PostureMemo`` twin).  Re-reading it per team could score
    # teams of one trade against different scarcity — the gameplan inputs are
    # re-loaded on every call and can fall to the TTL-cached live fallback.
    # Market fairness builds no capacity, so it reads nothing.
    scarcity_reading = (
        roster_capacity.league_scarcity(snap.league_key, snap.contract)
        if include_capacity
        else None
    )
    goals = dict(team_goals or {})
    unverifiable = set(ledger.unverifiable_asset_ids)
    n_teams = len(ledger.teams)

    teams: dict[int, dict[str, Any]] = {}
    for rid in sorted(ledger.teams):
        flows = team_flows(ledger, rid)
        team = snap.teams_by_roster_id[rid]
        labels = {
            **{f"p:{pid}": player_label(snap, pid) for pid in flows.player_ids_in},
            **{f"p:{pid}": player_label(snap, pid) for pid in flows.player_ids_out},
            **{aid: pick_label(snap, aid) for aid in flows.pick_ids_in},
            **{aid: pick_label(snap, aid) for aid in flows.pick_ids_out},
        }
        mine = sorted(
            a
            for a in unverifiable
            if a in {leg.asset_id for leg in (*flows.gives, *flows.receives)}
        )
        tstage = _team_stage(stage, rid)
        simulation = simulate_for_team(
            dict(snap.contract),
            league_key=snap.league_key,
            roster_settings=dict(snap.roster_settings or {}),
            resolved_team=team,  # the snapshot's own team dict
            players_in=[labels[f"p:{p}"] for p in flows.player_ids_in],
            players_out=[labels[f"p:{p}"] for p in flows.player_ids_out],
            player_ids_in=list(flows.player_ids_in),
            player_ids_out=list(flows.player_ids_out),
            picks_in=[labels[a] for a in flows.pick_ids_in],
            picks_out=[labels[a] for a in flows.pick_ids_out],
            pick_ids_in=list(flows.pick_ids_in),
            pick_ids_out=list(flows.pick_ids_out),
            team_context=team_context,
            for_analysis=True,
            posture_resolver=resolver,
            stage=tstage,
            include_roster_capacity=include_capacity,
            unverifiable_asset_ids=mine,
            scarcity_reading=scarcity_reading,
        )
        comparables: Any = None
        comparables_state: dict[str, Any] | None = None
        if mode != "market_fairness":
            if n_teams == 2 and comparables_provider is not None:
                with tstage("comparables"):
                    try:
                        comparables = comparables_provider(flows, simulation)
                    except Exception:  # noqa: BLE001 — evidence only, never the verdict
                        comparables = {"state": "unavailable", "reason": "comparables_error"}
            elif n_teams >= 3:
                # SD-12: the non-voting comparables lens is not computed per
                # team at N >= 3 until measured to fit the budget.  Named, so
                # "not computed" never reads as "no comparable trades".
                comparables_state = {"state": "not_computed_multi_team"}
        with tstage("decision"):
            analysis = analyze_for_team(
                simulation,
                contract=snap.contract,
                team_goal=goals.get(rid),
                comparables=comparables,
                counterfactuals=counterfactuals,
            )
        decision = analysis.get("decision") if isinstance(analysis, dict) else None
        checks = simulation.get("ownedPickChecks") or {}
        not_held = {
            str(c.get("assetId"))
            for c in checks.get("notOwnedBySender") or []
            if isinstance(c, dict) and c.get("assetId")
        }
        entry: dict[str, Any] = {
            "rosterId": rid,
            "team": {"rosterId": rid, "name": str(team.get("name") or f"Team {rid}")},
            "gives": _side_rows(
                flows.gives,
                simulation.get("sending") or [],
                labels,
                direction="gives",
                not_held=not_held,
            ),
            "receives": _side_rows(
                flows.receives,
                simulation.get("receiving") or [],
                labels,
                direction="receives",
                not_held=set(),
            ),
            "simulation": simulation,
            "analysis": analysis,
            "category": team_verdicts.team_category(decision),
            "categoryText": team_verdicts.team_category_text(decision),
            "categoryReason": team_verdicts.team_category_reason(decision),
            "fairness": team_verdicts.team_fairness(simulation, analysis),
            "unverifiableAssetIds": mine,
        }
        if comparables_state is not None:
            entry["comparables"] = comparables_state
        teams[rid] = entry

    _assert_conserved(ledger, teams)
    ordered = [teams[r] for r in sorted(teams)]
    return {
        "multiTeamVersion": MULTI_TEAM_VERSION,
        "mode": mode,
        "teams": teams,
        "summary": team_verdicts.all_team_summary(ordered, leg_count=len(ledger.legs)),
        "ledger": ledger.to_dict(),
    }


def multi_team_payload(
    result: Mapping[str, Any],
    *,
    snap: Any,
    ledger: Any,
    league_key: str,
    perspective: int | None,
    expected_generation: str | None,
) -> dict[str, Any]:
    """The private ``/api/trade/analyze-multi`` body for one
    :func:`analyze_trade_n` result (spec §3.1), minus what the route adds per
    request (decision receipts, ``tradeRunId``, ``analysisTiming`` and the
    valuation-lens stamp).  One assembly, shared by the route and the UI
    fixtures, so the two cannot drift.  ``teams`` is ascending ``rosterId``.
    """
    from src.valuation_math import fairness_bands, package_model  # noqa: PLC0415

    teams = result["teams"]
    return {
        "multiTeamVersion": result["multiTeamVersion"],
        "leagueKey": league_key,
        "generation": snap.generation,
        "snapshotChanged": (
            None if expected_generation is None else expected_generation != snap.generation
        ),
        "rosters": {"state": snap.rosters_state, "asOf": snap.rosters_as_of},
        "mode": result["mode"],
        "perspectiveRosterId": perspective,
        "teamCount": len(ledger.teams),
        "teams": [teams[rid] for rid in sorted(teams)],
        "summary": result["summary"],
        "ledger": result["ledger"],
        "packageModel": package_model.receipt(),
        "fairnessBands": fairness_bands.receipt(),
    }
