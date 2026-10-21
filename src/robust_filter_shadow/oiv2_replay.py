"""Outlier-integrity-v2 historical replay: builds, records and capture seams.

Preregistration ``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` §6, §7,
§10. This module only BUILDS archived boards (through the inherited rebuild
procedure of ``scripts/joint_filter_shadow.py``, as #1847's replay harness does)
and READS what each build stamped. It changes no vote, weight, threshold or
value: the only seams it uses are replay seams that already exist
(``source_integrity.history_override``, ``data_contract._ADVERSARIAL_VOTE_TRANSFORM``)
plus read-only call recorders around two pure functions (Layer C's
``LayerCContext.assess`` and Layer A's ``assess_identity_evidence``), which
call the original unchanged and return its result.

Comparators per board (prereg §2.2, §6.1), every build at the prereg §6 pins:

====== ========================  ====================  ==================
name   filter                    DLF IDP / D4          history lane
====== ========================  ====================  ==================
inc    incumbent (board A)       held / off            —
v1     outlier-corroborated-v1   held / off            —
v2     V2 primary (board D)      held / off            chained (V2's own)
v2nh   V2-NOHIST                 held / off            empty
v2d1   V2+D1                     held / off            chained
B      incumbent                 restored / off        —
C      V2                        restored / off        chained
Bp     incumbent (B′)            held / on             —
Cp     V2 (C′)                   held / on             chained
Bpp    incumbent (B″)            restored / on         —
Cpp    V2 (C″)                   restored / on         chained
====== ========================  ====================  ==================

Missing is never zero: a row or vote a build did not produce is absent from the
record, never 0.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

from src.api import data_contract as dc
from src.api import outlier_policy as op
from src.api import source_integrity as si
from src.api import value_replay as vr
from src.robust_filter_shadow.record import precap_weight

SCHEMA = "oiv2-replay/v1"
PREREG = "docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md"

#: Prereg §6 pins on every build (release defaults otherwise).
BASE_PINS: dict[str, bool] = {
    "source_freshness_weighting": True,
    "source_family_cap": True,
    "idp_deep_tail_native_challenger": False,
    "joint_outlier_sparse_challenger": False,
    "joint_sparse_limited_evidence": False,
    "rank_space_hampel_challenger": False,
    "rank_space_hampel_per_vote_challenger": False,
    "idp_hampel_n3_challenger": False,
    "outlier_disagreement_policy": False,
    "dlf_offense_only_vote": True,
    "dlf_values_rank_hill_vote": False,
    "integrity_holds_as_withheld": False,
    "source_rank_history_record": False,
}
V2_FLAGS = (
    "outlier_integrity_v2",
    "identity_evidence_v2",
    "payload_provenance_guard",
    "rookie_ladder_fail_closed",
)
_RESTORED = {"dlf_offense_only_vote": False}
_D4 = {"dlf_values_rank_hill_vote": True}


@dataclasses.dataclass(frozen=True)
class Config:
    name: str
    v2: bool
    extra: Mapping[str, bool] = dataclasses.field(default_factory=dict)
    #: "chain" = the V2 history lane rebuilt from earlier boards; "none" = empty.
    history: str | None = None
    label: str = ""


CONFIGS: dict[str, Config] = {
    c.name: c
    for c in (
        Config("inc", False, {}, None, "incumbent (board A, release defaults)"),
        Config("v1", False, {"outlier_disagreement_policy": True}, None, "outlier-corroborated-v1"),
        Config("v2", True, {}, "chain", "V2 primary (board D)"),
        Config("v2nh", True, {}, "none", "V2-NOHIST"),
        Config("v2d1", True, {"integrity_holds_as_withheld": True}, "chain", "V2+D1"),
        Config("B", False, dict(_RESTORED), None, "B: DLF IDP restored + incumbent"),
        Config("C", True, dict(_RESTORED), "chain", "C: DLF IDP restored + V2"),
        Config("Bp", False, dict(_D4), None, "B': D4 on + incumbent"),
        Config("Cp", True, dict(_D4), "chain", "C': D4 on + V2"),
        Config("Bpp", False, {**_RESTORED, **_D4}, None, "B'': DLF IDP restored + D4 + incumbent"),
        Config("Cpp", True, {**_RESTORED, **_D4}, "chain", "C'': DLF IDP restored + D4 + V2"),
    )
}
V2_CONFIGS = tuple(n for n, c in CONFIGS.items() if c.v2)


def flags_for(config: Config) -> dict[str, bool]:
    flags = dict(BASE_PINS)
    for f in V2_FLAGS:
        flags[f] = config.v2
    flags.update(config.extra)
    return flags


def build(
    raw: Mapping[str, Any],
    csv_root: Any,
    config: Config,
    *,
    history: si.IntegrityHistory | None = None,
    thresholds: si.IntegrityThresholds | None = None,
    transform: Callable[[Mapping[str, Any], str, float], float] | None = None,
    source_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One full build. ``thresholds`` replaces the committed thresholds file
    for this build only (Stage 2 selection runs); ``None`` reads the file."""
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
        for name, enabled in sorted(flags_for(config).items()):
            stack.enter_context(vr._flag(name, enabled))
        if config.v2:
            stack.enter_context(si.history_override(history))
        if thresholds is not None:
            stack.enter_context(_patched_module(si, "load_thresholds", lambda *_a: thresholds))
        stack.enter_context(vr._patched("_ADVERSARIAL_VOTE_TRANSFORM", transform))
        return dc.build_api_data_contract(
            json.loads(json.dumps(raw)),
            source_overrides=dict(source_overrides) if source_overrides else None,
            csv_root=csv_root,
        )


