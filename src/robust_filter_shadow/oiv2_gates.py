"""Outlier-integrity-v2 FULL-PIPELINE adversarial gates (directive §5, prereg §7).

``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` §7 requires the gates to
be measured on the complete layered system, not on a per-row emulator. V1's M7
suite (``outlier_policy_eval.adversarial``) recomputes a decision from a stored
record with an emulated blend: it measures the statistical filter only. This
module is the full-pipeline mode:

* every case is a corrupted OBSERVATION injected through the replay-only seam
  ``data_contract._ADVERSARIAL_VOTE_TRANSFORM`` -- right after the vote is priced
  (rank->Hill or value-direct, TE basis applied) and before Layer B's vote-level
  exclusions, the B3 segment screen (both ranking passes), B4, Layer C, the B10
  family cap, the count-aware blend, post-blend overrides and confidence;
* the board is rebuilt end to end through ``build_api_data_contract`` for every
  batch and configuration, and the outcome is read from what the contract
  itself stamped (``sourceRankMeta``, ``rankDerivedValue``, ``sourceIntegrity``).

**Which component each gate measures** (stated, never implied):

* AD1a-d, AD4 -- the complete post-join pipeline (B vote exclusions, B3, B4,
  Layer C, cap, blend, overrides). The injected value is a correctly formatted,
  correctly attributed number that both payload and CSV copies agree on, so
  Layer A, B0 and B2 have no signature to read **by construction** -- the
  worst case for V2, and the corruption class those gates name.
* AD2 (as registered) -- the same, with the vote replaced by the same source's
  vote for a player >= 100 consensus ranks away and NO identity evidence. Layer
  A cannot fire on information the fixture does not carry; that missing
  evidence is documented, never invented (directive §5).
* AD3 -- B3 (segment screen) on a board-wide vote transform of one source:
  "flagged before voting" = a B0 source quarantine or a B3 segment / class
  quarantine of that source on that asset class. Rank boards are densely
  re-ranked inside the pipeline, so an INPUT-level uniform rank rescaling is a
  no-op by construction (V1 §4 E1); the transform is applied to the priced
  votes, exactly as V1's fixture (``_reprice``).

Pass rule (prereg §7): a case is MATERIAL when the no-filter board moves the
row by >= 0.10 in log value; a configuration PASSES a material case when the
corrupted observation is excluded or held by any layer, or its own board moves
the row by < 0.10. Rates are over material cases.

Batching: one build carries many cases, never two on one row and never two on
one (source, asset class, position group) segment, so no per-segment statistic
sees more than one corrupted vote. Cross-case contamination is MEASURED on every
batch (the largest log move of any row carrying no case) and published.

Variant: NO-HISTORY (the gate of record unless O-1 is recorded, prereg §7.1) --
``source_integrity.history_override(None)``.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.api import data_contract as dc
from src.api import outlier_policy as op
from src.api import source_integrity as si
from src.api import value_replay as vr

SCHEMA = "oiv2-full-pipeline-gates/v1"
MATERIAL = 0.10
SEED = 2033
#: Directive §5 bars, verbatim. Never edited to make a run pass: a run below a
#: bar is a failed gate (pinned by ``tests/api/test_oiv2_full_pipeline_gates.py``).
GATES: dict[str, dict[str, Any]] = {
    "AD1a": {"label": "Extreme high corruption x5", "factor": 5.0, "bar": 0.90},
    "AD1b": {"label": "Extreme low corruption x0.2", "factor": 0.2, "bar": 0.90},
    "AD1c": {"label": "Extreme high corruption x20", "factor": 20.0, "bar": 0.95},
    "AD1d": {"label": "Extreme low corruption x0.05", "factor": 0.05, "bar": 0.95},
    "AD2": {"label": "Wrong-player matching", "bar": 0.90},
    "AD4": {"label": "Single-source spike", "bar": 0.95},
    "AD3": {"label": "Wrong-scale board detection", "boardsRequired": 16},
}
AD3_SOURCES: tuple[tuple[str, str], ...] = (
    ("dynastyNerdsSfTep", "offense"),
    ("flockFantasySf", "offense"),
    ("fantasyCalc", "offense"),
    ("fantasyProsIdp", "idp"),
)
AD3_KINDS = ("ranks_x2", "ranks_x5", "values_x0.01", "reversed")

#: Pinned flags on every gate build (prereg §6), release defaults otherwise.
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
CONFIGS = ("none", "incumbent", "v2")


def _flags_for(config: str, extra: Mapping[str, bool] | None = None) -> dict[str, bool]:
    flags = dict(BASE_PINS)
    v2_on = config == "v2"
    for f in V2_FLAGS:
        flags[f] = v2_on
    flags.update(extra or {})
    return flags


def _no_filter(pairs, **_kwargs):
    return list(pairs), []


def build(
    raw: Mapping[str, Any],
    csv_root: Any,
    config: str,
    transform: Callable[[Mapping[str, Any], str, float], float] | None = None,
    *,
    extra_flags: Mapping[str, bool] | None = None,
    history: Any = None,
) -> dict[str, Any]:
    """One full build. ``none`` = no per-row filter (V2 off, incumbent stood
    down); ``incumbent`` = release filter; ``v2`` = V2 primary configuration
    under ``history`` (``None`` = NO-HISTORY)."""
    if config not in CONFIGS:
        raise ValueError(config)
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
        for name, enabled in sorted(_flags_for(config, extra_flags).items()):
            stack.enter_context(vr._flag(name, enabled))
        if config == "none":
            stack.enter_context(vr._patched("_hampel_filter_per_player", _no_filter))
        if config == "v2":
            stack.enter_context(si.history_override(history))
        stack.enter_context(vr._patched("_ADVERSARIAL_VOTE_TRANSFORM", transform))
        return dc.build_api_data_contract(
            json.loads(json.dumps(raw)), source_overrides=None, csv_root=csv_root
        )


# ── reading a built board ──────────────────────────────────────────────


def family_of(source: str) -> str:
    return dc.correlation_group_for(source) or source


def pos_group(row: Mapping[str, Any]) -> str:
    return str(row.get("position") or "").strip().upper() or "OTHER"


def voting_votes(row: Mapping[str, Any]) -> dict[str, float]:
    """``{source: priced vote}`` for every observation that reached the filter
    stage (no exclusion of any kind stamped before it)."""
    out: dict[str, float] = {}
    for k, m in (row.get("sourceRankMeta") or {}).items():
        if not isinstance(m, Mapping) or m.get("excludedReason"):
            continue
        integ = m.get("integrity")
        if isinstance(integ, Mapping) and integ.get("status") not in (
            si.STATUS_VOTING,
            si.STATUS_REJECTED_TAIL,
        ):
            continue
        v = m.get("valueContribution")
        if isinstance(v, (int, float)) and v > 0:
            out[str(k)] = float(v)
    return out


def exclusion_of(row: Mapping[str, Any] | None, source: str) -> str | None:
    """Why ``source``'s observation on ``row`` did not count, or ``None``."""
    if not row:
        return "row_absent"
    m = (row.get("sourceRankMeta") or {}).get(source)
    if not isinstance(m, Mapping):
        return "observation_absent"
    integ = m.get("integrity")
    if isinstance(integ, Mapping) and integ.get("status") not in (None, si.STATUS_VOTING):
        return str(integ.get("primaryReason") or integ.get("status"))
    if m.get("excludedReason"):
        return str(m["excludedReason"])
    if m.get("hampelDropped") or source in (row.get("droppedSources") or []):
        return "filter_dropped"
    return None


