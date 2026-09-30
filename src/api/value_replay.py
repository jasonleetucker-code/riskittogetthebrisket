"""Pinned, reproducible replay of the canonical value pipeline for named assets.

Extends the existing explain surface (``src/api/source_weighting_explain.py``,
``GET /api/players/{player}/value-explain``) with what that view cannot show:

* **Pins** -- the code revision, the raw payload, every source CSV, every
  freshness-state file, the freshness config and the relevant feature flags, each
  content-hashed, so a replay states exactly which inputs produced its numbers.
* **Stage outputs** read from the row the canonical pipeline itself stamped
  (``sourceRankMeta``): per-source raw value, transformed value, path
  (value-direct vs rank->Hill), configured and applied weights, freshness,
  family adjustment, exclusion reason. Nothing is recomputed outside
  ``_compute_unified_rankings``; one blend recomputation is performed only to
  CHECK that the stamped survivors reproduce the published value.
* **Counterfactual rebuilds** of the whole board through the same pipeline with
  one controlled change (a source or family disabled, the outlier filter
  disabled, native values treated as ranks, freshness weighting off). Each is a
  separate build; deltas are sensitivities, NOT additive causal shares -- the
  stages are nonlinear, and the sum of leave-one-out deltas means nothing.

Counterfactuals that need no production seam use the documented override path
(``source_overrides``) or feature flags. Two diagnostic counterfactuals patch a
module attribute for the duration of one build (``hampel_off``,
``native_values_as_ranks``) and restore it in ``finally``; they exist only here,
never in serving, and are labelled as diagnostic.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import statistics
import subprocess
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

from src.api import data_contract as dc
from src.api import feature_flags

REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY_SCHEMA = "value-replay/v1"
_FLAGS = ("source_freshness_weighting", "source_family_cap", "te_basis_conversion")
_META_FIELDS = (
    "valueContribution",
    "valueContributionPath",
    "valueDirectFallbackReason",
    "rawRank",
    "effectiveRank",
    "percentile",
    "baseWeight",
    "freshness",
    "freshnessAgeHours",
    "dynamicWeightFactor",
    "preFamilyWeight",
    "familyAdjustment",
    "appliedWeight",
    "contributedToBlend",
    "hampelDropped",
    "excludedReason",
    "isAnchor",
    "tepBoostApplied",
)
_ROW_FIELDS = (
    "displayName",
    "position",
    "assetClass",
    "team",
    "age",
    "rookie",
    "rankDerivedValue",
    "canonicalConsensusRank",
    "confidenceBucket",
    "confidenceReasons",
    "droppedSources",
    "freshnessExcludedSources",
    "independentSourceCount",
    "sourceCount",
    "anchorValue",
    "subgroupBlendValue",
    "alphaShrinkage",
    "_blendedValueUncapped",
    "singleSourceValuePenaltyApplied",
    "quarantined",
    "anomalyFlags",
    "ktcMarket",
    "pickValueProvenance",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def pins(payload_path: Path, root: Path = REPO_ROOT) -> dict[str, Any]:
    """Content identity of every input a local build reads."""
    csv_dir = root / "CSVs" / "site_raw"
    state_dir = root / "data" / "scrape_state"
    config = root / "config" / "sources" / "freshness_v1.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    return {
        "codeRevision": _git("rev-parse", "HEAD"),
        "workingTreeDirty": bool(_git("status", "--porcelain", "--", "src", "config", "CSVs")),
        "payload": {
            "path": str(payload_path.relative_to(root))
            if payload_path.is_relative_to(root)
            else str(payload_path),
            "sha256": _sha256(payload_path),
            "scrapeTimestamp": payload.get("scrapeTimestamp") or payload.get("date"),
        },
        "sourceCsvs": {p.name: _sha256(p) for p in sorted(csv_dir.glob("*.csv"))},
        "freshnessState": {p.name: _sha256(p) for p in sorted(state_dir.glob("*_dataset.json"))},
        "freshnessConfig": _sha256(config) if config.exists() else None,
        "flags": {name: feature_flags.is_enabled(name) for name in _FLAGS},
        "contractVersion": dc.CONTRACT_VERSION,
        "hampel": {
            "k": dc._HAMPEL_K,
            "minN": dc._HAMPEL_MIN_N,
            "minThreshold": dc._HAMPEL_MIN_THRESHOLD,
        },
        "singleSourceRetention": dc._SINGLE_SOURCE_VALUE_RETENTION,
    }


def source_families() -> dict[str, str]:
    """``{source_key: correlation_group}`` from the canonical registry."""
    return {
        str(s["key"]): str(s.get("correlation_group") or s["key"])
        for s in dc._RANKING_SOURCES
        if s.get("key")
    }


@contextlib.contextmanager
def _patched(attr: str, value: Any) -> Iterator[None]:
    original = getattr(dc, attr)
    setattr(dc, attr, value)
    try:
        yield
    finally:
        setattr(dc, attr, original)


@contextlib.contextmanager
def _flag(name: str, enabled: bool) -> Iterator[None]:
    env = f"RISKIT_FEATURE_{name.upper()}"
    previous = os.environ.get(env)
    os.environ[env] = "1" if enabled else "0"
    feature_flags.reload()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = previous
        feature_flags.reload()


def _no_hampel(pairs, **_kwargs):
    return list(pairs), []


def counterfactual_specs(families: Mapping[str, str], keys: list[str]) -> dict[str, dict]:
    """Named single-change rebuilds. ``kind`` says which seam each uses."""
    specs: dict[str, dict] = {
        "hampel_off": {
            "kind": "diagnostic_patch",
            "patch": ("_hampel_filter_per_player", _no_hampel),
        },
        "native_values_as_ranks": {
            "kind": "diagnostic_patch",
            "patch": ("_VALUE_BASED_SOURCES", frozenset()),
        },
        "freshness_weighting_off": {
            "kind": "feature_flag",
            "flag": ("source_freshness_weighting", False),
        },
    }
    for key in keys:
        specs[f"leave_out_source:{key}"] = {"kind": "source_override", "disable": [key]}
    by_family: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        by_family[families.get(key, key)].append(key)
    for family, members in sorted(by_family.items()):
        if len(members) > 1:
            specs[f"leave_out_family:{family}"] = {
                "kind": "source_override",
                "disable": sorted(members),
            }
    return specs


def build(raw_payload: Mapping[str, Any], spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One canonical build, optionally under one counterfactual ``spec``."""
    spec = spec or {}
    overrides = None
    if spec.get("disable"):
        overrides = {key: {"include": False} for key in spec["disable"]}
    with contextlib.ExitStack() as stack:
        if "patch" in spec:
            stack.enter_context(_patched(*spec["patch"]))
        if "flag" in spec:
            stack.enter_context(_flag(*spec["flag"]))
        return dc.build_api_data_contract(
            json.loads(json.dumps(raw_payload)), source_overrides=overrides
        )