@contextlib.contextmanager
def _patched_module(module: Any, attr: str, value: Any) -> Iterator[None]:
    original = getattr(module, attr)
    setattr(module, attr, value)
    try:
        yield
    finally:
        setattr(module, attr, original)


# ── read-only call recorders ────────────────────────────────────────────


class LayerCRecorder:
    """Records, for every per-row Layer C call, the decision Layer C makes on
    the same panel with each family left out -- through the SAME context
    object (its declared lineage, persistence history and capped weights), so
    the M1 reduced-panel decision is V2's own, not an emulation. The original
    ``assess`` is called unchanged and its result returned."""

    def __init__(self) -> None:
        self.by_panel: dict[tuple, dict[str, list[str]]] = {}
        self._depth = 0

    @staticmethod
    def panel_key(pairs: Sequence[tuple[str, float]]) -> tuple:
        return tuple(sorted((str(k), int(round(float(v)))) for k, v in pairs))

    @contextlib.contextmanager
    def active(self) -> Iterator[LayerCRecorder]:
        original = op.LayerCContext.assess
        rec = self

        def assess(ctx, pairs, weights=None):  # noqa: ANN001
            out = original(ctx, pairs, weights)
            if rec._depth == 0 and weights is None and len(pairs) >= 2:
                rec._depth += 1
                try:
                    fams = sorted({ctx.family_of(k) for k, _v in pairs})
                    reduced: dict[str, list[str]] = {"*": sorted(out.dropped)}
                    for fam in fams:
                        sub = [(k, v) for k, v in pairs if ctx.family_of(k) != fam]
                        reduced[fam] = (
                            sorted(original(ctx, sub, None).dropped) if len(sub) >= 2 else []
                        )
                    rec.by_panel.setdefault(rec.panel_key(pairs), reduced)
                finally:
                    rec._depth -= 1
            return out

        op.LayerCContext.assess = assess
        try:
            yield self
        finally:
            op.LayerCContext.assess = original


