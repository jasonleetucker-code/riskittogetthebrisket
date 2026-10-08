"""C6-SIG-01 — the central Buy/Sell reconciler is dedup/lineage ONLY.

Pins the five properties the unit exists for: one body of evidence appears
once (lineage collapse), conflict is labelled and never averaged, a missing
emitter is unobserved rather than neutral, withheld wins without dropping
anything, and the module contains no numeric blend or cross-emitter weight.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.signals import reconciler as rec

REPO = Path(__file__).resolve().parents[2]


def _run(emitter, *observations, state=rec.OBSERVED, reason=None, freshness=None):
    return rec.EmitterRun(
        emitter_id=emitter,
        state=state,
        reason=reason,
        as_of="2026-10-07T12:00:00+00:00",
        freshness=freshness or {"state": "fresh"},
        observations=tuple(observations),
    )


def _obs(emitter, key, label, **kw):
    return rec.Observation(emitter_id=emitter, player_key=key, native_label=label, **kw)


def _player(payload, key):
    matches = [p for p in payload["players"] if p["playerKey"] == key]
    assert len(matches) == 1, matches
    return matches[0]


# ── lineage collapse ─────────────────────────────────────────────────────


def test_same_lineage_restatement_collapses_into_its_root_whatever_the_order():
    """The alert sweep re-sending the terminal verdict is ONE body of evidence."""
    for order in ("root_first", "restatement_first"):
        runs = [
            _run("terminal_signal", _obs("terminal_signal", "player:1", "BUY")),
            _run("signal_alerts", _obs("signal_alerts", "player:1", "BUY")),
        ]
        if order == "restatement_first":
            runs.reverse()
        player = _player(rec.reconcile(runs), "player:1")
        assert [s["emitter"] for s in player["signals"]] == ["terminal_signal"], order
        assert player["collapsed"] == [
            {
                "emitter": "signal_alerts",
                "domain": "market_momentum",
                "lineageGroup": "canonical_board_history",
                "nativeLabel": "BUY",
                "reason": "same_lineage_restatement",
                "collapsedInto": "terminal_signal",
            }
        ], order
        assert player["state"] == rec.STATE_BUY_ONLY


def test_exact_duplicate_from_one_emitter_is_listed_once_and_recorded():
    run = _run(
        "bdvm_market_signal",
        _obs("bdvm_market_signal", "player:1", "SELL"),
        _obs("bdvm_market_signal", "player:1", "SELL"),
    )
    player = _player(rec.reconcile([run]), "player:1")
    assert len(player["signals"]) == 1
    assert [c["reason"] for c in player["collapsed"]] == ["exact_duplicate"]
    assert player["collapsed"][0]["collapsedInto"] == "bdvm_market_signal"


def test_terminal_and_bdvm_agreement_is_not_independent():
    """Both descend from the value-signal market (D1, review of #1705).

    The canonical board the terminal engine drifts on is built partly from
    KTC Crowd / KTC Trades / idpTradeCalc, and BDVM's verdict is the gap
    between its fundamentals and those same value markets.  Kept as two
    signals (different questions), but never published as independent.
    """
    payload = rec.reconcile(
        [
            _run("terminal_signal", _obs("terminal_signal", "player:1", "BUY")),
            _run("bdvm_market_signal", _obs("bdvm_market_signal", "player:1", "STRONG_BUY")),
        ]
    )
    player = _player(payload, "player:1")
    assert {s["emitter"] for s in player["signals"]} == {"terminal_signal", "bdvm_market_signal"}
    assert player["collapsed"] == []
    assert player["agreement"]["buy"]["independent"] is False
    assert "value_market_sources" in player["agreement"]["buy"]["sharedAncestry"]


def test_consensus_edge_and_bdvm_agreement_is_not_independent():
    """CE's mispricing and BDVM's gap both read KTC Market / idpTradeCalc."""
    payload = rec.reconcile(
        [
            _run("consensus_edge", _obs("consensus_edge", "player:1", "Buy")),
            _run("bdvm_market_signal", _obs("bdvm_market_signal", "player:1", "BUY")),
        ]
    )
    agreement = _player(payload, "player:1")["agreement"]["buy"]
    assert agreement["independent"] is False
    assert "value_market_sources" in agreement["sharedAncestry"]


def test_lineage_ancestry_is_transitive_over_the_declared_dag():
    """Ancestry is computed from ONE declared DAG, not per-emitter lists."""
    terminal = rec.lineage_closure(rec.spec_for("terminal_signal").lineage_group)
    assert {"canonical_board", "value_market_sources", "news_feed"} <= terminal
    for spec in rec.EMITTERS:
        assert spec.lineage_group in rec.LINEAGE_PARENTS, spec.emitter_id
    for parents in rec.LINEAGE_PARENTS.values():
        for parent in parents:
            assert parent in rec.LINEAGE_PARENTS, parent
    # Sharp cohort movements share nothing with BDVM's lineage.
    assert rec.lineage_closure("sharp_cohort_movements").isdisjoint(
        rec.lineage_closure("bdvm_fundamental_vs_market")
    )


def test_agreement_with_shared_ancestry_is_published_as_not_independent():
    """Terminal and Consensus Edge both descend from the canonical board."""
    payload = rec.reconcile(
        [
            _run("terminal_signal", _obs("terminal_signal", "player:1", "BUY")),
            _run("consensus_edge", _obs("consensus_edge", "player:1", "Buy")),
        ]
    )
    player = _player(payload, "player:1")
    assert len(player["signals"]) == 2  # different questions — both kept
    agreement = player["agreement"]["buy"]
    assert agreement["independent"] is False
    assert "canonical_board" in agreement["sharedAncestry"]


# ── conflict ─────────────────────────────────────────────────────────────


def test_buy_and_sell_from_different_domains_is_a_labelled_conflict():
    payload = rec.reconcile(
        [
            _run("terminal_signal", _obs("terminal_signal", "player:1", "SELL")),
            _run("bdvm_market_signal", _obs("bdvm_market_signal", "player:1", "BUY")),
        ]
    )
    player = _player(payload, "player:1")
    assert player["state"] == rec.STATE_CONFLICT
    conflict = player["conflict"]
    assert [r["emitter"] for r in conflict["buy"]] == ["bdvm_market_signal"]
    assert [r["emitter"] for r in conflict["sell"]] == ["terminal_signal"]
    assert conflict["crossDomain"] is True
    assert conflict["sameLineage"] is False
    assert conflict["resolution"] == "not_resolved_by_reconciler"
    # Never averaged: both verdicts survive with their own labels.
    assert {s["nativeLabel"] for s in player["signals"]} == {"SELL", "BUY"}
    assert payload["counts"]["conflicts"] == 1


def test_same_lineage_opposite_directions_conflict_rather_than_collapse():
    payload = rec.reconcile(
        [
            _run("terminal_signal", _obs("terminal_signal", "player:1", "BUY")),
            _run("signal_alerts", _obs("signal_alerts", "player:1", "SELL")),
        ]
    )
    player = _player(payload, "player:1")
    assert player["state"] == rec.STATE_CONFLICT
    assert player["conflict"]["sameLineage"] is True
    assert player["collapsed"] == []


def test_non_directional_labels_never_manufacture_a_conflict_or_a_direction():
    payload = rec.reconcile(
        [
            _run("terminal_signal", _obs("terminal_signal", "player:1", "RISK")),
            _run("bdvm_market_signal", _obs("bdvm_market_signal", "player:1", "HOLD")),
            _run("consensus_edge", _obs("consensus_edge", "player:1", "Insufficient Evidence")),
        ]
    )
    player = _player(payload, "player:1")
    assert player["state"] == rec.STATE_NONE
    assert {s["direction"] for s in player["signals"]} == {rec.CAUTION, rec.HOLD, rec.REFUSAL}


def test_an_unlisted_label_is_unmapped_not_guessed():
    assert rec.direction_for("terminal_signal", "STRONG_BUY_NEW") == rec.UNMAPPED
    assert rec.direction_for("sharp_market", None) == rec.UNLABELLED


# ── missing is never zero ────────────────────────────────────────────────


def test_an_emitter_that_did_not_run_is_unobserved_not_neutral():
    payload = rec.reconcile(
        [
            _run("terminal_signal", _obs("terminal_signal", "player:1", "BUY")),
            rec.unobserved("bdvm_market_signal", "feature_disabled:bdvm_engine"),
        ]
    )
    player = _player(payload, "player:1")
    # consensus_edge and sharp_market were never asked: also unobserved.
    assert player["emittersUnobserved"] == [
        "bdvm_market_signal",
        "consensus_edge",
        "sharp_market",
    ]
    assert player["state"] == rec.STATE_BUY_ONLY
    assert [s["emitter"] for s in player["signals"]] == ["terminal_signal"]
    by_id = {e["emitterId"]: e for e in payload["emitters"]}
    assert by_id["bdvm_market_signal"]["state"] == rec.UNOBSERVED
    assert by_id["bdvm_market_signal"]["reason"] == "feature_disabled:bdvm_engine"
    assert by_id["consensus_edge"]["reason"] == "not_run"
    assert by_id["bdvm_market_signal"]["observationCount"] == 0


def test_a_player_no_emitter_spoke_about_is_not_a_hold():
    payload = rec.reconcile(
        [_run("terminal_signal", _obs("terminal_signal", "player:1", "BUY"))],
        player_keys=["player:1", "player:2"],
    )
    silent = _player(payload, "player:2")
    assert silent["signals"] == []
    assert silent["state"] == rec.STATE_NONE
    assert silent["emittersSilent"] == ["terminal_signal"]


def test_restatement_and_out_of_scope_emitters_are_declared_not_silently_absent():
    by_id = {e["emitterId"]: e for e in rec.reconcile([])["emitters"]}
    assert by_id["signal_alerts"]["state"] == rec.RESTATEMENT
    assert by_id["signal_alerts"]["restates"] == "terminal_signal"
    assert by_id["trade_finder"]["state"] == rec.OUT_OF_SCOPE
    assert by_id["terminal_signal"]["state"] == rec.UNOBSERVED


# ── withheld precedence ──────────────────────────────────────────────────


def test_canonical_quarantine_withholds_without_dropping_the_other_verdicts():
    payload = rec.reconcile(
        [_run("terminal_signal", _obs("terminal_signal", "player:1", "BUY"))],
        quarantined={"player:1": "blend_integrity_violation"},
    )
    player = _player(payload, "player:1")
    assert player["state"] == rec.STATE_WITHHELD
    assert player["withheldBy"] == [
        {"source": "canonical_quarantine", "reason": "blend_integrity_violation"}
    ]
    assert [s["nativeLabel"] for s in player["signals"]] == ["BUY"]


def test_consensus_edge_withheld_beats_a_conflict():
    payload = rec.reconcile(
        [
            _run("terminal_signal", _obs("terminal_signal", "player:1", "SELL")),
            _run("bdvm_market_signal", _obs("bdvm_market_signal", "player:1", "BUY")),
            _run(
                "consensus_edge",
                _obs("consensus_edge", "player:1", "Withheld", reason="identity quarantined"),
            ),
        ]
    )
    player = _player(payload, "player:1")
    assert player["state"] == rec.STATE_WITHHELD
    assert player["withheldBy"] == [{"source": "consensus_edge", "reason": "identity quarantined"}]
    # The conflict is still reported underneath, not erased.
    assert player["conflict"] is not None
    assert len(player["signals"]) == 3


# ── refusals ─────────────────────────────────────────────────────────────


def test_a_duplicate_run_for_one_emitter_is_refused():
    with pytest.raises(ValueError, match="duplicate run"):
        rec.reconcile([_run("terminal_signal"), _run("terminal_signal")])


def test_an_unregistered_emitter_is_refused():
    with pytest.raises(ValueError, match="unregistered"):
        rec.reconcile([_run("made_up_emitter")])


def test_unobserved_run_cannot_carry_observations():
    with pytest.raises(ValueError, match="carries observations"):
        rec.reconcile(
            [
                _run(
                    "terminal_signal",
                    _obs("terminal_signal", "player:1", "BUY"),
                    state=rec.UNOBSERVED,
                )
            ]
        )


# ── structural: no blend, no weights ─────────────────────────────────────

_FORBIDDEN_CALLS = {"sum", "mean", "median", "fsum", "fmean", "average", "prod"}


def _module_tree(rel: str) -> ast.Module:
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def test_reconciler_contains_no_arithmetic_and_no_weights():
    """A blend needs arithmetic; the synthesis owner has none at all.

    Any ``+ - * / // % **`` (or augmented form) here would be the first
    step toward scoring the emitters against each other, which is an owner
    methodology decision this unit is not authorised to make.
    """
    tree = _module_tree("src/signals/reconciler.py")
    # ``X | None`` in a type annotation is a BinOp too; annotations are not
    # computation, so their subtrees are excluded.
    annotation_nodes = set()
    for node in ast.walk(tree):
        for ann in (
            getattr(node, "annotation", None),
            getattr(node, "returns", None),
        ):
            if isinstance(ann, ast.AST):
                annotation_nodes.update(id(sub) for sub in ast.walk(ann))
    offenders = []
    for node in ast.walk(tree):
        if id(node) in annotation_nodes:
            continue
        if isinstance(node, (ast.BinOp, ast.AugAssign)):
            offenders.append(f"arithmetic at line {node.lineno}")
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name in _FORBIDDEN_CALLS:
                offenders.append(f"{name}() at line {node.lineno}")
        if isinstance(node, ast.Import | ast.ImportFrom):
            mod = getattr(node, "module", None) or ""
            names = [a.name for a in node.names]
            if "statistics" in (mod, *names) or "numpy" in (mod, *names):
                offenders.append(f"numeric import at line {node.lineno}")
        identifier = None
        if isinstance(node, ast.Name):
            identifier = node.id
        elif isinstance(node, ast.Attribute):
            identifier = node.attr
        elif isinstance(node, ast.arg):
            identifier = node.arg
        elif isinstance(node, ast.FunctionDef):
            identifier = node.name
        if identifier and ("weight" in identifier.lower() or "score" in identifier.lower()):
            offenders.append(f"identifier {identifier!r} at line {node.lineno}")
    assert offenders == []


def test_collectors_compute_no_cross_emitter_number():
    """The adapters translate and place; they do not multiply or divide."""
    tree = _module_tree("src/signals/collect.py")
    offenders = [
        f"line {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, (ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod))
    ]
    assert offenders == []


def test_reconciled_player_carries_no_number_of_its_own():
    """Every number on a player is an emitter's own, under ``evidence``/``freshness``."""
    payload = rec.reconcile(
        [
            _run(
                "bdvm_market_signal",
                _obs("bdvm_market_signal", "player:1", "BUY", evidence={"gap": 812.0}),
                freshness={"state": "fresh", "hoursStale": 1.5},
            ),
            _run("terminal_signal", _obs("terminal_signal", "player:1", "SELL")),
        ]
    )
    player = _player(payload, "player:1")

    def _numbers(value, path):
        if isinstance(value, bool):
            return []
        if isinstance(value, int | float):
            return [path]
        if isinstance(value, dict):
            out = []
            for k, v in value.items():
                if k in ("evidence", "freshness"):
                    continue
                out.extend(_numbers(v, f"{path}.{k}"))
            return out
        if isinstance(value, list):
            return [p for i, v in enumerate(value) for p in _numbers(v, f"{path}[{i}]")]
        return []

    assert _numbers(player, "player") == []


# ── scope and owner refusals are not silence ─────────────────────────────


def test_a_player_outside_an_emitters_evaluated_scope_is_out_of_scope_not_silent():
    run = rec.EmitterRun(
        emitter_id="terminal_signal",
        state=rec.OBSERVED,
        observations=(_obs("terminal_signal", "player:1", "BUY"),),
        covered_keys=frozenset({"player:1"}),
    )
    payload = rec.reconcile([run], player_keys=["player:1", "player:2"])
    off_roster = _player(payload, "player:2")
    assert off_roster["emittersOutOfScope"] == ["terminal_signal"]
    assert off_roster["emittersSilent"] == []


def test_an_owner_refusal_is_declined_with_the_owners_reason():
    run = rec.EmitterRun(
        emitter_id="bdvm_market_signal",
        state=rec.OBSERVED,
        declined={"player:2": "no_projection"},
    )
    payload = rec.reconcile([run], player_keys=["player:2", "player:3"])
    assert _player(payload, "player:2")["emittersDeclined"] == [
        {"emitter": "bdvm_market_signal", "reason": "no_projection"}
    ]
    assert _player(payload, "player:2")["emittersSilent"] == []
    # Evaluated, not refused, said nothing: that one IS silent.
    assert _player(payload, "player:3")["emittersSilent"] == ["bdvm_market_signal"]
