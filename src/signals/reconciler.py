"""ONE Central Buy/Sell reconciler (C6-SIG-01) — dedup and lineage only.

The platform has several live Buy/Sell emitters (terminal signal rules,
BDVM's fundamental-vs-market layer, Consensus Edge, the Sharp market
board, ...).  They measure different things, several descend from the
same evidence, and before this module nothing put them side by side.  A
dead module (``src/news/unified_signal_engine.py``, retired with this
unit) claimed to be "the single entry point for every BUY/SELL/HOLD
decision" while nothing called it.

This module is that single entry point, and its methodology boundary is
the point of it:

* **It never blends.**  No numeric score, no average, no cross-emitter
  weight, no vote count that decides anything.  Every emitter's verdict
  is published side by side under its own name, domain and lineage.
  ``tests/signals/test_reconciler.py`` pins this structurally: the module
  contains no arithmetic operator at all.
* **One body of evidence appears once.**  Observations are collapsed when
  they are exact duplicates (same emitter, same label) or same-lineage
  restatements (same correlation group, same direction — e.g. the daily
  alert sweep re-sending the terminal engine's verdict).  Every collapse
  is listed with its reason and the observation it collapsed into.
* **Agreement is not independence.**  Two agreeing verdicts from
  DIFFERENT lineages that share an ancestor are kept — they are different
  questions — but the shared ancestry is published beside the agreement so
  it cannot read as two independent opinions.  Ancestry is the transitive
  closure over ONE declared lineage DAG (:data:`LINEAGE_PARENTS`): the
  terminal engine, Consensus Edge and BDVM's gap all descend from the
  value-signal market (KTC Crowd / Trades / Market, idpTradeCalc).
* **Withheld wins.**  A quarantined canonical row, or a Consensus Edge
  ``Withheld`` verdict, makes the player ``withheld``.  Nothing is
  dropped: the other emitters' verdicts stay listed underneath.
* **Missing is never zero.**  An emitter that did not run is
  ``unobserved`` (with its reason) — never a neutral or a HOLD.  A player
  outside what an emitter evaluated is ``out_of_scope`` for it; one the
  emitter explicitly refused to price is ``declined`` with the owner's
  reason; only an emitter that evaluated the player and said nothing is
  ``silent``.
* **Conflict is labelled, never averaged.**  A BUY and a SELL on one
  player produce state ``conflict`` naming both sides, their domains and
  lineages.

Deciding what to DO with a conflict, how much a lineage should count, or
introducing a STASH / SPECULATIVE BUY category are owner methodology
choices (``docs/lane4/LANE4_SIGNAL_EMITTER_INVENTORY.md`` §3) and are
deliberately absent.

Adapters that read the live emitters through their owners live in
:mod:`src.signals.collect`; this module is pure and takes no I/O.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

RECONCILER_VERSION = "sig.2026-10-07.v1"

# ── Direction vocabulary ─────────────────────────────────────────────────
# A TRANSLATION of each emitter's own label into one shared vocabulary so
# conflicts can be detected.  It adds no category the emitters do not
# already publish, and a label an emitter's table does not list maps to
# ``unmapped`` — never to the nearest-looking direction.
BUY = "buy"
SELL = "sell"
HOLD = "hold"
CAUTION = "caution"
REFUSAL = "refusal"
WITHHELD = "withheld"
UNLABELLED = "unlabelled"
UNMAPPED = "unmapped"

DIRECTIONAL = frozenset({BUY, SELL})

# Emitter run states.
OBSERVED = "observed"
UNOBSERVED = "unobserved"

# Per-player reconciled states.  Categorical, never a magnitude.
STATE_WITHHELD = "withheld"
STATE_CONFLICT = "conflict"
STATE_BUY_ONLY = "directional_buy_only"
STATE_SELL_ONLY = "directional_sell_only"
STATE_NONE = "no_directional_signal"

# Emitter dispositions in the registry.
COLLECTED = "collected"
RESTATEMENT = "restatement"
OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class EmitterSpec:
    """One Buy/Sell emitter as the reconciler understands it.

    ``lineage_group`` is the correlation group of the evidence that DRIVES
    the verdict; two emitters in one group restate one body of evidence.
    Its ``ancestors`` are NOT declared per emitter: they are the transitive
    closure of ``lineage_group`` over the one declared DAG,
    :data:`LINEAGE_PARENTS`, so a shared upstream declared once reaches
    every descendant (agreement is then reported as non-independent rather
    than collapsed).
    """

    emitter_id: str
    owner: str
    domain: str
    lineage_group: str
    scope: str
    label_directions: Mapping[str, str]
    disposition: str
    restates: str | None = None
    note: str = ""

    @property
    def ancestors(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                node for node in lineage_closure(self.lineage_group) if node != self.lineage_group
            )
        )


#: The ONE declared lineage DAG: correlation group -> the groups its
#: evidence is derived from.  Ancestry everywhere in this module is the
#: transitive closure over this table (:func:`lineage_closure`).
#:
#: ``value_market_sources`` is one correlation family: KTC Crowd, KTC Trades,
#: KTC Market (KTC's own Crowd+Trades, derived from the other two) and
#: idpTradeCalc.  The canonical board votes on KTC Crowd / KTC Trades /
#: idpTradeCalc; Consensus Edge's mispricing compares fair value against KTC
#: Market (offense) / idpTradeCalc (IDP); BDVM's market layer reads the same
#: value-signal sources.  So value drift, Consensus Edge and the BDVM gap are
#: NOT independent votes (lane-4 inventory section 3.3).
LINEAGE_PARENTS: dict[str, tuple[str, ...]] = {
    # roots
    "value_market_sources": (),
    "expert_rank_sources": (),
    "news_feed": (),
    "bdvm_projections": (),
    "sharp_cohort_movements": (),
    "player_context": (),
    "ros_projection": (),
    "intel_ledger": (),
    # derived
    "canonical_board": ("value_market_sources", "expert_rank_sources"),
    "canonical_board_history": ("canonical_board", "news_feed"),
    # BDVM fundamentals take no market input, but the GAP that sets its
    # direction is fundamentals against the value-signal market.
    "bdvm_fundamental_vs_market": ("bdvm_projections", "value_market_sources"),
    "consensus_edge_composite": (
        "canonical_board",
        "value_market_sources",
        "sharp_cohort_movements",
        "player_context",
    ),
    "canonical_board_vs_retail_market": ("canonical_board", "value_market_sources"),
}


def lineage_closure(group: str) -> frozenset[str]:
    """``group`` plus every lineage group it descends from, transitively."""
    if group not in LINEAGE_PARENTS:
        raise ValueError(f"undeclared lineage group: {group!r}")
    seen: set[str] = set()
    stack = [group]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(LINEAGE_PARENTS[node])
    return frozenset(seen)


_TERMINAL_LABELS = {
    "BUY": BUY,
    "SELL": SELL,
    "RISK": CAUTION,
    "MONITOR": CAUTION,
    "STRONG_HOLD": HOLD,
    "HOLD": HOLD,
}
_BDVM_LABELS = {
    "STRONG_BUY": BUY,
    "BUY": BUY,
    "HOLD": HOLD,
    "SELL": SELL,
    "STRONG_SELL": SELL,
    "NO_MARKET": REFUSAL,
}
# Consensus Edge's own label strings (``src/consensus_edge/score.py``).
_CONSENSUS_EDGE_LABELS = {
    "Strong Buy": BUY,
    "Buy": BUY,
    "Neutral": HOLD,
    "Sell": SELL,
    "Strong Sell": SELL,
    "Conflicted": REFUSAL,
    "Insufficient Evidence": REFUSAL,
    "No Market Price": REFUSAL,
    "Withheld": WITHHELD,
}

#: Every emitter the lane-4 inventory found, with what this unit does with
#: it.  Order matters only for tie-breaking which observation a restatement
#: collapses INTO (the lineage root is always preferred over a restatement).
EMITTERS: tuple[EmitterSpec, ...] = (
    EmitterSpec(
        emitter_id="terminal_signal",
        owner="src/api/terminal.py::_evaluate_signal (via build_terminal_payload)",
        domain="market_momentum",
        lineage_group="canonical_board_history",
        scope="roster",
        label_directions=_TERMINAL_LABELS,
        disposition=COLLECTED,
        note="Board-value drift + news rules for the selected roster.",
    ),
    EmitterSpec(
        emitter_id="bdvm_market_signal",
        owner="src/bdvm/market.py::buy_hold_sell (via src/api/bdvm_api.get_bdvm_values)",
        domain="fundamental",
        lineage_group="bdvm_fundamental_vs_market",
        scope="league",
        label_directions=_BDVM_LABELS,
        disposition=COLLECTED,
        note=(
            "Projection-driven fundamental value against the value-signal market. "
            "Fundamentals take no market input, but the gap that sets the direction "
            "does, so the verdict is partly market-derived."
        ),
    ),
    EmitterSpec(
        emitter_id="consensus_edge",
        owner="src/consensus_edge/service.py::build_board (via api.board_for_contract)",
        domain="consensus",
        lineage_group="consensus_edge_composite",
        scope="scoring_profile",
        label_directions=_CONSENSUS_EDGE_LABELS,
        disposition=COLLECTED,
        note=(
            "Composite of mispricing (fair value vs KTC Market / idpTradeCalc), "
            "sharp flow and opportunity; flag-gated."
        ),
    ),
    EmitterSpec(
        emitter_id="sharp_market",
        owner="src/sharp/market.py::market_payload",
        domain="sharp",
        lineage_group="sharp_cohort_movements",
        scope="global",
        label_directions={},
        disposition=COLLECTED,
        note=(
            "Publishes signed movement strength but NO verdict; carried as "
            "unlabelled evidence.  Turning its strength into Buy/Sell is a "
            "threshold choice this reconciler does not make."
        ),
    ),
    EmitterSpec(
        emitter_id="signal_alerts",
        owner="src/api/signal_alerts.py::process_user_alerts",
        domain="market_momentum",
        lineage_group="canonical_board_history",
        scope="roster",
        label_directions=_TERMINAL_LABELS,
        disposition=RESTATEMENT,
        restates="terminal_signal",
        note="Emails the terminal engine's verdicts; same evidence, not collected.",
    ),
    EmitterSpec(
        emitter_id="frontend_signal_engine",
        owner="frontend/lib/signal-engine.js::evaluateRoster",
        domain="market_momentum",
        lineage_group="canonical_board_history",
        scope="roster",
        label_directions=_TERMINAL_LABELS,
        disposition=RESTATEMENT,
        restates="terminal_signal",
        note="Rule-table parity with the terminal engine is pinned by test.",
    ),
    EmitterSpec(
        emitter_id="bdvm_signal_alerts",
        owner="src/api/bdvm_signal_alerts.py",
        domain="fundamental",
        lineage_group="bdvm_fundamental_vs_market",
        scope="roster",
        label_directions=_BDVM_LABELS,
        disposition=RESTATEMENT,
        restates="bdvm_market_signal",
        note="Notifies BDVM's own verdicts; same evidence, not collected.",
    ),
    EmitterSpec(
        emitter_id="ros_tags",
        owner="src/ros/tags.py::tags_for_player",
        domain="seasonal",
        lineage_group="ros_projection",
        scope="league",
        label_directions={},
        disposition=OUT_OF_SCOPE,
        note="Contender/rebuilder context tags, not a per-player Buy/Sell verdict.",
    ),
    EmitterSpec(
        emitter_id="intel_leads",
        owner="src/intel/leads.py::score_lead",
        domain="manager",
        lineage_group="intel_ledger",
        scope="league",
        label_directions={},
        disposition=OUT_OF_SCOPE,
        note="Ranks trade PARTNERS for a chosen player; not a player verdict.",
    ),
    EmitterSpec(
        emitter_id="trade_suggestions",
        owner="src/trade/suggestions.py",
        domain="trade",
        lineage_group="canonical_board",
        scope="roster",
        label_directions={},
        disposition=OUT_OF_SCOPE,
        note="Emits whole TRADES (sell-high/buy-low packages), not player verdicts.",
    ),
    EmitterSpec(
        emitter_id="trade_finder",
        owner="src/trade/finder.py",
        domain="trade",
        lineage_group="canonical_board_vs_retail_market",
        scope="roster",
        label_directions={},
        disposition=OUT_OF_SCOPE,
        note="Emits whole TRADES (board-vs-market arbitrage), not player verdicts.",
    ),
)

_SPEC_BY_ID: dict[str, EmitterSpec] = {spec.emitter_id: spec for spec in EMITTERS}
_REGISTRY_ORDER: dict[str, int] = {spec.emitter_id: i for i, spec in enumerate(EMITTERS)}


def _validate_lineage() -> None:
    """Every emitter's group and every declared parent must be in the DAG."""
    for spec in EMITTERS:
        lineage_closure(spec.lineage_group)
    for parents in LINEAGE_PARENTS.values():
        for parent in parents:
            lineage_closure(parent)


