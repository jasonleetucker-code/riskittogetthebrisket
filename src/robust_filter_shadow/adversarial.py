"""Constructed adversarial cases for the joint robust filter, on REAL rows.

Each case starts from a real filter row of a replayed board -- its real
sources, families, votes and pre-cap evidence weights -- and perturbs it into
one of the preregistered shapes (``PREREGISTRATION.md`` §7):

* **A1 trap** -- three ~3000-3200 observations at weight 0.03 vs one fresh
  4600 at 1.0, scaled to the row's own level (A1b: the whole real row stale,
  one source fresh and high).
* **A2 stale cluster vs fresh single** -- every member stale except one fresh
  disagreeing observation.
* **A3 correlated family** -- every member of one multi-member family agrees on
  a value far from the independent families.
* **A4 broken scale** -- one low-weight observation ×5 / ×0.2 (A4b: the broken
  observation is the row's dominant evidence -- the disclosed limitation).

Function-level cases call the two filters exactly as the pipeline does
(``_hampel_filter_per_player`` vs ``joint_robust_filter`` over
``cap_family_weights``). With ``full_pipeline`` two cases are also expressed in
a ``csv_root`` tree and rebuilt end to end: a broken scale on one rank source's
CSV, and a stale cluster made by ageing three sources' dataset state.
"""

from __future__ import annotations

import json
import shutil
import statistics
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.api import data_contract as dc
from src.api.joint_robust_filter import joint_robust_filter
from src.robust_filter_shadow import record as R

TRAP_RATIOS = (3000 / 3100, 1.0, 3200 / 3100)
TRAP_FRESH_RATIO = 4600 / 3100
STALE_W, TRAP_STALE_W, FRESH_W = 0.05, 0.03, 1.0
CASE_ROWS = 25


def run_filters(
    observations: Sequence[tuple[str, float]],
    weights: Mapping[str, float],
    family_of: Callable[[str], str] = dc.correlation_group_for,
) -> dict[str, Any]:
    """Both filters on one row, the challenger over family-capped weights."""
    capped, _ = dc.cap_family_weights(dict(weights))
    families = {s: family_of(s) for s, _v in observations}
    challenger = joint_robust_filter(
        list(observations),
        capped,
        families,
        k=dc._HAMPEL_K,
        min_n=dc._HAMPEL_MIN_N,
        min_threshold=dc._HAMPEL_MIN_THRESHOLD,
    )
    _kept, inc_dropped = dc._hampel_filter_per_player(list(observations))
    surviving_families = {families[s] for s in challenger.kept}
    return {
        "incumbentDropped": sorted(inc_dropped),
        "challengerDropped": sorted(challenger.dropped),
        "reasons": dict(challenger.reasons),
        "familiesPresent": len(set(families.values())),
        "familiesSurvivingChallenger": len(surviving_families),
    }