def rows_by_name(contract: Mapping[str, Any]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    dup: set[str] = set()
    for r in contract.get("playersArray") or []:
        n = str(r.get("displayName") or "")
        if n in out:
            dup.add(n)
        out[n] = r
    for n in dup:
        out.pop(n, None)
    return out


def _value(row: Mapping[str, Any] | None) -> float | None:
    v = (row or {}).get("rankDerivedValue")
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


# ── cases ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Case:
    gate: str
    row: str
    source: str
    clean: float
    bad: float
    segment: tuple[str, str, str]
    band: str
    swapped_from: str | None = None


@dataclass
class CaseResult:
    case: Case
    harm: dict[str, float] = field(default_factory=dict)
    excluded: dict[str, str | None] = field(default_factory=dict)

    @property
    def material(self) -> bool:
        return self.harm.get("none", 0.0) >= MATERIAL

    def passed(self, config: str) -> bool:
        return bool(self.excluded.get(config)) or self.harm.get(config, 1.0) < MATERIAL


def _band(n_fam: int) -> str:
    return "3" if n_fam == 3 else ("4-5" if n_fam <= 5 else ">=6")


def plan_cases(
    clean: Mapping[str, Mapping[str, Any]],
    *,
    seed: int = SEED,
    max_rows: int | None = None,
) -> list[Case]:
    """V1's case construction (``outlier_policy_eval.adversarial``) on full-
    pipeline votes: rows with >= 3 voting families on ALL clean boards, one
    random voting source per row and case. ``clean`` maps config -> contract."""
    rng = random.Random(seed)
    boards = {c: rows_by_name(clean[c]) for c in CONFIGS}
    rank_of: dict[str, int] = {}
    for n, r in boards["incumbent"].items():
        rk = r.get("canonicalConsensusRank")
        if isinstance(rk, int):
            rank_of[n] = rk
    eligible: dict[str, dict] = {}
    for n in sorted(boards["none"]):
        r = boards["none"][n]
        if r.get("assetClass") == "pick" or _value(r) is None:
            continue
        votes = voting_votes(r)
        # A vote already set aside on a CLEAN board by any configuration is
        # not a case: catching it would not be catching the corruption.
        if any(n not in boards[c] for c in CONFIGS):
            continue
        votes = {
            k: v
            for k, v in votes.items()
            if all(exclusion_of(boards[c][n], k) in (None,) for c in ("none", "v2"))
            and exclusion_of(boards["incumbent"][n], k) in (None, "filter_dropped")
        }
        if len({family_of(k) for k in votes}) < 3:
            continue
        eligible[n] = {"row": r, "votes": votes}
    names = sorted(eligible)
    if max_rows is not None:
        names = names[:max_rows]
    by_source_rows: dict[str, list[str]] = defaultdict(list)
    for n in names:
        for s in eligible[n]["votes"]:
            by_source_rows[s].append(n)
    cases: list[Case] = []
    for n in names:
        r, votes = eligible[n]["row"], eligible[n]["votes"]
        sources = sorted(votes)
        band = _band(len({family_of(k) for k in votes}))
        ac = str(r.get("assetClass") or "")
        pg = pos_group(r)
        for gate in ("AD1a", "AD1b", "AD1c", "AD1d"):
            s = rng.choice(sources)
            bad = min(9999.0, max(1.0, votes[s] * GATES[gate]["factor"]))
            cases.append(Case(gate, n, s, votes[s], bad, (s, ac, pg), band))
        s = rng.choice(sources)
        rk = rank_of.get(n)
        pool = [
            o
            for o in by_source_rows[s]
            if o != n and rk is not None and o in rank_of and abs(rank_of[o] - rk) >= 100
        ]
        if pool:
            other = rng.choice(sorted(pool))
            bad = eligible[other]["votes"][s]
            cases.append(Case("AD2", n, s, votes[s], bad, (s, ac, pg), band, swapped_from=other))
        if rk is not None and 150 <= rk <= 400:
            s = rng.choice(sources)
            cases.append(Case("AD4", n, s, votes[s], 9000.0, (s, ac, pg), band))
    return cases


def batch_cases(cases: Sequence[Case]) -> list[list[Case]]:
    """Greedy, deterministic: within a batch no two cases share a row or a
    (source, asset class, position group) segment."""
    batches: list[list[Case]] = []
    keys: list[tuple[set, set]] = []
    for c in sorted(cases, key=lambda c: (c.segment, c.row)):
        for i, (rows, segs) in enumerate(keys):
            if c.row not in rows and c.segment not in segs:
                batches[i].append(c)
                rows.add(c.row)
                segs.add(c.segment)
                break
        else:
            batches.append([c])
            keys.append(({c.row}, {c.segment}))
    return batches


def transform_for(overrides: Mapping[tuple[str, str], float]):
    def _t(row: Mapping[str, Any], source: str, value: float) -> float:
        bad = overrides.get((str(row.get("displayName") or ""), source))
        return value if bad is None else float(bad)

    return _t


def _log_move(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return abs(math.log(b) - math.log(a))


def run_cases(
    raw: Mapping[str, Any],
    csv_root: Any,
    clean: Mapping[str, Mapping[str, Any]],
    cases: Sequence[Case],
    *,
    progress: Callable[[str], None] | None = None,
) -> tuple[list[CaseResult], dict[str, Any]]:
    """Every case through every configuration, batched. Returns the per-case
    results and the contamination census."""
    clean_rows = {c: rows_by_name(clean[c]) for c in CONFIGS}
    results: list[CaseResult] = []
    contamination: dict[str, list[float]] = {c: [] for c in CONFIGS}
    contaminated: dict[str, list[dict]] = {c: [] for c in CONFIGS}
    batches = batch_cases(cases)
    for bi, batch in enumerate(batches):
        overrides = {(c.row, c.source): c.bad for c in batch}
        case_rows = {c.row for c in batch}
        per_config: dict[str, dict[str, dict]] = {}
        for config in CONFIGS:
            contract = build(raw, csv_root, config, transform_for(overrides))
            per_config[config] = rows_by_name(contract)
            worst, worst_row = 0.0, None
            for n, r in per_config[config].items():
                if n in case_rows or r.get("assetClass") == "pick":
                    continue
                mv = _log_move(_value(clean_rows[config].get(n)), _value(r))
                if mv is not None and mv > worst:
                    worst, worst_row = mv, n
            contamination[config].append(worst)
            if worst > 0.01:
                contaminated[config].append(
                    {
                        "batch": bi,
                        "row": worst_row,
                        "logMove": round(worst, 6),
                        "batchCases": sorted(f"{c.row}|{c.source}" for c in batch),
                    }
                )
        for c in batch:
            res = CaseResult(c)
            for config in CONFIGS:
                row = per_config[config].get(c.row)
                mv = _log_move(_value(clean_rows[config].get(c.row)), _value(row))
                res.harm[config] = mv if mv is not None else float("inf")
                res.excluded[config] = exclusion_of(row, c.source) if config != "none" else None
            results.append(res)
        if progress:
            progress(f"batch {bi + 1}/{len(batches)}: {len(batch)} cases")
    census = {
        c: {
            "batches": len(v),
            "maxUncorruptedRowLogMove": round(max(v), 6) if v else None,
            "batchesAbove0.01": sum(1 for x in v if x > 0.01),
            "above0.01": contaminated[c][:40],
        }
        for c, v in contamination.items()
    }
    return results, census


def summarize_cases(results: Sequence[CaseResult]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    by_gate: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_gate[r.case.gate].append(r)
    for gate in ("AD1a", "AD1b", "AD1c", "AD1d", "AD2", "AD4"):
        items = by_gate.get(gate, [])
        material = [r for r in items if r.material]
        entry: dict[str, Any] = {
            "label": GATES[gate]["label"],
            "bar": GATES[gate]["bar"],
            "cases": len(items),
            "material": len(material),
        }
        for config in ("incumbent", "v2"):
            passed = [r for r in material if r.passed(config)]
            reasons: dict[str, int] = defaultdict(int)
            for r in material:
                reasons[str(r.excluded.get(config) or "not_excluded")] += 1
            entry[config] = {
                "passRate": round(len(passed) / len(material), 4) if material else None,
                "passed": len(passed),
                "byBand": {
                    b: round(
                        sum(1 for r in material if r.case.band == b and r.passed(config))
                        / sum(1 for r in material if r.case.band == b),
                        4,
                    )
                    for b in ("3", "4-5", ">=6")
                    if any(r.case.band == b for r in material)
                },
                "exclusionReasons": dict(sorted(reasons.items())),
            }
        rate = entry["v2"]["passRate"]
        entry["v2Passes"] = rate is not None and rate >= GATES[gate]["bar"]
        entry["failures"] = [
            {
                "row": r.case.row,
                "source": r.case.source,
                "clean": round(r.case.clean, 1),
                "bad": round(r.case.bad, 1),
                "harmNone": round(r.harm["none"], 4),
                "harmV2": None if math.isinf(r.harm["v2"]) else round(r.harm["v2"], 4),
                "band": r.case.band,
                **({"swappedFrom": r.case.swapped_from} if r.case.swapped_from else {}),
            }
            for r in material
            if not r.passed("v2")
        ][:60]
        out[gate] = entry
    return out


# ── AD3 board-scale cases ──────────────────────────────────────────────


def _reprice(v: float, curve: tuple[float, float], factor: float) -> float:
    c, s = curve
    p = op.hill_inverse(v, c, s) * factor
    return 9999.0 / (1.0 + (p / c) ** s)


def ad3_overrides(
    clean_none: Mapping[str, Any], source: str, asset_class: str, kind: str
) -> dict[tuple[str, str], float]:
    rows = rows_by_name(clean_none)
    covered = {
        n: voting_votes(r)[source]
        for n, r in rows.items()
        if r.get("assetClass") == asset_class and source in voting_votes(r)
    }
    curve = op.scope_curve(asset_class)
    if kind == "reversed":
        ordered = sorted(covered, key=lambda n: (-covered[n], n))
        vals = [covered[n] for n in ordered]
        return {(n, source): v for n, v in zip(ordered, reversed(vals))}
    out = {}
    for n, v in covered.items():
        if kind == "ranks_x2":
            out[(n, source)] = _reprice(v, curve, 2.0)
        elif kind == "ranks_x5":
            out[(n, source)] = _reprice(v, curve, 5.0)
        elif kind == "values_x0.01":
            out[(n, source)] = max(1.0, v * 0.01)
        else:
            raise ValueError(kind)
    return out


def ad3_flagged(contract: Mapping[str, Any], source: str, asset_class: str) -> list[str]:
    stamp = contract.get("sourceIntegrity") or {}
    hits = []
    if source in (stamp.get("sourceQuarantines") or {}):
        hits.append(f"source:{stamp['sourceQuarantines'][source]}")
    for key, reason in sorted((stamp.get("segmentQuarantines") or {}).items()):
        parts = str(key).split("/")
        if parts[0] == source and len(parts) > 1 and parts[1] == asset_class:
            hits.append(f"{key}:{reason}")
    return hits


def run_ad3(
    raw: Mapping[str, Any],
    csv_root: Any,
    clean_none: Mapping[str, Any],
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    cases = []
    for source, ac in AD3_SOURCES:
        for kind in AD3_KINDS:
            ov = ad3_overrides(clean_none, source, ac, kind)
            if not ov:
                cases.append({"source": source, "kind": kind, "rows": 0, "flagged": False})
                continue
            contract = build(raw, csv_root, "v2", transform_for(ov))
            hits = ad3_flagged(contract, source, ac)
            rows = rows_by_name(contract)
            excluded = sum(1 for (n, s) in ov if exclusion_of(rows.get(n), s))
            cases.append(
                {
                    "source": source,
                    "kind": kind,
                    "assetClass": ac,
                    "rows": len(ov),
                    "flagged": bool(hits),
                    "flags": hits,
                    "votesExcluded": excluded,
                    "rankingPasses": (contract.get("sourceIntegrity") or {}).get("rankingPasses"),
                }
            )
            if progress:
                progress(f"AD3 {source} {kind}: flagged={bool(hits)} ({excluded}/{len(ov)})")
    flagged = sum(1 for c in cases if c["flagged"])
    return {
        "label": GATES["AD3"]["label"],
        "boards": len(cases),
        "flagged": flagged,
        "boardsRequired": GATES["AD3"]["boardsRequired"],
        "v2Passes": flagged >= GATES["AD3"]["boardsRequired"] and len(cases) == 16,
        "cases": cases,
    }


def gate_verdicts(summary: Mapping[str, Any]) -> dict[str, bool | None]:
    """``{gate: passes}`` for the seven directive §5 gates; ``None`` = not run
    (never reported as a pass)."""
    return {g: (bool(summary[g].get("v2Passes")) if g in summary else None) for g in GATES}


def board_digest(contract: Mapping[str, Any]) -> str:
    """Content identity of a built board for the determinism check: every
    row's value, rank, dropped sources and integrity stamp."""
    rows = sorted(
        (
            str(r.get("displayName")),
            r.get("rankDerivedValue"),
            r.get("canonicalConsensusRank"),
            json.dumps(r.get("droppedSources") or [], sort_keys=True, default=str),
            json.dumps(
                {k: (m or {}).get("integrity") for k, m in (r.get("sourceRankMeta") or {}).items()},
                sort_keys=True,
                default=str,
            ),
        )
        for r in contract.get("playersArray") or []
    )
    return hashlib.sha256(json.dumps(rows, default=str).encode("utf-8")).hexdigest()


def run_all(
    raw: Mapping[str, Any],
    csv_root: Any,
    *,
    seed: int = SEED,
    max_rows: int | None = None,
    gates: Iterable[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    clean = {c: build(raw, csv_root, c) for c in CONFIGS}
    wanted = set(gates or GATES)
    cases = [c for c in plan_cases(clean, seed=seed, max_rows=max_rows) if c.gate in wanted]
    results, contamination = run_cases(raw, csv_root, clean, cases, progress=progress)
    summary: dict[str, Any] = summarize_cases(results)
    summary = {g: v for g, v in summary.items() if g in wanted}
    if "AD3" in wanted:
        summary["AD3"] = run_ad3(raw, csv_root, clean["none"], progress=progress)
    return {
        "schema": SCHEMA,
        "seed": seed,
        "variant": "NO-HISTORY",
        "pins": _flags_for("v2"),
        "thresholds": si.load_thresholds().to_stamp(),
        "cleanDigests": {c: board_digest(clean[c]) for c in CONFIGS},
        "contamination": contamination,
        "summary": summary,
        "gates": gate_verdicts(summary),
    }