_validate_lineage()


def spec_for(emitter_id: str) -> EmitterSpec:
    """The registry entry for ``emitter_id``; unknown ids raise."""
    try:
        return _SPEC_BY_ID[emitter_id]
    except KeyError as exc:
        raise ValueError(f"unregistered signal emitter: {emitter_id!r}") from exc


def direction_for(emitter_id: str, native_label: str | None) -> str:
    """Translate an emitter's own label; never guess an unlisted one."""
    if native_label is None:
        return UNLABELLED
    return spec_for(emitter_id).label_directions.get(str(native_label), UNMAPPED)


@dataclass(frozen=True)
class Observation:
    """One emitter's verdict about one player, as its owner published it."""

    emitter_id: str
    player_key: str
    native_label: str | None
    display_name: str | None = None
    reason: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    #: How the identity join placed this row (``player_id`` /
    #: ``emitter_key`` / ``exact_name`` / ``name_fallback:*`` ...).
    placement: str | None = None


@dataclass(frozen=True)
class EmitterRun:
    """Whether an emitter ran for this request, and what it said.

    ``state`` is ``observed`` or ``unobserved``; an unobserved run carries
    a ``reason`` and no observations.  ``freshness`` is the emitter's own
    data-age verdict (``fresh`` / ``stale`` / ``unknown`` plus its basis).

    ``covered_keys`` is the set of players the emitter actually EVALUATED
    (a roster-scoped emitter, or a board truncated at a row limit); ``None``
    means it evaluated the whole universe.  A player outside it is
    ``out_of_scope`` for that emitter — never ``silent``.  ``declined`` maps
    players the emitter explicitly refused to price to the owner's own
    reason (e.g. BDVM ``no_projection``).
    """

    emitter_id: str
    state: str
    reason: str | None = None
    as_of: str | None = None
    freshness: Mapping[str, Any] = field(default_factory=dict)
    observations: tuple[Observation, ...] = ()
    notes: tuple[str, ...] = ()
    covered_keys: frozenset[str] | None = None
    declined: Mapping[str, str] = field(default_factory=dict)