def _position_ranks(rows: list[dict]) -> dict[str, int]:
    ranked = sorted(
        (r for r in rows if r.get("canonicalConsensusRank")),
        key=lambda r: r["canonicalConsensusRank"],
    )
    counters: dict[str, int] = defaultdict(int)
    out = {}
    for row in ranked:
        counters[row.get("position") or "?"] += 1
        out[row.get("displayName")] = counters[row.get("position") or "?"]
    return out


def asset_view(contract: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    """Row-level stages for one asset, exactly as the pipeline stamped them."""
    rows = contract.get("playersArray") or []
    row = next((r for r in rows if r.get("displayName") == name), None)
    if row is None:
        return None
    view = {k: row.get(k) for k in _ROW_FIELDS}
    view["positionRank"] = _position_ranks(rows).get(name)
    meta = row.get("sourceRankMeta") or {}
    view["sources"] = {
        key: {
            "nativeValue": (row.get("canonicalSiteValues") or {}).get(key),
            "sourceRank": (row.get("sourceRanks") or {}).get(key),
            **{f: (meta.get(key) or {}).get(f) for f in _META_FIELDS},
        }
        for key in sorted(set(meta) | set(row.get("sourceRanks") or {}))
    }
    view["blendCheck"] = blend_check(row)
    return view


def blend_check(row: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute the blend from the stamped survivors, to CHECK the stamps.

    Only meaningful for offense rows (flat blend, no anchor shrinkage); other
    asset classes report ``not_applicable`` rather than a misleading number.
    """
    if row.get("assetClass") != "offense":
        return {"status": "not_applicable", "reason": "anchor/pick path"}
    meta = row.get("sourceRankMeta") or {}
    voters = [
        (float(m["valueContribution"]), float(m.get("appliedWeight") or 0.0))
        for m in meta.values()
        if not m.get("hampelDropped")
        and not m.get("excludedReason")
        and m.get("contributedToBlend") is not False
        and (m.get("appliedWeight") or 0) > 0
        and m.get("valueContribution") is not None
    ]
    if not voters:
        return {"status": "no_voters"}
    values = [v for v, _ in voters]
    weights = [w for _, w in voters]
    blended, _ = dc.weighted_count_aware_mean_median_blend(values, weights)
    if row.get("singleSourceValuePenaltyApplied"):
        blended *= dc._SINGLE_SOURCE_VALUE_RETENTION
    published = row.get("_blendedValueUncapped")
    return {
        "status": "reproduced"
        if published is not None and abs(int(blended) - published) <= 1
        else "mismatch",
        "recomputed": round(blended, 2),
        "published": published,
        "voters": len(voters),
    }


def _group(row: Mapping[str, Any]) -> str:
    if row.get("assetClass") == "pick":
        return "PICK"
    if row.get("assetClass") == "idp":
        return "IDP"
    return str(row.get("position") or "?")


def board_diff(
    base: Mapping[str, Any], other: Mapping[str, Any], *, top: int = 10
) -> dict[str, Any]:
    """Whole-board effect of one counterfactual, by asset group."""
    before = {r["displayName"]: r for r in base.get("playersArray") or [] if r.get("displayName")}
    after = {r["displayName"]: r for r in other.get("playersArray") or [] if r.get("displayName")}
    deltas = []
    for name, row in before.items():
        a, b = row.get("rankDerivedValue"), (after.get(name) or {}).get("rankDerivedValue")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a != b:
            deltas.append(
                (
                    name,
                    _group(row),
                    b - a,
                    row.get("canonicalConsensusRank"),
                    (after.get(name) or {}).get("canonicalConsensusRank"),
                )
            )
    by_group: dict[str, list[float]] = defaultdict(list)
    for _n, g, d, _r0, _r1 in deltas:
        by_group[g].append(abs(d))

    def stats(values: list[float]) -> dict[str, Any]:
        ordered = sorted(values)
        return {
            "changed": len(ordered),
            "medianAbs": round(statistics.median(ordered), 1),
            "p90Abs": round(ordered[int(0.9 * (len(ordered) - 1))], 1),
            "maxAbs": round(ordered[-1], 1),
        }

    top200_before = {
        n for n, r in before.items() if (r.get("canonicalConsensusRank") or 10**9) <= 200
    }
    top200_after = {
        n for n, r in after.items() if (r.get("canonicalConsensusRank") or 10**9) <= 200
    }
    return {
        "rowsCompared": len(before),
        "rowsChanged": len(deltas),
        "byGroup": {g: stats(v) for g, v in sorted(by_group.items())},
        "top200MembershipChanges": len(top200_before ^ top200_after),
        "largestMoves": [
            {"asset": n, "group": g, "delta": d, "rankBefore": r0, "rankAfter": r1}
            for n, g, d, r0, r1 in sorted(deltas, key=lambda x: -abs(x[2]))[:top]
        ],
    }


def outlier_census(contract: Mapping[str, Any]) -> dict[str, Any]:
    """How often the outlier filter removes each source, and the KTC pair."""
    per_source: dict[str, int] = defaultdict(int)
    both_ktc = []
    for row in contract.get("playersArray") or []:
        dropped = row.get("droppedSources") or []
        for key in dropped:
            per_source[key] += 1
        if {"ktcCrowdSfTep", "ktcTradesSfTep"} <= set(dropped):
            both_ktc.append(row.get("displayName"))
    return {
        "dropsBySource": dict(sorted(per_source.items(), key=lambda kv: -kv[1])),
        "rowsWithBothKtcDropped": len(both_ktc),
        "exampleRowsWithBothKtcDropped": both_ktc[:15],
    }


def native_vs_hill(base: Mapping[str, Any], as_ranks: Mapping[str, Any]) -> dict[str, Any]:
    """Value-direct sources: the native-value path vs the same observation taken
    through the source's own rank on its Hill curve (the ``native_values_as_ranks``
    rebuild stamps that value through the real pipeline -- nothing reimplemented).
    A normalized rank index and a native price scale are different products; this
    measures how far apart they sit, by the source's own rank bucket."""
    alt = {r.get("displayName"): r for r in as_ranks.get("playersArray") or []}
    out: dict[str, Any] = {}
    for key in sorted(dc._VALUE_BASED_SOURCES):
        buckets: dict[int, list[float]] = defaultdict(list)
        for row in base.get("playersArray") or []:
            meta = (row.get("sourceRankMeta") or {}).get(key) or {}
            other = ((alt.get(row.get("displayName")) or {}).get("sourceRankMeta") or {}).get(
                key
            ) or {}
            rank = meta.get("rawRank") or (row.get("sourceRanks") or {}).get(key)
            if (
                meta.get("valueContributionPath") != "value_direct"
                or other.get("valueContributionPath") != "rank_hill"
                or not rank
                or not meta.get("valueContribution")
                or not other.get("valueContribution")
            ):
                continue
            buckets[(int(rank) - 1) // 50].append(
                meta["valueContribution"] / other["valueContribution"]
            )
        out[key] = {
            f"{b * 50 + 1}-{b * 50 + 50}": {
                "n": len(v),
                "medianNativeOverHill": round(statistics.median(v), 3),
            }
            for b, v in sorted(buckets.items())
        }
    return out


def replay(
    payload_path: Path,
    assets: list[str],
    *,
    counterfactuals: list[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Pinned baseline + named counterfactual rebuilds for ``assets``."""
    raw = json.loads(payload_path.read_text(encoding="utf-8"))
    families = source_families()
    base = build(raw)
    keys = sorted(
        {k for r in base.get("playersArray") or [] for k in (r.get("sourceRankMeta") or {})}
    )
    specs = counterfactual_specs(families, keys)
    chosen = counterfactuals if counterfactuals is not None else list(specs)
    result: dict[str, Any] = {
        "schema": REPLAY_SCHEMA,
        "pins": pins(payload_path),
        "sourceFamilies": {k: families.get(k, k) for k in keys},
        "assets": {
            name: {"baseline": asset_view(base, name), "counterfactuals": {}} for name in assets
        },
        "board": {"outlierCensus": outlier_census(base)},
        "counterfactualBoard": {},
        "interpretation": (
            "Counterfactual deltas are single-change sensitivities through a nonlinear "
            "pipeline; they are not additive contribution shares."
        ),
    }
    for name in chosen:
        spec = specs[name]
        if progress:
            progress(name)
        other = build(raw, spec)
        result["counterfactualBoard"][name] = {"kind": spec["kind"], **board_diff(base, other)}
        if name == "native_values_as_ranks":
            result["board"]["nativeVsHill"] = native_vs_hill(base, other)
        for asset, entry in result["assets"].items():
            view = asset_view(other, asset)
            b = (entry["baseline"] or {}).get("rankDerivedValue")
            v = (view or {}).get("rankDerivedValue")
            entry["counterfactuals"][name] = {
                "value": v,
                "rank": (view or {}).get("canonicalConsensusRank"),
                "delta": (v - b)
                if isinstance(v, (int, float)) and isinstance(b, (int, float))
                else None,
            }
    return result
