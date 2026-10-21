"""Outlier-integrity V2.1: the EXPLORATORY / DEV evaluator (prereg §3.6, §7, §8, §10).

``docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md`` registers what V2.1
is evaluated on and how.  This module executes the parts that may run on DEV
boards only (``outlier_integrity_v21/manifests/POPULATIONS.json`` DEV, the 79
boards of V2's E_BASELINE + E_DEV).  It never reads an R pin, a SPENT board or
an archive added after T0 (the sealed held-out set): the driver
(``scripts/oiv21_dev.py``) refuses any board outside DEV.

It only BUILDS archived boards through the inherited rebuild procedure
(``scripts/joint_filter_shadow.py`` via ``oiv2_replay``) and READS what each
build stamped.  It changes no vote, weight, threshold or value of the served
pipeline.  Replay-only seams used:

* ``source_integrity.history_override`` (the history lane),
* ``source_integrity.load_thresholds`` patched for exploratory selection
  builds (never written to a config file),
* ``data_contract._ADVERSARIAL_VOTE_TRANSFORM`` (AD1 / AD4 / AD2-as-registered
  / INJ-DUP post-pricing injections),
* input-level injections: a COPY of the archived CSV tree / payload is edited
  (AD2-ID, AD2-N, AD3 registered seam, INJ-SEG, H2-SYN, AD2-SUR's synthetic
  U2 sidecar) -- the archive itself is never touched,
* ``outlier_policy.LayerCContext.assess`` replaced for the V2-RPC comparator
  only (a scientific comparator, never a candidate; prereg §2).

Missing is never zero: a row or vote a build did not produce is absent from a
record, never 0.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from src.api import data_contract as dc
from src.api import outlier_policy as op
from src.api import source_integrity as si
from src.api import value_replay as vr
from src.robust_filter_shadow import oiv2_gates as G
from src.robust_filter_shadow import oiv2_replay as RP

SCHEMA = "oiv21-dev/v1"
PREREG = "docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md"
REPO_ROOT = Path(__file__).resolve().parents[2]
POPULATIONS = REPO_ROOT / "docs" / "sources" / "outlier_integrity_v21" / "manifests"

#: Registered seeds (prereg §3.6 selection, §7 gates).
SELECTION_SEED = 20261021
GATE_SEED = 2034

#: V2.1 primary configuration (prereg §3.8): the V2 flags plus the V2.1
#: sub-flag and the record-only history flag.
V21_EXTRA: dict[str, bool] = {"outlier_integrity_v21": True, "source_rank_history_record": True}
_RESTORED = {"dlf_offense_only_vote": False}
_D4 = {"dlf_values_rank_hill_vote": True}


@dataclasses.dataclass(frozen=True)
class Cfg:
    """One build configuration.

    ``kind``: ``none`` (no per-row filter), ``inc`` (incumbent), ``v1``,
    ``v2`` (V2 at its frozen thresholds, the V2.1 sub-flag OFF), ``v21``
    (the candidate), ``rpc`` (V2.1 with Layer C replaced, prereg §2).
    ``lane``: which history lane an ARRIVING build reads (``v21`` / ``v2`` /
    ``rpc``); ``None`` for the history-free configurations.
    """

    name: str
    kind: str
    extra: Mapping[str, bool] = dataclasses.field(default_factory=dict)
    lane: str | None = None
    label: str = ""

    @property
    def v2_master(self) -> bool:
        return self.kind in ("v2", "v21", "rpc")

    @property
    def v21(self) -> bool:
        return self.kind in ("v21", "rpc")


CFGS: dict[str, Cfg] = {
    c.name: c
    for c in (
        Cfg("none", "none", {}, None, "no per-row filter (materiality reference)"),
        Cfg("inc", "inc", {}, None, "incumbent (board A / A')"),
        Cfg("v1", "v1", {"outlier_disagreement_policy": True}, None, "V1"),
        Cfg("v2", "v2", {}, "v2", "V2 at its frozen thresholds (reported comparator)"),
        Cfg("v21", "v21", dict(V21_EXTRA), "v21", "V2.1 primary (board D / D')"),
        Cfg("v21d1", "v21", {**V21_EXTRA, "integrity_holds_as_withheld": True}, "v21", "V2.1+D1"),
        Cfg("rpc", "rpc", dict(V21_EXTRA), "rpc", "V2-RPC (required comparator)"),
        Cfg("B", "inc", dict(_RESTORED), None, "B: DLF IDP restored + incumbent"),
        Cfg("C", "v21", {**V21_EXTRA, **_RESTORED}, "v21", "C: DLF IDP restored + V2.1"),
        Cfg("Bp", "inc", dict(_D4), None, "B': D4 on + incumbent"),
        Cfg("Cp", "v21", {**V21_EXTRA, **_D4}, "v21", "C': D4 on + V2.1"),
        Cfg("Bpp", "inc", {**_RESTORED, **_D4}, None, "B'': DLF IDP + D4 + incumbent"),
        Cfg("Cpp", "v21", {**V21_EXTRA, **_RESTORED, **_D4}, "v21", "C'': DLF IDP + D4 + V2.1"),
    )
}


def flags_for(cfg: Cfg) -> dict[str, bool]:
    flags = dict(RP.BASE_PINS)
    for f in RP.V2_FLAGS:
        flags[f] = cfg.v2_master
    flags["outlier_integrity_v21"] = False
    flags.update(cfg.extra)
    return flags


# ── the Sleeper directory snapshot (R4 / R5 / R11) ──────────────────────

_DIRECTORY: list[Path | None] = [None]


def set_directory(path: Path | None) -> None:
    """The identity owner's Sleeper directory snapshot V2.1 builds read
    (``None``: none on the host -- A1 then uses board rows only and says so)."""
    _DIRECTORY[0] = Path(path) if path is not None else None


@contextlib.contextmanager
def _directory_patch() -> Iterator[None]:
    from src.identity import directory_cache  # noqa: PLC0415

    target = _DIRECTORY[0]
    missing = REPO_ROOT / "data" / "__oiv21_dev_no_directory__.json"
    original = directory_cache.default_directory_path
    directory_cache.default_directory_path = lambda: target if target is not None else missing
    try:
        yield
    finally:
        directory_cache.default_directory_path = original


# ── V2-RPC: reliability-prior per-family error cells (prereg §2) ────────

#: Fixed before any DEV result was read (V2.1 DEVIATIONS V21-D6): the middle
#: of the reliability-prior prototype's grid.  Never selected on DEV.
RPC_Z = 5.0
RPC_DMIN = math.log(2.5)
RPC_CORR = math.log(1.25)
RPC_MIN_N = 25


def rpc_band(value: float) -> str:
    return "b1" if value >= 5000 else "b2" if value >= 2500 else "b3" if value >= 1200 else "b4"


def _scope_of_curve(curve: Sequence[float]) -> str:
    return "idp" if tuple(curve) == tuple(op.scope_curve("idp")) else "offense"


def _residuals(
    votes: Mapping[str, float], curve: Sequence[float], family_of: Callable[[str], str]
) -> dict[str, tuple[float, float, float]]:
    """``{key: (residual, reference value, coordinate)}`` against the
    leave-family-out reference (V1's coordinate and reference)."""
    coords = {k: op.rank_coordinate(v, tuple(curve)) for k, v in votes.items()}
    coords = {k: u for k, u in coords.items() if u is not None}
    vals = {k: float(votes[k]) for k in coords}
    fm = op.family_medians(coords, vals, family_of)
    out = {}
    for k, u in coords.items():
        ref = op.leave_family_out(k, coords, vals, family_of, families=fm)
        if ref is None:
            continue
        out[k] = (u - ref.coordinate, ref.value, u)
    return out


def fit_rpc_model(panels: Sequence[tuple[str, Mapping[str, float]]]) -> dict[str, Any]:
    """Per-family error cells from ``(asset class, {source: vote})`` panels."""
    fam = dc.correlation_group_for
    seg: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for ac, votes in panels:
        curve = op.scope_curve(ac)
        scope = _scope_of_curve(curve)
        for k, (r, refv, _u) in _residuals(votes, curve, lambda s: fam(s) or s).items():
            f = fam(k) or k
            seg[(f, scope, rpc_band(refv))].append(r)
            seg[(f, scope, "*")].append(r)
            seg[("*", scope, "*")].append(r)
    cells = {}
    for key, xs in seg.items():
        if len(xs) < RPC_MIN_N:
            continue
        mu = statistics.median(xs)
        sigma = 1.4826 * statistics.median(abs(x - mu) for x in xs)
        cells["|".join(key)] = {"n": len(xs), "mu": round(mu, 6), "sigma": round(sigma, 6)}
    return {
        "schema": "oiv21-rpc-model/v1",
        "z": RPC_Z,
        "dMin": RPC_DMIN,
        "corr": RPC_CORR,
        "minN": RPC_MIN_N,
        "cells": dict(sorted(cells.items())),
    }


def _rpc_cell(model: Mapping[str, Any], f: str, scope: str, band: str) -> Mapping | None:
    cells = model["cells"]
    for key in (f"{f}|{scope}|{band}", f"{f}|{scope}|*", f"*|{scope}|*"):
        if key in cells:
            return cells[key]
    return None


def rpc_assess_factory(model: Mapping[str, Any]):
    """A drop-in for ``LayerCContext.assess``: guards 2-3 (corroborated
    reference, tau_C) replaced by the family's own error envelope; guards 1
    (>= 3 providers), 4 (persistence, dominance) and 5 (>= 2 surviving
    providers) kept, so the comparison isolates the decision rule."""

    def assess(ctx: op.LayerCContext, pairs, weights=None):  # noqa: ANN001
        keys = [k for k, _v in pairs]
        votes = {k: float(v) for k, v in pairs}
        scope = _scope_of_curve(ctx.curve)
        res = _residuals(votes, ctx.curve, ctx.family_of)
        prov = {k: ctx.provider_of(k) for k in keys}
        coords = {k: t[2] for k, t in res.items()}
        dissent: dict[str, str] = {}
        for k, u in coords.items():
            near = [abs(u - coords[j]) for j in coords if prov[j] != prov[k]]
            if near and min(near) > op.C_CORROBORATION_DISTANCE:
                dissent[k] = op.KEPT_DISSENT
        cands: list[tuple[float, str]] = []
        if len(set(prov.values())) >= op.C_MIN_PROVIDERS:
            w = weights
            if w is None and ctx.weights_for is not None:
                w = ctx.weights_for(keys)
            shares = op._family_shares(keys, w, ctx.family_of)
            confirmed = ctx.persistence_confirmed or (lambda _k, _u: False)
            for k, (r, refv, u) in res.items():
                cell = _rpc_cell(model, ctx.family_of(k), scope, rpc_band(refv))
                if cell is None:
                    continue
                env = max(model["z"] * float(cell["sigma"]), model["dMin"])
                dev = abs(r - float(cell["mu"]))
                if dev <= env:
                    continue
                if any(
                    ctx.family_of(j) != ctx.family_of(k) and abs(coords[j] - u) <= model["corr"]
                    for j in coords
                ):
                    continue
                if confirmed(k, u):
                    continue
                if shares.get(ctx.family_of(k), 0.0) >= op.C_DOMINANT_SHARE:
                    continue
                cands.append((dev / env, k))
        dropped: set[str] = set()
        for _s, k in sorted(cands, reverse=True):
            left = [x for x in keys if x not in dropped and x != k]
            if (
                len({prov[x] for x in left}) < op.C_MIN_SURVIVING_PROVIDERS
                or len({ctx.family_of(x) for x in left}) < 2
            ):
                continue
            dropped.add(k)
        for k in dropped:
            dissent.pop(k, None)
        return op.LayerCVerdict(
            kept=tuple(k for k in keys if k not in dropped),
            dropped=tuple(k for k in keys if k in dropped),
            reasons={k: op.REASON_TAIL for k in sorted(dropped)},
            dissent=dict(sorted(dissent.items())),
            kept_because={},
            details={},
        )

    return assess


# ── builds ──────────────────────────────────────────────────────────────


def _no_filter(pairs, **_kwargs):
    return list(pairs), []


def build(
    raw: Mapping[str, Any],
    root: Any,
    cfg: Cfg | str,
    *,
    history: si.IntegrityHistory | None = None,
    thresholds: si.IntegrityThresholds | None = None,
    transform: Callable[[Mapping[str, Any], str, float], float] | None = None,
    source_overrides: Mapping[str, Any] | None = None,
    rpc_model: Mapping[str, Any] | None = None,
    repairs: si.Repairs | None = None,
) -> dict[str, Any]:
    """One full build.  ``thresholds`` applies to V2.1 builds only (V2 reads
    its own frozen file); ``history`` to builds with the V2 master on."""
    c = CFGS[cfg] if isinstance(cfg, str) else cfg
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
        for name, enabled in sorted(flags_for(c).items()):
            stack.enter_context(vr._flag(name, enabled))
        if c.kind == "none":
            stack.enter_context(vr._patched("_hampel_filter_per_player", _no_filter))
        if c.v2_master:
            stack.enter_context(si.history_override(history))
        if c.v21:
            stack.enter_context(_directory_patch())
            if thresholds is not None:
                stack.enter_context(
                    RP._patched_module(si, "load_thresholds", lambda *_a: thresholds)
                )
            if repairs is not None:
                stack.enter_context(si.repairs_override(repairs))
        if c.kind == "rpc":
            if rpc_model is None:
                raise ValueError("V2-RPC needs its fitted model")
            stack.enter_context(
                RP._patched_module(op.LayerCContext, "assess", rpc_assess_factory(rpc_model))
            )
        stack.enter_context(vr._patched("_ADVERSARIAL_VOTE_TRANSFORM", transform))
        return dc.build_api_data_contract(
            json.loads(json.dumps(raw)),
            source_overrides=dict(source_overrides) if source_overrides else None,
            csv_root=root,
        )


# ── reading a build ─────────────────────────────────────────────────────

#: Integrity statuses that keep the observation voting.
VOTING_STATUSES = frozenset({None, si.STATUS_VOTING, si.STATUS_RELEASED_BY_CAP})
V21_LAYER_STATUSES = frozenset(
    {
        si.STATUS_REFUSED,
        si.STATUS_WITHHELD,
        si.STATUS_QUARANTINED,
        si.STATUS_HELD,
        si.STATUS_REJECTED_TAIL,
    }
)


def exclusion_of(row: Mapping[str, Any] | None, source: str) -> str | None:
    """Why ``source``'s observation on ``row`` did not count, or ``None``.

    Like ``oiv2_gates.exclusion_of`` but a V2.1 ``released_by_cap`` vote is
    counted as VOTING (it votes, prereg §3.4 P-3), and a Layer A refusal that
    left the vote slot (R6 finalize) is still found."""
    if not row:
        return "row_absent"
    m = (row.get("sourceRankMeta") or {}).get(source)
    if not isinstance(m, Mapping):
        blk = (row.get("sourceIntegrity") or {}).get(source)
        if isinstance(blk, Mapping) and blk.get("status") not in VOTING_STATUSES:
            return str(blk.get("primaryReason") or blk.get("status"))
        return "observation_absent"
    integ = m.get("integrity")
    if isinstance(integ, Mapping) and integ.get("status") not in VOTING_STATUSES:
        return str(integ.get("primaryReason") or integ.get("status"))
    if m.get("excludedReason"):
        return str(m["excludedReason"])
    if m.get("hampelDropped") or source in (row.get("droppedSources") or []):
        return "filter_dropped"
    return None


def v21_layer_drop(row: Mapping[str, Any] | None, source: str) -> str | None:
    """The V2.1 layer that excluded the observation (prereg §7.4
    measurement), or ``None`` when no V2.1 layer did.  Policy holds,
    freshness exclusions, the declared-range check and non-positive values are
    not V2.1's and are not counted."""
    if not row:
        return None
    m = (row.get("sourceRankMeta") or {}).get(source)
    integ = m.get("integrity") if isinstance(m, Mapping) else None
    if not isinstance(integ, Mapping):
        integ = (row.get("sourceIntegrity") or {}).get(source)
    if isinstance(integ, Mapping) and integ.get("status") in V21_LAYER_STATUSES:
        return f"{integ.get('status')}:{integ.get('primaryReason')}"
    if isinstance(m, Mapping) and not m.get("excludedReason"):
        if m.get("hampelDropped") or source in (row.get("droppedSources") or []):
            return "rejected_tail:filter_slot"
    return None


def rows_by_name(contract: Mapping[str, Any]) -> dict[str, dict]:
    return G.rows_by_name(contract)


def value_of(row: Mapping[str, Any] | None) -> float | None:
    return G._value(row)


def log_move(a: float | None, b: float | None) -> float | None:
    return G._log_move(a, b)


def observations(row: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Every observation the row carries: ``{source: {v, st, layer}}``."""
    out: dict[str, dict[str, Any]] = {}
    for s in sorted(set(row.get("sourceRankMeta") or {}) | set(row.get("sourceIntegrity") or {})):
        m = (row.get("sourceRankMeta") or {}).get(s)
        v = RP._num(m.get("valueContribution")) if isinstance(m, Mapping) else None
        out[s] = {"v": v, "ex": exclusion_of(row, s), "layer": v21_layer_drop(row, s)}
    return out


def board_counts(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Votes, V2.1-layer exclusions and board-level hard findings of a build."""
    votes = excl = 0
    by_layer: Counter = Counter()
    by_source: Counter = Counter()
    for r in contract.get("playersArray") or []:
        if r.get("assetClass") == "pick":
            continue
        for s in set(r.get("sourceRankMeta") or {}) | set(r.get("sourceIntegrity") or {}):
            m = (r.get("sourceRankMeta") or {}).get(s)
            # A V2.1 exclusion also stamps ``excludedReason``: decide the
            # layer FIRST, and skip only exclusions V2.1 does not own.
            lay = v21_layer_drop(r, s)
            if lay is None and isinstance(m, Mapping) and m.get("excludedReason"):
                continue
            if lay is None and not (
                isinstance(m, Mapping) and (RP._num(m.get("valueContribution")) or 0) > 0
            ):
                continue
            votes += 1
            if lay is not None:
                excl += 1
                by_layer[lay] += 1
                by_source[s] += 1
    integ = contract.get("sourceIntegrity") or {}
    hard = [f for f in integ.get("findings") or [] if f.get("hard")]
    return {
        "observations": votes,
        "v21Excluded": excl,
        "rate": round(excl / votes, 6) if votes else None,
        "byLayer": dict(sorted(by_layer.items())),
        "bySource": dict(sorted(by_source.items())),
        "hardFindings": [
            {k: f.get(k) for k in ("source", "scope", "assetClass", "pos", "reason")} for f in hard
        ],
        "sourceQuarantines": dict(integ.get("sourceQuarantines") or {}),
        "segmentQuarantines": dict(integ.get("segmentQuarantines") or {}),
    }


# ── history lane ────────────────────────────────────────────────────────


def advance(history, contract, degraded: Sequence[str]):
    drop = RP.degraded_filter(degraded or [])
    return si.advance(history, RP.board_record_for_history(contract, drop))


def history_json(history) -> dict[str, Any] | None:
    return None if history is None else history.to_json()


def history_from(blob: Mapping[str, Any] | None):
    return None if blob is None else si.IntegrityHistory.from_json(blob)


# ── B2 provenance pairs recorder (epsilon selection under R14) ──────────


class ProvenanceRecorder:
    """Records each B2 call's per-group log ratios (both copies >= 100), so
    the epsilon grid can be evaluated on the R14 reading at every grid
    point, not only at the epsilon the build ran with.  Calls the original
    unchanged."""

    def __init__(self) -> None:
        self.calls: dict[str, dict[str, list[float]]] = {}
        self._source: list[str] = []

    @contextlib.contextmanager
    def active(self) -> Iterator[ProvenanceRecorder]:
        orig_guard = dc._apply_payload_provenance_guard
        orig_check = si.provenance_check
        rec = self

        def guard(source_key, payload_rows, integrity):  # noqa: ANN001
            rec._source.append(str(source_key))
            try:
                return orig_guard(source_key, payload_rows, integrity)
            finally:
                rec._source.pop()

        def check(pairs, **kw):  # noqa: ANN001
            src = rec._source[-1] if rec._source else "?"
            groups: dict[str, list[float]] = defaultdict(list)
            for p in pairs:
                if p.payload >= si.B2_MIN_VALUE and p.csv >= si.B2_MIN_VALUE:
                    groups[p.group].append(round(math.log(p.payload / p.csv), 6))
            rec.calls[src] = {g: sorted(v) for g, v in groups.items()}
            return orig_check(pairs, **kw)

        dc._apply_payload_provenance_guard = guard
        si.provenance_check = check
        try:
            yield self
        finally:
            dc._apply_payload_provenance_guard = orig_guard
            si.provenance_check = orig_check


def b2_board_proof(groups: Mapping[str, Sequence[float]], eps: float) -> list[str]:
    """``provenance_check``'s board-proof groups on recorded log ratios under
    the R14 reading at ``eps`` (same function, same rule)."""
    pairs = []
    i = 0
    for g, ds in groups.items():
        for d in ds:
            pairs.append(si.ProvenancePair(i, g, 1000.0 * math.exp(d), 1000.0))
            i += 1
    res = si.provenance_check(pairs, epsilon=eps, nonzero_sign_share=True)
    return list(res.proven_groups) if res.board_proof else []


# ── selection (prereg §3.6) ─────────────────────────────────────────────

EPS_GRID = (0.01, 0.02, 0.05)
N_MIN_GRID = (10, 20, 30)
RHO_GRID = (0.0, 0.3)
TAU_GROSS_GRID = (("ln 3", math.log(3.0)), ("ln 4", math.log(4.0)))
KC_GRID = (4.0, 6.0, 8.0)
TAUC_GRID = (("ln 4", math.log(4.0)), ("ln 5", math.log(5.0)), ("ln 6", math.log(6.0)))
H3_H4_BOARDS = ("dynasty_export_20260803_235610.zip", "dynasty_export_20260806_150742.zip")
FALSE_HOLD_LIMIT = 0.005
MIN_TAU_C_PAIRS = 20


def select_epsilon(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    proofs: dict[str, list] = {str(e): [] for e in EPS_GRID}
    boards = 0
    for rec in records:
        if rec["board"]["archive"] in H3_H4_BOARDS:
            continue
        boards += 1
        for source, groups in sorted((rec.get("provenancePairs") or {}).items()):
            for e in EPS_GRID:
                hit = b2_board_proof(groups, e)
                if hit:
                    proofs[str(e)].append(
                        {"board": rec["board"]["archive"], "source": source, "groups": hit}
                    )
    feasible = [e for e in EPS_GRID if not proofs[str(e)]]
    return {
        "selected": min(feasible) if feasible else None,
        "feasible": bool(feasible),
        "boards": boards,
        "boardProofCountsByGrid": {k: len(v) for k, v in proofs.items()},
        "boardProofsByGrid": {k: v[:50] for k, v in proofs.items()},
    }


def select_b3(records: Sequence[Mapping[str, Any]], tau_board: Mapping[str, float]) -> dict:
    """The registered B3b grid on the SERVED rule (R3): the selector's
    ``_hard_findings(v21=True)`` over each board's and each injection's own
    stamped segment statistics and served proof sources, the window replayed
    chronologically from DEV boards only (ARRIVING, DEV history)."""
    from src.robust_filter_shadow import oiv2_select as S  # noqa: PLC0415

    settings = []
    for n_min in N_MIN_GRID:
        for rho in RHO_GRID:
            for lab, tg in TAU_GROSS_GRID:
                window: dict[str, list[float]] = {}
                clean_flags: list[dict] = []
                inj_total = inj_caught = 0
                missed: list[dict] = []
                for rec in records:
                    b = rec["builds"]["v21"]
                    stats = (b.get("sourceIntegrity") or {}).get("segmentStats") or {}
                    proof = {str(x) for x in (b.get("proofSources") or [])}
                    kw = dict(n_min=n_min, rho_min=rho, tau_gross=tg, tau_board=tau_board)
                    hard = S._hard_findings(stats, window, proof=proof, v21=True, **kw)
                    if S.is_clean_dev(rec):
                        for k, why in sorted(hard.items()):
                            clean_flags.append(
                                {"board": rec["board"]["archive"], "segment": k, "rule": why}
                            )
                    for inj in rec.get("injections") or []:
                        if not inj.get("rows"):
                            continue
                        inj_total += 1
                        ip = {str(x) for x in (inj.get("proofSources") or [])}
                        ih = S._hard_findings(
                            inj.get("segmentStats") or {}, window, proof=ip, v21=True, **kw
                        )
                        if inj.get("sourceQuarantine") or ih:
                            inj_caught += 1
                        else:
                            missed.append(
                                {
                                    "board": rec["board"]["archive"],
                                    "source": inj["source"],
                                    "assetClass": inj["assetClass"],
                                    "kind": inj["kind"],
                                }
                            )
                    S._advance(window, {"board": rec["board"], "builds": {"v2": b}}, hard)
                by_kind: Counter = Counter(m["kind"] for m in missed)
                settings.append(
                    {
                        "n_min": n_min,
                        "rho_min": rho,
                        "tau_gross": lab,
                        "cleanHardFlags": len(clean_flags),
                        "cleanHardFlagSample": clean_flags[:30],
                        "injections": inj_total,
                        "injectionsCaught": inj_caught,
                        "injectionCatchRate": round(inj_caught / inj_total, 4)
                        if inj_total
                        else None,
                        "missedByKind": dict(sorted(by_kind.items())),
                        "missedSample": missed[:30],
                        "feasible": not clean_flags and inj_total > 0 and inj_caught == inj_total,
                    }
                )
    feasible = [s for s in settings if s["feasible"]]
    if feasible:
        best = sorted(
            feasible,
            key=lambda s: (-s["n_min"], s["rho_min"], -dict(TAU_GROSS_GRID)[s["tau_gross"]]),
        )[0]
        status = "SELECTED"
        selected = {k: best[k] for k in ("n_min", "rho_min", "tau_gross")}
    else:
        status = "FAILED_SELECTION"
        selected = None
    return {"status": status, "selected": selected, "settings": settings}


def tau_c_mad(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``{source: {band: MAD}}`` of the source's own CONTENT-DISTINCT (P-1)
    same-player Δu: a pair counts only between two consecutive accepted
    observations whose source dataset content hashes differ."""
    from src.robust_filter_shadow import oiv2_select as S  # noqa: PLC0415

    prev: dict[str, tuple[str, float]] = {}
    deltas: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for rec in records:
        b = rec["builds"]["v21"]
        hashes = b.get("hashes") or {}
        for row in b["rows"].values():
            pk, ac = row.get("pk"), row.get("ac")
            if not pk or ac == "pick":
                continue
            for source, (val, _w, state) in (row.get("obs") or {}).items():
                if val is None or val <= 0 or state != "voting":
                    continue
                if S._excluded(rec, source):
                    continue
                h = hashes.get(source)
                u = si.vote_coordinate(val, ac)
                if u is None or h is None:
                    continue
                key = f"{source}|{pk}"
                got = prev.get(key)
                if got is not None and got[0] != h:
                    deltas[source][si.depth_band(got[1])].append(u - got[1])
                if got is None or got[0] != h:
                    prev[key] = (h, u)
    out: dict[str, dict[str, Any]] = {}
    for source, bands in sorted(deltas.items()):
        pooled = [d for v in bands.values() for d in v]
        if len(pooled) < MIN_TAU_C_PAIRS:
            continue
        med = statistics.median(pooled)
        pooled_mad = statistics.median(abs(d - med) for d in pooled)
        cells = {}
        for band in sorted(bands):
            v = bands[band]
            if len(v) >= MIN_TAU_C_PAIRS:
                m = statistics.median(v)
                cells[band] = {"mad": statistics.median(abs(d - m) for d in v), "n": len(v)}
            else:
                cells[band] = {"mad": pooled_mad, "n": len(v), "pooled": True}
        for _edge, band in si.B4_BANDS:
            cells.setdefault(band, {"mad": pooled_mad, "n": 0, "pooled": True})
        out[source] = {"pooledMad": pooled_mad, "pooledN": len(pooled), "bands": cells}
    return out


def tau_c_table(mads: Mapping[str, Any], k_c: float) -> dict[str, dict[str, float]]:
    return {
        source: {
            band: round(max(si.B4_MIN_TAU_C, k_c * 1.4826 * float(c["mad"])), 6)
            for band, c in blk["bands"].items()
        }
        for source, blk in mads.items()
    }


def thresholds_from(sel: Mapping[str, Any], **over: Any) -> si.IntegrityThresholds:
    """An ``IntegrityThresholds`` from a (partial) selection; unspecified
    fields keep V2's frozen values (``load_v21_thresholds`` semantics:
    ``tau_age`` is R5's fixed 1.0 year either way)."""
    from src.identity.resolution import V21_TAU_AGE  # noqa: PLC0415

    base = dataclasses.replace(si.load_thresholds(), tau_age=V21_TAU_AGE)
    vals: dict[str, Any] = {"status": "oiv21_dev_exploratory_not_frozen"}
    if sel.get("epsilon_b2") is not None:
        vals["epsilon_b2"] = float(sel["epsilon_b2"])
    if sel.get("tau_board"):
        vals["tau_board"] = dict(sel["tau_board"])
    b3 = sel.get("b3") or {}
    if b3:
        vals["n_min"] = int(b3["n_min"])
        vals["rho_min"] = float(b3["rho_min"])
        vals["tau_gross"] = math.log(float(str(b3["tau_gross"])[3:]))
    if sel.get("k_c") is not None:
        vals["k_c"] = float(sel["k_c"])
    if sel.get("tau_c"):
        vals["tau_c"] = {k: dict(v) for k, v in sel["tau_c"].items()}
    if sel.get("tau_C"):
        vals["tau_c_big"] = math.log(float(str(sel["tau_C"])[3:]))
    vals.update(over)
    return dataclasses.replace(base, **vals)


# ── gate cases (prereg §7.2; V2's construction, V2.1 exclusion reading) ─


def plan_cases(
    clean: Mapping[str, Mapping[str, Any]],
    *,
    seed: int,
    allowed_sources: Sequence[str] | None = None,
    gates: Sequence[str] = ("AD1a", "AD1b", "AD1c", "AD1d", "AD2", "AD4"),
) -> list[G.Case]:
    """V2's case construction (``oiv2_gates.plan_cases``) with the V2.1
    exclusion reading.  ``clean`` maps ``none`` / ``inc`` / ``cand`` to clean
    contracts.  ``allowed_sources`` restricts the corrupted source (the
    selection's non-registered sources, prereg §3.6)."""
    import random  # noqa: PLC0415

    rng = random.Random(seed)
    boards = {c: rows_by_name(clean[c]) for c in ("none", "inc", "cand")}
    rank_of = {
        n: r["canonicalConsensusRank"]
        for n, r in boards["inc"].items()
        if isinstance(r.get("canonicalConsensusRank"), int)
    }
    allowed = set(allowed_sources) if allowed_sources is not None else None
    eligible: dict[str, dict] = {}
    for n in sorted(boards["none"]):
        r = boards["none"][n]
        if r.get("assetClass") == "pick" or value_of(r) is None:
            continue
        if any(n not in boards[c] for c in boards):
            continue
        votes = G.voting_votes(r)
        votes = {
            k: v
            for k, v in votes.items()
            if exclusion_of(boards["none"][n], k) is None
            and exclusion_of(boards["cand"][n], k) is None
            and exclusion_of(boards["inc"][n], k) in (None, "filter_dropped")
        }
        if len({G.family_of(k) for k in votes}) < 3:
            continue
        eligible[n] = {"row": r, "votes": votes}
    names = sorted(eligible)
    by_source_rows: dict[str, list[str]] = defaultdict(list)
    for n in names:
        for s in eligible[n]["votes"]:
            by_source_rows[s].append(n)
    cases: list[G.Case] = []
    for n in names:
        r, votes = eligible[n]["row"], eligible[n]["votes"]
        pool_src = sorted(votes) if allowed is None else sorted(s for s in votes if s in allowed)
        if not pool_src:
            continue
        band = G._band(len({G.family_of(k) for k in votes}))
        ac = str(r.get("assetClass") or "")
        pg = G.pos_group(r)
        for gate in ("AD1a", "AD1b", "AD1c", "AD1d"):
            s = rng.choice(pool_src)
            bad = min(9999.0, max(1.0, votes[s] * G.GATES[gate]["factor"]))
            cases.append(G.Case(gate, n, s, votes[s], bad, (s, ac, pg), band))
        s = rng.choice(pool_src)
        rk = rank_of.get(n)
        pool = [
            o
            for o in by_source_rows[s]
            if o != n and rk is not None and o in rank_of and abs(rank_of[o] - rk) >= 100
        ]
        if pool:
            other = rng.choice(sorted(pool))
            bad = eligible[other]["votes"][s]
            cases.append(G.Case("AD2", n, s, votes[s], bad, (s, ac, pg), band, swapped_from=other))
        if rk is not None and 150 <= rk <= 400:
            s = rng.choice(pool_src)
            cases.append(G.Case("AD4", n, s, votes[s], 9000.0, (s, ac, pg), band))
    return [c for c in cases if c.gate in gates]


@dataclasses.dataclass
class Spec:
    """One configuration of a gate run: what to build and with which lane."""

    label: str
    cfg: str
    history: Any = None
    thresholds: si.IntegrityThresholds | None = None
    rpc_model: Mapping[str, Any] | None = None

    def build(self, raw, root, transform=None, *, history=dataclasses.MISSING, **kw):
        h = self.history if history is dataclasses.MISSING else history
        return build(
            raw,
            root,
            self.cfg,
            history=h,
            thresholds=self.thresholds,
            transform=transform,
            rpc_model=self.rpc_model,
            **kw,
        )


def run_value_cases(
    raw: Mapping[str, Any],
    root: Any,
    specs: Sequence[Spec],
    clean: Mapping[str, Mapping[str, Any]],
    cases: Sequence[G.Case],
    *,
    progress: Callable[[str], None] | None = None,
    history_for_batch: Callable[[Spec, list[G.Case]], Any] | None = None,
) -> tuple[list[dict], dict]:
    """Every case through every spec, batched (V2's batching).  ``clean``:
    label -> clean contract (same lane).  ``history_for_batch`` (PERSISTENT)
    supplies a per-batch lane for a spec, else the spec's own lane."""
    clean_rows = {s.label: rows_by_name(clean[s.label]) for s in specs}
    results: list[dict] = []
    contamination: dict[str, list[float]] = {s.label: [] for s in specs}
    batches = G.batch_cases(cases)
    for bi, batch in enumerate(batches):
        overrides = {(c.row, c.source): c.bad for c in batch}
        tf = G.transform_for(overrides)
        case_rows = {c.row for c in batch}
        got: dict[str, dict] = {}
        for s in specs:
            kw = {}
            if history_for_batch is not None:
                h = history_for_batch(s, batch)
                if h is not dataclasses.MISSING:
                    kw["history"] = h
            got[s.label] = rows_by_name(s.build(raw, root, tf, **kw))
            worst = 0.0
            for n, r in got[s.label].items():
                if n in case_rows or r.get("assetClass") == "pick":
                    continue
                mv = log_move(value_of(clean_rows[s.label].get(n)), value_of(r))
                if mv is not None and mv > worst:
                    worst = mv
            contamination[s.label].append(worst)
        for c in batch:
            item = {
                "gate": c.gate,
                "row": c.row,
                "source": c.source,
                "clean": round(c.clean, 2),
                "bad": round(c.bad, 2),
                "band": c.band,
                "swappedFrom": c.swapped_from,
                "harm": {},
                "excluded": {},
            }
            for s in specs:
                row = got[s.label].get(c.row)
                mv = log_move(value_of(clean_rows[s.label].get(c.row)), value_of(row))
                item["harm"][s.label] = None if mv is None else round(mv, 6)
                item["excluded"][s.label] = None if s.cfg == "none" else exclusion_of(row, c.source)
            results.append(item)
        if progress and (bi % 10 == 0 or bi + 1 == len(batches)):
            progress(f"batch {bi + 1}/{len(batches)}")
    census = {
        k: {
            "batches": len(v),
            "maxUncorruptedRowLogMove": round(max(v), 6) if v else None,
            "batchesAbove0.01": sum(1 for x in v if x > 0.01),
        }
        for k, v in contamination.items()
    }
    return results, census


def case_material(item: Mapping[str, Any]) -> bool:
    h = item["harm"].get("none")
    return h is not None and h >= G.MATERIAL


def case_passed(item: Mapping[str, Any], label: str) -> bool:
    if item["excluded"].get(label):
        return True
    h = item["harm"].get(label)
    return h is not None and h < G.MATERIAL


def summarize(results: Sequence[Mapping[str, Any]], labels: Sequence[str]) -> dict[str, Any]:
    by_gate: dict[str, list] = defaultdict(list)
    for r in results:
        by_gate[r["gate"]].append(r)
    out: dict[str, Any] = {}
    for gate in ("AD1a", "AD1b", "AD1c", "AD1d", "AD2", "AD4"):
        items = by_gate.get(gate, [])
        mat = [r for r in items if case_material(r)]
        entry: dict[str, Any] = {
            "label": G.GATES[gate]["label"],
            "bar": G.GATES[gate]["bar"],
            "cases": len(items),
            "material": len(mat),
        }
        for lab in labels:
            if lab == "none":
                continue
            passed = [r for r in mat if case_passed(r, lab)]
            reasons: Counter = Counter(str(r["excluded"].get(lab) or "not_excluded") for r in mat)
            entry[lab] = {
                "passRate": round(len(passed) / len(mat), 4) if mat else None,
                "passed": len(passed),
                "meetsBar": bool(mat) and len(passed) / len(mat) >= G.GATES[gate]["bar"],
                "byBand": {
                    b: round(
                        sum(1 for r in mat if r["band"] == b and case_passed(r, lab))
                        / sum(1 for r in mat if r["band"] == b),
                        4,
                    )
                    for b in ("3", "4-5", ">=6")
                    if any(r["band"] == b for r in mat)
                },
                "exclusionReasons": dict(sorted(reasons.items())),
                "failures": [
                    {k: r[k] for k in ("row", "source", "clean", "bad", "band", "swappedFrom")}
                    | {"harmNone": r["harm"].get("none"), "harm": r["harm"].get(lab)}
                    for r in mat
                    if not case_passed(r, lab)
                ][:40],
            }
        out[gate] = entry
    return out


# ── AD3 (both seams; V21-D4) ────────────────────────────────────────────

import csv as _csv  # noqa: E402
import shutil as _shutil  # noqa: E402
import tempfile as _tempfile  # noqa: E402

NAME_COLS = ("name", "Name", "Player", "canonicalName", "player")
RANK_COLS = ("rank", "Rank", "originalRank", "effectiveRank")
VALUE_COLS = ("value", "Value", "normalizedValue", "boone_value", "3D Value +")


def csv_path_for(source: str, root: Path) -> Path | None:
    cfg = dc._SOURCE_CSV_PATHS.get(source)
    rel = cfg if isinstance(cfg, str) else (cfg or {}).get("path")
    return (Path(root) / rel) if rel else None


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as fh:
        rd = _csv.DictReader(fh)
        rows = list(rd)
        return list(rd.fieldnames or []), rows


def write_csv(path: Path, header: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=list(header))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})


@contextlib.contextmanager
def tree_copy(root: Path) -> Iterator[Path]:
    with _tempfile.TemporaryDirectory(prefix="oiv21-dev-tree-") as tmp:
        dst = Path(tmp) / "root"
        _shutil.copytree(root, dst, symlinks=True)
        yield dst


def _num_cell(x: str) -> float | None:
    try:
        f = float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _fmt_like(orig: str, value: float) -> str:
    return str(int(round(value))) if "." not in str(orig) else f"{value:.4f}"


def ad3_input_transform(root: Path, source: str, kind: str) -> dict[str, Any]:
    """The REGISTERED seam (prereg §7: corrupted observations injected before
    Layer A): the source's archived CSV, edited in place in a tree COPY."""
    path = csv_path_for(source, root)
    if path is None or not path.is_file():
        return {"applied": False, "why": "no_csv"}
    header, rows = read_csv(path)
    rcols = [c for c in header if c in RANK_COLS]
    vcols = [c for c in header if c in VALUE_COLS]
    changed = 0
    if kind in ("ranks_x2", "ranks_x5"):
        f = 2.0 if kind == "ranks_x2" else 5.0
        for r in rows:
            for c in rcols:
                v = _num_cell(r.get(c, ""))
                if v is not None:
                    r[c] = _fmt_like(r[c], v * f)
                    changed += 1
    elif kind == "values_x0.01":
        for r in rows:
            for c in vcols:
                v = _num_cell(r.get(c, ""))
                if v is not None and v > 0:
                    r[c] = _fmt_like(r[c], max(1.0, v * 0.01))
                    changed += 1
    elif kind == "reversed":
        for c in rcols + vcols:
            idx = [i for i, r in enumerate(rows) if _num_cell(r.get(c, "")) is not None]
            vals = [rows[i][c] for i in idx]
            for i, v in zip(idx, reversed(vals)):
                rows[i][c] = v
                changed += 1
    write_csv(path, header, rows)
    return {"applied": changed > 0, "cellsChanged": changed, "rankCols": rcols, "valueCols": vcols}


def run_ad3(
    raw: Mapping[str, Any],
    root: Path,
    specs: Sequence[Spec],
    clean_none: Mapping[str, Any],
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """AD3 on both seams for each spec: ``registered`` (input CSV, before
    Layer A) and ``v2_priced`` (V2's post-pricing vote transform)."""
    out: dict[str, Any] = {}
    for seam in ("registered", "v2_priced"):
        per_spec: dict[str, list] = {s.label: [] for s in specs}
        for source, ac in G.AD3_SOURCES:
            for kind in G.AD3_KINDS:
                if seam == "v2_priced":
                    ov = G.ad3_overrides(clean_none, source, ac, kind)
                    meta = {"rows": len(ov)}
                    for s in specs:
                        c = s.build(raw, root, G.transform_for(ov)) if ov else None
                        per_spec[s.label].append(_ad3_case(c, source, ac, kind, meta, ov))
                else:
                    with tree_copy(root) as r2:
                        meta = ad3_input_transform(r2, source, kind)
                        none_c = build(raw, r2, "none")
                        moved = _board_move(clean_none, none_c, ac)
                        meta["noneBoardMaxLogMove"] = moved
                        for s in specs:
                            c = s.build(raw, r2) if meta.get("applied") else None
                            per_spec[s.label].append(_ad3_case(c, source, ac, kind, meta, None))
                if progress:
                    progress(f"AD3 {seam} {source} {kind}")
        out[seam] = {
            lab: {
                "flagged": sum(1 for x in v if x["flagged"]),
                "boards": len(v),
                "passes16of16": sum(1 for x in v if x["flagged"]) == 16 and len(v) == 16,
                "cases": v,
            }
            for lab, v in per_spec.items()
        }
    return out


def _board_move(a: Mapping[str, Any], b: Mapping[str, Any], ac: str) -> float | None:
    ra, rb = rows_by_name(a), rows_by_name(b)
    worst = None
    for n, r in ra.items():
        if r.get("assetClass") != ac:
            continue
        mv = log_move(value_of(r), value_of(rb.get(n)))
        if mv is not None and (worst is None or mv > worst):
            worst = mv
    return None if worst is None else round(worst, 6)


def _ad3_case(contract, source, ac, kind, meta, ov) -> dict[str, Any]:
    if contract is None:
        return {"source": source, "kind": kind, "assetClass": ac, "flagged": False, **meta}
    hits = G.ad3_flagged(contract, source, ac)
    rows = rows_by_name(contract)
    excluded = None
    if ov:
        excluded = sum(1 for (n, s) in ov if exclusion_of(rows.get(n), s))
    return {
        "source": source,
        "kind": kind,
        "assetClass": ac,
        "flagged": bool(hits),
        "flags": hits,
        "votesExcluded": excluded,
        **meta,
    }


# ── input-level identity injections (AD2-ID, AD2-N, AD2-SUR; V21-D8..D10) ─

ID_COLS = {
    "position": ("position", "pos", "Pos", "Fantasy Position"),
    "team": ("team", "Team"),
    "age": ("Age", "age"),
    "sleeperId": ("SleeperId", "sleeper_id"),
    "vendorId": ("player_id",),
}
NAME_LIKE = ("name", "Name", "Player", "canonicalName", "sourceName", "matchedSourceName")


def name_key(name: Any) -> str:
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    return normalize_player_name(str(name or ""))


def identity_columns(header: Sequence[str]) -> dict[str, str]:
    out = {}
    for field, cands in ID_COLS.items():
        for c in cands:
            if c in header:
                out[field] = c
                break
    return out


def _name_col(header: Sequence[str]) -> str | None:
    for c in NAME_COLS:
        if c in header:
            return c
    return None


def csv_index(path: Path) -> tuple[list[str], list[dict[str, str]], dict[str, list[int]]]:
    header, rows = read_csv(path)
    nc = _name_col(header)
    idx: dict[str, list[int]] = defaultdict(list)
    if nc:
        for i, r in enumerate(rows):
            idx[name_key(r.get(nc))].append(i)
    return header, rows, idx


def payload_key_of(clean_rows: Mapping[str, Mapping[str, Any]], display: str) -> str:
    r = clean_rows.get(display) or {}
    return str(r.get("legacyRef") or r.get("canonicalName") or display)


def payload_value(raw: Mapping[str, Any], key: str, source: str) -> float | None:
    p = (raw.get("players") or {}).get(key)
    if not isinstance(p, Mapping):
        return None
    site = p.get("_canonicalSiteValues")
    v = site.get(source) if isinstance(site, Mapping) else None
    if not isinstance(v, (int, float)):
        v = p.get(source)
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


def set_payload_value(raw: dict, key: str, source: str, value: float) -> bool:
    p = (raw.get("players") or {}).get(key)
    if not isinstance(p, dict):
        return False
    site = p.get("_canonicalSiteValues")
    done = False
    if isinstance(site, dict) and source in site:
        site[source] = value
        done = True
    if source in p:
        p[source] = value
        done = True
    return done


def apply_swap_id(
    raw: dict,
    root: Path,
    clean_rows: Mapping[str, Mapping[str, Any]],
    source: str,
    target: str,
    other: str,
    *,
    mode: str,
    homonym_fields: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Edit ``source``'s observation of ``target`` in place (tree COPY / raw
    COPY).  Modes:

    * ``swap_id``  -- AD2-ID: the entry becomes ``other``'s entry (value or
      rank AND every published non-name field), name kept as ``target``'s;
    * ``strip``    -- AD2-N (a): the entry keeps its value, every published
      identity field blanked (no disambiguating evidence);
    * ``homonym``  -- AD2-N (b): the entry keeps its value, its published
      identity fields set to the homonym's (``homonym_fields``).

    Payload-attached sources (B2's ``PAYLOAD_PROVENANCE_SOURCES``) get the
    same value in the payload AND the CSV copy (both copies agree: the worst
    case for B2, as in AD1)."""
    meta: dict[str, Any] = {"source": source, "target": target, "other": other, "mode": mode}
    path = csv_path_for(source, root)
    tkey = payload_key_of(clean_rows, target)
    okey = payload_key_of(clean_rows, other)
    if source in si.PAYLOAD_PROVENANCE_SOURCES and mode == "swap_id":
        ov = payload_value(raw, okey, source)
        if ov is None or not set_payload_value(raw, tkey, source, ov):
            return {**meta, "constructed": False, "why": "payload_value_missing"}
        meta["payloadSwapped"] = True
    if path is None or not path.is_file():
        if meta.get("payloadSwapped"):
            return {**meta, "constructed": True, "identityFields": []}
        return {**meta, "constructed": False, "why": "no_csv"}
    header, rows, idx = csv_index(path)
    tl = idx.get(name_key(target)) or idx.get(name_key(tkey)) or []
    idcols = identity_columns(header)
    if mode in ("strip", "homonym") and tl:
        # A name the source lists more than once (both homonyms on one board)
        # is edited on every entry: no entry may keep disambiguating evidence.
        meta["identityFields"] = sorted(idcols)
        meta["csvEntries"] = len(tl)
        for i in tl:
            for field, col in idcols.items():
                if mode == "homonym" and field in (homonym_fields or {}):
                    rows[i][col] = str((homonym_fields or {})[field])
                else:
                    rows[i][col] = ""
        write_csv(path, header, rows)
        return {**meta, "constructed": True}
    if len(tl) != 1:
        if meta.get("payloadSwapped"):
            return {**meta, "constructed": True, "identityFields": [], "csvRowFound": len(tl)}
        return {**meta, "constructed": False, "why": f"target_csv_rows={len(tl)}"}
    t = rows[tl[0]]
    idcols = identity_columns(header)
    meta["identityFields"] = sorted(idcols)
    if mode == "swap_id":
        ol = idx.get(name_key(other)) or idx.get(name_key(okey)) or []
        if len(ol) != 1:
            return {**meta, "constructed": False, "why": f"other_csv_rows={len(ol)}"}
        o = dict(rows[ol[0]])
        for c in header:
            if c not in NAME_LIKE:
                t[c] = o.get(c, "")
    elif mode == "strip":
        for col in idcols.values():
            t[col] = ""
    elif mode == "homonym":
        for field, col in idcols.items():
            if field in (homonym_fields or {}):
                t[col] = str((homonym_fields or {})[field])
            elif field in ("age", "sleeperId", "vendorId"):
                t[col] = ""
    write_csv(path, header, rows)
    return {**meta, "constructed": True}


def run_input_cases(
    raw: Mapping[str, Any],
    root: Path,
    specs: Sequence[Spec],
    clean: Mapping[str, Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    *,
    progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Input-level cases (dicts with ``row``, ``source``, ``other``, ``mode``,
    optional ``homonymFields``), batched so a batch never touches one row or
    one (source, position group) twice.  Each batch edits a tree and payload
    COPY, then builds every spec plus ``none`` (materiality)."""
    clean_rows = {s.label: rows_by_name(clean[s.label]) for s in specs}
    base_rows = clean_rows.get("none") or next(iter(clean_rows.values()))
    batches: list[list[Mapping[str, Any]]] = []
    keys: list[tuple[set, set]] = []
    for c in sorted(cases, key=lambda c: (c["source"], c["row"], c.get("mode", ""))):
        seg = (c["source"], str((base_rows.get(c["row"]) or {}).get("position") or ""))
        for i, (rows_, segs) in enumerate(keys):
            if c["row"] not in rows_ and seg not in segs and c.get("other") not in rows_:
                batches[i].append(c)
                rows_.add(c["row"])
                segs.add(seg)
                break
        else:
            batches.append([c])
            keys.append(({c["row"]}, {seg}))
    out: list[dict] = []
    for bi, batch in enumerate(batches):
        raw2 = json.loads(json.dumps(raw))
        with tree_copy(root) as r2:
            metas = []
            for c in batch:
                metas.append(
                    apply_swap_id(
                        raw2,
                        r2,
                        base_rows,
                        c["source"],
                        c["row"],
                        c.get("other") or c["row"],
                        mode=c["mode"],
                        homonym_fields=c.get("homonymFields"),
                    )
                )
            got = {s.label: rows_by_name(s.build(raw2, r2)) for s in specs}
        for c, meta in zip(batch, metas):
            item = {**{k: v for k, v in c.items() if k != "homonymFields"}, **meta}
            item["harm"] = {}
            item["excluded"] = {}
            item["identity"] = {}
            for s in specs:
                row = got[s.label].get(c["row"])
                mv = log_move(value_of(clean_rows[s.label].get(c["row"])), value_of(row))
                item["harm"][s.label] = None if mv is None else round(mv, 6)
                item["excluded"][s.label] = (
                    None if s.cfg == "none" else exclusion_of(row, c["source"])
                )
                m = ((row or {}).get("sourceRankMeta") or {}).get(c["source"]) or {}
                blk = ((row or {}).get("sourceIntegrity") or {}).get(c["source"]) or {}
                integ = m.get("integrity") if isinstance(m, Mapping) else None
                ident = (integ or {}).get("identity") or blk.get("identity") or blk.get("verdict")
                if ident:
                    item["identity"][s.label] = ident
            out.append(item)
        if progress and (bi % 10 == 0 or bi + 1 == len(batches)):
            progress(f"input batch {bi + 1}/{len(batches)}")
    return out


def identity_refused(item: Mapping[str, Any], label: str) -> bool:
    """A Layer A refusal (CONTRADICTED / UNRESOLVED) of the injected entry."""
    ex = str(item["excluded"].get(label) or "")
    return ex.startswith("identity_") or ex.startswith("invalid_identity") or "identity" in ex


def summarize_input(items: Sequence[Mapping[str, Any]], labels: Sequence[str], *, rule: str):
    """``rule``: ``material`` (AD2-ID / AD2-SUR: pass = excluded or harm <
    0.10 over material constructed cases) or ``refused`` (AD2-N: pass = a
    Layer A refusal on every constructed case, 100%)."""
    cons = [i for i in items if i.get("constructed")]
    out: dict[str, Any] = {"cases": len(items), "constructed": len(cons)}
    out["unconstructed"] = dict(
        Counter(str(i.get("why")) for i in items if not i.get("constructed"))
    )
    if rule == "material":
        pool = [i for i in cons if (i["harm"].get("none") or 0) >= G.MATERIAL]
    else:
        pool = cons
    out["scored"] = len(pool)
    by_kind = defaultdict(list)
    for i in pool:
        kind = "with_identity_fields" if i.get("identityFields") else "name_only"
        by_kind[kind].append(i)
    for lab in labels:
        if lab == "none":
            continue

        def ok(i, lab=lab):
            if rule == "refused":
                return identity_refused(i, lab)
            return bool(i["excluded"].get(lab)) or (
                i["harm"].get(lab) is not None and i["harm"][lab] < G.MATERIAL
            )

        out[lab] = {
            "passRate": round(sum(1 for i in pool if ok(i)) / len(pool), 4) if pool else None,
            "passed": sum(1 for i in pool if ok(i)),
            "byKind": {
                k: {
                    "n": len(v),
                    "passRate": round(sum(1 for i in v if ok(i)) / len(v), 4) if v else None,
                }
                for k, v in sorted(by_kind.items())
            },
            "exclusionReasons": dict(
                Counter(str(i["excluded"].get(lab) or "not_excluded") for i in pool)
            ),
            "failures": [
                {k: i.get(k) for k in ("row", "source", "other", "mode", "identityFields")}
                | {"harmNone": i["harm"].get("none"), "identity": i["identity"].get(lab)}
                for i in pool
                if not ok(i)
            ][:40],
        }
    return out


# ── the Sleeper directory: same-group homonyms (AD2-N) ──────────────────


def directory_homonyms(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """``{(name key, position group): [players]}`` with >= 2 distinct ACTIVE
    players (Sleeper ``active``), from the identity owner's directory dump."""
    from src.utils.name_clean import canonical_position_group  # noqa: PLC0415

    data = json.loads(Path(path).read_text("utf-8"))
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for sid, p in data.items():
        if not isinstance(p, Mapping) or not p.get("active"):
            continue
        name = p.get("full_name") or f"{p.get('first_name') or ''} {p.get('last_name') or ''}"
        k = name_key(name)
        pos = str(p.get("position") or "")
        grp = canonical_position_group(pos) if pos else ""
        if not k or not grp:
            continue
        groups[(k, grp)].append(
            {"sleeperId": str(sid), "name": name, "position": pos, "team": p.get("team") or ""}
        )
    return {k: v for k, v in groups.items() if len(v) >= 2}


# ── AD2-SUR: a synthetic U2 sidecar (V21-D9) ────────────────────────────


def write_sur_sidecar(root: Path, raw: Mapping[str, Any], stamps: Mapping[str, Mapping]) -> None:
    """A U2 sidecar bound to this payload carrying only ``stamps``
    (``{payload row key: stamp}`` for ``idpTradeCalc``)."""
    from src.identity import capture_evidence as cev  # noqa: PLC0415

    payload = {
        "schema": cev.SCHEMA_VERSION,
        "scrapeTimestamp": raw.get("scrapeTimestamp"),
        "generatedAt": "oiv21-dev-synthetic",
        "sources": {
            "idpTradeCalc": {
                "acquisition": {cev.ACQ_AUTOCOMPLETE: len(stamps)},
                "toggles": None,
                "entryCount": len(stamps),
                "attached": dict(stamps),
            }
        },
        "census": {},
    }
    cev.write_sidecar(payload, Path(root) / cev.SIDECAR_REL)


# ── INJ-DUP (prereg §7.3; V2 §9 property 14; V21-D11) ───────────────────


def run_inj_dup(
    raw: Mapping[str, Any],
    root: Any,
    spec: Spec,
    clean: Mapping[str, Any],
    *,
    seed: int,
    max_rows: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Identical translated values from different boards, end to end: on rows
    with >= 3 voting families and >= 2 rank-signal providers, provider B's
    priced vote is set to provider A's (two separate boards publishing the same
    synthetic value).  Property: (a) neither A nor B is merged away or set
    aside -- both still vote, the row's voting provider and family counts are
    unchanged; (b) no band narrows: on rows whose clean Layer C panel already
    had a corroborated reference for some vote (guards 1, 2, 5 met), no OTHER
    vote that was retained becomes dropped."""
    import random  # noqa: PLC0415

    from src.sources import source_census  # noqa: PLC0415

    rng = random.Random(seed)
    rows = rows_by_name(clean)
    rank_signal = {
        k
        for k, cfg in dc._SOURCE_CSV_PATHS.items()
        if isinstance(cfg, Mapping) and cfg.get("signal") == "rank"
    }
    cases = []
    for n in sorted(rows):
        r = rows[n]
        if r.get("assetClass") == "pick":
            continue
        votes = {k: v for k, v in G.voting_votes(r).items() if exclusion_of(r, k) is None}
        if len({G.family_of(k) for k in votes}) < 3:
            continue
        rs = sorted(k for k in votes if k in rank_signal)
        provs = {k: source_census.provider_of(k) or k for k in rs}
        pairs = [(a, b) for a in rs for b in rs if a < b and provs[a] != provs[b]]
        if not pairs:
            continue
        a, b = rng.choice(pairs)
        cases.append(
            G.Case(
                "DUP",
                n,
                b,
                votes[b],
                votes[a],
                (b, str(r.get("assetClass")), G.pos_group(r)),
                "",
                swapped_from=a,
            )
        )
    if max_rows is not None:
        cases = cases[:max_rows]
    viol_a: list[dict] = []
    viol_b: list[dict] = []
    newly_dropped_no_prior_reference = 0
    for bi, batch in enumerate(G.batch_cases(cases)):
        tf = G.transform_for({(c.row, c.source): c.bad for c in batch})
        got = rows_by_name(spec.build(raw, root, tf))
        for c in batch:
            before, after = rows.get(c.row), got.get(c.row)
            a = c.swapped_from
            vb = {k for k in G.voting_votes(before) if exclusion_of(before, k) is None}
            va = {k for k in G.voting_votes(after or {}) if exclusion_of(after, k) is None}
            fam_b = {G.family_of(k) for k in vb}
            fam_a = {G.family_of(k) for k in va}
            if a not in va or c.source not in va or len(fam_a) != len(fam_b):
                viol_a.append(
                    {"row": c.row, "a": a, "b": c.source, "lostFamilies": sorted(fam_b - fam_a)}
                )
            newly = sorted(k for k in vb - va if k not in (a, c.source))
            if newly:
                ref_before = _has_reference(before)
                if ref_before:
                    viol_b.append({"row": c.row, "a": a, "b": c.source, "newlyDropped": newly})
                else:
                    newly_dropped_no_prior_reference += 1
        if progress and bi % 10 == 0:
            progress(f"INJ-DUP batch {bi + 1}")
    return {
        "cases": len(cases),
        "propertyA_noProviderMerged": not viol_a,
        "propertyA_violations": viol_a[:40],
        "propertyB_noBandNarrows": not viol_b,
        "propertyB_violations": viol_b[:40],
        "rowsNewlyDroppedWithoutPriorReference": newly_dropped_no_prior_reference,
        "holds": not viol_a and not viol_b,
    }


def _has_reference(row: Mapping[str, Any] | None) -> bool:
    """Whether the clean row's Layer C stamp shows a corroborated reference
    was available to some vote (a guard-3 candidate that reached guard 2)."""
    for m in ((row or {}).get("sourceRankMeta") or {}).values():
        integ = m.get("integrity") if isinstance(m, Mapping) else None
        if not isinstance(integ, Mapping):
            continue
        lc = integ.get("layerC")
        if (isinstance(lc, Mapping) and lc.get("reference")) or integ.get("keptBecause") in (
            op.C_KEPT_PERSISTENT,
            op.C_KEPT_DOMINANT,
            op.C_KEPT_SURVIVORS,
        ):
            return True
    return False


# ── INJ-SEG and H2-SYN (V21-D12) ────────────────────────────────────────


def shift_payload_source(
    raw: Mapping[str, Any],
    source: str,
    shifts: Mapping[str, float],
    *,
    share: float,
    seed: int,
    sign_random: bool = False,
) -> tuple[dict, dict[str, Any]]:
    """The payload copy of ``source`` shifted per position group (log), on a
    ``share`` of rows; the CSV keeps the vendor's values."""
    import random  # noqa: PLC0415

    from src.utils.name_clean import POSITION_ALIASES  # noqa: PLC0415

    rng = random.Random(seed)
    out = json.loads(json.dumps(raw))
    positions = (out.get("sleeper") or {}).get("positions") or {}
    groups: dict[str, float] = dict(shifts)
    touched = 0
    for name in sorted(out.get("players") or {}):
        p = out["players"][name]
        if not isinstance(p, dict):
            continue
        val = payload_value(out, name, source)
        if val is None:
            continue
        raw_pos = str(positions.get(name) or "").upper()
        pos = POSITION_ALIASES.get(raw_pos) or raw_pos or "OTHER"
        if pos not in groups:
            if not sign_random:
                continue
            groups[pos] = rng.choice((-1.0, 1.0)) * rng.uniform(0.1, 0.3)
        if rng.random() < share:
            set_payload_value(out, name, source, int(round(val * math.exp(groups[pos]))))
            touched += 1
    return out, {"rowsShifted": touched, "groupShifts": {k: round(v, 4) for k, v in groups.items()}}


# ── cold-start safety (prereg §7.4) ─────────────────────────────────────


def l4_drops(
    contract: Mapping[str, Any],
    *,
    exclude: Callable[[str, str], bool] = lambda _n, _s: False,
) -> dict[str, Any]:
    """Every vote on the board that a V2.1 layer excluded (prereg §7.4
    measurement), minus the labelled positives' scope (``exclude``)."""
    drops = []
    votes = 0
    for r in contract.get("playersArray") or []:
        if r.get("assetClass") == "pick":
            continue
        n = str(r.get("displayName") or "")
        for s in sorted(set(r.get("sourceRankMeta") or {}) | set(r.get("sourceIntegrity") or {})):
            if exclude(n, s):
                continue
            m = (r.get("sourceRankMeta") or {}).get(s)
            lay = v21_layer_drop(r, s)
            if lay is None and isinstance(m, Mapping) and m.get("excludedReason"):
                continue
            val = RP._num(m.get("valueContribution")) if isinstance(m, Mapping) else None
            if lay is None and not (val and val > 0):
                continue
            votes += 1
            if lay is not None:
                integ = m.get("integrity") if isinstance(m, Mapping) else None
                if not isinstance(integ, Mapping):
                    integ = (r.get("sourceIntegrity") or {}).get(s) or {}
                drops.append(
                    {
                        "row": n,
                        "position": r.get("position"),
                        "source": s,
                        "value": val,
                        "layer": lay,
                        "category": integ.get("category"),
                        "identity": integ.get("identity"),
                    }
                )
    return {"votes": votes, "dropped": len(drops), "drops": drops}


def invalid_category_labels(contract: Mapping[str, Any]) -> list[dict]:
    """Votes that passed A and B but carry an invalid §10 category (R7)."""
    from src.sources import voting_status as vs  # noqa: PLC0415

    bad = []
    for r in contract.get("playersArray") or []:
        for s, m in (r.get("sourceRankMeta") or {}).items():
            integ = m.get("integrity") if isinstance(m, Mapping) else None
            if not isinstance(integ, Mapping):
                continue
            st = integ.get("status")
            cat = integ.get("category")
            if st in (si.STATUS_VOTING, si.STATUS_REJECTED_TAIL, si.STATUS_RELEASED_BY_CAP) and (
                cat in vs.INVALID_OBSERVATION_CATEGORIES
            ):
                bad.append(
                    {"row": r.get("displayName"), "source": s, "status": st, "category": cat}
                )
    return bad