def unobserved(emitter_id: str, reason: str, *, notes: Sequence[str] = ()) -> EmitterRun:
    """Convenience constructor for an emitter that did not run."""
    spec_for(emitter_id)
    return EmitterRun(emitter_id=emitter_id, state=UNOBSERVED, reason=reason, notes=tuple(notes))


def _validate_runs(runs: Sequence[EmitterRun]) -> dict[str, EmitterRun]:
    by_id: dict[str, EmitterRun] = {}
    for run in runs:
        spec_for(run.emitter_id)
        if run.state not in (OBSERVED, UNOBSERVED):
            raise ValueError(f"emitter {run.emitter_id!r}: unknown run state {run.state!r}")
        if run.emitter_id in by_id:
            # Two runs of one emitter would count its evidence twice; refuse
            # rather than silently pick one (same posture as the confidence
            # gate refusing a repeated family).
            raise ValueError(f"duplicate run for emitter {run.emitter_id!r}")
        if run.state == UNOBSERVED and run.observations:
            raise ValueError(f"unobserved emitter {run.emitter_id!r} carries observations")
        for obs in run.observations:
            if obs.emitter_id != run.emitter_id:
                raise ValueError(
                    f"observation from {obs.emitter_id!r} filed under run {run.emitter_id!r}"
                )
        by_id[run.emitter_id] = run
    return by_id