class IdentityAgeRecorder:
    """For τ_age selection (prereg §3.5): every Layer A join whose entry and
    row both carry an age, with whether an id vouched for it and whether a rule
    BEFORE the age rule already decided it. Calls the original unchanged."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    @contextlib.contextmanager
    def active(self) -> Iterator[IdentityAgeRecorder]:
        from src.identity import resolution as res  # noqa: PLC0415

        original = res.assess_identity_evidence
        rec = self

        def wrapped(*args, **kwargs):  # noqa: ANN002, ANN003
            out = original(*args, **kwargs)
            try:
                row = kwargs.get("row")
                cands = kwargs.get("candidates") or []
                chosen = kwargs.get("chosen", 0)
                idx = out.selected if out.selected is not None else chosen
                entry = cands[idx] if 0 <= idx < len(cands) else None
                if entry is not None and entry.age is not None and row.age is not None:
                    pre = original(*args, **{**kwargs, "tau_age": None})
                    row_sid = str(row.player_id or "").strip()
                    id_agrees = kwargs.get("via") == "sleeper_id" or (
                        bool(row_sid) and str(entry.sleeper_id or "").strip() == row_sid
                    )
                    rec.rows.append(
                        {
                            "name": row.name,
                            "entryAge": float(entry.age),
                            "rowAge": float(row.age),
                            "absDiff": round(abs(float(entry.age) - float(row.age)), 4),
                            "idAgrees": bool(id_agrees),
                            "preAgeVerdict": pre.verdict,
                            "preAgeReason": pre.reason,
                        }
                    )
            except Exception:  # noqa: BLE001 -- a recorder never changes a build
                pass
            return out

        res.assess_identity_evidence = wrapped
        try:
            yield self
        finally:
            res.assess_identity_evidence = original


# ── reading a built board ───────────────────────────────────────────────


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    f = float(x)
    return f if math.isfinite(f) else None


def vote_state(meta: Mapping[str, Any]) -> str:
    """``voting`` | ``filter_dropped`` | ``integrity:<primary reason>`` |
    ``excluded:<excludedReason>`` for one observation."""
    integ = meta.get("integrity")
    if isinstance(integ, Mapping) and integ.get("status") not in (None, si.STATUS_VOTING):
        if integ.get("status") == si.STATUS_REJECTED_TAIL:
            return "filter_dropped"
        return "integrity:" + str(integ.get("primaryReason") or integ.get("status"))
    if meta.get("excludedReason"):
        return "excluded:" + str(meta["excludedReason"])
    if meta.get("hampelDropped"):
        return "filter_dropped"
    return "voting"


def row_observations(row: Mapping[str, Any]) -> dict[str, list]:
    """``{source: [vote value or None, pre-cap weight, state]}`` for every
    observation the row carries (refused Layer A observations included, with
    no value: they were never priced)."""
    out: dict[str, list] = {}
    for s, m in sorted((row.get("sourceRankMeta") or {}).items()):
        if not isinstance(m, Mapping):
            continue
        out[str(s)] = [
            _num(m.get("valueContribution")),
            round(precap_weight(m), 6),
            vote_state(m),
        ]
    for s, blk in sorted((row.get("sourceIntegrity") or {}).items()):
        if s in out or not isinstance(blk, Mapping):
            continue
        if blk.get("status") == si.STATUS_REFUSED:
            out[str(s)] = [None, 0.0, "integrity:" + str(blk.get("primaryReason"))]
    return out


def voting_panel(obs: Mapping[str, list]) -> dict[str, float]:
    """The votes that reached the per-row filter (voting or filter-dropped)."""
    return {
        k: v[0]
        for k, v in obs.items()
        if v[0] is not None and v[0] > 0 and v[2] in ("voting", "filter_dropped")
    }


def extract(
    contract: Mapping[str, Any],
    *,
    full: bool,
    layer_c: LayerCRecorder | None = None,
) -> dict[str, Any]:
    """One build's compact record. ``full`` keeps every observation (the
    primary V2 build and the incumbent); otherwise only rows' outcomes and
    their non-voting observations."""
    rows: dict[str, Any] = {}
    seen: Counter = Counter()
    for r in contract.get("playersArray") or []:
        if isinstance(r, Mapping) and r.get("displayName"):
            seen[str(r["displayName"])] += 1
    for r in contract.get("playersArray") or []:
        if not isinstance(r, Mapping) or not r.get("displayName"):
            continue
        name = str(r["displayName"])
        if seen[name] > 1:
            name = f"{name}|{r.get('assetClass')}|{r.get('position')}"
        obs = row_observations(r)
        entry: dict[str, Any] = {
            "v": _num(r.get("rankDerivedValue")),
            "rk": r.get("canonicalConsensusRank"),
            "cf": r.get("confidenceBucket"),
            "dr": sorted(r.get("droppedSources") or []),
        }
        if full:
            entry["ac"] = r.get("assetClass")
            entry["pos"] = r.get("position")
            entry["pk"] = si.player_key_for_row(r)
            entry["obs"] = obs
            reasons = r.get("outlierIntegrityReasons") or r.get("outlierPolicyReasons")
            if reasons:
                entry["fr"] = dict(reasons)
            if layer_c is not None:
                panel = voting_panel(obs)
                got = layer_c.by_panel.get(LayerCRecorder.panel_key(list(panel.items())))
                if got is not None:
                    entry["m1"] = got
        else:
            nv = {k: v[2] for k, v in obs.items() if v[2] != "voting"}
            if nv:
                entry["nv"] = nv
        rows[name] = entry
    out: dict[str, Any] = {"rows": rows}
    integ = contract.get("sourceIntegrity")
    if isinstance(integ, Mapping):
        keep = (
            "version",
            "layerC",
            "historyLane",
            "thresholds",
            "findings",
            "sourceQuarantines",
            "segmentQuarantines",
            "dependency",
            "provenance",
            "identity",
            "voteExclusions",
            "alerts",
            "rankingPasses",
        )
        blk = {k: integ.get(k) for k in keep if k in integ}
        if full:
            blk["segmentMedians"] = integ.get("segmentMedians")
            blk["segmentStats"] = integ.get("segmentStats")
        out["sourceIntegrity"] = blk
    pol = contract.get("outlierPolicy")
    if isinstance(pol, Mapping):
        out["outlierPolicy"] = pol
    return out


# ── history lane ────────────────────────────────────────────────────────


def board_record_for_history(
    contract: Mapping[str, Any], excluded_sources: Callable[[str], bool]
) -> dict[str, Any]:
    """``source_integrity.board_record`` with a degraded source's observations
    removed (prereg §6: "degraded sources excluded")."""
    rec = si.board_record(contract)
    rec["observations"] = {
        k: v for k, v in rec["observations"].items() if not excluded_sources(k.split("|", 1)[0])
    }
    rec["hashes"] = {k: v for k, v in rec["hashes"].items() if not excluded_sources(k)}
    rec["segmentMedians"] = {
        k: v for k, v in rec["segmentMedians"].items() if not excluded_sources(k.split("|", 1)[0])
    }
    return rec


def degraded_filter(degraded_run_sources: Sequence[str]) -> Callable[[str], bool]:
    """Source keys whose critical run source was degraded on the board.

    The only degraded run sources in the frozen manifests are ``KTC_TradeDB`` /
    ``KTC_WaiverDB`` (E_BASELINE), whose critical primary is ``KTC``; every
    KeepTradeCut source key starts with ``ktc``.
    """
    primaries = set()
    for name in degraded_run_sources or ():
        p = dc.critical_primary_for_run_source(str(name))
        if p:
            primaries.add(str(p))
    if not primaries:
        return lambda _k: False
    if primaries - {"KTC"}:
        raise ValueError(f"unmapped degraded primaries: {sorted(primaries)}")
    return lambda k: str(k).lower().startswith("ktc")


def thresholds_with(**changes: Any) -> si.IntegrityThresholds:
    return dataclasses.replace(si.load_thresholds(), **changes)


def defaultdict_list() -> defaultdict:
    return defaultdict(list)