def real_rows(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Filter rows of a built board: real votes, pre-cap weights, families, rank order."""
    rows = []
    for row in contract.get("playersArray") or []:
        obs = R.voting_observations(row)
        if not R.is_filter_row(row, obs):
            continue
        meta = row.get("sourceRankMeta") or {}
        rows.append(
            {
                "name": row.get("displayName"),
                "assetClass": row.get("assetClass"),
                "rank": row.get("canonicalConsensusRank") or 10**6,
                "obs": dict(sorted(obs.items())),
                "weights": {s: R.precap_weight(meta.get(s) or {}) for s in obs},
                "families": {s: dc.correlation_group_for(s) for s in obs},
            }
        )
    rows.sort(key=lambda r: (r["rank"], str(r["name"])))
    return rows


def _distinct_family_sources(row: Mapping[str, Any]) -> list[str]:
    seen: dict[str, str] = {}
    for source in sorted(row["obs"]):
        seen.setdefault(row["families"][source], source)
    return [seen[f] for f in sorted(seen)]


def case_a1_trap(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    results = []
    for row in rows:
        picks = _distinct_family_sources(row)
        level = statistics.median(row["obs"].values())
        if len(picks) < 4 or not (2100 <= level <= 6700):
            continue
        stale, fresh = picks[:3], picks[3]
        obs = [(s, level * ratio) for s, ratio in zip(stale, TRAP_RATIOS)]
        obs.append((fresh, level * TRAP_FRESH_RATIO))
        weights = {s: TRAP_STALE_W for s in stale} | {fresh: FRESH_W}
        out = run_filters(obs, weights)
        out.update(
            row=row["name"],
            fresh=fresh,
            expected=(
                fresh not in out["challengerDropped"]
                and out["reasons"].get(fresh) == "dominant_evidence_kept"
                and out["familiesSurvivingChallenger"] >= 2
            ),
            incumbentDropsFresh=fresh in out["incumbentDropped"],
        )
        results.append(out)
        if len(results) >= CASE_ROWS:
            break
    return _tally("A1_trap", results, ("dominant_evidence_kept", "kept_to_avoid_single_family"))


def case_a1b_trap_full_row(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    results = []
    for row in rows:
        level = statistics.median(row["obs"].values())
        if len(set(row["families"].values())) < 3 or not (2100 <= level <= 6700):
            continue
        fresh = sorted(row["obs"])[0]
        obs = [(s, v) for s, v in row["obs"].items() if s != fresh]
        obs.append((fresh, min(9999.0, level * TRAP_FRESH_RATIO)))
        weights = {s: TRAP_STALE_W for s in row["obs"]} | {fresh: FRESH_W}
        out = run_filters(obs, weights)
        out.update(
            row=row["name"],
            fresh=fresh,
            expected=fresh not in out["challengerDropped"]
            and out["familiesSurvivingChallenger"] >= 2,
            incumbentDropsFresh=fresh in out["incumbentDropped"],
        )
        results.append(out)
        if len(results) >= CASE_ROWS:
            break
    return _tally(
        "A1b_trap_full_row", results, ("dominant_evidence_kept", "kept_to_avoid_single_family")
    )


def case_a2_stale_cluster(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    results = []
    for row in rows:
        if len(row["obs"]) < 5 or len(set(row["families"].values())) < 4:
            continue
        level = statistics.median(row["obs"].values())
        fresh = sorted(row["obs"])[-1]
        obs = [(s, v) for s, v in row["obs"].items() if s != fresh] + [(fresh, level * 0.6)]
        weights = {s: STALE_W for s in row["obs"]} | {fresh: FRESH_W}
        out = run_filters(obs, weights)
        out.update(
            row=row["name"],
            fresh=fresh,
            expected=fresh not in out["challengerDropped"]
            and out["familiesSurvivingChallenger"] >= 2,
            incumbentDropsFresh=fresh in out["incumbentDropped"],
        )
        results.append(out)
        if len(results) >= CASE_ROWS:
            break
    return _tally(
        "A2_stale_cluster_vs_fresh_single",
        results,
        ("dominant_evidence_kept", "kept_to_avoid_single_family"),
    )


def case_a3_correlated_family(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    results = []
    for row in rows:
        members_by_family: dict[str, list[str]] = {}
        for s, fam in row["families"].items():
            members_by_family.setdefault(fam, []).append(s)
        multi = sorted(f for f, ms in members_by_family.items() if len(ms) >= 2)
        if not multi:
            continue
        family = multi[0]
        others = sorted(f for f in members_by_family if f != family)
        if len(others) < 2:
            continue
        # Keep exactly two independent families, so the correlated members are
        # a raw-count majority the incumbent's unweighted median can side with.
        keep_independent = [members_by_family[f][0] for f in others[:2]]
        indep_level = statistics.median(row["obs"][s] for s in keep_independent)
        members = sorted(members_by_family[family])
        obs = [(s, row["obs"][s]) for s in keep_independent]
        obs += [(s, min(9999.0, indep_level * 1.6)) for s in members]
        if len(obs) < dc._HAMPEL_MIN_N:
            continue
        weights = {s: 1.0 for s, _v in obs}
        out = run_filters(obs, weights)
        out.update(
            row=row["name"],
            family=family,
            members=members,
            expected=not set(keep_independent) & set(out["challengerDropped"]),
            incumbentDropsIndependent=bool(set(keep_independent) & set(out["incumbentDropped"])),
            challengerDropsCluster=set(members) <= set(out["challengerDropped"]),
        )
        results.append(out)
        if len(results) >= CASE_ROWS:
            break
    return _tally(
        "A3_correlated_family_members",
        results,
        ("dominant_evidence_kept", "kept_to_avoid_single_family"),
    )


def case_a4_broken_scale(rows: Sequence[Mapping[str, Any]], factor: float) -> dict[str, Any]:
    results = []
    for row in rows:
        total = sum(row["weights"].values()) or 1.0
        candidates = sorted(
            (s for s in row["obs"] if row["weights"][s] / total < 0.5),
            key=lambda s: (row["weights"][s], s),
        )
        if not candidates or len(set(row["families"].values())) < 3:
            continue
        broken = candidates[0]
        obs = [(s, v) for s, v in row["obs"].items() if s != broken]
        obs.append((broken, max(1.0, min(9999.0, row["obs"][broken] * factor))))
        out = run_filters(obs, row["weights"])
        out.update(
            row=row["name"],
            broken=broken,
            expected=broken in out["challengerDropped"],
            incumbentDropsBroken=broken in out["incumbentDropped"],
        )
        results.append(out)
        if len(results) >= CASE_ROWS:
            break
    return _tally(
        f"A4_broken_scale_x{factor:g}",
        results,
        ("dominant_evidence_kept", "kept_to_avoid_single_family"),
    )


def case_a4b_dominant_broken(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The disclosed limitation: dominant evidence is kept even when broken."""
    results = []
    for row in rows:
        if len(set(row["families"].values())) < 3:
            continue
        broken = sorted(row["obs"])[0]
        obs = [(s, v) for s, v in row["obs"].items() if s != broken]
        obs.append((broken, max(1.0, min(9999.0, row["obs"][broken] * 5))))
        weights = {s: STALE_W for s in row["obs"]} | {broken: FRESH_W}
        out = run_filters(obs, weights)
        out.update(
            row=row["name"],
            broken=broken,
            # Expected (by design, a limitation): the challenger KEEPS it.
            expected=broken not in out["challengerDropped"],
            incumbentDropsBroken=broken in out["incumbentDropped"],
        )
        results.append(out)
        if len(results) >= CASE_ROWS:
            break
    return _tally(
        "A4b_dominant_broken_kept_limitation",
        results,
        ("dominant_evidence_kept", "kept_to_avoid_single_family"),
    )


def _tally(name: str, results: list[dict[str, Any]], reasons: Sequence[str]) -> dict[str, Any]:
    fired: Counter[str] = Counter()
    for out in results:
        fired.update(r for r in out["reasons"].values() if r in reasons)
    flags = Counter()
    for out in results:
        for key, value in out.items():
            if key.startswith(("incumbentDrops", "challengerDrops")) and isinstance(value, bool):
                flags[key] += value
    return {
        "case": name,
        "rows": len(results),
        "expectedHeld": sum(1 for out in results if out["expected"]),
        "safeguardsFired": {r: fired.get(r, 0) for r in reasons},
        "descriptive": dict(flags),
        "examples": results[:3],
        "failures": [out for out in results if not out["expected"]][:5],
    }


# ── full pipeline ───────────────────────────────────────────────────────


def _copy_tree(root: Path) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory(prefix="jfs-advfp-")
    shutil.copytree(root, tmp.name, dirs_exist_ok=True)
    return tmp


def _scale_rank_csv(path: Path, factor: float, top: int) -> int:
    import csv  # noqa: PLC0415

    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        rows = list(reader)
    rank_col = next(c for c in fields if c.lower() == "rank")
    ranked = sorted(
        (r for r in rows if (r.get(rank_col) or "").strip()), key=lambda r: float(r[rank_col])
    )
    changed = 0
    for r in ranked[:top]:
        r[rank_col] = f"{max(1.0, float(r[rank_col]) * factor):.2f}"
        changed += 1
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return changed


def _age_state(path: Path, cutoff: datetime) -> bool:
    from src.sources.dataset_state import parse_iso, utc_iso  # noqa: PLC0415

    if not path.exists():
        return False
    state = json.loads(path.read_text(encoding="utf-8"))
    for subset in (state.get("subsets") or {}).values():
        history = [
            e
            for e in subset.get("changeHistory") or []
            if (parse_iso(e.get("at")) or cutoff) <= cutoff
        ]
        subset["changeHistory"] = history
        broad = [parse_iso(e["at"]) for e in history if e.get("broad")]
        anyt = [parse_iso(e["at"]) for e in history]
        first = parse_iso(subset.get("firstObservedAt"))
        subset["lastBroadDatasetChangeAt"] = (
            utc_iso(max(broad)) if broad else (utc_iso(first) if first else None)
        )
        subset["lastAnyMeaningfulChangeAt"] = (
            utc_iso(max(anyt)) if anyt else subset["lastBroadDatasetChangeAt"]
        )
        subset["rowChangedAt"] = {}
    path.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    return True


def _pipeline_tally(
    name: str, base_inc: Mapping, inc: Mapping, ch: Mapping, focus: set[str]
) -> dict[str, Any]:
    comparison = R.shadow_record(inc, ch)
    base_votes = {
        str(r.get("displayName")): R.voting_observations(r)
        for r in base_inc.get("playersArray") or []
    }
    inc_rows = {str(r.get("displayName")): r for r in inc.get("playersArray") or []}
    ch_rows = {str(r.get("displayName")): r for r in ch.get("playersArray") or []}
    affected: Counter[str] = Counter()
    freshness = []
    for name, row in inc_rows.items():
        votes = R.voting_observations(row)
        if not R.is_filter_row(row, votes):
            continue
        ch_dropped = set((ch_rows.get(name) or {}).get("droppedSources") or [])
        reasons = (ch_rows.get(name) or {}).get("jointFilterReasons") or {}
        for source in focus & set(votes):
            meta = (row.get("sourceRankMeta") or {}).get(source) or {}
            if meta.get("freshness") is not None:
                freshness.append(float(meta["freshness"]))
            # "perturbed" = the vote differs from the unperturbed board's vote.
            prefix = (
                "perturbed"
                if base_votes.get(name, {}).get(source) != votes[source]
                else "unchanged"
            )
            affected[f"{prefix}Observations"] += 1
            affected[f"{prefix}IncumbentDropped"] += source in set(row.get("droppedSources") or [])
            affected[f"{prefix}ChallengerDropped"] += source in ch_dropped
            if reasons.get(source) in R.SAFEGUARD_REASONS:
                affected[f"{prefix}ChallengerKept:{reasons[source]}"] += 1
    return {
        "case": name,
        "focusSources": sorted(focus),
        "focusObservations": dict(affected),
        "focusFreshnessMedian": round(statistics.median(freshness), 4) if freshness else None,
        "counts": comparison["counts"],
        "safeguardsFired": comparison["safeguardsFired"],
    }


def full_pipeline_cases(
    raw: Mapping[str, Any], root: Path, base_inc: Mapping[str, Any]
) -> list[dict[str, Any]]:
    results = []
    as_of = dc._payload_as_of(raw)
    # FP-A4: a broken scale on one rank source (ranks ×5 and ×0.2 for its top 60).
    for factor in (5.0, 0.2):
        tmp = _copy_tree(root)
        try:
            tree = Path(tmp.name)
            changed = _scale_rank_csv(tree / "CSVs" / "site_raw" / "dlfSf.csv", factor, 60)
            inc, ch = R.build_pair(raw, tree)
            out = _pipeline_tally(f"FP_A4_dlfSf_ranks_x{factor:g}", base_inc, inc, ch, {"dlfSf"})
            out["csvRowsChanged"] = changed
            results.append(out)
        finally:
            tmp.cleanup()
    # FP-A2: three independent rank sources made stale (state aged 40 days).
    stale = {"fantasyCalc", "dynastyDaddySf", "pfkDynasty"}
    tmp = _copy_tree(root)
    try:
        tree = Path(tmp.name)
        from src.sources.dataset_state import state_path  # noqa: PLC0415

        aged = [
            s
            for s in sorted(stale)
            if as_of is not None
            and _age_state(
                state_path(tree / "data" / "scrape_state", s), as_of - timedelta(days=40)
            )
        ]
        inc, ch = R.build_pair(raw, tree)
        out = _pipeline_tally("FP_A2_three_sources_stale_40d", base_inc, inc, ch, set(aged))
        out["agedSources"] = aged
        results.append(out)
    finally:
        tmp.cleanup()
    return results


def run_all(raw: Mapping[str, Any], root: Path, *, full_pipeline: bool = False) -> dict[str, Any]:
    base_inc, base_ch = R.build_pair(raw, root)
    rows = real_rows(base_inc)
    cases = [
        case_a1_trap(rows),
        case_a1b_trap_full_row(rows),
        case_a2_stale_cluster(rows),
        case_a3_correlated_family(rows),
        case_a4_broken_scale(rows, 5.0),
        case_a4_broken_scale(rows, 0.2),
        case_a4b_dominant_broken(rows),
    ]
    result: dict[str, Any] = {
        "schema": f"{R.SCHEMA}/adversarial",
        "baseline": {
            "filterRows": len(rows),
            "safeguardsFiredOnRealBoard": R.shadow_record(base_inc, base_ch)["safeguardsFired"],
        },
        "functionLevel": cases,
        "allExpected": all(c["rows"] > 0 and c["expectedHeld"] == c["rows"] for c in cases),
    }
    if full_pipeline:
        result["fullPipeline"] = full_pipeline_cases(raw, root, base_inc)
    return result