def _signal_entry(obs: Observation, run: EmitterRun) -> dict[str, Any]:
    spec = spec_for(obs.emitter_id)
    return {
        "emitter": obs.emitter_id,
        "domain": spec.domain,
        "lineageGroup": spec.lineage_group,
        "ancestors": list(spec.ancestors),
        "nativeLabel": obs.native_label,
        "direction": direction_for(obs.emitter_id, obs.native_label),
        "reason": obs.reason,
        "placement": obs.placement,
        "asOf": run.as_of,
        "freshness": dict(run.freshness) if run.freshness else {"state": "unknown"},
        "evidence": dict(obs.evidence),
    }


def _ref(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "emitter": entry["emitter"],
        "domain": entry["domain"],
        "lineageGroup": entry["lineageGroup"],
        "nativeLabel": entry["nativeLabel"],
    }


def _collapse(
    observations: Sequence[tuple[Observation, EmitterRun]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep one observation per body of evidence; list everything collapsed.

    Lineage roots are visited before restatements so a restatement always
    collapses INTO the emitter it restates, never the other way round.
    """

    def _order(item: tuple[Observation, EmitterRun]) -> tuple[bool, int]:
        spec = spec_for(item[0].emitter_id)
        return (spec.restates is not None, _REGISTRY_ORDER[spec.emitter_id])

    kept: list[dict[str, Any]] = []
    collapsed: list[dict[str, Any]] = []
    by_exact: dict[tuple[str, str | None], dict[str, Any]] = {}
    by_lineage: dict[tuple[str, str], dict[str, Any]] = {}
    for obs, run in sorted(observations, key=_order):
        entry = _signal_entry(obs, run)
        exact_key = (obs.emitter_id, obs.native_label)
        lineage_key = (entry["lineageGroup"], entry["direction"])
        if exact_key in by_exact:
            collapsed.append(
                {
                    **_ref(entry),
                    "reason": "exact_duplicate",
                    "collapsedInto": by_exact[exact_key]["emitter"],
                }
            )
            continue
        if lineage_key in by_lineage:
            collapsed.append(
                {
                    **_ref(entry),
                    "reason": "same_lineage_restatement",
                    "collapsedInto": by_lineage[lineage_key]["emitter"],
                }
            )
            continue
        by_exact[exact_key] = entry
        by_lineage[lineage_key] = entry
        kept.append(entry)
    return kept, collapsed


def _shared_ancestry(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    """Lineage nodes that more than one of ``entries`` descends from."""
    counts = Counter(
        node for entry in entries for node in {entry["lineageGroup"], *entry["ancestors"]}
    )
    return sorted(node for node, seen in counts.items() if seen > 1)


def _agreement(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if len(entries) < 2:
        return None
    shared = _shared_ancestry(entries)
    return {
        "emitters": [entry["emitter"] for entry in entries],
        "domains": sorted({entry["domain"] for entry in entries}),
        "sharedAncestry": shared,
        # Not a count of votes: whether the agreeing verdicts could be one
        # body of evidence seen twice.
        "independent": not shared,
    }


def _conflict(
    buys: Sequence[Mapping[str, Any]], sells: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    if not buys or not sells:
        return None
    domains = {entry["domain"] for entry in [*buys, *sells]}
    buy_lineages = {entry["lineageGroup"] for entry in buys}
    sell_lineages = {entry["lineageGroup"] for entry in sells}
    return {
        "buy": [_ref(entry) for entry in buys],
        "sell": [_ref(entry) for entry in sells],
        "crossDomain": len(domains) > 1,
        "sameLineage": not buy_lineages.isdisjoint(sell_lineages),
        "resolution": "not_resolved_by_reconciler",
    }


def reconcile(
    runs: Sequence[EmitterRun],
    *,
    player_keys: Sequence[str] | None = None,
    quarantined: Mapping[str, str] | None = None,
    display_names: Mapping[str, str] | None = None,
    unresolved: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Publish every player's labelled domain signals side by side.

    ``runs`` — one :class:`EmitterRun` per emitter that was asked.  Any
    COLLECTED emitter with no run at all is reported ``unobserved`` with
    reason ``not_run`` (missing is never neutral).

    ``player_keys`` — the player universe (e.g. a roster), in order.  When
    omitted it is every player any observed emitter spoke about.

    ``quarantined`` — canonical-row quarantine by player key → reason.
    These rows are WITHHELD regardless of what any emitter says, and
    whether or not Consensus Edge ran.

    ``unresolved`` — emitter rows the identity join refused to place (never
    fuzzy-matched); passed through so they are visible, not dropped.
    """
    quarantined = dict(quarantined or {})
    display_names = dict(display_names or {})
    by_id = _validate_runs(runs)

    for spec in EMITTERS:
        if spec.disposition == COLLECTED and spec.emitter_id not in by_id:
            by_id[spec.emitter_id] = unobserved(spec.emitter_id, "not_run")

    observed_runs = [run for run in by_id.values() if run.state == OBSERVED]
    unobserved_ids = sorted(run.emitter_id for run in by_id.values() if run.state == UNOBSERVED)

    by_player: dict[str, list[tuple[Observation, EmitterRun]]] = {}
    for run in observed_runs:
        for obs in run.observations:
            by_player.setdefault(obs.player_key, []).append((obs, run))
            if obs.display_name and obs.player_key not in display_names:
                display_names[obs.player_key] = obs.display_name

    if player_keys is None:
        universe = sorted(by_player)
    else:
        universe = list(dict.fromkeys(player_keys))

    players: list[dict[str, Any]] = []
    for key in universe:
        items = by_player.get(key, [])
        kept, collapsed = _collapse(items)
        spoke = {obs.emitter_id for obs, _run in items}
        withheld_by: list[dict[str, Any]] = []
        if key in quarantined:
            withheld_by.append({"source": "canonical_quarantine", "reason": quarantined[key]})
        for entry in kept:
            if entry["direction"] == WITHHELD:
                withheld_by.append({"source": entry["emitter"], "reason": entry["reason"]})
        buys = [entry for entry in kept if entry["direction"] == BUY]
        sells = [entry for entry in kept if entry["direction"] == SELL]
        if withheld_by:
            state = STATE_WITHHELD
        elif buys and sells:
            state = STATE_CONFLICT
        elif buys:
            state = STATE_BUY_ONLY
        elif sells:
            state = STATE_SELL_ONLY
        else:
            state = STATE_NONE
        players.append(
            {
                "playerKey": key,
                "displayName": display_names.get(key),
                "state": state,
                "withheldBy": withheld_by,
                "signals": kept,
                "collapsed": collapsed,
                "conflict": _conflict(buys, sells),
                "agreement": {
                    BUY: _agreement(buys),
                    SELL: _agreement(sells),
                },
                "emittersUnobserved": unobserved_ids,
                "emittersOutOfScope": sorted(
                    run.emitter_id
                    for run in observed_runs
                    if run.emitter_id not in spoke
                    and run.covered_keys is not None
                    and key not in run.covered_keys
                ),
                "emittersDeclined": [
                    {"emitter": run.emitter_id, "reason": run.declined[key]}
                    for run in observed_runs
                    if run.emitter_id not in spoke and key in run.declined
                ],
                "emittersSilent": sorted(
                    run.emitter_id
                    for run in observed_runs
                    if run.emitter_id not in spoke
                    and key not in run.declined
                    and (run.covered_keys is None or key in run.covered_keys)
                ),
            }
        )

    emitters_out: list[dict[str, Any]] = []
    for spec in EMITTERS:
        run = by_id.get(spec.emitter_id)
        if spec.disposition != COLLECTED and run is None:
            state = spec.disposition
            reason = (
                f"restates {spec.restates}; its evidence is already counted there"
                if spec.disposition == RESTATEMENT
                else "not a per-player Buy/Sell verdict"
            )
        else:
            state = run.state if run is not None else UNOBSERVED
            reason = run.reason if run is not None else "not_run"
        emitters_out.append(
            {
                "emitterId": spec.emitter_id,
                "owner": spec.owner,
                "domain": spec.domain,
                "lineageGroup": spec.lineage_group,
                "ancestors": list(spec.ancestors),
                "scope": spec.scope,
                "disposition": spec.disposition,
                "restates": spec.restates,
                "note": spec.note,
                "state": state,
                "reason": reason,
                "asOf": run.as_of if run is not None else None,
                "freshness": dict(run.freshness) if run is not None and run.freshness else None,
                "observationCount": len(run.observations) if run is not None else None,
                "notes": list(run.notes) if run is not None else [],
            }
        )

    return {
        "reconcilerVersion": RECONCILER_VERSION,
        "method": {
            "kind": "dedup_and_lineage_only",
            "numericBlend": False,
            "crossEmitterWeights": False,
            "conflictResolution": "labelled_not_resolved",
            "withheldPrecedence": ["canonical_quarantine", "consensus_edge:Withheld"],
            "missingEmitter": "unobserved_not_neutral",
        },
        "emitters": emitters_out,
        "players": players,
        "unresolved": [dict(item) for item in unresolved],
        "counts": {
            "players": len(players),
            "withheld": len([p for p in players if p["state"] == STATE_WITHHELD]),
            "conflicts": len([p for p in players if p["state"] == STATE_CONFLICT]),
            "collapsedObservations": len([c for p in players for c in p["collapsed"]]),
            "unresolvedObservations": len(unresolved),
        },
    }
